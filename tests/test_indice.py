"""Testes do índice em memória, `sau/rag/retrieve.py`.

O que se prova aqui é o contrato do índice: que ele é montado em memória a
partir das seções do Corpus, que o módulo de recuperação guarda o índice que
montou e o expõe — e a exposição devolve exatamente as seções indexadas —, e
que nada é persistido em disco.

Justificativa do ajuste (issue #40, ADR-0011): o `corpus/` do repositório não
tem mais `.md` — a base passou a ser o PDF do Manual, e a #40 removeu os
sintéticos. Estes testes copiavam aquele diretório; agora cada teste escreve
a sua fixture mínima em `tmp_path`, e o contrato do `retrieve.py` segue
provado sem depender do material versionado. A persistência nova mora em
`sau/manual/indice.py` e é provada em `tests/test_manual.py`: este módulo
continua sem escrever em disco, e os dois testes finais seguem valendo.

Nenhum teste deste arquivo fala com o Ollama, e nenhum grava em `outputs/`:
o embedding é falso, e as fixtures de arquivo moram em `tmp_path`. O último
teste confere o outro lado da mesma regra: se algum teste escrevesse em
`outputs/`, a pasta deixaria de ter só as linhas de base.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from sau.rag.embed import MODELO_EMBEDDING_PADRAO, ClienteEmbedding
from sau.rag.retrieve import Indice, Secao, limpar_ultimo_indice, montar_indice, ultimo_indice

_RAIZ = Path(__file__).resolve().parent.parent

_BASE_URL = "http://host.docker.internal:11434"


def _cliente_falso(dimensoes: int = 3) -> ClienteEmbedding:
    """Embedding falso que devolve um vetor por texto, sem rede e sem Ollama."""

    def handler(request: httpx.Request) -> httpx.Response:
        corpo: dict[str, Any] = json.loads(request.content.decode("utf-8"))
        textos: list[str] = corpo["input"]
        base = [1.0] + [0.0] * (dimensoes - 1)
        vetores = [list(base) for _ in textos]
        return httpx.Response(200, json={"embeddings": vetores}, request=request)

    return ClienteEmbedding(
        _BASE_URL, client=httpx.Client(transport=httpx.MockTransport(handler))
    )


def _copiar_corpus(destino: Path) -> Path:
    """Escreve uma fixture mínima de Corpus em `tmp_path`, sem ler o repositório."""
    corpus = destino / "corpus"
    corpus.mkdir()
    (corpus / "prazos.md").write_text(
        "## Prazo de entrega do relatório de atividades\n"
        "O relatório sai até a segunda sexta-feira.\n"
        "## Prazo de devolução do Termo assinado pela Empresa\n"
        "A Empresa devolve o Termo assinado em dias úteis.\n",
        encoding="utf-8",
    )
    (corpus / "seguro-de-acidentes-pessoais.md").write_text(
        "## Número de protocolo na assinatura do Termo\n"
        "O protocolo é conferido na assinatura.\n",
        encoding="utf-8",
    )
    return corpus


# --- Montagem e exposição ---


def test_indice_monta_das_secoes_do_corpus(tmp_path: Path) -> None:
    corpus = _copiar_corpus(tmp_path)

    indice = montar_indice(corpus, _cliente_falso())

    assert len(indice.secoes) == 3
    assert len(indice.vetores) == 3
    assert {s.documento for s in indice.secoes} == {
        "prazos.md",
        "seguro-de-acidentes-pessoais.md",
    }


def test_exposicao_devolve_exatamente_as_secoes_indexadas(tmp_path: Path) -> None:
    """A rodada do harness declara o que usou lendo daqui: tem de ser o mesmo."""
    from sau.rag.retrieve import carregar_corpus

    corpus = _copiar_corpus(tmp_path)

    indice = montar_indice(corpus, _cliente_falso())

    assert indice.secoes == carregar_corpus(corpus)
    titulos = [s.titulo for s in indice.secoes]
    assert "Prazo de entrega do relatório de atividades" in titulos
    assert "Número de protocolo na assinatura do Termo" in titulos


def test_montar_indice_guarda_o_modelo_de_embedding_usado(tmp_path: Path) -> None:
    """A rodada declara qual modelo embutiu: o índice carrega o nome."""
    corpus = _copiar_corpus(tmp_path)

    indice = montar_indice(corpus, _cliente_falso())

    assert indice.modelo_embedding == MODELO_EMBEDDING_PADRAO


def test_ultimo_indice_e_o_que_a_montagem_guardou(tmp_path: Path) -> None:
    """O módulo guarda o índice que montou e o expõe: é daqui que o harness lê."""
    corpus = _copiar_corpus(tmp_path)

    indice = montar_indice(corpus, _cliente_falso())

    assert ultimo_indice() is indice


def test_limpar_ultimo_indice_devolve_o_global_a_desligado(tmp_path: Path) -> None:
    """Montagem direta em helper não pode vazar para a rodada do vizinho.

    É o que fecha "a rodada declara o que o teste vizinho usou": sem o zero,
    um `montar_indice` chamado fora do turno deixava o global apontando para
    ele, e o bloco de recuperação nascia ligado sem turno nenhum.
    """
    corpus = _copiar_corpus(tmp_path)

    montar_indice(corpus, _cliente_falso())
    assert ultimo_indice() is not None

    limpar_ultimo_indice()

    assert ultimo_indice() is None


def test_indice_com_vetores_a_menos_falha_alto() -> None:
    secoes = [Secao(documento="prazos.md", titulo="Um prazo", texto="corpo")]
    with pytest.raises(ValueError, match="1 seções e 2 vetores"):
        Indice(secoes=secoes, vetores=[[1.0], [0.5]])


def test_corpus_vazio_nao_monta_indice(tmp_path: Path) -> None:
    vazio = tmp_path / "corpus"
    vazio.mkdir()
    with pytest.raises(ValueError, match="Nenhuma seção"):
        montar_indice(vazio, _cliente_falso())


# --- Nada em disco ---


def test_montar_indice_nao_persiste_nada_em_disco(tmp_path: Path) -> None:
    """Índice em disco é segundo artefato: montar só lê, nunca escreve."""
    corpus = _copiar_corpus(tmp_path)
    antes = sorted(p.name for p in corpus.iterdir())

    montar_indice(corpus, _cliente_falso())

    depois = sorted(p.name for p in corpus.iterdir())
    assert depois == antes
    assert all(p.suffix == ".md" for p in corpus.iterdir())


def test_recuperacao_nao_tem_persistencia_no_codigo() -> None:
    """Sem `salvar`, sem escrita: o que não existe no módulo não quebra em silêncio."""
    fonte = (_RAIZ / "sau" / "rag" / "retrieve.py").read_text(encoding="utf-8")
    assert "def salvar" not in fonte
    assert "write_text" not in fonte
    assert "json.dump" not in fonte


def test_nenhum_teste_escreve_em_outputs() -> None:
    saidas = sorted(p.name for p in (_RAIZ / "outputs").iterdir() if p.is_file())
    assert saidas, "outputs/ sem linhas de base: a régua sumiu"
    assert all(nome.startswith("baseline-") for nome in saidas), saidas
