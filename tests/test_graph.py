"""Testes do grafo do turno, `sau/graph/`.

O que se prova aqui é o grafo do ADR-0010, com a separação da #36: o ciclo
`roteador → ferramentas → roteador` decide e busca, o `redator` escreve a
resposta ao Aluno, e o `finalizar` fecha com a guarda determinística de ausência
de evidência. A costura do prompt e a entrada e a saída no log também ficam aqui.

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

import hashlib
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
from sau.persona import PERSONA, PERSONA_DE_ROTEAMENTO, montar_prompt, montar_prompt_de_roteamento

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


# --- Topologia: o roteador, a ferramenta opcional e o redator ---


def test_grafo_tem_o_roteador_e_o_redator_com_ferramenta(fazer_cliente: FabricaCliente) -> None:
    """Com Manual, o grafo tem roteador, ferramentas, fallback, redator e finalizar.

    A topologia é o critério de aceitação do grafo, e ela é afirmada pela visão
    que o LangGraph monta do grafo compilado — não pelo código que a construiu,
    que é a mesma coisa que se verificaria escrevendo o mesmo grafo de novo. É o
    ciclo do ADR-0010 com a separação da #36: o roteador decide e a ferramenta
    executa quando chamada, a `busca_de_seguranca` cobre o declínio do roteador
    com UMA busca determinística, o redator escreve a resposta ao Aluno, e o
    finalizar encerra com a guarda de ausência.
    """
    visao = construir_grafo(fazer_cliente(_roteiro([], [])), manual=_manual()).get_graph()

    assert sorted(visao.nodes) == [
        "__end__",
        "__start__",
        "busca_de_seguranca",
        "ferramentas",
        "finalizar",
        "redator",
        "roteador",
    ]
    arestas = {(aresta.source, aresta.target) for aresta in visao.edges}
    assert ("__start__", "roteador") in arestas
    assert ("ferramentas", "roteador") in arestas
    assert ("busca_de_seguranca", "redator") in arestas
    assert ("redator", "finalizar") in arestas
    assert ("finalizar", "__end__") in arestas


def test_grafo_sem_manual_nao_tem_roteador_nem_ferramenta(fazer_cliente: FabricaCliente) -> None:
    """Sem Manual, o redator escreve direto da persona e o ciclo nunca abre.

    É o modo dos testes de persona: o prompt é medido sem que o índice entre no
    caminho. Um roteador sem ferramenta a decidir seria um nó que não muda nada.
    """
    visao = construir_grafo(fazer_cliente(_roteiro([], []))).get_graph()

    assert sorted(visao.nodes) == ["__end__", "__start__", "finalizar", "redator"]
    arestas = {(aresta.source, aresta.target) for aresta in visao.edges}
    assert ("__start__", "redator") in arestas
    assert ("redator", "finalizar") in arestas


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
    """A aresta condicional tem três destinos: ferramenta, fallback e redator.

    Com chamada pendente e rodada livre, volta à ferramenta. Sem chamada e sem
    ferramenta executada — o roteador declinou de primeira —, passa à
    `busca_de_seguranca`, que tenta UMA busca determinística. Sem chamada mas
    com ferramenta já executada — o declínio pós-busca —, vai direto ao
    `redator`, sem rebusca. No teto de rodadas, também passa ao redator, que
    escreve com o que o roteador já trouxe, em vez de girar para sempre: é a
    trava contra o laço infinito de um modelo que peça a ferramenta sem parar.
    """
    assert rota_das_ferramentas({"mensagem": _MENSAGEM, "pendentes": []}) == (
        "busca_de_seguranca"
    )
    chamada = ChamadaDeFerramenta(nome="buscar_no_manual", argumentos={})
    com_chamada: EstadoTurno = {"mensagem": _MENSAGEM, "pendentes": [chamada], "rodadas": 1}
    assert rota_das_ferramentas(com_chamada) == "ferramentas"
    declinio_pos_busca: EstadoTurno = {
        "mensagem": _MENSAGEM,
        "pendentes": [],
        "houve_ferramenta": True,
        "houve_evidencia": True,
        "rodadas": 2,
    }
    assert rota_das_ferramentas(declinio_pos_busca) == "redator"
    no_teto: EstadoTurno = {
        "mensagem": _MENSAGEM,
        "pendentes": [chamada],
        "houve_ferramenta": True,
        "houve_evidencia": True,
        "rodadas": LIMITE_DE_RODADAS,
    }
    assert rota_das_ferramentas(no_teto) == "redator"


# --- O que o grafo devolve, com e sem ferramenta ---


def test_turno_devolve_o_texto_do_modelo(fazer_cliente: FabricaCliente) -> None:
    """Resposta direta do redator — saudação, cortesia — sai como veio."""
    handler = _roteiro([_chat_com_texto(_RESPOSTA)], [])

    assert executar_turno(fazer_cliente(handler), _MENSAGEM) == _RESPOSTA


def test_turno_com_ferramenta_executa_e_o_redator_escreve(
    fazer_cliente: FabricaCliente, buscar_falsa: list[list[TrechoDoManual]]
) -> None:
    """O roteador pede a ferramenta, o grafo executa e o redator escreve a resposta.

    É o caminho do ADR-0010 com a separação da #36: o roteador decide consultar,
    a ferramenta traz o material, o roteador confirma que não precisa de mais
    nada e o redator redige. O prompt que abre o turno é o do roteador; o do
    redator chega ao modelo na terceira rodada, junto do resultado da ferramenta
    como mensagem `tool`, com a Fonte que o redator cita. Sem esta mensagem, o
    redator escreveria sem material.
    """
    buscar_falsa.append([_TRECHO])
    chats: list[dict[str, Any]] = []
    passos = [
        _chat_com_chamada(consulta="prazo de entrega"),
        _chat_com_texto("sem busca"),
        _chat_com_texto(_RESPOSTA_COM_FONTE),
    ]
    handler = _roteiro(passos, chats)

    resposta = executar_turno(fazer_cliente(handler), _MENSAGEM, manual=_manual())

    assert resposta == _RESPOSTA_COM_FONTE
    assert len(chats) == 3
    # A terceira rodada é o redator: prompt do redator mais o par de ferramenta.
    mensagens = chats[2]["messages"]
    assert mensagens[0]["role"] == "user"
    assert mensagens[0]["content"] == montar_prompt(_MENSAGEM)
    assert mensagens[-1]["role"] == "tool"
    assert mensagens[-1]["tool_name"] == "buscar_no_manual"
    assert _TRECHO.fonte in mensagens[-1]["content"]
    # O schema da ferramenta vai declarado ao roteador (as duas rodadas dele).
    assert chats[0]["tools"][0]["function"]["name"] == "buscar_no_manual"
    assert chats[1]["tools"][0]["function"]["name"] == "buscar_no_manual"
    # O redator **não** declara `tools`: é o ponto central da #36.
    assert "tools" not in chats[2]


def test_saudacao_passa_pelo_roteador_e_pelo_redator_sem_ferramenta(
    fazer_cliente: FabricaCliente,
    buscar_falsa: list[list[TrechoDoManual]],
) -> None:
    """Uma resposta direta são duas rodadas — roteador e redator — e nenhuma `tool`.

    O roteador não abre o ciclo (não há chamada pendente) e o redator escreve da
    persona, sem par de ferramenta no corpo. O que o teste protege é justamente
    isso: a mensagem `tool` só existe quando houve consulta. A busca falsificada
    vazia é a do fallback: a busca de segurança roda e não acha nada, então não
    anexa nada.
    """
    chats: list[dict[str, Any]] = []
    handler = _roteiro([_chat_com_texto("sem busca"), _chat_com_texto(_RESPOSTA)], chats)

    executar_turno(fazer_cliente(handler), _MENSAGEM, manual=_manual())

    assert len(chats) == 2
    assert all(mensagem["role"] != "tool" for mensagem in chats[1]["messages"])
    assert "tools" not in chats[1]


def test_a_ferramenta_sem_evidencia_vira_o_literal_de_ausencia(
    fazer_cliente: FabricaCliente, buscar_falsa: list[list[TrechoDoManual]]
) -> None:
    """Chamou a ferramenta e nada passou pelo limiar: resposta é o literal.

    O redator pode ter respondido qualquer coisa na terceira rodada; a guarda do
    `finalizar` troca pelo texto do grafo. É o critério do ADR-0012 que não
    depende de o modelo obedecer ao prompt.
    """
    buscar_falsa.append([])  # A busca não devolve trecho algum.
    chats: list[dict[str, Any]] = []
    passos = [
        _chat_com_chamada(consulta="prazo de entrega"),
        _chat_com_texto("sem busca"),
        _chat_com_texto("resposta inventada"),
    ]
    handler = _roteiro(passos, chats)

    resposta = executar_turno(fazer_cliente(handler), _MENSAGEM, manual=_manual())

    assert resposta == TEXTO_AUSENCIA
    assert LITERAL_NAO_ENCONTREI in resposta
    assert "Coordenação de Estágios" in resposta


def test_a_guarda_nao_dispara_quando_nao_houve_ferramenta(
    fazer_cliente: FabricaCliente, buscar_falsa: list[list[TrechoDoManual]]
) -> None:
    """Sem chamada à ferramenta, a resposta do redator passa intacta.

    Saudação e cortesia não buscam nada; não há ausência de evidência a
    declarar, e trocar a resposta pelo literal seria responder o que o Aluno não
    perguntou. A busca falsificada vazia é a do fallback, que roda e não acha.
    """
    handler = _roteiro([_chat_com_texto("sem busca"), _chat_com_texto(_RESPOSTA)], [])

    assert executar_turno(fazer_cliente(handler), _MENSAGEM, manual=_manual()) == _RESPOSTA


def test_declinio_factual_com_evidencia_no_fallback_nao_vira_ausencia(
    fazer_cliente: FabricaCliente, buscar_falsa: list[list[TrechoDoManual]]
) -> None:
    """O roteador declinou a pergunta factual, mas o fallback achou material.

    É o defeito que a busca de segurança fecha: sem ela, o redator escreveria
    sem material nenhum — e já saiu resposta não ancorada carimbada como se
    viesse do Manual. Com ela, o redator recebe o par `tool` com
    os trechos, a resposta é a ancorada, e a guarda de ausência não dispara.
    A busca usa a mensagem crua do Aluno, e o turno continua em duas rodadas —
    o fallback não chama o modelo.
    """
    buscar_falsa.append([_TRECHO])
    chats: list[dict[str, Any]] = []
    passos = [
        _chat_com_texto("sem busca"),
        _chat_com_texto(_RESPOSTA_COM_FONTE),
    ]
    grafo = construir_grafo(fazer_cliente(_roteiro(passos, chats)), manual=_manual())

    entrada: EstadoTurno = {
        "mensagem": _MENSAGEM,
        "mensagens": [{"role": "user", "content": montar_prompt_de_roteamento(_MENSAGEM)}],
        "rodadas": 0,
    }
    estado = grafo.invoke(entrada)

    assert estado["resposta"] == _RESPOSTA_COM_FONTE
    assert estado["resposta"] != TEXTO_AUSENCIA
    assert estado["houve_ferramenta"] is True
    assert estado["houve_evidencia"] is True
    assert estado["fontes"] == [_TRECHO.fonte]
    assert len(chats) == 2
    # O redator recebeu o par de ferramenta do fallback, com a consulta crua.
    mensagens = chats[1]["messages"]
    assistentes = [
        mensagem
        for mensagem in mensagens
        if mensagem["role"] == "assistant" and mensagem.get("tool_calls")
    ]
    assert len(assistentes) == 1
    chamada = assistentes[0]["tool_calls"][0]["function"]
    assert chamada["name"] == "buscar_no_manual"
    assert chamada["arguments"] == {"consulta": _MENSAGEM}
    ferramentas = [mensagem for mensagem in mensagens if mensagem["role"] == "tool"]
    assert len(ferramentas) == 1
    assert ferramentas[0]["tool_name"] == "buscar_no_manual"
    assert _TRECHO.fonte in ferramentas[0]["content"]


def test_saudacao_declinada_sem_evidencia_no_fallback_responde_direto(
    fazer_cliente: FabricaCliente, buscar_falsa: list[list[TrechoDoManual]]
) -> None:
    """A saudação que o fallback não sustentou responde direto, sem o literal.

    É o teste guarda-chuva da saudação: o roteador declinou, a busca de
    segurança não achou nada e por isso NÃO anexou nada nem marcou as
    bandeiras — a guarda do `finalizar` só dispara com `houve_ferramenta`, e
    uma saudação trocada pelo literal de ausência responderia o que o Aluno
    não perguntou.
    """
    buscar_falsa.append([])  # A busca de segurança não devolve trecho algum.
    chats: list[dict[str, Any]] = []
    passos = [
        _chat_com_texto("sem busca"),
        _chat_com_texto(_RESPOSTA),
    ]
    grafo = construir_grafo(fazer_cliente(_roteiro(passos, chats)), manual=_manual())
    mensagem = "oi, bom dia!"

    entrada: EstadoTurno = {
        "mensagem": mensagem,
        "mensagens": [{"role": "user", "content": montar_prompt_de_roteamento(mensagem)}],
        "rodadas": 0,
    }
    estado = grafo.invoke(entrada)

    assert estado["resposta"] == _RESPOSTA
    assert estado["resposta"] != TEXTO_AUSENCIA
    assert not estado.get("houve_ferramenta")
    assert not estado.get("houve_evidencia")
    assert len(chats) == 2
    assert all(
        recebida["role"] != "tool" for recebida in chats[1]["messages"]
    )


def test_o_teto_de_rodadas_encerra_o_ciclo(
    fazer_cliente: FabricaCliente, buscar_falsa: list[list[TrechoDoManual]]
) -> None:
    """Um modelo que pede a ferramenta para sempre não trava o turno.

    O teto encerra o roteador em `LIMITE_DE_RODADAS` rodadas e passa ao redator,
    que é a rodada extra depois do teto; sem ele, o ciclo `roteador →
    ferramentas` giraria indefinidamente. A busca devolve trecho válido para a
    guarda de ausência não disparar e a resposta ser o texto do redator.
    """
    buscar_falsa.extend([[_TRECHO] for _ in range(LIMITE_DE_RODADAS)])
    chats: list[dict[str, Any]] = []
    passos = [_chat_com_chamada(consulta="prazo") for _ in range(LIMITE_DE_RODADAS)]
    passos.append(_chat_com_texto(_RESPOSTA_COM_FONTE))
    handler = _roteiro(passos, chats)

    resposta = executar_turno(fazer_cliente(handler), _MENSAGEM, manual=_manual())

    assert len(chats) == LIMITE_DE_RODADAS + 1
    assert resposta == _RESPOSTA_COM_FONTE


# --- A costura do prompt, que é onde a persona do S.A.U. entra ---


def test_o_prompt_que_chega_ao_modelo_sem_manual_e_o_montar_prompt(
    fazer_cliente: FabricaCliente,
) -> None:
    """Sem Manual, o prompt que chega ao modelo é o `montar_prompt` do redator.

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


