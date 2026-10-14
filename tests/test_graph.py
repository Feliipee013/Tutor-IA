"""Testes do grafo do turno, `sau/graph/`.

O que se prova aqui é o grafo do ADR-0010: o ciclo `agente → ferramentas →
agente` com a ferramenta opcional, a costura do prompt, a guarda determinística
de ausência de evidência e a entrada e a saída no log.

O transporte do modelo é um `httpx.MockTransport`, o mesmo tipo que
`test_ollama.py` usa, e o corpo de `/api/chat` é reescrito aqui em vez de
importado: cada arquivo de teste declara o contrato que ele precisa, e ninguém
depende do texto de outro. O que não é reescrito é o resto — o grafo roda sobre
o `ClienteOllama` de verdade, e só o Ollama do host é falso. Um S.A.U. falso
aqui passaria com o grafo desconectado do cliente, que é o defeito que a #8 tem
que fechar.

A busca no Manual é falsa por `monkeypatch`, e não por Chroma de verdade: o
índice persistente e o limiar têm testes próprios em `test_tool_manual.py`, e o
que este arquivo mede é o que o grafo faz com o que a ferramenta devolveu —
inclusive quando devolveu nada.
"""

from __future__ import annotations

import inspect
import json
import logging
from pathlib import Path
from typing import Any, Callable, Iterator

import httpx
import pytest

from harness.run import sha256_do_prompt
from sau.graph.graph import TEXTO_AUSENCIA, construir_grafo, executar_turno
from sau.graph.nodes import LIMITE_DE_RODADAS, EstadoTurno, OpcoesDoManual, rota_das_ferramentas
from sau.inference.ollama import (
    MOTIVO_PARADA_NO_LIMITE,
    ChamadaDeFerramenta,
    ClienteOllama,
    ErroDeInferencia,
)
from sau.manual.indice import TrechoDoManual
from sau.manual.tool import LITERAL_NAO_ENCONTREI
from sau.persona import PERSONA, montar_prompt

_BASE_URL = "http://host.docker.internal:11434"
_MODELO = "qwen2.5:3b"

# Uma Pergunta Frequente de prazo, e não um pedido de Atividade. O `CONTEXT.md`
# separa os dois conceitos e diz que um é o outro pelo motivo: "perguntar quando
# um documento vence não é pedir a Atividade". A frase da Aluna cita o prazo sem
# nomear a Atividade, que é a forma como o `CONTEXT.md` diz que a dúvida é
# rotineira — e é a única resposta aceitável do modelo, porque um prazo é dado
# que ele não tem e não pode inventar.
_MENSAGEM = "até que dia eu preciso entregar?"
_RESPOSTA = "Esse prazo eu não sei."
_RESPOSTA_COM_FONTE = "O relatório é entregue até a segunda sexta-feira (Fonte: Prazos, p. 1)."

# O vetor que o embedding falso devolve para todo texto. Só é usado quando o
# teste deixa a busca real acontecer; a maioria falsifica a busca inteira.
_VETOR_FALSO = [1.0, 0.0]

_TRECHO = TrechoDoManual(
    titulo="Prazos do Estágio",
    pagina=1,
    texto="O relatório de atividades é entregue até a segunda sexta-feira.",
    fonte="Prazos do Estágio (p. 1)",
    pontuacao=0.9,
)

FabricaCliente = Callable[[Any], ClienteOllama]


def _chat_com_texto(texto: str) -> dict[str, Any]:
    """O que o Ollama devolve no `/api/chat` quando o modelo responde direto."""
    return {
        "model": _MODELO,
        "message": {"role": "assistant", "content": texto},
        "done": True,
        "done_reason": "stop",
        "load_duration": 400_000_000,
        "prompt_eval_duration": 100_000_000,
        "eval_duration": 1_000_000_000,
        "eval_count": 50,
    }


