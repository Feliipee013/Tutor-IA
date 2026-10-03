"""Trava do `num_ctx` em 4096.

A janela de contexto não é tocada neste ticket: as seções do Corpus são
curtas de propósito porque 4096 é o que a conversa tem, e um `num_ctx`
mudado em silêncio recarrega o modelo e invalida a medição do ADR-0003.
Este arquivo trava o valor nos dois lugares onde ele mora — a constante do
cliente e o `options` que ele envia — e falha se qualquer um dos dois mexer.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from sau.inference.ollama import NUM_CTX_PADRAO, ClienteOllama

_BASE_URL = "http://host.docker.internal:11434"
_MODELO = "qwen2.5:3b"


def test_num_ctx_padrao_e_4096() -> None:
    assert NUM_CTX_PADRAO == 4096


def test_geracao_envia_num_ctx_4096_por_padrao() -> None:
    enviados: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        enviados.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(
            200,
            json={"response": "oi", "done": True, "done_reason": "stop"},
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        ClienteOllama(_BASE_URL, _MODELO, client=c).responder("oi")

    assert len(enviados) == 1
    assert enviados[0]["options"]["num_ctx"] == 4096