def test_o_prompt_do_roteador_chega_ao_modelo_com_manual(
    fazer_cliente: FabricaCliente,
    buscar_falsa: list[list[TrechoDoManual]],
) -> None:
    """Com Manual, o turno abre pelo prompt do roteador, e não pelo do redator.

    É a mesma costura do teste anterior, do lado do roteador: o texto que abre o
    turno é o de `montar_prompt_de_roteamento`. Uma troca acidental — abrir pelo
    prompt do redator — tiraria do roteador a persona enxuta que faz o modelo
    chamar a ferramenta, e as duas pontas ficariam diferentes sem que o conteúdo
    da persona mudasse. A busca falsificada vazia é a do fallback, que roda e
    não acha.
    """
    chats: list[dict[str, Any]] = []
    handler = _roteiro([_chat_com_texto("sem busca"), _chat_com_texto(_RESPOSTA)], chats)

    executar_turno(fazer_cliente(handler), _MENSAGEM, manual=_manual())

    assert chats[0]["messages"][0]["content"] == montar_prompt_de_roteamento(_MENSAGEM)


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
    passos = [
        _chat_com_chamada(consulta="prazo"),
        _chat_com_texto("sem busca"),
        _chat_com_texto(_RESPOSTA_COM_FONTE),
    ]
    grafo = construir_grafo(fazer_cliente(_roteiro(passos, chats)), manual=_manual())

    entrada: EstadoTurno = {
        "mensagem": _MENSAGEM,
        "mensagens": [{"role": "user", "content": montar_prompt_de_roteamento(_MENSAGEM)}],
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
    assert TEXTO_AUSENCIA not in PERSONA_DE_ROTEAMENTO
    assert sha256_do_prompt() == hashlib.sha256(
        (PERSONA + "\n\n" + PERSONA_DE_ROTEAMENTO).encode("utf-8")
    ).hexdigest()


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
