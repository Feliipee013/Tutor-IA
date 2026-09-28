"""Handler do webhook do Telegram do S.A.U.

Recebe o update do Telegram, registra o update bruto para depuração e entrega ao
Aluno um acuse de recibo fixo, antes de qualquer inferência. É a primeira metade
do que o ADR-0001 exige: confirmar o recebimento imediatamente, ainda antes da
inferência, é requisito, não polimento. A segunda metade — a posição na fila de
espera — é do ticket de concorrência.

O acuse é fixo, e isso é deliberado: este ticket existe para provar o fio
(webhook, serialização, roteamento de chat) sem depender do modelo. O turno com
inferência é do ticket #8, a persona é do #10.
"""

from __future__ import annotations

import logging
import secrets
import sys
from typing import Any

import httpx
from flask import Flask, Response, jsonify, request

from sau.config import Configuracao, carregar_configuracao

logger = logging.getLogger(__name__)

TEXTO_ACK = "Recebi sua mensagem. Vou te responder em instantes."
"""O acuse de recibo, fixo e sem o modelo. O texto não promete posição na fila
porque a #11 é dona dela; o que ele promete é o que este ticket entrega — que a
mensagem do Aluno chegou e que alguém respondeu. A resposta que vem depois é o
que o #8 acrescenta."""

CABECALHO_SECRET_TOKEN = "X-Telegram-Bot-Api-Secret-Token"
"""Header que o Telegram anexa a toda entrega quando o `setWebhook` foi feito com
`secret_token`. A porta do webhook é pública pelo túnel de desenvolvimento, e sem
esta conferência qualquer POST na URL vira mensagem do S.A.U. para o `chat_id` que
a pessoa mandar no corpo."""

TIMEOUT_ACK_SEGUNDOS = 5.0
"""Teto do envio do acuse. O update já é do Aluno e ele não pode ficar esperando
por uma chamada de saída; o ADR-0001 pede confirmação imediata, e um envio sem
teto transforma o webhook numa espera."""

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


def enviar_ack(
    config: Configuracao,
    chat_id: int,
    client: httpx.Client | None = None,
) -> None:
    """Entrega o acuse de recibo ao Aluno.

    Falha do Telegram não vira status não-2xx de volta para o webhook: o Telegram
    reentrega o update quando o status difere de 2xx, e o Aluno levaria um
    segundo acuse da mesma mensagem. O update já foi consumido no caminho feliz,
    então a falha é registrada e a entrega segue — o retrabalho é da #11, que é
    quem tem a fila para repetir.
    """
    token = config.telegram_bot_token
    if token is None:
        # Só alcançável se o app for montado sem passar por `main`, que é quem
        # exige a credencial. Não engolir: sem token não há acuse, e o acuse é o
        # critério de aceitação deste ticket.
        logger.error(
            "TELEGRAM_BOT_TOKEN ausente: o acuse de recibo não pode ser enviado ao Aluno %s.",
            chat_id,
        )
        return

    url = f"{config.telegram_api_base.rstrip('/')}/bot{token}/sendMessage"

    def postar(cliente: httpx.Client) -> None:
        resposta = cliente.post(url, json={"chat_id": chat_id, "text": TEXTO_ACK})
        if resposta.status_code != 200:
            logger.error(
                "O Telegram recusou o acuse do Aluno %s: status %d, corpo %s",
                chat_id,
                resposta.status_code,
                resposta.text,
            )
            return
        logger.info("Acuse de recibo enviado ao Aluno %s.", chat_id)

    try:
        if client is not None:
            postar(client)
        else:
            with httpx.Client(timeout=TIMEOUT_ACK_SEGUNDOS) as cliente_proprio:
                postar(cliente_proprio)
    except httpx.HTTPError as err:
        logger.error(
            "Falha de rede ao enviar o acuse para o Aluno %s: %s. "
            "O update segue consumido, para o Aluno não levar o acuse duas vezes.",
            chat_id,
            err,
        )


def _atender_webhook(config: Configuracao, client: httpx.Client | None) -> RespostaWebhook:
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

    # O acuse sai antes de qualquer inferência — e este ticket não tem inferência.
    enviar_ack(config, chat_id, client)
    return jsonify({"status": "ok"}), 200


def criar_app(config: Configuracao, client: httpx.Client | None = None) -> Flask:
    """Monta o app do webhook em torno de uma `Configuracao`.

    Nada é lido do ambiente na importação: quem monta o app decide qual
    configuração ele serve, e o teste monta com a dele.
    """
    app = Flask(__name__)

    @app.post("/webhook")
    def webhook() -> RespostaWebhook:
        return _atender_webhook(config, client)

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
    logger = logging.getLogger("sau.telegram.webhook")

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
    logger.info(
        "URL pública do túnel: registre com setWebhook antes de usar. "
        "O Telegram só entrega em 443, 80, 88 e 8443, então o túnel precisa ser HTTPS."
    )
    logger.info("=" * 60)

    # 0.0.0.0 porque o serviço roda em container, e é o bind que o torna
    # alcançável de fora da máquina que o do compose.
    criar_app(config).run(host="0.0.0.0", port=config.telegram_webhook_port)
