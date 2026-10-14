"""Nós do grafo de resposta do turno do S.A.U.

A recuperação deixou de ser etapa obrigatória do turno e virou ferramenta
opcional da LLM (`buscar_no_manual`), conforme o ADR-0010. Desde a #36 o ciclo do
agente é dividido em dois papéis, porque o modelo pequeno não sustenta decisão e
redação num prompt só:

    roteador → (chamou ferramenta?) → ferramentas → roteador … → redator → finalizar

Quando o roteador declina a consulta — responde direto sem chamar a ferramenta
—, o ciclo passa pela `busca_de_seguranca` antes do redator: uma busca
determinística com a mensagem crua do Aluno, que só anexa material quando acha
evidência. Sem ela, um declínio numa pergunta factual deixava o redator sem
material nenhum.

O nó `roteador` leva as mensagens ao modelo por `/api/chat`, com o schema da
ferramenta declarado em `tools`, e a persona enxuta do roteamento
(`sau.persona.montar_prompt_de_roteamento`). Ele **decide**: quando o modelo
responde direto — saudação, agradecimento, pergunta fora do escopo —, o ciclo
não abre; quando pede a ferramenta, o nó `ferramentas` busca no Manual, devolve o
resultado como mensagem `tool` e o roteador decide de novo.

O nó `redator` é quem escreve a resposta ao Aluno: monta o prompt com a persona
completa (`sau.persona.montar_prompt`) **sem declarar `tools`** e recebe os pares
de ferramenta do roteador como mensagens `tool`. Um redator que recebe os trechos
sem tool calling escreve ancorado e fluente — era a tentativa de o modelo fazer
tool-call e persona ao mesmo tempo que produzia a resposta quebrada.

O nó `finalizar` carrega a **guarda determinística** da ausência de evidência:
se o roteador chamou a ferramenta e nada passou pelo limiar, a resposta vira o
literal "não encontrei no material" com Encaminhamento, sem depender de o
redator obedecer ao prompt. É a metade em código do critério do ADR-0012, que o
prompt pede e o grafo garante.

Os prompts do turno vêm de `sau.persona`, reexportados aqui para que quem importa
o caminho do prompt continue resolvendo a partir deste módulo: o do roteador
(`montar_prompt_de_roteamento`) e o do redator (`montar_prompt`).
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
from sau.persona import montar_prompt_de_roteamento as montar_prompt_de_roteamento

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
    existem aqui para o log e para os testes. O que o ciclo do roteador usa de
    fato é `mensagens`: a lista no formato do `/api/chat`, que começa com a
    persona do roteamento mais a conversa, ganha a resposta do modelo, ganha as
    mensagens `tool` dos resultados e volta ao roteador até o modelo responder
    direto. O `redator` reconstrói o próprio prompt a partir de `mensagem` e
    `historico`, então não depende dessa lista: ele só colhe dela os pares de
    ferramenta.

    `pendentes` são as chamadas de ferramenta que o último `roteador` pediu e
    `ferramentas` ainda não executou; é o que a aresta condicional lê para
    decidir entre voltar ao roteador e passar ao redator. `houve_ferramenta` e
    `houve_evidencia` são o que a guarda do `finalizar` lê: chamou a ferramenta
    e nada voltou acima do limiar vira o literal de ausência.

    `resposta` é `NotRequired` porque o estado nasce sem ela e é o `redator` que
    a preenche (o `finalizar` pode trocá-la pelo literal de ausência). `rodadas`
    conta quantas vezes o roteador já foi consultado, e é o teto que impede o
    ciclo infinito.
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


def criar_no_roteador(
    cliente: ClienteOllama,
    *,
    ferramentas: list[dict[str, Any]] | None,
) -> Callable[[EstadoTurno], dict[str, Any]]:
    """Cria o nó `roteador`, que decide se consulta o Manual antes de responder.

    O cliente é injetado para que o grafo não saiba onde o modelo roda: em
    serviço é o `ClienteOllama` do ADR-0002, e nos testes é o mesmo cliente com
    um transporte falso. `ferramentas` é o schema declarado em `tools`; quando é
    `None`, o roteador conversa sem tool calling e o ciclo nunca abre — o modo
    dos testes de persona, que medem o prompt e não a ferramenta.

    A resposta do modelo entra na lista de mensagens como a fala dele: quando é
    uma chamada de ferramenta, a mensagem carrega `tool_calls` para que o
    roteador, na rodada seguinte, veja o que ele mesmo pediu e interprete o
    resultado. A decisão sai no log — consultou o Manual ou respondeu sem
    consultar —, porque é ela o que esta persona foi separada para medir.
    """

    def roteador(estado: EstadoTurno) -> dict[str, Any]:
        mensagens = list(estado.get("mensagens", []))
        logger.info("Prompt do turno enviado ao modelo:\n%s", _ultima_mensagem(mensagens))
        resposta: Resposta = cliente.conversar(mensagens, ferramentas=ferramentas)
        mensagens.append(_mensagem_do_assistente(resposta))
        if resposta.chamadas:
            logger.info(
                "Roteador decidiu consultar o Manual: %s.",
                [chamada.nome for chamada in resposta.chamadas],
            )
        else:
            logger.info("Roteador decidiu responder sem consultar o Manual.")
        _avisar_se_cortado(resposta)
        return {
            "mensagens": mensagens,
            "resposta": resposta.texto,
            "pendentes": list(resposta.chamadas),
            "rodadas": estado.get("rodadas", 0) + 1,
        }

    return roteador


def criar_no_redator(cliente: ClienteOllama) -> Callable[[EstadoTurno], dict[str, Any]]:
    """Cria o nó `redator`, que escreve a resposta ao Aluno **sem** tool calling.

    O redator reconstrói o próprio prompt a partir de `mensagem` e `historico` —
    não depende das `mensagens` que o roteador acumulou — e recebe os pares de
    ferramenta daquele acúmulo como mensagens `tool`. O ponto central da #36 é a
    ausência de `ferramentas`: `cliente.conversar(mensagens, ferramentas=None)`.
    Um redator que declarasse `tools` voltaria a tentar tool-call e persona ao
    mesmo tempo, que é o defeito que a separação veio fechar.

    Quando não há resultado de ferramenta — saudação, resposta direta —, a lista
    tem só o próprio prompt: não há material a ancorar, e a resposta sai da
    persona.
    """

    def redator(estado: EstadoTurno) -> dict[str, Any]:
        mensagem = estado["mensagem"]
        historico = estado.get("historico", [])
        mensagens = [
            {"role": "user", "content": montar_prompt(mensagem, historico)},
            *_pares_de_ferramenta(estado.get("mensagens", [])),
        ]
        logger.info("Prompt do turno enviado ao modelo:\n%s", _ultima_mensagem(mensagens))
        resposta: Resposta = cliente.conversar(mensagens, ferramentas=None)
        _avisar_se_cortado(resposta)
        return {"resposta": resposta.texto}

    return redator


def _pares_de_ferramenta(mensagens: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extrai o histórico de consulta do roteador: os pares `tool_calls`/`tool`.

    Devolve, na ordem em que foram acumuladas, só as mensagens `assistant` que
    carregam `tool_calls` e as mensagens `role == "tool"` — o que o roteador
    consultou e o que a ferramenta respondeu. Os prompts `user` e as mensagens
    de texto ficam de fora: o redator reconstrói o próprio prompt, e reenviar a
    conversa inteira duplicaria a persona no corpo da requisição.
    """
    pares: list[dict[str, Any]] = []
    for mensagem in mensagens:
        papel = mensagem.get("role")
        if papel == "tool" or (papel == "assistant" and mensagem.get("tool_calls")):
            pares.append(mensagem)
    return pares


