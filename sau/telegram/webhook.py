"""Handler do webhook do Telegram do S.A.U.

Recebe o update do Telegram, registra o update bruto para depuração e entrega ao
Aluno um acuse de recibo fixo, ainda antes de qualquer inferência. É a primeira
metade do que o ADR-0001 exige: confirmar o recebimento imediatamente é
requisito, não polimento. A segunda metade — a posição na fila de espera — é da
#11, e ela mora aqui porque é uma mensagem para o Aluno: `texto_posicao_na_fila`.

Desde a #8 o turno acontece aqui: o acuse sai primeiro, o grafo roda depois, fora
do request, e a resposta do modelo volta ao Aluno em uma segunda mensagem. O
serviço `webhook` é quem roda o grafo, e isso é uma emenda ao ADR-0002, não uma
decisão nova — o modelo continua no host e continua fora do container.

Desde a #11 o grafo roda dentro de um semáforo com `k` vagas, e o turno que não
consegue vaga não desaparece: ou o Aluno recebe a posição e a estimativa, ou,
acima do teto da fila, recebe a recusa educada. São as duas metades do backpressure
que o ADR-0001 chama de "comunicado, não escondido".

**A thread por turno continua, e o texto desta verdade mudou.** Antes ela era
provisória e a #11 a substituiria; a #11 substituiu a thread como mecanismo de
**escassez**, não como mecanismo de tira-fora-do-request. Ela segue existindo
porque é ela que tira o turno de dentro do request, que é a promessa do acuse: o
Aluno levou o primeiro retorno antes de qualquer inferência. O que a #11
descartou foi o worker dedicado *por Aluno*, e continua descartado.
"""

from __future__ import annotations

import logging
import math
import secrets
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

import httpx
from flask import Flask, Response, jsonify, request

from sau.config import Configuracao, carregar_configuracao
from sau.graph.graph import executar_turno
from sau.graph.state import RegistroDeConversas
from sau.inference.ollama import ClienteOllama, ErroDeInferencia
from sau.inference.semaphore import FilaCheiaError, PosicaoNaFila, SemaforoDeInferencia
from sau.manual.indice import carregar_ou_indexar
from sau.rag.embed import ClienteEmbedding

logger = logging.getLogger(__name__)

TEXTO_ACK = "Recebi sua mensagem. Vou te responder em instantes."
"""O acuse de recibo, fixo e sem o modelo, e a primeira das duas mensagens que o
Aluno leva. O texto não promete posição na fila porque a #11 é dona dela; o que
ele promete é que a mensagem chegou e que alguém respondeu. A resposta do modelo
é a segunda mensagem, e sai depois desta.

Desde a #11 existe uma terceira mensagem possível entre o acuse e a resposta: a
de posição na fila. Ela não substitui o acuse nem a resposta, e é a que transforma
o silêncio em espera — ver `texto_posicao_na_fila`."""

TEXTO_FALHA = (
    "Tive um problema para responder sua mensagem agora. Tente novamente em instantes."
)
"""O que o Aluno recebe quando o turno falha. Amigável de propósito: o
`ErroDeInferencia` que subiu do modelo tem "FALHA CRÍTICA" e a URL do Ollama
escritos, e esse texto é para o Aluno ler, não para quem depura. O motivo vai
inteiro para o log do turno, e a exceção nunca chega até aqui — quem vê stack
trace é o operador, no `stderr` do serviço, e o Aluno leva esta frase."""

TEXTO_FILA_CHEIA = (
    "Muitos alunos estão me perguntando ao mesmo tempo e a fila de espera está cheia. "
    "Tente sua pergunta de novo daqui a pouco."
)
"""O que o Aluno recebe quando o semáforo recusa o turno, acima do teto da fila.

Educado e curto de propósito, e por duas razões que a #9 e a #11 deixaram claras. A
primeira é que o Aluno é alguém acordado às duas da manhã pedindo ajuda, e recusa
seca é o que faz ele achar que o S.A.U. quebrou. A segunda é que a recusa **entra
no histórico** como resposta da conversa: o histórico não pode divergir do que o
Aluno leu, e foi essa a invariante que a `TEXTO_FALHA` fixou para a falha.

A frase não promete prazo nem "tente mais tarde" com horário: o que ela promete é
o que o serviço pode cumprir — que a próxima tentativa entra numa fila nova. E não
cita número nenhum, porque quem recusa é a válvula: a fila pode estar cheia por um
motivo que o Aluno não tem como agir sobre ele.

Ela também não pode se fundir com a `TEXTO_FALHA`. A falha diz que algo quebrou e
convida a tentar; a recusa diz que a fila encheu e que o momento é o problema, não o
S.A.U. São diagnósticos diferentes para o Aluno e para o log.

O efeito colateral conhecido: o Aluno já leu o `TEXTO_ACK` ("vou te responder em
instantes") antes da recusa, e a recusa chega logo em seguida. É o que a issue pede
— recusar educado, e não espera silenciosa."""