def _chat_com_chamada(*, consulta: str, k: int | None = None) -> dict[str, Any]:
    """O que o Ollama devolve quando o modelo pede a ferramenta."""
    argumentos: dict[str, Any] = {"consulta": consulta}
    if k is not None:
        argumentos["k"] = k
    return {
        "model": _MODELO,
        "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"function": {"name": "buscar_no_manual", "arguments": argumentos}}],
        },
        "done": True,
        "done_reason": "stop",
    }


def _resposta_embed(request: httpx.Request) -> httpx.Response:
    """O que o Ollama devolve no `/api/embed`: um vetor falso por texto de entrada."""
    corpo = json.loads(request.content.decode("utf-8"))
    total = len(corpo["input"])
    return httpx.Response(200, json={"embeddings": [_VETOR_FALSO for _ in range(total)]})


def _e_rota_de_embed(request: httpx.Request) -> bool:
    return request.url.path.endswith("/api/embed")


def _roteiro(passos: list[dict[str, Any]], chats: list[dict[str, Any]]) -> Any:
    """Transporte que responde um roteiro de rodadas ao modelo.

    Cada item de `passos` é o `dict` de `/api/chat` que o modelo devolve naquela
    rodada; quando o roteiro acaba, o handler segue devolvendo a resposta
    direta, para os testes que não precisam numerar todos os passos. `chats`
    recebe cada corpo de `/api/chat` recebido, para os testes que conferem o que
    o grafo mandou — as mensagens `tool`, por exemplo.
    """

    pendentes = list(passos)

    def handler(request: httpx.Request) -> httpx.Response:
        if _e_rota_de_embed(request):
            return _resposta_embed(request)
        chats.append(json.loads(request.content.decode("utf-8")))
        if not pendentes:
            return httpx.Response(200, json=_chat_com_texto(_RESPOSTA))
        return httpx.Response(200, json=pendentes.pop(0))

    return handler


@pytest.fixture
def fazer_cliente() -> Iterator[FabricaCliente]:
    """Fabrica um `ClienteOllama` de verdade com o transporte do host falso.

    O cliente vive enquanto o teste, e o grafo o recebe pronto: o grafo não sabe
    de onde o modelo vem, e esta é a forma de provar isso sem abrir exceção.
    """
    abertos: list[httpx.Client] = []

    def fabricar(handler: Any) -> ClienteOllama:
        cliente_http = httpx.Client(transport=httpx.MockTransport(handler))
        abertos.append(cliente_http)
        return ClienteOllama(_BASE_URL, _MODELO, client=cliente_http)

    yield fabricar
    for cliente_http in abertos:
        cliente_http.close()


@pytest.fixture
def buscar_falsa(monkeypatch: pytest.MonkeyPatch) -> list[list[TrechoDoManual]]:
    """Falsifica a busca no índice e devolve a lista de retornos, por chamada.

    O `buscar_no_manual` real lê o Chroma; aqui o que se quer é controlar o que
    a ferramenta devolve — trecho válido, lista vazia —, e o índice de verdade
    não acrescenta nada a essa afirmação. A lista de retornos é consumida na
    ordem; quando acaba, devolve vazio.
    """
    retornos: list[list[TrechoDoManual]] = []

    def buscar_falsa_no_indice(**_: Any) -> list[TrechoDoManual]:
        if retornos:
            return retornos.pop(0)
        return []

    monkeypatch.setattr("sau.manual.tool.buscar_no_indice", buscar_falsa_no_indice)
    return retornos


def _manual() -> OpcoesDoManual:
    """As opções de Manual para os testes: caminho e coleção não são tocados."""
    return OpcoesDoManual(
        diretorio_chroma=Path("/nao-usado/chroma"),
        nome_colecao="manual-teste",
        k_padrao=4,
        limiar=0.35,
    )


# --- Topologia: o ciclo do agente, com a ferramenta opcional ---


