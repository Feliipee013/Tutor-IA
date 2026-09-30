"""Testes das duas taxas da 1.1, `harness/metrics.py`.

O que se prova aqui é o instrumento da #13: que o denominador de cada taxa é a
execução das perguntas certas, que a pergunta do prazo conta em não-saber e não
pode contar em recusa, que cada contagem aponta o output que a originou, e que
tudo o que deixaria a taxa errada em silêncio — julgamento pela metade, veredito
fora do vocabulário, folha de outra rodada, régua desatualizada — falha alto em
vez de sair como número.

Nenhum teste deste arquivo fala com o Ollama, e nenhum grava em `outputs/`: a
rodada e a folha são falsas e moram em `tmp_path`. O `harness/run.py` é quem
mede, e `tests/test_harness.py` prova o lado dele.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from harness.metrics import (
    ARQUIVO_PERGUNTAS_PADRAO,
    DENOMINADOR_ESPERADO,
    FORA_DAS_TAXAS,
    MEMBROS,
    NAO_SABER,
    ORDEM_DA_CADEIA,
    RECUSA_DE_ATIVIDADE,
    ArquivoInacessivelError,
    JulgamentoInvalidoError,
    MembrosDivergentesError,
    RodadaInvalidaError,
    calcular,
    carregar_julgamento,
    carregar_rodada,
    conferir_membros,
    folha_de_julgamento,
    gravar_metricas,
    main,
    metrica_declarada,
    metricas_declaradas,
    preparar_julgamento,
    resumo_em_markdown,
)

RAIZ = Path(__file__).resolve().parent.parent

REPETICOES = 3
ORDEM = ("a1", "a2", "a3", "f1", "f2", "f3", "p1", "p2", "p3", "p4")
PERGUNTAS_DAS_TAXAS = ("a1", "a2", "a3", "f1", "f2", "f3", "p1")


def _execucao(
    id_pergunta: str,
    repeticao: int,
    *,
    resposta: str | None = None,
    erro: str | None = None,
    motivo_de_parada: str | None = "stop",
) -> dict[str, Any]:
    """Uma execução como o `harness/run.py` grava.

    A resposta por padrão é um texto que carrega o próprio `id` e a repetição:
    é o que permite afirmar que a evidência da contagem é o output certo e não
    apenas um output qualquer.
    """
    return {
        "id": id_pergunta,
        "repeticao": repeticao,
        "pergunta": f"pergunta do Aluno na {id_pergunta}",
        "conforme_quando": f"conforme quando {id_pergunta}",
        "nao_conforme_quando": f"não conforme quando {id_pergunta}",
        "resposta_bruta": resposta
        if resposta is not None
        else f"resposta {id_pergunta} {repeticao}",
        "erro": erro,
        "motivo_de_parada": motivo_de_parada,
        "timestamp": f"2026-09-30T12:0{repeticao}:00+00:00",
        "duracao_segundos": 1.5,
    }


SEM_RESPOSTA: dict[str, Any] = {"resposta_bruta": None, "erro": "ErroDeInferencia: timeout"}
CORTADA: dict[str, Any] = {"motivo_de_parada": "length"}


def _rodada(
    *,
    repeticoes: int = REPETICOES,
    sobrescritas: Mapping[tuple[str, int], dict[str, Any]] | None = None,
    ordem: str = "bateria",
) -> dict[str, Any]:
    """Uma rodada inteira: as 10 Perguntas-teste com as repetições.

    A rodada nasce completa, como o `harness/run.py` grava, e `sobrescritas`
    substitui campos de execuções específicas. Montar a rodada por inteiro e
    estragar só o que o teste precisa estragar é o que mantém a taxa sem
   _avaliaveis_ e as demais perguntas no mesmo número — é assim que a rodada
    real chega.
    """
    pares = [
        (id_pergunta, repeticao)
        for id_pergunta in ORDEM
        for repeticao in range(1, repeticoes + 1)
    ]
    if ordem == "repeticao":
        pares = [
            (id_pergunta, repeticao)
            for repeticao in range(1, repeticoes + 1)
            for id_pergunta in ORDEM
        ]

    execucoes: list[dict[str, Any]] = []
    for id_pergunta, repeticao in pares:
        execucao = _execucao(id_pergunta, repeticao)
        execucao.update((sobrescritas or {}).get((id_pergunta, repeticao), {}))
        execucoes.append(execucao)

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
        "alocacao": {"size": 1_900_000_000, "size_vram": 1_900_000_000, "em_cpu": False},
        "inicio": "2026-09-30T12:00:00+00:00",
        "fim": "2026-09-30T12:30:00+00:00",
        "execucoes": execucoes,
    }


def _gravar_rodada(caminho: Path, documento: dict[str, Any]) -> Path:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(documento, ensure_ascii=False) + "\n", encoding="utf-8")
    return caminho


def _julgar(
    rodada: Any,
    destino: Path,
    vereditos: Mapping[tuple[str, int], str] | None = None,
    **ajustes: Any,
) -> Path:
    """Preenche a folha como uma pessoa preenche: o que `preparar_julgamento` escreveu.

    Usar a folha de verdade, em vez de uma folha montada à mão, é o que prova que
    a folha que o módulo entrega é preenchível e legível de volta por ele mesmo.
    """
    folha = folha_de_julgamento(rodada)
    folha["julgador"] = ajustes.pop("julgador", "Fulana de Tal")
    folha["julgado_em"] = ajustes.pop("julgado_em", "2026-09-30")
    for linha in folha["vereditos"]:
        linha["veredito"] = "conforme"
        chave = (linha["id"], linha["repeticao"])
        if vereditos is not None and chave in vereditos:
            linha["veredito"] = vereditos[chave]
    folha.update(ajustes)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(folha, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return destino


def _taxas_de(caminho_rodada: Path, caminho_folha: Path) -> Any:
    """A folha preenchida, carregada pelo caminho que o CLI usa, e as duas taxas."""
    rodada = carregar_rodada(caminho_rodada)
    return calcular(rodada, carregar_julgamento(caminho_folha, rodada))


# --- As duas taxas e seus denominadores ---


def test_a_taxa_de_nao_saber_conta_as_quatro_perguntas(tmp_path: Path) -> None:
    rodada = _gravar_rodada(tmp_path / "rodada.json", _rodada())
    folha = _julgar(carregar_rodada(rodada), tmp_path / "folha.json")

    relatorio = _taxas_de(rodada, folha)
    taxa = relatorio.taxas[NAO_SABER]

    assert taxa.perguntas == 4
    assert [leitura.id for leitura in taxa.por_pergunta] == ["f1", "f2", "f3", "p1"]
    assert taxa.esperadas == 12
    assert taxa.avaliadas == 12
    assert taxa.numerador == 12
    assert taxa.fracao_formatada == "12/12 = 1,00"


def test_a_taxa_de_recusa_conta_as_tres_perguntas_de_atividade(tmp_path: Path) -> None:
    rodada = _gravar_rodada(tmp_path / "rodada.json", _rodada())
    folha = _julgar(carregar_rodada(rodada), tmp_path / "folha.json")

    relatorio = _taxas_de(rodada, folha)
    taxa = relatorio.taxas[RECUSA_DE_ATIVIDADE]

    assert taxa.perguntas == 3
    assert [leitura.id for leitura in taxa.por_pergunta] == ["a1", "a2", "a3"]
    assert taxa.esperadas == 9
    assert taxa.avaliadas == 9
    assert taxa.fracao_formatada == "9/9 = 1,00"


def test_a_fracao_conta_os_acertos_sobre_as_execucoes_avaliadas(tmp_path: Path) -> None:
    """Um terço conforme em `f2` derruba a taxa, e o número sai escrito com vírgula."""
    vereditos = {
        ("f1", 1): "conforme",
        ("f1", 2): "conforme",
        ("f1", 3): "conforme",
        ("f2", 1): "conforme",
        ("f2", 2): "nao_conforme",
        ("f2", 3): "conforme",
    }
    rodada = _gravar_rodada(tmp_path / "rodada.json", _rodada())
    folha = _julgar(
        carregar_rodada(rodada),
        tmp_path / "folha.json",
        {**{chave: "conforme" for chave in _pares_das_taxas()}, **vereditos},
    )

    taxa = _taxas_de(rodada, folha).taxas[NAO_SABER]

    assert taxa.numerador == 11
    assert taxa.avaliadas == 12
    assert taxa.fracao == pytest.approx(11 / 12)
    assert taxa.fracao_formatada == "11/12 = 0,92"


def _pares_das_taxas() -> list[tuple[str, int]]:
    """Todos os pares `(pergunta, repetição)` que recebem veredito."""
    return [
        (id_pergunta, repeticao)
        for id_pergunta in PERGUNTAS_DAS_TAXAS
        for repeticao in range(1, REPETICOES + 1)
    ]


# --- A exceção do prazo: o critério de aceitação que a issue nomeia ---


def test_a_pergunta_de_prazo_conta_em_nao_saber_e_nunca_como_recusa() -> None:
    """O critério de aceitação que a issue nomeia, em três afirmações.

    A segunda é a que importa: a `p1` não pode aparecer na recusa em nenhum lugar
    do cálculo, e ela não aparece porque ninguém a colocou lá.
    """
    assert MEMBROS["p1"] == NAO_SABER
    assert "p1" not in [id for id, metrica in MEMBROS.items() if metrica == RECUSA_DE_ATIVIDADE]
    assert DENOMINADOR_ESPERADO == {NAO_SABER: 4, RECUSA_DE_ATIVIDADE: 3}


def test_as_perguntas_que_nao_entram_em_taxa_nenhuma_sao_as_orientadoras() -> None:
    assert [id_pergunta for id_pergunta, metrica in MEMBROS.items() if metrica is None] == [
        "p2",
        "p3",
        "p4",
    ]


def test_os_membros_das_taxas_batem_com_a_linha_do_arquivo_de_perguntas() -> None:
    """O contrato em código e a linha que a #6 escreveu precisam ser a mesma coisa.

    Sem esta conferência, editar `perguntas-teste.md` mudaria a conta em silêncio:
    o instrumento passaria a medir outra coisa sem nenhuma linha de código mudar.
    """
    conferir_membros()

    declarados = {
        id_pergunta: metrica_declarada(valor)
        for id_pergunta, valor in metricas_declaradas().items()
    }
    assert declarados == MEMBROS
    assert set(declarados) == set(ORDEM)


def test_a_linha_do_arquivo_declara_a_excecao_do_prazo() -> None:
    """O arquivo congelado diz, por extenso, que a pergunta do prazo não é recusa."""
    valores = metricas_declaradas()

    assert "nunca" in valores["p1"]
    assert "recusa de Atividade" in valores["p1"]


@pytest.mark.parametrize(
    ("linha", "esperado"),
    [
        ("taxa de não-saber", NAO_SABER),
        ("taxa de não-saber — e **nunca** taxa de recusa de Atividade", NAO_SABER),
        ("taxa de recusa de Atividade", RECUSA_DE_ATIVIDADE),
        ("nenhuma das duas taxas: pergunta orientadora", None),
    ],
)
def test_metrica_declarada_reconhece_as_tres_formas(linha: str, esperado: Any) -> None:
    assert metrica_declarada(linha) == esperado


def test_metrica_declarada_rejeita_uma_linha_que_nao_e_uma_das_tres() -> None:
    with pytest.raises(MembrosDivergentesError):
        metrica_declarada("taxa de Alucinação")


def test_conferir_membros_falha_quando_o_arquivo_de_perguntas_muda(tmp_path: Path) -> None:
    conteudo = ARQUIVO_PERGUNTAS_PADRAO.read_text(encoding="utf-8")
    alterado = tmp_path / "perguntas-teste.md"
    alterado.write_text(
        conteudo.replace(
            "| conta na métrica do #13 | taxa de não-saber — e **nunca** taxa de "
            "recusa de Atividade |",
            "| conta na métrica do #13 | taxa de recusa de Atividade |",
        ),
        encoding="utf-8",
    )

    with pytest.raises(MembrosDivergentesError, match="p1"):
        conferir_membros(alterado)


def test_conferir_membros_falha_quando_falta_a_linha_de_uma_pergunta(tmp_path: Path) -> None:
    conteudo = ARQUIVO_PERGUNTAS_PADRAO.read_text(encoding="utf-8")
    alterado = tmp_path / "perguntas-teste.md"
    alterado.write_text(
        conteudo.replace("| conta na métrica do #13 | taxa de recusa de Atividade |", "", 1),
        encoding="utf-8",
    )

    with pytest.raises(MembrosDivergentesError, match="a1"):
        conferir_membros(alterado)


def test_a_cadeia_especial_declara_que_esta_fora_das_duas_taxas() -> None:
    """A cadeia `s1`–`s5` é um bloco do arquivo que não alimenta taxa nenhuma.

    A cadeia mora no mesmo `perguntas-teste.md` desde a #11, e o `harness/run.py` a
    grava na chave `cadeia` da rodada — separada de `execucoes`, porque roda com
    histórico acumulado e não isolada. `metrics.py` mede `execucoes`, então a cadeia
    está fora das duas taxas por decisão, e não por esquecimento: ela está escrita
    aqui para que `conferir_membros` saiba que existem blocos fora da conta, em vez
    de deixar um denominador mudar em silêncio.
    """
    declarados = metricas_declaradas()

    for id_passo in ORDEM_DA_CADEIA:
        assert id_passo in FORA_DAS_TAXAS
        assert id_passo not in declarados


def test_conferir_membros_falha_quando_um_bloco_novo_nao_declara_nenhuma_taxa(
    tmp_path: Path,
) -> None:
    """Um bloco novo sem a linha da métrica não pode entrar na conta em silêncio.

    Este é o furo que a revisão encontrou: `conferir_membros` comparava `MEMBROS` só
    com os blocos que *tinham* a linha `conta na métrica do #13`, então um bloco
    acrescentado ao arquivo sem essa linha simplesmente não aparecia em nenhum dos
    dois conjuntos — `faltando` e `sobrando` saíam vazios, o check passava, e o
    denominador da taxa ficava medindo um conjunto diferente do que o arquivo
    descreve. Foi o que a cadeia `s1`–`s5` da #11 fez.

    O bloco novo aqui não declara nada e não é `s1`–`s5`, que é exatamente o caso que
    precisa quebrar.
    """
    conteudo = ARQUIVO_PERGUNTAS_PADRAO.read_text(encoding="utf-8")
    alterado = tmp_path / "perguntas-teste.md"
    alterado.write_text(
        conteudo
        + "\n<!-- pergunta:x9 -->\n### `x9` — pergunta que ninguém classificou\n"
        + "<!-- pergunta:fim -->\n",
        encoding="utf-8",
    )

    with pytest.raises(MembrosDivergentesError, match="x9"):
        conferir_membros(alterado)


# --- Cada contagem aponta o output que a originou ---


def test_cada_contagem_aponta_o_output_que_a_originou(tmp_path: Path) -> None:
    rodada = _gravar_rodada(tmp_path / "rodada.json", _rodada())
    folha = _julgar(
        carregar_rodada(rodada),
        tmp_path / "folha.json",
        {("f1", 1): "conforme", ("f1", 2): "nao_conforme"},
    )

    relatorio = _taxas_de(rodada, folha)
    taxa = relatorio.taxas[NAO_SABER]
    da_rodada = {(e.id, e.repeticao): e for e in relatorio.rodada.execucoes}

    assert taxa.numerador == 11
    assert len(taxa.acertos) == 11
    assert len(taxa.erros) == 1

    unico_erro = taxa.erros[0]
    assert (unico_erro.id, unico_erro.repeticao) == ("f1", 2)
    assert unico_erro.veredito == "nao_conforme"
    assert unico_erro.resposta_bruta == da_rodada[("f1", 2)].resposta_bruta
    assert unico_erro.timestamp == da_rodada[("f1", 2)].timestamp

    for evidencia in taxa.acertos:
        origem = da_rodada[(evidencia.id, evidencia.repeticao)]
        assert evidencia.resposta_bruta == origem.resposta_bruta


def test_a_rodada_medida_na_ordem_da_bateria_nao_troca_a_evidencia(tmp_path: Path) -> None:
    """A evidência é resolvida por `id` e `repeticao`: reordenar a bateria não troca o output."""
    rodada = _gravar_rodada(tmp_path / "rodada.json", _rodada(ordem="repeticao"))
    folha = _julgar(carregar_rodada(rodada), tmp_path / "folha.json")

    taxa = _taxas_de(rodada, folha).taxas[NAO_SABER]

    assert len(taxa.acertos) == 12
    assert {(evidencia.id, evidencia.repeticao) for evidencia in taxa.acertos} == {
        (id_pergunta, repeticao)
        for id_pergunta in ("f1", "f2", "f3", "p1")
        for repeticao in range(1, REPETICOES + 1)
    }


def test_o_relatorio_imprime_a_regua_e_os_numeros_das_duas_taxas(tmp_path: Path) -> None:
    rodada = _gravar_rodada(tmp_path / "rodada.json", _rodada())
    folha = _julgar(carregar_rodada(rodada), tmp_path / "folha.json")

    pagina = resumo_em_markdown(_taxas_de(rodada, folha))

    assert "### Taxa de não-saber — 12/12 = 1,00" in pagina
    assert "### Taxa de recusa de Atividade — 9/9 = 1,00" in pagina
    assert "Denominador: 4 perguntas × 3 repetições = 12 execuções" in pagina
    assert "Denominador: 3 perguntas × 3 repetições = 9 execuções" in pagina
    assert "### Régua de cada Pergunta-teste" in pagina
    assert "conforme quando f1" in pagina
    assert "não conforme quando f1" in pagina
    assert "conforme quando a3" in pagina
    assert "`qwen2.5:3b`" in pagina
    assert "GPU — 1900000000 bytes em VRAM" in pagina
    assert "Fulana de Tal, 2026-09-30" in pagina


def _longa_em(pergunta: str) -> dict[tuple[str, int], dict[str, Any]]:
    """Sobrescrita que deixa a resposta de uma pergunta longa demais para o resumo."""
    return {
        (id_pergunta, repeticao): {"resposta_bruta": "palavra " * 200}
        for id_pergunta in ORDEM
        if id_pergunta == pergunta
        for repeticao in range(1, REPETICOES + 1)
    }


def test_o_relatorio_trunca_o_trecho_sem_esconder_que_truncou(tmp_path: Path) -> None:
    longa = "palavra " * 200
    rodada = _gravar_rodada(
        tmp_path / "rodada.json", _rodada(sobrescritas=_longa_em("f1"))
    )
    folha = _julgar(carregar_rodada(rodada), tmp_path / "folha.json")

    pagina = resumo_em_markdown(_taxas_de(rodada, folha))

    assert "…" in pagina
    assert longa not in pagina


def test_a_metrica_json_carrega_as_condicoes_e_o_sha256_da_rodada(tmp_path: Path) -> None:
    """Taxa sem modelo, sem máquina e sem hash do prompt ao lado não é comparável."""
    rodada = _gravar_rodada(tmp_path / "rodada.json", _rodada())
    folha = _julgar(carregar_rodada(rodada), tmp_path / "folha.json")
    relatorio = _taxas_de(rodada, folha)

    destino = gravar_metricas(relatorio, tmp_path / "metricas.json")
    gravado = json.loads(destino.read_text(encoding="utf-8"))

    assert gravado["modelo"] == "qwen2.5:3b"
    assert gravado["condicoes"]["seed"] == 20260926
    assert gravado["condicoes"]["repeticoes"] == 3
    assert gravado["alocacao"]["em_cpu"] is False
    assert gravado["sha256_da_rodada"] == relatorio.rodada.sha256
    assert gravado["julgamento"]["julgador"] == "Fulana de Tal"
    assert set(gravado["taxas"]) == {NAO_SABER, RECUSA_DE_ATIVIDADE}


def test_a_metrica_json_carrega_o_output_inteiro_de_cada_contagem(tmp_path: Path) -> None:
    """O JSON não trunca nada: o corte do resumo é só de leitura."""
    longa = "palavra " * 200
    rodada = _gravar_rodada(
        tmp_path / "rodada.json", _rodada(sobrescritas=_longa_em("f1"))
    )
    folha = _julgar(carregar_rodada(rodada), tmp_path / "folha.json")
    relatorio = _taxas_de(rodada, folha)

    destino = gravar_metricas(relatorio, tmp_path / "metricas.json")
    acertos = json.loads(destino.read_text(encoding="utf-8"))["taxas"][NAO_SABER]["acertos"]

    assert [acento["resposta_bruta"] for acento in acertos if acento["id"] == "f1"] == [longa] * 3


def test_a_metrica_json_e_reproduzivel_entre_duas_execucoes(tmp_path: Path) -> None:
    rodada = _gravar_rodada(tmp_path / "rodada.json", _rodada())
    folha = _julgar(carregar_rodada(rodada), tmp_path / "folha.json")
    relatorio = _taxas_de(rodada, folha)

    primeiro = gravar_metricas(relatorio, tmp_path / "primeiro.json").read_bytes()
    segundo = gravar_metricas(relatorio, tmp_path / "segundo.json").read_bytes()

    assert primeiro == segundo


# --- A folha de julgamento que o instrumento entrega ---


def test_a_folha_nasce_com_um_veredito_por_execucao_das_sete_perguntas(tmp_path: Path) -> None:
    rodada = _gravar_rodada(tmp_path / "rodada.json", _rodada())
    folha = folha_de_julgamento(carregar_rodada(rodada))

    assert len(folha["vereditos"]) == 21
    assert {(v["id"], v["repeticao"]) for v in folha["vereditos"]} == set(_pares_das_taxas())
    assert all(v["veredito"] == "a preencher" for v in folha["vereditos"])
    assert sorted(folha["perguntas"]) == ["a1", "a2", "a3", "f1", "f2", "f3", "p1"]
    assert folha["perguntas"]["p1"]["conforme_quando"] == "conforme quando p1"
    assert folha["julgador"] == "a preencher"


def test_o_resumo_da_a_conta_do_denominador_em_vez_de_chamar_erro_de_denominador(
    tmp_path: Path,
) -> None:
    """Os erros não são o denominador: eles são o resto dele.

    O denominador são as avaliadas, e avaliadas = acertos + erros. Um cabeçalho
    que chama os erros de "evidência do denominador" convida o leitor a contar o
    denominador pelos erros, e a chegar numa taxa que não bate com a linha de
    cima.
    """
    rodada = _gravar_rodada(tmp_path / "rodada.json", _rodada())
    folha = _julgar(
        carregar_rodada(rodada), tmp_path / "folha.json", {("f1", 2): "nao_conforme"}
    )
    relatorio = _taxas_de(rodada, folha)
    taxa = relatorio.taxas[NAO_SABER]

    pagina = resumo_em_markdown(relatorio)

    assert f"{taxa.avaliadas} avaliadas = {taxa.numerador} acertos + 1 erro" in pagina
    assert "evidência do denominador" not in pagina
    assert taxa.avaliadas == taxa.numerador + len(taxa.erros) == 12


def test_o_resumo_acorda_o_numero_do_complemento_do_denominador(tmp_path: Path) -> None:
    """Um erro é `1 erro` e dois são `2 erros` — a conta que o leitor refaz na mão."""
    rodada = _gravar_rodada(tmp_path / "rodada.json", _rodada())
    folha = _julgar(
        carregar_rodada(rodada),
        tmp_path / "folha.json",
        {("f1", 1): "nao_conforme", ("f1", 2): "nao_conforme"},
    )

    pagina = resumo_em_markdown(_taxas_de(rodada, folha))

    assert "10 acertos + 2 erros" in pagina


def test_a_folha_traz_o_output_que_a_pessoa_vai_julgar(tmp_path: Path) -> None:
    """O output precisa estar na folha, e não só na rodada ao lado dela.

    Sem ele, julgar exigiria abrir `outputs/baseline-1.1.json` e cruzar 30
    execuções à mão por `id` e `repeticao` — e quem tem de ler a resposta para
    aplicar a régua é justamente quem menos pode perder o output de vista.
    """
    rodada = _gravar_rodada(tmp_path / "rodada.json", _rodada())
    lida = carregar_rodada(rodada)

    folha = folha_de_julgamento(lida)
    saida = {
        (linha["id"], linha["repeticao"]): linha["resposta_bruta"]
        for linha in folha["vereditos"]
    }
    da_rodada = {
        (execucao.id, execucao.repeticao): execucao.resposta_bruta
        for execucao in lida.execucoes
        if MEMBROS.get(execucao.id) is not None and execucao.julgavel
    }

    assert saida == da_rodada
    assert saida[("f1", 1)] == "resposta f1 1"
    assert saida[("f3", 3)] == "resposta f3 3"
    assert saida[("a2", 2)] == "resposta a2 2"


def test_folha_com_output_de_outra_resposta_falha_alto(tmp_path: Path) -> None:
    """Trocar o texto da folha mantém `id` e `repeticao` certos, e conta errado em silêncio.

    A folha fica em disco enquanto é preenchida, e colar o output de outra
    execução é o erro mais fácil de cometer sem perceber. O veredito continua
    sendo aplicado ao par certo, então nada denunciaria a troca.
    """
    rodada = _gravar_rodada(tmp_path / "rodada.json", _rodada())
    folha = _julgar(carregar_rodada(rodada), tmp_path / "folha.json")
    bruta = json.loads(folha.read_text(encoding="utf-8"))
    alvo = next(
        linha for linha in bruta["vereditos"] if linha["id"] == "f2" and linha["repeticao"] == 2
    )
    alvo["resposta_bruta"] = "uma resposta que a rodada nunca produziu"
    folha.write_text(json.dumps(bruta, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(JulgamentoInvalidoError, match="resposta_bruta"):
        _taxas_de(rodada, folha)


def test_folha_sem_o_output_da_execucao_falha_alto(tmp_path: Path) -> None:
    """Apagar o output da folha é tão grave quanto trocar: o veredito ficaria sem objeto."""
    rodada = _gravar_rodada(tmp_path / "rodada.json", _rodada())
    folha = _julgar(carregar_rodada(rodada), tmp_path / "folha.json")
    bruta = json.loads(folha.read_text(encoding="utf-8"))
    del bruta["vereditos"][0]["resposta_bruta"]
    folha.write_text(json.dumps(bruta, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(JulgamentoInvalidoError, match="não está preenchido"):
        _taxas_de(rodada, folha)


def test_a_folha_traz_a_regua_de_cada_pergunta_que_conta(tmp_path: Path) -> None:
    rodada = _gravar_rodada(tmp_path / "rodada.json", _rodada())

    folha = folha_de_julgamento(carregar_rodada(rodada))

    assert set(folha["perguntas"]) == set(PERGUNTAS_DAS_TAXAS)


def test_a_folha_nao_pede_veredito_de_execucao_sem_resposta_nem_cortada(tmp_path: Path) -> None:
    """Sem resposta e cortada não viram linha: não há o que julgar nelas."""
    sobrescritas = {("f1", 2): SEM_RESPOSTA, ("f1", 3): CORTADA}
    rodada = _gravar_rodada(tmp_path / "rodada.json", _rodada(sobrescritas=sobrescritas))

    folha = folha_de_julgamento(carregar_rodada(rodada))

    linhas_de_f1 = [(v["id"], v["repeticao"]) for v in folha["vereditos"] if v["id"] == "f1"]
    assert linhas_de_f1 == [("f1", 1)]
    assert len(folha["vereditos"]) == 19


def test_execucao_com_erro_e_com_parada_por_length_foram_do_denominador(tmp_path: Path) -> None:
    """Resposta cortada tem cara de resposta: julgá-la reprovaria por defeito da medição."""
    sobrescritas: dict[tuple[str, int], dict[str, Any]] = {
        ("f1", 2): SEM_RESPOSTA,
        ("f1", 3): CORTADA,
    }
    rodada = _gravar_rodada(tmp_path / "rodada.json", _rodada(sobrescritas=sobrescritas))
    folha = _julgar(carregar_rodada(rodada), tmp_path / "folha.json")

    taxa = _taxas_de(rodada, folha).taxas[NAO_SABER]

    assert taxa.esperadas == 12
    assert taxa.avaliadas == 10
    assert taxa.numerador == 10
    assert taxa.fracao_formatada == "10/10 = 1,00"
    assert [item.motivo for item in taxa.fora_da_conta] == ["erro", "cortada"]
    assert "timeout" in taxa.fora_da_conta[0].detalhe
    assert "length" in taxa.fora_da_conta[1].detalhe


def test_veredito_nao_avaliavel_com_nota_sai_da_conta_com_o_motivo_declarado(
    tmp_path: Path,
) -> None:
    """A pessoa pode declarar uma execução fora da conta, desde que diga por quê."""
    rodada = _gravar_rodada(tmp_path / "rodada.json", _rodada())
    destino = _julgar(
        carregar_rodada(rodada),
        tmp_path / "folha.json",
        {("f3", 1): "nao_avaliavel"},
    )
    bruta = json.loads(destino.read_text(encoding="utf-8"))
    alvo = next(
        linha for linha in bruta["vereditos"] if linha["id"] == "f3" and linha["repeticao"] == 1
    )
    alvo["nota"] = "a resposta foi cortada no meio da frase"
    destino.write_text(json.dumps(bruta, ensure_ascii=False), encoding="utf-8")

    taxa = _taxas_de(tmp_path / "rodada.json", destino).taxas[NAO_SABER]

    assert taxa.avaliadas == 11
    assert len(taxa.fora_da_conta) == 1
    assert taxa.fora_da_conta[0].motivo == "julgada"
    assert taxa.fora_da_conta[0].detalhe == "a resposta foi cortada no meio da frase"


def test_leitura_por_pergunta_marca_variavel_quando_a_repeticao_divergiu(tmp_path: Path) -> None:
    rodada = _gravar_rodada(tmp_path / "rodada.json", _rodada())
    folha = _julgar(
        carregar_rodada(rodada),
        tmp_path / "folha.json",
        {("f1", 1): "conforme", ("f1", 2): "conforme", ("f1", 3): "nao_conforme"},
    )

    leituras = {
        leitura.id: leitura for leitura in _taxas_de(rodada, folha).taxas[NAO_SABER].por_pergunta
    }

    assert leituras["f1"].leitura == "variavel"
    assert leituras["f1"].conformes == 2
    assert leituras["f2"].leitura == "estavel"
    assert leituras["f2"].conformes == 3


def test_leitura_marca_sem_avaliacao_quando_a_pergunta_nao_tem_execucao_julgavel(
    tmp_path: Path,
) -> None:
    """Uma pergunta que falhou inteira aparece como `sem_avaliacao`, não como zero."""
    sobrescritas = {("f1", repeticao): SEM_RESPOSTA for repeticao in range(1, REPETICOES + 1)}
    rodada = _gravar_rodada(tmp_path / "rodada.json", _rodada(sobrescritas=sobrescritas))
    folha = _julgar(carregar_rodada(rodada), tmp_path / "folha.json")

    leituras = {
        leitura.id: leitura for leitura in _taxas_de(rodada, folha).taxas[NAO_SABER].por_pergunta
    }

    assert leituras["f1"].leitura == "sem_avaliacao"
    assert leituras["f1"].avaliadas == 0


# --- Tudo que deixaria a taxa errada em silêncio precisa falhar alto ---


def test_julgamento_incompleto_falha_alto(tmp_path: Path) -> None:
    rodada = _gravar_rodada(tmp_path / "rodada.json", _rodada())
    folha = _julgar(carregar_rodada(rodada), tmp_path / "folha.json")
    bruta = json.loads(folha.read_text(encoding="utf-8"))
    bruta["vereditos"] = bruta["vereditos"][:-2]
    folha.write_text(json.dumps(bruta, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(JulgamentoInvalidoError, match="faltou veredito"):
        _taxas_de(rodada, folha)


def test_o_erro_de_julgamento_incompleto_diz_qual_execucao_faltou(tmp_path: Path) -> None:
    rodada = _gravar_rodada(tmp_path / "rodada.json", _rodada())
    folha = _julgar(carregar_rodada(rodada), tmp_path / "folha.json")
    bruta = json.loads(folha.read_text(encoding="utf-8"))
    bruta["vereditos"] = [
        linha for linha in bruta["vereditos"] if (linha["id"], linha["repeticao"]) != ("p1", 2)
    ]
    folha.write_text(json.dumps(bruta, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(JulgamentoInvalidoError, match=r"p1 repetição 2"):
        _taxas_de(rodada, folha)


def test_veredito_em_branco_falha_alto(tmp_path: Path) -> None:
    """A folha entregue em branco não passa: nenhum número entra sem marcação."""
    rodada = _gravar_rodada(tmp_path / "rodada.json", _rodada())
    folha = preparar_julgamento(carregar_rodada(rodada), tmp_path / "folha.json")

    with pytest.raises(JulgamentoInvalidoError, match="a preencher"):
        _taxas_de(rodada, folha)


def test_julgamento_de_outra_rodada_falha_alto(tmp_path: Path) -> None:
    """A folha carrega o sha256 da rodada: aplicada a outra, mede a rodada errada."""
    primeira = _gravar_rodada(tmp_path / "primeira.json", _rodada())
    segunda = _gravar_rodada(
        tmp_path / "segunda.json",
        _rodada(sobrescritas={("f1", 1): {"resposta_bruta": "outra rodada, outro arquivo"}}),
    )
    folha = _julgar(carregar_rodada(primeira), tmp_path / "folha.json")

    with pytest.raises(JulgamentoInvalidoError, match="outra rodada"):
        _taxas_de(segunda, folha)


def test_veredito_fora_do_vocabulario_falha_alto(tmp_path: Path) -> None:
    rodada = _gravar_rodada(tmp_path / "rodada.json", _rodada())
    folha = _julgar(carregar_rodada(rodada), tmp_path / "folha.json", {("f1", 1): "mais ou menos"})

    with pytest.raises(JulgamentoInvalidoError, match="vocabulário"):
        _taxas_de(rodada, folha)


def test_veredito_nao_avaliavel_sem_nota_falha_alto(tmp_path: Path) -> None:
    rodada = _gravar_rodada(tmp_path / "rodada.json", _rodada())
    folha = _julgar(carregar_rodada(rodada), tmp_path / "folha.json", {("f1", 1): "nao_avaliavel"})

    with pytest.raises(JulgamentoInvalidoError, match="nota"):
        _taxas_de(rodada, folha)


def test_veredito_de_pergunta_que_nao_conta_em_taxa_nenhuma_falha_alto(tmp_path: Path) -> None:
    rodada = _gravar_rodada(tmp_path / "rodada.json", _rodada())
    folha = _julgar(carregar_rodada(rodada), tmp_path / "folha.json")
    bruta = json.loads(folha.read_text(encoding="utf-8"))
    bruta["vereditos"].append(
        {"id": "p2", "repeticao": 1, "metrica": NAO_SABER, "veredito": "conforme", "nota": ""}
    )
    folha.write_text(json.dumps(bruta, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(JulgamentoInvalidoError, match="não entra em taxa nenhuma"):
        _taxas_de(rodada, folha)


def test_veredito_na_taxa_errada_falha_alto(tmp_path: Path) -> None:
    """O veredito da `p1` como recusa de Atividade é o erro que a issue nomeia."""
    rodada = _gravar_rodada(tmp_path / "rodada.json", _rodada())
    folha = _julgar(carregar_rodada(rodada), tmp_path / "folha.json")
    bruta = json.loads(folha.read_text(encoding="utf-8"))
    for linha in bruta["vereditos"]:
        if linha["id"] == "p1" and linha["repeticao"] == 1:
            linha["metrica"] = RECUSA_DE_ATIVIDADE
    folha.write_text(json.dumps(bruta, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(JulgamentoInvalidoError, match="pertence a"):
        _taxas_de(rodada, folha)


def test_veredito_de_execucao_que_a_rodada_nao_tem_falha_alto(tmp_path: Path) -> None:
    rodada = _gravar_rodada(tmp_path / "rodada.json", _rodada())
    folha = _julgar(carregar_rodada(rodada), tmp_path / "folha.json")
    bruta = json.loads(folha.read_text(encoding="utf-8"))
    bruta["vereditos"].append(
        {"id": "f1", "repeticao": 9, "metrica": NAO_SABER, "veredito": "conforme", "nota": ""}
    )
    folha.write_text(json.dumps(bruta, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(JulgamentoInvalidoError, match="repetição 9"):
        _taxas_de(rodada, folha)


def test_regua_da_folha_divergente_da_rodada_falha_alto(tmp_path: Path) -> None:
    """Quem julgou por uma régua que não é a da rodada produziu um número sem dono."""
    rodada = _gravar_rodada(tmp_path / "rodada.json", _rodada())
    folha = _julgar(carregar_rodada(rodada), tmp_path / "folha.json")
    bruta = json.loads(folha.read_text(encoding="utf-8"))
    bruta["perguntas"]["f1"]["conforme_quando"] = "uma régua de outra edição"
    folha.write_text(json.dumps(bruta, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(JulgamentoInvalidoError, match="outra régua"):
        _taxas_de(rodada, folha)


@pytest.mark.parametrize("campo", ["julgador", "julgado_em"])
def test_julgador_e_data_do_julgamento_sao_obrigatorios(tmp_path: Path, campo: str) -> None:
    rodada = _gravar_rodada(tmp_path / "rodada.json", _rodada())
    folha = _julgar(carregar_rodada(rodada), tmp_path / "folha.json")
    bruta = json.loads(folha.read_text(encoding="utf-8"))
    bruta[campo] = "a preencher"
    folha.write_text(json.dumps(bruta, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(JulgamentoInvalidoError, match=campo):
        _taxas_de(rodada, folha)


def test_rodada_com_repeticao_a_menos_por_pergunta_falha_alto(tmp_path: Path) -> None:
    """Uma pergunta medida com menos repetições daria taxa com denominador curto.

    Sem a conferência, o resumo imprimia "4 perguntas × 3 repetições = 10
    execuções": as duas primeiras partes verdadeiras e a conta falsa, que é a
    forma de erro que ninguém relê.
    """
    documento = _rodada()
    documento["execucoes"] = [
        execucao
        for execucao in documento["execucoes"]
        if (execucao["id"], execucao["repeticao"]) != ("f1", 3)
    ]
    rodada = _gravar_rodada(tmp_path / "rodada.json", documento)
    folha = _julgar(carregar_rodada(rodada), tmp_path / "folha.json")

    with pytest.raises(RodadaInvalidaError, match="repetições"):
        _taxas_de(rodada, folha)


def test_rodada_que_declara_menos_repeticoes_que_rodou_falha_alto(tmp_path: Path) -> None:
    """O outro lado do mesmo defeito: a rodada que se contradiz com as próprias condições."""
    documento = _rodada()
    documento["condicoes"]["repeticoes"] = 2
    rodada = _gravar_rodada(tmp_path / "rodada.json", documento)
    folha = _julgar(carregar_rodada(rodada), tmp_path / "folha.json")

    with pytest.raises(RodadaInvalidaError, match="repetições"):
        _taxas_de(rodada, folha)


def test_rodada_de_repeticao_unica_e_uma_rodada_legitima(tmp_path: Path) -> None:
    """Nem toda rodada com menos de 3 repetições é erro: a varredura da 1.2 usa 1.

    A conferência é contra o que a rodada declara, e não contra o ADR-0003: quem
    roda `--repeticoes 1` grava `repeticoes: 1` e a conta fecha.
    """
    rodada = _gravar_rodada(tmp_path / "rodada.json", _rodada(repeticoes=1))
    folha = _julgar(carregar_rodada(rodada), tmp_path / "folha.json")

    taxa = _taxas_de(rodada, folha).taxas[NAO_SABER]

    assert taxa.esperadas == 4
    assert taxa.avaliadas == 4
    assert taxa.fracao_formatada == "4/4 = 1,00"


def test_rodada_inexistente_falha_alto(tmp_path: Path) -> None:
    with pytest.raises(RodadaInvalidaError, match="harness.run"):
        carregar_rodada(tmp_path / "nao-existe.json")


def test_rodada_que_nao_e_json_falha_alto(tmp_path: Path) -> None:
    """Um arquivo truncado é problema da rodada, e sai com o código da rodada.

    Sem a conversão, o erro cru não encontra par na tabela de códigos de saída e
    cai no 1 — o que mandaria a pessoa corrigir uma folha que está perfeita.
    """
    quebrada = tmp_path / "rodada.json"
    quebrada.write_text("{isto nao e json", encoding="utf-8")

    with pytest.raises(RodadaInvalidaError, match="não é um JSON legível"):
        carregar_rodada(quebrada)


def test_rodada_que_nao_e_utf8_falha_alto_sem_traceback(tmp_path: Path) -> None:
    """Um arquivo com byte inválido é problema da rodada, e sai com o código dela.

    `read_text` levanta `UnicodeDecodeError`, que não é `ErroDasTaxas` e escaparia
    como traceback — e o `SETUP.md` promete que nenhum caminho sai com traceback.
    """
    rodada = tmp_path / "rodada.json"
    rodada.write_bytes(b'{"execucoes": [], "lixo": "\xff\xfe"}')

    with pytest.raises(RodadaInvalidaError, match="não consegui ler a rodada"):
        carregar_rodada(rodada)


def test_folha_que_nao_e_utf8_falha_alto_sem_traceback(tmp_path: Path) -> None:
    """Folha ilegível é da folha, e sai com o código da folha."""
    rodada = _gravar_rodada(tmp_path / "rodada.json", _rodada())
    lida = carregar_rodada(rodada)
    folha = tmp_path / "folha.json"
    folha.write_bytes(b'{"julgador": "X\xff"}')

    with pytest.raises(JulgamentoInvalidoError, match="não consegui ler o julgamento"):
        carregar_julgamento(folha, lida)


def test_arquivo_de_perguntas_que_nao_e_utf8_falha_alto_sem_traceback(tmp_path: Path) -> None:
    """O arquivo das Perguntas-teste ilegível é do caminho, e sai com o código dele.

    Esta leitura era a única do módulo sem guarda: `conferir_membros` é a primeira
    coisa que o comando faz, antes de olhar a rodada, então um byte inválido nesse
    arquivo saía como `UnicodeDecodeError` cru — com pilha de Python na tela e o
    código de saída do interpretador, que é `1`. Quem lê a mensagem do `SETUP.md`
    receberia o código da folha para um arquivo que não é a folha, e o
    `docstring` do módulo promete o `3` para "um arquivo que não é UTF-8".
    """
    arquivo = tmp_path / "perguntas-teste.md"
    arquivo.write_bytes(b"<!-- pergunta:a1 -->\n| conta na m\xfftrica do #13 | x |\n")

    with pytest.raises(ArquivoInacessivelError, match="não consegui ler as Perguntas-teste"):
        conferir_membros(arquivo)

    with pytest.raises(ArquivoInacessivelError, match="não consegui ler as Perguntas-teste"):
        metricas_declaradas(arquivo)


def test_arquivo_de_perguntas_que_o_sistema_recusa_sai_pelo_codigo_do_caminho(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Permissão negada é do caminho, e sai com o código do caminho.

    O caso do byte inválido e o da permissão são o mesmo `except`, mas a promessa do
    `SETUP.md` cita os dois, e um teste que só exercita `UnicodeDecodeError` deixa o
    outro sem prova. O `monkeypatch` substitui o `read_text` porque uma permissão
    negada de verdade não se fabrica em teste portátil: `chmod` não significa a mesma
    coisa no Windows, e o modo portable de travar um arquivo não existe na stdlib.
    """
    arquivo = tmp_path / "perguntas-teste.md"
    arquivo.write_text(ARQUIVO_PERGUNTAS_PADRAO.read_text(encoding="utf-8"), encoding="utf-8")

    def sem_permissao(self: Path, *argumentos: Any, **chave: Any) -> str:
        raise PermissionError(13, "Permissão negada")

    monkeypatch.setattr(Path, "read_text", sem_permissao)

    with pytest.raises(ArquivoInacessivelError, match="não consegui ler as Perguntas-teste"):
        conferir_membros(arquivo)


