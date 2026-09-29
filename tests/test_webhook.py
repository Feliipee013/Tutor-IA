"""Testes do handler do webhook do Telegram, sau/telegram/webhook.py.

O que se prova aqui é o fio do canal: update chega, update bruto é registrado, o
Aluno recebe o acuse de recibo sem esperar o modelo e, desde a #8, recebe a
resposta do modelo depois do acuse. O transporte do Telegram e o do modelo são
falsos (`httpx.MockTransport`), então a suíte verifica as requisições que
sairiam de verdade em vez de simular o S.A.U.
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any, Callable, Iterator

import httpx
import pytest
from flask import Flask

from sau.config import carregar_configuracao
from sau.inference.ollama import ErroDeInferencia, Resposta, TempoEsgotadoError
from sau.main import configurar_logging
from sau.telegram import webhook
from sau.telegram.webhook import (
    CABECALHO_SECRET_TOKEN,
    TEXTO_ACK,
    TEXTO_FALHA,
    CredencialTelegramAusenteError,
    ExecutorTurno,
    criar_app,
    exigir_credenciais,
    main,
)

_TOKEN = "7123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw"
_SEGREDO = "chave-de-desenvolvimento"

_ENV_PADRAO = {
    "TELEGRAM_BOT_TOKEN": _TOKEN,
    "TELEGRAM_WEBHOOK_SECRET_TOKEN": _SEGREDO,
}

UPDATE_DO_ALUNO: dict[str, Any] = {
    "update_id": 999,
    "message": {
        "message_id": 42,
        "chat": {"id": 55_512_345, "type": "private"},
        "from": {"id": 55_512_345, "is_bot": False, "first_name": "Aluna"},
        "text": "qual o prazo de entrega da Atividade 2?",
    },
}

UPDATE_COM_FOTO: dict[str, Any] = {
    "update_id": 1000,
    "message": {
        "message_id": 43,
        "chat": {"id": 55_512_345, "type": "private"},
        "from": {"id": 55_512_345, "is_bot": False, "first_name": "Aluna"},
        "photo": [{"file_id": "AgAC...", "width": 90, "height": 90}],
        "caption": "olha essa imagem",
    },
}

LOGGER = "sau.telegram.webhook"


def _geracao(texto: str) -> dict[str, Any]:
    """O corpo de um `/api/generate` completo, como o `ClienteOllama` espera receber.

    Fica aqui, e não dentro da fixture que a usa, porque é o contrato do Ollama e
    não da guarda: a fixture registra o tráfego e precisa saber responder cada
    destino, e é esse "saber responder" que vira nome quando ele é uma função só.
    """
    return {
        "response": texto,
        "done": True,
        "done_reason": "stop",
        "eval_count": 11,
        "eval_duration": 1_000_000_000,
    }


class TelegramFalso:
    """Cliente do Telegram que registra o que o S.A.U. tentou enviar."""

    def __init__(self, status: int = 200) -> None:
        self.status = status
        self.requisicoes: list[httpx.Request] = []
        self.cliente = httpx.Client(transport=httpx.MockTransport(self._responder))

    def _responder(self, request: httpx.Request) -> httpx.Response:
        self.requisicoes.append(request)
        return httpx.Response(
            status_code=self.status,
            json={"ok": self.status == 200, "result": {"message_id": 1}},
            request=request,
        )

    def responder(self, url: Any) -> httpx.Response:
        """Responde a uma URL como se fosse o Telegram, sem passar por cliente.

        Existe para a guarda de "o acuse não espera o modelo": ela precisa
        registrar o tráfego de **qualquer** cliente, inclusive de um que o handler
        tenha aberto por conta própria para falar com o Ollama. A resposta
        continua sendo falsa, e é isso que mantém a promessa de nenhum teste
        depender de rede.
        """
        return self._responder(httpx.Request("POST", url))

    @property
    def enviados(self) -> list[httpx.Request]:
        """Só as chamadas de envio de mensagem, sem o resto do tráfico."""
        return [r for r in self.requisicoes if r.url.path.endswith("/sendMessage")]

    @property
    def textos(self) -> list[str]:
        """O texto de cada mensagem, na ordem em que a Aluna as receberia.

        A lista de `text` é a única afirmação que importa sobre o canal: o que a
        Aluna viu, e em que ordem. Ela aparece em quase todo teste de turno, e
        escrevê-la à mão a cada vez era o mesmo `json.loads` repetido seis vezes,
        com uma delas errando o campo e passando sem querer.
        """
        return [json.loads(envio.content)["text"] for envio in self.enviados]

    def fechar(self) -> None:
        self.cliente.close()


@pytest.fixture
def telegram() -> Iterator[TelegramFalso]:
    falso = TelegramFalso()
    yield falso
    falso.fechar()


@pytest.fixture
def threads_do_turno(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[threading.Thread]]:
    """Captura as threads que o agendamento de produção criar, e as espera no fim.

    Só os dois testes do agendamento de verdade usam isto. A captura vem de um
    patch em `threading.Thread` porque a função de agendamento não devolve a
    thread que criou — ela chama `start()` e larga. A thread é a de verdade, e
    roda a ação; o patch só dá acesso ao objeto.

    O `join` no teardown é o que impede a thread de escrever depois do fim do
    caso: o `pytest` fecha a captura de log, e uma thread que escreve depois disso
    produz `Logging error` no meio da saída, escondendo a falha que a suíte
    deveria estar mostrando.
    """
    criada: list[threading.Thread] = []
    classe_real = threading.Thread

    def fabrica(*args: Any, **kwargs: Any) -> threading.Thread:
        thread = classe_real(*args, **kwargs)
        criada.append(thread)
        return thread

    monkeypatch.setattr(threading, "Thread", fabrica)
    yield criada
    for thread in criada:
        thread.join(timeout=5.0)


@pytest.fixture
def destinos_de_saida(monkeypatch: pytest.MonkeyPatch, telegram: TelegramFalso) -> list[str]:
    """Registra toda URL que o processo tentou chamar, venha de onde vier.

    O `TelegramFalso` só enxerga o `httpx.Client` que o teste injeta, e o handler
    pode abrir um cliente próprio para falar com o Ollama. Nesse caso nada seria
    registrado e uma guarda de "o acuse não espera o modelo" passaria com a
    garantia quebrada — foi o que a primeira versão desta PR fazia.

    Por isso o registro é no `httpx.Client.request`, e não no cliente injetado.
    Esse método é o funil por onde **todo** o tráfego HTTP do processo passa:
    `Client.post` e `Client.get` delegam a ele, e `httpx.post` e `httpx.request`
    de módulo abrem um `Client` e chamam o mesmo método. Patchear o `.post` — a
    versão anterior desta fixture — deixava passar de fininho uma chamada
    `.request`, que é a forma que a inferência da #8 usa para falar com o Ollama:
    a guarda ficava verde com a garantia quebrada.

    Cada destino é respondido no formato que ele espera: o Telegram recebe a
    resposta de `TelegramFalso` e o Ollama recebe um `/api/generate` de verdade,
    com o campo `response`. Sem isso o `ClienteOllama` real — que é o que a
    guarda precisa exercitar — cairia em "não devolveu o campo 'response'" e a
    prova da ordem viria de um turno que falhou por um motivo que não é o do
    teste.
    """
    destinos: list[str] = []
    endereco_do_modelo = carregar_configuracao(_ENV_PADRAO).ollama_base_url

    def request_do_cliente(
        _self: httpx.Client, *args: Any, **kwargs: Any
    ) -> httpx.Response:
        # As duas portas do funil chamam `request` de formas diferentes:
        # `Client.post` e `Client.get` passam `method` e `url` por posição, e o
        # `httpx.request` de módulo passa por nome. Uma substituta com `method` e
        # `url` declarados aceitaria as duas — o Python liga por nome quando a
        # chamada é nomeada. Pegamos de `args`/`kwargs` mesmo assim, para que a
        # forma da chamada deixe de ser informação que esta guarda carrega.
        url = kwargs["url"] if "url" in kwargs else args[1]
        destinos.append(str(url))
        if endereco_do_modelo in str(url):
            return httpx.Response(
                status_code=200,
                json=_geracao(ModeloFalso.texto),
                request=httpx.Request("POST", url),
            )
        return telegram.responder(url)

    monkeypatch.setattr(httpx.Client, "request", request_do_cliente)
    return destinos


class ModeloFalso:
    """O `ClienteOllama` do turno, falso: nenhum byte sai para o host.

    O grafo e o nó são os de verdade — só o modelo é falso. Um turno inteiro com
    o grafo falso passaria com o `webhook` desconectado do grafo, que é o
    defeito que a #8 fecha.
    """

    texto: str = "O prazo da entrega eu não sei."
    erro: ErroDeInferencia | None = None

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        self.prompts: list[str] = []

    def responder(self, prompt: str, *, opcoes: dict[str, Any] | None = None) -> Resposta:
        self.prompts.append(prompt)
        if self.erro is not None:
            raise self.erro
        return Resposta(
            texto=self.texto,
            primeiro_token_segundos=0.0,
            carga_segundos=0.0,
            avaliacao_prompt_segundos=0.0,
            segundos_totais=0.0,
            tokens_por_segundo=None,
            tokens_gerados=None,
            concluida=True,
            motivo_de_parada="stop",
        )


class ModeloQueFalha(ModeloFalso):
    """O mesmo modelo, com o Ollama fora do ar — a falha que a #8 precisa fechar."""

    texto = ""
    erro = ErroDeInferencia(
        "FALHA CRÍTICA: não consegui falar com o Ollama em "
        "http://host.docker.internal:11434/api/generate: Connection refused."
    )