def test_grafo_tem_o_ciclo_do_agente_com_ferramenta(fazer_cliente: FabricaCliente) -> None:
    """Com Manual, o grafo tem `agente`, `ferramentas` e `finalizar`.

    A topologia é o critério de aceitação do grafo, e ela é afirmada pela visão
    que o LangGraph monta do grafo compilado — não pelo código que a construiu,
    que é a mesma coisa que se verificaria escrevendo o mesmo grafo de novo. É o
    ciclo do ADR-0010: o agente decide, a ferramenta executa quando chamada, e o
    finalizar encerra com a guarda de ausência.
    """
    visao = construir_grafo(fazer_cliente(_roteiro([], [])), manual=_manual()).get_graph()

    assert sorted(visao.nodes) == ["__end__", "__start__", "agente", "ferramentas", "finalizar"]
    arestas = {(aresta.source, aresta.target) for aresta in visao.edges}
    assert ("__start__", "agente") in arestas
    assert ("ferramentas", "agente") in arestas
    assert ("finalizar", "__end__") in arestas


def test_grafo_sem_manual_nao_tem_no_de_ferramenta(fazer_cliente: FabricaCliente) -> None:
    """Sem Manual, o agente conversa sem ferramenta e o ciclo nunca abre.

    É o modo dos testes de persona: o prompt é medido sem que o índice entre no
    caminho. Um nó `ferramentas` aqui seria um caminho que nunca é percorrido.
    """
    visao = construir_grafo(fazer_cliente(_roteiro([], []))).get_graph()

    assert sorted(visao.nodes) == ["__end__", "__start__", "agente", "finalizar"]
    arestas = {(aresta.source, aresta.target) for aresta in visao.edges}
    assert ("agente", "finalizar") in arestas


def test_assinatura_do_turno_e_do_grafo_recebem_o_manual() -> None:
    """`executar_turno` e `construir_grafo` recebem o Manual por parâmetro.

    O grafo não lê o ambiente sozinho: quem monta o turno passa as opções — o
    `webhook` a partir da `Configuracao`, o harness a partir da dele, o teste
    com as suas. Um `manual` lido de dentro do módulo seria uma segunda fonte
    para o mesmo caminho.
    """
    assert list(inspect.signature(executar_turno).parameters) == [
        "cliente",
        "mensagem",
        "historico",
        "manual",
    ]
    assert list(inspect.signature(construir_grafo).parameters) == ["cliente", "manual"]
    para_turno = inspect.signature(executar_turno).parameters["manual"]
    para_grafo = inspect.signature(construir_grafo).parameters["manual"]
    assert para_turno.kind is inspect.Parameter.KEYWORD_ONLY
    assert para_grafo.kind is inspect.Parameter.KEYWORD_ONLY


def test_rota_das_ferramentas_so_abre_o_ciclo_com_chamada_pendente() -> None:
    """A aresta condicional só volta à ferramenta com chamada pendente e rodada livre.

    Sem chamada, o turno encerra — resposta direta do modelo. No teto de
    rodadas, encerra com o que o modelo já escreveu em vez de girar para
    sempre: é a trava contra o laço infinito de um modelo que peça a ferramenta
    sem parar.
    """
    assert rota_das_ferramentas({"mensagem": _MENSAGEM, "pendentes": []}) == "finalizar"
    chamada = ChamadaDeFerramenta(nome="buscar_no_manual", argumentos={})
    com_chamada: EstadoTurno = {"mensagem": _MENSAGEM, "pendentes": [chamada], "rodadas": 1}
    assert rota_das_ferramentas(com_chamada) == "ferramentas"
    no_teto: EstadoTurno = {
        "mensagem": _MENSAGEM,
        "pendentes": [chamada],
        "rodadas": LIMITE_DE_RODADAS,
    }
    assert rota_das_ferramentas(no_teto) == "finalizar"


# --- O que o grafo devolve, com e sem ferramenta ---


