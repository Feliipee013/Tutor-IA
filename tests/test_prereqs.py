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
                    {"name": "llama3.2:3b", "model": "llama3.2:3b"},
                    {"name": "qwen2.5:3b", "model": "qwen2.5:3b"},
                ]
            },
        )
    })
    # Não deve levantar exceção
    verificar_modelo_disponivel("http://host.docker.internal:11434", "llama3.2:3b", client=client)


def test_verificar_modelo_disponivel_com_latest() -> None:
    client = _criar_mock_client({
        "GET /api/tags": (
            200,
            {"models": [{"name": "llama3.2:latest", "model": "llama3.2:latest"}]},
        )
    })
    # Sem tag explícita, deve encontrar com :latest
    verificar_modelo_disponivel("http://host.docker.internal:11434", "llama3.2", client=client)


def test_verificar_modelo_disponivel_falha_nao_encontrado() -> None:
    client = _criar_mock_client({
        "GET /api/tags": (
            200,
            {"models": [{"name": "qwen2.5:3b", "model": "qwen2.5:3b"}]},
        )
    })
    with pytest.raises(ModeloNaoEncontradoError) as exc_info:
        verificar_modelo_disponivel(
            "http://host.docker.internal:11434", "llama3.2:3b", client=client
        )

    msg = str(exc_info.value)
    assert "FALHA CRÍTICA" in msg
    assert "ollama pull llama3.2:3b" in msg
    assert "qwen2.5:3b" in msg


# --- Testes de Alocação GPU vs CPU ---


def test_verificar_alocacao_gpu_sucesso_100_gpu() -> None:
    client = _criar_mock_client({
        "GET /api/ps": (
            200,
            {
                "models": [
                    {
                        "name": "llama3.2:3b",
                        "size": 2000000000,
                        "size_vram": 2000000000,
                    }
                ]
            },
        )
    })
    resultado = verificar_alocacao_gpu(
        "http://host.docker.internal:11434",
        "llama3.2:3b",
        permitir_cpu=False,
        client=client,
    )
    assert resultado["name"] == "llama3.2:3b"
    assert resultado["size_vram"] == 2000000000


def test_verificar_alocacao_gpu_falha_alta_em_cpu() -> None:
    # 0 VRAM -> 100% CPU
    client = _criar_mock_client({
        "GET /api/ps": (
            200,
            {
                "models": [
                    {
                        "name": "llama3.2:3b",
                        "size": 2000000000,
                        "size_vram": 0,
                    }
                ]
            },
        )
    })
    with pytest.raises(CpuNaoAutorizadaError) as exc_info:
        verificar_alocacao_gpu(
            "http://host.docker.internal:11434",
            "llama3.2:3b",
            permitir_cpu=False,
            client=client,
        )

    msg = str(exc_info.value)
    assert "FALHA CRÍTICA" in msg
    assert "100.0% em CPU" in msg
    assert "ADR-0002" in msg
    assert "OLLAMA_ALLOW_CPU=true" in msg


def test_verificar_alocacao_gpu_falha_alta_em_cpu_parcial() -> None:
    # 50% CPU, 50% VRAM
    client = _criar_mock_client({
        "GET /api/ps": (
            200,
            {
                "models": [
                    {
                        "name": "llama3.2:3b",
                        "size": 2000000000,
                        "size_vram": 1000000000,
                    }
                ]
            },
        )
    })
    with pytest.raises(CpuNaoAutorizadaError) as exc_info:
        verificar_alocacao_gpu(
            "http://host.docker.internal:11434",
            "llama3.2:3b",
            permitir_cpu=False,
            client=client,
        )

    msg = str(exc_info.value)
    assert "50.0% em CPU" in msg


def test_verificar_alocacao_gpu_autorizada_via_flag(caplog: pytest.LogCaptureFixture) -> None:
    # 0 VRAM com permitir_cpu=True deve registrar warning e não falhar
    client = _criar_mock_client({
        "GET /api/ps": (
            200,
            {
                "models": [
                    {
                        "name": "llama3.2:3b",
                        "size": 2000000000,
                        "size_vram": 0,
                    }
                ]
            },
        )
    })
    with caplog.at_level(logging.WARNING):
        resultado = verificar_alocacao_gpu(
            "http://host.docker.internal:11434",
            "llama3.2:3b",
            permitir_cpu=True,
            client=client,
        )

    assert resultado["name"] == "llama3.2:3b"
    assert "ATENÇÃO: O modelo 'llama3.2:3b' está alocado em CPU" in caplog.text


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
                json={"models": [{"name": "llama3.2:3b", "size": 2000, "size_vram": 2000}]},
                request=request,
            )
        if request.url.path == "/api/generate":
            return httpx.Response(200, json={"response": "ok"}, request=request)
        return httpx.Response(404, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    resultado = verificar_alocacao_gpu(
        "http://host.docker.internal:11434",
        "llama3.2:3b",
        permitir_cpu=False,
        client=client,
    )
    assert chamadas_ps == 2
    assert resultado["name"] == "llama3.2:3b"


# --- Teste de Execução Completa ---


def test_executar_checagens_fluxo_completo_sucesso() -> None:
    client = _criar_mock_client({
        "GET /api/version": (200, {"version": "0.32.3"}),
        "GET /api/tags": (200, {"models": [{"name": "llama3.2:3b"}]}),
        "GET /api/ps": (
            200,
            {"models": [{"name": "llama3.2:3b", "size": 2000, "size_vram": 2000}]},
        ),
    })
    config = Configuracao(
        ollama_base_url="http://host.docker.internal:11434",
        ollama_model="llama3.2:3b",
        ollama_timeout=10.0,
        ollama_allow_cpu=False,
        bot_port=8000,
        bot_env="test",
        log_level="INFO",
    )
    # Deve rodar sem lançar exceções
    executar_checagens(config, client=client)