def criar_no_ferramentas(
    cliente: ClienteOllama, *, manual: OpcoesDoManual
) -> Callable[[EstadoTurno], dict[str, Any]]:
    """Cria o nó `ferramentas`, que executa o que o modelo pediu.

    O cliente é o mesmo do roteador: ele carrega o embedding junto, e é ele que
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


def criar_no_busca_de_seguranca(
    cliente: ClienteOllama, *, manual: OpcoesDoManual
) -> Callable[[EstadoTurno], dict[str, Any]]:
    """Cria o nó `busca_de_seguranca`, o fallback determinístico do declínio.

    O roteador às vezes declina uma pergunta factual — responde "sem busca" sem
    chamar a ferramenta —, e sem este nó o redator escreveria sem material
    nenhum: foi assim que uma resposta não ancorada saiu carimbada com
    "Segundo o material da UNOPAR". O nó faz UMA busca determinística com a
    mensagem crua do Aluno, pelo mesmo caminho seguro do nó `ferramentas`
    (`_executar_chamada_segura`, que registra a auditoria e degrada para vazio
    em vez de derrubar o turno).

    Com trechos, anexa o par assistant-com-`tool_calls` mais a mensagem `tool`
    e marca `houve_ferramenta` e `houve_evidencia`: o redator escreve ancorado,
    e a guarda do `finalizar` vê que houve evidência. Sem trechos, NÃO anexa
    nada e NÃO toca nas bandeiras — só loga. É o que mantém a saudação fora do
    literal de ausência: a guarda só dispara com `houve_ferramenta`, e uma
    saudação que não achou nada continua sendo resposta direta, não ausência
    de evidência.
    """

    def busca_de_seguranca(estado: EstadoTurno) -> dict[str, Any]:
        mensagem = estado["mensagem"]
        trechos = _executar_chamada_segura(
            ChamadaDeFerramenta(nome=NOME_DA_FERRAMENTA, argumentos={"consulta": mensagem}),
            cliente,
            manual,
        )
        if not trechos:
            logger.info(
                "Busca de segurança sem evidência no Manual: o turno segue sem "
                "material, e a resposta do redator passa intacta."
            )
            return {}
        logger.info(
            "Busca de segurança achou evidência no Manual: o redator escreve ancorado."
        )
        return {
            "mensagens": [
                *estado.get("mensagens", []),
                {
                    "role": "assistant",
                    "content": "sem busca",
                    "tool_calls": [
                        {
                            "function": {
                                "name": NOME_DA_FERRAMENTA,
                                "arguments": {"consulta": mensagem},
                            }
                        }
                    ],
                },
                {
                    "role": "tool",
                    "tool_name": NOME_DA_FERRAMENTA,
                    "content": formatar_para_o_modelo(trechos),
                },
            ],
            "houve_ferramenta": True,
            "houve_evidencia": True,
            "fontes": [*estado.get("fontes", []), *(trecho.fonte for trecho in trechos)],
        }

    return busca_de_seguranca


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
    """A aresta condicional: ferramenta pedida, busca de segurança ou redator.

    Vai às `ferramentas` enquanto houver chamada pendente e o teto de rodadas não
    foi atingido. Sem chamada pendente e sem nenhuma ferramenta executada — o
    roteador declinou de primeira —, passa à `busca_de_seguranca`, que tenta UMA
    busca determinística antes de entregar ao redator. Sem chamada pendente mas
    com ferramenta já executada — o declínio pós-busca —, vai direto ao
    `redator`, sem rebusca: o material já está nas mensagens. Ao atingir o teto,
    também passa ao `redator` em vez de girar para sempre.
    """
    if estado.get("pendentes") and estado.get("rodadas", 0) < LIMITE_DE_RODADAS:
        return "ferramentas"
    if not estado.get("houve_ferramenta"):
        return "busca_de_seguranca"
    return "redator"


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


def _avisar_se_cortado(resposta: Resposta) -> None:
    """Registra o aviso quando a geração parou por falta de espaço.

    O corte silencioso é o pior caso: nenhuma falha é lançada e o Aluno recebe
    uma resposta truncada. Roteador e redator geram pelo mesmo caminho e sofrem
    o mesmo corte, então o aviso mora aqui, num lugar só.
    """
    if resposta.motivo_de_parada == MOTIVO_PARADA_NO_LIMITE:
        logger.warning(
            "A geração parou por falta de espaço e saiu cortada: o Aluno "
            "recebeu uma resposta incompleta, e nenhuma falha foi lançada. "
            "Motivo informado: %s.",
            resposta.motivo_de_parada,
        )


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
