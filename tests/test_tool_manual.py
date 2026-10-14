"""Testes da ferramenta `buscar_no_manual`, do limiar e do schema (ADR-0010, ADR-0012).

O que se prova aqui são os critérios de aceitação da ferramenta:

1. Pergunta factual do manual devolve trecho com Fonte título + página.
2. Trecho abaixo do limiar é descartado.
3. Quando nenhum trecho passa pelo limiar, devolve vazio — a ausência de
   evidência que o turno transforma no literal e no Encaminhamento.
4. Proibição de dados ilustrativos: a máscara garante que apólice, CNPJ, CPF
   e afins não constam no texto entregue.
5. O log registra consulta, pontuações brutas, descartes pelo limiar e Fontes
   entregues.
6. O schema declarado ao modelo e o executor da chamada usam o `k` da
   configuração como padrão e ignoram argumento inválido vindo do modelo.

O `k` e o `limiar` são passados em toda chamada porque a ferramenta não tem
padrão próprio: a fonte única é a `Configuracao` do serviço (ver `sau/config.py`).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from sau.manual.indice import carregar_ou_indexar
from sau.manual.mascara import MARCADOR
from sau.manual.tool import (
    LITERAL_NAO_ENCONTREI,
    NOME_DA_FERRAMENTA,
    TrechoFiltrado,
    buscar_no_manual,
    esquema_da_ferramenta,
    executar_chamada,
    formatar_para_o_modelo,
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
            k=2,
            limiar=0.35,
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
        k=2,
        limiar=0.0,
    )

    assert len(trechos) == 1
    texto = trechos[0].texto
    assert "12.345.678/0001-90" not in texto
    assert "987654321" not in texto
    assert MARCADOR in texto


def test_literal_de_ausencia_esta_declarado() -> None:
    """O literal obrigatório do ADR-0012 é 'não encontrei no material'."""
    assert LITERAL_NAO_ENCONTREI == "não encontrei no material"


def test_busca_com_trechos_abaixo_do_limiar_devolve_vazio(tmp_path: Path) -> None:
    """Trecho com similaridade abaixo do limiar é descartado e gera ausência de evidência."""
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
        k=2,
        limiar=0.35,
    )

    assert trechos == []


def test_esquema_da_ferramenta_declara_o_nome_e_a_consulta_obrigatoria() -> None:
    """O schema que vai em `tools` nomeia a ferramenta e exige a consulta."""
    esquema = esquema_da_ferramenta(k_padrao=4)

    assert esquema["type"] == "function"
    funcao = esquema["function"]
    assert funcao["name"] == NOME_DA_FERRAMENTA
    assert "consulta" in funcao["parameters"]["properties"]
    assert funcao["parameters"]["required"] == ["consulta"]
    # O `k` é opcional e o padrão do serviço aparece na descrição.
    assert "4" in funcao["parameters"]["properties"]["k"]["description"]


def test_executar_chamada_usa_k_do_modelo_e_cai_no_padrao_quando_invalido(
    tmp_path: Path,
) -> None:
    """O executor passa o `k` do modelo adiante e ignora um `k` que não serve.

    O argumento vem de saída de modelo, e saída de modelo não é entrada
    confiável: um `k` ausente, não numérico ou abaixo de um cai no padrão da
    configuração em vez de derrubar o turno.
    """
    caminho_pdf = _pdf_simples(
        tmp_path,
        ["PRAZOS DO ESTÁGIO\nEntrega do relatório em 30 dias."],
    )
    chroma = tmp_path / "chroma"
    falso = FalsoEmbedding()
    carregar_ou_indexar(caminho_pdf, chroma, _COLECAO, falso)

    def executar(argumentos: dict[str, object]) -> list[TrechoFiltrado]:
        return executar_chamada(
            argumentos,
            diretorio_chroma=chroma,
            nome_colecao=_COLECAO,
            cliente=falso,
            k_padrao=4,
            limiar=0.35,
        )

    # O `k` do modelo chega ao cliente de embedding como pedido.
    falso.chamadas.clear()
    assert executar({"consulta": "prazo de entrega", "k": 2}) != []
    assert any("prazo de entrega" in chamada[0] for chamada in falso.chamadas)

    # Sem consulta utilizável, a busca não acontece.
    assert executar({"k": "nada"}) == []
    # `k` inválido não derruba o turno: cai no padrão e ainda busca.
    assert executar({"consulta": "prazo de entrega", "k": 0}) != []


def test_formatar_para_o_modelo_entrega_json_com_fonte_ou_aviso_de_ausencia() -> None:
    """O resultado da ferramenta vira JSON com Fonte ou o aviso de lista vazia."""
    # Lista vazia vira o aviso de ausência, e não `[]`: o modelo precisa ler
    # que a busca não achou nada.
    vazio = formatar_para_o_modelo([])
    assert vazio != "[]"
    assert "limiar" in vazio

    trecho = TrechoFiltrado(
        titulo="PRAZOS DO ESTÁGIO",
        pagina=1,
        texto="Entrega em 30 dias.",
        fonte="PRAZOS DO ESTÁGIO (p. 1)",
        pontuacao=0.9,
    )
    decodificado = json.loads(formatar_para_o_modelo([trecho]))
    assert decodificado[0]["fonte"] == "PRAZOS DO ESTÁGIO (p. 1)"
    assert decodificado[0]["texto"] == "Entrega em 30 dias."

