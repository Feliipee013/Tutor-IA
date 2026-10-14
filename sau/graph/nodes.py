"""Nós do grafo de resposta do turno do S.A.U.

A recuperação deixou de ser etapa obrigatória do turno e virou ferramenta
opcional da LLM (`buscar_no_manual`), conforme o ADR-0010. O grafo deixa de ter
um nó `recuperar` que roda em todo turno e passa a ter um ciclo de agente:

    agente → (chamou ferramenta?) → ferramentas → agente ... → finalizar

O nó `agente` leva as mensagens ao modelo por `/api/chat`, com o schema da
ferramenta declarado em `tools`. Quando o modelo responde direto — saudação,
agradecimento, pergunta fora do escopo —, o ciclo não abre. Quando ele pede a
ferramenta, o nó `ferramentas` busca no Manual, devolve o resultado como
mensagem `tool` e o agente volta a decidir; uma pergunta que cruza assuntos
pode chamar a ferramenta mais de uma vez.

O nó `finalizar` carrega a **guarda determinística** da ausência de evidência:
se o modelo chamou a ferramenta e nada passou pelo limiar, a resposta vira o
literal "não encontrei no material" com Encaminhamento, sem depender de o
modelo obedecer ao prompt. É a metade em código do critério do ADR-0012, que o
prompt pede e o grafo garante.

O prompt do turno vem de `sau.persona.montar_prompt`, reexportado aqui para que
quem importa o caminho do prompt continue resolvendo a partir deste módulo. A
persona entra como a primeira mensagem `user` da conversa; o histórico e a
mensagem do Aluno vão dentro dela, com a cerca de sempre.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, NotRequired, TypedDict

from sau.config import Configuracao
from sau.graph.state import Mensagem
from sau.inference.ollama import (
    MOTIVO_PARADA_NO_LIMITE,
    ChamadaDeFerramenta,
    ClienteOllama,
    Resposta,
)
from sau.manual.tool import (
    NOME_DA_FERRAMENTA,
    TrechoFiltrado,
    executar_chamada,
    formatar_para_o_modelo,
)
from sau.persona import montar_prompt as montar_prompt

logger = logging.getLogger("sau.graph.nodes")

LIMITE_DE_RODADAS = 4
"""Quantas vezes o agente pode pedir ferramenta antes de o turno ser encerrado.

