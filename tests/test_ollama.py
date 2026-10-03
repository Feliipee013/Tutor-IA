"""Testes do cliente de inferência sau/inference/ollama.py."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
import pytest

from sau.inference.ollama import (
    NUM_CTX_PADRAO,
    ClienteOllama,
    ErroDeInferencia,
    TempoEsgotadoError,
)

_BASE_URL = "http://host.docker.internal:11434"
_MODELO = "qwen2.5:3b"


def _criar_mock_client(rotas: dict[str, tuple[int, dict[str, Any]]]) -> httpx.Client:
    """Cria um cliente httpx com respostas simuladas por rota e método."""

    def handler(request: httpx.Request) -> httpx.Response:
        chave = f"{request.method} {request.url.path}"
        if chave in rotas:
            status, conteudo = rotas[chave]
            return httpx.Response(
                status_code=status,
                content=json.dumps(conteudo).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                request=request,
            )
        return httpx.Response(
            status_code=404,
            content=b'{"error": "not found"}',
            headers={"Content-Type": "application/json"},
            request=request,
        )

    return httpx.Client(transport=httpx.MockTransport(handler))


def _payload_do_generate() -> dict[str, Any]:
    """O que o Ollama devolve numa geração completa, em nanossegundos."""
    return {
        "model": _MODELO,
        "response": "O prazo da entrega eu não sei.",
        "done": True,
        "done_reason": "stop",
        "total_duration": 1_500_000_000,
        "load_duration": 400_000_000,
        "prompt_eval_duration": 100_000_000,
        "eval_duration": 1_000_000_000,
        "eval_count": 50,
        "prompt_eval_count": 30,
    }


# --- Caminho feliz ---


def test_responder_devolve_texto_e_tempos() -> None:
    client = _criar_mock_client({"POST /api/generate": (200, _payload_do_generate())})
    cliente = ClienteOllama(_BASE_URL, _MODELO, client=client)

    resposta = cliente.responder("Quando vence a entrega?")

    assert resposta.texto == "O prazo da entrega eu não sei."
    assert resposta.carga_segundos == pytest.approx(0.4)
    assert resposta.avaliacao_prompt_segundos == pytest.approx(0.1)
    assert resposta.segundos_totais > 0
    assert resposta.tokens_gerados == 50
    assert resposta.tokens_por_segundo == pytest.approx(50.0)
    assert resposta.concluida is True
    assert resposta.motivo_de_parada == "stop"


def test_primeiro_token_e_a_soma_da_carga_com_a_leitura_do_prompt() -> None:
    """A régua do ADR-0003: `load_duration + prompt_eval_duration`.

    O número tem de sair com o mesmo nome e a mesma conta de
    `docs/medicao-modelo/medir.py`, porque é a régua que a #7 usa para
    documentar o tempo de primeira resposta. Régua com nome diferente é número
    que ninguém vai comparar.
    """
    client = _criar_mock_client({"POST /api/generate": (200, _payload_do_generate())})
    cliente = ClienteOllama(_BASE_URL, _MODELO, client=client)

    resposta = cliente.responder("Quando vence a entrega?")

    assert resposta.primeiro_token_segundos == pytest.approx(0.5)
    assert resposta.primeiro_token_segundos == pytest.approx(
        resposta.carga_segundos + resposta.avaliacao_prompt_segundos
    )


def test_geracao_incompleta_sem_duracao_nao_inventa_velocidade() -> None:
    """Sem `eval_duration` não há tok/s, e o campo tem de ficar vazio.

    Zero no lugar de `None` seria uma velocidade que ninguém mediu.
    """
    client = _criar_mock_client({
        "POST /api/generate": (200, {"response": "oi", "done": True, "eval_count": 7}),
    })
    cliente = ClienteOllama(_BASE_URL, _MODELO, client=client)

    resposta = cliente.responder("oi")

    assert resposta.tokens_por_segundo is None
    assert resposta.tokens_gerados == 7
    assert resposta.primeiro_token_segundos == pytest.approx(0.0)


# --- O que o cliente manda ---


def _corpo_enviado(acao: Any) -> dict[str, Any]:
    """Roda `acao` com um cliente que guarda o corpo da requisição."""
    enviados: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/generate":
            enviados.append(json.loads(request.content.decode("utf-8")))
            return httpx.Response(
                200,
                json=_payload_do_generate(),
                headers={"Content-Type": "application/json"},
                request=request,
            )
        return httpx.Response(404, request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        acao(ClienteOllama(_BASE_URL, _MODELO, client=c))

    assert len(enviados) == 1
    return enviados[0]


def test_sem_opcoes_manda_so_o_num_ctx() -> None:
    """O cliente não trava temperatura nem seed.

    A seed fixa do ADR-0003 era condição de medição. Em produção ela daria a
    todo Aluno exatamente a mesma resposta, e o `num_ctx` é o único valor que o
    cliente decide sozinho.
    """
    corpo = _corpo_enviado(lambda cliente: cliente.responder("oi"))

    assert corpo["options"] == {"num_ctx": NUM_CTX_PADRAO}
    assert "seed" not in corpo["options"]
    assert "temperature" not in corpo["options"]


def test_opcoes_da_chamada_chegam_juntas_do_num_ctx() -> None:
    """Quem mede passa as condições dele e elas chegam junto do `num_ctx`."""
    corpo = _corpo_enviado(
        lambda cliente: cliente.responder(
            "oi",
            opcoes={"temperature": 0, "seed": 20260926, "num_predict": 256},
        )
    )

    opcoes = corpo["options"]
    assert opcoes["temperature"] == 0
    assert opcoes["seed"] == 20260926
    assert opcoes["num_predict"] == 256
    assert opcoes["num_ctx"] == NUM_CTX_PADRAO


def test_opcoes_da_chamada_ganham_do_num_ctx_do_cliente() -> None:
    """O `num_ctx` que vem na chamada manda no que está no cliente."""
    enviados: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        enviados.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(
            200,
            json=_payload_do_generate(),
            headers={"Content-Type": "application/json"},
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        cliente = ClienteOllama(_BASE_URL, _MODELO, num_ctx=1024, client=c)
        cliente.responder("oi", opcoes={"num_ctx": 4096})

    assert enviados[0]["options"]["num_ctx"] == 4096


def test_a_requisicao_vai_para_api_generate_sem_stream() -> None:
    """`stream: false` é o que traz a resposta inteira, com os tempos, em um JSON."""
    corpo = _corpo_enviado(lambda cliente: cliente.responder("oi"))

    assert corpo["stream"] is False
    assert corpo["model"] == _MODELO
    assert corpo["prompt"] == "oi"


# --- Falhas ---


def test_status_diferente_de_200_falha_com_o_motivo() -> None:
    client = _criar_mock_client({
        "POST /api/generate": (500, {"error": "model runner exited"}),
    })
    cliente = ClienteOllama(_BASE_URL, _MODELO, client=client)

    with pytest.raises(ErroDeInferencia) as exc_info:
        cliente.responder("oi")

    msg = str(exc_info.value)
    assert "FALHA CRÍTICA" in msg
    assert "500" in msg
    assert "model runner exited" in msg


def test_payload_sem_response_falha_em_vez_de_devolver_texto_vazio() -> None:
    """Sem `response` não há resposta para o Aluno, e texto vazio esconde isso."""
    client = _criar_mock_client({
        "POST /api/generate": (200, {"done": True, "eval_count": 0}),
    })
    cliente = ClienteOllama(_BASE_URL, _MODELO, client=client)

    with pytest.raises(ErroDeInferencia) as exc_info:
        cliente.responder("oi")

    msg = str(exc_info.value)
    assert "FALHA CRÍTICA" in msg
    assert "'response'" in msg
    assert "done" in msg  # o que veio é listado, para dar o que investigar


def test_response_vazio_e_uma_resposta_e_nao_uma_falha() -> None:
    """O campo presente e vazio é o modelo calado, que é outra coisa.

    A diferença importa: payload incompleto é defeito do Ollama, e modelo que
    devolve string vazia é conteúdo. Tratar os dois como erro esconderia o
    segundo, que é problema de prompt.
    """
    client = _criar_mock_client({
        "POST /api/generate": (200, {"response": "", "done": True, "done_reason": "stop"}),
    })
    cliente = ClienteOllama(_BASE_URL, _MODELO, client=client)

    resposta = cliente.responder("oi")

    assert resposta.texto == ""
    assert resposta.concluida is True


def test_timeout_vira_tempo_esgotado_com_o_tempo_esperado() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out")

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        cliente = ClienteOllama(_BASE_URL, _MODELO, timeout=7.0, client=c)
        with pytest.raises(TempoEsgotadoError) as exc_info:
            cliente.responder("oi")

    msg = str(exc_info.value)
    assert "FALHA CRÍTICA" in msg
    assert "7s" in msg
    # Timeout é subclasse de ErroDeInferencia: quem trata o erro grande trata
    # os dois, e quem quiser o detalhe do tempo tem a classe própria.
    assert isinstance(exc_info.value, ErroDeInferencia)


def test_resposta_que_nao_e_json_falha_com_mensagem_propria() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>proxy</html>", request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        cliente = ClienteOllama(_BASE_URL, _MODELO, client=c)
        with pytest.raises(ErroDeInferencia, match="não é JSON"):
            cliente.responder("oi")


def test_erro_de_rede_manda_olhar_o_adr_0002() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused")

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        cliente = ClienteOllama(_BASE_URL, _MODELO, client=c)
        with pytest.raises(ErroDeInferencia) as exc_info:
            cliente.responder("oi")

    assert "ADR-0002" in str(exc_info.value)


# --- Resposta no log ---


def test_a_saida_do_modelo_vai_no_log_inteira(caplog: pytest.LogCaptureFixture) -> None:
    """Critério 5 da #7: a saída do modelo fica em log, para poder ser lida.

    O teste usa uma resposta com espaçamento quebrado em três linhas, porque
    o que a fumaça recebe na prática é assim, e um resumo, uma aspas ou uma
    truncagem no meio da frase não serviria para ler nada.
    """
    texto = (
        "Oi! Eu não tenho essa informação aqui. Como eu não sei o prazo, não "
        "vou inventar um — isso é pior do que dizer que não sei. Procure a "
        "Coordenação de Estágios, que ela tem o calendário do estágio."
    )
    client = _criar_mock_client({
        "POST /api/generate": (200, {**_payload_do_generate(), "response": texto}),
    })
    cliente = ClienteOllama(_BASE_URL, _MODELO, client=client)

    with caplog.at_level(logging.INFO):
        cliente.responder("Quando vence a entrega?")

    registros = [r for r in caplog.records if r.name == "sau.inference.ollama"]
    assert len(registros) == 1
    registro = registros[0]
    assert registro.levelno == logging.INFO
    # O texto vai como está: a mensagem inteira sai com o mesmo conteúdo que o
    # modelo devolveu, sem aspas, sem reticências e sem quebra.
    assert texto in registro.getMessage()
    assert texto in caplog.text


def test_o_log_traz_os_tempos_no_mesmo_registro(caplog: pytest.LogCaptureFixture) -> None:
    """Tempo sem a resposta que ele mediu é tempo de ninguém."""
    client = _criar_mock_client({"POST /api/generate": (200, _payload_do_generate())})
    cliente = ClienteOllama(_BASE_URL, _MODELO, client=client)

    with caplog.at_level(logging.INFO):
        cliente.responder("oi")

    texto = caplog.text
    assert "primeiro token 0.500s" in texto
    assert "carga 0.400s" in texto
    assert "prompt 0.100s" in texto
    assert "50.0 tok/s" in texto
    assert "50 tokens" in texto
    assert "parada: stop" in texto


def test_motivo_de_parada_ausente_nao_deixa_campo_vazio_no_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Campo vazio no log vira espaço em branco, e ninguém sabe se houve erro."""
    client = _criar_mock_client({
        "POST /api/generate": (200, {"response": "oi", "done": True}),
    })
    cliente = ClienteOllama(_BASE_URL, _MODELO, client=client)

    with caplog.at_level(logging.INFO):
        resposta = cliente.responder("oi")

    assert resposta.motivo_de_parada == ""
    assert "parada: (o Ollama não informou)" in caplog.text
    assert "parada: \n" not in caplog.text


