"""Índice vetorial persistente do Manual no Chroma (issue #40, ADR-0011).

O banco é embarcado e persistente: mora no volume nomeado em container (ou
no diretório local no host) e sobrevive ao restart. A coleção é dedicada ao
Manual, e a carga inicial é idempotente pelo `sha256` do PDF — re-ingere
somente quando o conteúdo muda, e reaproveita quando é o mesmo.

Os vetores vêm do `ClienteEmbedding` (`sau/rag/embed.py`), o mesmo embedding
local via Ollama do host: nenhum modelo novo, e os vetores entram e saem
prontos — o Chroma nunca embute sozinho. Por isso a coleção é criada sem
função de embedding própria: `add` recebe `embeddings` e a busca recebe
`query_embeddings`, e a função padrão do Chroma nunca é chamada.

O espaço é cosseno com vetores L2-normalizados, então a pontuação é
`1 - distância`: o mesmo cosseno que `sau/rag/retrieve.py` calcula em
memória, e o que a busca devolve junto da Fonte.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from sau.manual.chunks import montar_chunks
from sau.manual.extrair import extrair_paginas
from sau.manual.hibrido import fundir_ranque_reciproco, ordenar_lexical, tokenizar
from sau.rag.embed import ProtocoloEmbedding, cosseno

logger = logging.getLogger("sau.manual.indice")

CHAVE_SHA_NO_METADADO = "pdf_sha256"
"""A chave do `sha256` do PDF no metadado da coleção: o que diz se re-ingere."""


@dataclass(frozen=True)
class EstadoDoIndice:
    """O resultado da carga no boot: o que foi feito com o índice do Manual."""

    total_chunks: int
    """Quantos chunks o índice guarda depois da carga."""

    reaproveitado: bool
    """Se o índice guardado já era do PDF atual e nada foi re-ingerido."""

    pdf_sha256: str
    """O `sha256` do PDF que o índice guarda: o que o próximo boot compara."""


@dataclass(frozen=True)
class TrechoDoManual:
    """Um trecho devolvido pela busca: texto, Fonte citável e pontuação."""

    titulo: str
    """O título do slide: a primeira metade da Fonte."""

    pagina: int
    """A página no PDF: a segunda metade da Fonte."""

    texto: str
    """O corpo do chunk, com a máscara de dados ilustrativos já aplicada."""

    fonte: str
    """A Fonte citável: título mais página, como o Aluno confere no material."""

    pontuacao: float
    """A similaridade de cosseno entre o chunk e a consulta: por que voltou."""


def sha256_do_pdf(caminho_pdf: Path) -> str:
    """O `sha256` do conteúdo do PDF: a identidade que a idempotência compara."""
    digest = hashlib.sha256()
    with caminho_pdf.open("rb") as arquivo:
        for bloco in iter(lambda: arquivo.read(1024 * 1024), b""):
            digest.update(bloco)
    return digest.hexdigest()


def carregar_ou_indexar(
    caminho_pdf: Path,
    diretorio_chroma: Path,
    nome_colecao: str,
    cliente: ProtocoloEmbedding,
) -> EstadoDoIndice:
    """Indexa o Manual no Chroma, ou reaproveita o índice quando é o mesmo PDF.

    Re-ingere somente quando o conteúdo do PDF muda (o `sha256` guardado no
    metadado da coleção diverge) ou quando o índice está vazio. Cada chunk
    vira um documento com título, página, Fonte e origem do OCR no metadado.
    """
    import chromadb

    sha = sha256_do_pdf(caminho_pdf)
    banco = chromadb.PersistentClient(path=str(diretorio_chroma))
    nomes = {colecao.name for colecao in banco.list_collections()}
    if nome_colecao in nomes:
        colecao = banco.get_collection(nome_colecao)
        metadados = colecao.metadata or {}
        if metadados.get(CHAVE_SHA_NO_METADADO) == sha and colecao.count() > 0:
            total = colecao.count()
            logger.info(
                "Manual reaproveitado: %d chunks do PDF %s já indexados.",
                total,
                caminho_pdf.name,
            )
            return EstadoDoIndice(total_chunks=total, reaproveitado=True, pdf_sha256=sha)
        banco.delete_collection(nome_colecao)
        logger.info("Manual mudou e o índice antigo foi descartado para re-ingestão.")

    colecao = banco.create_collection(
        nome_colecao,
        metadata={CHAVE_SHA_NO_METADADO: sha, "hnsw:space": "cosine"},
    )
    chunks = montar_chunks(extrair_paginas(caminho_pdf))
    textos = [f"{chunk.titulo}\n{chunk.texto}" for chunk in chunks]
    # O `cast` é só de tipo: a lista de vetores normalizados casa com o
    # `Embeddings` do Chroma em execução, e o `Sequence` invariante do stub
    # não prova `list[list[float]]` sem ele. O conteúdo segue verificado pelo
    # `ProtocoloEmbedding`, que é quem produz os vetores.
    vetores = cast(Any, [list(vetor) for vetor in cliente.embutir(textos)])
    colecao.add(
        ids=[f"p{chunk.pagina}-{pos}" for pos, chunk in enumerate(chunks)],
        documents=textos,
        metadatas=[
            {
                "titulo": chunk.titulo,
                "pagina": chunk.pagina,
                "fonte": chunk.fonte,
                "tem_ocr": chunk.tem_ocr,
            }
            for chunk in chunks
        ],
        embeddings=vetores,
    )
    logger.info(
        "Manual indexado: %d chunks do PDF %s na coleção %r.",
        len(chunks),
        caminho_pdf.name,
        nome_colecao,
    )
    return EstadoDoIndice(total_chunks=len(chunks), reaproveitado=False, pdf_sha256=sha)


K_PADRAO = 3
"""Quantos trechos a busca no Manual devolve: o mesmo orçamento da busca em memória."""


def buscar_no_indice(
    diretorio_chroma: Path,
    nome_colecao: str,
    consulta: str,
    cliente: ProtocoloEmbedding,
    k: int = K_PADRAO,
) -> list[TrechoDoManual]:
    """Devolve os `k` chunks mais próximos da consulta, com Fonte e pontuação.

    Índice ausente ou vazio devolve lista vazia: sem material não há o que
    citar, e quem lê isso como ausência de evidência é o turno — não a busca.
    """
    import chromadb

    if k < 1:
        raise ValueError(f"A busca precisa de ao menos um trecho: k foi {k}.")
    banco = chromadb.PersistentClient(path=str(diretorio_chroma))
    if nome_colecao not in {colecao.name for colecao in banco.list_collections()}:
        return []
    colecao = banco.get_collection(nome_colecao)
    if colecao.count() == 0:
        return []
    (vetor_consulta,) = cliente.embutir([consulta])
    resposta: Any = colecao.query(
        query_embeddings=cast(Any, [list(vetor_consulta)]),
        n_results=min(k, colecao.count()),
        include=["documents", "metadatas", "distances"],
    )
    documentos = resposta["documents"][0]
    metadados = resposta["metadatas"][0]
    distancias = resposta["distances"][0]
    trechos: list[TrechoDoManual] = []
    for documento, metadado, distancia in zip(documentos, metadados, distancias, strict=True):
        trechos.append(
            TrechoDoManual(
                titulo=str(metadado["titulo"]),
                pagina=int(metadado["pagina"]),
                texto=str(documento),
                fonte=str(metadado["fonte"]),
                pontuacao=1.0 - float(distancia),
            )
        )
    return trechos


def buscar_hibrida_no_indice(
    diretorio_chroma: Path,
    nome_colecao: str,
    consulta: str,
    cliente: ProtocoloEmbedding,
    k: int = K_PADRAO,
) -> list[TrechoDoManual]:
    """Devolve até `k` trechos fundindo a via vetorial e a lexical por RRF.

    A via vetorial e a lexical são montadas sobre o índice inteiro, lido de
    uma vez com `colecao.get`: nenhum artefato novo é escrito em disco, e o
    índice lexical nasce e morre a cada busca, do próprio Chroma. O RRF
    decide **quem entra** nos `k` candidatos — a via lexical resgata um chunk
    que o vetorial sozinho deixaria de fora —, e o cosseno vetorial decide a
    ordem final e a pontuação exposta. Coleção ausente ou vazia devolve [].
    """
    import chromadb

    if k < 1:
        raise ValueError(f"A busca precisa de ao menos um trecho: k foi {k}.")
    banco = chromadb.PersistentClient(path=str(diretorio_chroma))
    if nome_colecao not in {colecao.name for colecao in banco.list_collections()}:
        return []
    colecao = banco.get_collection(nome_colecao)
    total = colecao.count()
    if total == 0:
        return []
    guardado: Any = colecao.get(include=["documents", "metadatas", "embeddings"])
    documentos = guardado["documents"] or []
    metadados = guardado["metadatas"] or []
    vetores_guardados = guardado["embeddings"]
    if len(documentos) == 0 or vetores_guardados is None:
        return []
    vetores = [[float(valor) for valor in vetor] for vetor in vetores_guardados]
    (vetor_consulta,) = cliente.embutir([consulta])
    similaridades = [cosseno(vetor_consulta, vetor) for vetor in vetores]
    vetorial = sorted(
        range(len(documentos)), key=lambda posicao: similaridades[posicao], reverse=True
    )
    lexical = ordenar_lexical(
        [tokenizar(str(documento)) for documento in documentos],
        tokenizar(consulta),
    )
    candidatos = fundir_ranque_reciproco([vetorial, lexical])[:k]
    candidatos.sort(key=lambda posicao: similaridades[posicao], reverse=True)
    return [
        TrechoDoManual(
            titulo=str(metadados[posicao]["titulo"]),
            pagina=int(metadados[posicao]["pagina"]),
            texto=str(documentos[posicao]),
            fonte=str(metadados[posicao]["fonte"]),
            pontuacao=similaridades[posicao],
        )
        for posicao in candidatos
    ]