TEXTO_BOAS_VINDAS = (
    "Olá! Eu sou o S.A.U., o assistente virtual que orienta sobre processos de "
    "estágio. Pergunte sobre prazos, documentação, contratos, seguro ou a ordem das "
    "etapas. Se eu não souber a resposta, te encaminho à Coordenação de Estágios."
)
"""As boas-vindas do `/start`: fixas e sem o modelo.

O `/start` não é pergunta — mandar para o modelo rendeu o "Olá novamente!" da
conversa real, que além de errado gasta um turno de inferência. O texto fixo
também cumpre a `identidade` da persona de graça: dizer "assistente virtual"
aqui é a apresentação única da conversa, e os turnos seguintes não se apresentam
mais. Entra no histórico como qualquer resposta do S.A.U., pela mesma
invariante da `TEXTO_FALHA`: o que o Aluno leu é parte da conversa dele.

Mora aqui, e não em `sau/persona.py`, pelo mesmo motivo invertido da sentinela
`test_as_regras_moram_so_em_sau_persona`: texto de canal é deste módulo, e
instrução ao modelo é da persona.
"""

TEXTO_REENGAJAMENTO = (
    "Que bom te ver de novo! Faz um tempo desde a nossa última conversa."
)
"""A frase que abre a resposta de quem voltou depois de o TTL apagar a conversa.

Vai grudada na frente da resposta do turno, e não como mensagem separada: o
Aluno já leva o acuse, e terceira mensagem viraria espera. Também entra no
histórico grudada, porque é o que o Aluno leu — separar na gravação e juntar no
envio divergiria o arquivo da conversa duas linhas depois.
"""

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

TENTATIVAS_NGROK = 10
"""Quantas vezes a descoberta consulta a API do ngrok antes de desistir.

A API demora a responder no boot do compose dev: o túnel ainda não existe
quando o webhook sobe. Dez tentativas curtas absorvem essa largada sem segurar
a subida.
"""

INTERVALO_NGROK_SEGUNDOS = 1.0
"""Espera entre duas consultas à API do ngrok."""

TIMEOUT_TUNEL_SEGUNDOS = 5.0
"""Teto de cada consulta à API local do ngrok."""

TIMEOUT_SETWEBHOOK_SEGUNDOS = 5.0
"""Teto do registro do webhook na API do Telegram."""

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


def _extrair_url_https_dos_tuneis(dados: Any) -> str | None:
    """Acha a primeira URL pública https na resposta do /api/tunnels do ngrok.

    A API devolve um objeto com a lista `tunnels`, e cada túnel traz o seu
    `public_url`. O http fica de fora de propósito: o Telegram só entrega em
    443, 80, 88 e 8443, então o túnel precisa terminar em HTTPS.
    """
    if not isinstance(dados, dict):
        return None
    tuneis = dados.get("tunnels")
    if not isinstance(tuneis, list):
        return None
    for tunel in tuneis:
        if not isinstance(tunel, dict):
            continue
        url = tunel.get("public_url")
        if isinstance(url, str) and url.startswith("https://"):
            normalizada = url.rstrip("/") or url
            return normalizada
    return None


def _descobrir_via_ngrok(
    cliente: httpx.Client,
    alvo: str,
    dormir: Callable[[float], None],
) -> str | None:
    """Consulta o /api/tunnels com retry curto e devolve o primeiro https."""
    for tentativa in range(TENTATIVAS_NGROK):
        try:
            resposta = cliente.get(alvo, timeout=TIMEOUT_TUNEL_SEGUNDOS)
            resposta.raise_for_status()
            encontrada = _extrair_url_https_dos_tuneis(resposta.json())
        except Exception:
            encontrada = None
        if encontrada is not None:
            return encontrada
        if tentativa < TENTATIVAS_NGROK - 1:
            dormir(INTERVALO_NGROK_SEGUNDOS)
    return None