É a trava contra o laço infinito: um modelo que peça a ferramenta para sempre
travaria o turno de um Aluno. Quatro é mais do que qualquer pergunta da bateria
precisa — o ADR-0010 fala em "mais de uma vez" para perguntas cruzadas — e é
baixo o bastante para o pior caso continuar respondendo.
"""


@dataclass(frozen=True)
class OpcoesDoManual:
    """O que o turno precisa para consultar o Manual: onde, quanto e com que corte.

    Vem da `Configuracao` do serviço (`manual_chroma_caminho`, `manual_colecao`,
    `manual_k_padrao`, `manual_limiar_similaridade`). O grafo não lê o ambiente
    sozinho: quem monta o turno passa estas opções, e o teste monta com as dele
    — o mesmo desenho do registro de conversas e do semáforo.
    """

    diretorio_chroma: Path
    nome_colecao: str
    k_padrao: int
    limiar: float

    @classmethod
    def de_config(cls, config: Configuracao) -> OpcoesDoManual:
        """Extrai as opções do Manual de uma `Configuracao` carregada."""
        return cls(
            diretorio_chroma=Path(config.manual_chroma_caminho),
            nome_colecao=config.manual_colecao,
            k_padrao=config.manual_k_padrao,
            limiar=config.manual_limiar_similaridade,
        )


class EstadoTurno(TypedDict):
    """O estado de um turno: as mensagens da conversa com o modelo e a resposta.

    `mensagem` e `historico` são a entrada do turno — o que veio do Aluno —, e
    existem aqui para o log e para os testes. O que o ciclo do agente usa de
    fato é `mensagens`: a lista no formato do `/api/chat`, que começa com a
    persona mais a conversa, ganha a resposta do modelo, ganha as mensagens
    `tool` dos resultados e volta ao agente até o modelo responder direto.

    `pendentes` são as chamadas de ferramenta que o último `agente` pediu e
    `ferramentas` ainda não executou; é o que a aresta condicional lê para
    decidir entre voltar ao agente e encerrar. `houve_ferramenta` e
    `houve_evidencia` são o que a guarda do `finalizar` lê: chamou a ferramenta
    e nada voltou acima do limiar vira o literal de ausência.

    `resposta` é `NotRequired` porque o estado nasce sem ela e é o `agente` ou
    o `finalizar` que a preenche. `rodadas` conta quantas vezes o modelo já foi
    consultado, e é o teto que impede o ciclo infinito.
    """

    mensagem: str
    historico: NotRequired[list[Mensagem]]
    mensagens: NotRequired[list[dict[str, Any]]]
    pendentes: NotRequired[list[ChamadaDeFerramenta]]
    houve_ferramenta: NotRequired[bool]
    houve_evidencia: NotRequired[bool]
    fontes: NotRequired[list[str]]
    rodadas: NotRequired[int]
    resposta: NotRequired[str]


def criar_no_agente(
    cliente: ClienteOllama,
    *,
    ferramentas: list[dict[str, Any]] | None,
) -> Callable[[EstadoTurno], dict[str, Any]]:
    """Cria o nó `agente`, que leva as mensagens ao modelo.

    O cliente é injetado para que o grafo não saiba onde o modelo roda: em
    serviço é o `ClienteOllama` do ADR-0002, e nos testes é o mesmo cliente com
    um transporte falso. `ferramentas` é o schema declarado em `tools`; quando é
    `None`, o agente conversa sem tool calling e o ciclo nunca abre — o modo dos
    testes de persona, que medem o prompt e não a ferramenta.

    A resposta do modelo entra na lista de mensagens como a fala dele: quando é
    uma chamada de ferramenta, a mensagem carrega `tool_calls` para que o modelo,
    na rodada seguinte, veja o que ele mesmo pediu e interprete o resultado.
    """

    def agente(estado: EstadoTurno) -> dict[str, Any]:
        mensagens = list(estado.get("mensagens", []))
        logger.info("Prompt do turno enviado ao modelo:\n%s", _ultima_mensagem(mensagens))
        resposta: Resposta = cliente.conversar(mensagens, ferramentas=ferramentas)
        mensagens.append(_mensagem_do_assistente(resposta))
        if resposta.motivo_de_parada == MOTIVO_PARADA_NO_LIMITE:
            logger.warning(
                "A geração parou por falta de espaço e saiu cortada: o Aluno "
                "recebeu uma resposta incompleta, e nenhuma falha foi lançada. "
                "Motivo informado: %s.",
                resposta.motivo_de_parada,
            )
        return {
            "mensagens": mensagens,
            "resposta": resposta.texto,
            "pendentes": list(resposta.chamadas),
            "rodadas": estado.get("rodadas", 0) + 1,
        }

    return agente


def criar_no_ferramentas(
    cliente: ClienteOllama, *, manual: OpcoesDoManual
) -> Callable[[EstadoTurno], dict[str, Any]]:
    """Cria o nó `ferramentas`, que executa o que o modelo pediu.

    O cliente é o mesmo do agente: ele carrega o embedding junto, e é ele que
    `buscar_no_manual` usa para embutir a consulta. O Manual é o índice
    persistente do ADR-0011, acessado pelo diretório e pela coleção das opções.

    Cada resultado volta como uma mensagem `tool` com o nome da ferramenta. O
    `houve_evidencia` só vira `True` quando algum trecho passou pelo limiar —
    lista vazia é ausência de evidência, e é o que a guarda do `finalizar` lê.
    Uma chamada a uma ferramenta desconhecida devolve vazio em vez de derrubar
    o turno: só `buscar_no_manual` é declarada, e qualquer outro nome é saída
    de modelo que não se deve confiar.
    """

    def ferramentas(estado: EstadoTurno) -> dict[str, Any]:
        mensagens = list(estado.get("mensagens", []))
        houve_ferramenta = bool(estado.get("houve_ferramenta", False))
        houve_evidencia = bool(estado.get("houve_evidencia", False))
        fontes = list(estado.get("fontes", []))

        for chamada in estado.get("pendentes", []):
            houve_ferramenta = True
            trechos = _executar_chamada_segura(chamada, cliente, manual)
            if trechos:
                houve_evidencia = True
                fontes.extend(trecho.fonte for trecho in trechos)
            mensagens.append(
                {
                    "role": "tool",
                    "tool_name": chamada.nome,
                    "content": formatar_para_o_modelo(trechos),
                }
            )

        return {
            "mensagens": mensagens,
            "houve_ferramenta": houve_ferramenta,
            "houve_evidencia": houve_evidencia,
            "fontes": fontes,
            "pendentes": [],
        }

    return ferramentas


def criar_no_finalizar(*, texto_ausencia: str) -> Callable[[EstadoTurno], dict[str, str]]:
    """Cria o nó `finalizar`, com a guarda determinística de ausência de evidência.

    Se o modelo chamou a ferramenta e nenhum trecho passou pelo limiar, o texto
    do modelo é substituído pelo literal de ausência com Encaminhamento. Sem
    isso, o critério do ADR-0012 dependeria de o modelo obedecer ao prompt — e a
    proteção contra Alucinação não pode ser creditada ao modelo (ADR-0003). É a
    metade em código do que o prompt pede.

    Quando não houve ferramenta — saudação, agradecimento, resposta direta —, a
    resposta do modelo passa intacta: não há busca para não ter encontrado nada.
    """

    def finalizar(estado: EstadoTurno) -> dict[str, str]:
        if estado.get("houve_ferramenta") and not estado.get("houve_evidencia"):
            logger.info(
                "A ferramenta foi chamada e nenhum trecho passou pelo limiar: "
                "resposta trocada pelo literal de ausência."
            )
            return {"resposta": texto_ausencia}
        return {"resposta": estado.get("resposta", "")}

    return finalizar


def rota_das_ferramentas(estado: EstadoTurno) -> str:
    """A aresta condicional: executar a ferramenta pedida ou encerrar o turno.

    Volta ao `agente` enquanto houver chamada pendente e o teto de rodadas não
    foi atingido. Sem chamada pendente — resposta direta do modelo —, encerra.
    Ao atingir o teto, encerra com o que o modelo já escreveu em vez de girar
    para sempre.
    """
    if estado.get("pendentes") and estado.get("rodadas", 0) < LIMITE_DE_RODADAS:
        return "ferramentas"
    return "finalizar"


def _executar_chamada_segura(
    chamada: ChamadaDeFerramenta, cliente: ClienteOllama, manual: OpcoesDoManual
) -> list[TrechoFiltrado]:
    """Executa a chamada, degradando para vazio em vez de derrubar o turno.

    A exceção larga é deliberada, como na antiga recuperação: um índice que não
    monta ou um embedding que não responde vira ausência de evidência, e o Aluno
    recebe o Encaminhamento — não a mensagem amigável de falha do instrumento.
    O motivo vai no log para que a causa seja legível depois.
    """
    if chamada.nome != NOME_DA_FERRAMENTA:
        logger.warning("O modelo chamou uma ferramenta desconhecida: %r.", chamada.nome)
        return []
    try:
        return executar_chamada(
            chamada.argumentos,
            diretorio_chroma=manual.diretorio_chroma,
            nome_colecao=manual.nome_colecao,
            cliente=cliente,
            k_padrao=manual.k_padrao,
            limiar=manual.limiar,
        )
    except Exception as exc:
        logger.warning(
            "A ferramenta falhou e o turno segue sem material: %s: %s. "
            "O Aluno recebe o Encaminhamento determinístico do grafo.",
            type(exc).__name__,
            exc,
        )
        return []


def _mensagem_do_assistente(resposta: Resposta) -> dict[str, Any]:
    """A fala do modelo como mensagem de chat, com as chamadas quando houver."""
    mensagem: dict[str, Any] = {"role": "assistant", "content": resposta.texto}
    if resposta.chamadas:
        mensagem["tool_calls"] = [
            {"function": {"name": chamada.nome, "arguments": chamada.argumentos}}
            for chamada in resposta.chamadas
        ]
    return mensagem


def _ultima_mensagem(mensagens: list[dict[str, Any]]) -> str:
    """O texto da última mensagem `user`: o prompt que o modelo recebeu.

    Aqui entra no log só o **prompt**. O texto do modelo já sai em dois outros
    lugares, e nenhum deles é este: o `ClienteOllama` grava a resposta com os
    tempos que a mediram, e o `grafo` grava a entrada e a saída do turno. A
    composição do que foi enviado só existe aqui, e é por isso que ela fica
    registrada.
    """
    for mensagem in reversed(mensagens):
        if mensagem.get("role") == "user":
            return str(mensagem.get("content", ""))
    return ""
