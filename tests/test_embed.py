"""Testes do cliente de embeddings locais, `sau/rag/embed.py`.

O que se prova aqui é o contrato com o Ollama: que o cliente faz
`POST /api/embed` com `input` como lista, que os vetores saem L2-normalizados
e que o cosseno é o produto escalar em Python puro, sem numpy.

Nenhum teste deste arquivo fala com o Ollama real: todo embedding sai de um
`httpx.MockTransport`, no mesmo formato de `tests/test_ollama.py`.
"""

from __future__ import annotations

import json
import math
from typing import Any

import httpx
import pytest

from sau.rag.embed import (
    MODELO_EMBEDDING_PADRAO,
    ClienteEmbedding,
    ErroDeEmbedding,
    cosseno,
    normalizar,
)

_BASE_URL = "http://host.docker.internal:11434"


def _criar_cliente(
    embeddings: list[list[float]], enviados: list[dict[str, Any]]
) -> ClienteEmbedding:
    def handler(request: httpx.Request) -> httpx.Response:
        enviados.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(
            200,
            json={"model": MODELO_EMBEDDING_PADRAO, "embeddings": embeddings},
            request=request,
        )

    return ClienteEmbedding(
        _BASE_URL, client=httpx.Client(transport=httpx.MockTransport(handler))
    )


# --- O que o cliente manda ---


def test_input_vai_como_lista_para_api_embed() -> None:
    enviados: list[dict[str, Any]] = []
    cliente = _criar_cliente([[1.0, 0.0], [0.0, 1.0]], enviados)
    vetores = cliente.embutir(["prazo de entrega", "formato do relatório"])

    assert len(enviados) == 1
    corpo = enviados[0]
    assert corpo["model"] == MODELO_EMBEDDING_PADRAO
    assert corpo["input"] == ["prazo de entrega", "formato do relatório"]
    assert isinstance(corpo["input"], list)
    assert len(vetores) == 2


def test_a_requisicao_vai_para_api_embed() -> None:
    caminhos: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        caminhos.append(request.url.path)
        return httpx.Response(200, json={"embeddings": [[1.0]]}, request=request)

    cliente = ClienteEmbedding(
        _BASE_URL, client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    cliente.embutir(["oi"])

    assert caminhos == ["/api/embed"]


# --- Normalização e cosseno ---


def test_vetores_saem_l2_normalizados() -> None:
    enviados: list[dict[str, Any]] = []
    cliente = _criar_cliente([[3.0, 4.0]], enviados)

    (vetor,) = cliente.embutir(["prazo"])

    assert vetor == pytest.approx([0.6, 0.8])
    assert math.sqrt(sum(x * x for x in vetor)) == pytest.approx(1.0)


def test_normalizar_vetor_zerado_devolve_zeros() -> None:
    """Dividir por zero inventaria direção onde não há nenhuma."""
    assert normalizar([0.0, 0.0, 0.0]) == [0.0, 0.0, 0.0]


def test_cosseno_e_o_produto_escalar() -> None:
    assert cosseno([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosseno([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert cosseno([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)


def test_cosseno_de_tamanhos_diferentes_falha_alto() -> None:
    with pytest.raises(ValueError, match="tamanhos diferentes"):
        cosseno([1.0, 0.0], [1.0])


# --- Falhas ---


def test_quantidade_de_vetores_diferente_dos_textos_falha() -> None:
    enviados: list[dict[str, Any]] = []
    cliente = _criar_cliente([[1.0, 0.0]], enviados)

    with pytest.raises(ErroDeEmbedding, match="FALHA CRÍTICA"):
        cliente.embutir(["um", "dois"])


def test_status_diferente_de_200_falha_com_o_motivo() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "model not found"}, request=request)

    cliente = ClienteEmbedding(
        _BASE_URL, client=httpx.Client(transport=httpx.MockTransport(handler))
    )

    with pytest.raises(ErroDeEmbedding) as exc_info:
        cliente.embutir(["oi"])

    msg = str(exc_info.value)
    assert "FALHA CRÍTICA" in msg
    assert "500" in msg


def test_erro_de_rede_manda_olhar_o_adr_0002() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused")

    cliente = ClienteEmbedding(
        _BASE_URL, client=httpx.Client(transport=httpx.MockTransport(handler))
    )

    with pytest.raises(ErroDeEmbedding) as exc_info:
        cliente.embutir(["oi"])

    assert "ADR-0002" in str(exc_info.value)


def test_modelo_padrao_e_o_medido_no_host() -> None:
    """O nome não é escolhido antes: é o que o ADR-0003 registra por medição."""
    assert MODELO_EMBEDDING_PADRAO == "nomic-embed-text"