def descobrir_url_publica(
    config: Configuracao,
    client: httpx.Client | None = None,
    dormir: Callable[[float], None] = time.sleep,
) -> str | None:
    """Descobre a URL pública do canal, ou None quando não há como saber.

    A TELEGRAM_PUBLIC_URL vence sempre: é o caminho de quem abre o túnel na
    mão, fora do compose dev. Sem ela, a descoberta consulta o /api/tunnels do
    ngrok apontado por NGROK_API_URL, com retry curto para absorver o boot.
    Sem as duas, nenhum HTTP acontece — o canal sobe sem registrar, como em
    prod — e é por isso que este retorno é None em vez de exceção.
    """
    if config.telegram_public_url:
        return config.telegram_public_url.rstrip("/") or config.telegram_public_url
    base = config.ngrok_api_url
    if base is None:
        return None
    alvo = f"{base.rstrip('/')}/api/tunnels"
    if client is not None:
        return _descobrir_via_ngrok(client, alvo, dormir)
    with httpx.Client(timeout=TIMEOUT_TUNEL_SEGUNDOS) as proprio:
        return _descobrir_via_ngrok(proprio, alvo, dormir)


def registrar_webhook(
    config: Configuracao,
    url_publica: str,
    client: httpx.Client | None = None,
) -> None:
    """Registra a URL pública no Telegram via setWebhook.

    A URL registrada é a pública com `/webhook` no fim, e o `secret_token` é o
    mesmo que fecha a porta do endpoint. O token do S.A.U. nunca vai para o
    log: ele mora na URL do setWebhook, então nenhuma mensagem de erro daqui
    carrega a URL chamada — só a URL pública e o motivo sanitizado.
    """
    token = config.telegram_bot_token
    if token is None:
        raise CredencialTelegramAusenteError(
            "TELEGRAM_BOT_TOKEN ausente: sem ele o S.A.U. não registra o webhook."
        )
    destino = f"{url_publica.rstrip('/')}/webhook"
    chamada = f"{config.telegram_api_base.rstrip('/')}/bot{token}/setWebhook"
    carga: dict[str, str] = {"url": destino}
    if config.telegram_webhook_secret_token is not None:
        carga["secret_token"] = config.telegram_webhook_secret_token

    def _postar(cliente: httpx.Client) -> None:
        try:
            resposta = cliente.post(chamada, json=carga, timeout=TIMEOUT_SETWEBHOOK_SEGUNDOS)
            resposta.raise_for_status()
            corpo = resposta.json()
        except httpx.HTTPError as err:
            raise RuntimeError(
                f"falha de rede ao registrar o webhook em {destino}: "
                f"{type(err).__name__}"
            ) from err
        if not isinstance(corpo, dict) or not corpo.get("ok", False):
            raise RuntimeError(f"o Telegram recusou o registro do webhook em {destino}: {corpo}")

    if client is not None:
        _postar(client)
    else:
        with httpx.Client(timeout=TIMEOUT_SETWEBHOOK_SEGUNDOS) as proprio:
            _postar(proprio)


