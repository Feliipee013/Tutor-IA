"""Isolamento entre testes dos índices de recuperação.

O índice em memória do Corpus (`sau/rag/retrieve.py`) guarda o último montado
por processo para que a descrição da rodada de medição o leia. A partir do
ADR-0010 o turno não o usa — a recuperação virou ferramenta sobre o Manual
persistente —, mas ele continua existindo e os testes que o exercitam não
podem ver o índice do vizinho. Sem o zero, um teste leria o índice montado por
outro. Produção nunca zera: lá o cache vive enquanto o processo.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from sau.rag.retrieve import limpar_ultimo_indice


@pytest.fixture(autouse=True)
def _indice_do_corpus_limpo() -> Iterator[None]:
    limpar_ultimo_indice()
    yield
    limpar_ultimo_indice()
