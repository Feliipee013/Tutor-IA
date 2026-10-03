"""Cliente de embeddings locais via Ollama do host.

O modelo de embedding foi escolhido por medição, não antes: `ollama ps` com o
gerador `qwen2.5:3b` e o candidato carregados, contra o orçamento de ~1 GB que
o ADR-0003 reserva para embedding. O resultado está registrado no próprio
ADR-0003, que é onde o orçamento de VRAM vive.

Três decisões estão no código:

- **`input` como lista.** O `/api/embed` do Ollama recebe a lista inteira de
  uma vez, e é assim que o índice embute as seções do Corpus sem uma chamada
  por seção.
- **Vetores L2-normalizados na saída.** O Ollama já devolve vetores próximos
  da norma unitária, e normalizar aqui deixa a invariante no contrato em vez
  de na sorte da versão do servidor.
- **Cosseno como produto escalar, em Python puro, sem numpy.** Com vetores
  normalizados, a similaridade de cosseno é o produto escalar — e a conta é
  uma soma, que não precisa de dependência nova no `pyproject.toml`.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Protocol

import httpx

logger = logging.getLogger("sau.rag.embed")

MODELO_EMBEDDING_PADRAO = "nomic-embed-text"
"""Modelo de embedding medido no host e registrado no ADR-0003.

274 MB de pesos, 323 MB residentes a 100% GPU, 768 dimensões: cabe ao lado do
gerador dentro do orçamento de ~1 GB, e o `ollama ps` que prova está
transcrito no ADR.
"""

TIMEOUT_PADRAO = 60.0
"""Tempo de espera do embedding quando ninguém informa outro, em segundos.

É a mesma rede de segurança do cliente de geração: quem embute o Corpus chama
na mão, fora do turno do Aluno.
"""


class ErroDeEmbedding(RuntimeError):
    """Falha ao pedir embeddings ao Ollama."""


class ProtocoloEmbedding(Protocol):
    """O que o índice precisa de quem embute: vetores e o nome do modelo.

    Existe para que `montar_indice` receba tanto o `ClienteEmbedding` quanto
    o `ClienteOllama` sem parâmetro novo no grafo: o cliente do turno carrega
    o embedding junto da geração, e a recuperação entra sem assinatura nova.
    """

    @property
    def modelo_embedding(self) -> str:
        """O modelo que produziu os vetores, para a rodada declarar o que usou."""
        ...

    def embutir(self, textos: list[str]) -> list[list[float]]:
        """Embute a lista de textos e devolve um vetor normalizado por texto."""
        ...


def normalizar(vetor: list[float]) -> list[float]:
    """Devolve o vetor com norma L2 unitária, em Python puro.

    Vetor zerado volta zerado: dividir por zero inventaria direção onde não há
    nenhuma, e direção inventada em índice de recuperação é falso positivo.
    """
    norma = math.sqrt(sum(x * x for x in vetor))
    if norma == 0.0:
        return [0.0 for _ in vetor]
    return [x / norma for x in vetor]


def cosseno(a: list[float], b: list[float]) -> float:
    """Similaridade de cosseno entre dois vetores já normalizados.

    É o produto escalar porque a norma é 1 dos dois lados — e é por isso que
    `embutir` normaliza na saída: quem compara não precisa lembrar de
    normalizar antes. Vetores de tamanhos diferentes falham alto em vez de
    compararem o prefixo em silêncio.
    """
    if len(a) != len(b):
        raise ValueError(
            f"Vetores de tamanhos diferentes não se comparam: {len(a)} contra {len(b)}."
        )
    return sum(x * y for x, y in zip(a, b, strict=True))


class ClienteEmbedding:
    """Fala com o `/api/embed` do Ollama no host e devolve vetores normalizados.

    `client` existe para os testes, que montam um `httpx.MockTransport` no
    mesmo formato de `tests/test_ollama.py`. Sem ele, cada chamada abre e
    fecha uma conexão.
    """

    def __init__(
        self,
        base_url: str,
        modelo: str = MODELO_EMBEDDING_PADRAO,
        timeout: float = TIMEOUT_PADRAO,
        client: httpx.Client | None = None,
    ) -> None:
        self._url = f"{base_url.rstrip('/')}/api/embed"
        self._modelo = modelo
        self._timeout = timeout
        self._client = client

    @property
    def modelo_embedding(self) -> str:
        """O modelo que produz os vetores: o que a rodada declara como usado."""
        return self._modelo

    def embutir(self, textos: list[str]) -> list[list[float]]:
        """Embute a lista de textos e devolve um vetor normalizado por texto.

        A ordem de saída é a de entrada: o vetor `i` é o texto `i`, e é assim
        que o índice casa cada vetor com a seção do Corpus que o originou.
        """
        bruto = self._pedir({"model": self._modelo, "input": textos})
        vetores = bruto.get("embeddings")
        if not isinstance(vetores, list) or not all(isinstance(v, list) for v in vetores):
            raise ErroDeEmbedding(
                f"FALHA CRÍTICA: o Ollama não devolveu uma lista de vetores no embedding do "
                f"modelo '{self._modelo}'. O que veio: {sorted(bruto)}."
            )
        if len(vetores) != len(textos):
            raise ErroDeEmbedding(
                f"FALHA CRÍTICA: o Ollama devolveu {len(vetores)} vetores para {len(textos)} "
                f"textos no modelo '{self._modelo}': a ordem não casa mais com as seções."
            )
        normalizados = [normalizar([float(x) for x in vetor]) for vetor in vetores]
        logger.info(
            "Embedding do modelo '%s': %d textos, %d dimensões.",
            self._modelo,
            len(textos),
            len(normalizados[0]) if normalizados else 0,
        )
        return normalizados

    def _pedir(self, payload: dict[str, Any]) -> dict[str, Any]:
        """POST em `/api/embed` e devolve o JSON do Ollama."""
        try:
            if self._client is not None:
                resp = self._client.post(self._url, json=payload, timeout=self._timeout)
            else:
                with httpx.Client() as c:
                    resp = c.post(self._url, json=payload, timeout=self._timeout)
        except httpx.TimeoutException as err:
            raise ErroDeEmbedding(
                f"FALHA CRÍTICA: o modelo de embedding '{self._modelo}' não respondeu em "
                f"{self._timeout:.0f}s."
            ) from err
        except httpx.HTTPError as err:
            raise ErroDeEmbedding(
                f"FALHA CRÍTICA: não consegui falar com o Ollama em {self._url}: {err}. "
                "Confira se o serviço está rodando no host e se o container alcança "
                "a porta 11434 (ver ADR-0002)."
            ) from err

        if resp.status_code != 200:
            raise ErroDeEmbedding(
                f"FALHA CRÍTICA: o Ollama respondeu {resp.status_code} ao pedir embedding do "
                f"modelo '{self._modelo}': {resp.text}"
            )

        try:
            dados = resp.json()
        except ValueError as err:
            raise ErroDeEmbedding(
                f"FALHA CRÍTICA: o Ollama devolveu algo que não é JSON ao pedir embedding do "
                f"modelo '{self._modelo}'."
            ) from err

        if not isinstance(dados, dict):
            raise ErroDeEmbedding(
                f"FALHA CRÍTICA: o Ollama devolveu {type(dados).__name__} no lugar de um "
                f"objeto JSON ao pedir embedding do modelo '{self._modelo}'."
            )

        return dados
