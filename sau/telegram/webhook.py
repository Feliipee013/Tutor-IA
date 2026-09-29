"""Handler do webhook do Telegram do S.A.U.

Recebe o update do Telegram, registra o update bruto para depuração e entrega ao
Aluno um acuse de recibo fixo, ainda antes de qualquer inferência. É a primeira
metade do que o ADR-0001 exige: confirmar o recebimento imediatamente é
requisito, não polimento. A segunda metade — a posição na fila de espera — é do
ticket de concorrência (#11).

Desde a #8 o turno acontece aqui: o acuse sai primeiro, o grafo roda depois, fora
do request, e a resposta do modelo volta ao Aluno em uma segunda mensagem. O
serviço `webhook` é quem roda o grafo, e isso é uma emenda ao ADR-0002, não uma
decisão nova — o modelo continua no host e continua fora do container.

A thread por turno é provisória e é o que a #11 substitui por fila e semáforo.
Ela existe para que o Aluno não espere o modelo dentro do request, que é a
promessa do acuse: ele levou o primeiro retorno antes de qualquer inferência.
"""

from __future__ import annotations

import logging
import secrets
import sys
import threading
import time
from typing import Any, Callable

import httpx
from flask import Flask, Response, jsonify, request

from sau.config import Configuracao, carregar_configuracao
from sau.graph.graph import executar_turno
from sau.inference.ollama import ClienteOllama, ErroDeInferencia

logger = logging.getLogger(__name__)

TEXTO_ACK = "Recebi sua mensagem. Vou te responder em instantes."
"""O acuse de recibo, fixo e sem o modelo, e a primeira das duas mensagens que o
Aluno leva. O texto não promete posição na fila porque a #11 é dona dela; o que
ele promete é que a mensagem chegou e que alguém respondeu. A resposta do modelo
é a segunda mensagem, e sai depois desta."""

TEXTO_FALHA = (
    "Tive um problema para responder sua mensagem agora. Tente novamente em instantes."
)
"""O que o Aluno recebe quando o turno falha. Amigável de propósito: o
`ErroDeInferencia` que subiu do modelo tem "FALHA CRÍTICA" e a URL do Ollama
escritos, e esse texto é para o Aluno ler, não para quem depura. O motivo vai
inteiro para o log do turno, e a exceção nunca chega até aqui — quem vê stack
trace é o operador, no `stderr` do serviço, e o Aluno leva esta frase."""

CABECALHO_SECRET_TOKEN = "X-Telegram-Bot-Api-Secret-Token"
"""Header que o Telegram anexa a toda entrega quando o `setWebhook` foi feito com
`secret_token`. A porta do webhook é pública pelo túnel de desenvolvimento, e sem
esta conferência qualquer POST na URL vira mensagem do S.A.U. para o `chat_id` que
a pessoa mandar no corpo."""

TIMEOUT_ENVIO_SEGUNDOS = 5.0
"""Teto de qualquer envio ao Telegram, do acuse e da resposta do modelo. O update
já é do Aluno e ele não pode ficar esperando por uma chamada de saída; o ADR-0001
pede confirmação imediata, e um envio sem teto transforma o webhook numa
espera."""

RespostaWebhook = Response | tuple[Response, int]


class CredencialTelegramAusenteError(RuntimeError):
    """Falta uma credencial que o serviço do webhook não sobe sem.

    Diferente de `ValueError` do `carregar_configuracao`, que é erro de escrita
    da configuração. Aqui a configuração está bem formada e o que falta é o
    serviço decidir não funcionar sem a credencial.
    """