def texto_posicao_na_fila(posicao: int, espera_segundos: float) -> str:
    """A frase que o Aluno lê quando o turno dele entrou atrás de outro.

    É a terceira das mensagens possíveis do turno, e ela existe porque o ADR-0001
    diz o que acontece sem ela: "um Aluno às 2h da manhã esperando sem saber o que
    está acontecendo destrói a promessa do produto". O texto informa duas coisas —
    a **posição** e uma **estimativa** — e a segunda vem com "cerca de", que não é
    refinamento de texto: é honestidade, porque o semáforo entrega uma média móvel
    que erra para os dois lados.

    A formatação vive aqui e não no semáforo, e é por isso que este módulo
    conhece o Telegram e o semáforo não: o semáforo entrega `PosicaoNaFila`, e quem
    sabe escrever para o Aluno em português é este arquivo, como o `TEXTO_ACK` e a
    `TEXTO_FALHA`.

    A granularidade é a do **minuto** a partir de um minuto, e não do segundo: a
    estimativa vem multiplicada por um número de voltas que raramente é inteiro, e
    "cerca de 3,7 minutos" é pior do que "cerca de 4 minutos" — é o tipo de
    precisão que não existe e que faz o Aluno desconfiar do resto do número. Abaixo
    de um minuto a frase é em segundos, porque "cerca de meio minuto" é mais difícil
    de ler do que "cerca de 30 segundos".

    A guarda de espera negativa é um `ValueError` e não um `assert` por uma razão
    concreta: `python -O` descarta `assert`, e o serviço roda com o interpretador
    normal — enquanto um `python -O` acidental em produção deixaria o Aluno ler
    "cerca de -20 segundos". A faixa de `max(1, ...)` abaixo é o que segura o zero
    de verdade, que é um caso legítimo: uma posição na frente com média medida em
    menos de meio segundo arredonda para zero, e "cerca de 0 segundos" é pior do que
    "cerca de 1 segundo".
    """
    if espera_segundos < 0:
        raise ValueError(
            f"Estimativa de espera negativa para o Aluno na posição {posicao}: "
            f"{espera_segundos}. O semáforo nunca devolve espera negativa — a média "
            "das vagas é uma duração, e duração não é negativa — e um valor assim "
            "aqui viraria um texto que mente para quem está de fato esperando."
        )
    if espera_segundos < 60:
        return (
            f"Você está na posição {posicao} da fila, "
            f"e a resposta deve sair em cerca de {max(1, round(espera_segundos))} segundos."
        )
    minutos = math.ceil(espera_segundos / 60)
    return (
        f"Você está na posição {posicao} da fila, "
        f"e a resposta deve sair em cerca de {minutos} minuto"
        f"{'s' if minutos > 1 else ''}."
    )


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


def _eh_comando_start(texto: str) -> bool:
    """Diz se o texto do Aluno é o `/start` do Telegram, com ou sem carga.

    O BotFather manda `/start` puro no primeiro contato, e botões e links
    profundos mandam `/start <carga>`. Em grupo o comando pode vir com o nome
    do S.A.U. grudado (`/start@meubot`). Nenhum dos três é pergunta: os três
    pedem as boas-vindas, e é por isso que a comparação é no comando, e não no
    texto inteiro.
    """
    comando = texto.split(None, 1)[0].lower()
    return comando == "/start" or comando.startswith("/start@")


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


ExecutorTurno = Callable[
    [
        Configuracao,
        int,
        str,
        "RegistroDeConversas",
        "SemaforoDeInferencia",
        "httpx.Client | None",
    ],
    None,
]
"""O que roda um turno: recebe a configuração, o chat do Aluno, a mensagem dele, o
registro de conversas e o semáforo de inferência, e é responsável por gravar a
conversa e por entregar a resposta — ou a mensagem de falha. É injetável porque o
turno é o passo que o teste precisa controlar, e um `threading.Thread` de verdade é
o que torna isso impossível de afirmar.

O `registro` entra no executor e não numa closure porque o turno roda numa thread
criada depois do request: a conversa precisa ser resolvida **dentro** da thread, no
momento do turno, e não no momento em que o `agendar` foi chamado. Uma conversa
montada no request e passada por valor carregaria um histórico velho e, pior, não
seria o mesmo objeto que segura a fila.

O `semaforo` entra pelo mesmo caminho e pelo mesmo motivo: ele é o limite de quantos
turnos rodam no modelo, e o app é quem o monta, porque quem tem a `Configuracao` com
o `INFERENCIA_K` é o `criar_app`. Um semáforo montado dentro do turno seria um
sinaleiro novo a cada mensagem, e o `k` não limitaria nada.
"""


def _agendar(acao: Callable[[], None]) -> None:
    """Roda `acao` em uma thread, fora do request.

    A thread **continua** depois da #11, e é preciso dizer por que, porque o texto
    desta função dizia que ela seria substituída e não foi. O que a #11 substituiu
    foi a thread como mecanismo de **escassez**: antes, uma thread por turno era o
    que fazia o serviço aceitar quantos Alunos o Python conseguisse acordar, e o
    Ollama era o único que não dava conta. Agora quem limita é o semáforo, com `k`
    medido na máquina alvo.

    A thread fica pelo outro motivo, que é o do acuse: ela tira o turno de dentro
    do request, e é por isso que o Aluno levou a primeira resposta antes de qualquer
    inferência. O ADR-0001 descartou worker dedicado *por Aluno*, que é outra coisa
    e continua descartado.

    Daemon de propósito: uma thread presa no timeout do modelo não pode segurar
    o processo do container na hora do `docker compose down`.
    """
    threading.Thread(target=acao, daemon=True).start()


