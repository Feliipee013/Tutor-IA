"""Testes unitários para o módulo de pré-requisitos sau/prereqs.py."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
import pytest

from sau.config import Configuracao
from sau.prereqs import (
    CpuNaoAutorizadaError,
    ModeloNaoEncontradoError,
    OllamaIndisponivelError,
    PreRequisitoError,
    VramNaoInformadaError,
    executar_checagens,
    verificar_alocacao_gpu,
    verificar_conectividade,
    verificar_modelo_disponivel,
)


def _criar_mock_client(rotas: dict[str, tuple[int, dict[str, Any]]]) -> httpx.Client:
    """Cria um cliente httpx com respostas simuladas por rota e método."""

    def handler(request: httpx.Request) -> httpx.Response:
        caminho = request.url.path
        chave = f"{request.method} {caminho}"
        if chave in rotas:
            status, conteudo = rotas[chave]
            return httpx.Response(
                status_code=status,
                content=json.dumps(conteudo).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                request=request,
            )
        return httpx.Response(
            status_code=404,
            content=b'{"error": "not found"}',
            headers={"Content-Type": "application/json"},
            request=request,
        )

    return httpx.Client(transport=httpx.MockTransport(handler))


# --- Testes de Conectividade ---


def test_verificar_conectividade_sucesso() -> None:
    client = _criar_mock_client({"GET /api/version": (200, {"version": "0.32.3"})})
    versao = verificar_conectividade("http://host.docker.internal:11434", client=client)
    assert versao == "0.32.3"


def test_verificar_conectividade_falha_conexao() -> None:
    def handler_falha(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused")

    client = httpx.Client(transport=httpx.MockTransport(handler_falha))
    with pytest.raises(OllamaIndisponivelError) as exc_info:
        verificar_conectividade("http://host.docker.internal:11434", client=client)

    msg = str(exc_info.value)
    assert "FALHA CRÍTICA" in msg
    assert "ollama serve" in msg
    assert "ADR-0002" in msg


def test_verificar_conectividade_status_erro() -> None:
    client = _criar_mock_client({"GET /api/version": (500, {"error": "internal server error"})})
    with pytest.raises(OllamaIndisponivelError, match="respondeu com código 500"):
        verificar_conectividade("http://host.docker.internal:11434", client=client)


# --- Testes de Modelo Disponível ---


def test_verificar_modelo_disponivel_sucesso() -> None:
    client = _criar_mock_client({
        "GET /api/tags": (
            200,
            {
                "models": [
                    {"name": "qwen2.5:3b", "model": "qwen2.5:3b"},
                    {"name": "gemma2:2b", "model": "gemma2:2b"},
                ]
            },
        )
    })
    # Não deve levantar exceção
    verificar_modelo_disponivel("http://host.docker.internal:11434", "qwen2.5:3b", client=client)


def test_verificar_modelo_disponivel_com_latest() -> None:
    client = _criar_mock_client({
        "GET /api/tags": (
            200,
            {"models": [{"name": "qwen2.5:latest", "model": "qwen2.5:latest"}]},
        )
    })
    # Sem tag explícita, deve encontrar com :latest
    verificar_modelo_disponivel("http://host.docker.internal:11434", "qwen2.5", client=client)


def test_verificar_modelo_disponivel_falha_nao_encontrado() -> None:
    # O host tem o llama3.2, que o ADR-0003 descartou; o serviço pede o qwen2.5,
    # que é o escolhido. A mensagem precisa listar o que está lá de fato.
    client = _criar_mock_client({
        "GET /api/tags": (
            200,
            {"models": [{"name": "llama3.2:3b", "model": "llama3.2:3b"}]},
        )
    })
    with pytest.raises(ModeloNaoEncontradoError) as exc_info:
        verificar_modelo_disponivel(
            "http://host.docker.internal:11434", "qwen2.5:3b", client=client
        )

    msg = str(exc_info.value)
    assert "FALHA CRÍTICA" in msg
    assert "ollama pull qwen2.5:3b" in msg
    assert "llama3.2:3b" in msg


# --- Testes de Alocação GPU vs CPU ---

_VRAM_4GIB = 4 * 1_073_741_824
"""VRAM declarada da máquina do ADR-0002: os 4 GiB da GTX 1650 que a #3 mediu."""

