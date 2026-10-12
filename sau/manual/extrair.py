"""Extração do Manual de Estágio Obrigatório do Polo a partir do PDF (issue #40).

Cada página rende uma `PaginaExtraida`: o texto nativo na ordem de leitura
mais o OCR em português de cada imagem da página, também em ordem. Imagem
pequena é ampliada antes do OCR, porque letra miúda em figura é o que o
tesseract mais erra.

O que este módulo não faz, de propósito: nada aqui decide o que é chunk nem
o que é máscara. O texto de imagem sai separado em `blocos_ocr`, e quem marca
(`[texto de imagem]`) é o `chunks.py` — que é onde a Fonte citável mora.

Sem o binário do tesseract no sistema, o OCR devolve vazio com aviso no log
em vez de derrubar a ingestão: o texto nativo continua indexável, e a
limitação fica registrada onde o operador lê.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field
from pathlib import Path

import pytesseract  # type: ignore[import-untyped]
from PIL import Image

logger = logging.getLogger("sau.manual.extrair")

IDIOMA_OCR = "por"
"""O idioma do OCR: o Manual é escrito em português."""

LARGURA_MINIMA_PARA_OCR = 400
"""Largura em pixels abaixo da qual a imagem é ampliada antes do OCR.

Figura pequena é letra pequena, e letra pequena é o que o tesseract mais
erra. A ampliação é 2x, que dobra a legibilidade sem inventar pixel: o
filtro LANCZOS interpola, não adivinha.
"""

FATOR_AMPLIACAO = 2


@dataclass(frozen=True)
class PaginaExtraida:
    """Uma página do Manual: número, texto nativo e OCR por imagem, em ordem."""

    numero: int
    """O número da página no PDF, começando em 1: a segunda metade da Fonte."""

    texto_nativo: str
    """O texto embutido da página, na ordem de leitura do PDF."""

    blocos_ocr: list[str] = field(default_factory=list)
    """O OCR de cada imagem da página, na ordem das imagens, sem os vazios."""


def ampliar_imagem_pequena(imagem: bytes) -> bytes:
    """Amplia a imagem 2x quando ela é pequena, para o OCR ler melhor.

    Recebe e devolve PNG: o que entra é o bytes cru da imagem do PDF, e o que
    sai é o que o tesseract lê. Imagem já grande volta como entrou — ampliar
    o que já é legível só gasta tempo.
    """
    figura = Image.open(io.BytesIO(imagem))
    if figura.width >= LARGURA_MINIMA_PARA_OCR:
        return imagem
    ampliada = figura.resize(
        (figura.width * FATOR_AMPLIACAO, figura.height * FATOR_AMPLIACAO),
        Image.Resampling.LANCZOS,
    )
    saida = io.BytesIO()
    ampliada.save(saida, format="PNG")
    logger.debug(
        "Imagem pequena ampliada para o OCR: %dx%d virou %dx%d.",
        figura.width,
        figura.height,
        ampliada.width,
        ampliada.height,
    )
    return saida.getvalue()


def _ocr_disponivel() -> bool:
    """Diz se o tesseract está instalado, sem rodar OCR nenhum.

    É conferido uma vez por extração: sem o binário, cada imagem geraria o
    mesmo aviso, e quarenta avisos iguais no boot escondem o resto do log.
    """
    try:
        pytesseract.get_tesseract_version()
    except Exception:
        return False
    return True


def ler_texto_da_imagem(imagem: bytes) -> str:
    """Roda o OCR em português na imagem e devolve o texto, sem as bordas.

    Sem o tesseract instalado, devolve vazio com aviso: a ingestão segue com
    o texto nativo, e a falta do OCR fica no log em vez de virar exceção no
    boot do `webhook`.
    """
    ampliada = ampliar_imagem_pequena(imagem)
    try:
        texto = str(
            pytesseract.image_to_string(Image.open(io.BytesIO(ampliada)), lang=IDIOMA_OCR)
        )
    except Exception as err:
        logger.warning(
            "OCR indisponível e a imagem da página segue sem texto (%s: %s). "
            "O texto nativo continua indexável.",
            type(err).__name__,
            err,
        )
        return ""
    return texto.strip()


def extrair_paginas(caminho_pdf: Path) -> list[PaginaExtraida]:
    """Extrai cada página do PDF: texto nativo mais OCR por imagem, em ordem.

    A ordem é a de leitura: primeiro o texto nativo da página, depois o OCR
    de cada imagem na ordem em que ela aparece. Bloco de OCR vazio fica de
    fora — figura decorativa não é conteúdo do Manual.
    """
    import pymupdf

    ocr_ok = _ocr_disponivel()
    if not ocr_ok:
        logger.warning(
            "Tesseract ausente e as imagens do Manual seguem sem OCR: só o "
            "texto nativo será indexado. Na imagem do serviço ele existe "
            "(ver Dockerfile); no host, instale `tesseract-ocr` com o pacote "
            "de português."
        )
    paginas: list[PaginaExtraida] = []
    # O `open` do PyMuPDF não é tipado no stub: o `ignore` é só de tipo, e o
    # comportamento é provado pelos testes com PDFs gerados pelo próprio PyMuPDF.
    with pymupdf.open(caminho_pdf) as documento:  # type: ignore[no-untyped-call]
        for numero, pagina in enumerate(documento, start=1):
            nativo = (pagina.get_text("text") or "").strip()
            blocos: list[str] = []
            if not ocr_ok:
                paginas.append(
                    PaginaExtraida(numero=numero, texto_nativo=nativo, blocos_ocr=blocos)
                )
                continue
            for info_imagem in pagina.get_images(full=True):
                xref = info_imagem[0]
                try:
                    extraida = documento.extract_image(xref)
                    texto = ler_texto_da_imagem(extraida["image"])
                except Exception as err:
                    logger.warning(
                        "Imagem da página %d ignorada no OCR (%s: %s).",
                        numero,
                        type(err).__name__,
                        err,
                    )
                    continue
                if texto:
                    blocos.append(texto)
            paginas.append(
                PaginaExtraida(numero=numero, texto_nativo=nativo, blocos_ocr=blocos)
            )
    logger.info("Manual extraído: %d páginas de %s.", len(paginas), caminho_pdf)
    return paginas
