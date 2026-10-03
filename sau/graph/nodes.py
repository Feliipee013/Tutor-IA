"""Nós do grafo de resposta do turno do S.A.U.

Dois nós, um caminho só: `recuperar` busca no Corpus os trechos que sustentam
a resposta, e `responder` leva o turno ao modelo com esse material. A
recuperação roda em todo turno, sem classificação de intenção e sem aresta
condicional ([ADR-0008](../../docs/adr/0008-recuperacao-sem-classificacao-de-intencao.md)).

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
from pathlib import Path
from typing import Any, Callable, NotRequired, TypedDict

from sau.graph.state import Mensagem
from sau.inference.ollama import MOTIVO_PARADA_NO_LIMITE, ClienteOllama, Resposta
from sau.persona import montar_prompt as montar_prompt
from sau.rag.retrieve import K_PADRAO, Indice, TrechoRecuperado, buscar, montar_indice

logger = logging.getLogger("sau.graph.nodes")

_INDICES: dict[tuple[str, str], Indice] = {}
"""O índice por (diretório do Corpus, modelo de embedding), além dos turnos.

O grafo é remontado a cada turno (`construir_grafo` em `graph.py`), então um
fecho por grafo morreria no fim do turno e o Corpus seria reembutido toda
vez — uma chamada `/api/embed` com as seções inteiras por pergunta do Aluno.
O cache em módulo mantém "montado na primeira vez" de verdade entre turnos e
entre clientes recriados (o `webhook` monta um `ClienteOllama` novo por turno),
sem parâmetro novo no grafo: a chave é o que identifica o material, e não
quem o pediu. Corpus em disco muda com rebuild/restart, que é quando o
processo nasce e o cache nasce vazio junto.
"""


def limpar_cache_recuperacao() -> None:
    """Esvazia o cache do índice da recuperação, para os testes.

    Sem isto, turnos de testes diferentes no mesmo processo reaproveitariam o
    índice do primeiro, e o teste que conta as chamadas de embedding contaria
    o turno errado. Produção nunca chama isto: lá o cache vive enquanto o
    processo.
    """
    _INDICES.clear()


DIRETORIO_CORPUS_PADRAO = Path(__file__).resolve().parent.parent.parent / "corpus"
"""O Corpus versionado de onde o índice é montado: a fonte, nunca um artefato."""


class EstadoTurno(TypedDict):
    """O estado de um turno: o que entra, o material recuperado e a resposta que sai.

    `historico` é por conversa e `mensagem` é por turno, e as duas coisas coexistem
    porque o turno não é a conversa: ele é uma fatia dela. O `historico` é `NotRequired`
    pelo mesmo motivo que a `resposta` — antes da #9 o estado era só a mensagem, e um
    grafo que exigisse o histórico quebraria todo chamador antigo. Quem chama hoje
    sempre passa o histórico, e quem não passar recebe o turno sem memória nenhuma,
    que é o comportamento antigo.

    `contexto` e `fontes` são o que a recuperação encontrou: os trechos que
    sustentam a resposta e os títulos que o S.A.U. cita como Fonte. Vazio é
    recuperação desligada — índice que não montou, embedding que falhou — e é
    o que o `responder` lê para encerrar com o Encaminhamento determinístico
    em vez de levar ao modelo uma pergunta sem material.
    """

    mensagem: str
    historico: NotRequired[list[Mensagem]]
    contexto: NotRequired[list[TrechoRecuperado]]
    fontes: NotRequired[list[str]]
    resposta: NotRequired[str]


def criar_no_recuperar(
    cliente: ClienteOllama, diretorio: Path = DIRETORIO_CORPUS_PADRAO
) -> Callable[[EstadoTurno], dict[str, Any]]:
    """Cria o nó `recuperar`, que busca no Corpus os trechos do turno.

    O cliente é o mesmo da geração: ele carrega o embedding junto, e por isso
    a recuperação entra sem parâmetro novo no grafo. O índice é montado na
    primeira vez e guardado no cache do módulo por (diretório, modelo de
    embedding) — e não no fecho do nó, que morreria com o grafo remontado a
    cada turno — para que o grafo continue autossuficiente: montado da fonte
    versionada, nunca de artefato em disco, e embutido uma vez por processo.

    Quando a recuperação falha — índice que não monta, embedding que não
    responde — o nó degrada para contexto vazio em vez de derrubar o turno:
    sem material não há o que responder, e quem encerra com forma é o
    `responder`, com o texto determinístico do grafo.
    """

    def recuperar(estado: EstadoTurno) -> dict[str, Any]:
        try:
            chave = (str(diretorio), cliente.modelo_embedding)
            indice = _INDICES.get(chave)
            if indice is None:
                indice = montar_indice(diretorio, cliente)
                _INDICES[chave] = indice
            (vetor_consulta,) = cliente.embutir([estado["mensagem"]])
            trechos = buscar(indice, vetor_consulta, k=K_PADRAO)
        except Exception as exc:
            # A exceção larga aqui é deliberada: recuperação que derruba turno
            # transforma falta de material em falha do instrumento, e o Aluno
            # receberia a mensagem amigável de erro em vez do Encaminhamento.
            # O motivo vai no log para que a causa seja legível depois.
            logger.warning(
                "A recuperação falhou e o turno segue sem material: %s: %s. "
                "O Aluno recebe o Encaminhamento determinístico do grafo.",
                type(exc).__name__,
                exc,
            )
            return {"contexto": [], "fontes": []}
        return {"contexto": trechos, "fontes": [trecho.titulo for trecho in trechos]}

    return recuperar


def criar_no_responder(
    cliente: ClienteOllama, *, texto_encaminhamento: str
) -> Callable[[EstadoTurno], dict[str, str]]:
    """Cria o nó `responder`, que leva o turno ao modelo e devolve o texto.

    O cliente é injetado para que o grafo não saiba onde o modelo roda: em
    serviço é o `ClienteOllama` que alcança o Ollama do host (ADR-0002), e nos
    testes é o mesmo cliente com um transporte falso.

    `texto_encaminhamento` é o Encaminhamento determinístico do grafo: sem
    material recuperado não há o que responder, e o nó devolve esse texto sem
    chamar o modelo. Ele mora no grafo — e não na persona — para que o
    `sha256_do_prompt` continue reportando a persona e não a topologia.

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
        if not estado.get("contexto"):
            return {"resposta": texto_encaminhamento}
        prompt = montar_prompt(
            estado["mensagem"], estado.get("historico", ()), estado.get("contexto", ())
        )
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