class ModeloQueTempoAcabou(ModeloFalso):
    """O mesmo modelo, lento demais: o `OLLAMA_TIMEOUT` do `webhook` estourou."""

    texto = ""
    erro = TempoEsgotadoError(
        "FALHA CRÍTICA: o modelo 'llama3.2:3b' não respondeu em 120s. O Aluno teria "
        "ficado esperando esse tempo todo antes de qualquer erro, então a espera é o "
        "defeito e não a ausência de resposta."
    )


class ModeloQueNaoResponde(ModeloFalso):
    """O mesmo modelo, que volta sem escrever nada: falha sem exceção."""

    texto = "   \n  "


def _sem_turno(*_args: Any) -> None:
    """Executor que não roda turno nenhum, para os testes que não são sobre o turno."""


def _anotando(registros: list[str]) -> ExecutorTurno:
    """Executor que anota a mensagem de cada turno, para afirmar o que entrou nele.

    O que interessa nesses testes é a lista, não o executor: o grafo está sendo
    ignorado de propósito, e a pergunta é só o que o `webhook` entregou a ele.
    """

    def anotar(_config: Any, _chat_id: int, texto: str, _client: Any) -> None:
        registros.append(texto)

    return anotar


def _sincrono(acao: Callable[[], None]) -> None:
    """Agenda o turno na thread do próprio teste, para poder esperar por ele."""
    acao()


