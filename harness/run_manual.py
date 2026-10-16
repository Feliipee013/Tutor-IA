"""Harness da bateria do Manual: b1–b10 + x1–x5 + n1–n5 no pipeline híbrido (issue #37).

Roda as 20 Perguntas-teste de `perguntas-teste/bateria-manual.md` no S.A.U. pelo
caminho real do turno — o grafo remontado por turno com `OpcoesDoManual` da
configuração (busca híbrida padrão, limiar e k atuais), histórico vazio, como o
`webhook` faz — e grava o output bruto de cada execução com as Fontes
recuperadas junto.

Cada Pergunta-teste roda **3 repetições**, com as mesmas travas da bateria
(`temperature 0`, `seed` 20260926, `num_predict` 512), e as condições vão no
JSON com modelo, alocação, `sha256` do prompt e o bloco do Manual lido do
índice montado (modo de busca, limiar, k, `sha256` do PDF, coleção e total de
chunks). Os blocos `d1`–`d10` ficam no arquivo e fora da rodada, por decisão
da #37.

O julgamento é humano por decisão da #6 (com a emenda do ADR-0006: pode ser
redigido por um agente e o campo `julgador` nomeia quem ratificou): este
script grava e não avalia. A falha ou o timeout de uma execução grava `erro`
no registro e a bateria segue.

Códigos de saída:

- `0` — a bateria rodou e produziu ao menos uma resposta
- `1` — a bateria rodou e **nenhuma** execução produziu resposta
- `2` — o arquivo da bateria não bate com as 20 esperadas
- `3` — o pré-requisito falhou (Ollama fora, modelo ausente, CPU não autorizada)

Uso canônico (no host, como a bateria):

    export OLLAMA_BASE_URL=http://localhost:11434
    python -m harness.run_manual --saida outputs/baseline-manual-hibrido.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final

from harness.run import (
    NUM_PREDICT_PADRAO,
    RE_BLOCO_PERGUNTA,
    RE_CONFORME,
    RE_MARCADOR_PERGUNTA,
    RE_NAO_CONFORME,
    REPETICOES_PADRAO,
    SEED_PADRAO,
    TEMPERATURA_PADRAO,
    ClienteMedido,
    CondicoesDaRodada,
    PerguntaTeste,
    _checar_pre_requisitos,
    sha256_do_prompt,
)
from sau.config import carregar_configuracao
from sau.graph.graph import construir_grafo
from sau.graph.nodes import OpcoesDoManual, montar_mensagens_de_roteamento
from sau.inference.ollama import NUM_CTX_PADRAO, Resposta
from sau.manual.indice import sha256_do_pdf

RAIZ_DO_PROJETO: Final = Path(__file__).resolve().parent.parent
ARQUIVO_BATERIA_MANUAL: Final = RAIZ_DO_PROJETO / "perguntas-teste" / "bateria-manual.md"

ORDEM_MANUAL: Final = (
    "b1",
    "b2",
    "b3",
    "b4",
    "b5",
    "b6",
    "b7",
    "b8",
    "b9",
    "b10",
    "x1",
    "x2",
    "x3",
    "x4",
    "x5",
    "n1",
    "n2",
    "n3",
    "n4",
    "n5",
)
"""As 20 Perguntas-teste da rodada do depois, na ordem dos blocos do arquivo.

São as 10 básicas mais as 5 cruzadas e as 5 fora do manual. Os blocos
`d1`–`d10` existem no arquivo e ficam fora desta rodada, por decisão da #37.
"""

IDS_MANUAL: Final = frozenset(ORDEM_MANUAL)

MODO_BUSCA_MANUAL: Final = "hibrida"
"""O modo de recuperação desta rodada: a busca híbrida é o padrão de produção.

