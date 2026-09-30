"""Testes do harness das Perguntas-teste, harness/run.py.

O que se prova aqui é o instrumento da #12: o parser lê as 10
Perguntas-teste com o comportamento esperado junto, a bateria grava
output bruto com timestamp e esperado, e a falha de um turno não
aborta a bateria.

O turno real (`executar_turno` contra o Ollama do host) não roda aqui:
o `turno` é uma função injetada, e a bateria prova o isolamento contra
ela. Nenhum teste deste arquivo fala com o Ollama.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from harness.run import (
    IDS_ESPERADOS,
    ORDEM_DA_BATERIA,
    PerguntaTeste,
    carregar_perguntas_teste,
    executar_bateria,
    gravar_rodada,
    montar_argumentos,
)
from sau.inference.ollama import ErroDeInferencia

RAIZ = Path(__file__).resolve().parent.parent
ARQUIVO_PERGUNTAS = RAIZ / "perguntas-teste" / "perguntas-teste.md"


def _pergunta_falsa(id_pergunta: str = "a1") -> PerguntaTeste:
    return PerguntaTeste(
        id=id_pergunta,
        texto=f"texto da Pergunta-teste {id_pergunta}",
        conforme_quando=f"conforme quando {id_pergunta}",
        nao_conforme_quando=f"não conforme quando {id_pergunta}",
    )


# --- Parser: as 10 Perguntas-teste com o esperado junto ---


def test_parser_le_as_10_perguntas_teste_em_ordem() -> None:
    perguntas = carregar_perguntas_teste(ARQUIVO_PERGUNTAS)

    assert [p.id for p in perguntas] == list(ORDEM_DA_BATERIA)
    assert set(IDS_ESPERADOS) == {f"a{i}" for i in (1, 2, 3)} | {f"f{i}" for i in (1, 2, 3)} | {
        f"p{i}" for i in (1, 2, 3, 4)
    }
    assert len(perguntas) == 10


def test_parser_traz_texto_e_comportamento_esperado_de_cada_caso() -> None:
    perguntas = carregar_perguntas_teste(ARQUIVO_PERGUNTAS)

    for pergunta in perguntas:
        assert pergunta.texto, f"a Pergunta-teste {pergunta.id} veio sem texto"
        assert "```" not in pergunta.texto
        assert pergunta.conforme_quando, f"{pergunta.id} sem o conforme quando"
        assert pergunta.nao_conforme_quando, f"{pergunta.id} sem o não conforme quando"


def test_parser_falha_alto_se_um_id_faltar(tmp_path: Path) -> None:
    arquivo = tmp_path / "perguntas-teste.md"
    arquivo.write_text(
        "<!-- pergunta:a1 -->\n```text\nOi\n```\n"
        "| Campo | Valor |\n"
        "| conforme quando | algo |\n"
        "| não conforme quando | outra |\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="faltando"):
        carregar_perguntas_teste(arquivo)


def test_parser_falha_alto_se_faltar_o_conforme(tmp_path: Path) -> None:
    blocos: list[str] = []
    for id_pergunta in ORDEM_DA_BATERIA:
        bloco = f"<!-- pergunta:{id_pergunta} -->\n```text\ntexto {id_pergunta}\n```\n"
        bloco += "| Campo | Valor |\n| tipo | Atividade |\n"
        bloco += "| conforme quando | algo |\n| não conforme quando | outra |\n"
        if id_pergunta == "a1":
            bloco = bloco.replace("| conforme quando | algo |\n", "")
        blocos.append(bloco)
    arquivo = tmp_path / "perguntas-teste.md"
    arquivo.write_text("\n".join(blocos), encoding="utf-8")

    with pytest.raises(ValueError, match="conforme quando"):
        carregar_perguntas_teste(arquivo)


# --- Bateria: output bruto com timestamp e esperado, falha isolada ---


def test_bateria_grava_output_bruto_com_esperado_e_timestamp() -> None:
    perguntas = [_pergunta_falsa("a1"), _pergunta_falsa("f1")]

    registros = executar_bateria(perguntas, lambda texto: f"S.A.U. respondeu: {texto}")

    assert len(registros) == 2
    for pergunta, registro in zip(perguntas, registros, strict=True):
        assert registro.id == pergunta.id
        assert registro.pergunta == pergunta.texto
        assert registro.conforme_quando == pergunta.conforme_quando
        assert registro.nao_conforme_quando == pergunta.nao_conforme_quando
        assert registro.resposta_bruta == f"S.A.U. respondeu: {pergunta.texto}"
        assert registro.erro is None
        datetime.fromisoformat(registro.timestamp)
        assert registro.duracao_segundos >= 0


def test_falha_de_um_turno_nao_aborta_a_bateria() -> None:
    perguntas = [_pergunta_falsa("a1"), _pergunta_falsa("a2"), _pergunta_falsa("a3")]

    def turno(texto: str) -> str:
        if "a2" in texto:
            raise ErroDeInferencia("FALHA CRÍTICA: Ollama fora do ar")
        return "output bruto do S.A.U."

    registros = executar_bateria(perguntas, turno)

    assert len(registros) == 3
    assert registros[0].resposta_bruta == "output bruto do S.A.U."
    assert registros[0].erro is None
    assert registros[1].resposta_bruta is None
    assert registros[1].erro is not None
    assert "ErroDeInferencia" in registros[1].erro
    assert registros[2].resposta_bruta == "output bruto do S.A.U."
    assert registros[2].erro is None


def test_timeout_tambem_vira_erro_do_caso_e_segue(tmp_path: Path) -> None:
    perguntas = [_pergunta_falsa("p1"), _pergunta_falsa("p2")]

    def turno(texto: str) -> str:
        if "p1" in texto:
            raise TimeoutError("tempo esgotado")
        return "resposta"

    registros = executar_bateria(perguntas, turno)
    destino = tmp_path / "rodada.json"
    gravar_rodada(registros, "qwen2.5:3b", "http://localhost:11434", destino)

    assert registros[0].erro is not None
    assert "TimeoutError" in (registros[0].erro or "")
    assert registros[1].erro is None
    assert destino.is_file()


# --- Gravação: um JSON por rodada com metadados ---


def test_gravacao_traz_metadados_e_um_registro_por_caso(tmp_path: Path) -> None:
    import json

    perguntas = [_pergunta_falsa("a1")]
    registros = executar_bateria(perguntas, lambda texto: "bruto")

    destino = tmp_path / "rodada.json"
    gravar_rodada(registros, "qwen2.5:3b", "http://localhost:11434", destino)

    rodada = json.loads(destino.read_text(encoding="utf-8"))
    assert rodada["modelo"] == "qwen2.5:3b"
    assert rodada["url"] == "http://localhost:11434"
    assert rodada["inicio"]
    assert len(rodada["casos"]) == 1
    caso = rodada["casos"][0]
    assert caso["id"] == "a1"
    assert caso["resposta_bruta"] == "bruto"
    assert caso["conforme_quando"]
    assert caso["timestamp"]


# --- CLI: flags que sobrescrevem o .env ---


def test_flags_do_harness_sobrescrevem_o_env() -> None:
    opcoes = montar_argumentos(
        ["--modelo", "outro:7b", "--url", "http://x:11434", "--timeout", "12", "--saida", "r.json"]
    )

    assert opcoes.modelo == "outro:7b"
    assert opcoes.url == "http://x:11434"
    assert opcoes.timeout == 12.0
    assert opcoes.saida == Path("r.json")
