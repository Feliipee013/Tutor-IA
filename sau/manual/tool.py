"""Ferramenta `buscar_no_manual` para consulta ao Manual de Estágio (issue #36, ADR-0010, ADR-0012).

A ferramenta é opcional para o modelo: saudações e agradecimentos respondem
direto sem consulta, e dúvidas factuais sobre o processo de estágio disparam
a ferramenta.

Ela filtra os resultados por um limiar mínimo de similaridade de cosseno
(padrão 0.35, configurável por ambiente). Trechos abaixo do limiar são
descartados como evidência insuficiente. Quando nenhum trecho atinge o
limiar, a busca devolve resultado vazio sinalizando a ausência de evidência,
o que orienta o modelo a responder com o literal "não encontrei no material"
seguido de Encaminhamento à Coordenação de Estágios.

Cada chamada é registrada em log estruturado com:
- Consulta do Aluno / do modelo
- Pontuações brutas retornadas pelo índice
- Quantidade de descartes pelo limiar
- Fontes efetivamente entregues
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sau.manual.indice import TrechoDoManual, buscar_no_indice
from sau.rag.embed import ProtocoloEmbedding

logger = logging.getLogger("sau.manual.tool")

LIMIAR_SIMILARIDADE_PADRAO = 0.35
"""Limiar inicial de similaridade de cosseno para aceitar um trecho como evidência."""

K_PADRAO = 4
"""Quantidade padrão de trechos solicitados ao índice pelo modelo."""

LITERAL_NAO_ENCONTREI = "não encontrei no material"
"""O literal obrigatório quando não há evidência válida para fato do manual."""


@dataclass(frozen=True)
class TrechoFiltrado:
    """Trecho do manual que atendeu ao limiar mínimo de evidência."""

    titulo: str
    pagina: int
    texto: str
    fonte: str
    pontuacao: float

    def para_dict(self) -> dict[str, Any]:
        """Converte para dicionário serializável para a ferramenta."""
        return {
            "titulo": self.titulo,
            "pagina": self.pagina,
            "texto": self.texto,
            "fonte": self.fonte,
            "pontuacao": round(self.pontuacao, 4),
        }


def buscar_no_manual(
    consulta: str,
    *,
    diretorio_chroma: Path,
    nome_colecao: str,
    cliente: ProtocoloEmbedding,
    k: int = K_PADRAO,
    limiar: float = LIMIAR_SIMILARIDADE_PADRAO,
) -> list[TrechoFiltrado]:
    """Busca trechos no Manual de Estágio Obrigatório aplicando filtro por limiar.

    Registra em log a consulta, todas as pontuações brutas, a quantidade de
    descartes pelo limiar e as Fontes retornadas.
    """
    consulta_limpa = consulta.strip()
    if not consulta_limpa:
        logger.info(
            "Consulta ao manual vazia: nenhum trecho buscado. descartes=0 fontes=[]"
        )
        return []

    trechos_brutos: list[TrechoDoManual] = buscar_no_indice(
        diretorio_chroma=diretorio_chroma,
        nome_colecao=nome_colecao,
        consulta=consulta_limpa,
        cliente=cliente,
        k=k,
    )

    pontuacoes_brutas = [round(t.pontuacao, 4) for t in trechos_brutos]
    trechos_validos: list[TrechoFiltrado] = []
    descartes = 0

    for t in trechos_brutos:
        if t.pontuacao >= limiar:
            trechos_validos.append(
                TrechoFiltrado(
                    titulo=t.titulo,
                    pagina=t.pagina,
                    texto=t.texto,
                    fonte=t.fonte,
                    pontuacao=t.pontuacao,
                )
            )
        else:
            descartes += 1

    fontes_entregues = [t.fonte for t in trechos_validos]

    logger.info(
        "Consulta ao manual: %r | pontuacoes=%s | descartes_limiar=%d (limiar=%.2f) | fontes_entregues=%s",
        consulta_limpa,
        pontuacoes_brutas,
        descartes,
        limiar,
        fontes_entregues,
    )

    return trechos_validos