Vem de `sau.manual.tool:buscar_no_manual`, que só chama
`buscar_hibrida_no_indice` — nenhum modo vetorial novo existe em produção.
O campo vai no JSON para que a leitura declare o que rodou, em vez de
depender de o leitor saber o padrão da época.
"""

SAIDA_OK: Final = 0
SAIDA_SEM_RESPOSTA: Final = 1
SAIDA_PERGUNTAS_INVALIDAS: Final = 2
SAIDA_PRE_REQUISITO: Final = 3

RE_FONTE_ESPERADA: Final = re.compile(
    r"^\s*\|\s*fonte esperada\s*\|\s*(?P<valor>.*)\|\s*$",
    re.MULTILINE,
)
RE_TIPO: Final = re.compile(
    r"^\s*\|\s*tipo\s*\|\s*(?P<valor>.*)\|\s*$",
    re.MULTILINE,
)


@dataclass(frozen=True)
class PerguntaDoManual:
    """Uma Pergunta-teste da bateria do Manual, com o tipo e a Fonte esperada.

    O `tipo` é o do bloco (`básica`, `avançada cruzando assuntos` ou `fora do
    manual`) e decide em qual métrica a pergunta conta; a `fonte_esperada` é a
    Fonte citável (título + página) que sustenta a resposta conforme, ou a
    marca de ausência nas `n`.
    """

    id: str
    texto: str
    tipo: str
    fonte_esperada: str
    conforme_quando: str
    nao_conforme_quando: str

    def para_pergunta_teste(self) -> PerguntaTeste:
        """A pergunta no formato que o resto do harness já carrega."""
        return PerguntaTeste(
            id=self.id,
            texto=self.texto,
            conforme_quando=self.conforme_quando,
            nao_conforme_quando=self.nao_conforme_quando,
        )


@dataclass(frozen=True)
class RegistroManual:
    """Uma execução da bateria do Manual: a pergunta, a resposta e o que a sustentou.

    É o mesmo formato do `RegistroDeCaso` do harness dos Casos, com dois
    campos a mais: o `tipo` do bloco (que decide a métrica) e a
    `fonte_esperada` (a régua da citação). As `fontes_recuperadas` são os
    títulos do top-k que o turno guardou — o que o S.A.U. tinha em mãos ao
    responder, e não só o que ele citou.
    """

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
    tokens_gerados: int | None
    primeiro_token_segundos: float | None
    fontes_recuperadas: list[str]
    timestamp: str
    duracao_segundos: float


@dataclass(frozen=True)
class BlocoDoManual:
    """O que a recuperação do Manual realmente usou nesta rodada, lido do índice.

    É o mesmo papel que já cumprem o modelo, a alocação e o `sha256` do
    prompt: separar "o híbrido mudou" de "o índice nem era o mesmo".
    `modo_busca` declara o caminho que a ferramenta usou; `limiar` e
    `k_padrao` são os da configuração no momento da rodada; `pdf_sha256` é o
    `sha256` do arquivo que o índice guarda — o que o próximo boot compara —;
    `ligada` é falsa quando o índice está ausente, vazio ou é de outro PDF.
    """

    ligada: bool
    modo_busca: str
    limiar: float
    k_padrao: int
    pdf_sha256: str | None
    colecao: str
    total_chunks: int
    modelo_embedding: str | None


def carregar_bateria_manual(caminho: Path = ARQUIVO_BATERIA_MANUAL) -> list[PerguntaDoManual]:
    """Lê as 20 Perguntas-teste da bateria do Manual e falha alto se o conjunto mudar.

    O formato é o mesmo da bateria da 1.1: marcador `<!-- pergunta:<id> -->`
    seguido do bloco ```text com o texto que o harness envia ao S.A.U., e o
    comportamento esperado nas linhas da tabela do bloco. Os blocos `d1`–`d10`
    moram no mesmo arquivo e não contam como sobra: eles ficam fora desta
    rodada por decisão da #37, e a bateria continua sendo as 20 filtradas.
    """
    if not caminho.is_file():
        raise ValueError(f"a bateria do Manual não está em {caminho}")

    conteudo = caminho.read_text(encoding="utf-8")
    textos = {m.group("id"): m.group("texto").strip() for m in RE_BLOCO_PERGUNTA.finditer(conteudo)}

    ids_lidos = set(textos)
    faltando = sorted(IDS_MANUAL - ids_lidos)
    if faltando:
        raise ValueError(
            "a bateria do Manual não bate com as 20 esperadas — "
            f"faltando {faltando}, esperadas {sorted(IDS_MANUAL)}"
        )

    perguntas: list[PerguntaDoManual] = []
    for id_pergunta in ORDEM_MANUAL:
        regiao = _regiao_do_bloco(conteudo, id_pergunta)
        perguntas.append(
            PerguntaDoManual(
                id=id_pergunta,
                texto=textos[id_pergunta],
                tipo=_extrair_campo(regiao, RE_TIPO, "tipo", id_pergunta),
                fonte_esperada=_extrair_campo(
                    regiao, RE_FONTE_ESPERADA, "fonte esperada", id_pergunta
                ),
                conforme_quando=_extrair_campo(
                    regiao, RE_CONFORME, "conforme quando", id_pergunta
                ),
                nao_conforme_quando=_extrair_campo(
                    regiao, RE_NAO_CONFORME, "não conforme quando", id_pergunta
                ),
            )
        )
    return perguntas


def _regiao_do_bloco(conteudo: str, id_pergunta: str) -> str:
    """O trecho do markdown do marcador da Pergunta-teste até a próxima pergunta.

    A tabela com o comportamento esperado vem depois do bloco de texto, então
    a região vai até o marcador da próxima Pergunta-teste com id válido (da
    bateria do Manual ou dos blocos `d`, que dividem o arquivo), e não até o
    próximo marcador qualquer.
    """
    marcadores = list(RE_MARCADOR_PERGUNTA.finditer(conteudo))
    inicio = -1
    fim = len(conteudo)
    for indice, marcador in enumerate(marcadores):
        if marcador.group("id") == id_pergunta and inicio == -1:
            inicio = marcador.start()
            for seguinte in marcadores[indice + 1 :]:
                id_seguinte = seguinte.group("id")
                if id_seguinte != id_pergunta and (
                    id_seguinte in IDS_MANUAL or id_seguinte.startswith("d")
                ):
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


def executar_manual(
    perguntas: Sequence[PerguntaDoManual],
    turno_com_fontes: Any,
    repeticoes: int = REPETICOES_PADRAO,
) -> list[RegistroManual]:
    """Roda cada Pergunta-teste `repeticoes` vezes e isola a falha por execução.

    A ordem é pergunta-maior: as repetições da `b1` vêm seguidas, e só então a
    `b2`. `turno_com_fontes` recebe o texto da Pergunta-teste e devolve o
    texto entregue, a `Resposta` do modelo e as Fontes recuperadas no turno.
    Erro ou timeout viram `erro` no registro e a bateria segue.
    """
    registros: list[RegistroManual] = []
    for pergunta in perguntas:
        for repeticao in range(1, repeticoes + 1):
            registros.append(_executar_uma(pergunta, repeticao, turno_com_fontes))
    return registros


def _executar_uma(
    pergunta: PerguntaDoManual,
    repeticao: int,
    turno_com_fontes: Any,
) -> RegistroManual:
    """Roda uma execução e devolve o registro dela, com ou sem erro."""
    timestamp = datetime.now(timezone.utc).isoformat()
    inicio = time.perf_counter()
    resposta: Resposta | None = None
    fontes: list[str] = []
    texto: str | None = None
    erro: str | None = None
    try:
        texto, resposta, fontes = turno_com_fontes(pergunta.texto)
    except Exception as exc:
        # A exceção larga aqui é deliberada, como na bateria: uma pergunta que
        # responde mal é dado, e uma que estoura o tempo limite também.
        erro = f"{type(exc).__name__}: {exc}"
    duracao = time.perf_counter() - inicio
    return RegistroManual(
        id=pergunta.id,
        repeticao=repeticao,
        pergunta=pergunta.texto,
        tipo=pergunta.tipo,
        fonte_esperada=pergunta.fonte_esperada,
        conforme_quando=pergunta.conforme_quando,
        nao_conforme_quando=pergunta.nao_conforme_quando,
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


def descrever_indice_manual(
    diretorio_chroma: Path,
    nome_colecao: str,
    caminho_pdf: Path,
    *,
    limiar: float,
    k_padrao: int,
    modelo_embedding: str,
) -> BlocoDoManual:
    """Lê o bloco do Manual do índice Chroma montado, depois da bateria.

    Índice ausente, vazio ou de outro PDF declara recuperação desligada:
    gravar o que deveria ter acontecido não separaria nada, e um JSON que
    declara o esperado em vez do usado é o buraco que este bloco existe para
    fechar. O `sha256` do PDF vem do arquivo no disco; o guardado no metadado
    da coleção é o que o boot compara — os dois precisam bater.
    """
    try:
        import chromadb
    except ImportError:
        return BlocoDoManual(
            ligada=False,
            modo_busca=MODO_BUSCA_MANUAL,
            limiar=limiar,
            k_padrao=k_padrao,
            pdf_sha256=None,
            colecao=nome_colecao,
            total_chunks=0,
            modelo_embedding=None,
        )
    try:
        if caminho_pdf.is_file():
            sha_do_arquivo: str | None = sha256_do_pdf(caminho_pdf)
        else:
            sha_do_arquivo = None
        banco = chromadb.PersistentClient(path=str(diretorio_chroma))
        if nome_colecao not in {colecao.name for colecao in banco.list_collections()}:
            return BlocoDoManual(
                ligada=False,
                modo_busca=MODO_BUSCA_MANUAL,
                limiar=limiar,
                k_padrao=k_padrao,
                pdf_sha256=sha_do_arquivo,
                colecao=nome_colecao,
                total_chunks=0,
                modelo_embedding=None,
            )
        colecao = banco.get_collection(nome_colecao)
        total = colecao.count()
        metadados = colecao.metadata or {}
        sha_guardado = metadados.get("pdf_sha256")
        ligada = (
            total > 0
            and sha_do_arquivo is not None
            and sha_guardado is not None
            and str(sha_guardado) == sha_do_arquivo
        )
        return BlocoDoManual(
            ligada=ligada,
            modo_busca=MODO_BUSCA_MANUAL,
            limiar=limiar,
            k_padrao=k_padrao,
            pdf_sha256=sha_do_arquivo,
            colecao=nome_colecao,
            total_chunks=total,
            modelo_embedding=modelo_embedding if ligada else None,
        )
    except Exception:
        # Índice que não abre vira ausência de evidência, como no turno: o
        # Aluno receberia o Encaminhamento, e a rodada declara que a
        # recuperação não estava ligada em vez de abortar a bateria.
        return BlocoDoManual(
            ligada=False,
            modo_busca=MODO_BUSCA_MANUAL,
            limiar=limiar,
            k_padrao=k_padrao,
            pdf_sha256=None,
            colecao=nome_colecao,
            total_chunks=0,
            modelo_embedding=None,
        )


def gravar_rodada_manual(
    registros: Sequence[RegistroManual],
    condicoes: CondicoesDaRodada,
    destino: Path,
    bloco_manual: BlocoDoManual,
) -> Path:
    """Grava o JSON da rodada do Manual: condições, bloco do índice e execuções.

    `condicoes` vem antes dos registros porque é ele que dá sentido aos
    registros; o `manual` declara o que a recuperação realmente usou — lido do
    índice montado, depois da bateria. A `recuperacao` repete o trio que as
    linhas de base antigas já trazem, para a comparação não precisar aprender
    um formato novo para ler se o índice estava ligado.
    """
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
        "manual": asdict(bloco_manual),
        "recuperacao": {
            "ligada": bloco_manual.ligada,
            "secoes_indexadas": bloco_manual.total_chunks,
            "modelo_embedding": bloco_manual.modelo_embedding,
        },
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
            "Roda as 20 Perguntas-teste da bateria do Manual no S.A.U. pelo caminho "
            "real do turno (híbrido padrão) e grava os outputs brutos com as Fontes "
            "recuperadas junto. O julgamento de conforme/não-conforme é humano: "
            "este script grava, não avalia."
        ),
        epilog=(
            "O harness roda no HOST, não no container: exporte OLLAMA_BASE_URL antes "
            "de rodar (ver SETUP.md). Saídas: 0 rodou e respondeu, 1 rodou sem "
            "nenhuma resposta, 2 Perguntas-teste inválidas, 3 pré-requisito falhou."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    analisador.add_argument("--modelo", default=None, help="modelo no Ollama")
    analisador.add_argument("--url", default=None, help="endereço do Ollama")
    analisador.add_argument(
        "--timeout", type=float, default=None, help="tempo limite da geração em segundos"
    )
    analisador.add_argument(
        "--repeticoes", type=int, default=REPETICOES_PADRAO, help="execuções por Pergunta-teste"
    )
    analisador.add_argument(
        "--temperatura", type=float, default=TEMPERATURA_PADRAO, help="temperatura de amostragem"
    )
    analisador.add_argument("--seed", type=int, default=SEED_PADRAO, help="seed da amostragem")
    analisador.add_argument(
        "--num-predict", type=int, default=NUM_PREDICT_PADRAO, help="teto de tokens por geração"
    )
    analisador.add_argument(
        "--perguntas",
        type=Path,
        default=ARQUIVO_BATERIA_MANUAL,
        help=f"arquivo da bateria do Manual (padrão: {ARQUIVO_BATERIA_MANUAL})",
    )
    analisador.add_argument(
        "--saida",
        type=Path,
        default=None,
        help="arquivo JSON da rodada (padrão: outputs/manual-<data-hora>.json)",
    )
    return analisador.parse_args(argumentos)


def _nome_padrao_de_saida() -> Path:
    carimbo = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return RAIZ_DO_PROJETO / "outputs" / f"manual-{carimbo}.json"


def main(argumentos: Sequence[str] | None = None) -> int:
    opcoes = montar_argumentos(argumentos)
    if opcoes.repeticoes < 1:
        print(
            f"\nFALHA: --repeticoes foi {opcoes.repeticoes} e o mínimo é 1. "
            "Uma execução só não é evidência de comportamento (ADR-0003).",
            file=sys.stderr,
        )
        return SAIDA_PERGUNTAS_INVALIDAS

    try:
        perguntas = carregar_bateria_manual(opcoes.perguntas)
    except ValueError as exc:
        print(f"\nFALHA: {exc}", file=sys.stderr)
        return SAIDA_PERGUNTAS_INVALIDAS

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
    manual = OpcoesDoManual.de_config(configuracao)

    def turno_com_fontes(texto: str) -> tuple[str, Resposta | None, list[str]]:
        # `ultima` é zerada antes porque ela vale por turno: sem o zero, um
        # Encaminhamento determinístico devolveria a geração do turno anterior.
        # O grafo é invocado direto (e não via `executar_turno`) porque a
        # rodada precisa das Fontes recuperadas junto da resposta — e
        # `executar_turno` devolve só o texto. A entrada é a mesma que ele
        # montaria: o turno abre pelo roteador, com histórico vazio.
        cliente.ultima = None
        grafo = construir_grafo(cliente, manual=manual)
        resultado = grafo.invoke(
            {
                "mensagem": texto,
                "historico": [],
                "mensagens": montar_mensagens_de_roteamento(texto),
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
                chamadas=(),
            ), fontes
        return texto_entregue, cliente.ultima, fontes

    registros = executar_manual(perguntas, turno_com_fontes, opcoes.repeticoes)
    bloco_manual = descrever_indice_manual(
        Path(configuracao.manual_chroma_caminho),
        configuracao.manual_colecao,
        Path(configuracao.manual_pdf_caminho),
        limiar=configuracao.manual_limiar_similaridade,
        k_padrao=configuracao.manual_k_padrao,
        modelo_embedding=cliente.modelo_embedding,
    )

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
    gravar_rodada_manual(registros, condicoes, destino, bloco_manual)

    com_resposta = sum(1 for registro in registros if registro.resposta_bruta is not None)
    falhas = len(registros) - com_resposta
    cortadas = sum(1 for registro in registros if registro.motivo_de_parada == "length")
    print(
        f"manual: {len(perguntas)} Perguntas-teste x {opcoes.repeticoes} repetições "
        f"= {len(registros)} execuções, {com_resposta} com resposta, {falhas} com erro"
    )
    print(f"índice: {bloco_manual}")
    if cortadas:
        print(
            f"ATENÇÃO: {cortadas} execuções pararam por falta de espaço e saíram "
            "cortadas. Resposta cortada parece não-conformidade: confira o motivo "
            "de parada antes de julgar a rodada."
        )
    print(f"JSON bruto gravado em {destino}")

    if com_resposta == 0:
        print(
            "\nFALHA: nenhuma execução produziu resposta. O arquivo foi gravado, "
            "mas ele não é evidência de nada — confira o `erro` do primeiro caso.",
            file=sys.stderr,
        )
        return SAIDA_SEM_RESPOSTA
    return SAIDA_OK


if __name__ == "__main__":
    raise SystemExit(main())
