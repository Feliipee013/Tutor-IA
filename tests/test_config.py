"""Testes unitários para o módulo de configuração sau/config.py."""

from __future__ import annotations

import pytest

from sau.config import carregar_configuracao


def test_configuracao_valores_padrao() -> None:
    config = carregar_configuracao({})
    assert config.ollama_base_url == "http://host.docker.internal:11434"
    assert config.ollama_model == "qwen2.5:3b"
    assert config.ollama_timeout == 30.0
    assert config.ollama_allow_cpu is False
    assert config.vram_total_bytes is None
    assert config.bot_port == 8000
    assert config.bot_env == "development"
    assert config.log_level == "INFO"


def test_configuracao_sobrescrita_via_ambiente() -> None:
    env = {
        "OLLAMA_BASE_URL": "http://localhost:11434",
        "OLLAMA_MODEL": "qwen2.5:3b",
        "OLLAMA_TIMEOUT": "45.5",
        "OLLAMA_ALLOW_CPU": "true",
        "VRAM_TOTAL_MIB": "4096",
        "BOT_PORT": "9000",
        "BOT_ENV": "production",
        "LOG_LEVEL": "DEBUG",
    }
    config = carregar_configuracao(env)
    assert config.ollama_base_url == "http://localhost:11434"
    assert config.ollama_model == "qwen2.5:3b"
    assert config.ollama_timeout == 45.5
    assert config.ollama_allow_cpu is True
    assert config.vram_total_bytes == 4096 * 1_048_576
    assert config.bot_port == 9000
    assert config.bot_env == "production"
    assert config.log_level == "DEBUG"


def test_configuracao_vram_ausente_ou_vazia() -> None:
    """Ausente de verdade e string vazia do compose são a mesma coisa."""
    assert carregar_configuracao({}).vram_total_bytes is None
    assert carregar_configuracao({"VRAM_TOTAL_MIB": ""}).vram_total_bytes is None
    assert carregar_configuracao({"VRAM_TOTAL_MIB": "   "}).vram_total_bytes is None


def test_configuracao_vram_aceita_espaco_em_branco() -> None:
    config = carregar_configuracao({"VRAM_TOTAL_MIB": " 4096 "})
    assert config.vram_total_bytes == 4096 * 1_048_576


@pytest.mark.parametrize("valor", ["invalido", "0", "-1", "-4096"])
def test_configuracao_vram_invalida(valor: str) -> None:
    with pytest.raises(ValueError, match="Valor inválido para VRAM_TOTAL_MIB"):
        carregar_configuracao({"VRAM_TOTAL_MIB": valor})


@pytest.mark.parametrize("valor,esperado", [
    ("1", True),
    ("True", True),
    ("TRUE", True),
    ("yes", True),
    ("sim", True),
    ("0", False),
    ("false", False),
    ("no", False),
    ("nao", False),
    ("", False),
])
def test_configuracao_boolean_allow_cpu(valor: str, esperado: bool) -> None:
    config = carregar_configuracao({"OLLAMA_ALLOW_CPU": valor})
    assert config.ollama_allow_cpu is esperado


def test_configuracao_timeout_invalido() -> None:
    with pytest.raises(ValueError, match="Valor inválido para OLLAMA_TIMEOUT"):
        carregar_configuracao({"OLLAMA_TIMEOUT": "invalido"})


def test_configuracao_porta_invalida() -> None:
    with pytest.raises(ValueError, match="Valor inválido para BOT_PORT"):
        carregar_configuracao({"BOT_PORT": "oito_mil"})
