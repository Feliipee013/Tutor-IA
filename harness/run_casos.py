"""Harness dos cinco Casos de alucinação da 1.2.

Roda os Casos de `harness/casos.py` no S.A.U. pelo caminho real do turno, com
as mesmas travas da bateria (`temperature 0`, `seed` 20260926, `num_predict`
256) e grava a rodada dos Casos com o material que a recuperação devolveu em
cada turno.

É o mesmo harness da 1.1 nos dois lados que importam: o turno é o
`executar_turno` real (via grafo remontado por turno, como o `webhook` faz), o
cliente é o `ClienteMedido` com as travas da medição, e as condições vão no
JSON com modelo, alocação, `sha256` do prompt e o bloco de recuperação lido do
índice montado (`descrever_recuperacao(ultimo_indice())`).

A diferença para a bateria é o que se grava por execução: além da resposta, as
`fontes_recuperadas` do turno (os títulos do top-k). É daqui que saem o falso
positivo de similaridade — que conta recuperação — e a conferência de que a
recuperação estava ligada no lado de depois. Sem elas, a rodada diria o que o
S.A.U. respondeu e não com o que ele respondeu.

O "antes" não é bateria nova: as execuções de `c1` a `c5` são as que a 1.1 já
gravou em `outputs/baseline-1.1.json` (`p4`, `p2`, `p3`, `p1`, `f3`), julgadas
aqui sob a régua dos Casos. Esta rodada é o lado de depois, e as duas saem
preservadas em disco para a comparação.

Uso canônico (no host, como a bateria):

    export OLLAMA_BASE_URL=http://localhost:11434
    python -m harness.run_casos --saida outputs/baseline-1.2.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final

from harness.casos import CASOS
from harness.run import (
    NUM_PREDICT_PADRAO,
    REPETICOES_PADRAO,
    SEED_PADRAO,
    TEMPERATURA_PADRAO,
    ClienteMedido,
    CondicoesDaRodada,
    RecuperacaoDaRodada,
    _checar_pre_requisitos,
    descrever_recuperacao,
    sha256_do_prompt,
)
from sau.config import carregar_configuracao
from sau.graph.graph import construir_grafo
from sau.graph.nodes import OpcoesDoManual, montar_prompt
from sau.inference.ollama import NUM_CTX_PADRAO, Resposta
from sau.rag.retrieve import ultimo_indice

RAIZ_DO_PROJETO: Final = Path(__file__).resolve().parent.parent

SAIDA_OK: Final = 0
SAIDA_SEM_RESPOSTA: Final = 1
SAIDA_PRE_REQUISITO: Final = 3


@dataclass(frozen=True)
class RegistroDeCaso:
    """Uma execução de um Caso: a pergunta, a resposta e o que a sustentou."""

    id: str
    repeticao: int
    pergunta: str
    conforme_quando: str
    nao_conforme_quando: str
    motivo_do_erro: str
    resposta_errada_esperada: str
    resposta_bruta: str | None
    erro: str | None
    motivo_de_parada: str | None
    tokens_gerados: int | None
    primeiro_token_segundos: float | None
    fontes_recuperadas: list[str]
    timestamp: str
    duracao_segundos: float


def executar_casos(
    turno_com_fontes: Any,
    repeticoes: int = REPETICOES_PADRAO,
) -> list[RegistroDeCaso]:
    """Roda cada Caso `repeticoes` vezes e isola a falha por execução.

    A ordem é caso-maior: as repetições do `c1` vêm seguidas, e só então o `c2`.
    Quem lê a rodada compara repetições do mesmo caso lado a lado.
    """
    registros: list[RegistroDeCaso] = []
    for caso in CASOS:
        for repeticao in range(1, repeticoes + 1):
            registros.append(_executar_um_caso(caso, repeticao, turno_com_fontes))
    return registros


def _executar_um_caso(caso: Any, repeticao: int, turno_com_fontes: Any) -> RegistroDeCaso:
    """Roda uma execução de um Caso e devolve o registro dela, com ou sem erro."""
    timestamp = datetime.now(timezone.utc).isoformat()
    inicio = time.perf_counter()
    resposta: Resposta | None = None
    fontes: list[str] = []
    texto: str | None = None
    erro: str | None = None
    try:
        texto, resposta, fontes = turno_com_fontes(caso.pergunta)
    except Exception as exc:
        erro = f"{type(exc).__name__}: {exc}"
    duracao = time.perf_counter() - inicio
    return RegistroDeCaso(
        id=caso.identificador,
        repeticao=repeticao,
        pergunta=caso.pergunta,
        conforme_quando=caso.conforme_quando,
        nao_conforme_quando=caso.nao_conforme_quando,
        motivo_do_erro=caso.motivo_do_erro,
        resposta_errada_esperada=caso.resposta_errada_esperada,
        resposta_bruta=texto if erro is None else None,
        erro=erro,
        motivo_de_parada=resposta.motivo_de_parada if resposta is not None else None,
        tokens_gerados=resposta.tokens_gerados if resposta is not None else None,
        primeiro_token_segundos=(
            resposta.primeiro_token_segundos if resposta is not None else None
        ),
        fontes_recuperadas=list(fontes),
        timestamp=timestamp,
        duracao_segundos=duracao,
    )


def gravar_rodada_de_casos(
    registros: Sequence[RegistroDeCaso],
    condicoes: CondicoesDaRodada,
    destino: Path,
    recuperacao: RecuperacaoDaRodada | None = None,
) -> Path:
    """Grava o JSON da rodada dos Casos: condições, máquina, recuperação e execuções."""
    bloco = recuperacao if recuperacao is not None else descrever_recuperacao(None)
    rodada = {
        "modelo": condicoes.modelo,
        "url": condicoes.url,
        "condicoes": {
            "repeticoes": condicoes.repeticoes,
            "temperatura": condicoes.temperatura,
            "seed": condicoes.seed,
            "num_predict": condicoes.num_predict,
            "num_ctx": condicoes.num_ctx,
            "sha256_do_prompt": condicoes.sha256_do_prompt,
        },
        "recuperacao": asdict(bloco),
        "alocacao": asdict(condicoes.alocacao) if condicoes.alocacao is not None else None,
        "inicio": condicoes.inicio,
        "fim": condicoes.fim,
        "execucoes": [asdict(registro) for registro in registros],
    }
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(rodada, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return destino


def montar_argumentos(argumentos: Sequence[str] | None = None) -> argparse.Namespace:
    analisador = argparse.ArgumentParser(
        description=(
            "Roda os cinco Casos de alucinação no S.A.U. pelo caminho real do turno "
            "e grava a rodada dos Casos com as Fontes recuperadas junto."
        ),
    )
    analisador.add_argument("--modelo", default=None, help="modelo no Ollama")
    analisador.add_argument("--url", default=None, help="endereço do Ollama")
    analisador.add_argument("--timeout", type=float, default=None, help="tempo limite em segundos")
    analisador.add_argument(
        "--repeticoes", type=int, default=REPETICOES_PADRAO, help="execuções por Caso"
    )
    analisador.add_argument(
        "--temperatura", type=float, default=TEMPERATURA_PADRAO, help="temperatura de amostragem"
    )
    analisador.add_argument("--seed", type=int, default=SEED_PADRAO, help="seed da amostragem")
    analisador.add_argument(
        "--num-predict", type=int, default=NUM_PREDICT_PADRAO, help="teto de tokens por geração"
    )
    analisador.add_argument(
        "--saida",
        type=Path,
        default=None,
        help="arquivo JSON da rodada dos Casos (padrão: outputs/casos-<data-hora>.json)",
    )
    return analisador.parse_args(argumentos)


def _nome_padrao_de_saida() -> Path:
    carimbo = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return RAIZ_DO_PROJETO / "outputs" / f"casos-{carimbo}.json"


def main(argumentos: Sequence[str] | None = None) -> int:
    opcoes = montar_argumentos(argumentos)
    if opcoes.repeticoes < 1:
        print(f"\nFALHA: --repeticoes foi {opcoes.repeticoes} e o mínimo é 1.", file=sys.stderr)
        return 2

    configuracao = carregar_configuracao()
    modelo = opcoes.modelo or configuracao.ollama_model
    url = opcoes.url or configuracao.ollama_base_url
    timeout = opcoes.timeout if opcoes.timeout is not None else configuracao.ollama_timeout

    inicio = datetime.now(timezone.utc).isoformat()
    try:
        alocacao = _checar_pre_requisitos(url, modelo, timeout)
    except Exception as exc:
        print(f"\nFALHA: {exc}", file=sys.stderr)
        return SAIDA_PRE_REQUISITO

    cliente = ClienteMedido(
        url,
        modelo,
        timeout=timeout,
        num_ctx=NUM_CTX_PADRAO,
        opcoes={
            "temperature": opcoes.temperatura,
            "seed": opcoes.seed,
            "num_predict": opcoes.num_predict,
        },
    )

    def turno_com_fontes(texto: str) -> tuple[str, Resposta | None, list[str]]:
        # `ultima` é zerada antes porque ela vale por turno: sem o zero, um
        # Encaminhamento determinístico devolveria a geração do turno anterior.
        # O grafo é invocado direto (e não via `executar_turno`) porque a rodada
        # dos Casos precisa das Fontes recuperadas junto da resposta — e
        # `executar_turno` devolve só o texto.
        cliente.ultima = None
        grafo = construir_grafo(cliente, manual=OpcoesDoManual.de_config(configuracao))
        resultado = grafo.invoke(
            {
                "mensagem": texto,
                "historico": [],
                "mensagens": [{"role": "user", "content": montar_prompt(texto)}],
                "rodadas": 0,
            }
        )
        texto_entregue = str(resultado["resposta"])
        fontes = [str(fonte) for fonte in resultado.get("fontes", []) or []]
        if cliente.ultima is None:
            return texto_entregue, Resposta(
                texto=texto_entregue,
                primeiro_token_segundos=0.0,
                carga_segundos=0.0,
                avaliacao_prompt_segundos=0.0,
                segundos_totais=0.0,
                tokens_por_segundo=None,
                tokens_gerados=None,
                concluida=True,
                motivo_de_parada="deterministico",
            ), fontes
        return texto_entregue, cliente.ultima, fontes

    registros = executar_casos(turno_com_fontes, opcoes.repeticoes)
    recuperacao = descrever_recuperacao(ultimo_indice())

    condicoes = CondicoesDaRodada(
        modelo=modelo,
        url=url,
        repeticoes=opcoes.repeticoes,
        temperatura=opcoes.temperatura,
        seed=opcoes.seed,
        num_predict=opcoes.num_predict,
        num_ctx=NUM_CTX_PADRAO,
        sha256_do_prompt=sha256_do_prompt(),
        alocacao=alocacao,
        inicio=inicio,
        fim=datetime.now(timezone.utc).isoformat(),
    )
    destino = opcoes.saida or _nome_padrao_de_saida()
    gravar_rodada_de_casos(registros, condicoes, destino, recuperacao)

    com_resposta = sum(1 for registro in registros if registro.resposta_bruta is not None)
    print(
        f"casos: {len(CASOS)} Casos x {opcoes.repeticoes} repetições "
        f"= {len(registros)} execuções, {com_resposta} com resposta"
    )
    print(f"recuperação: {recuperacao}")
    print(f"JSON bruto gravado em {destino}")

    if com_resposta == 0:
        print("\nFALHA: nenhuma execução produziu resposta.", file=sys.stderr)
        return SAIDA_SEM_RESPOSTA
    return SAIDA_OK


if __name__ == "__main__":
    raise SystemExit(main())
