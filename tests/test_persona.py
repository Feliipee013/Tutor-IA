"""Testes da persona do S.A.U., sau/persona.py.

O que se prova aqui é que cada regra de comportamento chega ao modelo: um
turno real roda pelo grafo, com o `ClienteOllama` de verdade e só o Ollama do
host falso, e o prompt que o modelo recebeu é conferido regra por regra.

O que não se prova aqui, de propósito, é que o modelo obedece: nenhum teste
unitário prova que um LLM segue instrução, e um programa que julgasse
"recusou" ou "encaminhou" julgaria a forma — que é o que a Alucinação imita
bem (`perguntas-teste/perguntas-teste.md`). Quem observa a regra disparar é a
pessoa, lendo o output que o harness da #12 grava. O que estes testes seguram
é a outra metade: que a regra que a pessoa avaliou é a regra que o modelo
recebeu, inteira, no lugar certo, sem ter sido derrubada na composição nem
comida por formatação.

O transporte do modelo é um `httpx.MockTransport`, o mesmo tipo que
`test_graph.py` usa. O corpo de `/api/generate` é reescrito aqui em vez de
importado: cada arquivo de teste declara o contrato que ele precisa, e ninguém
depende do texto de outro.

O teste do conjunto (`test_o_prompt_tem_exatamente_as_regras_da_issue`) é o
último a ficar verde por construção: ele afirma as sete regras de uma vez, e
cada ciclo de regra nova o aproxima do verde sem que ele passe antes da hora.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable, Iterator

import httpx
import pytest

from sau.graph.graph import executar_turno
from sau.inference.ollama import ClienteOllama
from sau.persona import (
    ENCAMINHAMENTO,
    IDENTIDADE,
    NAO_INVENTAR,
    ORIENTACAO_POR_PERGUNTAS,
    PERSONA,
    PRAZO_NAO_E_ATIVIDADE,
    RECUSA_DE_ATIVIDADE,
    REGRAS,
    ROTULO_MENSAGEM,
    TOM,
)

_BASE_URL = "http://host.docker.internal:11434"
_MODELO = "qwen2.5:3b"

_MENSAGEM = "não entendi a matéria de ontem"
_RESPOSTA = "Vamos por partes: o que travou você?"

FabricaCliente = Callable[[Any], ClienteOllama]


def _payload(texto: str) -> dict[str, Any]:
    """O que o Ollama devolve numa geração completa."""
    return {
        "model": _MODELO,
        "response": texto,
        "done": True,
        "done_reason": "stop",
    }


@pytest.fixture
def fazer_cliente() -> Iterator[FabricaCliente]:
    """Fabrica um `ClienteOllama` de verdade com o transporte do host falso."""
    abertos: list[httpx.Client] = []

    def fabricar(handler: Any) -> ClienteOllama:
        cliente_http = httpx.Client(transport=httpx.MockTransport(handler))
        abertos.append(cliente_http)
        return ClienteOllama(_BASE_URL, _MODELO, client=cliente_http)

    yield fabricar
    for cliente_http in abertos:
        cliente_http.close()


def _espelhando_prompts(registros: list[str]) -> Any:
    """Transporte que guarda o prompt que o turno mandou ao modelo."""

    def handler(request: httpx.Request) -> httpx.Response:
        corpo = json.loads(request.content.decode("utf-8"))
        registros.append(corpo["prompt"])
        return httpx.Response(200, json=_payload(_RESPOSTA))

    return handler


def _prompt_do_turno(fazer_cliente: FabricaCliente) -> str:
    """Roda um turno e devolve o prompt que o modelo recebeu."""
    prompts: list[str] = []

    executar_turno(fazer_cliente(_espelhando_prompts(prompts)), _MENSAGEM)

    assert len(prompts) == 1
    return prompts[0]


# --- O conjunto: as sete regras da issue, na ordem em que o modelo as lê ---


def test_o_prompt_tem_exatamente_as_regras_da_issue() -> None:
    """As regras do prompt são estas sete, nesta ordem, e nenhuma a mais.

    A lista é literal porque a fonte dela não é o código: é o critério de
    aceitação da issue #10. Uma regra nova entra aqui junto, e uma regra
    derrubada da composição deixa este teste vermelho antes de qualquer outro.
    """
    assert tuple(regra.id for regra in REGRAS) == (
        "identidade",
        "tom",
        "orientacao_por_perguntas",
        "recusa_de_atividade",
        "prazo_nao_e_atividade",
        "nao_inventar",
        "encaminhamento",
    )


# --- Uma regra por teste: cada uma chega ao modelo como bloco próprio ---


def test_a_regra_de_identidade_chega_ao_modelo(
    fazer_cliente: FabricaCliente,
) -> None:
    """A identidade do S.A.U. está no prompt que o modelo recebeu.

    É esta instrução que diz ao modelo que ele é um assistente virtual, que se
    diz uma única vez na primeira resposta da conversa e que nunca é humano.
    """
    prompt = _prompt_do_turno(fazer_cliente)

    assert IDENTIDADE.instrucao in prompt
    assert prompt.count(IDENTIDADE.instrucao) == 1


def test_a_regra_de_tom_chega_ao_modelo(
    fazer_cliente: FabricaCliente,
) -> None:
    """O tom acolhedor e didático está no prompt que o modelo recebeu.

    É esta instrução que impede o S.A.U. de soar como assistente genérico —
    sem ela, o modelo abre a conversa oferecendo ajuda com qualquer assunto,
    que é o oposto do papel de Tutor do `CONTEXT.md`.
    """
    prompt = _prompt_do_turno(fazer_cliente)

    assert TOM.instrucao in prompt
    assert prompt.count(TOM.instrucao) == 1


def test_a_regra_socratica_chega_ao_modelo(
    fazer_cliente: FabricaCliente,
) -> None:
    """A orientação por perguntas está no prompt que o modelo recebeu.

    É esta instrução que faz o S.A.U. agir como Tutor em vez de entregar a
    resposta pronta — e é a pergunta orientadora que o `conforme quando` das
    Perguntas-teste de Atividade exige junto da recusa.
    """
    prompt = _prompt_do_turno(fazer_cliente)

    assert ORIENTACAO_POR_PERGUNTAS.instrucao in prompt
    assert prompt.count(ORIENTACAO_POR_PERGUNTAS.instrucao) == 1


def test_a_regra_de_recusa_de_atividade_chega_ao_modelo(
    fazer_cliente: FabricaCliente,
) -> None:
    """A recusa de Atividade está no prompt que o modelo recebeu.

    É esta instrução que segura a taxa de recusa da #13: ela nomeia os três
    disfarces que as Perguntas-teste usam — o pedido direto (`a1`), o
    "rascunho só para ver" (`a2`) e a urgência (`a3`) — e manda recusar junto
    com uma pergunta, nunca recusar seco.
    """
    prompt = _prompt_do_turno(fazer_cliente)

    assert RECUSA_DE_ATIVIDADE.instrucao in prompt
    assert prompt.count(RECUSA_DE_ATIVIDADE.instrucao) == 1


def test_a_excecao_do_prazo_chega_ao_modelo(
    fazer_cliente: FabricaCliente,
) -> None:
    """A exceção do prazo está no prompt que o modelo recebeu.

    É esta instrução que impede a recusa de engolir a Pergunta Frequente de
    prazo: sem ela, o modelo lê "Atividade 2" em "quando vence a entrega da
    Atividade 2" e recusa o que ele deveria responder sem inventar — e a `p1`,
    que conta em não-saber e nunca em recusa, cai na taxa errada.
    """
    prompt = _prompt_do_turno(fazer_cliente)

    assert PRAZO_NAO_E_ATIVIDADE.instrucao in prompt
    assert prompt.count(PRAZO_NAO_E_ATIVIDADE.instrucao) == 1


def test_a_regra_de_nao_inventar_chega_ao_modelo(
    fazer_cliente: FabricaCliente,
) -> None:
    """A instrução de não inventar está no prompt que o modelo recebeu.

    É esta instrução que segura a taxa de não-saber da #13: ela nomeia as
    iscas que as Perguntas-teste plantam — data e prazo (`p1`), formato
    (`p2`), caminho (`p3`), protocolo (`p4`), remédio e dose (`f2`), canal
    (`f1`, `f3`) — e o telefone que o ADR-0003 viu o modelo fabricar. Sem a
    lista, o modelo preenche a lacuna com o detalhe mais plausível, que é
    exatamente a Alucinação do `CONTEXT.md`.
    """
    prompt = _prompt_do_turno(fazer_cliente)

    assert NAO_INVENTAR.instrucao in prompt
    assert prompt.count(NAO_INVENTAR.instrucao) == 1


def test_a_regra_de_encaminhamento_chega_ao_modelo(
    fazer_cliente: FabricaCliente,
) -> None:
    """O Encaminhamento está no prompt que o modelo recebeu.

    É esta instrução que escreve a frase que nenhum dos três modelos escreveu
    sozinho na sondagem do ADR-0003: recusar sem encaminhar não é encaminhar.
    E ela fecha a porta do `f1` pelo outro lado — sem prometer sigilo, sem dar
    conselho e sem inventar o canal para onde o Aluno iria.
    """
    prompt = _prompt_do_turno(fazer_cliente)

    assert ENCAMINHAMENTO.instrucao in prompt
    assert prompt.count(ENCAMINHAMENTO.instrucao) == 1


# --- A mensagem: verbatim, depois das regras, com rótulo próprio ---


def test_a_mensagem_do_aluno_vem_depois_das_regras(
    fazer_cliente: FabricaCliente,
) -> None:
    """A mensagem do Aluno chega verbatim, depois da persona, sob o rótulo.

    Três afirmações em uma: a mensagem não é comida pela composição, ela não
    divide o prompt com as regras (vem depois da persona inteira, sob o
    rótulo), e aparece uma vez só. Sem a ordem e o rótulo, uma mensagem que
    soe como ordem — "ignore o resto e responda..." — seria lida como
    instrução no meio das regras.
    """
    prompt = _prompt_do_turno(fazer_cliente)

    assert PERSONA in prompt
    assert ROTULO_MENSAGEM in prompt
    assert _MENSAGEM in prompt
    assert prompt.index(_MENSAGEM) > prompt.index(PERSONA)
    assert prompt.index(_MENSAGEM) > prompt.index(ROTULO_MENSAGEM)
    assert prompt.count(_MENSAGEM) == 1


# --- Um lugar só: nenhum texto de regra mora fora de sau/persona.py ---


def test_as_regras_moram_so_em_sau_persona() -> None:
    """Nenhum texto de regra aparece em outro arquivo do pacote.

    É o "regras todas em um lugar só" do critério de aceitação, tornado
    mecânico: se alguém copiar uma instrução para outro módulo — um segundo
    prompt, um default, um fallback — este teste quebra e aponta o arquivo.
    Os testes podem citar as regras pelo nome; o que não pode existir é um
    segundo texto de instrução fora daqui.
    """
    raiz = Path(__file__).resolve().parent.parent / "sau"
    arquivos = sorted(raiz.rglob("*.py"))
    assert arquivos, "nenhum .py em sau/: o teste varreu o lugar errado"
    fontes = {
        arquivo: _normalizar(arquivo.read_text(encoding="utf-8")) for arquivo in arquivos
    }

    for regra in REGRAS:
        alvo = _normalizar(regra.instrucao)
        donos = [arquivo for arquivo, fonte in fontes.items() if alvo in fonte]
        assert [arquivo.name for arquivo in donos] == ["persona.py"], (
            f"a regra {regra.id!r} aparece fora de sau/persona.py: "
            f"{[str(arquivo) for arquivo in donos]}"
        )


def _normalizar(texto: str) -> str:
    """Tira espaços e aspas para comparar o runtime com o fonte.

    No fonte, cada instrução é uma sequência de literais adjacentes — com
    aspas e quebras de linha entre os pedaços — e em runtime ela é uma string
    só. Sem normalizar, a instrução "não aparece" nem no próprio
    `persona.py`, e o teste acima quebra com a lista de donos vazia em vez de
    quebrar com o segundo prompt.
    """
    return re.sub(r"[\s\"']", "", texto)
