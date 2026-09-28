"""Entrypoint principal do serviço S.A.U. - Sistema de Apoio Unopar.

Configura logs padronizados, executa checagens de pré-requisitos e
mantém o serviço ativo.
"""

from __future__ import annotations

import json
import logging
import signal
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from sau.config import Configuracao, carregar_configuracao
from sau.prereqs import PreRequisitoError, executar_checagens


def configurar_logging(nivel: str = "INFO") -> None:
    """Configura o formato de log padronizado e distinguível do S.A.U."""
    formato = "%(asctime)s [SAU] [%(levelname)s] %(name)s: %(message)s"
    data_formato = "%Y-%m-%d %H:%M:%S"
    logging.basicConfig(
        level=getattr(logging, nivel.upper(), logging.INFO),
        format=formato,
        datefmt=data_formato,
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,
    )


class ServicoHealthHandler(BaseHTTPRequestHandler):
    """Handler HTTP básico para health check e status do serviço do bot."""

    def do_GET(self) -> None:  # noqa: N802
        if self.path in ("/", "/health"):
            resposta: dict[str, Any] = {
                "status": "healthy",
                "servico": "sau-bot",
                "identidade": "S.A.U. - Sistema de Apoio Unopar",
            }
            dados = json.dumps(resposta).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(dados)))
            self.end_headers()
            self.wfile.write(dados)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        logger = logging.getLogger("sau.server")
        logger.debug(
            "%s - - [%s] " + format,
            self.address_string(),
            self.log_date_time_string(),
            *args,
        )


def rodar_servidor(config: Configuracao, stop_event: threading.Event) -> None:
    """Inicia o servidor HTTP do bot e aguarda encerramento."""
    logger = logging.getLogger("sau.main")
    servidor = HTTPServer(("0.0.0.0", config.bot_port), ServicoHealthHandler)
    servidor.timeout = 1.0

    logger.info("Servidor do bot iniciado na porta %d. Pronto para atender.", config.bot_port)

    while not stop_event.is_set():
        servidor.handle_request()

    servidor.server_close()
    logger.info("Servidor do bot encerrado graciosamente.")


def main() -> None:
    """Execução principal do serviço."""
    # O log é configurado ANTES da configuração, e não depois. Uma
    # VRAM_TOTAL_MIB malformada também é falha alta, e ela precisa sair no
    # mesmo formato distinguível de todo o resto — um traceback cru não é
    # "falha alta com mensagem explícita", que é o que o critério da #4 pede.
    configurar_logging()
    logger = logging.getLogger("sau.main")

    try:
        config = carregar_configuracao()
    except ValueError as err:
        logger.critical(
            "\n%s\n[ABORTANDO] Configuração inválida:\n%s\n%s",
            "!" * 60,
            err,
            "!" * 60,
        )
        sys.exit(1)

    # Reaplica com o nível que a própria configuração pediu.
    configurar_logging(config.log_level)

    logger.info("=" * 60)
    logger.info("S.A.U. - Sistema de Apoio Unopar (Tutor Virtual EaD)")
    logger.info("Iniciando serviço do bot no container...")
    logger.info("=" * 60)

    try:
        executar_checagens(config)
    except PreRequisitoError as err:
        logger.critical(
            "\n%s\n[ABORTANDO] Falha crítica de pré-requisito:\n%s\n%s",
            "!" * 60,
            err,
            "!" * 60,
        )
        sys.exit(1)
    except Exception as err:
        logger.critical("Erro inesperado durante inicialização: %s", err, exc_info=True)
        sys.exit(1)

    stop_event = threading.Event()

    def tratar_sinal(sig: int, _frame: Any) -> None:
        logger.info("Sinal %d recebido. Iniciando encerramento gracioso...", sig)
        stop_event.set()

    signal.signal(signal.SIGINT, tratar_sinal)
    signal.signal(signal.SIGTERM, tratar_sinal)

    rodar_servidor(config, stop_event)


if __name__ == "__main__":
    main()