def _processar_turno(
    config: Configuracao,
    chat_id: int,
    texto: str,
    registro: RegistroDeConversas,
    semaforo: SemaforoDeInferencia,
    client: httpx.Client | None = None,
) -> None:
    """Roda o grafo do turno e entrega ao Aluno a resposta, ou a mensagem de falha.

    O turno inteiro acontece dentro de `conversa.em_ordem()`, e a conversa é resolvida
    aqui dentro e não no request: a fila por conversa só existe se o turno N souber
    qual é a conversa do Aluno, e o `chat_id` do update é a única coisa que sabe
    disso. Resolver antes de agendar daria uma conversa possivelmente já expirada
    e, pior, um objeto de fila que não é o mesmo que o registro segura.

    Dentro da fila, a ordem das três coisas é o que faz o histórico ser a conversa
    que o Aluno teve:

    1. **lê** o histórico — é o que o modelo vai ver como conversa anterior;
    2. **grava a mensagem do Aluno**, antes do grafo, porque se o turno falhar a
       pergunta foi dada e é parte da conversa de qualquer jeito;
    3. **grava a resposta entregue**, depois da entrega ser montada, e inclusive a
       `TEXTO_FALHA` e a `TEXTO_FILA_CHEIA` — o histórico não pode divergir do que o
       Aluno leu.

    **O semáforo é adquirido dentro do `em_ordem()`, e essa é a decisão que sustenta
    o critério "um Aluno nunca tem dois turnos processados ao mesmo tempo".** Dentro,
    a fila do semáforo tem no máximo uma entrada por conversa, porque o turno só
    chega ao semáforo quando já é a vez dele na conversa. Fora, seguraria uma vaga
    enquanto o turno espera a vez da *própria* conversa, e dois turnos do mesmo Aluno
    poderiam estar na vaga ao mesmo tempo — o critério viraria uma corrida.

    A consequência boa dessa ordem é que a posição contada é posição **entre
    Alunos**, que é o que o Aluno entende quando lê "sua vez é a 3ª". Um turno atrás
    de outro turno do mesmo Aluno não existe aqui: ele está atrás da conversa, e o
    Aluno já sabe que o mandou antes.

    A ordem dos dois travamentos é sempre conversa e depois semáforo, e o
    `finally` do semáforo devolve a vaga mesmo com exceção no corpo. Não há caminho
    que inverta a ordem, então não há deadlock.

    O `aviso` do semáforo chama `enviar_mensagem` de dentro desta thread, e é
    proposital: a thread do turno é o único lugar do processo onde um `sendMessage`
    pode demorar sem travar nada, porque o acuse já saiu e o request já voltou 2xx.
    A espera tem teto de `TIMEOUT_ENVIO_SEGUNDOS`, então um Telegram lento atrasa a
    fila em até 5 s e não a trava.

    E o `aviso` pode falhar, e a falha não é da fila. O `enviar_mensagem` só captura
    `httpx.HTTPError`: um `TELEGRAM_API_BASE` malformado levanta `httpx.InvalidURL`,
    que não é subclasse de `HTTPError`, e a exceção sai direto — como sai qualquer
    outra falha de I/O. Ela cai no `except Exception` largo abaixo e vira
    `TEXTO_FALHA` para o Aluno com o motivo no log, que é o mesmo tratamento de
    qualquer outro turno que falhou. O que o semáforo garante é o resto: o turno que
    morreu no `aviso` devolve a senha antes de sair, senão ninguém viria servi-la e
    todo turno posterior esperaria para sempre, em silêncio. Ninguém fica preso por
    causa de I/O de terceiro — e é por isso que o `aviso` roda dentro do `try` do
    semáforo: fora da trava de propósito, dentro do `try` por necessidade.

    A `FilaCheiaError` vira `TEXTO_FILA_CHEIA` para o Aluno, `warning` no log e
    **nenhuma chamada ao modelo**: recusar por fila cheia antes de inferir é o que
    evita que o modelo seja chamado para um turno que já foi recusado. Ela entra no
    histórico pelo mesmo `registrar_do_sau` da falha, e é a mesma invariante.

    Dois caminhos não chamam o modelo, e os dois entram no histórico do mesmo
    jeito. O `/start` devolve a `TEXTO_BOAS_VINDAS` sem inferência e sem semáforo
    — comando não é pergunta, e gastar um turno de modelo nele foi o "Olá
    novamente!" da conversa real. A volta depois do TTL gruda a
    `TEXTO_REENGAJAMENTO` na frente da resposta do turno, seja ela a do modelo,
    a falha ou a recusa: quem voltou lê o "que bom te ver de novo" antes de
    qualquer outra coisa. O `/start` vence o reengajamento quando os dois
    coincidem — a volta que começou pelo comando já foi saudada —, e o sinal é
    consumido de qualquer jeito para não vazar ao turno seguinte.

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

    O `FilaCheiaError` é pego **antes** do `Exception` largo, e a ordem importa: se
    o largo viesse primeiro, a recusa educada viraria `TEXTO_FALHA` e o Aluno leria
    que algo quebrou, quando o que houve é fila cheia.

    Uma falha de leitura ou escrita do registro também vira `TEXTO_FALHA`, e não
    sobe: o arquivo de conversas é infraestrutura, e um disco cheio não pode
    derrubar o canal do Telegram — que ainda acuseja e ainda precisa atender quem
    não depende de histórico nenhum para a primeira pergunta.
    """
    cliente = ClienteOllama(
        config.ollama_base_url,
        config.ollama_model,
        timeout=config.ollama_timeout,
    )
    inicio = time.perf_counter()

    def avisar_posicao(posicao: PosicaoNaFila) -> None:
        """Entrega a posição da fila ao Aluno, uma vez só, antes de esperar.

        O texto vem do `texto_posicao_na_fila` e não do semáforo: o módulo da
        inferência mede tempo, e quem escreve para o Aluno é este arquivo. A
        entrega é anônima no log — só a posição e a estimativa — porque o
        `sendMessage` do `enviar_mensagem` já registra o `chat_id` e o resultado.
        """
        logger.info(
            "Turno do Aluno %s entrou na fila do semáforo na posição %d, "
            "com espera estimada de %.1fs.",
            chat_id,
            posicao.posicao,
            posicao.espera_estimada,
        )
        enviar_mensagem(
            config,
            chat_id,
            texto_posicao_na_fila(posicao.posicao, posicao.espera_estimada),
            client,
        )

    try:
        conversa = registro.conversa(chat_id)
        with conversa.em_ordem():
            reengajou = registro.consumir_reengajamento(chat_id)
            historico = conversa.historico()
            conversa.registrar_do_aluno(texto, time.time())
            if _eh_comando_start(texto):
                entrega, desfecho = TEXTO_BOAS_VINDAS, "boas-vindas"
            else:
                try:
                    with semaforo.na_fila(aviso=avisar_posicao):
                        entrega = executar_turno(cliente, texto, historico)
                except FilaCheiaError as err:
                    # A recusa é do Aluno, não do operador: `warning` e não `error`,
                    # porque nada quebrou — a fila encheu, que é o que o teto existe para
                    # transformar em resposta. O motivo técnico inteiro fica na exceção e
                    # o Aluno leva a frase que não tem número nem prazo.
                    logger.warning("Turno do Aluno %s recusado: %s", chat_id, err)
                    entrega, desfecho = TEXTO_FILA_CHEIA, "fila cheia"
                except ErroDeInferencia as err:
                    # `TempoEsgotadoError` é subclasse: o timeout cai aqui com o motivo
                    # certo no log e a mesma frase para o Aluno.
                    logger.error("O turno do Aluno %s falhou: %s", chat_id, err)
                    entrega, desfecho = TEXTO_FALHA, "falha do modelo"
                except Exception:
                    logger.exception(
                        "O turno do Aluno %s falhou por um erro que não é do modelo.", chat_id
                    )
                    entrega, desfecho = TEXTO_FALHA, "erro inesperado"
                else:
                    if entrega.strip():
                        desfecho = "resposta do modelo"
                    else:
                        # Resposta vazia não é erro do `ClienteOllama`: ele entrega o que
                        # veio, e o Ollama devolve `response: ""` com `done: true` quando o
                        # modelo para sem escrever nada. Mandar esse vazio ao Telegram é pior
                        # do que falhar — o `sendMessage` é recusado com 400 e o Aluno fica
                        # com o acuse e nenhum sinal do motivo. A mesma frase cobre os três
                        # jeitos de não responder.
                        logger.error(
                            "O turno do Aluno %s voltou do modelo sem texto nenhum.", chat_id
                        )
                        entrega, desfecho = TEXTO_FALHA, "resposta vazia"

                if reengajou:
                    entrega = f"{TEXTO_REENGAJAMENTO}\n\n{entrega}"

            # A resposta entregue vai para o histórico **dentro** da fila e antes do
            # envio. A ordem é o que importa: se o registro falhasse depois do envio, o
            # Aluno leria uma resposta que não está no histórico, e o turno seguinte
            # mostraria ao modelo uma conversa que ele não teve. A `TEXTO_FILA_CHEIA`
            # entra aqui pelo mesmo caminho da `TEXTO_FALHA`, e pelo mesmo motivo: o
            # Aluno leu a recusa, então a recusa é parte da conversa dele.
            conversa.registrar_do_sau(entrega, time.time())
    except Exception:
        # Falha do registro de conversas: disco cheio, arquivo corrompido, caminho
        # sem permissão. O Aluno ainda leva o acuse e ainda recebe `TEXTO_FALHA`, e o
        # motivo técnico vai inteiro no log. O canal do Telegram não pode cair porque
        # o histórico não pôde ser lido — foi o que o ADR-0001 deixou escrito: confirmar
        # o recebimento é requisito, não polimento.
        logger.exception(
            "O turno do Aluno %s falhou antes de entregar: o registro de conversas "
            "não respondeu.",
            chat_id,
        )
        entrega, desfecho = TEXTO_FALHA, "falha do registro"

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
    registro: RegistroDeConversas,
    semaforo: SemaforoDeInferencia,
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
        # O registro e o semáforo vão por parâmetro e a conversa não:
        # `registro.conversa(chat_id)` é chamado dentro do turno, na thread, e é aí
        # que a fila precisa existir. O semáforo vai pelo mesmo motivo e por um
        # segundo: ele é único no app, e um semáforo novo por turno não limitaria
        # nada.
        executor(config, chat_id, texto, registro, semaforo, client)

    agendar(iniciar)
    return jsonify({"status": "ok"}), 200


