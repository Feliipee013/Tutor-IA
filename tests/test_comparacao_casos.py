"""Testes da comparação nos cinco Casos de alucinação, issue #28.

O que se prova aqui é a evidência da 1.2: que a verificação mecânica da Fonte
distingue os cinco resultados da tabela (citação válida; documento inexistente;
seção inexistente; linha sem parsear; ausência total), que as duas taxas da 1.1
saem republicadas sem alteração, que a folha dos Casos traz a saída inteira ao
lado do veredito com a régua de cada caso, e que as duas rodadas estão
preservadas em disco com modelo, alocação e `sha256` nos dois lados — e a
recuperação ligada no lado de depois, lida do bloco que a rodada declara.

Nenhum teste deste arquivo fala com o Ollama, e nenhum grava em `outputs/`: as
rodadas são lidas do repositório, e as rodadas e folhas falsas moram em
`tmp_path`. O `harness/run_casos.py` é quem mede, e a rodada do depois é o que
ele gravou.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from harness.metrics import (
    A_PREENCHER,
    ALUCINACAO,
    CASOS_IDS,
    CONFABULACAO_COM_FONTE,
    FONTE_VERIFICAVEL,
    TAXAS_1_1_CONGELADAS,
    TITULO_ENGANOSO,
    MembrosDivergentesError,
    calcular_casos,
    carregar_julgamento_dos_casos,
    carregar_rodada_de_casos,
    conferir_taxas_1_1_congeladas,
    extrair_citacoes,
    folha_de_julgamento_dos_casos,
    gravar_metricas_dos_casos,
    recuperacao_ligada,
    republicar_taxas_1_1,
    titulos_do_corpus,
    verificar_fontes_da_resposta,
)

_RAIZ = Path(__file__).resolve().parent.parent
_BASE_1_1 = _RAIZ / "outputs" / "baseline-1.1.json"
_METRICAS_1_1 = _RAIZ / "outputs" / "baseline-1.1.metricas.json"
_BASE_1_2 = _RAIZ / "outputs" / "baseline-1.2.json"
_JULGAMENTO_1_2 = _RAIZ / "outputs" / "baseline-1.2.julgamento.json"
_METRICAS_1_2 = _RAIZ / "outputs" / "baseline-1.2.metricas.json"

_TITULOS = [
    "Prazo de entrega do relatório de atividades",
    "Formato do relatório de acompanhamento do Supervisor",
]
_DOCUMENTOS = ["prazos.md", "documentacao-de-estagio.md"]


# --- A tabela mecânica: um resultado esperado por linha ---


@pytest.mark.parametrize(
    ("resposta", "esperado"),
    [
        (
            "O relatório sai em PDF.\nFonte: Prazo de entrega do relatório de atividades",
            "verificavel",
        ),
        (
            "O dado está no manual.\nFonte: manual-do-aluno.md",
            "documento_inexistente",
        ),
        (
            "O dado está na seção.\nFonte: Seção que não existe no Corpus",
            "secao_inexistente",
        ),
        (
            "O dado está na seção.\nFonte:",
            "linha_sem_parsear",
        ),
        (
            "O relatório sai em PDF, sem citar nada.",
            "ausente",
        ),
    ],
)
def test_tabela_mecanica_tem_um_resultado_por_linha(resposta: str, esperado: str) -> None:
    """Cada linha da spec sai com o seu status, e nenhum script julga sustento."""
    assert verificar_fontes_da_resposta(resposta, _TITULOS, _DOCUMENTOS) == esperado


def test_citacao_com_letra_trocada_nao_resolve() -> None:
    """A Fonte é copiada verbatim: cópia fiel não muda letra."""
    resposta = "O relatório sai em PDF.\nFonte: prazo de entrega do relatório de atividades"
    assert verificar_fontes_da_resposta(resposta, _TITULOS, _DOCUMENTOS) == "secao_inexistente"


def test_mencao_solta_de_fonte_sem_linha_e_linha_sem_parsear() -> None:
    """Quem escreve 'fonte' sem a linha `Fonte: <título>` não citou nada parseável."""
    resposta = "conforme a fonte do material, o relatório sai em PDF."
    assert verificar_fontes_da_resposta(resposta, _TITULOS, _DOCUMENTOS) == "linha_sem_parsear"


def test_extracao_nao_normaliza_o_titulo() -> None:
    citacoes = extrair_citacoes("Texto.\nFonte:  Prazo de entrega do relatório de atividades  ")
    assert citacoes == ["Prazo de entrega do relatório de atividades"]


@pytest.mark.skip(reason="suspensa na #40: sem `.md` no corpus; a #38 reconstrói a bateria")
def test_todo_titulo_do_corpus_e_unico_e_resolve() -> None:
    """A invariante que permite a correspondência exata, lida do Corpus versionado.

    Suspensa na #40 (ADR-0011): media os títulos dos `.md` sintéticos, que
    saíram do `corpus/` — a base passou a ser o PDF do Manual. A #38
    reconstrói a bateria sobre o Manual e reativa esta invariante lá.
    """
    titulos, documentos = titulos_do_corpus(_RAIZ / "corpus")
    assert len(titulos) >= 13
    assert len(set(titulos)) == len(titulos)
    for titulo in titulos:
        assert verificar_fontes_da_resposta(f"Texto.\nFonte: {titulo}", titulos, documentos) == (
            "verificavel"
        )


# --- As duas taxas da 1.1, republicadas congeladas ---


def test_as_taxas_da_1_1_saem_republicadas_sem_alteracao() -> None:
    """O arquivo versionado bate com o bloco congelado, campo a campo."""
    documento: dict[str, Any] = json.loads(_METRICAS_1_1.read_text(encoding="utf-8"))
    conferir_taxas_1_1_congeladas(documento)
    assert republicar_taxas_1_1() == TAXAS_1_1_CONGELADAS


def test_republicacao_travada_acusa_mudanca(tmp_path: Path) -> None:
    documento: dict[str, Any] = json.loads(_METRICAS_1_1.read_text(encoding="utf-8"))
    documento["taxas"]["nao_saber"]["fracao_formatada"] = "4/12 = 0,33"
    with pytest.raises(MembrosDivergentesError, match="republicadas"):
        conferir_taxas_1_1_congeladas(documento)


# --- A folha dos Casos: saída inteira, régua e quem ratificou ---


def _execucao_de_caso(id_caso: str, repeticao: int, resposta: str) -> dict[str, Any]:
    return {
        "id": id_caso,
        "repeticao": repeticao,
        "pergunta": f"pergunta do Aluno no {id_caso}",
        "conforme_quando": f"conforme quando {id_caso}",
        "nao_conforme_quando": f"não conforme quando {id_caso}",
        "motivo_do_erro": f"motivo do erro {id_caso}",
        "resposta_errada_esperada": f"resposta errada {id_caso}",
        "resposta_bruta": resposta,
        "erro": None,
        "motivo_de_parada": "stop",
        "fontes_recuperadas": [],
        "timestamp": f"2026-10-03T12:0{repeticao}:00+00:00",
        "duracao_segundos": 1.5,
    }


def _rodada_de_casos(repeticoes: int = 1) -> dict[str, Any]:
    return {
        "modelo": "qwen2.5:3b",
        "url": "http://localhost:11434",
        "condicoes": {
            "repeticoes": repeticoes,
            "temperatura": 0.0,
            "seed": 20260926,
            "num_predict": 256,
            "num_ctx": 4096,
            "sha256_do_prompt": "abc123",
        },
        "recuperacao": {
            "ligada": True,
            "secoes_indexadas": 14,
            "modelo_embedding": "nomic-embed-text",
        },
        "alocacao": {"size": 1_900_000_000, "size_vram": 1_900_000_000, "em_cpu": False},
        "inicio": "2026-10-03T12:00:00+00:00",
        "fim": "2026-10-03T12:05:00+00:00",
        "execucoes": [
            _execucao_de_caso(id_caso, repeticao, f"resposta {id_caso} {repeticao}")
            for id_caso in CASOS_IDS
            for repeticao in range(1, repeticoes + 1)
        ],
    }


def _gravar(caminho: Path, documento: Any) -> Path:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(documento, ensure_ascii=False) + "\n", encoding="utf-8")
    return caminho


def test_folha_dos_casos_traz_saida_inteira_e_regua(tmp_path: Path) -> None:
    rodada = carregar_rodada_de_casos(_gravar(tmp_path / "rodada.json", _rodada_de_casos()))

    folha = folha_de_julgamento_dos_casos(rodada)

    assert sorted(folha["casos"]) == sorted(CASOS_IDS)
    for id_caso, regua in folha["casos"].items():
        for campo in (
            "pergunta",
            "conforme_quando",
            "nao_conforme_quando",
            "motivo_do_erro",
            "resposta_errada_esperada",
        ):
            assert regua[campo], f"{id_caso} sem {campo}"
    assert folha["julgador"] == A_PREENCHER
    # Duas linhas por execução julgável: Alucinação e confabulação com Fonte.
    assert len(folha["vereditos"]) == 2 * len(rodada.execucoes)
    for linha in folha["vereditos"]:
        assert linha["resposta_bruta"].startswith("resposta ")
        assert linha["metrica"] in (ALUCINACAO, CONFABULACAO_COM_FONTE)


def test_folha_dos_casos_exige_quem_ratificou(tmp_path: Path) -> None:
    rodada = carregar_rodada_de_casos(_gravar(tmp_path / "rodada.json", _rodada_de_casos()))
    folha = folha_de_julgamento_dos_casos(rodada)
    folha["julgador"] = "kcronnossz (ratificador; veredito redigido por agente)"
    folha["julgado_em"] = "2026-10-03"
    for linha in folha["vereditos"]:
        linha["veredito"] = "conforme"
    destino = tmp_path / "folha.json"
    destino.write_text(json.dumps(folha, ensure_ascii=False) + "\n", encoding="utf-8")

    julgamento = carregar_julgamento_dos_casos(destino, rodada)

    assert "ratificador" in julgamento.julgador
    assert "kcronnossz" in julgamento.julgador


def test_calculo_dos_casos_separa_pessoa_de_script(tmp_path: Path) -> None:
    """Com citação válida e veredito conforme, as três métricas contam 1/1."""
    documento = _rodada_de_casos()
    for execucao in documento["execucoes"]:
        execucao["resposta_bruta"] = (
            "O relatório sai em PDF.\nFonte: Prazo de entrega do relatório de atividades"
        )
    rodada = carregar_rodada_de_casos(_gravar(tmp_path / "rodada.json", documento))
    folha = folha_de_julgamento_dos_casos(rodada)
    folha["julgador"] = "kcronnossz (ratificador)"
    folha["julgado_em"] = "2026-10-03"
    for linha in folha["vereditos"]:
        linha["veredito"] = "conforme"
    destino = tmp_path / "folha.json"
    destino.write_text(json.dumps(folha, ensure_ascii=False) + "\n", encoding="utf-8")

    relatorio = calcular_casos(
        rodada,
        carregar_julgamento_dos_casos(destino, rodada),
        _TITULOS,
        _DOCUMENTOS,
    )

    assert relatorio.taxas[ALUCINACAO].fracao == 0.0
    assert relatorio.taxas[CONFABULACAO_COM_FONTE].fracao == 0.0
    assert relatorio.taxas[FONTE_VERIFICAVEL].fracao == 1.0
    destino_metricas = tmp_path / "metricas.json"
    gravar_metricas_dos_casos(relatorio, destino_metricas)
    gravado: dict[str, Any] = json.loads(destino_metricas.read_text(encoding="utf-8"))
    assert set(gravado["taxas"]) == {ALUCINACAO, CONFABULACAO_COM_FONTE, FONTE_VERIFICAVEL}
    assert gravado["taxas_1_1_republicadas"] == TAXAS_1_1_CONGELADAS


def test_falso_positivo_conta_a_enganosa_recuperada(tmp_path: Path) -> None:
    documento = _rodada_de_casos()
    documento["execucoes"][0]["fontes_recuperadas"] = [TITULO_ENGANOSO, "Outra seção"]
    rodada = carregar_rodada_de_casos(_gravar(tmp_path / "rodada.json", documento))
    folha = folha_de_julgamento_dos_casos(rodada)
    folha["julgador"] = "kcronnossz (ratificador)"
    folha["julgado_em"] = "2026-10-03"
    for linha in folha["vereditos"]:
        linha["veredito"] = "conforme"
    destino = tmp_path / "folha.json"
    destino.write_text(json.dumps(folha, ensure_ascii=False) + "\n", encoding="utf-8")

    relatorio = calcular_casos(
        rodada,
        carregar_julgamento_dos_casos(destino, rodada),
        _TITULOS,
        _DOCUMENTOS,
    )

    assert relatorio.falso_positivo.titulo == TITULO_ENGANOSO
    assert relatorio.falso_positivo.ocorrencias == 1
    assert relatorio.falso_positivo.avaliadas == len(rodada.execucoes)


# --- As duas rodadas em disco: modelo, alocação, sha256 e recuperação ---


def test_as_duas_rodadas_declaram_modelo_alocacao_e_sha256() -> None:
    antes: dict[str, Any] = json.loads(_BASE_1_1.read_text(encoding="utf-8"))
    depois: dict[str, Any] = json.loads(_BASE_1_2.read_text(encoding="utf-8"))

    for rodada in (antes, depois):
        assert rodada["modelo"] == "qwen2.5:3b"
        assert rodada["alocacao"]["em_cpu"] is False
        assert rodada["alocacao"]["size_vram"] == 2159374499
        assert len(rodada["condicoes"]["sha256_do_prompt"]) == 64
        assert rodada["condicoes"]["temperatura"] == 0.0
        assert rodada["condicoes"]["seed"] == 20260926
        assert rodada["condicoes"]["num_predict"] == 256


def test_recuperacao_ligada_no_depois_e_desligada_no_antes() -> None:
    antes: dict[str, Any] = json.loads(_BASE_1_1.read_text(encoding="utf-8"))
    depois: dict[str, Any] = json.loads(_BASE_1_2.read_text(encoding="utf-8"))

    assert recuperacao_ligada(antes) is False
    assert recuperacao_ligada(depois) is True
    assert depois["recuperacao"]["secoes_indexadas"] == 14
    assert depois["recuperacao"]["modelo_embedding"] == "nomic-embed-text"


def test_rodada_do_depois_tem_cinco_casos_e_tres_repeticoes() -> None:
    rodada = carregar_rodada_de_casos(_BASE_1_2)

    assert sorted({execucao.id for execucao in rodada.execucoes}) == sorted(CASOS_IDS)
    assert rodada.repeticoes == 3
    assert len(rodada.execucoes) == 15


def test_julgamento_do_depois_nomeia_quem_ratificou() -> None:
    rodada = carregar_rodada_de_casos(_BASE_1_2)
    julgamento = carregar_julgamento_dos_casos(_JULGAMENTO_1_2, rodada)

    assert "kcronnossz" in julgamento.julgador
    assert "ratificador" in julgamento.julgador
    assert len(julgamento.vereditos) == 30


def test_metricas_do_depois_trazem_tres_taxas_e_republicacao() -> None:
    metricas: dict[str, Any] = json.loads(_METRICAS_1_2.read_text(encoding="utf-8"))

    assert set(metricas["taxas"]) == {ALUCINACAO, CONFABULACAO_COM_FONTE, FONTE_VERIFICAVEL}
    assert metricas["taxas"][ALUCINACAO]["fracao_formatada"] == "3/15 = 0,20"
    assert metricas["taxas"][CONFABULACAO_COM_FONTE]["fracao_formatada"] == "0/15 = 0,00"
    assert metricas["taxas"][FONTE_VERIFICAVEL]["fracao_formatada"] == "0/15 = 0,00"
    conferir_taxas_1_1_congeladas({"taxas": metricas["taxas_1_1_republicadas"]})
