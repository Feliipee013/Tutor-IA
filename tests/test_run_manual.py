"""Testes do harness da bateria do Manual, harness/run_manual.py.

O que se prova aqui é o instrumento da #37: o parser lê as 20 Perguntas-teste
(b1–b10 + x1–x5 + n1–n5) com tipo, Fonte esperada e comportamento esperado
junto, os blocos d1–d10 ficam fora da rodada, a bateria roda N repetições por
pergunta com as Fontes recuperadas junto, o bloco do Manual é lido do índice
montado, e a falha de um turno não aborta a bateria.

O turno real (grafo contra o Ollama do host) não roda aqui: o
`turno_com_fontes` é uma função injetada. Nenhum teste deste arquivo fala com
o Ollama de verdade.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from harness.run import (
    NUM_PREDICT_PADRAO,
    SEED_PADRAO,
    TEMPERATURA_PADRAO,
    AlocacaoDoModelo,
    CondicoesDaRodada,
)
from harness.run_manual import (
    IDS_MANUAL,
    ORDEM_MANUAL,
    BlocoDoManual,
    PerguntaDoManual,
    carregar_bateria_manual,
    descrever_indice_manual,
    executar_manual,
    gravar_rodada_manual,
    main,
    montar_argumentos,
)
from sau.inference.ollama import Resposta

RAIZ = Path(__file__).resolve().parent.parent
ARQUIVO_BATERIA = RAIZ / "perguntas-teste" / "bateria-manual.md"


def _pergunta_falsa(id_pergunta: str = "b1") -> PerguntaDoManual:
    return PerguntaDoManual(
        id=id_pergunta,
        texto=f"texto da Pergunta-teste {id_pergunta}",
        tipo="básica",
        fonte_esperada="ALGUM TÍTULO (p. 1)",
        conforme_quando=f"conforme quando {id_pergunta}",
        nao_conforme_quando=f"não conforme quando {id_pergunta}",
    )


def _resposta_falsa(texto: str, *, motivo_de_parada: str = "stop") -> Resposta:
    return Resposta(
        texto=texto,
        primeiro_token_segundos=0.4,
        carga_segundos=0.2,
        avaliacao_prompt_segundos=0.2,
        segundos_totais=1.5,
        tokens_por_segundo=18.0,
        tokens_gerados=27,
        concluida=True,
        motivo_de_parada=motivo_de_parada,
    )


def _turno_falso(texto: str) -> tuple[str, Resposta, list[str]]:
    """O turno injetado: devolve texto, Resposta e Fontes, sem Ollama."""
    resposta = _resposta_falsa(f"S.A.U. respondeu: {texto}")
    return resposta.texto, resposta, ["ALGUM TÍTULO (p. 1)"]


def _condicoes_falsas(**mudancas: Any) -> CondicoesDaRodada:
    base: dict[str, Any] = {
        "modelo": "qwen2.5:3b",
        "url": "http://localhost:11434",
        "repeticoes": 3,
        "temperatura": TEMPERATURA_PADRAO,
        "seed": SEED_PADRAO,
        "num_predict": NUM_PREDICT_PADRAO,
        "num_ctx": 4096,
        "sha256_do_prompt": "abc123",
        "alocacao": AlocacaoDoModelo(size=1_900_000_000, size_vram=1_900_000_000, em_cpu=False),
        "inicio": "2026-10-15T12:00:00+00:00",
        "fim": "2026-10-15T12:05:00+00:00",
    }
    return CondicoesDaRodada(**{**base, **mudancas})


def _bloco_falso(**mudancas: Any) -> BlocoDoManual:
    base: dict[str, Any] = {
        "ligada": True,
        "modo_busca": "hibrida",
        "limiar": 0.55,
        "k_padrao": 4,
        "pdf_sha256": "sha-falso",
        "colecao": "manual-estagio-obrigatorio",
        "total_chunks": 57,
        "modelo_embedding": "nomic-embed-text",
    }
    return BlocoDoManual(**{**base, **mudancas})


# --- Parser: as 20 Perguntas-teste com tipo, Fonte e esperado junto ---


def test_parser_le_as_20_perguntas_em_ordem() -> None:
    perguntas = carregar_bateria_manual(ARQUIVO_BATERIA)

    assert [p.id for p in perguntas] == list(ORDEM_MANUAL)
    assert len(perguntas) == 20
    assert set(IDS_MANUAL) == {f"b{i}" for i in range(1, 11)} | {f"x{i}" for i in range(1, 6)} | {
        f"n{i}" for i in range(1, 6)
    }


def test_parser_traz_tipo_fonte_e_comportamento_de_cada_caso() -> None:
    perguntas = carregar_bateria_manual(ARQUIVO_BATERIA)

    for pergunta in perguntas:
        assert pergunta.texto, f"{pergunta.id} sem texto"
        assert "```" not in pergunta.texto
        assert pergunta.tipo, f"{pergunta.id} sem tipo"
        assert pergunta.fonte_esperada, f"{pergunta.id} sem fonte esperada"
        assert pergunta.conforme_quando, f"{pergunta.id} sem o conforme quando"
        assert pergunta.nao_conforme_quando, f"{pergunta.id} sem o não conforme quando"


def test_parser_deixa_os_blocos_d_fora_da_rodada() -> None:
    """Os d1–d10 moram no arquivo e não entram nas 20: decisão da #37."""
    perguntas = carregar_bateria_manual(ARQUIVO_BATERIA)
    conteudo = ARQUIVO_BATERIA.read_text(encoding="utf-8")

    assert "pergunta:d1" in conteudo
    assert not [p for p in perguntas if p.id.startswith("d")]


