"""Harness das Perguntas-teste do S.A.U.

Envia as 10 Perguntas-teste ao S.A.U. pelo caminho real do turno
(`sau.config` + `ClienteOllama` + `sau.graph.graph.executar_turno`,
com histórico vazio, como o `webhook` faz) e grava o output bruto
de cada uma, com o comportamento esperado lado a lado.

O julgamento é humano por decisão da #6: este script grava e não
avalia. A falha ou o timeout de um turno grava `erro` no registro
do caso e a bateria segue.

Uso canônico:

    python -m harness.run
    python -m harness.run --modelo qwen2.5:3b --saida outputs/rodada.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Final

from sau.config import carregar_configuracao
from sau.graph.graph import executar_turno
from sau.inference.ollama import ClienteOllama

RAIZ_DO_PROJETO: Final = Path(__file__).resolve().parent.parent
ARQUIVO_PERGUNTAS_PADRAO: Final = RAIZ_DO_PROJETO / "perguntas-teste" / "perguntas-teste.md"
PASTA_SAIDAS_PADRAO: Final = RAIZ_DO_PROJETO / "outputs"

IDS_ESPERADOS: Final = frozenset({"a1", "a2", "a3", "f1", "f2", "f3", "p1", "p2", "p3", "p4"})
ORDEM_DA_BATERIA: Final = ("a1", "a2", "a3", "f1", "f2", "f3", "p1", "p2", "p3", "p4")

RE_BLOCO_PERGUNTA: Final = re.compile(
    r"<!--\s*pergunta:(?P<id>[a-z0-9_-]+)\s*-->\s*```text\n(?P<texto>.*?)```",
    re.DOTALL,
)
RE_CONFORME: Final = re.compile(
    r"^\s*\|\s*conforme quando\s*\|\s*(?P<valor>.*)\|\s*$",
    re.MULTILINE,
)
RE_NAO_CONFORME: Final = re.compile(
    r"^\s*\|\s*não conforme quando\s*\|\s*(?P<valor>.*)\|\s*$",
    re.MULTILINE,
)


@dataclass(frozen=True)
class PerguntaTeste:
    """Uma Pergunta-teste com o comportamento esperado dela.

    O texto é o que o harness envia ao S.A.U. O `conforme_quando` e o
    `nao_conforme_quando` vêm das linhas de mesmo nome no bloco da
    Pergunta-teste e servem para a pessoa julgar ao lado do output.
    """

    id: str
    texto: str
    conforme_quando: str
    nao_conforme_quando: str


@dataclass(frozen=True)
class RegistroDoCaso:
    """O resultado de uma Pergunta-teste na bateria.

    `resposta_bruta` é o output bruto do S.A.U., character a character.
    Quando o turno falha, ela é `None` e o motivo vai em `erro`: a
    bateria nunca aborta por causa de um caso.
    """

    id: str
    pergunta: str
    conforme_quando: str
    nao_conforme_quando: str
    resposta_bruta: str | None
    erro: str | None
    timestamp: str
    duracao_segundos: float


def carregar_perguntas_teste(caminho: Path = ARQUIVO_PERGUNTAS_PADRAO) -> list[PerguntaTeste]:
    """Lê as 10 Perguntas-teste do markdown e falha alto se o conjunto mudar.

    O formato é o que `docs/medicao-modelo/medir.py` já lê na sondagem:
    marcador `<!-- pergunta:<id> -->` seguido do bloco ```text com o texto
    que o harness envia ao S.A.U. O comportamento esperado sai das linhas
    `conforme quando` / `não conforme quando` do bloco de cada Pergunta-teste.
    """
    if not caminho.is_file():
        raise ValueError(f"as Perguntas-teste não estão em {caminho}")

    conteudo = caminho.read_text(encoding="utf-8")
    textos = {m.group("id"): m.group("texto").strip() for m in RE_BLOCO_PERGUNTA.finditer(conteudo)}

    ids_lidos = set(textos)
    faltando = sorted(IDS_ESPERADOS - ids_lidos)
    sobrando = sorted(ids_lidos - IDS_ESPERADOS)
    if faltando or sobrando:
        raise ValueError(
            "as Perguntas-teste do arquivo não batem com as 10 esperadas — "
            f"faltando {faltando}, sobrando {sobrando}, "
            f"esperadas {sorted(IDS_ESPERADOS)}"
        )

    perguntas: list[PerguntaTeste] = []
    for id_pergunta in ORDEM_DA_BATERIA:
        regiao = _regiao_do_bloco(conteudo, id_pergunta)
        conforme = _extrair_campo(regiao, RE_CONFORME, "conforme quando", id_pergunta)
        nao_conforme = _extrair_campo(regiao, RE_NAO_CONFORME, "não conforme quando", id_pergunta)
        perguntas.append(
            PerguntaTeste(
                id=id_pergunta,
                texto=textos[id_pergunta],
                conforme_quando=conforme,
                nao_conforme_quando=nao_conforme,
            )
        )
    return perguntas


RE_MARCADOR_PERGUNTA: Final = re.compile(r"<!--\s*pergunta:(?P<id>[a-z0-9_-]+)\s*-->")


def _regiao_do_bloco(conteudo: str, id_pergunta: str) -> str:
    """O trecho do markdown do marcador da Pergunta-teste até a próxima Pergunta-teste.

    O bloco de texto termina em `<!-- pergunta:fim -->`, e a tabela com o
    `conforme quando` vem depois dele: cortar no `fim` deixaria o
    comportamento esperado fora da região. Por isso a região vai até o
    marcador da próxima Pergunta-teste com id válido, e não até o próximo
    marcador qualquer.
    """
    marcadores = list(RE_MARCADOR_PERGUNTA.finditer(conteudo))
    inicio = -1
    fim = len(conteudo)
    for indice, marcador in enumerate(marcadores):
        if marcador.group("id") == id_pergunta and inicio == -1:
            inicio = marcador.start()
            for seguinte in marcadores[indice + 1 :]:
                id_seguinte = seguinte.group("id")
                if id_seguinte in IDS_ESPERADOS and id_seguinte != id_pergunta:
                    fim = seguinte.start()
                    break
            break
    if inicio == -1:
        raise ValueError(f"a Pergunta-teste {id_pergunta} não tem marcador no arquivo")
    return conteudo[inicio:fim]


def _extrair_campo(regiao: str, regex: re.Pattern[str], nome: str, id_pergunta: str) -> str:
    achado = regex.search(regiao)
    if achado is None:
        raise ValueError(f"a Pergunta-teste {id_pergunta} não tem a linha `{nome}`")
    valor = achado.group("valor").strip()
    if not valor:
        raise ValueError(f"a Pergunta-teste {id_pergunta} tem a linha `{nome}` vazia")
    return valor


def executar_bateria(
    perguntas: Sequence[PerguntaTeste],
    turno: Callable[[str], str],
) -> list[RegistroDoCaso]:
    """Roda cada Pergunta-teste no turno e isola a falha por caso.

    `turno` recebe o texto da Pergunta-teste e devolve o output bruto do
    S.A.U. Erro ou timeout viram `erro` no registro do caso e a bateria
    segue para a próxima Pergunta-teste.
    """
    registros: list[RegistroDoCaso] = []
    for pergunta in perguntas:
        timestamp = datetime.now(timezone.utc).isoformat()
        inicio = time.perf_counter()
        resposta: str | None = None
        erro: str | None = None
        try:
            resposta = turno(pergunta.texto)
        except Exception as exc:  # noqa: BLE001 — a bateria não aborta por um caso
            erro = f"{type(exc).__name__}: {exc}"
        duracao = time.perf_counter() - inicio
        registros.append(
            RegistroDoCaso(
                id=pergunta.id,
                pergunta=pergunta.texto,
                conforme_quando=pergunta.conforme_quando,
                nao_conforme_quando=pergunta.nao_conforme_quando,
                resposta_bruta=resposta,
                erro=erro,
                timestamp=timestamp,
                duracao_segundos=duracao,
            )
        )
    return registros


def gravar_rodada(
    registros: Sequence[RegistroDoCaso],
    modelo: str,
    url: str,
    destino: Path,
) -> Path:
    """Grava o JSON de uma rodada com metadados e um registro por Pergunta-teste."""
    rodada = {
        "modelo": modelo,
        "url": url,
        "inicio": registros[0].timestamp if registros else datetime.now(timezone.utc).isoformat(),
        "casos": [asdict(registro) for registro in registros],
    }
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(rodada, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return destino


def montar_argumentos(argumentos: Sequence[str] | None = None) -> argparse.Namespace:
    analisador = argparse.ArgumentParser(
        description=(
            "Roda as 10 Perguntas-teste no S.A.U. pelo caminho real do turno "
            "e grava os outputs brutos com o comportamento esperado junto. "
            "O julgamento de conforme/não-conforme é humano: este script grava, não avalia."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    analisador.add_argument(
        "--modelo",
        default=None,
        help="modelo no Ollama (padrão: o OLLAMA_MODEL do ambiente)",
    )
    analisador.add_argument(
        "--url",
        default=None,
        help="endereço do Ollama (padrão: o OLLAMA_BASE_URL do ambiente)",
    )
    analisador.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="tempo limite da geração em segundos (padrão: o OLLAMA_TIMEOUT do ambiente)",
    )
    analisador.add_argument(
        "--perguntas",
        type=Path,
        default=ARQUIVO_PERGUNTAS_PADRAO,
        help=f"arquivo das Perguntas-teste (padrão: {ARQUIVO_PERGUNTAS_PADRAO})",
    )
    analisador.add_argument(
        "--saida",
        type=Path,
        default=None,
        help="arquivo JSON da rodada (padrão: outputs/harness-<data-hora>.json)",
    )
    return analisador.parse_args(argumentos)


def _nome_padrao_de_saida() -> Path:
    carimbo = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return PASTA_SAIDAS_PADRAO / f"harness-{carimbo}.json"


def main(argumentos: Sequence[str] | None = None) -> int:
    opcoes = montar_argumentos(argumentos)
    try:
        perguntas = carregar_perguntas_teste(opcoes.perguntas)
    except ValueError as exc:
        print(f"\nFALHA: {exc}", file=sys.stderr)
        return 2

    configuracao = carregar_configuracao()
    modelo = opcoes.modelo or configuracao.ollama_model
    url = opcoes.url or configuracao.ollama_base_url
    timeout = opcoes.timeout if opcoes.timeout is not None else configuracao.ollama_timeout

    cliente = ClienteOllama(url, modelo, timeout=timeout)

    def turno(texto: str) -> str:
        return executar_turno(cliente, texto, ())

    registros = executar_bateria(perguntas, turno)
    destino = opcoes.saida or _nome_padrao_de_saida()
    gravar_rodada(registros, modelo, url, destino)

    falhas = sum(1 for registro in registros if registro.erro is not None)
    print(f"bateria: {len(registros)} Perguntas-teste, {falhas} com erro")
    print(f"JSON bruto gravado em {destino}")
    for registro in registros:
        if registro.erro:
            estado = f"erro: {registro.erro}"
        else:
            estado = f"{len(registro.resposta_bruta or '')} caracteres"
        print(f"  {registro.id}: {estado}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