def exigir_credenciais(config: Configuracao) -> None:
    """Falha alto se faltar a credencial que o canal do Telegram não funciona sem.

    As duas ausentes são o mesmo defeito com nomes diferentes: sem elas o S.A.U.
    não existe do lado do Telegram. Falha alta e não aviso, pelo mesmo motivo da
    checagem de pré-requisito do ADR-0002 — um endpoint que sobe e não acuse nada
    é pior do que um serviço que não sobe.
    """
    ausentes: list[str] = []

    if config.telegram_bot_token is None:
        ausentes.append(
            "TELEGRAM_BOT_TOKEN: a credencial que o @BotFather entrega para o S.A.U.\n"
            "  Fale com o @BotFather no Telegram, use /newbot para criar o S.A.U. e\n"
            "  cole o token que ele devolve. É esse token que faz o Aluno achar o\n"
            "  S.A.U. pelo @username e é com ele que o serviço chama o Telegram."
        )

    if config.telegram_webhook_secret_token is None:
        ausentes.append(
            "TELEGRAM_WEBHOOK_SECRET_TOKEN: a chave que o Telegram devolve no header\n"
            "  X-Telegram-Bot-Api-Secret-Token, e que fecha a porta do endpoint — que é\n"
            "  público pelo túnel de desenvolvimento. Gere uma com:\n"
            "    openssl rand -hex 16\n"
            "  O Telegram só aceita de A-Z, a-z, 0-9, _ e -, até 256 caracteres."
        )

    if ausentes:
        raise CredencialTelegramAusenteError("\n".join(ausentes))


def _extrair_chat_id(update: dict[str, Any]) -> int | None:
    """Descobre o chat do Aluno no update, ou None quando ele não é uma mensagem.

    Update sem `message` é rotina — edição, reação, entrada em grupo, ação em
    teclado. Não é erro, e não tem Aluno a acusejar.
    """
    mensagem = update.get("message")
    if not isinstance(mensagem, dict):
        return None

    chat = mensagem.get("chat")
    if not isinstance(chat, dict):
        return None

    chat_id = chat.get("id")
    # bool é subclasse de int em Python, e um id de chat verdadeiro não existe.
    if isinstance(chat_id, bool) or not isinstance(chat_id, int):
        return None

    return chat_id


def _extrair_texto(update: dict[str, Any]) -> str | None:
    """Descobre o texto que o Aluno mandou, ou None quando ele não mandou texto.

    Ausência de texto é rotina, e não erro: foto, áudio, figurinha e comando de
    teclado chegam todos como update com mensagem e sem `text`. Nenhuma deles
    entra no turno — o grafo da #8 recebe mensagem escrita, e um turno sobre um
    comando de teclado seria inventar a pergunta do Aluno. O acuse sai do mesmo
    jeito, porque o que o Aluno precisa é saber que a mensagem chegou.

    A legenda da foto também fica de fora, e isso é uma escolha de comportamento,
    não de parsing. A legenda é texto escrito pela Aluna, mas vai no campo
    `caption`, e se um dia ela passar a contar como pergunta, essa é uma regra do
    S.A.U. — pertence à #10, junto com a persona, e não a este filtro. O que o
    filtro garante é o mínimo: o grafo nunca recebe um prompt inventado a partir
    de algo que ninguém perguntou.
    """
    mensagem = update.get("message")
    if not isinstance(mensagem, dict):
        return None

    texto = mensagem.get("text")
    if not isinstance(texto, str):
        return None

    return texto.strip() or None


def enviar_mensagem(
    config: Configuracao,
    chat_id: int,
    texto: str,
    client: httpx.Client | None = None,
) -> None:
    """Entrega um texto ao Aluno. O acuse é o primeiro deles, não o único.

    Falha do Telegram não vira status não-2xx de volta para o webhook: o Telegram
    reentrega o update quando o status difere de 2xx, e o Aluno levaria um
    segundo acuse da mesma mensagem. O update já foi consumido no caminho feliz,
    então a falha é registrada e a entrega segue — o retrabalho é da #11, que é
    quem tem a fila para repetir.
    """
    token = config.telegram_bot_token
    if token is None:
        # Só alcançável se o app for montado sem passar por `main`, que é quem
        # exige a credencial. Não engolir: sem token não há acuse nem resposta, e
        # nenhuma das duas mensagens do turno chega ao Aluno.
        logger.error(
            "TELEGRAM_BOT_TOKEN ausente: a mensagem não pode ser enviada ao Aluno %s.",
            chat_id,
        )
        return

    url = f"{config.telegram_api_base.rstrip('/')}/bot{token}/sendMessage"

    def postar(cliente: httpx.Client) -> None:
        resposta = cliente.post(url, json={"chat_id": chat_id, "text": texto})
        if resposta.status_code != 200:
            logger.error(
                "O Telegram recusou a mensagem do Aluno %s: status %d, corpo %s",
                chat_id,
                resposta.status_code,
                resposta.text,
            )
            return
        logger.info("Mensagem enviada ao Aluno %s.", chat_id)

    try:
        if client is not None:
            postar(client)
        else:
            with httpx.Client(timeout=TIMEOUT_ENVIO_SEGUNDOS) as cliente_proprio:
                postar(cliente_proprio)
    except httpx.HTTPError as err:
        logger.error(
            "Falha de rede ao enviar uma mensagem para o Aluno %s: %s. "
            "O update segue consumido, para o Aluno não levar a mensagem duas vezes.",
            chat_id,
            err,
        )