def test_turno_devolve_o_texto_do_modelo(fazer_cliente: FabricaCliente) -> None:
    """Resposta direta do modelo — saudação, cortesia — sai como veio."""
    handler = _roteiro([_chat_com_texto(_RESPOSTA)], [])

    assert executar_turno(fazer_cliente(handler), _MENSAGEM) == _RESPOSTA


def test_turno_com_ferramenta_executa_e_volta_ao_modelo(
    fazer_cliente: FabricaCliente, buscar_falsa: list[list[TrechoDoManual]]
) -> None:
    """O modelo pede a ferramenta, o grafo executa e o modelo responde de novo.

    É o caminho do ADR-0010: a resposta factual sai da segunda rodada, e não da
    primeira. A primeira mensagem ao modelo é o prompt do turno; a segunda
    carrega o resultado da ferramenta como mensagem `tool`, com a Fonte que o
    modelo cita. Sem esta mensagem, a segunda rodada responderia sem material.
    """
    buscar_falsa.append([_TRECHO])
    chats: list[dict[str, Any]] = []
    passos = [_chat_com_chamada(consulta="prazo de entrega"), _chat_com_texto(_RESPOSTA_COM_FONTE)]
    handler = _roteiro(passos, chats)

    resposta = executar_turno(fazer_cliente(handler), _MENSAGEM, manual=_manual())

    assert resposta == _RESPOSTA_COM_FONTE
    assert len(chats) == 2
    mensagens = chats[1]["messages"]
    assert mensagens[0]["role"] == "user"
    assert mensagens[-1]["role"] == "tool"
    assert mensagens[-1]["tool_name"] == "buscar_no_manual"
    assert _TRECHO.fonte in mensagens[-1]["content"]
    # O schema da ferramenta vai declarado ao modelo em toda rodada.
    assert chats[0]["tools"][0]["function"]["name"] == "buscar_no_manual"


def test_turno_sem_ferramenta_chama_o_modelo_uma_vez_so(fazer_cliente: FabricaCliente) -> None:
    """Uma resposta direta é uma rodada só: o ciclo não abre sem chamada.

    Uma segunda chamada de geração no mesmo turno passaria pela topologia e
    sairia daqui.
    """
    chats: list[dict[str, Any]] = []
    handler = _roteiro([_chat_com_texto(_RESPOSTA)], chats)

    executar_turno(fazer_cliente(handler), _MENSAGEM, manual=_manual())

    assert len(chats) == 1


def test_a_ferramenta_sem_evidencia_vira_o_literal_de_ausencia(
    fazer_cliente: FabricaCliente, buscar_falsa: list[list[TrechoDoManual]]
) -> None:
    """Chamou a ferramenta e nada passou pelo limiar: resposta é o literal.

    O modelo pode ter respondido qualquer coisa na segunda rodada; a guarda do
    `finalizar` troca pelo texto do grafo. É o critério do ADR-0012 que não
    depende de o modelo obedecer ao prompt.
    """
    buscar_falsa.append([])  # A busca não devolve trecho algum.
    chats: list[dict[str, Any]] = []
    passos = [_chat_com_chamada(consulta="prazo de entrega"), _chat_com_texto("resposta inventada")]
    handler = _roteiro(passos, chats)

    resposta = executar_turno(fazer_cliente(handler), _MENSAGEM, manual=_manual())

    assert resposta == TEXTO_AUSENCIA
    assert LITERAL_NAO_ENCONTREI in resposta
    assert "Coordenação de Estágios" in resposta


def test_a_guarda_nao_dispara_quando_nao_houve_ferramenta(fazer_cliente: FabricaCliente) -> None:
    """Sem chamada à ferramenta, a resposta do modelo passa intacta.

    Saudação e cortesia não buscam nada; não há ausência de evidência a
    declarar, e trocar a resposta pelo literal seria responder o que o Aluno não
    perguntou.
    """
    handler = _roteiro([_chat_com_texto(_RESPOSTA)], [])

    assert executar_turno(fazer_cliente(handler), _MENSAGEM, manual=_manual()) == _RESPOSTA


