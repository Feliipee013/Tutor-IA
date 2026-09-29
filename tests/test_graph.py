"""Testes do grafo do turno, sau/graph/.

O que se prova aqui é o grafo: a topologia de um caminho só, a costura do prompt,
a resposta do modelo saindo do grafo e a entrada e a saída no log.

O transporte do modelo é um `httpx.MockTransport`, o mesmo tipo que
`test_ollama.py` usa, e o corpo de `/api/generate` é reescrito aqui em vez de
importado: cada arquivo de teste declara o contrato que ele precisa, e ninguém
depende do texto de outro. O que não é reescrito é o resto — o grafo roda sobre
o `ClienteOllama` de verdade, e só o Ollama do host é falso. Um S.A.U. falso aqui
passaria com o grafo desconectado do cliente, que é o defeito que a #8 tem que
fechar.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Iterator

import httpx
import pytest

from sau.graph.graph import construir_grafo, executar_turno
from sau.graph.nodes import EstadoTurno, montar_prompt
from sau.inference.ollama import ClienteOllama, ErroDeInferencia

_BASE_URL = "http://host.docker.internal:11434"
_MODELO = "qwen2.5:3b"

# Uma Pergunta Frequente de prazo, e não um pedido de Atividade. O `CONTEXT.md`
# separa os dois conceitos e diz que um é o outro pelo motivo: "perguntar quando
# a entrega vence não é pedir a Atividade". A frase da Aluna cita o prazo sem
# nomear a Atividade, que é a forma como o `CONTEXT.md` diz que a dúvida é
# rotineira — e é a única resposta aceitável do modelo, porque um prazo é dado
# que ele não tem e não pode inventar.
_MENSAGEM = "até que dia eu preciso entregar?"
_RESPOSTA = "Esse prazo eu não sei."

LOGGER_GRAFO = "sau.graph.graph"
LOGGER_NOS = "sau.graph.nodes"

FabricaCliente = Callable[[Any], ClienteOllama]


def _payload(texto: str) -> dict[str, Any]:
    """O que o Ollama devolve numa geração completa, em nanossegundos."""
    return {
        "model": _MODELO,
        "response": texto,
        "done": True,
        "done_reason": "stop",
        "load_duration": 400_000_000,
        "prompt_eval_duration": 100_000_000,
        "eval_duration": 1_000_000_000,
        "eval_count": 50,
    }


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


def _responde(texto: str) -> Any:
    """Transporte que devolve uma geração completa com o texto dado."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_payload(texto))

    return handler


