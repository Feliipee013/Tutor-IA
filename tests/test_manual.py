"""Testes da base do Manual de Estágio Obrigatório do Polo (issue #40, ADR-0011).

O que se prova aqui é o comportamento externo da ingestão: que cada página
vira um chunk com título, página e OCR em ordem e marcado como tal; que dado
ilustrativo (apólice, CNPJ, CPF, matrícula, nome em tabela, telefone, e-mail)
vira marcador neutro e nunca fato; que o contato da Coordenação de Estágios
é a única exceção que preserva telefone e e-mail; que a Fonte é título mais
página; que o boot indexa do zero e reaproveita em seguida; que trocar o PDF
re-ingere; e que a busca devolve trecho com Fonte e pontuação.

Nenhum teste deste arquivo fala com o Ollama nem precisa do tesseract: o
embedding é falso, os PDFs de fixture são gerados com o próprio PyMuPDF em
`tmp_path`, e o Manual real (ausente no CI) nunca é lido. O vocabulário é o
do `CONTEXT.md`.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from sau.manual.chunks import MARCA_OCR, ChunkManual, montar_chunks
from sau.manual.extrair import PaginaExtraida, ampliar_imagem_pequena, extrair_paginas
from sau.manual.indice import (
    EstadoDoIndice,
    buscar_no_indice,
    carregar_ou_indexar,
    sha256_do_pdf,
)
from sau.manual.mascara import MARCADOR, e_contato_da_coordenacao, mascarar

_COLECAO = "manual-estagio-obrigatorio"


class FalsoEmbedding:
    """Embedding falso por palavra-chave, sem rede e sem Ollama.

    O vetor marca o assunto do texto (`prazo`, `seguro`, resto), já
    L2-normalizado como o `ClienteEmbedding` entrega: o que os vetores provam
    é o mecanismo da busca no Chroma — Fonte e pontuação — e não o sentido de
    uma pergunta real do Aluno.
    """

    modelo_embedding = "falso-para-teste"

    def __init__(self) -> None:
        self.chamadas: list[list[str]] = []

    def embutir(self, textos: list[str]) -> list[list[float]]:
        self.chamadas.append(list(textos))
        vetores: list[list[float]] = []
        for texto in textos:
            minusculo = texto.lower()
            if "prazo" in minusculo or "entreg" in minusculo:
                vetores.append([1.0, 0.0, 0.0])
            elif "seguro" in minusculo or "apólice" in minusculo or "apolice" in minusculo:
                vetores.append([0.0, 1.0, 0.0])
            else:
                vetores.append([0.0, 0.0, 1.0])
        return vetores


def _pdf_com_paginas(destino: Path, paginas: list[str], nome: str = "manual.pdf") -> Path:
    """Gera um PDF mínimo com uma página por texto, com o próprio PyMuPDF."""
    import pymupdf

    caminho = destino / nome
    # O stub do PyMuPDF não tipa estes construtores: o `ignore` é só de tipo,
    # e o comportamento é o que os testes de extração provam logo abaixo.
    documento = pymupdf.open()  # type: ignore[no-untyped-call]
    for texto in paginas:
        pagina = documento.new_page()
        pagina.insert_text((72, 72), texto)
    documento.save(caminho)  # type: ignore[no-untyped-call]
    documento.close()  # type: ignore[no-untyped-call]
    return caminho


# --- Chunking: um slide por chunk, título mais corpo mais OCR, em ordem ---


def test_um_slide_vira_um_chunk_com_titulo_e_pagina() -> None:
    paginas = [
        PaginaExtraida(
            numero=1, texto_nativo="PRAZOS DO ESTÁGIO\nO relatório sai na sexta.", blocos_ocr=[]
        ),
        PaginaExtraida(
            numero=2, texto_nativo="SEGURO OBRIGATÓRIO\nA cobertura é exigida.", blocos_ocr=[]
        ),
    ]

    chunks = montar_chunks(paginas)

    assert len(chunks) == 2
    assert chunks[0].titulo == "PRAZOS DO ESTÁGIO"
    assert chunks[0].pagina == 1
    assert "O relatório sai na sexta." in chunks[0].texto
    assert chunks[1].titulo == "SEGURO OBRIGATÓRIO"
    assert chunks[1].pagina == 2


def test_ocr_entra_marcado_e_depois_do_texto_nativo() -> None:
    pagina = PaginaExtraida(
        numero=3,
        texto_nativo="CADASTRAR EMPRESA\nConsulte pelo CNPJ.",
        blocos_ocr=["clique em novo cadastro", "preencha os campos"],
    )

    (chunk,) = montar_chunks([pagina])

    assert chunk.tem_ocr is True
    nativo = chunk.texto.find("Consulte pelo CNPJ.")
    primeiro_ocr = chunk.texto.find(f"{MARCA_OCR} clique em novo cadastro")
    segundo_ocr = chunk.texto.find(f"{MARCA_OCR} preencha os campos")
    assert nativo >= 0
    assert nativo < primeiro_ocr < segundo_ocr


def test_chunk_sem_ocr_nao_marca_nada() -> None:
    pagina = PaginaExtraida(numero=1, texto_nativo="TÍTULO\nCorpo.", blocos_ocr=[])

    (chunk,) = montar_chunks([pagina])

    assert chunk.tem_ocr is False
    assert MARCA_OCR not in chunk.texto


def test_pagina_so_de_figura_nao_fica_sem_fonte() -> None:
    pagina = PaginaExtraida(numero=7, texto_nativo="   ", blocos_ocr=["fluxo do estágio"])

    (chunk,) = montar_chunks([pagina])

    assert chunk.titulo == "Página 7"
    assert chunk.fonte == "Página 7 (p. 7)"


def test_titulo_ignora_numero_da_pagina_e_prefere_o_cabecalho() -> None:
    pagina = PaginaExtraida(
        numero=1,
        texto_nativo="1\nESTÁGIO OBRIGATÓRIO\n2026/2\nCorpo do slide.",
        blocos_ocr=[],
    )

    (chunk,) = montar_chunks([pagina])

    assert chunk.titulo == "ESTÁGIO OBRIGATÓRIO"
    assert chunk.fonte == "ESTÁGIO OBRIGATÓRIO (p. 1)"


# --- Fonte: título mais página ---


def test_fonte_e_titulo_mais_pagina() -> None:
    chunk = ChunkManual(titulo="PRAZOS DO ESTÁGIO", pagina=4, texto="corpo", tem_ocr=False)

    assert chunk.fonte == "PRAZOS DO ESTÁGIO (p. 4)"


# --- Máscara: dado ilustrativo vira marcador neutro ---


@pytest.mark.parametrize(
    "original",
    [
        "apólice nº 123456789",
        "apólice número 123456789",
        "CNPJ 12.345.678/0001-90",
        "CNPJ 12345678000190",
        "CPF 123.456.789-00",
        "CPF 12345678900",
        "busca pelo número da matrícula 20260123",
        "RA 20260123",
        "(11) 98765-4321",
        "11 98765 4321",
        "aluno@exemplo.edu.br",
    ],
)
def test_dado_ilustrativo_vira_marcador_neutro(original: str) -> None:
    mascarado = mascarar(f"O trecho informa {original} no exemplo.")

    assert original not in mascarado
    assert MARCADOR in mascarado


def test_vigencia_com_data_e_mascarada_e_a_cobertura_normativa_fica() -> None:
    mascarado = mascarar("A vigência: 01/01/2026 a 31/12/2026 está no exemplo.")

    assert "01/01/2026" not in mascarado
    texto_normativo = mascarar("Durante a vigência da disciplina a cobertura é exigida.")

    assert texto_normativo == "Durante a vigência da disciplina a cobertura é exigida."


def test_apolice_sem_numero_e_materia_normativa_e_fica() -> None:
    """O nome da cobertura ou do filtro não é dado: só o número mascara."""
    assert (
        mascarar("A apólice vigente contempla duas coberturas.")
        == "A apólice vigente contempla duas coberturas."
    )
    assert (
        mascarar("Dúvidas Relacionadas à Apólice de Seguro: Graduação EAD")
        == "Dúvidas Relacionadas à Apólice de Seguro: Graduação EAD"
    )


def test_lei_e_prazo_nao_sao_telefone() -> None:
    """A máscara de telefone não come número normativo: lei e período ficam."""
    texto = "Lei 11.788/08 e o período 2026/2 com 4 dias úteis."

    assert mascarar(texto) == texto


def test_nome_proprio_em_tabela_mascara_e_termo_normativo_fica() -> None:
    linha = "✓ Cadastro de empresa: 4 dias    Maria Silva"

    mascarado = mascarar(linha)

    assert "Maria Silva" not in mascarado
    assert MARCADOR in mascarado
    assert "Cadastro de empresa" in mascarado


def test_termo_do_dominio_em_tabela_nao_e_nome() -> None:
    """Termo do `CONTEXT.md` em linha de tabela é assunto, não exemplo de pessoa."""
    linha = "✓ Liberação do Termo de Compromisso: Graduação EAD"

    assert mascarar(linha) == linha


def test_nome_em_texto_corrido_nao_mascara() -> None:
    """Fora de tabela, o nome pode ser o assunto do exemplo didático que o trecho explica."""
    texto = "A Escola João e Maria é o exemplo de razão social divergente."

    assert mascarar(texto) == texto


# --- Exceção: contato da Coordenação de Estágios segue citável ---


def test_regra_do_contato_exige_coordenacao_com_indicacao_de_contato() -> None:
    assert (
        e_contato_da_coordenacao(
            "Contato da Coordenação de Estágios",
            "Fale com a Coordenação pelo contato (11) 99999-1234.",
        )
        is True
    )
    assert (
        e_contato_da_coordenacao(
            "CADASTRAR EMPRESA", "Informe o CPF e e-mail do Aluno."
        )
        is False
    )
    assert (
        e_contato_da_coordenacao(
            "DECLARAÇÃO DE DISPENSA", "A Coordenação de Curso analisará o pedido."
        )
        is False
    )


def test_contato_da_coordenacao_preserva_telefone_e_email() -> None:
    corpo = "Fale com a Coordenação pelo contato (11) 99999-1234 ou coord@exemplo.edu.br."

    preservado = mascarar(corpo, preservar_contato=True)
    mascarado = mascarar(corpo)

    assert "(11) 99999-1234" in preservado
    assert "coord@exemplo.edu.br" in preservado
    assert "(11) 99999-1234" not in mascarado
    assert "coord@exemplo.edu.br" not in mascarado


def test_chunk_de_contato_da_coordenacao_chega_indexavel() -> None:
    pagina = PaginaExtraida(
        numero=9,
        texto_nativo=(
            "Contato da Coordenação de Estágios\n"
            "Fale com a Coordenação pelo contato coord@exemplo.edu.br."
        ),
        blocos_ocr=[],
    )

    (chunk,) = montar_chunks([pagina])

    assert "coord@exemplo.edu.br" in chunk.texto


# --- Extração: texto nativo e ampliação das imagens pequenas ---


def test_extracao_le_o_texto_nativo_em_ordem(tmp_path: Path) -> None:
    caminho = _pdf_com_paginas(
        tmp_path, ["PRIMEIRA PÁGINA\nCorpo um.", "SEGUNDA PÁGINA\nCorpo dois."]
    )

    paginas = extrair_paginas(caminho)

    assert [p.numero for p in paginas] == [1, 2]
    assert "PRIMEIRA PÁGINA" in paginas[0].texto_nativo
    assert "SEGUNDA PÁGINA" in paginas[1].texto_nativo


def test_imagem_pequena_e_ampliada_e_grande_volta_como_entrou() -> None:
    from PIL import Image

    pequena = Image.new("RGB", (100, 50), "white")
    grande = Image.new("RGB", (800, 600), "white")
    import io as _io

    def em_png(figura: Image.Image) -> bytes:
        saida = _io.BytesIO()
        figura.save(saida, format="PNG")
        return saida.getvalue()

    ampliada = Image.open(_io.BytesIO(ampliar_imagem_pequena(em_png(pequena))))
    assert (ampliada.width, ampliada.height) == (200, 100)
    assert ampliar_imagem_pequena(em_png(grande)) == em_png(grande)


# --- Idempotência: boot do zero indexa, de novo reaproveita, troca re-ingere ---


def test_primeira_carga_indexa_e_segunda_reaproveita(tmp_path: Path) -> None:
    caminho = _pdf_com_paginas(tmp_path, ["PRAZO DO RELATÓRIO\nEntrega na sexta."])
    chroma = tmp_path / "chroma"
    falso = FalsoEmbedding()

    primeira = carregar_ou_indexar(caminho, chroma, _COLECAO, falso)
    segunda = carregar_ou_indexar(caminho, chroma, _COLECAO, falso)

    assert primeira.reaproveitado is False
    assert primeira.total_chunks == 1
    assert segunda.reaproveitado is True
    assert segunda.total_chunks == 1
    assert segunda.pdf_sha256 == primeira.pdf_sha256
    assert len(falso.chamadas) == 1, "a segunda carga não re-embute nada"


def test_trocar_o_pdf_re_ingere_no_proximo_boot(tmp_path: Path) -> None:
    caminho = _pdf_com_paginas(tmp_path, ["PRAZO DO RELATÓRIO\nEntrega na sexta."])
    chroma = tmp_path / "chroma"
    falso = FalsoEmbedding()
    carregar_ou_indexar(caminho, chroma, _COLECAO, falso)

    _pdf_com_paginas(tmp_path, ["SEGURO DO ALUNO\nCobertura exigida."])
    seguinte = carregar_ou_indexar(caminho, chroma, _COLECAO, falso)

    assert seguinte.reaproveitado is False
    assert seguinte.total_chunks == 1
    assert len(falso.chamadas) == 2, "o conteúdo novo é embutido de novo"


def test_sha256_muda_com_o_conteudo(tmp_path: Path) -> None:
    um = _pdf_com_paginas(tmp_path, ["TEXTO UM"], nome="um.pdf")
    dois = _pdf_com_paginas(tmp_path, ["TEXTO DOIS"], nome="dois.pdf")

    assert sha256_do_pdf(um) != sha256_do_pdf(dois)
    assert sha256_do_pdf(um) == sha256_do_pdf(um)


# --- Busca: trecho com Fonte e pontuação ---


def test_busca_devolve_trecho_com_fonte_e_pontuacao(tmp_path: Path) -> None:
    caminho = _pdf_com_paginas(
        tmp_path,
        ["PRAZO DO RELATÓRIO\nEntrega na sexta.", "SEGURO DO ALUNO\nCobertura exigida."],
    )
    chroma = tmp_path / "chroma"
    falso = FalsoEmbedding()
    estado = carregar_ou_indexar(caminho, chroma, _COLECAO, falso)
    assert estado.total_chunks == 2

    (primeiro,) = buscar_no_indice(chroma, _COLECAO, "qual o prazo de entrega?", falso, k=1)

    assert "PRAZO" in primeiro.titulo
    assert primeiro.pagina == 1
    assert primeiro.fonte == f"{primeiro.titulo} (p. {primeiro.pagina})"
    assert primeiro.pontuacao == pytest.approx(1.0)


def test_busca_sem_indice_devolve_vazio(tmp_path: Path) -> None:
    assert buscar_no_indice(tmp_path / "chroma", _COLECAO, "prazo?", FalsoEmbedding()) == []


def test_busca_com_k_invalido_falha_alto(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="ao menos um trecho"):
        buscar_no_indice(tmp_path / "chroma", _COLECAO, "prazo?", FalsoEmbedding(), k=0)


def test_indexacao_aplica_a_mascara_antes_de_guardar(tmp_path: Path) -> None:
    caminho = _pdf_com_paginas(
        tmp_path, ["PRAZO DO RELATÓRIO\nExemplo com CPF 123.456.789-00."]
    )
    chroma = tmp_path / "chroma"

    carregar_ou_indexar(caminho, chroma, _COLECAO, FalsoEmbedding())
    (trecho,) = buscar_no_indice(chroma, _COLECAO, "prazo do relatório", FalsoEmbedding(), k=1)

    assert "123.456.789-00" not in trecho.texto
    assert MARCADOR in trecho.texto


# --- Configuração do Manual ---


def test_configuracao_do_manual_tem_padrao() -> None:
    from sau.config import carregar_configuracao

    config = carregar_configuracao({})

    assert config.manual_pdf_caminho == "corpus/manual-estagio-obrigatorio-polo-2026-2.pdf"
    assert config.manual_chroma_caminho == "manual-chroma"
    assert config.manual_colecao == "manual-estagio-obrigatorio"


def test_configuracao_do_manual_lida_do_ambiente() -> None:
    from sau.config import carregar_configuracao

    config = carregar_configuracao({
        "MANUAL_PDF_CAMINHO": "corpus/outro.pdf",
        "MANUAL_CHROMA_CAMINHO": "/var/lib/sau/manual-chroma",
        "MANUAL_COLECAO": "outra-colecao",
    })

    assert config.manual_pdf_caminho == "corpus/outro.pdf"
    assert config.manual_chroma_caminho == "/var/lib/sau/manual-chroma"
    assert config.manual_colecao == "outra-colecao"


# --- Boot: sem PDF segue no ar com instrução; com PDF indexa ---


def test_boot_sem_pdf_segue_no_ar_com_instrucao(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    from sau.config import carregar_configuracao
    from sau.telegram.webhook import inicializar_manual

    ausente = tmp_path / "nao-existe.pdf"
    config = carregar_configuracao({"MANUAL_PDF_CAMINHO": str(ausente)})

    with caplog.at_level(logging.WARNING):
        inicializar_manual(config)

    mensagens = [r.getMessage() for r in caplog.records]
    assert any("corpus/README.md" in m for m in mensagens), mensagens


def test_boot_com_pdf_chama_a_carga_idempotente(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sau.config import carregar_configuracao
    from sau.telegram import webhook as modulo_webhook
    from sau.telegram.webhook import inicializar_manual

    caminho = _pdf_com_paginas(tmp_path, ["PRAZO\nCorpo."])
    config = carregar_configuracao({
        "MANUAL_PDF_CAMINHO": str(caminho),
        "MANUAL_CHROMA_CAMINHO": str(tmp_path / "chroma"),
    })
    chamadas: list[Path] = []

    def carga_falsa(
        pdf: Path, _chroma: Path, _colecao: str, _cliente: object
    ) -> EstadoDoIndice:
        chamadas.append(pdf)
        return EstadoDoIndice(total_chunks=1, reaproveitado=False, pdf_sha256="x")

    monkeypatch.setattr(modulo_webhook, "carregar_ou_indexar", carga_falsa)

    inicializar_manual(config)

    assert chamadas == [caminho]
