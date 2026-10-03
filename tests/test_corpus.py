"""Testes do Corpus sobre o processo de Estágio, `corpus/`.

O que se prova aqui é o material que o S.A.U. vai responder: que são quatro
documentos versionados, que cada seção `##` responde a uma Pergunta Frequente,
que o Seguro de Acidentes Pessoais é coberto no documento próprio por emenda
do ADR-0007, que todo título de seção é único no Corpus inteiro — com um caso
repetido de propósito provando que a verificação acusa — e que os defeitos
plantados existem, cada um nomeando o caso que ataca.

Nenhum teste deste arquivo fala com o Ollama, e nenhum grava em `outputs/`:
o Corpus é lido do repositório, e o caso repetido de propósito mora em
memória.
"""

from __future__ import annotations

import re
from pathlib import Path

from sau.rag.retrieve import Secao, carregar_corpus, ler_secoes_corpus, titulos_duplicados

_RAIZ = Path(__file__).resolve().parent.parent
_CORPUS = _RAIZ / "corpus"
_DOCUMENTOS_ESPERADOS = (
    "prazos.md",
    "documentacao-de-estagio.md",
    "termo-de-compromisso.md",
    "seguro-de-acidentes-pessoais.md",
)
_DOCUMENTOS_SEM_SEGURO = (
    "prazos.md",
    "documentacao-de-estagio.md",
    "termo-de-compromisso.md",
)
_SEGURO_DOC = "seguro-de-acidentes-pessoais.md"
_MARCADOR_CASO = re.compile(r"<!--\s*caso:\s*(c\d+)\s*(?:—\s*(.+?))?\s*-->")


def _texto_dos_documentos() -> dict[str, str]:
    return {nome: (_CORPUS / nome).read_text(encoding="utf-8") for nome in _DOCUMENTOS_ESPERADOS}


# --- Os quatro documentos ---


def test_corpus_tem_os_quatro_documentos_versionados() -> None:
    assert _CORPUS.is_dir()
    assert sorted(p.name for p in _CORPUS.glob("*.md")) == sorted(_DOCUMENTOS_ESPERADOS)


def test_cada_documento_cita_o_seguro_e_o_adr() -> None:
    """O Seguro é decisão declarada em todo cabeçalho: cobertura ou remissão, nunca silêncio."""
    for nome, texto in _texto_dos_documentos().items():
        assert "Seguro de Acidentes Pessoais" in texto, nome
        assert "ADR-0007" in texto, nome


def test_so_o_documento_proprio_cobre_o_seguro() -> None:
    """O Seguro é seção só no documento próprio; nos outros, só no cabeçalho (`>`)."""
    for nome in _DOCUMENTOS_SEM_SEGURO:
        texto = (_CORPUS / nome).read_text(encoding="utf-8")
        for linha in texto.splitlines():
            if "eguro" in linha.lower():
                assert linha.lstrip().startswith(">"), f"{nome}: {linha}"


def test_a_secao_do_seguro_nao_afirma_dado_de_apolice() -> None:
    """Cobertura é processo, não dado: sem número de apólice ou vigência."""
    seguro = [s for s in carregar_corpus(_CORPUS) if s.documento == _SEGURO_DOC]
    assert len(seguro) == 1
    assert re.search(r"\d{4,}", seguro[0].texto) is None
    assert "Coordenação de Estágios" in seguro[0].texto


def test_cada_documento_tem_secao_respondendo_a_pergunta_frequente() -> None:
    secoes = carregar_corpus(_CORPUS)
    por_documento: dict[str, int] = {}
    for secao in secoes:
        assert secao.texto, f"seção vazia: {secao.titulo}"
        por_documento[secao.documento] = por_documento.get(secao.documento, 0) + 1
    assert sorted(por_documento) == sorted(_DOCUMENTOS_ESPERADOS)
    minimos = {nome: 2 for nome in _DOCUMENTOS_SEM_SEGURO}
    minimos[_SEGURO_DOC] = 1
    assert all(por_documento[nome] >= minimo for nome, minimo in minimos.items())


# --- Unicidade dos títulos ---


def test_todo_titulo_de_secao_e_unico_no_corpus_inteiro() -> None:
    """É o que permite resolver a Fonte citada por correspondência exata."""
    secoes = carregar_corpus(_CORPUS)
    assert len(secoes) >= 13
    assert titulos_duplicados(secoes) == []