ExecutorTurno = Callable[[Configuracao, int, str, "httpx.Client | None"], None]
"""O que roda um turno: recebe a configuração, o chat do Aluno e a mensagem dele,
e é responsável por entregar a resposta — ou a mensagem de falha. É injetável
porque o turno é o passo que o teste precisa controlar, e um `threading.Thread`
de verdade é o que torna isso impossível de afirmar."""


def _agendar(acao: Callable[[], None]) -> None:
    """Roda `acao` em uma thread, fora do request.

    Thread e não fila é escolha provisória da #8, e o motivo é o mesmo da #11:
    o acuse já saiu, o Telegram já recebeu o 2xx, e o que sobrou para esperar é
    o modelo. A thread entrega isso hoje sem o estado que a fila exige.

    Daemon de propósito: uma thread presa no timeout do modelo não pode segurar
    o processo do container na hora do `docker compose down`.
    """
    threading.Thread(target=acao, daemon=True).start()


def _processar_turno(
    config: Configuracao,
    chat_id: int,
    texto: str,
    client: httpx.Client | None = None,
) -> None:
    """Roda o grafo do turno e entrega ao Aluno a resposta, ou a mensagem de falha.

    O `ClienteOllama` é montado aqui, com o `OLLAMA_TIMEOUT` da configuração: o
    `webhook` não roda a checagem de pré-requisito do `bot` (ADR-0002), e essa é
    a diferença de propósito entre os dois serviços. Lá, Ollama fora é falha alta
    na subida, porque o serviço inteiro é inferência. Aqui o serviço é o canal do
    Telegram, e ele tem que continuar no ar para acusejar Aluno mesmo com o modelo
    fora — o que ele faz, com `TEXTO_FALHA`.

    A falha do modelo vira mensagem para o Aluno e registro no log. Ela não sobe:
    quem chamou isto é uma thread, e uma exceção que sai de uma thread morre com
    a thread, sem log e sem o Aluno saber que o turno nem aconteceu.

    O `except` é largo, e é largo de propósito. `ErroDeInferencia` é o caminho
    previsto — o `ClienteOllama` transforma timeout, conexão, HTTP e JSON inválido
    nela — mas o grafo também pode estourar: um `KeyError` de estado faltando, um
    `AttributeError` de cliente trocado. Quem está do outro lado é uma thread sem
    ninguém esperando, então qualquer exceção que escape daqui é um turno que
    simplesmente nunca aconteceu, sem uma linha no log para o operador procurar.
    O `Exception` largo é o ponto, e o motivo técnico fica inteiro no log, onde
    quem opera o serviço o encontra. O Aluno recebe a mesma frase, porque para ele
    é a mesma coisa: não houve resposta.
    """
    cliente = ClienteOllama(
        config.ollama_base_url,
        config.ollama_model,
        timeout=config.ollama_timeout,
    )
    inicio = time.perf_counter()
    try:
        entrega = executar_turno(cliente, texto)
    except ErroDeInferencia as err:
        # `TempoEsgotadoError` é subclasse: o timeout cai aqui com o motivo certo
        # no log e a mesma frase para o Aluno.
        logger.error("O turno do Aluno %s falhou: %s", chat_id, err)
        entrega, desfecho = TEXTO_FALHA, "falha do modelo"
    except Exception:
        logger.exception("O turno do Aluno %s falhou por um erro que não é do modelo.", chat_id)
        entrega, desfecho = TEXTO_FALHA, "erro inesperado"
    else:
        if entrega.strip():
            desfecho = "resposta do modelo"
        else:
            # Resposta vazia não é erro do `ClienteOllama`: ele entrega o que veio,
            # e o Ollama devolve `response: ""` com `done: true` quando o modelo
            # para sem escrever nada. Mandar esse vazio ao Telegram é pior do que
            # falhar — o `sendMessage` é recusado com 400 e o Aluno fica com o
            # acuse e nenhum sinal do motivo. A mesma frase cobre os três jeitos
            # de não responder.
            logger.error("O turno do Aluno %s voltou do modelo sem texto nenhum.", chat_id)
            entrega, desfecho = TEXTO_FALHA, "resposta vazia"

    # Uma entrega só, e uma linha só: os três jeitos de não responder convergem
    # para a `TEXTO_FALHA` antes de sair daqui, e o que difere entre eles — o
    # motivo técnico — já ficou no log, onde quem opera o serviço o encontra.
    enviar_mensagem(config, chat_id, entrega, client)
    # O tempo do turno inteiro, do começo à entrega. É o número do critério "a
    # resposta chega em tempo aceitável para alguém acordado às 2h da manhã", e
    # ele é o do turno: o `ClienteOllama` já registra o `total` da geração, que é
    # só uma parte disso. O número medido da máquina está em
    # `docs/tempo-primeira-resposta.md`; este é o que se vê turno a turno.
    logger.info(
        "Turno do Aluno %s entregue em %.2fs (%s).",
        chat_id,
        time.perf_counter() - inicio,
        desfecho,
    )