def _app(
    telegram: TelegramFalso,
    env: dict[str, str] | None = None,
    executor: ExecutorTurno | None = _sem_turno,
    agendar: Callable[[Callable[[], None]], None] | None = _sincrono,
) -> Flask:
    """Monta o app com o turno e o agendamento injetados.

    O executor e o agendamento são substituídos em **quase** todos os testes daqui.
    O executor de produção monta um `ClienteOllama` de verdade e tentaria falar
    com o Ollama da máquina: a suíte passaria a depender da rede, e a thread
    poderia rodar depois do fim do teste, com o cliente de Telegram já fechado. Foi
    o que aconteceu na primeira versão desta PR — o teste do acuse ficou vermelho
    por causa de um `RuntimeError` de thread órfã.

    Passar `None` em vez do executor falso é o caminho de produção: `criar_app` recoloca o
    executor e o agendamento reais, e só o modelo e o transporte ficam falsos. É
    assim que os testes do turno rodam o `webhook` de verdade sem sair da rede — e,
    nos dois que passam `agendar=None`, a thread de verdade também.
    """
    config = carregar_configuracao({**_ENV_PADRAO, **(env or {})})
    return criar_app(config, telegram.cliente, executor, agendar)


def _postar(app: Flask, update: Any, *, segredo: str | None = _SEGREDO) -> Any:
    """POST no webhook. Sem `segredo`, vai sem o header, como o Telegram faria
    se o `setWebhook` tivesse sido feito sem `secret_token`."""
    cabecalhos = {} if segredo is None else {CABECALHO_SECRET_TOKEN: segredo}
    return app.test_client().post("/webhook", json=update, headers=cabecalhos)


# --- O update bruto é registrado, que é o que o ticket promete depurar ---


def test_webhook_registra_o_update_bruto(
    telegram: TelegramFalso, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger=LOGGER):
        _postar(_app(telegram), UPDATE_DO_ALUNO)

    registros = [r.getMessage() for r in caplog.records]
    algum = next((r for r in registros if "update_telegram bruto" in r), None)
    assert algum is not None, f"o update bruto não foi registrado: {registros}"
    # O update inteiro, não um resumo: é o que serve para depurar o payload.
    assert json.loads(algum.split("bruto: ", 1)[1]) == UPDATE_DO_ALUNO


