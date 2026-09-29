"""Nós do grafo de resposta do turno do S.A.U.

Um nó, por enquanto: `responder` leva a mensagem do Aluno ao modelo e devolve o
texto. O grafo tem um único caminho (issue #8) — a classificação de intenção, a
recuperação da 1.2 e o encaminhamento entram como nós e arestas novos aqui
dentro, não como serviço à parte.

O prompt do turno mora em `montar_prompt`, e é de propósito uma costura isolada:
a #8 não tem persona, e é a #10 que troca este texto pelo prompt versionado do
S.A.U. sem tocar no resto do grafo.
"""

from __future__ import annotations

import logging
from typing import Callable, NotRequired, TypedDict

from sau.inference.ollama import ClienteOllama, Resposta

logger = logging.getLogger("sau.graph.nodes")


class EstadoTurno(TypedDict):
    """O estado de um turno: a mensagem que entra e a resposta que sai.

    É por turno, não por conversa: o histórico isolado por Aluno é a #9, dona de
    `sau/graph/state.py`. Aqui só trafega o que este turno precisa, e a resposta
    é opcional porque ela não existe antes de o nó `responder` rodar.
    """

    mensagem: str
    resposta: NotRequired[str]


PROMPT_SEM_PERSONA = "Responda à mensagem do Aluno:\n\n{mensagem}"
"""O corpo do prompt do turno, ainda sem persona.

A #10 substitui este texto pelo prompt versionado do S.A.U. (tom, regras de
comportamento, o que recusar). Até lá, o modelo recebe a mensagem crua do Aluno
com a instrução mínima de respondê-la — nada de tom ou de regra aqui, para que a
troca da #10 seja uma troca de texto e não uma reescrita do grafo.
"""


def montar_prompt(mensagem: str) -> str:
    """Monta o prompt do turno a partir da mensagem do Aluno.

    É a costura da persona (#10): quem for injetar o prompt versionado troca
    esta função, e o grafo não precisa saber que o texto mudou.
    """
    return PROMPT_SEM_PERSONA.format(mensagem=mensagem)


def criar_no_responder(cliente: ClienteOllama) -> Callable[[EstadoTurno], dict[str, str]]:
    """Cria o nó `responder`, que leva o turno ao modelo e devolve o texto.

    O cliente é injetado para que o grafo não saiba onde o modelo roda: em
    serviço é o `ClienteOllama` que alcança o Ollama do host (ADR-0002), e nos
    testes é o mesmo cliente com um transporte falso.

    Aqui entra no log só o **prompt**. O texto do modelo já sai em dois outros
    lugares, e nenhum deles é este: o `ClienteOllama` grava a resposta com os
    tempos que a mediram, e o `grafo` grava a saída do turno. O prompt é a única
    coisa que só este módulo sabe — depois da #10 ele deixa de ser a mensagem
    crua do Aluno — e é por isso que ele fica registrado aqui.
    """

    def responder(estado: EstadoTurno) -> dict[str, str]:
        prompt = montar_prompt(estado["mensagem"])
        logger.info("Prompt do turno enviado ao modelo:\n%s", prompt)
        resposta: Resposta = cliente.responder(prompt)
        return {"resposta": resposta.texto}

    return responder
