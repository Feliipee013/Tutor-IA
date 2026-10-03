"""Harness das Perguntas-teste do S.A.U.

Envia as 10 Perguntas-teste ao S.A.U. pelo caminho real do turno
(`sau.config` + `ClienteOllama` + `sau.graph.graph.executar_turno`, com
histórico vazio, como o `webhook` faz) e a cadeia especial s1–s5 em sequência
com histórico acumulado, e grava o output bruto de cada execução, com o
comportamento esperado lado a lado.

Cada Pergunta-teste roda **3 repetições**, e não uma. O ADR-0003 mediu que das
12 perguntas da sondagem só 4 tiveram as 3 repetições idênticas na máquina de
CPU e 7 na do ADR-0002, e que o telefone inventado pelo `qwen2.5:3b` apareceu
em 2 de 3 repetições numa e em 0 de 3 na outra: quem mede uma vez só registra
uma das duas respostas e conclui o oposto do que o modelo faz. O ADR-0003
nomeia este harness e proíbe a execução única.

As condições da medição são travadas e **gravadas na rodada**: `temperatura 0`,
`seed` 20260926 e `num_predict` 256, as mesmas do ADR-0003, mais o `num_ctx`
realmente enviado e o `sha256` do prompt versionado. Linha de base que não
declara as condições não é comparável com nada — por isso elas vão dentro do
JSON e não numa nota de rodapé.

A máquina também vai no JSON. O ADR-0003 exige que toda afirmação qualitativa
diga de qual máquina veio, e `sau.prereqs.executar_checagens` já leu `/api/ps`
para decidir se o modelo está na GPU: essa leitura ia dispensada, e aqui ela
vira o campo `alocacao`. Uma rodada medida em CPU fica visivelmente uma
rodada em CPU, que é o defeito que o ADR-0002 existe para não deixar passar.

O julgamento é humano por decisão da #6: este script grava e não avalia. A
falha ou o timeout de uma execução grava `erro` no registro e a bateria segue.

Códigos de saída:

- `0` — a bateria rodou e produziu ao menos uma resposta (na bateria ou na cadeia)
- `1` — a bateria rodou e **nenhuma** execução produziu resposta
- `2` — o arquivo das Perguntas-teste não bate com as 10 esperadas mais a cadeia s1–s5
- `3` — o pré-requisito falhou (Ollama fora, modelo ausente, CPU não autorizada)

Uso canônico:

    export OLLAMA_BASE_URL=http://localhost:11434   # o harness roda no host
    python -m harness.run
    python -m harness.run --saida outputs/baseline-1.1.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final

import httpx

from sau.config import carregar_configuracao
from sau.graph.graph import executar_turno
from sau.graph.state import Mensagem
from sau.inference.ollama import (
    NUM_CTX_PADRAO,
    TIMEOUT_PADRAO,
    ClienteOllama,
    ErroDeInferencia,
    Resposta,
)
from sau.persona import PERSONA
from sau.prereqs import PreRequisitoError, executar_checagens, modelo_servido_em_cpu
from sau.rag.retrieve import Indice, ultimo_indice

RAIZ_DO_PROJETO: Final = Path(__file__).resolve().parent.parent
ARQUIVO_PERGUNTAS_PADRAO: Final = RAIZ_DO_PROJETO / "perguntas-teste" / "perguntas-teste.md"
PASTA_SAIDAS_PADRAO: Final = RAIZ_DO_PROJETO / "outputs"

ORDEM_DA_BATERIA: Final = ("a1", "a2", "a3", "f1", "f2", "f3", "p1", "p2", "p3", "p4")
IDS_ESPERADOS: Final = frozenset(ORDEM_DA_BATERIA)

ORDEM_DA_CADEIA: Final = ("s1", "s2", "s3", "s4", "s5")
"""A cadeia especial de Petrolina, na ordem em que o Aluno a disse.

É um caso especial encadeado, e não parte da bateria: as 10 Perguntas-teste
rodam isoladas com histórico vazio, e estes 5 passos rodam em sequência com
histórico acumulado, 3 repetições da cadeia inteira.
"""

IDS_DA_CADEIA: Final = frozenset(ORDEM_DA_CADEIA)
IDS_TODOS: Final = IDS_ESPERADOS | IDS_DA_CADEIA

REPETICOES_PADRAO: Final = 3
"""Quantas vezes cada Pergunta-teste roda.

