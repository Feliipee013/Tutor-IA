"""Testes do handler do webhook do Telegram, sau/telegram/webhook.py.

O objetivo é provar o fio que a issue #5 promete: update chega, update bruto é
registrado, e o Aluno recebe o acuse de recibo sem que nada dependa do modelo.
O transporte do Telegram é falso (`httpx.MockTransport`), então o teste verifica
a requisição que sairia de verdade em vez de um duplo do S.A.U.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Iterator

import httpx
import pytest
from flask import Flask

from sau.config import carregar_configuracao
from sau.main import configurar_logging
from sau.telegram.webhook import (
    CABECALHO_SECRET_TOKEN,
    TEXTO_ACK,
    CredencialTelegramAusenteError,
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

LOGGER = "sau.telegram.webhook"


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

    def fechar(self) -> None:
        self.cliente.close()


@pytest.fixture
def telegram() -> Iterator[TelegramFalso]:
    falso = TelegramFalso()
    yield falso
    falso.fechar()


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
    """
    destinos: list[str] = []

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
        return telegram.responder(url)

    monkeypatch.setattr(httpx.Client, "request", request_do_cliente)
    return destinos


def _app(telegram: TelegramFalso, env: dict[str, str] | None = None) -> Flask:
    config = carregar_configuracao({**_ENV_PADRAO, **(env or {})})
    return criar_app(config, telegram.cliente)


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


def test_webhook_nao_toca_no_ollama(
    telegram: TelegramFalso, destinos_de_saida: list[str]
) -> None:
    """O acuse sai sem esperar o modelo, e o modelo é o Ollama.

    A afirmação é sobre **toda** URL que saiu do processo, e não sobre o que o
    cliente injetado registrou. As duas coisas não são a mesma coisa: um cliente
    que o próprio handler abre para falar com o Ollama não passa pelo
    `TelegramFalso`, e uma guarda montada só sobre ele passa com o acuse
    esperando o modelo.

    "Toda URL" só é verdade porque a fixture `destinos_de_saida` patcha o
    `httpx.Client.request`, por onde todo o tráfego passa. Numa versão anterior
    ela patchava o `Client.post`, e uma chamada `.request` para o Ollama — a
    forma que a #8 usa — não era registrada: este teste ficava verde com a
    garantia quebrada. A promessa agora vem com o funil que a sustenta.
    """
    config = carregar_configuracao(_ENV_PADRAO)
    _postar(criar_app(config, telegram.cliente), UPDATE_DO_ALUNO)

    assert destinos_de_saida, "o acuse não saiu: a guarda estaria medindo o vazio"

    fora_do_telegram = [d for d in destinos_de_saida if "api.telegram.org" not in d]
    assert not fora_do_telegram, f"o acuse saiu para fora do Telegram: {fora_do_telegram}"

    esperou_o_modelo = [d for d in destinos_de_saida if config.ollama_base_url in d]
    assert not esperou_o_modelo, f"o acuse esperou o modelo antes de sair: {esperou_o_modelo}"

    # E o que saiu foi exatamente o acuse, uma vez, para o Telegram.
    assert destinos_de_saida == [f"{config.telegram_api_base}/bot{_TOKEN}/sendMessage"]


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
    assert any("recusou o acuse" in r.getMessage() for r in caplog.records)


def test_webhook_falha_de_rede_nao_vira_5xx(caplog: pytest.LogCaptureFixture) -> None:
    def cair(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    cliente = httpx.Client(transport=httpx.MockTransport(cair))
    try:
        with caplog.at_level(logging.ERROR, logger=LOGGER):
            resposta = _postar(
                criar_app(carregar_configuracao(_ENV_PADRAO), cliente), UPDATE_DO_ALUNO
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
            _postar(criar_app(carregar_configuracao({}), telegram.cliente), UPDATE_DO_ALUNO)
    finally:
        telegram.fechar()

    assert telegram.enviados == []
    assert any("TELEGRAM_BOT_TOKEN ausente" in r.getMessage() for r in caplog.records)