_MODELO = "qwen2.5:3b"
"""O modelo do ADR-0003, o mesmo que o compose pede por padrão."""


def _client_com_ps(item_modelo: dict[str, Any]) -> httpx.Client:
    """Cliente que devolve um único modelo carregado em /api/ps."""
    return _criar_mock_client({"GET /api/ps": (200, {"models": [item_modelo]})})


def test_verificar_alocacao_gpu_sucesso_100_gpu() -> None:
    client = _client_com_ps({"name": _MODELO, "size": 2000000000, "size_vram": 2000000000})
    resultado = verificar_alocacao_gpu(
        "http://host.docker.internal:11434",
        _MODELO,
        permitir_cpu=False,
        vram_total_bytes=_VRAM_4GIB,
        client=client,
    )
    assert resultado["name"] == _MODELO
    assert resultado["size_vram"] == 2000000000


def test_verificar_alocacao_gpu_falha_queda_silenciosa() -> None:
    """size_vram zerado com VRAM declarada é a queda que o ADR-0002 fecha."""
    client = _client_com_ps({"name": _MODELO, "size": 2000000000, "size_vram": 0})
    with pytest.raises(CpuNaoAutorizadaError) as exc_info:
        verificar_alocacao_gpu(
            "http://host.docker.internal:11434",
            _MODELO,
            permitir_cpu=False,
            vram_total_bytes=_VRAM_4GIB,
            client=client,
        )

    msg = str(exc_info.value)
    assert "FALHA CRÍTICA" in msg
    assert "Queda silenciosa para CPU" in msg
    assert "100.0% em CPU" in msg
    assert str(_VRAM_4GIB) in msg
    assert "ADR-0002" in msg
    assert "OLLAMA_ALLOW_CPU=true" in msg


def test_verificar_alocacao_gpu_falha_spill_parcial() -> None:
    client = _client_com_ps({"name": _MODELO, "size": 2000000000, "size_vram": 1000000000})
    with pytest.raises(CpuNaoAutorizadaError) as exc_info:
        verificar_alocacao_gpu(
            "http://host.docker.internal:11434",
            _MODELO,
            permitir_cpu=False,
            vram_total_bytes=_VRAM_4GIB,
            client=client,
        )

    msg = str(exc_info.value)
    assert "FALHA CRÍTICA" in msg
    assert "Spill parcial para CPU" in msg
    assert "50.0% em CPU" in msg
    assert "Queda silenciosa" not in msg


def test_verificar_alocacao_gpu_falha_vram_nao_informada() -> None:
    """Sem VRAM declarada não há contra o que conferir: a checagem para."""
    client = _client_com_ps({"name": _MODELO, "size": 2000000000, "size_vram": 2000000000})
    with pytest.raises(VramNaoInformadaError) as exc_info:
        verificar_alocacao_gpu(
            "http://host.docker.internal:11434",
            _MODELO,
            permitir_cpu=False,
            client=client,
        )

    msg = str(exc_info.value)
    assert "FALHA CRÍTICA" in msg
    assert "não foi informada" in msg
    # A mensagem precisa dizer o que fazer, não só nomear o problema.
    assert "VRAM_TOTAL_MIB" in msg
    assert "nvidia-smi" in msg


