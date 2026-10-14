"""Grafo LangGraph do turno de resposta do S.A.U.

A recuperação deixou de ser etapa obrigatória e virou ferramenta opcional da
LLM, conforme o ADR-0010. Desde a #36 o ciclo é dividido em dois papéis, porque
o modelo pequeno não sustenta decisão e redação num prompt só:

    START → roteador → (chamou a ferramenta?) → ferramentas → roteador … → redator → finalizar → END

Quando o roteador declina a consulta sem chamar a ferramenta, o ciclo passa pela
`busca_de_seguranca` — UMA busca determinística com a mensagem do Aluno, que só
anexa material quando acha evidência — antes do redator. Sem ela, um declínio
numa pergunta factual deixava o redator sem material.

O nó `roteador` leva a conversa ao modelo por `/api/chat` com o schema de
`buscar_no_manual` declarado e a persona enxuta do roteamento. Ele **decide**:
quando o modelo responde direto — saudação, agradecimento, pergunta fora do
escopo —, o ciclo não abre; quando pede a ferramenta, o nó `ferramentas` busca
no Manual, devolve o resultado como mensagem `tool` e o roteador decide de novo.
O nó `redator` é quem escreve a resposta ao Aluno: leva a persona completa
**sem declarar `tools`** e recebe os pares de ferramenta do roteador. O
`finalizar` carrega a guarda determinística: ferramenta chamada sem evidência
vira o literal de ausência, mesmo que o modelo tenha respondido outra coisa.

Sem `manual`, não há ferramenta nem decisão a tomar: o grafo vira
`START → redator → finalizar → END`, e o redator escreve direto da persona.

A entrada e a saída do grafo ficam logadas, que é o critério da #8 e o que deixa
a resposta rastreável quando alguém depura uma conversa. O turno recebe o
`historico` da conversa, que o `webhook` leu do registro (`sau/graph/state.py`)
e passou pronto. O grafo **não** lê nem grava estado: é o que mantém a troca da
persona (#10) como troca de texto e o registro como uma classe que se reescreve
inteira se um dia o banco mudar.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any, cast

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from sau.graph.nodes import (
    EstadoTurno,
    OpcoesDoManual,
    criar_no_busca_de_seguranca,
    criar_no_ferramentas,
    criar_no_finalizar,
    criar_no_redator,
    criar_no_roteador,
    rota_das_ferramentas,
)
from sau.graph.nodes import montar_prompt as montar_prompt
from sau.graph.nodes import montar_prompt_de_roteamento as montar_prompt_de_roteamento
from sau.graph.state import Mensagem
from sau.inference.ollama import ClienteOllama
from sau.manual.tool import LITERAL_NAO_ENCONTREI, esquema_da_ferramenta

logger = logging.getLogger("sau.graph.graph")

TEXTO_AUSENCIA = f"{LITERAL_NAO_ENCONTREI}. Procure a Coordenação de Estágios."
"""O Encaminhamento determinístico quando a ferramenta não acha evidência.

Mora no grafo — e não na persona — para que o `sha256_do_prompt` continue
reportando a persona e não a topologia: mudar este texto não muda o hash.
É a metade em código do critério do ADR-0012: o literal "não encontrei no
material" com Encaminhamento não depende de o modelo obedecer ao prompt.
"""

GrafoDoTurno = CompiledStateGraph[EstadoTurno, None, EstadoTurno, EstadoTurno]
"""O grafo compilado do turno, com os quatro parâmetros de tipo preenchidos.

