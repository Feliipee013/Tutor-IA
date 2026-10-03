"""Testes da busca top-k, `sau/rag/retrieve.py`.

O que se prova aqui é a primeira entrega da #30: uma consulta devolve os
`k = 3` trechos mais próximos — cada um com documento, seção, texto e
similaridade —, a matriz de similaridade é inspecionável, o caso de valor de
borda é encontrado pelo sentido da pergunta e não por palavra-chave, e a
similaridade enganosa volta visível sem ser confundida com a seção certa.

Nenhum teste deste arquivo fala com o Ollama real: os vetores são fabricados
à mão, que é o que permite afirmar por que um trecho voltou e o outro não sem
depender do modelo de embedding. O que os vetores provam é o mecanismo — a
ordenação pelo cosseno — e não o sentido de uma pergunta real.
"""

from __future__ import annotations

import pytest

from sau.rag.retrieve import (
    K_PADRAO,
    Indice,
    Secao,
    TrechoRecuperado,
    buscar,
    resolver_fonte,
    similaridades,
)

_BORDA = Secao(
    documento="prazos.md",
    titulo="Prazo de entrega do relatório de atividades",
    texto="O relatório de atividades do Estágio é entregue até a segunda sexta-feira.",
)
_DEVOLUCAO = Secao(
    documento="prazos.md",
    titulo="Prazo de devolução do Termo assinado pela Empresa",
    texto="A Empresa devolve o Termo de Compromisso de Estágio assinado em até 10 dias úteis.",
)
_MODELO = Secao(
    documento="documentacao-de-estagio.md",
    titulo="Onde fica o modelo do relatório de atividades",
    texto="O modelo do relatório de atividades fica no portal do Aluno, na pasta Documentação.",
)
_ENGANOSA = Secao(
    documento="documentacao-de-estagio.md",
    titulo="Formato do relatório de acompanhamento do Supervisor",
    texto="O relatório de acompanhamento é preenchido pelo Supervisor(a) de Estágio.",
)


def _indice(secoes: list[Secao], vetores: list[list[float]]) -> Indice:
    return Indice(secoes=list(secoes), vetores=[list(v) for v in vetores])


# --- O top-k: três trechos, cada um com documento, seção, texto e similaridade ---


def test_busca_devolve_os_3_trechos_mais_proximos() -> None:
    secoes = [_BORDA, _DEVOLUCAO, _MODELO, _ENGANOSA]
    vetores = [[1.0, 0.0], [0.9, 0.1], [0.0, 1.0], [-1.0, 0.0]]
    indice = _indice(secoes, vetores)

    trechos = buscar(indice, [1.0, 0.0])

    assert K_PADRAO == 3
    assert len(trechos) == 3
    assert [t.titulo for t in trechos] == [
        "Prazo de entrega do relatório de atividades",
        "Prazo de devolução do Termo assinado pela Empresa",
        "Onde fica o modelo do relatório de atividades",
    ]


def test_cada_trecho_carrega_documento_secao_texto_e_similaridade() -> None:
    indice = _indice([_BORDA], [[1.0, 0.0]])

    (trecho,) = buscar(indice, [1.0, 0.0])

    assert isinstance(trecho, TrechoRecuperado)
    assert trecho.documento == "prazos.md"
    assert trecho.titulo == "Prazo de entrega do relatório de atividades"
    assert trecho.texto == _BORDA.texto
    assert trecho.similaridade == pytest.approx(1.0)


def test_k_maior_que_o_indice_devolve_tudo_sem_repetir() -> None:
    indice = _indice([_BORDA, _DEVOLUCAO], [[1.0, 0.0], [0.0, 1.0]])

    trechos = buscar(indice, [1.0, 0.0], k=10)

    assert [t.titulo for t in trechos] == [
        "Prazo de entrega do relatório de atividades",
        "Prazo de devolução do Termo assinado pela Empresa",
    ]


def test_k_menor_que_um_falha_alto() -> None:
    indice = _indice([_BORDA], [[1.0, 0.0]])

    with pytest.raises(ValueError, match="ao menos um trecho"):
        buscar(indice, [1.0, 0.0], k=0)


def test_indice_vazio_devolve_lista_vazia() -> None:
    """Sem seção não há o que responder: o grafo lê isso como recuperação desligada."""
    indice = Indice(secoes=[], vetores=[])

    assert buscar(indice, [1.0, 0.0]) == []


# --- A matriz: dá para ver por que um trecho voltou e o outro não ---


