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

import hashlib
import inspect
import json
import logging
from pathlib import Path
from typing import Any, Callable, Iterator

import httpx
import pytest

from harness.run import sha256_do_prompt
from sau.graph.graph import TEXTO_ENCAMINHAMENTO, construir_grafo, executar_turno
from sau.graph.nodes import EstadoTurno, montar_prompt
from sau.inference.ollama import MOTIVO_PARADA_NO_LIMITE, ClienteOllama, ErroDeInferencia
from sau.persona import PERSONA
from sau.rag.embed import ClienteEmbedding
from sau.rag.retrieve import TrechoRecuperado, buscar, carregar_corpus, montar_indice

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

# O vetor que o embedding falso devolve para todo texto: todo trecho empata
# em similaridade, e a busca devolve os três primeiros do índice em ordem.
_VETOR_FALSO = [1.0, 0.0]

_CORPUS = Path(__file__).resolve().parent.parent / "corpus"

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


def _resposta_embed(request: httpx.Request) -> httpx.Response:
    """O que o Ollama devolve no `/api/embed`: um vetor falso por texto de entrada."""
    corpo = json.loads(request.content.decode("utf-8"))
    total = len(corpo["input"])
    return httpx.Response(200, json={"embeddings": [_VETOR_FALSO for _ in range(total)]})


def _e_rota_de_embed(request: httpx.Request) -> bool:
    return request.url.path.endswith("/api/embed")


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
    """Transporte que devolve uma geração completa com o texto dado, e embedding falso.

    O turno agora fala duas rotas do Ollama — `/api/embed` na recuperação e
    `/api/generate` na resposta — e o transporte falso precisa responder as
    duas: sem a rota de embedding, nenhum teste chegaria ao modelo.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if _e_rota_de_embed(request):
            return _resposta_embed(request)
        return httpx.Response(200, json=_payload(texto))

    return handler


def _cliente_embed_falso() -> ClienteEmbedding:
    """O embedding falso para montar o índice esperado, sem rede e sem Ollama."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _resposta_embed(request)

    return ClienteEmbedding(
        _BASE_URL, client=httpx.Client(transport=httpx.MockTransport(handler))
    )


def _contexto_esperado() -> list[TrechoRecuperado]:
    """Os 3 trechos que a recuperação encontra com o vetor falso, na ordem do índice."""
    indice = montar_indice(_CORPUS, _cliente_embed_falso())
    return buscar(indice, list(_VETOR_FALSO))


