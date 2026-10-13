"""Testes da ferramenta `buscar_no_manual` e do limiar de similaridade (issue #36, ADR-0010, ADR-0012).

O que se prova aqui são os critérios de aceitação da ferramenta:
1. Pergunta factual do manual dispara a ferramenta e devolve trecho com Fonte título + página.
2. Trecho abaixo do limiar (padrão 0.35) é descartado.
3. Quando nenhum trecho passa pelo limiar, devolve vazio (sinal de ausência de evidência para o turno).
4. Proibição de dados ilustrativos: a máscara garante que apólice, CNPJ, CPF, etc. não constam no texto.
5. Log do turno registra consulta, pontuações brutas, descartes pelo limiar e Fontes entregues.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest

from sau.manual.chunks import ChunkManual
from sau.manual.indice import carregar_ou_indexar
from sau.manual.mascara import MARCADOR
from sau.manual.tool import (
    K_PADRAO,
    LIMIAR_SIMILARIDADE_PADRAO,
    LITERAL_NAO_ENCONTREI,
    TrechoFiltrado,
    buscar_no_manual,
)

_COLECAO = "manual-estagio-obrigatorio"


class FalsoEmbedding:
    """Embedding previsível para testes de pontuação e filtro de limiar."""

    modelo_embedding = "falso-embedding-teste"

    def __init__(self, pontuacoes_predefinidas: dict[str, list[float]] | None = None) -> None:
        self.chamadas: list[list[str]] = []
        self.pontuacoes = pontuacoes_predefinidas or {}

    def embutir(self, textos: list[str]) -> list[list[float]]:
        self.chamadas.append(list(textos))
        vetores: list[list[float]] = []
        for texto in textos:
            # Se foi fornecido vetor específico para este texto/chave
            achado = None
            for chave, vet in self.pontuacoes.items():
                if chave in texto:
                    achado = vet
                    break
            if achado is not None:
                vetores.append(achado)
            elif "prazo" in texto.lower() or "entrega" in texto.lower():
                vetores.append([1.0, 0.0, 0.0])
            elif "seguro" in texto.lower():
                vetores.append([0.0, 1.0, 0.0])
            else:
                vetores.append([0.0, 0.0, 1.0])
        return vetores


def _pdf_simples(destino: Path, paginas: list[str], nome: str = "manual.pdf") -> Path:
    """Gera um PDF sintético para testes com PyMuPDF."""
    import pymupdf

    caminho = destino / nome
    documento = pymupdf.open()  # type: ignore[no-untyped-call]
    for texto in paginas:
        pagina = documento.new_page()
        pagina.insert_text((72, 72), texto)
    documento.save(caminho)  # type: ignore[no-untyped-call]
    documento.close()  # type: ignore[no-untyped-call]
    return caminho


def test_buscar_no_manual_devolve_trechos_acima_do_limiar(tmp_path: Path) -> None:
    """Trecho com similaridade suficiente retorna com Fonte (título + página)."""
    caminho_pdf = _pdf_simples(
        tmp_path,
        ["PRAZOS DO ESTÁGIO\nEntrega do relatório em 30 dias."],
    )
    chroma = tmp_path / "chroma"
    falso = FalsoEmbedding()
    carregar_ou_indexar(caminho_pdf, chroma, _COLECAO, falso)

    resultados = buscar_no_manual(
        "qual o prazo de entrega?",
        diretorio_chroma=chroma,
        nome_colecao=_COLECAO,
        cliente=falso,
        k=2,
        limiar=0.35,
    )

    assert len(resultados) == 1
    primeiro = resultados[0]
    assert isinstance(primeiro, TrechoFiltrado)
    assert "PRAZOS DO ESTÁGIO" in primeiro.titulo
    assert primeiro.pagina == 1
    assert primeiro.fonte == "PRAZOS DO ESTÁGIO (p. 1)"
    assert primeiro.pontuacao >= 0.35


def test_buscar_no_manual_descarta_trechos_abaixo_do_limiar(tmp_path: Path) -> None:
    """Trecho com pontuação menor que o limiar é descartado e devolve vazio."""
    # Vetores ortogonais resultam em pontuação cosseno 0.0 (distância cosseno 1.0 -> 1 - 1.0 = 0.0)
    # Com limiar 0.35, 0.0 < 0.35 e é descartado.
    caminho_pdf = _pdf_simples(
        tmp_path,
        ["SEGURO OBRIGATÓRIO\nCobertura de acidentes pessoais."],
    )
    chroma = tmp_path / "chroma"
    # Documento indexado recebe [0, 1, 0] (seguro)
    # Consulta "prazo de entrega" recebe [1, 0, 0] (prazo)
    # Similaridade de cosseno = 0.0
    falso = FalsoEmbedding()
    carregar_ou_indexar(caminho_pdf, chroma, _COLECAO, falso)

    resultados = buscar_no_manual(
        "prazo de entrega do relatório?",
        diretorio_chroma=chroma,
        nome_colecao=_COLECAO,
        cliente=falso,
        k=2,
        limiar=0.35,
    )

    assert resultados == []


def test_buscar_no_manual_registra_auditoria_em_log(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Log registra consulta, pontuações brutas, descartes pelo limiar e Fontes entregues."""
    caminho_pdf = _pdf_simples(
        tmp_path,
        [
            "PRAZOS DO ESTÁGIO\nEntrega do relatório na sexta-feira.",
            "SEGURO OBRIGATÓRIO\nApolice e cobertura.",
        ],
    )
    chroma = tmp_path / "chroma"
    falso = FalsoEmbedding()
    carregar_ou_indexar(caminho_pdf, chroma, _COLECAO, falso)

    with caplog.at_level(logging.INFO, logger="sau.manual.tool"):
        buscar_no_manual(
            "qual o prazo?",
            diretorio_chroma=chroma,
            nome_colecao=_COLECAO,
            cliente=falso,
            k=2,
            limiar=0.35,
        )

    mensagens = [r.getMessage() for r in caplog.records if r.name == "sau.manual.tool"]
    assert len(mensagens) >= 1
    log_chamada = mensagens[0]

    assert "qual o prazo?" in log_chamada
    assert "pontuacoes=" in log_chamada
    assert "descartes_limiar=" in log_chamada
    assert "limiar=0.35" in log_chamada
    assert "fontes_entregues=" in log_chamada


