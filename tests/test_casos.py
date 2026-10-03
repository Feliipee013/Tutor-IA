"""Testes dos cinco Casos de alucinação, `harness/casos.py`.

O que se prova aqui é a régua da 1.2: que os cinco casos estão declarados, que
cada saída de origem confere contra a linha de base da 1.1 versionada — e
falha se o texto não bater, porque transcrição corrigida quebra a evidência —,
que o caso novo é adversarial sem origem, e que todo nome de caso citado nos
defeitos plantados do Corpus corresponde a um caso declarado.

Nenhum teste deste arquivo fala com o Ollama, e nenhum grava em `outputs/`:
a linha de base é lida do repositório, e `harness/casos.py` não importa nada
de `sau/`.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any

import pytest

from harness.casos import CASOS, CasoDeAlucinacao, obter_caso

_RAIZ = Path(__file__).resolve().parent.parent
_LINHA_DE_BASE = _RAIZ / "outputs" / "baseline-1.1.json"


def _execucoes_da_linha_de_base() -> list[dict[str, Any]]:
    dados: dict[str, Any] = json.loads(_LINHA_DE_BASE.read_text(encoding="utf-8"))
    execucoes: list[dict[str, Any]] = dados["execucoes"]
    return execucoes


# --- Os cinco casos ---


def test_os_cinco_casos_estao_declarados() -> None:
    assert [c.identificador for c in CASOS] == ["c1", "c2", "c3", "c4", "c5"]
    for caso in CASOS:
        assert caso.pergunta.strip(), caso.identificador
        assert caso.resposta_errada_esperada.strip(), caso.identificador
        assert caso.motivo_do_erro.strip(), caso.identificador


def test_quatro_casos_tem_origem_e_um_e_novo() -> None:
    com_origem = [c for c in CASOS if c.saida_origem_1_1 is not None]
    assert [c.identificador for c in com_origem] == ["c1", "c2", "c3", "c4"]
    novo = obter_caso("c5")
    assert novo.saida_origem_1_1 is None


def test_cada_saida_de_origem_confere_contra_a_linha_de_base() -> None:
    """Transcrição que diverge da linha de base falha aqui, de propósito.

    O teste é frágil por desenho: se o texto não bater, ou a linha de base
    mudou, ou o caso cita um output que não existe — e os dois são defeito.
    """
    execucoes = _execucoes_da_linha_de_base()
    pares = {(e["pergunta"], e["resposta_bruta"]) for e in execucoes}
    for caso in CASOS:
        if caso.saida_origem_1_1 is None:
            continue
        assert (caso.pergunta, caso.saida_origem_1_1) in pares, caso.identificador


def test_obter_caso_falha_alto_em_identificador_desconhecido() -> None:
    assert obter_caso("c1").identificador == "c1"
    with pytest.raises(KeyError):
        obter_caso("c9")


def test_todo_caso_citado_no_corpus_corresponde_a_caso_declarado() -> None:
    """Defeito plantado citando caso que não existe é ruído que ninguém explica depois."""
    declarados = {c.identificador for c in CASOS}
    citados: set[str] = set()
    for documento in (_RAIZ / "corpus").glob("*.md"):
        texto = documento.read_text(encoding="utf-8")
        citados.update(re.findall(r"<!--\s*caso:\s*(c\d+)\b", texto))
    assert citados, "nenhum defeito cita caso nenhum"
    assert citados <= declarados, citados - declarados


def test_casos_nao_importa_nada_de_sau() -> None:
    """Dado de bancada não conhece o pacote do bot: quem conhece deixa de ser régua."""
    arvore = ast.parse((_RAIZ / "harness" / "casos.py").read_text(encoding="utf-8"))
    importados: list[str] = []
    for no in ast.walk(arvore):
        if isinstance(no, ast.Import):
            importados.extend(a.name for a in no.names)
        elif isinstance(no, ast.ImportFrom):
            importados.append(no.module or "")
    assert not any(m == "sau" or m.startswith("sau.") for m in importados), importados


def test_caso_e_imutavel() -> None:
    caso = CasoDeAlucinacao(
        identificador="cx",
        pergunta="p",
        saida_origem_1_1="s",
        resposta_errada_esperada="r",
        motivo_do_erro="m",
        conforme_quando="c",
        nao_conforme_quando="n",
    )
    with pytest.raises(AttributeError):
        caso.pergunta = "outra"  # type: ignore[misc]
