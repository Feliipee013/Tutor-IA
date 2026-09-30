"""Nós do grafo de resposta do turno do S.A.U.

Um nó, por enquanto: `responder` leva a mensagem do Aluno ao modelo e devolve o
texto. O grafo tem um único caminho (issue #8) — a classificação de intenção, a
recuperação da 1.2 e o encaminhamento entram como nós e arestas novos aqui
dentro, não como serviço à parte.

O prompt do turno vem de `sau.persona.montar_prompt`, e a costura é de
propósito isolada: a persona do S.A.U. (issue #10) entra por esta função, e o
resto do grafo não precisa saber que o texto mudou. Reexportada aqui para que
quem importa o caminho do prompt continue resolvendo a partir deste módulo.

Desde a #9 o turno também carrega o `historico` da conversa: ele chega pronto,
lido pelo `webhook`, e o grafo não sabe de onde veio nem de onde ele foi lido. É o
grafo não fazer I/O que deixou a #10 ser uma troca de texto: a persona e o
histórico entram pela mesma função, e nada mais no grafo mudou.
"""

from __future__ import annotations

import logging
from typing import Callable, NotRequired, TypedDict

from sau.graph.state import Mensagem
from sau.inference.ollama import MOTIVO_PARADA_NO_LIMITE, ClienteOllama, Resposta
from sau.persona import montar_prompt as montar_prompt

logger = logging.getLogger("sau.graph.nodes")


class EstadoTurno(TypedDict):
    """O estado de um turno: o que entra e a resposta que sai.

    `historico` é por conversa e `mensagem` é por turno, e as duas coisas coexistem
    porque o turno não é a conversa: ele é uma fatia dela. O `historico` é `NotRequired`
    pelo mesmo motivo que a `resposta` — antes da #9 o estado era só a mensagem, e um
    grafo que exigisse o histórico quebraria todo chamador antigo. Quem chama hoje
    sempre passa o histórico, e quem não passar recebe o turno sem memória nenhuma,
    que é o comportamento antigo.
    """

    mensagem: str
    historico: NotRequired[list[Mensagem]]
    resposta: NotRequired[str]


def criar_no_responder(cliente: ClienteOllama) -> Callable[[EstadoTurno], dict[str, str]]:
    """Cria o nó `responder`, que leva o turno ao modelo e devolve o texto.

    O cliente é injetado para que o grafo não saiba onde o modelo roda: em
    serviço é o `ClienteOllama` que alcança o Ollama do host (ADR-0002), e nos
    testes é o mesmo cliente com um transporte falso.

    Aqui entra no log só o **prompt**. O texto do modelo já sai em dois outros
    lugares, e nenhum deles é este: o `ClienteOllama` grava a resposta com os
    tempos que a mediram, e o `grafo` grava a entrada e a saída do turno.

    O prompt montado é a única coisa do caminho que nenhum outro registro
    guarda. As partes dele são legíveis onde estão — as regras, em
    `sau/persona.py`, e a conversa do Aluno, na entrada do grafo e no registro de
    `sau/graph/state.py` — mas a composição das duas, que é o texto exato enviado
    para o modelo, só existe aqui. É essa composição que o log torna auditável, e
    é por isso que ele fica registrado aqui.

    O `historico` vem do estado com `get`, e não com `[]`: um estado sem ele é um
    turno sem memória, e a memória ausente é um slice vazio, não um `KeyError` no
    meio da conversa do Aluno.

    O nó não olha o texto da resposta, e o motivo pelo limite é um: o corte de
    geração é o defeito que não se vê no turno. O Ollama fecha a geração como
    bem-sucedida (`MOTIVO_PARADA_NO_LIMITE`), o grafo devolve o texto cortado
    como se fosse a resposta, e o Aluno lê uma frase que termina no meio. Sem
    esta linha o corte sai do log do cliente — que grava o `parada` — e só como
    palavra, para quem for procurar. Aqui ele vira `WARNING`, que é o nível que
    aparece sem ninguém pedir.
    """

    def responder(estado: EstadoTurno) -> dict[str, str]:
        prompt = montar_prompt(estado["mensagem"], estado.get("historico", ()))
        logger.info("Prompt do turno enviado ao modelo:\n%s", prompt)
        resposta: Resposta = cliente.responder(prompt)
        if resposta.motivo_de_parada == MOTIVO_PARADA_NO_LIMITE:
            logger.warning(
                "A geração parou por falta de espaço e saiu cortada: o Aluno "
                "recebeu uma resposta incompleta, e nenhuma falha foi lançada. "
                "Motivo informado: %s.",
                resposta.motivo_de_parada,
            )
        return {"resposta": resposta.texto}

    return responder
