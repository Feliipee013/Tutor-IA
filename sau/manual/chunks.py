"""Chunking do Manual: um slide por chunk (issue #40, ADR-0011).

Cada página do PDF é um chunk, sem sobreposição: título mais corpo mais OCR,
na ordem de leitura. A Fonte citável é título mais página — o que o Aluno
consegue conferir sozinho no material.

O texto de imagem entra marcado como tal no chunk (`[texto de imagem]`), e
todo o texto passa pela máscara de dados ilustrativos antes de indexar: dado
de exemplo nunca chega ao índice como fato.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sau.manual.extrair import PaginaExtraida
from sau.manual.mascara import e_contato_da_coordenacao, mascarar

logger = logging.getLogger("sau.manual.chunks")

MARCA_OCR = "[texto de imagem]"
"""A marca do texto que veio de figura, e não do texto nativo da página.

Quem lê o chunk sabe o que foi lido da imagem — e é por isso que a marca é
prefixo de cada bloco, e não um campo escondido no metadado."""


@dataclass(frozen=True)
class ChunkManual:
    """Um slide do Manual pronto para indexar: título, página e texto com máscara."""

    titulo: str
    """A primeira linha de texto da página: a primeira metade da Fonte."""

    pagina: int
    """O número da página no PDF: a segunda metade da Fonte."""

    texto: str
    """Corpo mais OCR com a máscara de dados ilustrativos já aplicada."""

    tem_ocr: bool
    """Se algum bloco do texto veio de imagem: rastreio da origem."""

    @property
    def fonte(self) -> str:
        """A Fonte citável: título mais página, como o Aluno confere no material."""
        return f"{self.titulo} (p. {self.pagina})"


def _tem_letra(linha: str) -> bool:
    """Diz se a linha tem ao menos uma letra: número de página não é título."""
    return any(ch.isalpha() for ch in linha)


def _titulo_da_pagina(pagina: PaginaExtraida) -> str:
    """O título do slide: a linha de cabeçalho, ou o número da página.

    A extração numera a página em linha própria, e ela costuma sair primeiro:
    sem o filtro, a Fonte viraria "56 (p. 56)". O cabeçalho do slide é em
    caixa alta, então a primeira linha majoritariamente maiúscula vence; sem
    ela, vale a primeira linha com letra. Slide sem texto nativo (só figura)
    não fica sem Fonte: a página o ancora.
    """
    linhas = [linha.strip() for linha in pagina.texto_nativo.splitlines()]
    linhas = [linha for linha in linhas if linha and _tem_letra(linha)]
    if not linhas:
        return f"Página {pagina.numero}"
    for linha in linhas[:10]:
        letras = [ch for ch in linha if ch.isalpha()]
        maiusculas = sum(1 for ch in letras if ch.isupper())
        if len(letras) >= 4 and maiusculas / len(letras) >= 0.7:
            return linha
    return linhas[0]


def montar_chunks(paginas: list[PaginaExtraida]) -> list[ChunkManual]:
    """Monta um chunk por página: título mais corpo mais OCR, sem sobreposição.

    A ordem dentro do chunk é a de leitura: corpo nativo primeiro, blocos de
    OCR depois, cada um com a marca de imagem. A máscara cobre o chunk
    inteiro, com a exceção do contato da Coordenação de Estágios decidida por
    chunk — trecho normativo de contato preserva telefone e e-mail, o resto
    mascara.
    """
    chunks: list[ChunkManual] = []
    for pagina in paginas:
        titulo = _titulo_da_pagina(pagina)
        partes = [pagina.texto_nativo.strip()] if pagina.texto_nativo.strip() else []
        for bloco in pagina.blocos_ocr:
            partes.append(f"{MARCA_OCR} {bloco.strip()}")
        corpo = "\n".join(partes).strip()
        contato = e_contato_da_coordenacao(titulo, corpo)
        chunks.append(
            ChunkManual(
                titulo=titulo,
                pagina=pagina.numero,
                texto=mascarar(corpo, preservar_contato=contato),
                tem_ocr=bool(pagina.blocos_ocr),
            )
        )
    logger.info("Chunks do Manual: %d trechos de %d páginas.", len(chunks), len(paginas))
    return chunks