`strict` exige todos eles, e `None` no lugar de `ContextT` é o que o `StateGraph`
de um schema só infere: este grafo não usa contexto, `store` nem escrita
direcionada. Escrever o tipo inteiro aqui é o que permite nomear o retorno de
`construir_grafo` sem `Any` no resto do módulo.
"""


def construir_grafo(
    cliente: ClienteOllama, *, manual: OpcoesDoManual | None = None
) -> GrafoDoTurno:
    """Monta e compila o grafo do turno: o roteador, as ferramentas e o redator.

    O grafo é remontado a cada turno. Parece desperdício e não é: o compilado é
    barato comparado à inferência, e um grafo por turno é o que mantém o cliente
    do modelo como dependência da chamada, e não estado global do módulo. O
    índice do Manual não paga essa remontagem: ele é persistente (ADR-0011), no
    volume nomeado, e cada turno só embute a consulta do modelo. O estado da
    conversa entra pela chamada, pelo `historico`, e nunca pelo grafo montado.

    `manual` são as opções de consulta ao Manual (onde, quanto e com que corte).
    Quando é `None`, não há ferramenta a declarar nem decisão a tomar: o grafo
    vira `START → redator → finalizar → END`, sem o roteador — o modo dos testes
    que medem o prompt sem tocar no índice.
    """
    construtor = StateGraph(EstadoTurno)

    ferramentas = (
        [esquema_da_ferramenta(k_padrao=manual.k_padrao)] if manual is not None else None
    )
    roteador = criar_no_roteador(cliente, ferramentas=ferramentas)
    redator = criar_no_redator(cliente)
    finalizar = criar_no_finalizar(texto_ausencia=TEXTO_AUSENCIA)

    construtor.add_node("redator", cast(Any, redator))
    construtor.add_node("finalizar", cast(Any, finalizar))
    construtor.add_edge("redator", "finalizar")
    construtor.add_edge("finalizar", END)

    if manual is not None:
        construtor.add_node(
            "roteador", cast(Any, roteador)
        )  # O `cast` é só de tipo: o nó casa em execução.
        construtor.add_node(
            "ferramentas", cast(Any, criar_no_ferramentas(cliente, manual=manual))
        )
        construtor.add_node(
            "busca_de_seguranca",
            cast(Any, criar_no_busca_de_seguranca(cliente, manual=manual)),
        )
        construtor.add_edge(START, "roteador")
        construtor.add_edge("ferramentas", "roteador")
        construtor.add_edge("busca_de_seguranca", "redator")
        construtor.add_conditional_edges(
            "roteador",
            rota_das_ferramentas,
            {
                "ferramentas": "ferramentas",
                "busca_de_seguranca": "busca_de_seguranca",
                "redator": "redator",
            },
        )
    else:
        construtor.add_edge(START, "redator")

    return construtor.compile()


def executar_turno(
    cliente: ClienteOllama,
    mensagem: str,
    historico: Sequence[Mensagem] = (),
    *,
    manual: OpcoesDoManual | None = None,
) -> str:
    """Roda um turno e devolve a resposta do modelo.

    A mensagem do Aluno, o `historico` da conversa e a resposta do modelo são a
    entrada e a saída do grafo, e as duas pontas saem no log: é o que torna um
    turno rastreável depois do fato.

    O `historico` é lista e padrão vazio pelos mesmos motivos de antes: a lista
    porque quem chama é o `webhook`, e o vazio porque é o estado de antes da #9.
    `manual` são as opções da ferramenta; sem elas o turno roda sem consulta ao
    Manual.

    A entrada é o prompt do **roteador** quando há Manual — é ele quem abre o
    turno decidindo se consulta; o `redator` reconstrói o próprio prompt a partir
    de `mensagem` e `historico`. Sem Manual não há roteador, e a entrada é o
    prompt do redator.
    """
    grafo = construir_grafo(cliente, manual=manual)
    logger.info("Entrada do grafo: mensagem do Aluno:\n%s", mensagem)
    prompt = (
        montar_prompt_de_roteamento(mensagem, historico)
        if manual is not None
        else montar_prompt(mensagem, historico)
    )
    entrada: EstadoTurno = {
        "mensagem": mensagem,
        "historico": list(historico),
        "mensagens": [{"role": "user", "content": prompt}],
        "rodadas": 0,
    }
    resultado = grafo.invoke(entrada)
    resposta = cast(str, resultado.get("resposta", ""))
    logger.info("Saída do grafo: resposta ao Aluno:\n%s", resposta)
    return resposta