def criar_app(
    config: Configuracao,
    client: httpx.Client | None = None,
    registro: RegistroDeConversas | None = None,
    executor: ExecutorTurno | None = None,
    agendar: Callable[[Callable[[], None]], None] | None = None,
    semaforo: SemaforoDeInferencia | None = None,
) -> Flask:
    """Monta o app do webhook em torno de uma `Configuracao`.

    Nada é lido do ambiente na importação: quem monta o app decide qual
    configuração ele serve, e o teste monta com a dele.

    O parâmetro se chama `executor` e não `executar_turno` de propósito: há uma
    função com esse nome no módulo, a que de fato roda o grafo, e um parâmetro
    homônimo a esconderia dentro desta função. Os dois nomes dizem coisas
    diferentes — `executor` é o callable injetado, `executar_turno` é a função
    que chama o modelo — e a armadilha é rara o bastante para o nome não ser o mesmo.

    `registro`, `executor`, `agendar` e `semaforo` existem para o teste afirmar
    coisas que com a thread real, o arquivo real e o semáforo real não são
    afirmáveis: que o turno começa depois do acuse, que o turno acontece, que a
    conversa do Aluno sobrevive ao teste sem deixar `conversas.db` na raiz do
    repositório, e que o `k` do limite é o que o teste mandou. Os padrões são os de
    serviço; só a substituição é do teste.

    Sem `registro`, o app monta o seu a partir da configuração — `CONVERSA_CAMINHO` e
    `CONVERSA_TTL_MINUTOS` — e é o que faz `python -m sau.telegram` funcionar no host
    sem nenhuma configuração. O compose aponta o caminho para o volume nomeado, que é
    o que faz o histórico sobreviver ao `docker compose down`.

    Sem `semaforo`, o app monta o seu a partir de `INFERENCIA_K` e
    `INFERENCIA_FILA_TETO`, pelo mesmo desenho do registro. O semáforo é **um só por
    app**, montado aqui e não dentro do turno: ele é o limite do serviço inteiro, e
    um semáforo novo a cada mensagem seria um `k` que não limita nada. A medição do
    `k` na máquina alvo é o procedimento de `docs/fila-e-semaforo.md`, e o campo
    está em branco porque a medição ainda não aconteceu.
    """
    registro_do_turno = registro or RegistroDeConversas(
        config.conversa_caminho, ttl_minutos=config.conversa_ttl_minutos
    )
    semaforo_do_turno = semaforo or SemaforoDeInferencia(
        config.inferencia_k, config.inferencia_fila_teto
    )
    rodar_turno = executor or _processar_turno
    disparar = agendar or _agendar
    app = Flask(__name__)

    @app.post("/webhook")
    def webhook() -> RespostaWebhook:
        return _atender_webhook(
            config, client, registro_do_turno, semaforo_do_turno, rodar_turno, disparar
        )

    return app


