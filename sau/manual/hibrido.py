"""Recuperação híbrida lexical + vetorial para o Manual (issue #39).

Soma à via vetorial uma via lexical (BM25 em memória, Python puro, sem
dependência nova) e funde as duas por ranque recíproco (RRF). O cosseno
vetorial continua mandando: ele decide a ordem final e a pontuação exposta,
e o limiar segue aplicado sobre ele. A via lexical só amplia o conjunto de
candidatos, o que permite um chunk raro — termo exato que o embedding não
aproximou — entrar mesmo fora do top-k vetorial.

A tokenização normaliza diacríticos para que "estagio" case "estágio".
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter

PADRAO_TOKEN = re.compile(r"[a-z0-9]+")
"""O que conta como token: sequência alfanumérica depois da normalização."""

K1_PADRAO = 1.5
"""Saturação da frequência do termo no BM25."""

B_PADRAO = 0.75
"""Peso da normalização pelo tamanho do documento no BM25."""

CONSTANTE_RRF_PADRAO = 60
"""A constante do RRF: achata a diferença de posição entre as listas."""


def tokenizar(texto: str) -> list[str]:
    """Normaliza o texto e devolve os tokens em minúsculas, sem diacríticos.

    O acento sai (NFKD mais remoção de combining) porque consulta e material
    não escrevem a mesma palavra do mesmo jeito: "estagio" precisa casar
    "estágio" para a via lexical somar em vez de errar por grafia.
    """
    if not texto:
        return []
    decomposto = unicodedata.normalize("NFKD", texto.lower())
    sem_diacriticos = "".join(c for c in decomposto if not unicodedata.combining(c))
    return PADRAO_TOKEN.findall(sem_diacriticos)


def _idf(documentos_tokens: list[list[str]], total: int) -> dict[str, float]:
    """O IDF de cada termo: o quanto ele distingue um documento dos demais."""
    frequencia_documental: Counter[str] = Counter()
    for tokens in documentos_tokens:
        frequencia_documental.update(set(tokens))
    return {
        termo: math.log((total - ocorrencias + 0.5) / (ocorrencias + 0.5) + 1.0)
        for termo, ocorrencias in frequencia_documental.items()
    }


def pontuacoes_bm25(
    documentos_tokens: list[list[str]],
    consulta_tokens: list[str],
    k1: float = K1_PADRAO,
    b: float = B_PADRAO,
) -> list[float]:
    """A pontuação BM25 de cada documento para a consulta, em Python puro.

    Devolve uma pontuação por documento, na mesma ordem dos documentos; zero
    quando nenhum termo da consulta aparece. É o BM25 clássico, com a
    normalização pelo tamanho médio controlada por `b`.
    """
    if not documentos_tokens:
        return []
    consulta_limpa = [termo for termo in consulta_tokens if termo]
    if not consulta_limpa:
        return [0.0] * len(documentos_tokens)

    total = len(documentos_tokens)
    tamanho_medio = sum(len(tokens) for tokens in documentos_tokens) / total
    idf = _idf(documentos_tokens, total)
    pontuacoes: list[float] = []

    for tokens in documentos_tokens:
        frequencias = Counter(tokens)
        tamanho = len(tokens)
        pontuacao = 0.0
        for termo in consulta_limpa:
            frequencia = frequencias.get(termo, 0)
            if frequencia == 0:
                continue
            numerador = frequencia * (k1 + 1)
            if tamanho_medio > 0:
                denominador = frequencia + k1 * (1 - b + b * tamanho / tamanho_medio)
            else:
                denominador = frequencia + k1
            pontuacao += idf.get(termo, 0.0) * numerador / denominador
        pontuacoes.append(pontuacao)
    return pontuacoes


def ordenar_lexical(
    documentos_tokens: list[list[str]],
    consulta_tokens: list[str],
) -> list[int]:
    """As posições dos documentos por BM25 decrescente, só as de score > 0.

    Documento sem correspondência fica fora da lista: a via lexical só
    acrescenta candidato com evidência lexical, e não dilui a fusão com o
    resto do índice.
    """
    pontuacoes = pontuacoes_bm25(documentos_tokens, consulta_tokens)
    posicoes = list(range(len(pontuacoes)))
    posicoes.sort(key=lambda posicao: pontuacoes[posicao], reverse=True)
    return [posicao for posicao in posicoes if pontuacoes[posicao] > 0.0]


def fundir_ranque_reciproco(
    listas: list[list[int]],
    constante: int = CONSTANTE_RRF_PADRAO,
) -> list[int]:
    """Funde listas de posições por RRF e devolve as posições fundidas.

    Cada lista contribui com `1 / (constante + posição)` por documento, e o
    documento que aparece bem colocado nas duas listas sobe: é o que dá à
    via lexical o poder de resgatar um chunk que o vetorial sozinho deixaria
    de fora.
    """
    soma: dict[int, float] = {}
    for lista in listas:
        for posicao, documento in enumerate(lista):
            soma[documento] = soma.get(documento, 0.0) + 1.0 / (constante + posicao + 1)
    return sorted(soma, key=lambda documento: soma[documento], reverse=True)