def test_parser_falha_alto_se_um_id_faltar(tmp_path: Path) -> None:
    arquivo = tmp_path / "bateria-manual.md"
    arquivo.write_text(
        "<!-- pergunta:b1 -->\n```text\nOi\n```\n"
        "| Campo | Valor |\n"
        "| tipo | básica |\n"
        "| fonte esperada | ALGO (p. 1) |\n"
        "| conforme quando | algo |\n"
        "| não conforme quando | outra |\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="faltando"):
        carregar_bateria_manual(arquivo)


def test_parser_falha_alto_se_faltar_a_fonte_esperada(tmp_path: Path) -> None:
    blocos: list[str] = []
    for id_pergunta in ORDEM_MANUAL:
        bloco = f"<!-- pergunta:{id_pergunta} -->\n```text\ntexto {id_pergunta}\n```\n"
        bloco += "| Campo | Valor |\n| tipo | básica |\n"
        bloco += "| fonte esperada | ALGO (p. 1) |\n"
        bloco += "| conforme quando | algo |\n| não conforme quando | outra |\n"
        if id_pergunta == "b1":
            bloco = bloco.replace("| fonte esperada | ALGO (p. 1) |\n", "")
        blocos.append(bloco)
    arquivo = tmp_path / "bateria-manual.md"
    arquivo.write_text("\n".join(blocos), encoding="utf-8")

    with pytest.raises(ValueError, match="fonte esperada"):
        carregar_bateria_manual(arquivo)


# --- Bateria: repetições, Fontes recuperadas, falha isolada ---


def test_bateria_roda_tres_repeticoes_por_pergunta() -> None:
    perguntas = [_pergunta_falsa("b1"), _pergunta_falsa("n1")]

    registros = executar_manual(perguntas, _turno_falso)

    assert len(registros) == 6
    assert [registro.repeticao for registro in registros] == [1, 2, 3, 1, 2, 3]


def test_bateria_grava_fontes_recuperadas_e_tipo() -> None:
    registros = executar_manual([_pergunta_falsa("x1")], _turno_falso, repeticoes=1)

    assert len(registros) == 1
    registro = registros[0]
    assert registro.fontes_recuperadas == ["ALGUM TÍTULO (p. 1)"]
    assert registro.tipo == "básica"
    assert registro.fonte_esperada == "ALGUM TÍTULO (p. 1)"
    assert registro.erro is None


def test_falha_de_um_turno_nao_aborta_a_bateria() -> None:
    def turno(texto: str) -> tuple[str, Resposta, list[str]]:
        if "b2" in texto:
            raise TimeoutError("tempo esgotado")
        return _turno_falso(texto)

    registros = executar_manual(
        [_pergunta_falsa("b1"), _pergunta_falsa("b2")], turno, repeticoes=1
    )

    assert len(registros) == 2
    assert registros[0].resposta_bruta is not None
    assert registros[0].erro is None
    assert registros[1].resposta_bruta is None
    assert registros[1].erro is not None
    assert "TimeoutError" in (registros[1].erro or "")


# --- Gravação: condições, bloco do Manual e execuções ---


def test_gravacao_traz_manual_e_recuperacao_compatível(tmp_path: Path) -> None:
    registros = executar_manual([_pergunta_falsa("b1")], _turno_falso, repeticoes=1)

    destino = tmp_path / "rodada.json"
    gravar_rodada_manual(registros, _condicoes_falsas(), destino, _bloco_falso())

    rodada = json.loads(destino.read_text(encoding="utf-8"))
    assert rodada["modelo"] == "qwen2.5:3b"
    manual = rodada["manual"]
    assert manual["modo_busca"] == "hibrida"
    assert manual["limiar"] == 0.55
    assert manual["k_padrao"] == 4
    assert manual["total_chunks"] == 57
    assert manual["pdf_sha256"] == "sha-falso"
    # O trio que as linhas de base antigas já trazem, para a comparação ler sem formato novo.
    assert rodada["recuperacao"] == {
        "ligada": True,
        "secoes_indexadas": 57,
        "modelo_embedding": "nomic-embed-text",
    }
    execucao = rodada["execucoes"][0]
    assert execucao["fontes_recuperadas"] == ["ALGUM TÍTULO (p. 1)"]


def test_descrever_indice_desligado_sem_colecao(tmp_path: Path) -> None:
    bloco = descrever_indice_manual(
        tmp_path / "chroma-vazio",
        "colecao-inexistente",
        tmp_path / "sem-pdf.pdf",
        limiar=0.55,
        k_padrao=4,
        modelo_embedding="nomic-embed-text",
    )

    assert bloco.ligada is False
    assert bloco.modo_busca == "hibrida"
    assert bloco.total_chunks == 0
    assert bloco.modelo_embedding is None


# --- CLI ---


def test_flags_do_harness_manual() -> None:
    opcoes = montar_argumentos(["--repeticoes", "1", "--saida", "r.json"])

    assert opcoes.repeticoes == 1
    assert opcoes.saida == Path("r.json")


def test_main_recusa_rodar_com_zero_repeticao(tmp_path: Path) -> None:
    assert main(["--repeticoes", "0", "--saida", str(tmp_path / "r.json")]) == 2
    assert not (tmp_path / "r.json").exists()


def test_main_falha_alto_quando_a_bateria_nao_bate(tmp_path: Path) -> None:
    arquivo = tmp_path / "bateria.md"
    arquivo.write_text("sem perguntas aqui", encoding="utf-8")

    assert main(["--perguntas", str(arquivo), "--saida", str(tmp_path / "r.json")]) == 2
    assert not (tmp_path / "r.json").exists()


def test_main_falha_alto_quando_o_ollama_nao_responde(tmp_path: Path, monkeypatch: Any) -> None:
    import harness.run_manual

    def _cair(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("FALHA CRÍTICA: Não foi possível conectar ao Ollama.")

    monkeypatch.setattr(harness.run_manual, "_checar_pre_requisitos", _cair)
    destino = tmp_path / "rodada.json"

    assert main(["--saida", str(destino)]) == 3
    assert not destino.exists()
