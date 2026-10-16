"""Testes das métricas da bateria do Manual, harness/metrics_manual.py.

O que se prova aqui é a régua da #37: as 20 perguntas alimentam três métricas
(acerto e citação correta nas b/x, "não sei" correto nas n), cada uma em dois
denominadores, com erro/cortada/não-avaliável fora da conta, e a Fonte
verificável por script como conferência mecânica que nunca vira veredito.

Nenhum teste deste arquivo fala com o Ollama: a rodada é montada em memória.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from harness.metrics_manual import (
    ACERTO,
    CITACAO_CORRETA,
    NAO_SEI_CORRETO,
    RodadaManual,
    calcular,
    carregar_julgamento,
    carregar_rodada_manual,
    conferir_fonte_mecanica,
    folha_de_julgamento,
    main,
    titulos_esperados,
    verificar_citacao_manual,
)

RAIZ = Path(__file__).resolve().parent.parent

IDS_B = [f"b{i}" for i in range(1, 11)]
IDS_X = [f"x{i}" for i in range(1, 6)]
IDS_N = [f"n{i}" for i in range(1, 6)]


def _execucao(
    id_pergunta: str,
    repeticao: int,
    *,
    resposta: str | None = "resposta do S.A.U. com Fonte (p. 1)",
    motivo: str | None = "stop",
    erro: str | None = None,
) -> dict[str, Any]:
    return {
        "id": id_pergunta,
        "repeticao": repeticao,
        "pergunta": f"texto da {id_pergunta}",
        "tipo": "fora do manual" if id_pergunta.startswith("n") else "básica",
        "fonte_esperada": (
            "fora do manual — não consta no manual"
            if id_pergunta.startswith("n")
            else "TÍTULO DO SLIDE (p. 1)"
        ),
        "conforme_quando": f"conforme {id_pergunta}",
        "nao_conforme_quando": f"não conforme {id_pergunta}",
        "resposta_bruta": resposta,
        "erro": erro,
        "motivo_de_parada": motivo,
        "tokens_gerados": 10 if resposta else None,
        "primeiro_token_segundos": 0.4 if resposta else None,
        "fontes_recuperadas": ["TÍTULO DO SLIDE (p. 1)"],
        "timestamp": "2026-10-15T12:00:00+00:00",
        "duracao_segundos": 1.0,
    }


def _rodada_falsa(tmp_path: Path, *, repeticoes: int = 1) -> Path:
    """As 20 perguntas com 1 repetição cada, todas julgáveis."""
    execucoes = [
        _execucao(id_pergunta, repeticao)
        for id_pergunta in IDS_B + IDS_X + IDS_N
        for repeticao in range(1, repeticoes + 1)
    ]
    # A b1 cita o título esperado de verdade, para a mecânica ter um verificável.
    execucoes[0]["resposta_bruta"] = "O Manual diz isso em TÍTULO DO SLIDE (p. 1), confira lá."
    rodada = {
        "modelo": "qwen2.5:3b",
        "url": "http://localhost:11434",
        "condicoes": {
            "repeticoes": repeticoes,
            "temperatura": 0.0,
            "seed": 20260926,
            "num_predict": 512,
            "num_ctx": 4096,
            "sha256_do_prompt": "abc123",
        },
        "manual": {
            "ligada": True,
            "modo_busca": "hibrida",
            "limiar": 0.55,
            "k_padrao": 4,
            "pdf_sha256": "sha-falso",
            "colecao": "manual-estagio-obrigatorio",
            "total_chunks": 57,
            "modelo_embedding": "nomic-embed-text",
        },
        "recuperacao": {
            "ligada": True,
            "secoes_indexadas": 57,
            "modelo_embedding": "nomic-embed-text",
        },
        "alocacao": {"size": 1, "size_vram": 1, "em_cpu": False},
        "inicio": "2026-10-15T12:00:00+00:00",
        "fim": "2026-10-15T12:05:00+00:00",
        "execucoes": execucoes,
    }
    destino = tmp_path / "rodada.json"
    destino.write_text(json.dumps(rodada, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return destino


def _folha_preenchida(rodada: RodadaManual, vereditos: dict[str, str]) -> dict[str, Any]:
    """A folha com o output da rodada e o veredito escolhido por (id, métrica)."""
    folha = folha_de_julgamento(rodada)
    folha["julgador"] = "Leonardo Rodrigues"
    folha["julgado_em"] = "2026-10-15"
    folha["redigido_por"] = "agente executor (plano #37)"
    for linha in folha["vereditos"]:
        linha["veredito"] = vereditos.get(f"{linha['id']}:{linha['metrica']}", "conforme")
    return folha


def _gravar_folha(tmp_path: Path, rodada: RodadaManual, vereditos: dict[str, str]) -> Path:
    destino = tmp_path / "rodada.julgamento.json"
    destino.write_text(
        json.dumps(_folha_preenchida(rodada, vereditos), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return destino


# --- Leitura da rodada ---


def test_carregar_rodada_manual_exige_as_20_perguntas(tmp_path: Path) -> None:
    caminho = _rodada_falsa(tmp_path)
    rodada = carregar_rodada_manual(caminho)

    assert len(rodada.execucoes) == 20
    assert rodada.repeticoes == 1
    assert rodada.manual["modo_busca"] == "hibrida"


def test_carregar_rodada_manual_recusa_conjunto_trocado(tmp_path: Path) -> None:
    caminho = _rodada_falsa(tmp_path)
    bruto = json.loads(caminho.read_text(encoding="utf-8"))
    bruto["execucoes"] = [e for e in bruto["execucoes"] if e["id"] != "n5"]
    caminho.write_text(json.dumps(bruto, ensure_ascii=False), encoding="utf-8")

    from harness.metrics import RodadaInvalidaError

    with pytest.raises(RodadaInvalidaError, match="20"):
        carregar_rodada_manual(caminho)


# --- Folha: linhas por métrica que cada pergunta alimenta ---


def test_folha_tem_duas_linhas_nas_b_e_x_e_uma_nas_n(tmp_path: Path) -> None:
    rodada = carregar_rodada_manual(_rodada_falsa(tmp_path))
    folha = folha_de_julgamento(rodada)

    por_id: dict[str, list[str]] = {}
    for linha in folha["vereditos"]:
        por_id.setdefault(linha["id"], []).append(linha["metrica"])

    for id_pergunta in IDS_B + IDS_X:
        assert sorted(por_id[id_pergunta]) == ["acerto", "citacao_correta"]
    for id_pergunta in IDS_N:
        assert por_id[id_pergunta] == ["nao_sei_correto"]
    assert len(folha["vereditos"]) == 15 * 2 + 5


def test_folha_traz_output_e_regua_lado_a_lado(tmp_path: Path) -> None:
    rodada = carregar_rodada_manual(_rodada_falsa(tmp_path))
    folha = folha_de_julgamento(rodada)

    assert folha["perguntas"]["b1"]["fonte_esperada"]
    assert folha["perguntas"]["b1"]["conforme_quando"]
    assert folha["vereditos"][0]["resposta_bruta"]
    assert folha["vereditos"][0]["veredito"] == "a preencher"


# --- Cálculo: denominadores, fora da conta, por pergunta ---


def test_calculo_com_tudo_conforme_da_1_em_tudo(tmp_path: Path) -> None:
    rodada = carregar_rodada_manual(_rodada_falsa(tmp_path))
    julgamento = carregar_julgamento(_gravar_folha(tmp_path, rodada, {}), rodada)
    relatorio = calcular(rodada, julgamento)

    for metrica in (ACERTO, CITACAO_CORRETA, NAO_SEI_CORRETO):
        taxa = relatorio.taxas[metrica]
        assert taxa.fracao == 1.0
        assert taxa.fracao_por_pergunta == 1.0
        assert taxa.fora_da_conta == ()
    assert relatorio.taxas[ACERTO].avaliadas == 15
    assert relatorio.taxas[NAO_SEI_CORRETO].avaliadas == 5


def test_erro_e_cortada_saem_da_conta_e_nao_do_numerador(tmp_path: Path) -> None:
    caminho = _rodada_falsa(tmp_path)
    bruto = json.loads(caminho.read_text(encoding="utf-8"))
    for execucao in bruto["execucoes"]:
        if execucao["id"] == "b1":
            execucao["resposta_bruta"] = None
            execucao["erro"] = "TempoEsgotadoError: estourou"
            execucao["motivo_de_parada"] = None
        if execucao["id"] == "b2":
            execucao["motivo_de_parada"] = "length"
    caminho.write_text(json.dumps(bruto, ensure_ascii=False), encoding="utf-8")

    rodada = carregar_rodada_manual(caminho)
    julgamento = carregar_julgamento(_gravar_folha(tmp_path, rodada, {}), rodada)
    relatorio = calcular(rodada, julgamento)
    taxa = relatorio.taxas[ACERTO]

    assert taxa.avaliadas == 13
    assert taxa.numerador == 13
    motivos = sorted(item.motivo for item in taxa.fora_da_conta)
    assert motivos == ["cortada", "erro"]
    assert all(item.resposta_bruta is None for item in taxa.fora_da_conta if item.motivo == "erro")


def test_por_pergunta_exige_todas_conformes(tmp_path: Path) -> None:
    rodada = carregar_rodada_manual(_rodada_falsa(tmp_path, repeticoes=3))
    folha = _folha_preenchida(rodada, {"b1:acerto": "nao_conforme"})
    # Só a repetição 1 da b1 erra: as outras duas conferem.
    for linha in folha["vereditos"]:
        if not (linha["id"] == "b1" and linha["metrica"] == "acerto" and linha["repeticao"] != 1):
            continue
        linha["veredito"] = "conforme"
    destino = tmp_path / "rodada.julgamento.json"
    destino.write_text(json.dumps(folha, ensure_ascii=False) + "\n", encoding="utf-8")

    julgamento = carregar_julgamento(destino, rodada)
    relatorio = calcular(rodada, julgamento)
    taxa = relatorio.taxas[ACERTO]

    assert taxa.fracao == pytest.approx(44 / 45)
    assert taxa.fracao_por_pergunta == pytest.approx(14 / 15)
    leitura_b1 = next(item for item in taxa.por_pergunta if item.id == "b1")
    assert (leitura_b1.conformes, leitura_b1.avaliadas, leitura_b1.leitura) == (2, 3, "variavel")


def test_julgamento_de_outra_rodada_e_recusado(tmp_path: Path) -> None:
    rodada = carregar_rodada_manual(_rodada_falsa(tmp_path))
    destino = _gravar_folha(tmp_path, rodada, {})
    bruto = json.loads(destino.read_text(encoding="utf-8"))
    bruto["sha256_da_rodada"] = "outro-sha"
    destino.write_text(json.dumps(bruto, ensure_ascii=False), encoding="utf-8")

    from harness.metrics import JulgamentoInvalidoError

    with pytest.raises(JulgamentoInvalidoError, match="outra rodada"):
        carregar_julgamento(destino, rodada)


def test_nao_avaliavel_sem_nota_e_recusado(tmp_path: Path) -> None:
    rodada = carregar_rodada_manual(_rodada_falsa(tmp_path))
    folha = _folha_preenchida(rodada, {"b1:acerto": "nao_avaliavel"})
    destino = tmp_path / "rodada.julgamento.json"
    destino.write_text(json.dumps(folha, ensure_ascii=False) + "\n", encoding="utf-8")

    from harness.metrics import JulgamentoInvalidoError

    with pytest.raises(JulgamentoInvalidoError, match="nota"):
        carregar_julgamento(destino, rodada)


# --- Fonte mecânica: página marcada + título, sem veredito ---


def test_titulos_esperados_tiram_a_pagina_e_ignoram_ausencia() -> None:
    assert titulos_esperados("CAMPO DE ESTÁGIO | EMPRESA (p.6); OUTRO (p. 7)") == [
        "CAMPO DE ESTÁGIO | EMPRESA",
        "OUTRO",
    ]
    assert titulos_esperados("fora do manual — não consta no manual") == []


def test_verificar_citacao_exige_pagina_e_titulo() -> None:
    fonte = "TÍTULO DO SLIDE (p. 1)"

    assert verificar_citacao_manual("Veja em TÍTULO DO SLIDE (p. 1).", fonte) == "verificavel"
    assert verificar_citacao_manual("Veja em (p. 1).", fonte) == "parcial"
    assert verificar_citacao_manual("Veja em TÍTULO DO SLIDE.", fonte) == "parcial"
    assert verificar_citacao_manual("Sem citação aqui.", fonte) == "ausente"
    assert (
        verificar_citacao_manual("não encontrei no material", "fora do manual — nada")
        == "nao_se_aplica"
    )


def test_fonte_mecanica_nao_muda_o_denominador(tmp_path: Path) -> None:
    rodada = carregar_rodada_manual(_rodada_falsa(tmp_path))
    mecanica = conferir_fonte_mecanica(rodada)

    assert len(mecanica) == 15
    b1 = next(item for item in mecanica if item.id == "b1")
    assert b1.status == "verificavel"
    assert b1.paginas_citadas == ("(p. 1)",)


# --- CLI e gravação ---


def test_main_preparar_escreve_a_folha(tmp_path: Path) -> None:
    caminho = _rodada_falsa(tmp_path)

    assert main(["--rodada", str(caminho), "--preparar"]) == 0
    folha = json.loads((tmp_path / "rodada.julgamento.json").read_text(encoding="utf-8"))
    assert len(folha["vereditos"]) == 35


def test_main_calcula_e_grava_as_metricas(tmp_path: Path) -> None:
    caminho = _rodada_falsa(tmp_path)
    rodada = carregar_rodada_manual(caminho)
    _gravar_folha(tmp_path, rodada, {})

    assert main(["--rodada", str(caminho)]) == 0
    metricas = json.loads((tmp_path / "rodada.metricas.json").read_text(encoding="utf-8"))
    assert set(metricas["taxas"]) == {"acerto", "citacao_correta", "nao_sei_correto"}
    assert metricas["julgamento"]["julgador"] == "Leonardo Rodrigues"
    assert len(metricas["fonte_mecanica"]) == 15
    assert metricas["manual"]["modo_busca"] == "hibrida"


def test_main_sem_rodada_devolve_2(tmp_path: Path) -> None:
    assert main(["--rodada", str(tmp_path / "inexistente.json")]) == 2
