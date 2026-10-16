"""As três métricas da bateria do Manual: acerto, citação correta e "não sei" correto.

Este módulo **não julga**, e isso é decisão da #6 e não concessão: o julgamento
é humano (com a emenda do ADR-0006, pode ser redigido por um agente, e o campo
`julgador` nomeia **quem ratificou**). `preparar_julgamento` escreve a folha
com o output de cada execução na linha a julgar e o `conforme quando` de cada
Pergunta-teste no bloco `perguntas`, e uma pessoa marca `conforme`,
`nao_conforme` ou `nao_avaliavel`. O que este módulo faz é contar, e contar com
o output ao lado de cada contagem.

Três métricas, sobre as mesmas 20 perguntas da rodada do depois
(`harness/run_manual.py`):

| Métrica | O que conta | Perguntas |
| --- | --- | --- |
| `acerto` | a resposta está **correta** segundo o Manual | `b1`–`b10`, `x1`–`x5` |
| `citacao_correta` | a resposta cita a **Fonte** e ela sustenta o dito | `b1`–`b10`, `x1`–`x5` |
| `nao_sei_correto` | a resposta usa o literal de ausência e Encaminha | `n1`–`n5` |

Cada métrica sai em **dois denominadores** (ADR-0006): por **execução**
(leitura primária) e por **pergunta** (conta como acerto quando **todas** as
suas execuções avaliadas conferem; pergunta sem execução avaliada fica fora do
denominador, nunca como erro).

O que **não** entra no denominador sai listado em `fora_da_conta`, com o
motivo: a execução que o turno deixou com `erro`, a que a geração cortou por
falta de espaço (`motivo_de_parada == "length"`) e a que a pessoa marcou
`nao_avaliavel` com a razão anotada. Nenhuma delas vira `nao_conforme` por
omissão.

A **Fonte verificável por script** (`fonte_mecanica`) é conferência mecânica,
não veredito: ela diz se a resposta traz marcador de página `(p. N)` e
fragmento do título esperado. O veredito humano continua sendo o que conta —
a forma é o que a Alucinação imita bem, e um programa que decidisse "citou"
julgaria a forma.

Códigos de saída (os mesmos de `harness/metrics.py`):

- `0` — as três métricas foram calculadas e gravadas
- `1` — o julgamento está ausente, ilegível, incompleto ou inconsistente com a
  rodada
- `2` — a rodada não está lá, não é um JSON de rodada, ou não fecha a conta
  que ela mesma declara
- `3` — o caminho não pôde ser lido ou gravado

Uso canônico:

    python -m harness.metrics_manual --rodada outputs/baseline-manual-hibrido.json --preparar
    python -m harness.metrics_manual --rodada outputs/baseline-manual-hibrido.json
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final, Literal, cast

from harness.metrics import (
    A_PREENCHER,
    PARADA_CORTADA,
    SAIDA_ARQUIVO_INACESSIVEL,
    SAIDA_JULGAMENTO_INVALIDO,
    SAIDA_OK,
    SAIDA_RODADA_INVALIDA,
    TAMANHO_DO_TRECHO,
    ArquivoInacessivelError,
    ChaveExecucao,
    ErroDasTaxas,
    JulgamentoInvalidoError,
    RodadaInvalidaError,
    Veredito,
    _gravar,
    _ler_json,
    _numero,
    _texto,
    _texto_ou_nulo,
    caminho_relativo,
    sha256_de_arquivo,
)

RAIZ_DO_PROJETO: Final = Path(__file__).resolve().parent.parent

MetricaManual = Literal["acerto", "citacao_correta", "nao_sei_correto"]
StatusCitacao = Literal["verificavel", "parcial", "ausente", "nao_se_aplica"]

ACERTO: Final[MetricaManual] = "acerto"
CITACAO_CORRETA: Final[MetricaManual] = "citacao_correta"
NAO_SEI_CORRETO: Final[MetricaManual] = "nao_sei_correto"
METRICAS_MANUAL: Final[tuple[MetricaManual, ...]] = (ACERTO, CITACAO_CORRETA, NAO_SEI_CORRETO)

TITULOS_MANUAL: Final[dict[MetricaManual, str]] = {
    ACERTO: "Acerto",
    CITACAO_CORRETA: "Citação correta",
    NAO_SEI_CORRETO: '"Não sei" correto',
}
"""O nome de cada métrica como a documentação escreve."""

IDS_BASICAS: Final[tuple[str, ...]] = tuple(f"b{i}" for i in range(1, 11))
IDS_CRUZADAS: Final[tuple[str, ...]] = tuple(f"x{i}" for i in range(1, 6))
IDS_FORA: Final[tuple[str, ...]] = tuple(f"n{i}" for i in range(1, 6))
IDS_MANUAL: Final[tuple[str, ...]] = IDS_BASICAS + IDS_CRUZADAS + IDS_FORA

METRICA_POR_ID: Final[dict[str, tuple[MetricaManual, ...]]] = {
    **{id_pergunta: (ACERTO, CITACAO_CORRETA) for id_pergunta in IDS_BASICAS + IDS_CRUZADAS},
    **{id_pergunta: (NAO_SEI_CORRETO,) for id_pergunta in IDS_FORA},
}
"""Qual métrica cada Pergunta-teste alimenta: o contrato da #37, escrito em código."""