def test_o_teto_de_rodadas_encerra_o_ciclo(
    fazer_cliente: FabricaCliente, buscar_falsa: list[list[TrechoDoManual]]
) -> None:
    """Um modelo que pede a ferramenta para sempre não trava o turno.

    O teto encerra em `LIMITE_DE_RODADAS` rodadas; sem ele, o ciclo `agente →
    ferramentas` giraria indefinidamente. A busca devolve trecho válido para a
    guarda de ausência não disparar e a resposta ser o texto do modelo.
    """
    buscar_falsa.extend([[_TRECHO] for _ in range(LIMITE_DE_RODADAS)])
    chats: list[dict[str, Any]] = []
    passos = [_chat_com_chamada(consulta="prazo") for _ in range(LIMITE_DE_RODADAS + 2)]
    handler = _roteiro(passos, chats)

    executar_turno(fazer_cliente(handler), _MENSAGEM, manual=_manual())

    assert len(chats) == LIMITE_DE_RODADAS


# --- A costura do prompt, que é onde a persona do S.A.U. entra ---


def test_o_prompt_que_chega_ao_modelo_e_o_montar_prompt(fazer_cliente: FabricaCliente) -> None:
    """`montar_prompt` é o caminho único do prompt até o modelo.

    O `montar_prompt` deste módulo não é um: é o de `sau.persona`, reexportado em
    `nodes.py` com `from sau.persona import montar_prompt as montar_prompt`. É por
    isso que a afirmação é esta e não "o prompt contém a persona": ela compara o
    texto que o grafo mandou com a função que mora no módulo da persona, e uma
    persona que tivesse entrado por outro caminho — um segundo prompt montado
    dentro do grafo — deixaria as duas pontas diferentes sem que nenhum teste de
    conteúdo notasse. Quem afirma o conteúdo da persona é o `test_persona.py`.
    """
    chats: list[dict[str, Any]] = []
    handler = _roteiro([_chat_com_texto(_RESPOSTA)], chats)

    executar_turno(fazer_cliente(handler), _MENSAGEM)

    assert chats[0]["messages"][0]["content"] == montar_prompt(_MENSAGEM)


def test_mensagem_do_aluno_chega_ao_modelo_verbatim(fazer_cliente: FabricaCliente) -> None:
    """A mensagem do Aluno chega ao modelo como ele a escreveu.

    Sem esta afirmação, um grafo que mandasse o prompt fixo e ignorasse a
    mensagem passaria por `test_turno_devolve_o_texto_do_modelo`: o texto do
    modelo voltaria igual, vindo de uma pergunta que o Aluno nunca fez.
    """
    chats: list[dict[str, Any]] = []
    handler = _roteiro([_chat_com_texto(_RESPOSTA)], chats)

    executar_turno(fazer_cliente(handler), _MENSAGEM)

    assert _MENSAGEM in chats[0]["messages"][0]["content"]


def test_as_fontes_do_turno_vem_da_ferramenta(
    fazer_cliente: FabricaCliente, buscar_falsa: list[list[TrechoDoManual]]
) -> None:
    """O estado do turno carrega as Fontes que a ferramenta entregou.

    É o que o harness lê para gravar a rodada: com a busca falsificada, a Fonte
    que aparece em `fontes` é a que a ferramenta devolveu, e não um título
    inventado.
    """
    buscar_falsa.append([_TRECHO])
    chats: list[dict[str, Any]] = []
    passos = [_chat_com_chamada(consulta="prazo"), _chat_com_texto(_RESPOSTA_COM_FONTE)]
    grafo = construir_grafo(fazer_cliente(_roteiro(passos, chats)), manual=_manual())

    entrada: EstadoTurno = {
        "mensagem": _MENSAGEM,
        "mensagens": [{"role": "user", "content": montar_prompt(_MENSAGEM)}],
        "rodadas": 0,
    }
    estado = grafo.invoke(entrada)

    assert estado["fontes"] == [_TRECHO.fonte]
    assert estado["houve_ferramenta"] is True
    assert estado["houve_evidencia"] is True