def _atender_webhook(
    config: Configuracao,
    client: httpx.Client | None,
    executor: ExecutorTurno,
    agendar: Callable[[Callable[[], None]], None],
) -> RespostaWebhook:
    """Valida a origem, registra o update bruto e acuseja o Aluno."""
    segredo_esperado = config.telegram_webhook_secret_token
    if segredo_esperado is not None:
        segredo_recebido = request.headers.get(CABECALHO_SECRET_TOKEN, "")
        # compare_digest em bytes: a comparação é de tempo constante, e o
        # cabeçalho é entrada de quem está na internet aberta.
        if not secrets.compare_digest(segredo_recebido.encode(), segredo_esperado.encode()):
            logger.warning(
                "POST em /webhook recusado: header %s ausente ou divergente.",
                CABECALHO_SECRET_TOKEN,
            )
            return jsonify({"status": "erro", "motivo": "token inválido"}), 403

    corpo_bruto = request.get_data(as_text=True)
    corpo = request.get_json(silent=True)
    if not isinstance(corpo, dict):
        logger.warning(
            "Payload que não é um objeto JSON recebido em /webhook: %r",
            corpo_bruto[:200],
        )
        return jsonify({"status": "erro", "motivo": "payload inválido"}), 400

    update: dict[str, Any] = corpo

    # O update bruto: o corpo como o Telegram o enviou, em JSON. Logar o dict já
    # parseado perderia a forma original — aspas simples, `True` em vez de
    # `true` — e é a forma original que serve quando o payload é o suspeito.
    logger.info("update_telegram bruto: %s", corpo_bruto)

    chat_id = _extrair_chat_id(update)
    if chat_id is None:
        # 2xx de propósito: o Telegram tentou entregar algo que não é mensagem,
        # e devolver erro faria ele reentregar o mesmo update para sempre.
        logger.info(
            "Update sem mensagem do Aluno, nada a acusejar. Chaves recebidas: %s",
            sorted(update),
        )
        return jsonify({"status": "ok"}), 200

    # O acuse sai antes de qualquer inferência. O turno começa depois deste
    # ponto, e fora do request: o Telegram já levou o 2xx quando o modelo ainda
    # está pensando.
    enviar_mensagem(config, chat_id, TEXTO_ACK, client)

    texto = _extrair_texto(update)
    if texto is None:
        # Foto, áudio, comando de teclado: o Aluno foi acusejado e não há
        # pergunta para o grafo. Registrado porque um update sem texto é a forma
        # que o canal tem de dizer que entrou algo que este grafo não atende.
        logger.info(
            "Update do Aluno %s sem texto: acusejado, e sem turno. Chaves da mensagem: %s",
            chat_id,
            sorted(update["message"]) if isinstance(update.get("message"), dict) else [],
        )
        return jsonify({"status": "ok"}), 200

    def iniciar() -> None:
        executor(config, chat_id, texto, client)

    agendar(iniciar)
    return jsonify({"status": "ok"}), 200