def _espelhando(registros: list[Any], campo: str | None = None) -> Any:
    """Transporte que guarda o que o grafo mandou ao modelo e devolve uma geração.

    Três testes precisam olhar o que saiu do grafo para o modelo — o corpo
    inteiro, o `prompt`, e o `prompt` conferido contra o `montar_prompt` — e os
    três precisam do mesmo par: espelhar o que foi pedido e responder uma geração.
    `campo` é o nome do que interessa guardar; sem ele, o corpo inteiro é
    guardado, porque `test_turno_chama_o_modelo_uma_vez_so` afirma duas coisas ao
    mesmo tempo sobre esse mesmo corpo.

    Só a geração é espelhada: o embedding da recuperação passa pelo mesmo
    transporte, e quem conta chamadas ao modelo não pode contar o índice junto.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if _e_rota_de_embed(request):
            return _resposta_embed(request)
        corpo = json.loads(request.content.decode("utf-8"))
        registros.append(corpo if campo is None else corpo[campo])
        return httpx.Response(200, json=_payload(_RESPOSTA))

    return handler


# --- Topologia: um caminho só, com a recuperação em todo turno ---


def test_grafo_tem_um_caminho_so(fazer_cliente: FabricaCliente) -> None:
    """`START → recuperar → responder → END`, e nenhum outro nó nem aresta.

    A topologia é o critério de aceitação do grafo, e ela é afirmada pela visão
    que o LangGraph monta do grafo compilado — não pelo código que a construiu,
    que é a mesma coisa que se verificaria escrevendo o mesmo grafo de novo.
    A recuperação roda em todo turno, sem classificação de intenção e sem
    aresta condicional (ADR-0008): somar um nó aqui e uma aresta condicional
    ali quebram este teste do mesmo jeito.
    """
    visao = construir_grafo(fazer_cliente(_responde(_RESPOSTA))).get_graph()

    assert sorted(visao.nodes) == ["__end__", "__start__", "recuperar", "responder"]
    assert {(aresta.source, aresta.target) for aresta in visao.edges} == {
        ("__start__", "recuperar"),
        ("recuperar", "responder"),
        ("responder", "__end__"),
    }


def test_assinatura_do_turno_e_do_grafo_nao_muda() -> None:
    """`executar_turno` e `construir_grafo` mantêm a assinatura.

    É o cliente que carrega o embedding: a recuperação entra sem parâmetro novo
    porque o `ClienteOllama` passou a embutir junto de gerar. Um parâmetro novo
    aqui seria mudança de medição levada para dentro do caminho quente do
    Telegram, e este teste é o que segura a porta.
    """
    assert list(inspect.signature(executar_turno).parameters) == [
        "cliente",
        "mensagem",
        "historico",
    ]
    assert list(inspect.signature(construir_grafo).parameters) == ["cliente"]


def test_turno_chama_o_modelo_uma_vez_so(fazer_cliente: FabricaCliente) -> None:
    """Um caminho só na topologia e uma geração só na prática.

    A topologia do teste anterior é a estrutura; esta é o comportamento. Uma
    segunda chamada de geração no mesmo turno passaria pela topologia de dois
    nós e sairia daqui — e o embedding da recuperação não conta, porque ele
    não gera resposta nenhuma.
    """
    corpos: list[dict[str, Any]] = []

    executar_turno(fazer_cliente(_espelhando(corpos)), _MENSAGEM)

    assert len(corpos) == 1
    assert corpos[0]["model"] == _MODELO
    assert corpos[0]["stream"] is False


def test_turno_embute_o_corpus_e_a_consulta(fazer_cliente: FabricaCliente) -> None:
    """A recuperação embute as seções do índice e a pergunta do Aluno.

    O grafo é remontado a cada turno e o índice mora no fecho do nó: cada
    turno embute o Corpus uma vez — a lista inteira, numa chamada só — e a
    consulta uma vez. Sem essas duas chamadas, o turno responderia sem
    material e sem que nenhum teste notasse.
    """
    rotas: list[str] = []
    corpos: list[list[str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if _e_rota_de_embed(request):
            rotas.append(request.url.path)
            corpos.append(json.loads(request.content.decode("utf-8"))["input"])
            return _resposta_embed(request)
        return httpx.Response(200, json=_payload(_RESPOSTA))

    executar_turno(fazer_cliente(handler), _MENSAGEM)

    assert rotas == ["/api/embed", "/api/embed"]
    assert len(corpos[0]) == len(carregar_corpus(_CORPUS))
    assert corpos[1] == [_MENSAGEM]


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


# --- A costura do prompt, que é onde a persona do S.A.U. entra ---


def test_o_prompt_que_chega_ao_modelo_e_o_montar_prompt(
    fazer_cliente: FabricaCliente,
) -> None:
    """`montar_prompt` é o caminho único do prompt até o modelo.

    E o `montar_prompt` deste módulo não é um: é o de `sau.persona`, reexportado
    em `nodes.py` com `from sau.persona import montar_prompt as montar_prompt`. É
    por isso que a afirmação é esta e não "o prompt contém a persona": ela
    compara o texto que o grafo mandou com a função que mora no módulo da
    persona, e uma persona que tivesse entrado por outro caminho — um segundo
    prompt montado dentro do grafo — deixaria as duas pontas diferentes sem que
    nenhum teste de conteúdo notasse. Quem afirma o conteúdo da persona é o
    `test_persona.py`, que é o arquivo dono dela.

    O contexto esperado é o que a recuperação encontra com o vetor falso: os
    três primeiros trechos do índice, na mesma ordem em que `buscar` devolve.
    """
    prompts: list[str] = []
    contexto = _contexto_esperado()

    executar_turno(fazer_cliente(_espelhando(prompts, "prompt")), _MENSAGEM)

    assert prompts == [montar_prompt(_MENSAGEM, [], contexto)]


def test_os_titulos_recuperados_chegam_ao_prompt(fazer_cliente: FabricaCliente) -> None:
    """Cada Fonte do turno está no prompt que o modelo recebeu, pelo título.

    Sem esta afirmação, um grafo que recuperasse e não entregasse passaria por
    `test_o_prompt_que_chega_ao_modelo_e_o_montar_prompt` do mesmo jeito que um
    grafo que nunca recuperou: a comparação provaria a costura, e o material
    teria ficado pelo caminho sem ninguém notar.
    """
    prompts: list[str] = []

    executar_turno(fazer_cliente(_espelhando(prompts, "prompt")), _MENSAGEM)

    assert len(prompts) == 1
    for trecho in _contexto_esperado():
        assert trecho.titulo in prompts[0], f"a Fonte {trecho.titulo!r} não chegou ao modelo"
        assert trecho.texto in prompts[0]


def test_montar_prompt_carrega_a_mensagem_e_mais_nada(fazer_cliente: FabricaCliente) -> None:
    """O prompt é a persona do S.A.U. com a mensagem do Aluno dentro.

    A persona entra por aqui desde a #10, e o que sobra para este teste é a
    afirmação de que o prompt não é a mensagem crua: um teste que só pedisse que
    a mensagem estivesse no prompt continuaria verde com a persona dentro, e uma
    persona que desaparecesse passaria sem ninguém notar. O `!=` segura a
    instrução sem depender de `sau.persona` — quem afirma o conteúdo da persona
    é o `test_persona.py` da #10, que é o arquivo dono dela.
    """
    prompt = montar_prompt(_MENSAGEM)

    assert _MENSAGEM in prompt
    # Não é a mensagem crua: existe a persona do S.A.U. antes dela.
    assert prompt != _MENSAGEM


def test_o_grafo_entra_somente_com_a_mensagem_e_devolve_os_quatro_campos(
    fazer_cliente: FabricaCliente,
) -> None:
    """O grafo entra com a mensagem e devolve mensagem, material, Fontes e resposta.

    É o que o `NotRequired` em `resposta` compra: sem ele, o estado de entrada
    seria obrigado a carregar uma resposta que ainda não existe, e o `invoke` com
    um estado só de entrada não teria como ser escrito. A afirmação aqui é por
    execução, e não por `__annotations__` — que vira string assim que existe um
    `from __future__ import annotations` no módulo, e passaria a testar o
    `from`, não o estado.
    """
    grafo = construir_grafo(fazer_cliente(_responde(_RESPOSTA)))
    contexto = _contexto_esperado()

    entrada: EstadoTurno = {"mensagem": _MENSAGEM}
    estado = grafo.invoke(entrada)

    assert estado == {
        "mensagem": _MENSAGEM,
        "contexto": contexto,
        "fontes": [trecho.titulo for trecho in contexto],
        "resposta": _RESPOSTA,
    }


def test_as_fontes_resolvem_por_correspondencia_exata_no_corpus(
    fazer_cliente: FabricaCliente,
) -> None:
    """Toda Fonte do turno é exatamente um título do Corpus, sem parsear nada.

    É o que permite ao S.A.U. citar copiando verbatim do trecho que ele tem na
    mão: título único no Corpus inteiro dispensa separar documento de seção, e
    letra trocada não resolve — que é o que a correspondência exata compra.
    """
    grafo = construir_grafo(fazer_cliente(_responde(_RESPOSTA)))

    entrada: EstadoTurno = {"mensagem": _MENSAGEM}
    estado = grafo.invoke(entrada)

    titulos = {secao.titulo for secao in carregar_corpus(_CORPUS)}
    assert estado["fontes"]
    for fonte in estado["fontes"]:
        assert fonte in titulos, f"a Fonte {fonte!r} não é um título do Corpus"


# --- Sem material: o Encaminhamento determinístico mora no grafo ---


def test_sem_trecho_o_turno_encerra_com_o_encaminhamento_deterministico(
    fazer_cliente: FabricaCliente,
) -> None:
    """Sem material recuperado, o S.A.U. diz que não tem o dado e Encaminha.

    O texto é fixo em código, e não pedido ao modelo: sem trecho não há o que
    dizer, e levar a pergunta ao modelo seria pedir forma onde falta conteúdo.
    A geração nem é chamada — o turno encerra no grafo.
    """
    geracoes: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if _e_rota_de_embed(request):
            return httpx.Response(500, json={"error": "model not found"})
        geracoes.append(request.url.path)
        return httpx.Response(200, json=_payload(_RESPOSTA))

    resposta = executar_turno(fazer_cliente(handler), _MENSAGEM)

    assert resposta == TEXTO_ENCAMINHAMENTO
    assert geracoes == []
    assert "Coordenação de Estágios" in resposta


def test_o_encaminhamento_deterministico_nao_mora_na_persona() -> None:
    """O texto fixo vive no grafo, e o `sha256` do prompt não muda com a topologia.

    É a separação que o ADR-0008 pede: o hash reporta a persona, e mudar o
    encerramento — ou somar nó — não muda o hash. Se este texto entrar na
    persona, a rodada passa a declarar mudança de persona onde houve mudança
    de grafo, e a comparação da 1.2 mede duas coisas ao mesmo tempo.
    """
    assert TEXTO_ENCAMINHAMENTO not in PERSONA
    assert sha256_do_prompt() == hashlib.sha256(PERSONA.encode("utf-8")).hexdigest()


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

    É o que separa "o grafo rodou" de "o grafo rodou com o prompt certo". Desde a
    #10 o prompt é a persona do S.A.U. com a mensagem do Aluno dentro, e a
    persona é legível em `sau/persona.py` — o que o log torna auditável é a
    composição das duas, que só existe aqui.

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


# --- O corte de geração: sucesso do modelo, texto pela metade no Aluno ---


def _parada_no_limite(request: httpx.Request) -> httpx.Response:
    """Geração que o Ollama fecha com sucesso e sem o texto inteiro.

    É o corpo exato do defeito: `done: true` e `done_reason: length` numa
    resposta que termina no meio da frase. O embedding segue falso, para que
    o turno chegue à geração com material.
    """
    if _e_rota_de_embed(request):
        return _resposta_embed(request)
    corpo = _payload("Esse prazo eu não sei. Consultar o calendário")
    corpo["done_reason"] = MOTIVO_PARADA_NO_LIMITE
    return httpx.Response(200, json=corpo)


def test_o_no_avisa_quando_a_geracao_para_no_limite(
    fazer_cliente: FabricaCliente, caplog: pytest.LogCaptureFixture
) -> None:
    """O corte de geração vira `WARNING` no log, e não um turno qualquer.

    O Ollama fecha essa geração como sucesso, então o grafo devolve o texto
    cortado e o turno termina igual a qualquer outro: sem aviso, ninguém descobre
    que o Aluno leu uma frase pela metade. O `WARNING` é o que a pessoa vê sem
    pedir — e o teste abaixo é o que impede que a linha vire `INFO`, que é o
    nível que o `webhook` esconde de quem opera.
    """
    with caplog.at_level(logging.WARNING):
        executar_turno(fazer_cliente(_parada_no_limite), _MENSAGEM)

    avisos = _avisos_do_no(caplog)
    assert len(avisos) == 1, f"o corte de geração não avisou: {avisos}"
    assert MOTIVO_PARADA_NO_LIMITE in avisos[0]


def test_o_no_nao_avisa_quando_a_geracao_para_normalmente(
    fazer_cliente: FabricaCliente, caplog: pytest.LogCaptureFixture
) -> None:
    """Só o corte avisa: uma resposta que chegou ao fim é turno sem novidade.

    O aviso que dispara para todo turno vira ruído, e ruído é o que faz a pessoa
    parar de ler o log — que é o oposto do que esta linha existe para dar.
    """
    with caplog.at_level(logging.WARNING):
        executar_turno(fazer_cliente(_responde(_RESPOSTA)), _MENSAGEM)

    assert _avisos_do_no(caplog) == [], "uma geração completa gerou aviso"


def _avisos_do_no(caplog: pytest.LogCaptureFixture) -> list[str]:
    """Os avisos que o nó do grafo registrou, e não os dos outros loggers."""
    return [
        registro.getMessage()
        for registro in caplog.records
        if registro.name == LOGGER_NOS and registro.levelno == logging.WARNING
    ]


# --- A falha do modelo sobe do grafo, e é o `webhook` quem a vira mensagem ---


def test_erro_de_inferencia_do_ollama_sobe_do_grafo(fazer_cliente: FabricaCliente) -> None:
    """O grafo não engole a falha da geração.

    Quem vira a falha em mensagem para o Aluno é o `webhook`, no seu executor de
    turno. Se o grafo a engolisse e devolvesse texto vazio, o Aluno receberia uma
    resposta em branco sem nenhum sinal de que o turno não aconteceu — que é o
    defeito que a issue exige fechar.

    A falha coberta aqui é a da geração: o embedding segue falso, para que o
    turno chegue ao modelo com material. Falha no embedding é recuperação
    desligada, e o turno encerra com o Encaminhamento determinístico em vez de
    subir erro — que é o que `test_sem_trecho_o_turno_encerra_com_o_encaminhamento_deterministico`
    prova.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if _e_rota_de_embed(request):
            return _resposta_embed(request)
        raise httpx.ConnectError("Connection refused")

    with pytest.raises(ErroDeInferencia):
        executar_turno(fazer_cliente(handler), _MENSAGEM)