def test_update_bruto_sai_no_stdout_com_o_log_do_operador(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """O update bruto precisa sair onde o operador olha, que é o AC #3.

    A primeira versão desta PR logava em INFO num logger sem handler.
    `logging.getLogger(__name__)` sozinho fica com nível efetivo WARNING, então o
    registro era descartado antes de chegar a qualquer handler: o único log que
    saía era o de payload inválido, ou seja, o log real registrava um update que
    não chegou e o que chegou sumia.

    A diferença em relação ao teste acima é que aqui passa pelo
    `configurar_logging` de verdade, o mesmo que o `main` chama na subida. Com
    `caplog` o teste instala o próprio handler e passaria mesmo com a
    configuração quebrada — que era exatamente o defeito, e por isso ele ficava
    invisível. Aqui a afirmação é sobre o stdout que o operador recebe.
    """
    raiz = logging.getLogger()
    handlers, nivel = raiz.handlers[:], raiz.level
    try:
        configurar_logging()
        telegram = TelegramFalso()
        try:
            _postar(_app(telegram), UPDATE_DO_ALUNO)
        finally:
            telegram.fechar()
    finally:
        raiz.handlers[:] = handlers
        raiz.setLevel(nivel)

    saida = capsys.readouterr().out
    assert "update_telegram bruto" in saida, f"o update bruto não saiu no stdout: {saida!r}"
    assert str(UPDATE_DO_ALUNO["update_id"]) in saida


def _nao_sobe_servidor(*_args: Any, **_kwargs: Any) -> None:
    """Substitui `Flask.run` para o teste do entrypoint não abrir uma porta."""


def test_entrypoint_do_webhook_configura_o_log_antes_do_banner(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """O `main` do webhook precisa configurar o log, e este é o AC #3.

    O teste anterior já prova que o update bruto sai no stdout **quando** o log
    está configurado, mas ele configura o log com a própria mão. Ninguém o
    provava: os dois testes passavam mesmo com o `configurar_logging` removido
    do `main`, porque nenhum deles passa pelo entrypoint. Este passa — chama o
    `main` de verdade, com as duas credenciais no ambiente, e só neutraliza o
    `Flask.run` para não subir servidor.

    O banner é o que faz a asserção: um `logger.info` num logger sem handler, em
    raiz WARNING, é descartado antes de chegar a lugar nenhum. Ele aparece no
    stdout se, e somente se, o `configurar_logging` rodou.
    """
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", _TOKEN)
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET_TOKEN", _SEGREDO)
    monkeypatch.setattr(Flask, "run", _nao_sobe_servidor)

    raiz = logging.getLogger()
    handlers, nivel = raiz.handlers[:], raiz.level
    try:
        # O estado de quem não configurou log nenhum: raiz sem handler, em
        # WARNING. Deixá-lo explícito é o que torna a falha limpa em vez de
        # depender do que o teste anterior deixou por trás.
        raiz.handlers[:] = []
        raiz.setLevel(logging.WARNING)
        main()
    finally:
        raiz.handlers[:] = handlers
        raiz.setLevel(nivel)

    saida = capsys.readouterr().out
    assert "S.A.U. - webhook do Telegram" in saida, f"o banner não saiu no stdout: {saida!r}"


def test_entrypoint_do_webhook_aplica_o_log_level_do_ambiente(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """O `LOG_LEVEL` do ambiente precisa chegar ao log do serviço, e este é o AC #3.

    O `main` do webhook chama `configurar_logging` duas vezes: uma antes de ler a
    configuração, para que uma configuração inválida saia no mesmo formato de todo
    o resto, e outra depois, com o nível que a própria configuração pediu. Ninguém
    provava a segunda. A suíte ficava verde com ela removida — `LOG_LEVEL` era
    lido do ambiente e jogado fora, e o operador que pedia `DEBUG` para depurar
    recebia `INFO` sem nenhum aviso.

    O módulo do webhook não tem nenhum `logger.debug`, então este teste não pode
    procurar um registro que não existe. Ele faz as duas coisas que importam:
    confere o nível efetivo da raiz, e emite de verdade um registro de DEBUG
    **depois** do `main`, para o stdout. A segunda é a que vale — prova que o
    operador veria a linha, e não só que uma configuração mudou.
    """
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", _TOKEN)
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET_TOKEN", _SEGREDO)
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setattr(Flask, "run", _nao_sobe_servidor)

    marcador = "marcador de depuração que o operador precisa ver"
    raiz = logging.getLogger()
    handlers, nivel = raiz.handlers[:], raiz.level
    try:
        raiz.handlers[:] = []
        raiz.setLevel(logging.WARNING)
        main()
        assert raiz.level == logging.DEBUG, (
            f"o LOG_LEVEL=DEBUG do ambiente não foi aplicado: raiz ficou em {raiz.level}"
        )
        # Depois do `main`, com o nível que ele deixou: é o caminho do operador.
        logging.getLogger(LOGGER).debug(marcador)
    finally:
        raiz.handlers[:] = handlers
        raiz.setLevel(nivel)

    saida = capsys.readouterr().out
    assert marcador in saida, f"o DEBUG não chegou ao stdout do operador: {saida!r}"


def test_linha_de_log_do_webhook_traz_o_prefixo_do_sau_e_o_nome_do_servico(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A linha do webhook diz `[SAU]` e o nome do serviço que a emitiu.

    O prefixo é do S.A.U. e não do serviço: `bot` está na seção *Evite* do
    `CONTEXT.md`, e o serviço já está identificado na própria linha pelo nome do
    módulo — `sau.telegram.webhook` contra `sau.main`. O prefixo `[SAU-BOT]`
    rotulava como "bot" a linha de um serviço que é o canal do Telegram, e
    apontava para o serviço errado para quem fosse filtrar por ele.

    Passa pelo `main` de verdade porque é a linha que o operador recebe que está
    em questão, não o que o `configurar_logging` produziria chamado na mão.
    """
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", _TOKEN)
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET_TOKEN", _SEGREDO)
    monkeypatch.setattr(Flask, "run", _nao_sobe_servidor)

    raiz = logging.getLogger()
    handlers, nivel = raiz.handlers[:], raiz.level
    try:
        main()
    finally:
        raiz.handlers[:] = handlers
        raiz.setLevel(nivel)

    saida = capsys.readouterr().out
    linha = next(
        (texto for texto in saida.splitlines() if "S.A.U. - webhook do Telegram" in texto),
        None,
    )
    assert linha is not None, f"o banner não saiu no stdout: {saida!r}"
    # `[SAU]` fecha com o colchete, e é isso que barra o prefixo antigo:
    # `[SAU-BOT]` não contém `[SAU]`.
    assert "[SAU]" in linha, f"o prefixo do S.A.U. não está na linha: {linha!r}"
    assert f"{LOGGER}:" in linha, f"o nome do serviço não está na linha: {linha!r}"


# --- O Aluno recebe o acuse de recibo, que é o que dá nome ao ticket ---


def test_webhook_envia_o_acuse_ao_aluno(telegram: TelegramFalso) -> None:
    _postar(_app(telegram), UPDATE_DO_ALUNO)

    assert len(telegram.enviados) == 1
    envio = telegram.enviados[0]
    assert envio.method == "POST"
    assert envio.url.path == f"/bot{_TOKEN}/sendMessage"
    assert json.loads(envio.content) == {"chat_id": 55_512_345, "text": TEXTO_ACK}


def test_webhook_responde_200_ao_telegram(telegram: TelegramFalso) -> None:
    assert _postar(_app(telegram), UPDATE_DO_ALUNO).status_code == 200


def test_o_acuse_sai_antes_de_o_turno_comecar(
    telegram: TelegramFalso, destinos_de_saida: list[str]
) -> None:
    """O acuse sai antes de o turno começar. Esta é a garantia da #5 desde a #8.

    Antes da #8 o teste afirmava que nenhum tráfico de modelo saía do processo, o
    que era verdade porque não havia inferência nenhuma. Com o turno no
    `webhook` essa afirmação não pode continuar: o modelo é chamado, e é chamado
    por este mesmo serviço. O que continua verdadeiro, e é o que o ADR-0001 pede,
    é a **ordem**: o Aluno levou o acuse antes de qualquer inferência começar.

    A ordem é afirmada pela **sequência inteira de tráfego**, e não por uma
    contagem vista de dentro do turno. Aqui vão as três peças de verdade — o
    `ClienteOllama` real, o grafo real e o `sendMessage` real —, e a fixture
    registra toda URL que saiu do processo, venha de onde vier. A lista sai nesta
    ordem: Telegram, modelo, Telegram. Um turno disparado antes do acuse a
    inverteria para modelo, Telegram, Telegram, e a lista inteira é a asserção —
    não só o seu primeiro elemento.

    A versão anterior desta guarda afirmava duas coisas que nada exercitava: que
    nenhum destino estava fora do Telegram, e que o acuse não esperou o modelo.
    Com o executor injetado as duas eram verdade por construção, porque o modelo
    nunca era chamado: a guarda media o vazio e passava. Aqui quem chama o modelo
    é o `ClienteOllama` de verdade, e as duas viram consequência da sequência.
    """
    config = carregar_configuracao(_ENV_PADRAO)
    para_o_telegram = f"{config.telegram_api_base}/bot{_TOKEN}/sendMessage"
    para_o_modelo = f"{config.ollama_base_url}/api/generate"

    _postar(_app(telegram, executor=None), UPDATE_DO_ALUNO)

    assert destinos_de_saida == [para_o_telegram, para_o_modelo, para_o_telegram], (
        f"o turno não rodou depois do acuse, ou rodou por outra via: {destinos_de_saida}"
    )


# --- O turno: a mensagem do Aluno chega ao modelo e a resposta volta ---


def test_a_mensagem_do_aluno_chega_ao_modelo_e_a_resposta_volta(
    telegram: TelegramFalso, monkeypatch: pytest.MonkeyPatch
) -> None:
    """O caminho da #8 inteiro, com o grafo, o nó e o modelo de verdade.

    A lista de textos enviados ao Telegram é a prova de ponta a ponta: acuse
    primeiro, resposta do modelo depois, na ordem em que o Aluno recebe. É o
    critério de aceitação da issue, e ele é de observável — o que o Aluno leva —
    e não de estado interno do grafo.
    """
    monkeypatch.setattr(webhook, "ClienteOllama", ModeloFalso)

    _postar(_app(telegram, executor=None), UPDATE_DO_ALUNO)

    assert telegram.textos == [TEXTO_ACK, ModeloFalso.texto]
    assert all(
        json.loads(envio.content)["chat_id"] == 55_512_345
        for envio in telegram.enviados
    )


def test_o_texto_do_aluno_e_a_mensagem_que_o_grafo_recebe(
    telegram: TelegramFalso, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pergunta do modelo é a da Aluna, e não uma constante do grafo.

    Um turno que respondesse a uma pergunta fixa passaria pelo teste do caminho
    inteiro acima, porque o texto do modelo voltaria igual. Aqui o modelo falso
    guarda o prompt que recebeu, e ele tem que ser a mensagem do update.
    """
    prompts: list[str] = []

    class ModeloQueGuarda(ModeloFalso):
        def responder(self, prompt: str, *, opcoes: dict[str, Any] | None = None) -> Resposta:
            prompts.append(prompt)
            return super().responder(prompt, opcoes=opcoes)

    monkeypatch.setattr(webhook, "ClienteOllama", ModeloQueGuarda)

    _postar(_app(telegram, executor=None), UPDATE_DO_ALUNO)

    assert len(prompts) == 1
    assert prompts[0].endswith(UPDATE_DO_ALUNO["message"]["text"])


def test_falha_do_modelo_vira_mensagem_ao_aluno_e_nao_stack_trace(
    telegram: TelegramFalso,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Ollama fora vira frase amigável, e o motivo fica com o operador.

    As duas metades importam. O Aluno recebe `TEXTO_FALHA`, que não é stack trace
    e não é a mensagem técnica do `ErroDeInferencia` — ela diz "FALHA CRÍTICA",
    a URL e a porta do host, e nenhuma dessas pertence a quem perguntou. O
    operador recebe o motivo inteiro no log do turno, porque a frase do Aluno não
    diz por que a resposta não veio.
    """
    monkeypatch.setattr(webhook, "ClienteOllama", ModeloQueFalha)

    with caplog.at_level(logging.ERROR, logger=LOGGER):
        resposta = _postar(_app(telegram, executor=None), UPDATE_DO_ALUNO)

    assert resposta.status_code == 200
    assert telegram.textos == [TEXTO_ACK, TEXTO_FALHA]

    # O motivo completo foi para o log, e não para o Aluno.
    assert "FALHA CRÍTICA" in caplog.text
    assert "11434" in caplog.text
    assert not any(
        "FALHA CRÍTICA" in texto or "11434" in texto for texto in telegram.textos
    )


def test_timeout_do_modelo_vira_mensagem_ao_aluno(
    telegram: TelegramFalso,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """O timeout é caminho próprio, e não o mesmo erro por herança.

    `TempoEsgotadoError` é subclasse de `ErroDeInferencia`, então o `except` do
    turno pega as duas sem um braço só para o timeout. O risco é esse mesmo: um
    `except ErroDeInferencia` estreitado por engano deixaria o timeout escapar, e
    o teste da falha de conexão continuaria verde.

    A espera é o defeito que importa aqui, e é o que a mensagem do log diz: o
    modelo não estava fora, estava lento. O Aluno recebe a mesma frase de sempre,
    porque para ele a diferença não muda nada — ele não recebeu resposta.
    """
    monkeypatch.setattr(webhook, "ClienteOllama", ModeloQueTempoAcabou)

    with caplog.at_level(logging.ERROR, logger=LOGGER):
        _postar(_app(telegram, executor=None), UPDATE_DO_ALUNO)

    assert telegram.textos == [TEXTO_ACK, TEXTO_FALHA]
    assert "não respondeu em" in caplog.text


def test_resposta_vazia_do_modelo_vira_mensagem_de_falha(
    telegram: TelegramFalso,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Resposta sem texto não vira `sendMessage` com texto vazio.

    O `ClienteOllama` trata `response` ausente como erro, mas `response` vazio é
    resposta válida para ele: o Ollama devolve isso quando o modelo para sem
    escrever. Entregar esse vazio ao Telegram é pior que falhar — o `sendMessage`
    é recusado com 400, o turno não vira erro nenhum, e a Aluna fica com o acuse e
    sem nenhum sinal do motivo.

    O teste usa um texto só de espaço, e não string vazia, porque é esse o caso
    que a checagem precisa pegar: o Telegram também recusa um texto que não tem
    nada visível, mesmo que o envio seja aceito.
    """
    monkeypatch.setattr(webhook, "ClienteOllama", ModeloQueNaoResponde)

    with caplog.at_level(logging.ERROR, logger=LOGGER):
        _postar(_app(telegram, executor=None), UPDATE_DO_ALUNO)

    assert telegram.textos == [TEXTO_ACK, TEXTO_FALHA]
    assert "sem texto" in caplog.text


def test_o_turno_roda_na_thread_de_producao(
    telegram: TelegramFalso,
    destinos_de_saida: list[str],
    threads_do_turno: list[threading.Thread],
) -> None:
    """O caminho de produção inteiro: thread de verdade, cliente de verdade, ordem de verdade.

    Todo o resto da suíte agenda o turno de forma síncrona, porque é assim que se
    afirma uma ordem sem corrida. Esta é a exceção: aqui a agendação é a de
    verdade, a do `criar_app` sem parâmetro, o `ClienteOllama` é o de verdade e o
    grafo é o de verdade. Só o transporte é falso.

    E a afirmação é a **ordem do tráfego inteiro**, a mesma de
    `test_o_acuse_sai_antes_de_o_turno_comecar`, e não a contagem de mensagens. A
    contagem passaria com o turno rodando antes do acuse, desde que as duas
    mensagens saíssem; a ordem não passa. Sem isto, a garantia do ADR-0001 valeria
    só no agendamento do teste, e o agendamento de produção — que é o que o
    `docker compose` sobe — ficaria sem prova.

    A thread precisa ser esperada antes de afirmar: o `post` volta antes de o
    turno terminar, e o caso acabaria com a thread ainda escrevendo depois do fim
    dele. A fixture `threads_do_turno` é quem espera.

    O que a Aluna recebeu não é afirmado aqui, e é de propósito: sob a
    `destinos_de_saida` o Telegram é respondido pela própria fixture, com uma
    requisição sintetizada e sem corpo, então os textos entregues são de outro
    teste — o `test_a_mensagem_do_aluno_chega_ao_modelo_e_a_resposta_volta`, que
    usa o cliente do `TelegramFalso` de verdade. A sequência de tráfego já prova
    que as duas mensagens saíram, e em que ordem.
    """
    config = carregar_configuracao(_ENV_PADRAO)

    resposta = _postar(_app(telegram, executor=None, agendar=None), UPDATE_DO_ALUNO)
    for thread in threads_do_turno:
        thread.join(timeout=5.0)

    assert resposta.status_code == 200
    assert destinos_de_saida == [
        f"{config.telegram_api_base}/bot{_TOKEN}/sendMessage",
        f"{config.ollama_base_url}/api/generate",
        f"{config.telegram_api_base}/bot{_TOKEN}/sendMessage",
    ], f"o turno não rodou depois do acuse, ou rodou por outra via: {destinos_de_saida}"


def test_a_thread_do_turno_e_daemon(threads_do_turno: list[threading.Thread]) -> None:
    """A thread do turno é daemon, e a razão é o `docker compose down`.

    Uma thread presa no timeout do modelo não pode segurar o processo na hora de
    derrubar a stack: o `down` ficaria esperando um modelo que não responde. Com
    `daemon=True` o processo sai e a thread morre junto.

    O teste chama a função de agendamento direto, e não o app inteiro, porque o
    que se afirma aqui é o `daemon` da thread — e o turno inteiro em thread real
    já é o teste de cima. Uma ação que não faz nada basta: a thread é criada do
    mesmo jeito, com a mesma flag.
    """
    rodou = threading.Event()
    webhook._agendar(rodou.set)

    assert rodou.wait(5.0), "a thread do turno não rodou a ação"
    assert [t.daemon for t in threads_do_turno] == [True]


def test_erro_inesperado_no_turno_vira_mensagem_ao_aluno(
    telegram: TelegramFalso,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Um erro que não é do modelo também vira frase para a Aluna.

    `ErroDeInferencia` é o caminho previsto: o `ClienteOllama` transforma timeout,
    conexão, HTTP e JSON inválido nela. Mas o grafo também pode estourar, e um
    `KeyError` de estado faltando não é `ErroDeInferencia`. Quem está do outro
    lado é uma thread, e exceção que sai de uma thread morre com ela: sem log e sem
    a Aluna saber que o turno nem aconteceu. O `except` largo no executor existe
    para essa borda, e este teste é o que a segura.

    A diferença em relação ao teste do `ErroDeInferencia` está no log: aqui a
    stack tem de estar lá. O Aluno recebe a mesma frase nos dois casos, porque para
    ele é a mesma coisa; quem conserta o serviço só consegue fazer isso se o motivo
    técnico tiver sobrevivido.
    """

    class ModeloQueEstoura(ModeloFalso):
        def responder(self, prompt: str, *, opcoes: dict[str, Any] | None = None) -> Resposta:
            raise KeyError("resposta")

    monkeypatch.setattr(webhook, "ClienteOllama", ModeloQueEstoura)

    with caplog.at_level(logging.ERROR, logger=LOGGER):
        _postar(_app(telegram, executor=None), UPDATE_DO_ALUNO)

    assert telegram.textos == [TEXTO_ACK, TEXTO_FALHA]
    assert "erro que não é do modelo" in caplog.text
    assert "KeyError" in caplog.text, "a stack do erro inesperado não foi para o log"


def test_telegram_recusando_a_resposta_nao_vira_5xx_e_nao_vira_excecao(
    telegram: TelegramFalso, caplog: pytest.LogCaptureFixture
) -> None:
    """O Telegram recusando a resposta é registrado, e o webhook segue de pé.

    Este é o furo honesto que sobrou depois do caminho feliz: o acuse sai, o turno
    roda, e a entrega da resposta é recusada pela API. A Aluna fica com o acuse e
    silêncio. Não há o que fazer no `#8` — a mensagem saiu do sistema e o Telegram
    não quis —, e devolver 5xx pioraria: faria o update ser reentregue e a Aluna
    levaria o acuse duas vezes.

    O que dá para fazer, e é o que este teste fixa, é o comportamento interno: o
    erro fica registrado para o operador e nada sobe. A reentrega do que falhou é
    a fila da #11, e é lá que a Aluna volta a receber a resposta.
    """
    telegram.status = 500

    with caplog.at_level(logging.ERROR, logger=LOGGER):
        resposta = _postar(_app(telegram, executor=None), UPDATE_DO_ALUNO)

    assert resposta.status_code == 200
    assert len(telegram.enviados) == 2, "o turno nem foi tentado depois do acuse"
    assert any("recusou a mensagem" in r.getMessage() for r in caplog.records)


def test_o_tempo_do_turno_vai_no_log(
    telegram: TelegramFalso, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """O tempo do turno inteiro, do começo à entrega, é o número que se vê na madrugada.

    O critério "a resposta chega em tempo aceitável para alguém acordado às 2h da
    manhã" é o único da issue que não dá para afirmar com um teste de tempo: a
    latência aqui é a do transporte falso, que responde na microsegunda, e um
    assert sobre ela passaria com o modelo mais lento do mundo. O que dá para
    garantir é que o número **existe**, por turno, com o desfecho junto — e que
    quem opera o serviço consegue responder "quanto tempo levou" semcronizar
    thread, relógio e log.

    A medição da máquina, essa sim é um número de verdade, e ela está em
    `docs/tempo-primeira-resposta.md`. Este é o do serviço, por turno.
    """
    monkeypatch.setattr(webhook, "ClienteOllama", ModeloFalso)

    with caplog.at_level(logging.INFO, logger=LOGGER):
        _postar(_app(telegram, executor=None), UPDATE_DO_ALUNO)

    tempos = [r.getMessage() for r in caplog.records if "entregue em" in r.getMessage()]
    assert len(tempos) == 1, f"o tempo do turno não foi registrado: {tempos}"
    assert "55_512_345" in tempos[0] or "55512345" in tempos[0], tempos[0]
    assert "(resposta do modelo)" in tempos[0], tempos[0]


def test_mensagem_sem_texto_e_acusejada_e_nao_gera_turno(telegram: TelegramFalso) -> None:
    """Foto, áudio e comando de teclado são acusejados e não viram turno.

    O grafo da #8 recebe mensagem escrita. Um turno sobre uma foto seria o S.A.U.
    inventando a pergunta da Aluna, e inventar a pergunta é o defeito que a
    persona da #10 vem justamente para fechar. O acuse sai do mesmo jeito, porque
    o que a Aluna precisa é saber que a mensagem chegou.

    O caso do `caption` é o que dá nome a este teste: o Telegram manda a legenda
    da foto no campo `caption`, e não em `text`. Ler `text` é o que impede que a
    legenda vire pergunta. Se a legenda um dia passar a contar, essa é a decisão da
    #10 — e ela precisa de um teste aqui do outro lado.
    """
    textos_dos_turnos: list[str] = []

    resposta = _postar(_app(telegram, executor=_anotando(textos_dos_turnos)), UPDATE_COM_FOTO)

    assert resposta.status_code == 200
    assert textos_dos_turnos == []
    assert telegram.textos == [TEXTO_ACK]


@pytest.mark.parametrize(
    "update",
    [
        {"update_id": 1, "message": {"chat": {"id": 55_512_345}, "text": ""}},
        {"update_id": 1, "message": {"chat": {"id": 55_512_345}, "text": "   \n  "}},
        {"update_id": 1, "message": {"chat": {"id": 55_512_345}, "text": 42}},
    ],
    ids=["texto-vazio", "texto-so-espaco", "texto-nao-string"],
)
def test_update_com_texto_que_nao_e_texto_nao_chega_ao_grafo(
    telegram: TelegramFalso, update: Any
) -> None:
    """Texto que não é texto escrito não entra no grafo.

    Update malformado não é o mesmo que foto: aqui o `text` existe, mas é vazio,
    é só espaço, ou nem é string. Ler `text` resolve os três, e é a mesma leitura
    que evita que o handler caia em cima de um `strip()` de um inteiro. A foto,
    que não tem `text` nenhum, tem teste próprio acima.
    """
    textos_dos_turnos: list[str] = []

    resposta = _postar(_app(telegram, executor=_anotando(textos_dos_turnos)), update)

    assert resposta.status_code == 200
    assert textos_dos_turnos == []


def test_o_turno_usa_o_timeout_do_ambiente(
    telegram: TelegramFalso, monkeypatch: pytest.MonkeyPatch
) -> None:
    """O `OLLAMA_TIMEOUT` do ambiente é o relógio do turno.

    O `webhook` não roda a checagem de pré-requisito do `bot`, e essa é a diferença
    de propósito entre os dois serviços. O que o turno herda do `bot` é o relógio:
    geração e checagem precisam esperar pelo mesmo tempo, ou a mesma máquina
    passa a ter dois tetos diferentes para o mesmo defeito.
    """
    timeouts: list[float] = []

    class ModeloQueMede(ModeloFalso):
        def __init__(self, _base_url: str, _modelo: str, timeout: float = 0.0) -> None:
            super().__init__()
            timeouts.append(timeout)

    monkeypatch.setattr(webhook, "ClienteOllama", ModeloQueMede)

    _postar(_app(telegram, env={"OLLAMA_TIMEOUT": "12.5"}, executor=None), UPDATE_DO_ALUNO)

    assert timeouts == [12.5]


# --- Payload inválido ---


@pytest.mark.parametrize("payload", [None, [], "texto solto", 7])
def test_webhook_recusa_payload_que_nao_e_objeto(
    telegram: TelegramFalso, payload: Any
) -> None:
    resposta = _postar(_app(telegram), payload)
    assert resposta.status_code == 400
    assert telegram.enviados == []


def test_webhook_ignora_o_corpo_invalido(
    telegram: TelegramFalso, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        resposta = _app(telegram).test_client().post(
            "/webhook",
            data=b"isto nao e json",
            headers={CABECALHO_SECRET_TOKEN: _SEGREDO},
        )

    assert resposta.status_code == 400
    assert any("não é um objeto JSON" in r.getMessage() for r in caplog.records)


# --- O header que fecha a porta pública do túnel ---


def test_webhook_recusa_post_sem_o_secret_token(telegram: TelegramFalso) -> None:
    resposta = _postar(_app(telegram), UPDATE_DO_ALUNO, segredo=None)
    assert resposta.status_code == 403
    assert telegram.enviados == []


def test_webhook_recusa_secret_token_divergente(telegram: TelegramFalso) -> None:
    resposta = _postar(_app(telegram), UPDATE_DO_ALUNO, segredo="chave-de-outra-pessoa")
    assert resposta.status_code == 403
    assert telegram.enviados == []


def test_webhook_aceita_o_secret_token_correto(telegram: TelegramFalso) -> None:
    resposta = _postar(_app(telegram), UPDATE_DO_ALUNO)
    assert resposta.status_code == 200
    assert len(telegram.enviados) == 1


def test_webhook_fica_aberto_quando_nao_ha_secret_token(telegram: TelegramFalso) -> None:
    """Sem a credencial no ambiente não há o que conferir.

    O serviço sobe sem ela quem não usa o canal; com a variável presente, conferir
    a chegada é o que fecha a porta.
    """
    app = _app(telegram, env={"TELEGRAM_WEBHOOK_SECRET_TOKEN": ""})
    assert _postar(app, UPDATE_DO_ALUNO, segredo=None).status_code == 200


# --- Update que não é mensagem do Aluno ---


@pytest.mark.parametrize(
    "update",
    [
        {"update_id": 1, "edited_message": {"text": "corrigindo"}},
        {"update_id": 1, "message_reaction": {"chat": {"id": 55_512_345}}},
        {"update_id": 1, "message": {"text": "sem chat"}},
        {"update_id": 1, "message": {"chat": {"id": "55.512.345"}}},
        {"update_id": 1, "message": {"chat": {"id": True}}},
    ],
    ids=["editado", "reacao", "sem-chat", "id-string", "id-bool"],
)
def test_webhook_update_sem_aluno_nao_acuseja(
    telegram: TelegramFalso, update: dict[str, Any]
) -> None:
    resposta = _postar(_app(telegram), update)
    # 2xx de propósito: erro faria o Telegram reentregar o mesmo update sempre.
    assert resposta.status_code == 200
    assert telegram.enviados == []


def test_webhook_update_sem_mensagem_e_registrado(
    telegram: TelegramFalso, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger=LOGGER):
        _postar(_app(telegram), {"update_id": 1, "edited_message": {"text": "corrigindo"}})
    assert any("sem mensagem do Aluno" in r.getMessage() for r in caplog.records)


# --- Falha do Telegram não pode virar update reentregue ---


def test_webhook_erro_do_telegram_nao_vira_5xx(
    telegram: TelegramFalso, caplog: pytest.LogCaptureFixture
) -> None:
    telegram.status = 500
    with caplog.at_level(logging.ERROR, logger=LOGGER):
        resposta = _postar(_app(telegram), UPDATE_DO_ALUNO)

    # Um 5xx faria o Telegram reentregar e o Aluno levaria o acuse duas vezes.
    assert resposta.status_code == 200
    assert any("recusou a mensagem" in r.getMessage() for r in caplog.records)


def test_webhook_falha_de_rede_nao_vira_5xx(caplog: pytest.LogCaptureFixture) -> None:
    def cair(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    cliente = httpx.Client(transport=httpx.MockTransport(cair))
    try:
        with caplog.at_level(logging.ERROR, logger=LOGGER):
            resposta = _postar(
                criar_app(
                    carregar_configuracao(_ENV_PADRAO), cliente, _sem_turno, _sincrono
                ),
                UPDATE_DO_ALUNO,
            )
    finally:
        cliente.close()

    assert resposta.status_code == 200
    assert any("Falha de rede" in r.getMessage() for r in caplog.records)


# --- O consumo é por webhook, não por long polling (ADR-0001) ---


def test_webhook_so_aceita_post(telegram: TelegramFalso) -> None:
    assert _app(telegram).test_client().get("/webhook").status_code == 405
    assert telegram.requisicoes == []


# --- Falha alta na ausência de credencial ---


def test_exigir_credenciais_recusa_o_token_do_sau_ausente() -> None:
    config = carregar_configuracao({"TELEGRAM_WEBHOOK_SECRET_TOKEN": _SEGREDO})
    with pytest.raises(CredencialTelegramAusenteError) as exc_info:
        exigir_credenciais(config)

    mensagem = str(exc_info.value)
    assert "TELEGRAM_BOT_TOKEN" in mensagem
    assert "@BotFather" in mensagem
    assert "TELEGRAM_WEBHOOK_SECRET_TOKEN" not in mensagem


def test_exigir_credenciais_recusa_o_secret_token_ausente() -> None:
    config = carregar_configuracao({"TELEGRAM_BOT_TOKEN": _TOKEN})
    with pytest.raises(CredencialTelegramAusenteError) as exc_info:
        exigir_credenciais(config)

    mensagem = str(exc_info.value)
    assert "TELEGRAM_WEBHOOK_SECRET_TOKEN" in mensagem
    assert "openssl rand -hex 16" in mensagem
    assert "TELEGRAM_BOT_TOKEN:" not in mensagem


def test_exigir_credenciais_recusa_as_duas_ausentes() -> None:
    with pytest.raises(CredencialTelegramAusenteError) as exc_info:
        exigir_credenciais(carregar_configuracao({}))

    mensagem = str(exc_info.value)
    assert "TELEGRAM_BOT_TOKEN" in mensagem
    assert "TELEGRAM_WEBHOOK_SECRET_TOKEN" in mensagem


def test_exigir_credenciais_aceita_as_duas_presentes() -> None:
    exigir_credenciais(carregar_configuracao(_ENV_PADRAO))


def test_sem_token_o_acuse_e_registrado_como_ausente(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """App montado sem passar por `main` não pode falhar em silêncio."""
    telegram = TelegramFalso()
    try:
        with caplog.at_level(logging.ERROR, logger=LOGGER):
            _postar(
                criar_app(
                    carregar_configuracao({}), telegram.cliente, _sem_turno, _sincrono
                ),
                UPDATE_DO_ALUNO,
            )
    finally:
        telegram.fechar()

    assert telegram.enviados == []
    assert any("TELEGRAM_BOT_TOKEN ausente" in r.getMessage() for r in caplog.records)
