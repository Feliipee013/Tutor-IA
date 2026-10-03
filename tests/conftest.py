"""Isolamento entre testes do índice da recuperação.

O índice do Corpus vive no cache do módulo (`sau.graph.nodes`) para
sobreviver à remontagem do grafo a cada turno — e, por isso, sobreviveria
também ao fim do teste. Sem o zero, um teste contaria as chamadas de
embedding do teste anterior ("primeiro turno embute o Corpus" só seria
verdade no primeiro do processo), e um transporte falso com vetores
diferentes leria o índice do vizinho. Produção nunca zera: lá o cache vive
enquanto o processo.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from sau.graph.nodes import limpar_cache_recuperacao
from sau.rag.retrieve import limpar_ultimo_indice


@pytest.fixture(autouse=True)
def _cache_da_recuperacao_limpo() -> Iterator[None]:
    limpar_cache_recuperacao()
    limpar_ultimo_indice()
    yield
    limpar_cache_recuperacao()
    limpar_ultimo_indice()