def test_titulo_repetido_de_proposito_e_acusado() -> None:
    """A verificação não é cordial: dois títulos iguais são listados, não ignorados."""
    secoes = [
        Secao(documento="a.md", titulo="Prazo de entrega do relatório de atividades", texto="um"),
        Secao(
            documento="b.md",
            titulo="Prazo de entrega do relatório de atividades",
            texto="outro",
        ),
        Secao(documento="b.md", titulo="Formato do relatório de atividades", texto="só uma vez"),
    ]
    assert titulos_duplicados(secoes) == ["Prazo de entrega do relatório de atividades"]


# --- Os defeitos plantados ---


def _defeitos_plantados() -> list[tuple[str, str, str]]:
    """Cada marcador `<!-- caso: cN — tipo -->` como (documento, caso, tipo)."""
    achados: list[tuple[str, str, str]] = []
    for nome, texto in _texto_dos_documentos().items():
        for m in _MARCADOR_CASO.finditer(texto):
            achados.append((nome, m.group(1), (m.group(2) or "").strip().split(":")[0].strip()))
    return achados


def test_os_defeitos_plantados_existem_e_nomeiam_o_caso() -> None:
    defeitos = _defeitos_plantados()
    tipos = sorted(tipo for _, _, tipo in defeitos)
    assert tipos == [
        "contradição",
        "contradição",
        "lacuna",
        "similaridade enganosa",
        "valor de borda",
    ], tipos
    casos = sorted(caso for _, caso, _ in defeitos)
    assert casos == ["c1", "c2", "c4", "c5", "c5"], casos


def test_a_contradicao_e_um_par_de_secoes_que_discordam_do_mesmo_prazo() -> None:
    """Contradição é par: duas seções, mesmo prazo, valores diferentes, mesmo caso."""
    secoes = carregar_corpus(_CORPUS)
    textos = "\n".join(
        (_CORPUS / nome).read_text(encoding="utf-8") for nome in _DOCUMENTOS_ESPERADOS
    )
    marcadas = [
        secao
        for secao in secoes
        if re.search(r"<!--\s*caso:\s*c5\b", _trecho_bruto(secao, textos))
    ]
    assert len(marcadas) == 2, [s.titulo for s in marcadas]
    assert marcadas[0].titulo != marcadas[1].titulo
    assert marcadas[0].texto != marcadas[1].texto
    assert "devolv" in marcadas[0].texto and "devolv" in marcadas[1].texto
    prazos = sorted(re.findall(r"\d+", m.texto)[0] for m in marcadas)
    assert prazos == ["10", "15"], [m.texto for m in marcadas]


def _trecho_bruto(secao: Secao, textos: str) -> str:
    inicio = textos.find(f"## {secao.titulo}")
    assert inicio >= 0, secao.titulo
    proximo = textos.find("\n## ", inicio + 1)
    return textos[inicio:] if proximo < 0 else textos[inicio:proximo]


def test_o_valor_de_borda_nao_e_achado_por_palavra_chave() -> None:
    """O prazo indireto não traz 'dias' nem dígito: busca por palavra-chave passa direto."""
    secoes = carregar_corpus(_CORPUS)
    bordas = [s for s in secoes if s.titulo == "Prazo de entrega do relatório de atividades"]
    assert len(bordas) == 1
    corpo = bordas[0].texto.lower()
    assert "dias" not in corpo
    assert re.search(r"\d", bordas[0].texto) is None


def test_os_marcadores_da_equipe_nao_entram_no_texto_indexado() -> None:
    """O que o S.A.U. recupera é o que o Aluno lê: `<!-- caso: ... -->` não é conteúdo."""
    for secao in carregar_corpus(_CORPUS):
        assert "<!--" not in secao.texto, secao.titulo
        assert "caso:" not in secao.texto, secao.titulo


def test_ler_secoes_de_um_documento() -> None:
    secoes = ler_secoes_corpus(_CORPUS / "prazos.md")
    assert [s.titulo for s in secoes] == [
        "Prazo de entrega do relatório de atividades",
        "Prazo de devolução do Termo assinado pela Empresa",
        "Carga horária mínima do Estágio",
    ]
    assert all(s.documento == "prazos.md" for s in secoes)