def test_verificar_alocacao_gpu_vram_nao_informada_autorizada(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Com permitir_cpu, a falta de VRAM declarada vira warning e a execução segue."""
    client = _client_com_ps({"name": _MODELO, "size": 2000000000, "size_vram": 2000000000})
    with caplog.at_level(logging.WARNING):
        resultado = verificar_alocacao_gpu(
            "http://host.docker.internal:11434",
            _MODELO,
            permitir_cpu=True,
            client=client,
        )

    assert resultado["name"] == _MODELO
    assert "não foi informada" in caplog.text
    assert "autorização explícita em OLLAMA_ALLOW_CPU=true" in caplog.text


def test_verificar_alocacao_gpu_falha_modelo_nao_cabe_na_placa() -> None:
    """Ollama joga para CPU porque o modelo não cabe: o diagnóstico é o tamanho."""
    client = _client_com_ps({"name": _MODELO, "size": 2000000000, "size_vram": 0})
    with pytest.raises(PreRequisitoError) as exc_info:
        verificar_alocacao_gpu(
            "http://host.docker.internal:11434",
            _MODELO,
            permitir_cpu=False,
            vram_total_bytes=1_000_000_000,
            client=client,
        )

    msg = str(exc_info.value)
    assert "não cabe na placa" in msg
    assert "Queda silenciosa" not in msg
    assert "Spill parcial" not in msg


def test_verificar_alocacao_gpu_falha_size_vram_ausente_no_payload() -> None:
    """Campo ausente não é campo zerado, e o diagnóstico tem que distinguir."""
    client = _client_com_ps({"name": _MODELO, "size": 2000000000})
    with pytest.raises(PreRequisitoError) as exc_info:
        verificar_alocacao_gpu(
            "http://host.docker.internal:11434",
            _MODELO,
            permitir_cpu=False,
            vram_total_bytes=_VRAM_4GIB,
            client=client,
        )

    msg = str(exc_info.value)
    assert "size_vram" in msg
    assert "payload veio incompleto" in msg
    assert "size_vram=0" not in msg
    assert "Queda silenciosa" not in msg


def test_verificar_alocacao_gpu_falha_dados_contraditorios() -> None:
    client = _client_com_ps({"name": _MODELO, "size": 2000000000, "size_vram": 6_000_000_000})
    with pytest.raises(PreRequisitoError) as exc_info:
        verificar_alocacao_gpu(
            "http://host.docker.internal:11434",
            _MODELO,
            permitir_cpu=False,
            vram_total_bytes=_VRAM_4GIB,
            client=client,
        )

    msg = str(exc_info.value)
    assert "Dados contraditórios" in msg
    assert "veredito é impossível" in msg


def test_verificar_alocacao_gpu_falha_modelo_sem_residencia() -> None:
    """size zerado não é queda para CPU, e a fração 0/0 não pode virar 0.0%.

    Calcular a fração com size=0 dava "0.0% em CPU", que é a mesma coisa que
    dizer que o modelo inteiro está na GPU — exatamente o que o ADR-0002
    proíbe o código de afirmar sem prova.
    """
    client = _client_com_ps({"name": _MODELO, "size": 0, "size_vram": 0})
    with pytest.raises(PreRequisitoError) as exc_info:
        verificar_alocacao_gpu(
            "http://host.docker.internal:11434",
            _MODELO,
            permitir_cpu=False,
            vram_total_bytes=_VRAM_4GIB,
            client=client,
        )

    msg = str(exc_info.value)
    assert "size=0" in msg
    assert "não tem residência" in msg
    assert "ollama ps" in msg
    # Nenhuma das leituras que a checagem não pode fazer.
    assert "em CPU" not in msg
    assert "Queda silenciosa" not in msg
    assert "Spill parcial" not in msg


def test_verificar_alocacao_gpu_falha_residencia_autocontraditoria() -> None:
    """size=0 com size_vram>0 é impossível: ninguém ocupa mais VRAM que o todo."""
    client = _client_com_ps({"name": _MODELO, "size": 0, "size_vram": 2_000_000_000})
    with pytest.raises(PreRequisitoError) as exc_info:
        verificar_alocacao_gpu(
            "http://host.docker.internal:11434",
            _MODELO,
            permitir_cpu=False,
            vram_total_bytes=_VRAM_4GIB,
            client=client,
        )

    msg = str(exc_info.value)
    assert "autocontraditório" in msg
    assert "em CPU" not in msg


def test_verificar_alocacao_gpu_autorizada_via_flag(caplog: pytest.LogCaptureFixture) -> None:
    """permitir_cpu transforma toda linha de falha em warning, sem parar."""
    client = _client_com_ps({"name": _MODELO, "size": 2000000000, "size_vram": 0})
    with caplog.at_level(logging.WARNING):
        resultado = verificar_alocacao_gpu(
            "http://host.docker.internal:11434",
            _MODELO,
            permitir_cpu=True,
            vram_total_bytes=_VRAM_4GIB,
            client=client,
        )

    assert resultado["name"] == _MODELO
    assert "ATENÇÃO: Queda silenciosa para CPU." in caplog.text
    # A mesma situação que vira falha alta vira warning, sem se contradizer.
    assert "FALHA CRÍTICA" not in caplog.text
    assert "autorização explícita em OLLAMA_ALLOW_CPU=true" in caplog.text


def test_verificar_alocacao_gpu_aquecimento_quando_nao_carregado() -> None:
    # Primeira chamada: vazio; generate: aquece; segunda chamada: retorna modelo carregado
    chamadas_ps = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal chamadas_ps
        if request.url.path == "/api/ps":
            chamadas_ps += 1
            if chamadas_ps == 1:
                return httpx.Response(200, json={"models": []}, request=request)
            return httpx.Response(
                200,
                json={"models": [{"name": _MODELO, "size": 2000, "size_vram": 2000}]},
                request=request,
            )
        if request.url.path == "/api/generate":
            return httpx.Response(200, json={"response": "ok"}, request=request)
        return httpx.Response(404, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    resultado = verificar_alocacao_gpu(
        "http://host.docker.internal:11434",
        _MODELO,
        permitir_cpu=False,
        vram_total_bytes=_VRAM_4GIB,
        client=client,
    )
    assert chamadas_ps == 2
    assert resultado["name"] == _MODELO


# --- Teste de Execução Completa ---


def _config_de_teste(vram_total_bytes: int | None) -> Configuracao:
    return Configuracao(
        ollama_base_url="http://host.docker.internal:11434",
        ollama_model=_MODELO,
        ollama_timeout=10.0,
        ollama_allow_cpu=False,
        vram_total_bytes=vram_total_bytes,
        bot_port=8000,
        bot_env="test",
        log_level="INFO",
        telegram_bot_token=None,
        telegram_webhook_secret_token=None,
        telegram_webhook_port=8080,
        telegram_api_base="https://api.telegram.org",
    )


def _client_com_stacks() -> httpx.Client:
    return _criar_mock_client({
        "GET /api/version": (200, {"version": "0.32.3"}),
        "GET /api/tags": (200, {"models": [{"name": _MODELO}]}),
        "GET /api/ps": (
            200,
            {"models": [{"name": _MODELO, "size": 2000, "size_vram": 2000}]},
        ),
    })


def test_executar_checagens_fluxo_completo_sucesso() -> None:
    # Deve rodar sem lançar exceções
    executar_checagens(_config_de_teste(_VRAM_4GIB), client=_client_com_stacks())


def test_executar_checagens_log_declara_a_vram(caplog: pytest.LogCaptureFixture) -> None:
    """O confronto precisa ficar visível no log, não só executado."""
    with caplog.at_level(logging.INFO):
        executar_checagens(_config_de_teste(_VRAM_4GIB), client=_client_com_stacks())

    assert f"VRAM da máquina: {_VRAM_4GIB} bytes" in caplog.text
    assert "Alocação em GPU confirmada" in caplog.text


def test_executar_checagens_sem_vram_declarada_falha_alta() -> None:
    """Config sem VRAM declarada tem de parar, e parar pelo motivo certo."""
    with pytest.raises(VramNaoInformadaError):
        executar_checagens(_config_de_teste(None), client=_client_com_stacks())