O número é o do ADR-0003, e ele não é um detalhe de configuração: sem repetição
a taxa da #13 sai de uma amostra só, e o ADR já mostrou que uma amostra só
registra uma das respostas possíveis. Por isso a flag existe mas o padrão é
este — mudar o número muda o que a rodada pode provar, e o JSON registra o
que foi usado.
"""

TEMPERATURA_PADRAO: Final = 0.0
SEED_PADRAO: Final = 20260926
NUM_PREDICT_PADRAO: Final = 256
"""As três condições que o ADR-0003 travou na medição do modelo.

São valores de arquivo, não preferences de execução: a flag existe porque a
varredura de temperatura do P7 da 1.2 precisa mexer nelas, e o padrão é o do
ADR porque é o que torna a linha de base comparável com
`docs/medicao-modelo/resultado-gpu.md`.
"""

SAIDA_OK: Final = 0
SAIDA_SEM_RESPOSTA: Final = 1
SAIDA_PERGUNTAS_INVALIDAS: Final = 2
SAIDA_PRE_REQUISITO: Final = 3

RE_BLOCO_PERGUNTA: Final = re.compile(
    r"<!--\s*pergunta:(?P<id>[a-z0-9_-]+)\s*-->\s*```text\n(?P<texto>.*?)```",
    re.DOTALL,
)
RE_MARCADOR_PERGUNTA: Final = re.compile(r"<!--\s*pergunta:(?P<id>[a-z0-9_-]+)\s*-->")
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
class AlocacaoDoModelo:
    """Onde o modelo estava rodando quando a rodada saiu.

    Vem do `/api/ps` que `sau.prereqs.executar_checagens` já leu para decidir
    se a checagem passa. `size_vram` zerado é a queda silenciosa para CPU do
    ADR-0002, e `em_cpu` é o mesmo veredito que o serviço do bot aplica — o
    campo entra na rodada para que a leitura que ia ser descartada vire
    evidência, e para que uma rodada de CPU não possa ser lida como se fosse
    de GPU.
    """

    size: int
    size_vram: int | None
    em_cpu: bool


@dataclass(frozen=True)
class CondicoesDaRodada:
    """As condições que produziram uma rodada inteira, declaradas de uma vez.

    Tudo o que separa uma rodada da outra mora aqui: o modelo, o endereço, as
    três travas de amostragem, a janela de contexto, o hash do prompt e a
    máquina. Uma rodada sem este bloco é um arquivo de texto com respostas
    soltas, e a diferença entre o "antes" e o "depois" da 1.2 deixa de ter
    causa — que é a única coisa que a comparação precisa dizer.
    """

    modelo: str
    url: str
    repeticoes: int
    temperatura: float
    seed: int
    num_predict: int
    num_ctx: int
    sha256_do_prompt: str
    alocacao: AlocacaoDoModelo | None
    inicio: str
    fim: str


@dataclass(frozen=True)
class RegistroDaExecucao:
    """Uma execução: uma Pergunta-teste, uma vez.

    `resposta_bruta` é o output bruto do S.A.U., character a character. Quando
    o turno falha, ela é `None` e o motivo vai em `erro`: a bateria nunca
    aborta por causa de uma execução.

    `motivo_de_parada`, `tokens_gerados` e `primeiro_token_segundos` vêm da
    `Resposta` do modelo e existem por um motivo prático: o Ollama trata o
    fim da geração por falta de espaço como sucesso, então uma resposta
    cortada sai com cara de resposta e parece não-conformidade. Sem estes três
    campos, uma rodada não distingue "o S.A.U. errou" de "a geração foi
    cortada no meio da frase".
    """

    id: str
    repeticao: int
    pergunta: str
    conforme_quando: str
    nao_conforme_quando: str
    resposta_bruta: str | None
    erro: str | None
    motivo_de_parada: str | None
    tokens_gerados: int | None
    primeiro_token_segundos: float | None
    timestamp: str
    duracao_segundos: float


@dataclass(frozen=True)
class RegistroDoPassoDaCadeia:
    """Um passo da cadeia especial: uma Pergunta-teste encadeada, uma vez.

    É o mesmo formato do `RegistroDaExecucao`, com um campo a mais:
    `historico_usado` guarda o histórico que o turno recebeu neste passo, como
    tupla de `Mensagem` do Aluno e do S.A.U. O primeiro passo usa histórico
    vazio; cada passo seguinte usa o acumulado dos passos anteriores da mesma
    repetição. Quando o passo falha, só a fala do Aluno entra no acumulado — o
    S.A.U. não respondeu, e o passo seguinte precisa ver a pergunta mesmo assim.
    A falha de um passo nunca aborta a cadeia.
    """

    id: str
    repeticao: int
    pergunta: str
    conforme_quando: str
    nao_conforme_quando: str
    resposta_bruta: str | None
    erro: str | None
    motivo_de_parada: str | None
    tokens_gerados: int | None
    primeiro_token_segundos: float | None
    historico_usado: tuple[Mensagem, ...]
    timestamp: str
    duracao_segundos: float


@dataclass(frozen=True)
class RecuperacaoDaRodada:
    """O que a recuperação realmente usou nesta rodada, lido do índice montado.

    É o mesmo papel que já cumprem o modelo, a alocação e o `sha256` do
    prompt: separar "o RAG mudou" de "o RAG nem estava ligado". `ligada` é
    falsa quando o índice nunca foi montado — a verdade, e é o que dá valor
    ao campo —, e `modelo_embedding` é `None` nesse caso pelo mesmo motivo.
    """

    ligada: bool
    secoes_indexadas: int
    modelo_embedding: str | None


def descrever_recuperacao(indice: Indice | None) -> RecuperacaoDaRodada:
    """Lê o bloco de recuperação do índice que o nó guardou, depois da bateria.

    Índice vazio — ou nunca montado — declara recuperação desligada: gravar o
    que deveria ter acontecido não separaria nada, e um JSON que declara o
    esperado em vez do usado é o buraco que este bloco existe para fechar.
    """
    if indice is None or not indice.secoes:
        return RecuperacaoDaRodada(ligada=False, secoes_indexadas=0, modelo_embedding=None)
    return RecuperacaoDaRodada(
        ligada=True,
        secoes_indexadas=len(indice.secoes),
        modelo_embedding=indice.modelo_embedding,
    )


class ClienteMedido(ClienteOllama):
    """O cliente do Ollama com as travas da medição aplicadas, e que guarda a `Resposta`.

    Existe para que o harness não tenha de passar `opcoes` por um caminho que
    não é seu: `sau.graph.graph.executar_turno` não tem por onde recebe-las, e
    mexer nele significaria levar mudança de medição para dentro do caminho
    quente do Telegram. `sau/inference/ollama.py` diz que quem mede passa as
    condições em `opcoes`, e esta classe é o "quem mede" do harness.

    `ultima` é a `Resposta` da última geração. Com o grafo de um caminho só,
    cada execução gera exatamente uma — a do `responder` — porque a recuperação
    não gera, só embute. A exceção é o Encaminhamento determinístico: sem
    material recuperado o turno encerra sem chamar o modelo, e `ultima` segue
    valendo a geração anterior. É o ponto que o ADR-0008 marcou para rever
    "quando a 1.2 somar nós que também geram", revisto aqui.
    """

    def __init__(
        self,
        base_url: str,
        modelo: str,
        *,
        opcoes: dict[str, Any],
        timeout: float = TIMEOUT_PADRAO,
        num_ctx: int = NUM_CTX_PADRAO,
        client: httpx.Client | None = None,
    ) -> None:
        super().__init__(base_url, modelo, timeout=timeout, num_ctx=num_ctx, client=client)
        self._opcoes_medidas = dict(opcoes)
        self.ultima: Resposta | None = None

    def responder(self, prompt: str, *, opcoes: dict[str, Any] | None = None) -> Resposta:
        combinadas = {**self._opcoes_medidas, **(opcoes or {})}
        resposta = super().responder(prompt, opcoes=combinadas)
        self.ultima = resposta
        return resposta


def carregar_perguntas_teste(caminho: Path = ARQUIVO_PERGUNTAS_PADRAO) -> list[PerguntaTeste]:
    """Lê as 10 Perguntas-teste do markdown e falha alto se o conjunto mudar.

    O formato é o que `docs/medicao-modelo/medir.py` já lê na sondagem:
    marcador `<!-- pergunta:<id> -->` seguido do bloco ```text com o texto
    que o harness envia ao S.A.U. O comportamento esperado sai das linhas
    `conforme quando` / `não conforme quando` do bloco de cada Pergunta-teste.

    A cadeia especial s1–s5 mora no mesmo arquivo e não conta como sobra: ela
    é lida por `carregar_cadeia`, e a bateria continua sendo as 10 isoladas.
    """
    if not caminho.is_file():
        raise ValueError(f"as Perguntas-teste não estão em {caminho}")

    conteudo = caminho.read_text(encoding="utf-8")
    textos = {m.group("id"): m.group("texto").strip() for m in RE_BLOCO_PERGUNTA.finditer(conteudo)}

    ids_lidos = set(textos)
    faltando = sorted(IDS_ESPERADOS - ids_lidos)
    sobrando = sorted(ids_lidos - IDS_TODOS)
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


def carregar_cadeia(caminho: Path = ARQUIVO_PERGUNTAS_PADRAO) -> list[PerguntaTeste]:
    """Lê a cadeia especial s1–s5 do mesmo markdown, na ordem da conversa.

    Cada passo tem o mesmo formato da bateria — marcador, bloco ```text e as
    linhas `conforme quando` / `não conforme quando` — e a ordem é a da
    conversa (s1→s5). A cadeia roda com histórico acumulado, e não isolada.
    """
    if not caminho.is_file():
        raise ValueError(f"as Perguntas-teste não estão em {caminho}")

    conteudo = caminho.read_text(encoding="utf-8")
    textos = {m.group("id"): m.group("texto").strip() for m in RE_BLOCO_PERGUNTA.finditer(conteudo)}

    ids_lidos = set(textos)
    faltando = sorted(IDS_DA_CADEIA - ids_lidos)
    if faltando:
        raise ValueError(
            "a cadeia do arquivo não bate com os 5 passos esperados — "
            f"faltando {faltando}, esperados {sorted(IDS_DA_CADEIA)}"
        )

    passos: list[PerguntaTeste] = []
    for id_passo in ORDEM_DA_CADEIA:
        regiao = _regiao_do_bloco(conteudo, id_passo)
        conforme = _extrair_campo(regiao, RE_CONFORME, "conforme quando", id_passo)
        nao_conforme = _extrair_campo(regiao, RE_NAO_CONFORME, "não conforme quando", id_passo)
        passos.append(
            PerguntaTeste(
                id=id_passo,
                texto=textos[id_passo],
                conforme_quando=conforme,
                nao_conforme_quando=nao_conforme,
            )
        )
    return passos


def _regiao_do_bloco(conteudo: str, id_pergunta: str) -> str:
    """O trecho do markdown do marcador da Pergunta-teste até a próxima Pergunta-teste.

    O bloco de texto termina em `<!-- pergunta:fim -->`, e a tabela com o
    `conforme quando` vem depois dele: cortar no `fim` deixaria o
    comportamento esperado fora da região. Por isso a região vai até o
    marcador da próxima Pergunta-teste com id válido (da bateria ou da
    cadeia), e não até o próximo marcador qualquer.
    """
    marcadores = list(RE_MARCADOR_PERGUNTA.finditer(conteudo))
    inicio = -1
    fim = len(conteudo)
    for indice, marcador in enumerate(marcadores):
        if marcador.group("id") == id_pergunta and inicio == -1:
            inicio = marcador.start()
            for seguinte in marcadores[indice + 1 :]:
                id_seguinte = seguinte.group("id")
                if id_seguinte in IDS_TODOS and id_seguinte != id_pergunta:
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
    turno: Callable[[str], Resposta],
    repeticoes: int = REPETICOES_PADRAO,
) -> list[RegistroDaExecucao]:
    """Roda cada Pergunta-teste `repeticoes` vezes e isola a falha por execução.

    A ordem é pergunta-maior: as repetições da `a1` vêm seguidas, e só então a
    `a2`. Quem lê a rodada compara repetições de uma mesma pergunta lado a
    lado, e a ordem que as separa facilitava a leitura e atrapalhava.

    `turno` recebe o texto da Pergunta-teste e devolve a `Resposta` do modelo.
    Erro ou timeout viram `erro` no registro e a bateria segue para a próxima
    execução — uma pergunta que responde mal é dado, e uma que estoura o
    tempo limite também.
    """
    registros: list[RegistroDaExecucao] = []
    for pergunta in perguntas:
        for repeticao in range(1, repeticoes + 1):
            registros.append(_executar_uma(pergunta, repeticao, turno))
    return registros


def _executar_uma(
    pergunta: PerguntaTeste,
    repeticao: int,
    turno: Callable[[str], Resposta],
) -> RegistroDaExecucao:
    """Roda uma execução e devolve o registro dela, com ou sem erro."""
    timestamp = datetime.now(timezone.utc).isoformat()
    inicio = time.perf_counter()
    resposta: Resposta | None = None
    erro: str | None = None
    try:
        resposta = turno(pergunta.texto)
    except Exception as exc:
        # A exceção larga aqui é deliberada: a bateria não pode abortar por causa
        # de uma execução (critério de aceitação da #12), e o tipo do erro entra
        # inteiro no registro para que a causa seja legível depois.
        erro = f"{type(exc).__name__}: {exc}"
    duracao = time.perf_counter() - inicio
    return RegistroDaExecucao(
        id=pergunta.id,
        repeticao=repeticao,
        pergunta=pergunta.texto,
        conforme_quando=pergunta.conforme_quando,
        nao_conforme_quando=pergunta.nao_conforme_quando,
        resposta_bruta=resposta.texto if resposta is not None else None,
        erro=erro,
        motivo_de_parada=resposta.motivo_de_parada if resposta is not None else None,
        tokens_gerados=resposta.tokens_gerados if resposta is not None else None,
        primeiro_token_segundos=(
            resposta.primeiro_token_segundos if resposta is not None else None
        ),
        timestamp=timestamp,
        duracao_segundos=duracao,
    )


def executar_cadeia(
    passos: Sequence[PerguntaTeste],
    turno_com_historico: Callable[[str, Sequence[Mensagem]], Resposta],
    repeticoes: int = REPETICOES_PADRAO,
) -> list[RegistroDoPassoDaCadeia]:
    """Roda a cadeia s1→s5 `repeticoes` vezes, com histórico acumulado.

    Cada repetição é uma conversa nova: o histórico começa vazio em s1 e cresce
    passo a passo, na ordem da cadeia. `turno_com_historico` recebe o texto do
    passo e o histórico até ali, e devolve a `Resposta` do modelo. Erro ou
    timeout viram `erro` no registro e a cadeia segue para o passo seguinte —
    a falha de um passo nunca aborta a repetição.
    """
    registros: list[RegistroDoPassoDaCadeia] = []
    for repeticao in range(1, repeticoes + 1):
        historico: list[Mensagem] = []
        for passo in passos:
            registros.append(_executar_passo(passo, repeticao, historico, turno_com_historico))
            ultimo = registros[-1]
            agora = time.time()
            historico.append(Mensagem(papel="aluno", texto=passo.texto, em=agora))
            if ultimo.resposta_bruta is not None:
                historico.append(Mensagem(papel="sau", texto=ultimo.resposta_bruta, em=agora))
    return registros


def _executar_passo(
    passo: PerguntaTeste,
    repeticao: int,
    historico: Sequence[Mensagem],
    turno_com_historico: Callable[[str, Sequence[Mensagem]], Resposta],
) -> RegistroDoPassoDaCadeia:
    """Roda um passo da cadeia com o histórico acumulado até ele."""
    usado = tuple(historico)
    timestamp = datetime.now(timezone.utc).isoformat()
    inicio = time.perf_counter()
    resposta: Resposta | None = None
    erro: str | None = None
    try:
        resposta = turno_com_historico(passo.texto, usado)
    except Exception as exc:
        # A exceção larga aqui é deliberada, como na bateria: um passo que
        # falha é dado, e a cadeia segue para o passo seguinte.
        erro = f"{type(exc).__name__}: {exc}"
    duracao = time.perf_counter() - inicio
    return RegistroDoPassoDaCadeia(
        id=passo.id,
        repeticao=repeticao,
        pergunta=passo.texto,
        conforme_quando=passo.conforme_quando,
        nao_conforme_quando=passo.nao_conforme_quando,
        resposta_bruta=resposta.texto if resposta is not None else None,
        erro=erro,
        motivo_de_parada=resposta.motivo_de_parada if resposta is not None else None,
        tokens_gerados=resposta.tokens_gerados if resposta is not None else None,
        primeiro_token_segundos=(
            resposta.primeiro_token_segundos if resposta is not None else None
        ),
        historico_usado=usado,
        timestamp=timestamp,
        duracao_segundos=duracao,
    )


def sha256_do_prompt() -> str:
    """O `sha256` do prompt versionado, para amarrar a rodada a um estado do código.

    A persona é versionada em `sau/persona.py` no sentido de que mora no
    arquivo — não tem número de versão. Duas rodadas com o mesmo modelo, a
    mesma seed e a mesma máquina podem ter prompts diferentes se alguém
    editou a persona entre elas, e aí a comparação da 1.2 mede duas coisas ao
    mesmo tempo. O hash é o que separa "o RAG mudou" de "a persona mudou".
    """
    return hashlib.sha256(PERSONA.encode("utf-8")).hexdigest()


def descrever_alocacao(item_ps: dict[str, Any]) -> AlocacaoDoModelo:
    """Lê a alocação do modelo no `/api/ps` que a checagem de pré-requisito já fez.

    O item é o mesmo que `executar_checagens` devolve, e o veredito de CPU é o
    mesmo que `sau.prereqs.modelo_servido_em_cpu` aplica: quem decide se a
    checagem passa e quem escreve na rodada precisam responder a mesma
    pergunta, com a mesma resposta.
    """
    size_vram_bruto = item_ps.get("size_vram")
    return AlocacaoDoModelo(
        size=int(item_ps.get("size", 0)),
        size_vram=int(size_vram_bruto) if size_vram_bruto is not None else None,
        em_cpu=modelo_servido_em_cpu(item_ps),
    )


def gravar_rodada(
    registros: Sequence[RegistroDaExecucao],
    condicoes: CondicoesDaRodada,
    destino: Path,
    cadeia: Sequence[RegistroDoPassoDaCadeia] = (),
    recuperacao: RecuperacaoDaRodada | None = None,
) -> Path:
    """Grava o JSON de uma rodada: as condições, a máquina, as execuções e a cadeia.

    `condicoes` vem antes dos registros porque é ele que dá sentido aos
    registros: os números só se comparam com os mesmos números. A `cadeia` vai
    em bloco separado porque roda com histórico acumulado, e não isolada como
    a bateria. A `recuperacao` declara o que a recuperação realmente usou —
    lida do índice montado, depois da bateria — e ausente declara desligada,
    que é a verdade quando o grafo nunca rodou.
    """
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
        "cadeia": [asdict(passo) for passo in cadeia],
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
        epilog=(
            "O harness roda no HOST, não no container: o padrão de OLLAMA_BASE_URL "
            "aponta para o container. Exporte a URL do host antes de rodar (ver SETUP.md). "
            "Saídas: 0 rodou e respondeu, 1 rodou sem nenhuma resposta, 2 "
            "Perguntas-teste inválidas, 3 pré-requisito falhou."
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
        "--repeticoes",
        type=int,
        default=REPETICOES_PADRAO,
        help=f"execuções por Pergunta-teste (padrão: {REPETICOES_PADRAO}, o do ADR-0003)",
    )
    analisador.add_argument(
        "--temperatura",
        type=float,
        default=TEMPERATURA_PADRAO,
        help=f"temperatura de amostragem (padrão: {TEMPERATURA_PADRAO}, o do ADR-0003)",
    )
    analisador.add_argument(
        "--seed",
        type=int,
        default=SEED_PADRAO,
        help=f"seed da amostragem (padrão: {SEED_PADRAO}, o do ADR-0003)",
    )
    analisador.add_argument(
        "--num-predict",
        type=int,
        default=NUM_PREDICT_PADRAO,
        help=f"teto de tokens por geração (padrão: {NUM_PREDICT_PADRAO}, o do ADR-0003)",
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


def _checar_pre_requisitos(url: str, modelo: str, timeout: float) -> AlocacaoDoModelo:
    """Roda a checagem do ADR-0002 antes da bateria e devolve a alocação lida.

    Ela falha alto em Ollama fora do ar, modelo ausente e CPU não autorizada,
    e é por isso que roda **antes**: um Ollama desligado produziria dez
    execuções com `erro` e um JSON de aparência válida, que é o tipo de
    arquivo que outra pessoa lê depois como evidência. A falha do pré-requisito
    é do instrumento, não de uma Pergunta-teste, e por isso ela não vira `erro`
    dentro de um caso.

    As checagem recebem a configuração já com `--url`, `--modelo` e `--timeout`
    aplicados, para validarem o alvo que a bateria vai usar de fato e não o que
    o ambiente declarar.
    """
    configuracao = replace(
        carregar_configuracao(),
        ollama_base_url=url,
        ollama_model=modelo,
        ollama_timeout=timeout,
    )
    return descrever_alocacao(executar_checagens(configuracao))


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
        perguntas = carregar_perguntas_teste(opcoes.perguntas)
        cadeia_passos = carregar_cadeia(opcoes.perguntas)
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
    except PreRequisitoError as exc:
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

    def turno(texto: str) -> Resposta:
        # `executar_turno` devolve o texto e o `ClienteMedido` guarda a
        # `Resposta` que produziu esse texto. O texto não é usado aqui: quem
        # interessa à rodada é a `Resposta` inteira, com o motivo de parada e os
        # tempos, e é ela que vai para o registro.
        executar_turno(cliente, texto, ())
        if cliente.ultima is None:
            raise ErroDeInferencia(
                "FALHA CRÍTICA: o turno rodou e não deixou registro de geração. "
                "O grafo deixou de chamar o cliente, e um turno sem geração não "
                "produz resposta nenhuma."
            )
        return cliente.ultima

    def turno_com_historico(texto: str, historico: Sequence[Mensagem]) -> Resposta:
        # O mesmo caminho do turno isolado, mas com o histórico acumulado da
        # cadeia: é assim que o `webhook` chama em produção, e é o que prova
        # que o S.A.U. retoma o dado em vez de repedir a pergunta.
        executar_turno(cliente, texto, historico)
        if cliente.ultima is None:
            raise ErroDeInferencia(
                "FALHA CRÍTICA: o turno rodou e não deixou registro de geração. "
                "O grafo deixou de chamar o cliente, e um turno sem geração não "
                "produz resposta nenhuma."
            )
        return cliente.ultima

    registros = executar_bateria(perguntas, turno, opcoes.repeticoes)
    registros_da_cadeia = executar_cadeia(cadeia_passos, turno_com_historico, opcoes.repeticoes)
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
    gravar_rodada(registros, condicoes, destino, registros_da_cadeia, recuperacao)

    com_resposta = sum(1 for registro in registros if registro.resposta_bruta is not None)
    com_resposta_cadeia = sum(
        1 for passo in registros_da_cadeia if passo.resposta_bruta is not None
    )
    falhas = len(registros) - com_resposta
    falhas_cadeia = len(registros_da_cadeia) - com_resposta_cadeia
    cortadas = sum(1 for registro in registros if registro.motivo_de_parada == "length")
    cortadas += sum(1 for passo in registros_da_cadeia if passo.motivo_de_parada == "length")
    print(
        f"bateria: {len(perguntas)} Perguntas-teste x {opcoes.repeticoes} repetições "
        f"= {len(registros)} execuções, {com_resposta} com resposta, {falhas} com erro"
    )
    print(
        f"cadeia: {len(cadeia_passos)} passos x {opcoes.repeticoes} repetições "
        f"= {len(registros_da_cadeia)} execuções, {com_resposta_cadeia} com resposta, "
        f"{falhas_cadeia} com erro"
    )
    if cortadas:
        print(
            f"ATENÇÃO: {cortadas} execuções pararam por falta de espaço e saíram "
            "cortadas. Resposta cortada parece não-conformidade: confira o motivo "
            "de parada antes de julgar a rodada."
        )
    print(f"JSON bruto gravado em {destino}")

    if com_resposta + com_resposta_cadeia == 0:
        print(
            "\nFALHA: nenhuma execução produziu resposta. O arquivo foi gravado, "
            "mas ele não é evidência de nada — confira o `erro` do primeiro caso.",
            file=sys.stderr,
        )
        return SAIDA_SEM_RESPOSTA
    return SAIDA_OK


if __name__ == "__main__":
    raise SystemExit(main())
