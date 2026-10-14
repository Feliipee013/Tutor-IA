"""Testes da recuperação híbrida (lexical + vetorial + RRF + re-rank).

O BM25 é puro em memória, sem dependência nova. O RRF funde as listas e a
ordenação final (e a pontuação) continua sendo o cosseno vetorial. A via
lexical só amplia o conjunto de candidatos, de modo que um chunk achado
apenas pela via lexical (BM25 alto, cosseno acima do limiar) entre mesmo
fora do top-k vetorial.

Nenhum teste deste arquivo fala com o Ollama: o embedding é falso e os PDFs
são gerados com o próprio PyMuPDF em `tmp_path`. O vocabulário é o do
`CONTEXT.md`.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from sau.manual.hibrido import (
    fundir_ranque_reciproco,
    ordenar_lexical,
    pontuacoes_bm25,
    tokenizar,
)
from sau.manual.indice import buscar_hibrida_no_indice, carregar_ou_indexar
from sau.manual.tool import buscar_no_manual

_COLECAO = "manual-hibrido-teste"


def _pdf_com_paginas(destino: Path, paginas: list[str], nome: str = "manual.pdf") -> Path:
    """Gera um PDF mínimo com uma página por texto, com o próprio PyMuPDF."""
    import pymupdf

    caminho = destino / nome
    documento = pymupdf.open()  # type: ignore[no-untyped-call]
    for texto in paginas:
        pagina = documento.new_page()
        pagina.insert_text((72, 72), texto)
    documento.save(caminho)  # type: ignore[no-untyped-call]
    documento.close()  # type: ignore[no-untyped-call]
    return caminho


class FalsoEmbedding:
    """Embedding falso por palavra-chave, já L2-normalizado, sem Ollama.

    `prazo` fica na direção do eixo x; `seguro` entra a 0.6 de cosseno dela;
    o resto vai para o eixo y. O que se prova é o mecanismo — Fonte,
    pontuação e fusão —, e não o sentido de uma pergunta real do Aluno.
    """

    modelo_embedding = "falso-para-teste-hibrido"

    def __init__(self) -> None:
        self.chamadas: list[list[str]] = []

    def embutir(self, textos: list[str]) -> list[list[float]]:
        self.chamadas.append(list(textos))
        vetores: list[list[float]] = []
        for texto in textos:
            minusculo = texto.lower()
            if "prazo" in minusculo:
                vetores.append([1.0, 0.0, 0.0])
            elif "seguro" in minusculo or "apólice" in minusculo or "apolice" in minusculo:
                vetores.append([0.6, 0.8, 0.0])
            else:
                vetores.append([0.0, 1.0, 0.0])
        return vetores


# --- BM25 e RRF: as peças puras ---


def test_tokenizar_remove_acento_e_ignora_pontuacao() -> None:
    assert tokenizar("Estágio, obrigatório!") == ["estagio", "obrigatorio"]
    assert tokenizar("") == []


def test_bm25_ranqueia_primeiro_o_termo_exato_ainda_que_raro() -> None:
    documentos = [
        tokenizar("o prazo de entrega do relatório é curto"),
        tokenizar("modelo empresa documento"),
        tokenizar("carga horária do estágio de serviço social"),
    ]
    consulta = tokenizar("modelo empresa")
    pontuacoes = pontuacoes_bm25(documentos, consulta)
    assert pontuacoes[1] > 0.0
    assert pontuacoes[0] == 0.0
    assert ordenar_lexical(documentos, consulta)[0] == 1


def test_ordenar_lexical_exclui_documentos_sem_correspondencia() -> None:
    documentos = [tokenizar("prazo"), tokenizar("seguro"), tokenizar("prazo seguro")]
    ordem = ordenar_lexical(documentos, tokenizar("prazo"))
    assert 1 not in ordem
    assert set(ordem) == {0, 2}


def test_rrf_sobe_o_chunk_presente_nas_duas_listas() -> None:
    # O documento 2 é o primeiro nas duas vias: o RRF o leva ao topo, acima do
    # 0 e do 1, que aparecem bem colocados em apenas uma das listas.
    primeira = [2, 0, 1]
    segunda = [2, 1, 0]
    assert fundir_ranque_reciproco([primeira, segunda])[0] == 2
    assert fundir_ranque_reciproco([]) == []


# --- A busca híbrida integrada ao índice ---


def test_buscar_hibrida_devolve_trechos_com_fonte_e_cosseno(tmp_path: Path) -> None:
    pdf = _pdf_com_paginas(
        tmp_path,
        [
            "CAMPO DE ESTÁGIO | EMPRESA\nA empresa precisa de convênio.",
            "SUPERVISOR DE CAMPO\nQuem valida no campo.",
            "SUPERVISOR ACADÊMICO\nQuem orienta na instituição.",
        ],
    )
    chroma = tmp_path / "chroma"
    carregar_ou_indexar(pdf, chroma, _COLECAO, FalsoEmbedding())

    trechos = buscar_hibrida_no_indice(chroma, _COLECAO, "convênio empresa", FalsoEmbedding())

    assert len(trechos) == 3
    assert all(0.0 <= trecho.pontuacao <= 1.0 for trecho in trechos)
    assert all(trecho.fonte.endswith(f"(p. {trecho.pagina})") for trecho in trechos)


def test_buscar_hibrida_resgata_chunk_so_da_via_lexical(tmp_path: Path) -> None:
    # O embedding da consulta cai perto do vizinho vetorial (doc longo) e longe
    # do raro (cosseno 0.2). Com k=1, a via vetorial pura devolveria o vizinho;
    # a híbrida resgata o raro, que só se acha por BM25.
    class EmbeddingVizinho:
        modelo_embedding = "falso-resgate"

        def embutir(self, textos: list[str]) -> list[list[float]]:
            vetores: list[list[float]] = []
            for texto in textos:
                minusculo = texto.lower()
                if "vizinho" in minusculo:
                    vetores.append([1.0, 0.0])
                elif "raro" in minusculo:
                    vetores.append([0.2, 0.9797958971])
                else:
                    vetores.append([1.0, 0.0])  # a consulta cai perto do vizinho
            return vetores

    pdf = _pdf_com_paginas(
        tmp_path,
        [
            "VIZINHO\nvizinho vizinho texto longo de recheio",
            "RARO\numa menção única a termoexato",
        ],
    )
    chroma = tmp_path / "chroma"
    carregar_ou_indexar(pdf, chroma, _COLECAO, EmbeddingVizinho())

    hibrido = buscar_hibrida_no_indice(chroma, _COLECAO, "termoexato", EmbeddingVizinho(), k=1)

    assert len(hibrido) == 1
    assert hibrido[0].titulo == "RARO"
    assert hibrido[0].pontuacao > 0.0  # o cosseno do raro, não o do vizinho


def test_buscar_hibrida_indice_ausente_devolve_vazio(tmp_path: Path) -> None:
    trechos = buscar_hibrida_no_indice(tmp_path / "sem-chroma", _COLECAO, "prazo", FalsoEmbedding())
    assert trechos == []


def test_buscar_hibrida_recusa_k_invalido(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        buscar_hibrida_no_indice(tmp_path, _COLECAO, "prazo", FalsoEmbedding(), k=0)


# --- O contrato da ferramenta: limiar e log inalterados ---


def test_buscar_no_manual_segue_filtrando_limiar_e_logando(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    pdf = _pdf_com_paginas(tmp_path, ["TÍTULO DO SLIDE\nA apólice cobre acidentes pessoais."])
    chroma = tmp_path / "chroma"
    carregar_ou_indexar(pdf, chroma, _COLECAO, FalsoEmbedding())

    caplog.set_level(logging.INFO, logger="sau.manual.tool")
    # A consulta "prazo" embute no eixo x; o chunk "seguro" fica a 0.6 de
    # cosseno — passa com limiar 0.1 e é descartado com limiar 0.99.
    trechos = buscar_no_manual(
        "prazo",
        diretorio_chroma=chroma,
        nome_colecao=_COLECAO,
        cliente=FalsoEmbedding(),
        k=3,
        limiar=0.1,
    )
    assert trechos
    mensagem = caplog.records[-1].getMessage()
    assert "pontuacoes=" in mensagem
    assert "descartes_limiar=" in mensagem
    assert "fontes_entregues=" in mensagem

    assert (
        buscar_no_manual(
            "prazo",
            diretorio_chroma=chroma,
            nome_colecao=_COLECAO,
            cliente=FalsoEmbedding(),
            k=3,
            limiar=0.99,
        )
        == []
    )