def test_matriz_devolve_um_cosseno_por_secao_na_ordem_do_indice() -> None:
    secoes = [_BORDA, _DEVOLUCAO, _ENGANOSA]
    indice = _indice(secoes, [[1.0, 0.0], [0.6, 0.8], [0.0, 1.0]])

    matriz = similaridades(indice, [1.0, 0.0])

    assert matriz == pytest.approx([1.0, 0.6, 0.0])
    assert len(matriz) == len(secoes)


def test_matriz_mostra_por_que_um_trecho_voltou_e_o_outro_nao() -> None:
    """O segundo volta e o terceiro não, e a matriz diz o quanto faltou."""
    indice = _indice([_BORDA, _DEVOLUCAO, _ENGANOSA], [[1.0, 0.0], [0.7, 0.1], [0.0, 1.0]])

    trechos = buscar(indice, [1.0, 0.0], k=2)
    matriz = similaridades(indice, [1.0, 0.0])

    assert [t.titulo for t in trechos] == [
        "Prazo de entrega do relatório de atividades",
        "Prazo de devolução do Termo assinado pela Empresa",
    ]
    assert matriz[0] > matriz[1] > matriz[2]


# --- O valor de borda: sentido, não palavra-chave ---


def test_borda_e_encontrada_pelo_sentido_e_nao_por_palavra_chave() -> None:
    """A seção do prazo indireto volta em primeiro, sem dividir palavra com a consulta.

    O corpo da borda não traz "dias" nem dígito (o teste do Corpus prova), e a
    concorrente divide "Prazo" no título: busca por palavra-chave ranquearia a
    concorrente, e a busca por vetor ranqueia a borda.
    """
    secoes = [_BORDA, _DEVOLUCAO]
    indice = _indice(secoes, [[1.0, 0.0], [0.2, 0.9]])

    (primeiro,) = buscar(indice, [1.0, 0.0], k=1)

    assert primeiro.titulo == "Prazo de entrega do relatório de atividades"
    assert "dias" not in primeiro.texto.lower()


# --- A similaridade enganosa: visível, distinguível, não confundida ---


def test_enganosa_volta_visivel_mas_nao_e_confundida_com_a_certa() -> None:
    """As duas voltam — falso positivo é custo declarado — e a certa vem antes.

    A seção enganosa divide assunto com a pergunta e por isso pontua alto; a
    certa pontua mais. O teste afirma as duas coisas juntas: a enganosa está
    no top-k (visível) e não é a primeira (distinguível).
    """
    secoes = [_MODELO, _ENGANOSA, _BORDA]
    indice = _indice(secoes, [[1.0, 0.0], [0.8, 0.2], [0.0, 1.0]])

    trechos = buscar(indice, [1.0, 0.0], k=2)

    assert trechos[0].titulo == "Onde fica o modelo do relatório de atividades"
    assert trechos[1].titulo == "Formato do relatório de acompanhamento do Supervisor"
    assert trechos[0].similaridade > trechos[1].similaridade


# --- A Fonte: correspondência exata contra os títulos do Corpus ---


@pytest.mark.parametrize(
    ("citacao", "resolve"),
    [
        ("Prazo de entrega do relatório de atividades", True),
        ("Formato do relatório de acompanhamento do Supervisor", True),
        ("Prazo de entrega do relatório", False),
        ("prazo de entrega do relatório de atividades", False),
        ("Prazo de Entrega do Relatório de Atividades", False),
        ("", False),
        ("Seção que não existe no Corpus", False),
    ],
)
def test_fonte_resolve_por_correspondencia_exata(citacao: str, resolve: bool) -> None:
    """A citação ou é exatamente um título do Corpus, ou não resolve.

    Letra trocada não resolve porque a Fonte é copiada verbatim do trecho que
    o modelo tem na mão: cópia fiel não muda letra, e tolerar diferença seria
    aceitar citação que o material não sustenta.
    """
    secoes = [_BORDA, _ENGANOSA]

    achada = resolver_fonte(citacao, secoes)

    if resolve:
        assert achada is not None
        assert achada.titulo == citacao
    else:
        assert achada is None


def test_fonte_resolvida_traz_documento_e_texto_da_secao() -> None:
    achada = resolver_fonte("Prazo de entrega do relatório de atividades", [_BORDA, _DEVOLUCAO])

    assert achada is not None
    assert achada.documento == "prazos.md"
    assert achada.texto == _BORDA.texto
