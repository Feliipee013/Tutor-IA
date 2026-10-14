"""Ferramenta `buscar_no_manual` para consulta ao Manual de Estágio (issue #36, ADR-0010, ADR-0012).

A ferramenta é opcional para o modelo: saudações e agradecimentos respondem
direto sem consulta, e dúvidas factuais sobre o processo de estágio disparam
a ferramenta.

Ela filtra os resultados por um limiar mínimo de similaridade de cosseno.
Trechos abaixo do limiar são descartados como evidência insuficiente. Quando
nenhum trecho atinge o limiar, a busca devolve resultado vazio sinalizando a
ausência de evidência, o que orienta o modelo a responder com o literal "não
encontrei no material" seguido de Encaminhamento à Coordenação de Estágios.

O limiar e o `k` **não** têm padrão aqui: são configuração do serviço
(`manual_limiar_similaridade` e `manual_k_padrao`, ver `sau/config.py`), e o
turno os repassa. Um default no módulo seria uma segunda fonte para o mesmo
número — e a que ninguém ajusta pelo ambiente.

Cada chamada é registrada em log estruturado com:
- Consulta do Aluno / do modelo
- Pontuações brutas retornadas pelo índice
- Quantidade de descartes pelo limiar
- Fontes efetivamente entregues
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sau.manual.indice import TrechoDoManual, buscar_hibrida_no_indice
from sau.rag.embed import ProtocoloEmbedding

logger = logging.getLogger("sau.manual.tool")

NOME_DA_FERRAMENTA = "buscar_no_manual"
"""O nome da ferramenta como o modelo a chama e como o turno a executa."""

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
    k: int,
    limiar: float,
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

    trechos_brutos: list[TrechoDoManual] = buscar_hibrida_no_indice(
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
        "Consulta ao manual: %r | pontuacoes=%s | descartes_limiar=%d (limiar=%.2f) "
        "| fontes_entregues=%s",
        consulta_limpa,
        pontuacoes_brutas,
        descartes,
        limiar,
        fontes_entregues,
    )

    return trechos_validos


def esquema_da_ferramenta(*, k_padrao: int) -> dict[str, Any]:
    """O schema da ferramenta no formato de `tools` do Ollama (`/api/chat`).

    O `k` é declarado como opcional e com o padrão do serviço no texto da
    descrição: o modelo pode pedir mais trechos numa pergunta que cruza
    assuntos, e quando não pede é o `k_padrao` da configuração que vale.
    """
    return {
        "type": "function",
        "function": {
            "name": NOME_DA_FERRAMENTA,
            "description": (
                "Busca trechos no Manual de Estágio Obrigatório do Polo. Chame "
                "somente quando precisar de um fato do manual (prazos, "
                "documentos, assinaturas, seguro, cadastro). Não chame para "
                "saudação, despedida ou agradecimento."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "consulta": {
                        "type": "string",
                        "description": "A dúvida do Aluno, em linguagem natural.",
                    },
                    "k": {
                        "type": "integer",
                        "description": (
                            "Quantos trechos trazer. Use o padrão "
                            f"({k_padrao}) na maioria dos casos."
                        ),
                        "minimum": 1,
                    },
                },
                "required": ["consulta"],
            },
        },
    }


def executar_chamada(
    argumentos: Mapping[str, Any],
    *,
    diretorio_chroma: Path,
    nome_colecao: str,
    cliente: ProtocoloEmbedding,
    k_padrao: int,
    limiar: float,
) -> list[TrechoFiltrado]:
    """Executa uma chamada da ferramenta a partir dos argumentos do modelo.

    A consulta e o `k` vêm do que o modelo mandou; o que faltar ou não for
    utilizável cai no padrão da configuração em vez de derrubar o turno — o
    argumento de uma ferramenta é saída de modelo, e saída de modelo não é
    entrada confiável.
    """
    consulta = str(argumentos.get("consulta", ""))
    k = _k_utilizavel(argumentos.get("k"), k_padrao)
    return buscar_no_manual(
        consulta,
        diretorio_chroma=diretorio_chroma,
        nome_colecao=nome_colecao,
        cliente=cliente,
        k=k,
        limiar=limiar,
    )


def formatar_para_o_modelo(trechos: list[TrechoFiltrado]) -> str:
    """Serializa os trechos como o `tool` message que volta ao modelo.

    Lista vazia vira o aviso de ausência de evidência em vez de `[]`: o modelo
    precisa ler que a busca não achou nada, e não um JSON que ele teria de
    interpretar como "sem resultado".
    """
    if not trechos:
        return "Nenhum trecho do manual passou pelo limiar de similaridade."
    return json.dumps(
        [trecho.para_dict() for trecho in trechos], ensure_ascii=False
    )


def _k_utilizavel(bruto: Any, k_padrao: int) -> int:
    """O `k` pedido pelo modelo, ou o padrão quando ele não serve."""
    try:
        k = int(bruto)
    except (TypeError, ValueError):
        return k_padrao
    return k if k >= 1 else k_padrao