def inicializar_manual(config: Configuracao) -> None:
    """Indexa o Manual de Estágio Obrigatório no boot, sem derrubar o canal.

    A carga é idempotente (`sau/manual/indice.py`): reaproveita o índice
    quando o PDF é o mesmo e re-ingere quando ele muda. Sem o PDF, registra
    onde colocá-lo e segue sem índice — o canal do Telegram não pode sair do
    ar por falta do material. Falha no Ollama ou no Chroma vira aviso pelo
    mesmo motivo: o Aluno continua sendo acusejado.
    """
    caminho_pdf = Path(config.manual_pdf_caminho)
    if not caminho_pdf.is_file():
        logger.warning(
            "Manual de Estágio ausente: coloque o PDF em `corpus/` — ver "
            "`corpus/README.md` (esperado: %s). O serviço segue no ar sem índice.",
            caminho_pdf,
        )
        return
    try:
        cliente = ClienteEmbedding(config.ollama_base_url)
        estado = carregar_ou_indexar(
            caminho_pdf,
            Path(config.manual_chroma_caminho),
            config.manual_colecao,
            cliente,
        )
    except Exception as err:
        logger.warning(
            "Manual não indexado e o serviço segue sem índice (%s: %s).",
            type(err).__name__,
            err,
        )
        return
    if estado.reaproveitado:
        logger.info(
            "Manual pronto: %d chunks reaproveitados do índice guardado.",
            estado.total_chunks,
        )
    else:
        logger.info(
            "Manual pronto: %d chunks indexados do PDF %s.",
            estado.total_chunks,
            caminho_pdf.name,
        )


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

    try:
        url_publica = descobrir_url_publica(config)
        if url_publica is None:
            logger.warning(
                "Sem URL pública (sem TELEGRAM_PUBLIC_URL e sem túnel do ngrok): "
                "subindo sem registrar o webhook. O Aluno só recebe após o setWebhook."
            )
        else:
            registrar_webhook(config, url_publica)
            logger.info("Webhook registrado em %s/webhook.", url_publica.rstrip("/"))
    except Exception as err:
        # Registro automático nunca derruba o canal: o serviço continua no ar
        # para acusejar o Aluno, e o setWebhook manual segue valendo. O token
        # não aparece aqui — só a URL pública e o motivo sanitizado.
        logger.warning("Não foi possível registrar o webhook automaticamente: %s", err)

    logger.info("=" * 60)
    logger.info("S.A.U. - webhook do Telegram")
    logger.info("Endpoint: POST /webhook na porta %d", config.telegram_webhook_port)
    logger.info("Modelo do turno: %s em %s", config.ollama_model, config.ollama_base_url)
    logger.info(
        "Conversas em %s, expirando depois de %d minutos sem contato.",
        config.conversa_caminho,
        config.conversa_ttl_minutos,
    )
    # O `k` vai no banner porque ele é a única configuração do serviço que a
    # pessoa não escolheu por conta própria: é medido na máquina alvo, e o
    # procedimento está em `docs/fila-e-semaforo.md`. Quem opera precisa saber
    # qual é o número sem abrir o `.env`.
    logger.info(
        "Inferência: %d turno(s) ao mesmo tempo, fila de espera de até %d.",
        config.inferencia_k,
        config.inferencia_fila_teto,
    )
    logger.info(
        "URL pública do túnel: registre com setWebhook antes de usar. "
        "O Telegram só entrega em 443, 80, 88 e 8443, então o túnel precisa ser HTTPS."
    )
    logger.info("=" * 60)

    inicializar_manual(config)

    # 0.0.0.0 porque o serviço roda em container, e é o bind que o torna
    # alcançável de fora da máquina que o do compose.
    criar_app(config).run(host="0.0.0.0", port=config.telegram_webhook_port)