RE_PAGINA_CITADA: Final = re.compile(r"\(p\.\s*\d+(?:\s*[–-]\s*\d+)?\)")
RE_TITULO_COM_PAGINA: Final = re.compile(r"\(p\.\s*\d+(?:\s*[–-]\s*\d+)?\)\s*$")


def _normalizar(texto: str) -> str:
    """O texto em minúsculas só com letras, números e espaços, para comparar título e resposta."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9áàâãéèêíïóôõöúçñ ]", " ", texto.lower())).strip()


def _tokens_significativos(titulo: str) -> list[str]:
    """As palavras do título que provam que ele foi citado, e não um artigo solto."""
    return [token for token in _normalizar(titulo).split() if len(token) >= 4]


def titulos_esperados(fonte_esperada: str) -> list[str]:
    """Os títulos citáveis da Fonte esperada, sem o sufixo de página.

    A Fonte esperada traz um ou mais títulos separados por `;`, cada um com o
    sufixo `(p. N)`. A marca de ausência das `n` ("fora do manual — …") não tem
    título e volta vazia: nela a citação mecânica não se aplica.
    """
    if _normalizar(fonte_esperada).startswith("fora do manual"):
        return []
    titulos: list[str] = []
    for parte in fonte_esperada.split(";"):
        titulo = RE_TITULO_COM_PAGINA.sub("", parte).strip(" —-")
        titulo = titulo.strip()
        if titulo and titulo.lower() != "fora do manual":
            titulos.append(titulo)
    return titulos


def verificar_citacao_manual(resposta: str, fonte_esperada: str) -> StatusCitacao:
    """O status mecânico da citação numa resposta: página marcada e título presente.

    `verificavel` exige as duas metades da Fonte citável — o marcador `(p. N)`
    e ao menos metade (mínimo 2) dos tokens significativos de um dos títulos
    esperados. Só uma das metades é `parcial`; nenhuma é `ausente`. Na Fonte de
    ausência (as `n`) a citação não se aplica, e o veredito humano é o único
    que conta.
    """
    esperados = titulos_esperados(fonte_esperada)
    if not esperados:
        return "nao_se_aplica"
    tem_pagina = RE_PAGINA_CITADA.search(resposta) is not None
    normalizada = _normalizar(resposta)
    tem_titulo = any(
        sum(1 for token in _tokens_significativos(titulo) if token in normalizada)
        >= max(2, (len(_tokens_significativos(titulo)) + 1) // 2)
        and _tokens_significativos(titulo)
        for titulo in esperados
    )
    if tem_pagina and tem_titulo:
        return "verificavel"
    if tem_pagina or tem_titulo:
        return "parcial"
    return "ausente"


@dataclass(frozen=True)
class ExecucaoManual:
    """Uma execução da rodada do Manual: uma Pergunta-teste, uma vez."""

    id: str
    repeticao: int
    pergunta: str
    tipo: str
    fonte_esperada: str
    conforme_quando: str
    nao_conforme_quando: str
    resposta_bruta: str | None
    erro: str | None
    motivo_de_parada: str | None
    fontes_recuperadas: tuple[str, ...]
    timestamp: str

    @property
    def chave(self) -> ChaveExecucao:
        return ChaveExecucao(self.id, self.repeticao)

    @property
    def julgavel(self) -> bool:
        """Se esta execução pode receber veredito de quem julga.

        Não pode quem não tem resposta nem quem teve a geração cortada por
        falta de espaço. O Encaminhamento determinístico (`deterministico`) é
        julgável — o Aluno leu uma resposta completa, só não foi o modelo quem
        a escreveu.
        """
        return self.resposta_bruta is not None and self.motivo_de_parada != PARADA_CORTADA


@dataclass(frozen=True)
class RodadaManual:
    """O JSON de uma rodada do Manual, lido e conferido."""

    caminho: str
    sha256: str
    modelo: str
    url: str
    condicoes: dict[str, Any]
    repeticoes: int
    alocacao: dict[str, Any] | None
    manual: dict[str, Any]
    execucoes: tuple[ExecucaoManual, ...]


@dataclass(frozen=True)
class VereditoManual:
    """O veredito de uma pessoa sobre uma execução, para uma métrica do Manual."""

    id: str
    repeticao: int
    metrica: MetricaManual
    veredito: Veredito
    nota: str

    @property
    def chave(self) -> tuple[ChaveExecucao, MetricaManual]:
        return (ChaveExecucao(self.id, self.repeticao), self.metrica)


@dataclass(frozen=True)
class JulgamentoManual:
    """A folha de julgamento da rodada do Manual: quem ratificou, quando e o que disse."""

    caminho: str
    sha256_da_rodada: str
    julgador: str
    julgado_em: str
    redigido_por: str
    vereditos: tuple[VereditoManual, ...]


@dataclass(frozen=True)
class EvidenciaManual:
    """Uma contagem do Manual e o output que a originou, inteiro."""

    id: str
    repeticao: int
    veredito: str
    pergunta: str
    resposta_bruta: str
    fontes_recuperadas: tuple[str, ...]
    motivo_de_parada: str | None


@dataclass(frozen=True)
class LeituraDaPerguntaManual:
    """A mesma métrica lida por pergunta: acertou sempre, errou sempre ou variou."""

    id: str
    metrica: MetricaManual
    conformes: int
    avaliadas: int
    leitura: Literal["estavel", "variavel", "sem_avaliacao"]


@dataclass(frozen=True)
class ForaDaContaManual:
    """Uma execução que existe na rodada e não entra em nenhuma contagem."""

    id: str
    repeticao: int
    motivo: Literal["erro", "cortada", "julgada"]
    detalhe: str
    resposta_bruta: str | None = None


@dataclass(frozen=True)
class TaxaManual:
    """Uma das três métricas, com numerador, denominador e evidência dos dois."""

    metrica: MetricaManual
    perguntas: int
    repeticoes: int
    esperadas: int
    avaliadas: int
    numerador: int
    fracao: float
    fracao_formatada: str
    perguntas_conformes: int
    perguntas_avaliadas: int
    fracao_por_pergunta: float
    fracao_por_pergunta_formatada: str
    acertos: tuple[EvidenciaManual, ...]
    erros: tuple[EvidenciaManual, ...]
    por_pergunta: tuple[LeituraDaPerguntaManual, ...]
    fora_da_conta: tuple[ForaDaContaManual, ...]


@dataclass(frozen=True)
class CitacaoMecanica:
    """A conferência mecânica da citação de uma execução, sem veredito."""

    id: str
    repeticao: int
    status: StatusCitacao
    paginas_citadas: tuple[str, ...]
    titulos_esperados: tuple[str, ...]


@dataclass(frozen=True)
class RelatorioManual:
    """As três métricas da rodada do Manual, com a rodada e o julgamento."""

    rodada: RodadaManual
    julgamento: JulgamentoManual
    taxas: dict[MetricaManual, TaxaManual]
    fonte_mecanica: tuple[CitacaoMecanica, ...]


def _ler_execucao_manual(bruto: Any, onde: str) -> ExecucaoManual:
    """Uma execução da rodada do Manual, com o campo faltando nomeado no erro."""
    fontes = bruto.get("fontes_recuperadas", []) if isinstance(bruto, dict) else []
    if fontes is None:
        fontes = []
    if not isinstance(fontes, list) or not all(isinstance(item, str) for item in fontes):
        raise ErroDasTaxas(f"{onde}: o campo `fontes_recuperadas` não é uma lista de textos")
    return ExecucaoManual(
        id=_texto(bruto, "id", onde),
        repeticao=_numero(bruto, "repeticao", onde),
        pergunta=_texto(bruto, "pergunta", onde),
        tipo=_texto(bruto, "tipo", onde),
        fonte_esperada=_texto(bruto, "fonte_esperada", onde),
        conforme_quando=_texto(bruto, "conforme_quando", onde),
        nao_conforme_quando=_texto(bruto, "nao_conforme_quando", onde),
        resposta_bruta=_texto_ou_nulo(bruto, "resposta_bruta", onde),
        erro=_texto_ou_nulo(bruto, "erro", onde),
        motivo_de_parada=_texto_ou_nulo(bruto, "motivo_de_parada", onde),
        fontes_recuperadas=tuple(fontes),
        timestamp=_texto(bruto, "timestamp", onde),
    )


def carregar_rodada_manual(caminho: Path) -> RodadaManual:
    """Lê o JSON de uma rodada do Manual e confere o que este módulo precisa."""
    if not caminho.is_file():
        raise RodadaInvalidaError(
            "a rodada do Manual não está em "
            f"{caminho}. Ela sai de `python -m harness.run_manual "
            "--saida outputs/baseline-manual-hibrido.json`"
        )
    try:
        bruto = _ler_json(caminho, "a rodada do Manual")
        if not isinstance(bruto, dict):
            raise ErroDasTaxas("a rodada do Manual não é um objeto JSON")
        onde = f"a rodada do Manual em {caminho}"
        execucoes = bruto.get("execucoes")
        if not isinstance(execucoes, list):
            raise ErroDasTaxas("o campo `execucoes` não é uma lista")
        lidas = tuple(
            _ler_execucao_manual(item, f"execução {indice + 1}")
            for indice, item in enumerate(execucoes)
        )
        condicoes = bruto.get("condicoes")
        if not isinstance(condicoes, dict):
            raise ErroDasTaxas("o campo `condicoes` não é um objeto")
        repeticoes = _numero(condicoes, "repeticoes", f"{onde}, em `condicoes`")
        alocacao = bruto.get("alocacao")
        if alocacao is not None and not isinstance(alocacao, dict):
            raise ErroDasTaxas("o campo `alocacao` não é um objeto nem nulo")
        manual = bruto.get("manual")
        if not isinstance(manual, dict):
            raise ErroDasTaxas("o campo `manual` não é um objeto")
        rodada = RodadaManual(
            caminho=caminho_relativo(caminho),
            sha256=sha256_de_arquivo(caminho),
            modelo=_texto(bruto, "modelo", onde),
            url=_texto(bruto, "url", onde),
            condicoes=dict(condicoes),
            repeticoes=repeticoes,
            alocacao=dict(alocacao) if isinstance(alocacao, dict) else None,
            manual=dict(manual),
            execucoes=lidas,
        )
    except ErroDasTaxas as exc:
        raise RodadaInvalidaError(str(exc)) from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise RodadaInvalidaError(
            f"não consegui ler a rodada do Manual em {caminho}: {exc}"
        ) from exc
    _conferir_execucoes(rodada)
    return rodada


def _conferir_execucoes(rodada: RodadaManual) -> None:
    """Cada uma das 20 perguntas tem as repetições que a rodada declara ter, e só elas."""
    ids = sorted({execucao.id for execucao in rodada.execucoes})
    if ids != sorted(IDS_MANUAL):
        raise RodadaInvalidaError(
            f"a rodada do Manual em {rodada.caminho} traz as perguntas {ids} e as 20 "
            f"esperadas são {sorted(IDS_MANUAL)}"
        )
    contadas: dict[str, int] = dict.fromkeys(IDS_MANUAL, 0)
    for execucao in rodada.execucoes:
        contadas[execucao.id] += 1
    fora = {
        id_pergunta: total
        for id_pergunta, total in contadas.items()
        if total != rodada.repeticoes
    }
    if fora:
        raise RodadaInvalidaError(
            f"a rodada do Manual em {rodada.caminho} declara {rodada.repeticoes} "
            f"repetições, mas as perguntas têm {fora}"
        )


def metricas_da_execucao(execucao: ExecucaoManual) -> tuple[MetricaManual, ...]:
    """As métricas que uma execução alimenta, pelo id da pergunta."""
    metricas = METRICA_POR_ID.get(execucao.id)
    if metricas is None:
        raise RodadaInvalidaError(
            f"a execução {execucao.id} repetição {execucao.repeticao} não é de nenhuma "
            "das 20 perguntas da bateria do Manual"
        )
    return metricas


def folha_de_julgamento(rodada: RodadaManual) -> dict[str, Any]:
    """A folha de julgamento da rodada do Manual, com a régua e os vereditos em branco.

    Cada execução julgável ganha uma linha por métrica que ela alimenta — duas
    nas `b`/`x` (acerto e citação correta), uma nas `n` ("não sei" correto) —,
    cada uma com o output inteiro ao lado do veredito. A régua vem no bloco
    `perguntas`, com o `conforme quando` e o `não conforme quando` de cada
    pergunta. A Fonte verificável por script não entra na folha: ela é
    mecânica, e sai do cálculo.
    """
    perguntas: dict[str, dict[str, str]] = {}
    vereditos: list[dict[str, Any]] = []
    for execucao in rodada.execucoes:
        perguntas.setdefault(
            execucao.id,
            {
                "pergunta": execucao.pergunta,
                "tipo": execucao.tipo,
                "fonte_esperada": execucao.fonte_esperada,
                "conforme_quando": execucao.conforme_quando,
                "nao_conforme_quando": execucao.nao_conforme_quando,
            },
        )
        if not execucao.julgavel:
            continue
        for metrica in metricas_da_execucao(execucao):
            vereditos.append(
                {
                    "id": execucao.id,
                    "repeticao": execucao.repeticao,
                    "metrica": metrica,
                    "resposta_bruta": execucao.resposta_bruta,
                    "veredito": A_PREENCHER,
                    "nota": "",
                }
            )
    return {
        "rodada": rodada.caminho,
        "sha256_da_rodada": rodada.sha256,
        "julgador": A_PREENCHER,
        "julgado_em": A_PREENCHER,
        "redigido_por": A_PREENCHER,
        "perguntas": perguntas,
        "vereditos": vereditos,
    }


def preparar_julgamento(rodada: RodadaManual, destino: Path) -> Path:
    """Escreve em disco a folha que `folha_de_julgamento` monta, e diz quantas linhas."""
    folha = folha_de_julgamento(rodada)
    _gravar(destino, folha)
    pendentes = len(folha["vereditos"])
    print(f"folha de julgamento escrita em {destino}")
    print(
        f"{pendentes} vereditos a preencher. Preencha `julgador`, `julgado_em`, "
        "`redigido_por` e o `veredito` de cada linha, e depois rode sem `--preparar`"
    )
    return destino


def _indice(rodada: RodadaManual) -> dict[ChaveExecucao, ExecucaoManual]:
    return {execucao.chave: execucao for execucao in rodada.execucoes}


def _ler_vereditos(bruto: Any, rodada: RodadaManual, onde: str) -> tuple[VereditoManual, ...]:
    """Os vereditos da folha, contra o vocabulário e a cobertura por métrica."""
    if not isinstance(bruto, list):
        raise ErroDasTaxas(f"{onde}: o campo `vereditos` não é uma lista")
    da_rodada = _indice(rodada)
    vistos: set[tuple[ChaveExecucao, MetricaManual]] = set()
    vereditos: list[VereditoManual] = []
    for indice, item in enumerate(bruto):
        lugar = f"{onde}, veredito {indice + 1}"
        if not isinstance(item, dict):
            raise ErroDasTaxas(f"{lugar} não é um objeto JSON")
        id_pergunta = _texto(item, "id", lugar)
        repeticao = _numero(item, "repeticao", lugar)
        metrica_bruta = _texto(item, "metrica", lugar)
        if metrica_bruta == ACERTO:
            metrica = ACERTO
        elif metrica_bruta == CITACAO_CORRETA:
            metrica = CITACAO_CORRETA
        elif metrica_bruta == NAO_SEI_CORRETO:
            metrica = NAO_SEI_CORRETO
        else:
            raise ErroDasTaxas(
                f"{lugar}: a métrica `{metrica_bruta}` não é uma das três do Manual "
                f"({', '.join(METRICAS_MANUAL)})"
            )
        chave = ChaveExecucao(id_pergunta, repeticao)
        execucao = da_rodada.get(chave)
        if execucao is None:
            raise JulgamentoInvalidoError(
                f"{lugar} é da execução {chave.como_texto()}, que não está na rodada"
            )
        if metrica not in metricas_da_execucao(execucao):
            raise JulgamentoInvalidoError(
                f"{lugar}: a métrica `{metrica}` não se aplica à pergunta `{id_pergunta}`"
            )
        veredito_bruto = _texto(item, "veredito", lugar)
        if veredito_bruto not in ("conforme", "nao_conforme", "nao_avaliavel"):
            raise ErroDasTaxas(
                f"{lugar}: o veredito `{veredito_bruto}` não é conforme, nao_conforme nem "
                "nao_avaliavel"
            )
        nota_bruta = item.get("nota", "")
        if not isinstance(nota_bruta, str):
            raise ErroDasTaxas(f"{lugar}: o campo `nota` não é texto")
        if veredito_bruto == "nao_avaliavel" and not nota_bruta.strip():
            raise JulgamentoInvalidoError(
                f"{lugar} marca `nao_avaliavel` sem dizer o motivo em `nota`: uma "
                "execução fora da conta sem motivo declarado é uma execução escondida"
            )
        copia = item.get("resposta_bruta")
        if copia != execucao.resposta_bruta:
            raise JulgamentoInvalidoError(
                f"{lugar} traz um `resposta_bruta` que não é o da rodada: alguém julgou "
                "um output que a rodada não produziu"
            )
        par = (chave, metrica)
        if par in vistos:
            raise JulgamentoInvalidoError(
                f"{lugar} repete o veredito de {chave.como_texto()} na métrica `{metrica}`"
            )
        vistos.add(par)
        vereditos.append(
            VereditoManual(
                id=id_pergunta,
                repeticao=repeticao,
                metrica=metrica,
                veredito=cast(Veredito, veredito_bruto),
                nota=nota_bruta,
            )
        )
    return tuple(vereditos)


def _conferir_reguas(bruto: Any, rodada: RodadaManual, onde: str) -> None:
    """A régua da folha é a da rodada, pergunta por pergunta."""
    if not isinstance(bruto, dict):
        raise ErroDasTaxas(f"{onde}: o campo `perguntas` não é um objeto")
    for id_pergunta in IDS_MANUAL:
        bloco = bruto.get(id_pergunta)
        if not isinstance(bloco, dict):
            raise JulgamentoInvalidoError(
                f"{onde}: a régua da pergunta `{id_pergunta}` sumiu da folha"
            )
        alguma = next(execucao for execucao in rodada.execucoes if execucao.id == id_pergunta)
        for campo in (
            "pergunta",
            "tipo",
            "fonte_esperada",
            "conforme_quando",
            "nao_conforme_quando",
        ):
            valor = bloco.get(campo)
            esperado = getattr(alguma, campo)
            if valor != esperado:
                raise JulgamentoInvalidoError(
                    f"{onde}: a régua da pergunta `{id_pergunta}` divergiu da rodada no "
                    f"campo `{campo}` — a folha foi preenchida contra outra rodada"
                )


def _conferir_cobertura(
    vereditos: Sequence[VereditoManual], rodada: RodadaManual, onde: str
) -> None:
    """Cada execução julgável tem veredito em cada métrica que ela alimenta, e só nelas."""
    esperados: set[tuple[ChaveExecucao, MetricaManual]] = set()
    for execucao in rodada.execucoes:
        if not execucao.julgavel:
            continue
        for metrica in metricas_da_execucao(execucao):
            esperados.add((execucao.chave, metrica))
    dados = {(veredito.chave[0], veredito.chave[1]) for veredito in vereditos}
    faltando = sorted(
        f"{chave.como_texto()} na métrica `{metrica}`" for chave, metrica in esperados - dados
    )
    sobrando = sorted(
        f"{chave.como_texto()} na métrica `{metrica}`" for chave, metrica in dados - esperados
    )
    if faltando or sobrando:
        raise JulgamentoInvalidoError(
            f"{onde}: a cobertura dos vereditos não fecha — sem veredito: {faltando}; "
            f"veredito sem execução julgável: {sobrando}"
        )


def carregar_julgamento(caminho: Path, rodada: RodadaManual) -> JulgamentoManual:
    """Lê a folha de julgamento e falha alto em tudo que a deixaria menteira."""
    if not caminho.is_file():
        raise JulgamentoInvalidoError(
            f"o julgamento não está em {caminho}. Ele nasce de "
            f"`python -m harness.metrics_manual --rodada {rodada.caminho} --preparar`"
        )
    try:
        bruto = _ler_json(caminho, "o julgamento")
        if not isinstance(bruto, dict):
            raise ErroDasTaxas("o julgamento não é um objeto JSON")
        onde = f"o julgamento em {caminho}"
        sha = _texto(bruto, "sha256_da_rodada", onde)
        if sha != rodada.sha256:
            raise JulgamentoInvalidoError(
                f"é o julgamento de outra rodada: o sha256 guardado é {sha} e a "
                f"rodada {rodada.caminho} tem {rodada.sha256}"
            )
        for campo in ("julgador", "julgado_em", "redigido_por"):
            if _texto(bruto, campo, onde) == A_PREENCHER:
                raise JulgamentoInvalidoError(
                    f"o campo `{campo}` está `{A_PREENCHER}`. A taxa precisa dizer "
                    "quem redigiu, quem ratificou e quando — é isso que separa um "
                    "número de uma opinião"
                )
        _conferir_reguas(bruto.get("perguntas"), rodada, onde)
        vereditos = _ler_vereditos(bruto.get("vereditos"), rodada, onde)
        _conferir_cobertura(vereditos, rodada, onde)
    except JulgamentoInvalidoError:
        raise
    except ErroDasTaxas as exc:
        raise JulgamentoInvalidoError(str(exc)) from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise JulgamentoInvalidoError(f"não consegui ler o julgamento em {caminho}: {exc}") from exc
    return JulgamentoManual(
        caminho=caminho_relativo(caminho),
        sha256_da_rodada=sha,
        julgador=str(bruto["julgador"]),
        julgado_em=str(bruto["julgado_em"]),
        redigido_por=str(bruto["redigido_por"]),
        vereditos=vereditos,
    )


def _calcular_uma(
    rodada: RodadaManual,
    indice: Mapping[tuple[ChaveExecucao, MetricaManual], VereditoManual],
    metrica: MetricaManual,
) -> TaxaManual:
    """Uma métrica, com numerador, denominador e evidência dos dois."""
    perguntas_da_metrica = [
        id_pergunta for id_pergunta in IDS_MANUAL if metrica in METRICA_POR_ID[id_pergunta]
    ]
    acertos: list[EvidenciaManual] = []
    erros: list[EvidenciaManual] = []
    fora: list[ForaDaContaManual] = []
    por_pergunta: list[LeituraDaPerguntaManual] = []
    avaliadas = 0
    numerador = 0
    perguntas_conformes = 0
    perguntas_avaliadas = 0
    for id_pergunta in perguntas_da_metrica:
        execucoes = [execucao for execucao in rodada.execucoes if execucao.id == id_pergunta]
        conformes = 0
        avaliadas_da_pergunta = 0
        for execucao in execucoes:
            if execucao.erro is not None:
                fora.append(
                    ForaDaContaManual(
                        id=execucao.id,
                        repeticao=execucao.repeticao,
                        motivo="erro",
                        detalhe=str(execucao.erro),
                        resposta_bruta=None,
                    )
                )
                continue
            if execucao.motivo_de_parada == PARADA_CORTADA:
                fora.append(
                    ForaDaContaManual(
                        id=execucao.id,
                        repeticao=execucao.repeticao,
                        motivo="cortada",
                        detalhe="geração cortada por falta de espaço (length)",
                        resposta_bruta=execucao.resposta_bruta,
                    )
                )
                continue
            veredito = indice[(execucao.chave, metrica)]
            if veredito.veredito == "nao_avaliavel":
                fora.append(
                    ForaDaContaManual(
                        id=execucao.id,
                        repeticao=execucao.repeticao,
                        motivo="julgada",
                        detalhe=f"marcada nao_avaliavel: {veredito.nota}",
                        resposta_bruta=execucao.resposta_bruta,
                    )
                )
                continue
            avaliadas_da_pergunta += 1
            avaliadas += 1
            evidencia = EvidenciaManual(
                id=execucao.id,
                repeticao=execucao.repeticao,
                veredito=veredito.veredito,
                pergunta=execucao.pergunta,
                resposta_bruta=str(execucao.resposta_bruta),
                fontes_recuperadas=execucao.fontes_recuperadas,
                motivo_de_parada=execucao.motivo_de_parada,
            )
            if veredito.veredito == "conforme":
                conformes += 1
                numerador += 1
                acertos.append(evidencia)
            else:
                erros.append(evidencia)
        if avaliadas_da_pergunta == 0:
            leitura: Literal["estavel", "variavel", "sem_avaliacao"] = "sem_avaliacao"
        else:
            perguntas_avaliadas += 1
            if conformes == avaliadas_da_pergunta:
                perguntas_conformes += 1
                leitura = "estavel"
            elif conformes == 0:
                leitura = "estavel"
            else:
                leitura = "variavel"
        por_pergunta.append(
            LeituraDaPerguntaManual(
                id=id_pergunta,
                metrica=metrica,
                conformes=conformes,
                avaliadas=avaliadas_da_pergunta,
                leitura=leitura,
            )
        )
    esperadas = len(perguntas_da_metrica) * rodada.repeticoes
    fracao = numerador / avaliadas if avaliadas else 0.0
    fracao_por_pergunta = perguntas_conformes / perguntas_avaliadas if perguntas_avaliadas else 0.0
    return TaxaManual(
        metrica=metrica,
        perguntas=len(perguntas_da_metrica),
        repeticoes=rodada.repeticoes,
        esperadas=esperadas,
        avaliadas=avaliadas,
        numerador=numerador,
        fracao=fracao,
        fracao_formatada=f"{numerador}/{avaliadas} = {_em_portugues(fracao)}",
        perguntas_conformes=perguntas_conformes,
        perguntas_avaliadas=perguntas_avaliadas,
        fracao_por_pergunta=fracao_por_pergunta,
        fracao_por_pergunta_formatada=(
            f"{perguntas_conformes}/{perguntas_avaliadas} perguntas = "
            f"{_em_portugues(fracao_por_pergunta)}"
        ),
        acertos=tuple(acertos),
        erros=tuple(erros),
        por_pergunta=tuple(por_pergunta),
        fora_da_conta=tuple(fora),
    )


def _em_portugues(valor: float) -> str:
    """O número com vírgula decimal, como o resto da documentação escreve."""
    return f"{valor:.2f}".replace(".", ",")


def conferir_fonte_mecanica(rodada: RodadaManual) -> tuple[CitacaoMecanica, ...]:
    """A conferência mecânica da citação em cada execução julgável de `b`/`x`.

    Não é veredito e não entra em denominador nenhum: é a evidência mecânica
    que acompanha o número, para que a leitura da citação não dependa só do
    olho de quem julgou.
    """
    saidas: list[CitacaoMecanica] = []
    for execucao in rodada.execucoes:
        if not execucao.julgavel:
            continue
        if ACERTO not in METRICA_POR_ID.get(execucao.id, ()):
            continue
        resposta = str(execucao.resposta_bruta)
        saidas.append(
            CitacaoMecanica(
                id=execucao.id,
                repeticao=execucao.repeticao,
                status=verificar_citacao_manual(resposta, execucao.fonte_esperada),
                paginas_citadas=tuple(RE_PAGINA_CITADA.findall(resposta)),
                titulos_esperados=tuple(titulos_esperados(execucao.fonte_esperada)),
            )
        )
    return tuple(saidas)


def calcular(rodada: RodadaManual, julgamento: JulgamentoManual) -> RelatorioManual:
    """Calcula as três métricas, com a evidência de cada contagem."""
    indice = {veredito.chave: veredito for veredito in julgamento.vereditos}
    taxas = {metrica: _calcular_uma(rodada, indice, metrica) for metrica in METRICAS_MANUAL}
    return RelatorioManual(
        rodada=rodada,
        julgamento=julgamento,
        taxas=taxas,
        fonte_mecanica=conferir_fonte_mecanica(rodada),
    )


def gravar_metricas(relatorio: RelatorioManual, destino: Path) -> Path:
    """Grava o JSON das métricas: os números, a evidência e de onde saíram."""
    rodada = relatorio.rodada
    documento = {
        "rodada": rodada.caminho,
        "sha256_da_rodada": rodada.sha256,
        "modelo": rodada.modelo,
        "url": rodada.url,
        "condicoes": rodada.condicoes,
        "manual": rodada.manual,
        "alocacao": rodada.alocacao,
        "julgamento": {
            "arquivo": relatorio.julgamento.caminho,
            "sha256_da_rodada": relatorio.julgamento.sha256_da_rodada,
            "julgador": relatorio.julgamento.julgador,
            "julgado_em": relatorio.julgamento.julgado_em,
            "redigido_por": relatorio.julgamento.redigido_por,
        },
        "taxas": {metrica: asdict(taxa) for metrica, taxa in relatorio.taxas.items()},
        "fonte_mecanica": [asdict(item) for item in relatorio.fonte_mecanica],
    }
    _gravar(destino, documento)
    return destino


def resumo_em_markdown(relatorio: RelatorioManual) -> str:
    """A página que vai para o relato: os três números, a evidência e a régua."""
    rodada = relatorio.rodada
    julgamento = relatorio.julgamento
    partes = [
        "## As três métricas do depois (híbrido)",
        "",
        f"- Rodada: `{rodada.caminho}` — sha256 `{rodada.sha256}`",
        f"- Modelo: `{rodada.modelo}` — {rodada.repeticoes} repetições",
        f"- Manual: modo {rodada.manual.get('modo_busca')}, limiar "
        f"{rodada.manual.get('limiar')}, k {rodada.manual.get('k_padrao')}, "
        f"{rodada.manual.get('total_chunks')} chunks, PDF `{rodada.manual.get('pdf_sha256')}`",
        f"- Julgamento: `{julgamento.caminho}` — redigido por {julgamento.redigido_por}, "
        f"ratificado por {julgamento.julgador} em {julgamento.julgado_em}",
        "",
    ]
    for metrica in METRICAS_MANUAL:
        taxa = relatorio.taxas[metrica]
        partes.extend(
            [
                f"### {TITULOS_MANUAL[metrica]} — {taxa.fracao_formatada}",
                "",
                f"Por pergunta: **{taxa.fracao_por_pergunta_formatada}**.",
                "",
                f"Denominador por execução: {taxa.perguntas} perguntas × "
                f"{taxa.repeticoes} repetições = {taxa.esperadas} execuções, "
                f"{taxa.avaliadas} avaliadas, {len(taxa.fora_da_conta)} fora da conta.",
                "",
                "| Pergunta | Acerto | Avaliadas | Comportamento |",
                "| --- | --- | --- | --- |",
            ]
        )
        partes.extend(
            f"| `{leitura.id}` | {leitura.conformes} | {leitura.avaliadas} "
            f"| {leitura.leitura} |"
            for leitura in taxa.por_pergunta
        )
        partes.extend(["", "**Acerto — a evidência do numerador**", ""])
        partes.extend(_linhas_de_evidencia(taxa.acertos))
        if taxa.erros:
            partes.extend(
                [
                    "",
                    f"**Erro — o resto do denominador** ({taxa.avaliadas} avaliadas = "
                    f"{taxa.numerador} acertos + {len(taxa.erros)} erros)",
                    "",
                ]
            )
            partes.extend(_linhas_de_evidencia(taxa.erros))
        if taxa.fora_da_conta:
            partes.extend(["", "**Fora da conta**", ""])
            partes.extend(_linhas_de_fora_da_conta(taxa.fora_da_conta))
        partes.append("")
    mecanica = relatorio.fonte_mecanica
    verificaveis = sum(1 for item in mecanica if item.status == "verificavel")
    partes.extend(
        [
            "### Fonte verificável por script (mecânica, sem veredito)",
            "",
            f"{verificaveis}/{len(mecanica)} execuções de `b`/`x` com página marcada e "
            "título esperado presentes. O veredito humano continua sendo o que conta.",
            "",
        ]
    )
    partes.extend(
        f"- `{item.id}` repetição {item.repeticao} — {item.status}"
        for item in mecanica
        if item.status != "verificavel"
    )
    partes.append("")
    return "\n".join(partes).rstrip() + "\n"


def _trecho(resposta: str) -> str:
    limpa = resposta.strip()
    if len(limpa) <= TAMANHO_DO_TRECHO:
        return limpa
    return f"{limpa[:TAMANHO_DO_TRECHO]}…"


def _linhas_de_evidencia(evidencias: Sequence[EvidenciaManual]) -> list[str]:
    linhas = [
        f"- `{evidencia.id}` repetição {evidencia.repeticao} — "
        f"\"{_trecho(evidencia.resposta_bruta)}\""
        for evidencia in evidencias
    ]
    return linhas or ["- nenhuma"]


def _linhas_de_fora_da_conta(itens: Sequence[ForaDaContaManual]) -> list[str]:
    linhas = [
        f"- `{item.id}` repetição {item.repeticao} — {item.motivo}: {item.detalhe}"
        + (f' — "{_trecho(item.resposta_bruta)}"' if item.resposta_bruta else "")
        for item in itens
    ]
    return linhas or ["- nenhuma"]


def montar_argumentos(argumentos: Sequence[str] | None = None) -> argparse.Namespace:
    analisador = argparse.ArgumentParser(
        description=(
            "Calcula as três métricas da bateria do Manual a partir da rodada e da "
            "folha de julgamento humano. Uso em dois passos: primeiro --preparar "
            "para escrever a folha, depois sem --preparar para calcular."
        ),
    )
    analisador.add_argument(
        "--rodada",
        type=Path,
        required=True,
        help="arquivo JSON da rodada do Manual",
    )
    analisador.add_argument(
        "--preparar",
        action="store_true",
        help="escreve a folha de julgamento em branco e sai",
    )
    analisador.add_argument(
        "--julgamento",
        type=Path,
        default=None,
        help="arquivo JSON do julgamento (padrão: <rodada>.julgamento.json)",
    )
    analisador.add_argument(
        "--saida",
        type=Path,
        default=None,
        help="arquivo JSON das métricas (padrão: <rodada>.metricas.json)",
    )
    return analisador.parse_args(argumentos)


def _padrao_de_nome(rodada: Path, sufixo: str) -> Path:
    return rodada.with_name(f"{rodada.stem}{sufixo}.json")


def main(argumentos: Sequence[str] | None = None) -> int:
    opcoes = montar_argumentos(argumentos)
    try:
        rodada = carregar_rodada_manual(opcoes.rodada)
    except RodadaInvalidaError as exc:
        print(f"\nFALHA: {exc}", file=sys.stderr)
        return SAIDA_RODADA_INVALIDA
    except ArquivoInacessivelError as exc:
        print(f"\nFALHA: {exc}", file=sys.stderr)
        return SAIDA_ARQUIVO_INACESSIVEL

    if opcoes.preparar:
        destino = opcoes.julgamento or _padrao_de_nome(opcoes.rodada, ".julgamento")
        try:
            preparar_julgamento(rodada, destino)
        except ArquivoInacessivelError as exc:
            print(f"\nFALHA: {exc}", file=sys.stderr)
            return SAIDA_ARQUIVO_INACESSIVEL
        return SAIDA_OK

    caminho = opcoes.julgamento or _padrao_de_nome(opcoes.rodada, ".julgamento")
    try:
        julgamento = carregar_julgamento(caminho, rodada)
    except (JulgamentoInvalidoError, ArquivoInacessivelError) as exc:
        print(f"\nFALHA: {exc}", file=sys.stderr)
        return SAIDA_JULGAMENTO_INVALIDO
    except RodadaInvalidaError as exc:
        print(f"\nFALHA: {exc}", file=sys.stderr)
        return SAIDA_RODADA_INVALIDA

    relatorio = calcular(rodada, julgamento)
    destino = opcoes.saida or _padrao_de_nome(opcoes.rodada, ".metricas")
    try:
        gravar_metricas(relatorio, destino)
    except ArquivoInacessivelError as exc:
        print(f"\nFALHA: {exc}", file=sys.stderr)
        return SAIDA_ARQUIVO_INACESSIVEL
    print(resumo_em_markdown(relatorio))
    print(f"JSON das métricas gravado em {destino}")
    return SAIDA_OK


if __name__ == "__main__":
    raise SystemExit(main())
