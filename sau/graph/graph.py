"""Grafo LangGraph do turno de resposta do S.A.U.

O grafo é a espinha do projeto: a classificação da intenção e as rotas da 1.2
entram aqui dentro, como nós e arestas novos. A #8 monta o menor grafo que prova
o caminho ponta a ponta — um único nó, `responder`:

    START → responder → END

A entrada e a saída do grafo ficam logadas, que é o critério da #8 e o que deixa
a resposta rastreável quando alguém depura uma conversa. As regras de
comportamento (#10) e a rota de recuperação (1.2/P5) acrescentam nós e arestas a
partir daqui.
"""

from __future__ import annotations

import logging
from typing import Any, cast

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from sau.graph.nodes import EstadoTurno, criar_no_responder
from sau.inference.ollama import ClienteOllama

logger = logging.getLogger("sau.graph.graph")


GrafoDoTurno = CompiledStateGraph[EstadoTurno, None, EstadoTurno, EstadoTurno]
"""O grafo compilado do turno, com os quatro parâmetros de tipo preenchidos.

`strict` exige todos eles, e `None` no lugar de `ContextT` é o que o `StateGraph`
de um schema só infere: este grafo não usa contexto, `store` nem escrita
direcionada. Escrever o tipo inteiro aqui é o que permite nomear o retorno de
`construir_grafo` sem `Any` no resto do módulo.
"""


def construir_grafo(cliente: ClienteOllama) -> GrafoDoTurno:
    """Monta e compila o grafo do turno, com um único caminho.

    O grafo é remontado a cada turno. Parece desperdício e não é: o compilado é
    barato comparado à inferência, e um grafo por turno é o que mantém o cliente
    do modelo como dependência da chamada, e não estado global do módulo. Quando
    a #9 trouxer o estado por conversa, é aqui que ele passa a ser lido e
    escrito.
    """
    construtor = StateGraph(EstadoTurno)
    # O `cast` é só de tipo, e ele é estreito de propósito: o que desliga é a
    # prova de que o callable casa com o `Protocol` do LangGraph, não a checagem
    # do próprio nó. A assinatura e o corpo de `criar_no_responder` continuam
    # sob o mypy, e o `Any` fica em um único ponto do módulo.
    #
    # A compatibilidade que o `cast` não pode provar é esta: o `add_node` do
    # LangGraph 1.2 declara o nó como um `Protocol` (`_Node[NodeInputT]`) com
    # `TypeVar` contravariante e limite em uma união, e o mypy não consegue provar
    # que um `Callable` comum satisfaz esse `Protocol` — nem na chamada mais
    # direta possível. O grafo aceito em tempo de execução é o mesmo, e
    # `test_grafo_tem_um_caminho_so` prova a topologia e
    # `test_turno_devolve_o_texto_do_modelo` prova a execução.
    construtor.add_node("responder", cast(Any, criar_no_responder(cliente)))
    construtor.add_edge(START, "responder")
    construtor.add_edge("responder", END)
    return construtor.compile()


def executar_turno(cliente: ClienteOllama, mensagem: str) -> str:
    """Roda um turno e devolve a resposta do modelo.

    A mensagem do Aluno e a resposta do modelo são a entrada e a saída do grafo,
    e as duas saem no log: é o que torna um turno rastreável depois do fato.
    """
    grafo = construir_grafo(cliente)
    logger.info("Entrada do grafo: mensagem do Aluno:\n%s", mensagem)
    entrada: EstadoTurno = {"mensagem": mensagem}
    resultado = grafo.invoke(entrada)
    resposta = cast(str, resultado["resposta"])
    logger.info("Saída do grafo: resposta ao Aluno:\n%s", resposta)
    return resposta