def criar_app(
    config: Configuracao,
    client: httpx.Client | None = None,
    executor: ExecutorTurno | None = None,
    agendar: Callable[[Callable[[], None]], None] | None = None,
) -> Flask:
    """Monta o app do webhook em torno de uma `Configuracao`.

    Nada é lido do ambiente na importação: quem monta o app decide qual
    configuração ele serve, e o teste monta com a dele.

    O parâmetro se chama `executor` e não `executar_turno` de propósito: há uma
    função com esse nome no módulo, a que de fato roda o grafo, e um parâmetro
    homônimo a esconderia dentro desta função. Os dois nomes dizem coisas
    diferentes — `executor` é o callable injetado, `executar_turno` é a função
    que chama o modelo — e a armadilha éara o bastante para o nome não ser o mesmo.

    `executor` e `agendar` existem para o teste afirmar duas coisas que com a
    thread real não são afirmáveis: que o turno começa depois do acuse, e que o
    turno acontece. Com a thread de verdade, o turno pode rodar depois do fim do
    teste, ou nunca rodar, e a suíte passaria sem provar nada. Os dois padrões
    são o de serviço; só a substituição é do teste.
    """
    rodar_turno = executor or _processar_turno
    disparar = agendar or _agendar
    app = Flask(__name__)

    @app.post("/webhook")
    def webhook() -> RespostaWebhook:
        return _atender_webhook(config, client, rodar_turno, disparar)

    return app


def main() -> None:
    """Sobe o servidor do webhook do Telegram."""
    # `configurar_logging` mora no entrypoint do serviço do bot porque foi ele
    # que subiu primeiro. O log é o mesmo sistema: dois formatos diferentes
    # fariam o operador procurar a mesma informação em dois lugares. Importado
    # aqui, dentro da função, para o módulo do webhook não depender do
    # entrypoint do outro serviço no import.
    from sau.main import configurar_logging

    configurar_logging()

    try:
        config = carregar_configuracao()
    except ValueError as err:
        logger.critical("\n%s\n[ABORTANDO] Configuração inválida:\n%s\n%s", "!" * 60, err, "!" * 60)
        sys.exit(1)

    # Reaplica com o nível que a própria configuração pediu.
    configurar_logging(config.log_level)

    try:
        exigir_credenciais(config)
    except CredencialTelegramAusenteError as err:
        logger.critical(
            "\n%s\n[ABORTANDO] Credencial do Telegram ausente:\n%s\n%s",
            "!" * 60,
            err,
            "!" * 60,
        )
        sys.exit(1)

    logger.info("=" * 60)
    logger.info("S.A.U. - webhook do Telegram")
    logger.info("Endpoint: POST /webhook na porta %d", config.telegram_webhook_port)
    logger.info("Modelo do turno: %s em %s", config.ollama_model, config.ollama_base_url)
    logger.info(
        "URL pública do túnel: registre com setWebhook antes de usar. "
        "O Telegram só entrega em 443, 80, 88 e 8443, então o túnel precisa ser HTTPS."
    )
    logger.info("=" * 60)

    # 0.0.0.0 porque o serviço roda em container, e é o bind que o torna
    # alcançável de fora da máquina que o do compose.
    criar_app(config).run(host="0.0.0.0", port=config.telegram_webhook_port)