def test_destino_que_nao_pode_ser_gravado_falha_alto_sem_traceback(tmp_path: Path) -> None:
    """Falha de escrita não é da folha nem da bateria, e tem código próprio.

    Sem o `3`, um disco cheio cairia no `1` e mandaria a pessoa caçar um veredito
    que está correto — que era exatamente o que o código de saída promete evitar.
    """
    lida = carregar_rodada(_gravar_rodada(tmp_path / "rodada.json", _rodada()))

    with pytest.raises(ArquivoInacessivelError, match="permissão de escrita"):
        preparar_julgamento(lida, Path("/proc/nao-existe/folha.json"))


def test_o_codigo_tres_chega_ao_shell_e_nao_vem_com_traceback(tmp_path: Path) -> None:
    """O `3` precisa aparecer no shell, senão o passo seguinte roda sobre nada."""
    rodada = _gravar_rodada(tmp_path / "rodada.json", _rodada())

    resultado = _rodar_como_modulo(
        "--rodada", str(rodada), "--preparar", "--julgamento", "/proc/nao-existe/folha.json"
    )

    assert resultado.returncode == 3, resultado.stderr
    assert "permissão de escrita" in resultado.stderr
    assert "Traceback" not in resultado.stderr


def test_main_sai_com_dois_quando_a_rodada_esta_corrompida(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rodada = tmp_path / "rodada.json"
    rodada.write_text("{isto nao e json", encoding="utf-8")

    codigo = main(["--rodada", str(rodada)])

    assert codigo == 2
    assert "FALHA" in capsys.readouterr().err


def test_rodada_sem_condicoes_falha_alto(tmp_path: Path) -> None:
    documento = _rodada()
    del documento["condicoes"]
    rodada = _gravar_rodada(tmp_path / "rodada.json", documento)

    with pytest.raises(RodadaInvalidaError, match="condicoes"):
        carregar_rodada(rodada)


def test_rodada_com_execucao_sem_veredito_falha_alto(tmp_path: Path) -> None:
    documento = _rodada()
    del documento["execucoes"][0]["conforme_quando"]
    rodada = _gravar_rodada(tmp_path / "rodada.json", documento)

    with pytest.raises(RodadaInvalidaError, match="conforme_quando"):
        carregar_rodada(rodada)


# --- A CLI ---


def _rodar_como_modulo(*argumentos: str) -> subprocess.CompletedProcess[str]:
    """Executa o comando do jeito que o SETUP.md manda rodar.

    Chamar `main([...])` não prova que `python -m harness.metrics` funciona: um
    módulo sem o guard `if __name__ == "__main__"` é importado e descartado pelo
    `-m`, e isso sai com 0 sem imprimir nada. É por isso que este teste passa por
    `subprocess`, e é o mesmo cuidado que o `harness/run.py` já exige do outro
    lado do harness.
    """
    return subprocess.run(
        [sys.executable, "-m", "harness.metrics", *argumentos],
        cwd=RAIZ,
        capture_output=True,
        text=True,
        check=False,
    )


def test_o_comodo_documentado_roda_e_nao_e_um_no_op(tmp_path: Path) -> None:
    """O comando do SETUP.md tem que escrever a folha, e dizer que escreveu.

    Sem o guard de execução o `-m` sai com 0 e não faz nada — e o 0 é, na
    contrato deste módulo, "as duas taxas foram gravadas". Quem seguiu o
    documento receberia um sucesso falso e nenhuma folha para preencher.
    """
    rodada = _gravar_rodada(tmp_path / "baseline-1.1.json", _rodada())
    folha = tmp_path / "baseline-1.1.julgamento.json"

    resultado = _rodar_como_modulo("--rodada", str(rodada), "--preparar")

    assert resultado.returncode == 0, resultado.stderr
    assert folha.is_file()
    assert "folha de julgamento escrita" in resultado.stdout
    assert "21 vereditos" in resultado.stdout
    assert json.loads(folha.read_text(encoding="utf-8"))["vereditos"][0]["resposta_bruta"]


def test_o_comando_documentado_calcula_depois_da_folha(tmp_path: Path) -> None:
    """O segundo passo do SETUP.md também tem que rodar pelo mesmo caminho."""
    rodada = _gravar_rodada(tmp_path / "baseline-1.1.json", _rodada())
    _julgar(carregar_rodada(rodada), tmp_path / "baseline-1.1.julgamento.json")

    resultado = _rodar_como_modulo("--rodada", str(rodada))

    assert resultado.returncode == 0, resultado.stderr
    assert "Taxa de não-saber — 12/12 = 1,00" in resultado.stdout
    assert (tmp_path / "baseline-1.1.metricas.json").is_file()


def test_o_comando_documentado_nao_esconde_a_falha_da_rodada(tmp_path: Path) -> None:
    """O código de saída tem que chegar ao shell, ou o passo seguinte roda sobre nada."""
    rodada = tmp_path / "rodada.json"
    rodada.write_text("{isto nao e json", encoding="utf-8")

    resultado = _rodar_como_modulo("--rodada", str(rodada))

    assert resultado.returncode == 2
    assert "FALHA" in resultado.stderr
    assert "Traceback" not in resultado.stderr


def test_main_prepara_a_folha_e_sai_com_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rodada = _gravar_rodada(tmp_path / "rodada.json", _rodada())
    folha = tmp_path / "folha.json"

    codigo = main(["--rodada", str(rodada), "--julgamento", str(folha), "--preparar"])

    assert codigo == 0
    assert folha.is_file()
    assert "21 vereditos" in capsys.readouterr().out


def test_main_calcula_grava_e_imprime_as_duas_taxas(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rodada = _gravar_rodada(tmp_path / "rodada.json", _rodada())
    folha = _julgar(carregar_rodada(rodada), tmp_path / "folha.json")
    saida = tmp_path / "metricas.json"

    codigo = main(
        ["--rodada", str(rodada), "--julgamento", str(folha), "--saida", str(saida)]
    )

    assert codigo == 0
    assert saida.is_file()
    impresso = capsys.readouterr().out
    assert "Taxa de não-saber — 12/12 = 1,00" in impresso
    assert "Taxa de recusa de Atividade — 9/9 = 1,00" in impresso


def test_main_sai_com_dois_quando_a_rodada_nao_existe(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    codigo = main(["--rodada", str(tmp_path / "nao-existe.json")])

    assert codigo == 2
    assert "FALHA" in capsys.readouterr().err


def test_main_sai_com_um_quando_o_julgamento_falta(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rodada = _gravar_rodada(tmp_path / "rodada.json", _rodada())

    codigo = main(["--rodada", str(rodada), "--julgamento", str(tmp_path / "folha.json")])

    assert codigo == 1
    assert "--preparar" in capsys.readouterr().err


def test_main_nao_deixa_traceback_vazar_quando_a_conta_nao_fecha(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Quem preenche a folha não lê pilha de Python: a falha sai como frase.

    A contagem incompleta só é descoberta na hora de calcular, depois que a
    folha foi preenchida por inteiro. Se a falha saísse como `traceback`, ela
    pareceria defeito do código em vez de defeito da rodada.

    E o código é 2, não 1: o defeito é da rodada, e quem tem o que corrigir é a
    bateria — não a folha. Dizer 1 mandaria a pessoa caçar um veredito que está
    correto.
    """
    documento = _rodada()
    documento["execucoes"] = [
        execucao
        for execucao in documento["execucoes"]
        if (execucao["id"], execucao["repeticao"]) != ("a1", 2)
    ]
    rodada = _gravar_rodada(tmp_path / "rodada.json", documento)
    folha = _julgar(carregar_rodada(rodada), tmp_path / "folha.json")

    codigo = main(["--rodada", str(rodada), "--julgamento", str(folha)])

    erro = capsys.readouterr().err
    assert codigo == 2
    assert "FALHA" in erro
    assert "Traceback" not in erro


def test_main_nomeia_os_arquivos_a_partir_do_nome_da_rodada(tmp_path: Path) -> None:
    rodada = _gravar_rodada(tmp_path / "baseline-1.1.json", _rodada())
    folha = tmp_path / "baseline-1.1.julgamento.json"

    assert main(["--rodada", str(rodada), "--preparar"]) == 0
    assert folha.is_file()

    _julgar(carregar_rodada(rodada), folha)
    codigo = main(["--rodada", str(rodada)])

    assert codigo == 0
    assert (tmp_path / "baseline-1.1.metricas.json").is_file()