# --- O Encaminhamento determinístico mora no grafo e não na persona ---


def test_o_texto_de_ausencia_nao_mora_na_persona() -> None:
    """O literal de ausência vive no grafo, e o `sha256` do prompt não muda com a topologia.

    É a separação que o ADR-0008 pede: o hash reporta a persona, e mudar o
    encerramento — ou somar nó — não muda o hash. Se este texto entrar na
    persona, a rodada passa a declarar mudança de persona onde houve mudança de
    topologia, e o `sha256_do_prompt` deixa de identificar o que ele promete.
    """
    assert TEXTO_AUSENCIA not in PERSONA
    assert sha256_do_prompt()


# --- Log: a entrada, o prompt e a saída ficam registrados ---


def test_entrada_e_saida_do_turno_ficam_no_log(
    fazer_cliente: FabricaCliente, caplog: pytest.LogCaptureFixture
) -> None:
    """A entrada e a saída do grafo saem no log, em loggers distintos.

    A entrada e a saída ficam no logger do grafo (`sau.graph.graph`), que é o
    que a #8 pede. A montagem do prompt fica no logger dos nós
    (`sau.graph.nodes`): a primeira é o registro do turno, e a segunda é a
    evidência do que foi enviado ao modelo.
    """
    handler = _roteiro([_chat_com_texto(_RESPOSTA)], [])

    with caplog.at_level(logging.INFO):
        executar_turno(fazer_cliente(handler), _MENSAGEM)

    registros = caplog.records
    assert any(
        _MENSAGEM in registro.getMessage() and registro.name == "sau.graph.graph"
        for registro in registros
    )
    assert any(
        _RESPOSTA in registro.getMessage() and registro.name == "sau.graph.graph"
        for registro in registros
    )
    assert any(registro.name == "sau.graph.nodes" for registro in registros)


def test_turno_cortado_por_limite_de_contexto_e_avisado(
    fazer_cliente: FabricaCliente, caplog: pytest.LogCaptureFixture
) -> None:
    """A geração que pára por falta de espaço vira aviso no log do turno.

    O Ollama devolve `done_reason=length` quando o `num_ctx` acaba, e a resposta
    sai cortada sem que o cliente levante erro. Sem este aviso, um Aluno
    receberia meia resposta sem que ninguém soubesse.
    """
    payload = _chat_com_texto(_RESPOSTA)
    payload["done_reason"] = MOTIVO_PARADA_NO_LIMITE
    handler = _roteiro([payload], [])

    with caplog.at_level(logging.WARNING):
        executar_turno(fazer_cliente(handler), _MENSAGEM)

    assert any("cortada" in registro.getMessage() for registro in caplog.records)


# --- Falha do modelo propaga, e não vira Encaminhamento silencioso ---


def test_erro_de_inferencia_propaga(fazer_cliente: FabricaCliente) -> None:
    """O Ollama fora do ar levanta, e não devolve Encaminhamento mudo.

    A falha do instrumento é outra coisa da ausência de material: quem trata a
    primeira é o `webhook`, com a mensagem de falha que ele já tem. Engolir o
    erro aqui e devolver o Encaminhamento diria ao Aluno que o material não tem
    a resposta quando o material nem foi consultado.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if _e_rota_de_embed(request):
            return _resposta_embed(request)
        return httpx.Response(500, json={"error": "model not found"})

    with pytest.raises(ErroDeInferencia):
        executar_turno(fazer_cliente(handler), _MENSAGEM, manual=_manual())