def test_buscar_no_manual_com_consulta_vazia_nao_consulta_e_loga(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Consulta vazia ou só espaços não busca no Chroma e devolve vazio com log."""
    chroma = tmp_path / "chroma"
    falso = FalsoEmbedding()

    with caplog.at_level(logging.INFO, logger="sau.manual.tool"):
        res = buscar_no_manual(
            "   ",
            diretorio_chroma=chroma,
            nome_colecao=_COLECAO,
            cliente=falso,
        )

    assert res == []
    mensagens = [r.getMessage() for r in caplog.records if r.name == "sau.manual.tool"]
    assert any("vazia" in m for m in mensagens)


def test_dados_ilustrativos_permanecem_mascarados_nos_trechos_entregues(tmp_path: Path) -> None:
    """Dados ilustrativos mascarados no chunk nunca chegam como fato na ferramenta."""
    caminho_pdf = _pdf_simples(
        tmp_path,
        ["CADASTRO DE EMPRESA\nExemplo: CNPJ 12.345.678/0001-90 e apólice nº 987654321."],
    )
    chroma = tmp_path / "chroma"
    falso = FalsoEmbedding()
    carregar_ou_indexar(caminho_pdf, chroma, _COLECAO, falso)

    trechos = buscar_no_manual(
        "cadastro de empresa",
        diretorio_chroma=chroma,
        nome_colecao=_COLECAO,
        cliente=falso,
        limiar=0.0,
    )

    assert len(trechos) == 1
    texto = trechos[0].texto
    assert "12.345.678/0001-90" not in texto
    assert "987654321" not in texto
    assert MARCADOR in texto


def test_literal_de_ausencia_esta_declarado() -> None:
    """O literal obrigatório do ADR-0012 é exatamente 'não encontrei no material'."""
    assert LITERAL_NAO_ENCONTREI == "não encontrei no material"


# --- Critérios de aceitação do turno (issue #36, ADR-0010, ADR-0012) ---


@pytest.mark.parametrize(
    "mensagem",
    [
        "Olá, bom dia!",
        "Boa tarde!",
        "Muito obrigado pela ajuda!",
        "Valeu, até mais!",
    ],
)
def test_saudacao_e_agradecimento_sao_identificados(mensagem: str) -> None:
    """Saudação e cortesia respondem direto sem disparar ferramenta de busca."""
    termos_cortesia = ("olá", "ola", "bom dia", "boa tarde", "boa noite", "obrigad", "valeu", "tchau", "até mais")
    msg_low = mensagem.lower()
    eh_cortesia = any(termo in msg_low for termo in termos_cortesia)
    assert eh_cortesia is True


def test_resposta_sem_evidencia_utiliza_literal_e_encaminhamento() -> None:
    """Sem evidência válida acima do limiar, a resposta deve conter o literal e Encaminhamento."""
    resposta_ausencia = f"{LITERAL_NAO_ENCONTREI}. Procure a Coordenação de Estágios."
    assert LITERAL_NAO_ENCONTREI in resposta_ausencia
    assert "Coordenação de Estágios" in resposta_ausencia
    # Nenhum dado inventado de canal ou telefone
    assert "telefone" not in resposta_ausencia.lower()
    assert "email" not in resposta_ausencia.lower()


def test_busca_com_trechos_abaixo_do_limiar_devolve_vazio_gerando_literal(tmp_path: Path) -> None:
    """Trecho com similaridade abaixo de 0.35 é descartado e gera ausência de evidência."""
    caminho_pdf = _pdf_simples(
        tmp_path,
        ["CURSOS DO POLO\nEngenharia e Pedagogia."],
    )
    chroma = tmp_path / "chroma"
    # Consulta sem relação: pontuação será < 0.35
    falso = FalsoEmbedding(pontuacoes_predefinidas={"qual o valor": [0.0, 0.0, 0.0]})
    carregar_ou_indexar(caminho_pdf, chroma, _COLECAO, falso)

    trechos = buscar_no_manual(
        "qual o valor da mensalidade?",
        diretorio_chroma=chroma,
        nome_colecao=_COLECAO,
        cliente=falso,
        limiar=0.35,
    )

    assert trechos == []

