"""Configurações do serviço do S.A.U.

Lê variáveis de ambiente com defaults seguros e tipados. A VRAM total da
máquina entra por `VRAM_TOTAL_MIB` porque nenhum endpoint do Ollama a expõe, e
a checagem de pré-requisito do ADR-0002 não consegue confrontar o `size_vram`
que o Ollama relata sem ela.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class Configuracao:
    """Configurações operacionais do bot S.A.U."""

    ollama_base_url: str
    ollama_model: str
    ollama_timeout: float
    ollama_allow_cpu: bool
    vram_total_bytes: int | None
    bot_port: int
    bot_env: str
    log_level: str
    telegram_bot_token: str | None
    telegram_webhook_secret_token: str | None
    telegram_webhook_port: int
    telegram_api_base: str


_MIB_EM_BYTES = 1_048_576
"""Quantos bytes tem 1 MiB, a unidade em que a VRAM é declarada."""


def _parse_bool(valor: str | None, default: bool = False) -> bool:
    if valor is None:
        return default
    return valor.strip().lower() in ("true", "1", "yes", "t", "sim")


def carregar_configuracao(origem: Mapping[str, str] | None = None) -> Configuracao:
    """Carrega as configurações a partir do ambiente ou de um dicionário fornecido."""
    env = os.environ if origem is None else origem

    ollama_base_url = env.get("OLLAMA_BASE_URL", "http://host.docker.internal:11434").strip()
    ollama_model = env.get("OLLAMA_MODEL", "qwen2.5:3b").strip()

    timeout_raw = env.get("OLLAMA_TIMEOUT", "30.0")
    try:
        ollama_timeout = float(timeout_raw)
    except ValueError as err:
        raise ValueError(
            f"Valor inválido para OLLAMA_TIMEOUT: '{timeout_raw}'. Esperado número."
        ) from err

    ollama_allow_cpu = _parse_bool(env.get("OLLAMA_ALLOW_CPU"), default=False)

    # A VRAM total da máquina não é exposta por nenhum endpoint do Ollama: o
    # /api/ps só diz o size_vram de cada modelo. Como o container não tem GPU
    # por desenho do ADR-0002, o total precisa vir do host, em MiB, exatamente
    # como o nvidia-smi imprime. Ausente é None; string vazia também, porque o
    # compose injeta '${VRAM_TOTAL_MIB:-}'.
    vram_mib_bruto = env.get("VRAM_TOTAL_MIB")
    vram_total_bytes: int | None = None
    vram_mib_texto = (vram_mib_bruto or "").strip()
    if vram_mib_texto:
        erro_vram = (
            f"Valor inválido para VRAM_TOTAL_MIB: '{vram_mib_bruto}'. "
            "Esperado um inteiro positivo em MiB.\n"
            "A causa quase sempre é o nvidia-smi: ele imprime UMA LINHA POR GPU, "
            "então em uma máquina com mais de uma placa o comando precisa ser "
            "filtrado para entregar um valor só:\n"
            "  export VRAM_TOTAL_MIB=$(nvidia-smi --query-gpu=memory.total "
            "--format=csv,noheader,nounits | head -1)\n"
            "Se a sua máquina tem mais de uma placa, o head -1 pega a primeira: "
            "informe na mão o total da placa que roda o Ollama."
        )
        try:
            vram_mib = int(vram_mib_texto)
        except ValueError as err:
            raise ValueError(erro_vram) from err
        if vram_mib <= 0:
            raise ValueError(erro_vram)
        vram_total_bytes = vram_mib * _MIB_EM_BYTES

    port_raw = env.get("BOT_PORT", "8000")
    try:
        bot_port = int(port_raw)
    except ValueError as err:
        raise ValueError(f"Valor inválido para BOT_PORT: '{port_raw}'. Esperado inteiro.") from err

    bot_env = env.get("BOT_ENV", "development").strip()
    log_level = env.get("LOG_LEVEL", "INFO").strip().upper()

    # Credenciais do Telegram. Nenhuma das duas tem valor padrão, e nenhuma é
    # exigida aqui: quem não conversa com o Telegram é o serviço do bot, que
    # não precisa delas. A obrigatoriedade mora no `sau/telegram/webhook.py`,
    # que falha alto se subir sem elas — no mesmo estilo da checagem de
    # pré-requisito do ADR-0002, e não num `ValueError` que derrubaria também
    # quem não usa o canal. Ausente é None; string vazia também, porque o
    # compose injeta '${TELEGRAM_BOT_TOKEN:-}'.
    telegram_bot_token = (env.get("TELEGRAM_BOT_TOKEN") or "").strip() or None
    telegram_webhook_secret_token = (env.get("TELEGRAM_WEBHOOK_SECRET_TOKEN") or "").strip() or None
    telegram_api_base = env.get("TELEGRAM_API_BASE", "https://api.telegram.org").strip()

    webhook_port_raw = env.get("TELEGRAM_WEBHOOK_PORT", "8080")
    try:
        telegram_webhook_port = int(webhook_port_raw)
    except ValueError as err:
        raise ValueError(
            f"Valor inválido para TELEGRAM_WEBHOOK_PORT: '{webhook_port_raw}'. Esperado inteiro."
        ) from err

    return Configuracao(
        ollama_base_url=ollama_base_url,
        ollama_model=ollama_model,
        ollama_timeout=ollama_timeout,
        ollama_allow_cpu=ollama_allow_cpu,
        vram_total_bytes=vram_total_bytes,
        bot_port=bot_port,
        bot_env=bot_env,
        log_level=log_level,
        telegram_bot_token=telegram_bot_token,
        telegram_webhook_secret_token=telegram_webhook_secret_token,
        telegram_webhook_port=telegram_webhook_port,
        telegram_api_base=telegram_api_base,
    )