def _espelhando(registros: list[Any], campo: str | None = None) -> Any:
    """Transporte que guarda o que o grafo mandou ao modelo e devolve uma geração.

    Três testes precisam olhar o que saiu do grafo para o modelo — o corpo
    inteiro, o `prompt`, e o `prompt` conferido contra o `montar_prompt` — e os
    três precisam do mesmo par: espelhar o que foi pedido e responder uma geração.
    `campo` é o nome do que interessa guardar; sem ele, o corpo inteiro é
    guardado, porque `test_turno_chama_o_modelo_uma_vez_so` afirma duas coisas ao
    mesmo tempo sobre esse mesmo corpo.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        corpo = json.loads(request.content.decode("utf-8"))
        registros.append(corpo if campo is None else corpo[campo])
        return httpx.Response(200, json=_payload(_RESPOSTA))

    return handler


# --- Topologia: um caminho só, que é o que a #8 promete ---


def test_grafo_tem_um_caminho_so(fazer_cliente: FabricaCliente) -> None:
    """`START → responder → END`, e nenhum outro nó nem aresta.

    A topologia é o critério de aceitação do grafo, e ela é afirmada pela visão
    que o LangGraph monta do grafo compilado — não pelo código que a construiu,
    que é a mesma coisa que se verificaria escrevendo o mesmo grafo de novo.
    """
    visao = construir_grafo(fazer_cliente(_responde(_RESPOSTA))).get_graph()

    assert sorted(visao.nodes) == ["__end__", "__start__", "responder"]
    assert {(aresta.source, aresta.target) for aresta in visao.edges} == {
        ("__start__", "responder"),
        ("responder", "__end__"),
    }


def test_turno_chama_o_modelo_uma_vez_so(fazer_cliente: FabricaCliente) -> None:
    """Um caminho só na topologia e uma geração só na prática.

    A topologia do teste anterior é a estrutura; esta é o comportamento. Uma
    segunda chamada ao modelo no mesmo turno passaria pela topologia de um nó e
    sairia daqui.
    """
    corpos: list[dict[str, Any]] = []

    executar_turno(fazer_cliente(_espelhando(corpos)), _MENSAGEM)

    assert len(corpos) == 1
    assert corpos[0]["model"] == _MODELO
    assert corpos[0]["stream"] is False


# --- O que o grafo devolve ---


def test_turno_devolve_o_texto_do_modelo(fazer_cliente: FabricaCliente) -> None:
    assert executar_turno(fazer_cliente(_responde(_RESPOSTA)), _MENSAGEM) == _RESPOSTA


def test_mensagem_do_aluno_chega_ao_modelo_verbatim(fazer_cliente: FabricaCliente) -> None:
    """A mensagem do Aluno chega ao modelo como ele a escreveu.

    Sem esta afirmação, um grafo que mandasse o prompt fixo e ignorasse a
    mensagem passaria por `test_turno_devolve_o_texto_do_modelo`: o texto do
    modelo voltaria igual, vindo de uma pergunta que o Aluno nunca fez.
    """
    prompts: list[str] = []

    executar_turno(fazer_cliente(_espelhando(prompts, "prompt")), _MENSAGEM)

    assert len(prompts) == 1
    assert _MENSAGEM in prompts[0]


# --- A costura do prompt, que é onde a #10 entra ---


def test_o_prompt_que_chega_ao_modelo_e_o_montar_prompt(
    fazer_cliente: FabricaCliente,
) -> None:
    """`montar_prompt` é o caminho único do prompt até o modelo.

    É esta afirmação que torna a troca da #10 uma troca de texto: a persona
    entra reescrevendo `montar_prompt`, e nada mais no grafo muda. Um teste que
    só conferisse que a mensagem aparece no prompt passaria igual depois que a
    persona tivesse entrado por outro caminho.
    """
    prompts: list[str] = []

    executar_turno(fazer_cliente(_espelhando(prompts, "prompt")), _MENSAGEM)

    assert prompts == [montar_prompt(_MENSAGEM)]


def test_montar_prompt_carrega_a_mensagem_e_mais_nada(fazer_cliente: FabricaCliente) -> None:
    """Até a #10, o prompt é a instrução mínima com a mensagem do Aluno dentro.

    A persona é a #10, e ela entra por aqui. Affirmar que o prompt hoje é esse
    texto simples é o que torna a chegada dela visível: um teste que só pedisse
    que a mensagem estivesse no prompt continuaria verde com a persona dentro, e
    a troca de comportamento passaria sem ninguém notar.
    """
    prompt = montar_prompt(_MENSAGEM)

    assert _MENSAGEM in prompt
    # Não é a mensagem crua: existe uma instrução, e é ela que a #10 substitui.
    assert prompt != _MENSAGEM


def test_o_grafo_entra_somente_com_a_mensagem_e_devolve_os_dois_campos(
    fazer_cliente: FabricaCliente,
) -> None:
    """O grafo entra com a mensagem do Aluno e devolve mensagem e resposta.

    É o que o `NotRequired` em `resposta` compra: sem ele, o estado de entrada
    seria obrigado a carregar uma resposta que ainda não existe, e o `invoke` com
    um estado só de entrada não teria como ser escrito. A afirmação aqui é por
    execução, e não por `__annotations__` — que vira string assim que existe um
    `from __future__ import annotations` no módulo, e passaria a testar o
    `from`, não o estado.
    """
    grafo = construir_grafo(fazer_cliente(_responde(_RESPOSTA)))

    entrada: EstadoTurno = {"mensagem": _MENSAGEM}
    estado = grafo.invoke(entrada)

    assert estado == {"mensagem": _MENSAGEM, "resposta": _RESPOSTA}


# --- A entrada e a saída no log, que é o outro critério ---


def test_entrada_e_saida_do_grafo_vao_no_log(
    fazer_cliente: FabricaCliente, caplog: pytest.LogCaptureFixture
) -> None:
    """A mensagem que entra e a resposta que sai estão no log do grafo.

    Sem isso, uma conversa não é reconstruível depois do fato: o operador tem o
    update bruto do Telegram, mas não tem o que o S.A.U. respondeu.
    """
    with caplog.at_level(logging.INFO):
        executar_turno(fazer_cliente(_responde(_RESPOSTA)), _MENSAGEM)

    registros = [r.getMessage() for r in caplog.records if r.name == LOGGER_GRAFO]
    assert any(_MENSAGEM in mensagem for mensagem in registros), (
        f"a mensagem do Aluno não foi registrada na entrada do grafo: {registros}"
    )
    assert any(_RESPOSTA in mensagem for mensagem in registros), (
        f"a resposta do modelo não foi registrada na saída do grafo: {registros}"
    )


def test_o_no_registra_o_prompt_que_manda_ao_modelo(
    fazer_cliente: FabricaCliente, caplog: pytest.LogCaptureFixture
) -> None:
    """O nó registra o prompt que ele monta, que é o registro mais perto do modelo.

    É o que separa "o grafo rodou" de "o grafo rodou com o prompt certo", e o que
    vai deixar de ser a mensagem crua do Aluno quando a #10 trouxer a persona.

    A resposta do modelo **não** é registrada aqui, e a ausência é o ponto: ela
    já sai do `ClienteOllama` com os tempos que a mediram e da saída do grafo, e
    uma terceira cópia no meio do caminho só fazia o log do turno ter o mesmo
    texto três vezes. Assertar que ela **não** aparece é o que segura essa
    decisão: um nó que volta a logar a resposta deixa o teste vermelho.
    """
    with caplog.at_level(logging.INFO):
        executar_turno(fazer_cliente(_responde(_RESPOSTA)), _MENSAGEM)

    registros = [r.getMessage() for r in caplog.records if r.name == LOGGER_NOS]
    assert any(_MENSAGEM in mensagem for mensagem in registros), (
        f"o prompt do turno não foi registrado: {registros}"
    )
    assert not any(_RESPOSTA in mensagem for mensagem in registros), (
        f"a resposta do modelo foi registrada uma terceira vez no nó: {registros}"
    )


# --- A falha do modelo sobe do grafo, e é o `webhook` quem a vira mensagem ---


def test_erro_de_inferencia_do_ollama_sobe_do_grafo(fazer_cliente: FabricaCliente) -> None:
    """O grafo não engole a falha do modelo.

    Quem vira a falha em mensagem para o Aluno é o `webhook`, no seu executor de
    turno. Se o grafo a engolisse e devolvesse texto vazio, o Aluno receberia uma
    resposta em branco sem nenhum sinal de que o turno não aconteceu — que é o
    defeito que a issue exige fechar.
    """

    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused")

    with pytest.raises(ErroDeInferencia):
        executar_turno(fazer_cliente(handler), _MENSAGEM)
