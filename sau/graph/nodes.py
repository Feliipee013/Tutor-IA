"""Nós do grafo de resposta do turno do S.A.U.

Um nó, por enquanto: `responder` leva a mensagem do Aluno ao modelo e devolve o
texto. O grafo tem um único caminho (issue #8) — a classificação de intenção, a
recuperação da 1.2 e o encaminhamento entram como nós e arestas novos aqui
dentro, não como serviço à parte.

Desde a #9 o turno também carrega o `historico` da conversa: ele chega pronto,
lido pelo `webhook`, e o grafo não sabe de onde veio nem de onde ele foi lido. É o
grafo não fazer I/O que mantém a persona (#10) como troca de texto — ela entra
reescrevendo `montar_prompt`, e nada mais muda.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Callable, NotRequired, TypedDict

from sau.graph.state import Mensagem
from sau.inference.ollama import ClienteOllama, Resposta

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


MENSAGENS_NO_PROMPT = 6
"""Quantas mensagens do histórico vão no prompt: três trocas.

Seis é o que cabe no `num_ctx` de 2048 do cliente (`NUM_CTX_PADRAO`) sem apertar a
janela, e três trocas é o mínimo de contexto para a pergunta "e aquela outra
coisa?" fazer sentido. O histórico continua gravado inteiro, limitado pelo
`MAXIMO_DE_MENSAGENS` do registro — o recorte é do prompt, não da memória.
"""

PROMPT_SEM_PERSONA = "Responda à mensagem do Aluno:\n\n{historico}{mensagem}"
"""O corpo do prompt do turno, ainda sem persona.

A #10 substitui este texto pelo prompt versionado do S.A.U. (tom, regras de
comportamento, o que recusar). Até lá, o modelo recebe a conversa com a instrução
mínima de continuar — nada de tom ou de regra aqui, para que a troca da #10 seja uma
troca de texto e não uma reescrita do grafo.

O `{historico}` é o bloco já desenhado, com uma linha por mensagem e o nome de quem
falou. Ele vem no lugar de `{mensagem}` e não junto dela, para que a última fala do
Aluno seja a última linha do prompt — que é a ordem que o modelo lê.
"""


def montar_prompt(mensagem: str, historico: Sequence[Mensagem] = ()) -> str:
    """Monta o prompt do turno a partir da mensagem do Aluno e da conversa anterior.

    O histórico entra pelas linhas `Aluno:` e `S.A.U.:` de `Mensagem.como_linha`, e
    o corte nas `MENSAGENS_NO_PROMPT` mais recentes acontece aqui e não no registro: o
    registro guarda tudo, e quem decide o que cabe na janela é quem monta o prompt.
    Um histórico sem nada vira string vazia, e o prompt sem `{historico}` fica igual
    ao de antes da #9.

    É a costura da persona (#10): quem for injetar o prompt versionado troca esta
    função, e o grafo não precisa saber que o texto mudou. É por isso que ela recebe
    o histórico como argumento pronto, e não como uma conversa: a #10 troca o texto
    sem precisar saber de onde a conversa veio.
    """
    linhas = [mensagem.como_linha() for mensagem in list(historico)[-MENSAGENS_NO_PROMPT:]]
    bloco = "".join(f"{linha}\n\n" for linha in linhas)
    return PROMPT_SEM_PERSONA.format(historico=bloco, mensagem=mensagem)


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

    O `historico` vem do estado com `get`, e não com `[]`: um estado sem ele é um
    turno sem memória, e a memória ausente é um slice vazio, não um `KeyError` no
    meio da conversa do Aluno.
    """

    def responder(estado: EstadoTurno) -> dict[str, str]:
        prompt = montar_prompt(estado["mensagem"], estado.get("historico", ()))
        logger.info("Prompt do turno enviado ao modelo:\n%s", prompt)
        resposta: Resposta = cliente.responder(prompt)
        return {"resposta": resposta.texto}

    return responder