def test_campos_ausentes_viram_n_d_e_nao_none(caplog: pytest.LogCaptureFixture) -> None:
    """`None` impresso no log é ruído; `n/d` é a forma que o ADR-0003 já usa."""
    client = _criar_mock_client({
        "POST /api/generate": (200, {"response": "oi", "done": True}),
    })
    cliente = ClienteOllama(_BASE_URL, _MODELO, client=client)

    with caplog.at_level(logging.INFO):
        cliente.responder("oi")

    assert "n/d tok/s" in caplog.text
    assert "n/d tokens" in caplog.text
    assert "None" not in caplog.text


# --- Embedding pelo cliente do turno: a recuperação sem parâmetro novo ---


def test_embutir_pede_vetores_no_api_embed_como_lista() -> None:
    """O transporte de mock responde também `/api/embed`: nenhum teste fala com o Ollama real."""
    enviados: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        corpo = json.loads(request.content.decode("utf-8"))
        enviados.append(corpo)
        total = len(corpo["input"])
        return httpx.Response(
            200,
            json={"embeddings": [[3.0, 4.0] for _ in range(total)]},
            request=request,
        )

    cliente = ClienteOllama(
        _BASE_URL, _MODELO, client=httpx.Client(transport=httpx.MockTransport(handler))
    )

    vetores = cliente.embutir(["prazo de entrega", "formato do relatório"])

    assert len(enviados) == 1
    assert enviados[0]["input"] == ["prazo de entrega", "formato do relatório"]
    assert len(vetores) == 2
    for vetor in vetores:
        assert vetor == pytest.approx([0.6, 0.8])


def test_modelo_de_embedding_padrao_e_o_medido_no_host() -> None:
    """O nome não é escolhido antes: é o que o ADR-0003 registra por medição."""
    cliente = ClienteOllama(_BASE_URL, _MODELO)

    assert cliente.modelo_embedding == "nomic-embed-text"
