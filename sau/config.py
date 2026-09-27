"""Configurações do serviço do S.A.U.

Lê variáveis de ambiente com defaults seguros e tipados.
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
    bot_port: int
    bot_env: str
    log_level: str


def _parse_bool(valor: str | None, default: bool = False) -> bool:
    if valor is None:
        return default
    return valor.strip().lower() in ("true", "1", "yes", "t", "sim")


def carregar_configuracao(origem: Mapping[str, str] | None = None) -> Configuracao:
    """Carrega as configurações a partir do ambiente ou de um dicionário fornecido."""
    env = os.environ if origem is None else origem

    ollama_base_url = env.get("OLLAMA_BASE_URL", "http://host.docker.internal:11434").strip()
    ollama_model = env.get("OLLAMA_MODEL", "llama3.2:3b").strip()

    timeout_raw = env.get("OLLAMA_TIMEOUT", "30.0")
    try:
        ollama_timeout = float(timeout_raw)
    except ValueError as err:
        raise ValueError(
            f"Valor inválido para OLLAMA_TIMEOUT: '{timeout_raw}'. Esperado número."
        ) from err

    ollama_allow_cpu = _parse_bool(env.get("OLLAMA_ALLOW_CPU"), default=False)

    port_raw = env.get("BOT_PORT", "8000")
    try:
        bot_port = int(port_raw)
    except ValueError as err:
        raise ValueError(f"Valor inválido para BOT_PORT: '{port_raw}'. Esperado inteiro.") from err

    bot_env = env.get("BOT_ENV", "development").strip()
    log_level = env.get("LOG_LEVEL", "INFO").strip().upper()

    return Configuracao(
        ollama_base_url=ollama_base_url,
        ollama_model=ollama_model,
        ollama_timeout=ollama_timeout,
        ollama_allow_cpu=ollama_allow_cpu,
        bot_port=bot_port,
        bot_env=bot_env,
        log_level=log_level,
    )
