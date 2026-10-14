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
`test_graph.py` usa. O corpo de `/api/chat` é reescrito aqui em vez de
importado: cada arquivo de teste declara o contrato que ele precisa, e ninguém
depende do texto de outro. O turno roda sem `OpcoesDoManual`, então o grafo
chama só o `redator` e o prompt que ele recebe é o objeto destes testes — a
ferramenta tem testes próprios, em `test_graph.py`.

O teste do conjunto (`test_o_prompt_tem_exatamente_as_regras_da_issue`) é o
último a ficar verde por construção: ele afirma as regras todas de uma vez, e
qualquer regra nova ou derrubada aparece nele primeiro.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable, Iterator

import httpx
import pytest

from sau.graph.graph import executar_turno
from sau.graph.state import Mensagem
from sau.inference.ollama import ClienteOllama
from sau.persona import (
    APRESENTACAO_DA_MENSAGEM,
    APRESENTACAO_DO_HISTORICO,
    AVISO_CONVERSA,
    CORTESIA,
    ENCAMINHAMENTO,
    ESCOPO_DE_ESTAGIO,
    EXEMPLO_DE_ENCAMINHAMENTO,
    FIM_CONVERSA,
    FORMATO_SAIDA,
    HISTORICO_VAZIO,
    IDENTIDADE,
    INICIO_CONVERSA,
    MENSAGENS_NO_PROMPT,
    NAO_INVENTAR,
    ORIENTACAO_DE_FONTE,
    ORIENTACAO_PROCEDURAL,
    PERSONA,
    PERSONA_DE_ROTEAMENTO,
    REGRAS,
    TOM,
    USAR_HISTORICO,
    montar_prompt,
    montar_prompt_de_roteamento,
)

_BASE_URL = "http://host.docker.internal:11434"
_MODELO = "qwen2.5:3b"

_MENSAGEM = "onde eu entrego o relatório de atividades?"
_RESPOSTA = "Primeiro: o Termo de Compromisso já está assinado?"

FabricaCliente = Callable[[Any], ClienteOllama]


def _payload(texto: str) -> dict[str, Any]:
    """O que o Ollama devolve numa conversa por `/api/chat` completa.

    O turno do ADR-0010 fala por `/api/chat`, e não por `/api/generate`: o
    corpo tem `message`, e não `response`.
    """
    return {
        "model": _MODELO,
        "message": {"role": "assistant", "content": texto},
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
    """Transporte que guarda o prompt que o turno mandou ao modelo.

    O prompt do turno é a primeira mensagem `user` da conversa: a persona mais
    a cerca com o histórico e a mensagem do Aluno. É ela que os testes de
    persona conferem regra por regra.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api/embed"):
            corpo = json.loads(request.content.decode("utf-8"))
            total = len(corpo["input"])
            return httpx.Response(200, json={"embeddings": [[1.0, 0.0] for _ in range(total)]})
        corpo = json.loads(request.content.decode("utf-8"))
        registros.append(corpo["messages"][0]["content"])
        return httpx.Response(200, json=_payload(_RESPOSTA))

    return handler


def _prompt_do_turno(fazer_cliente: FabricaCliente) -> str:
    """Roda um turno e devolve o prompt que o modelo recebeu."""
    prompts: list[str] = []

    executar_turno(fazer_cliente(_espelhando_prompts(prompts)), _MENSAGEM)

    assert len(prompts) == 1
    return prompts[0]


# --- O conjunto: as regras todas, na ordem em que o modelo as lê ---


def test_o_prompt_tem_exatamente_as_regras_da_issue() -> None:
    """As regras do prompt são estas, nesta ordem, e nenhuma a mais.

    A lista é literal porque a fonte dela não é o código: é o comportamento que
    o `CONTEXT.md` exige do agente de orientação sobre processos de estágio. Uma
    regra nova entra aqui junto, e uma regra derrubada da composição deixa este
    teste vermelho antes de qualquer outro.
    """
    assert tuple(regra.id for regra in REGRAS) == (
        "identidade",
        "escopo_de_estagio",
        "tom",
        "cortesia",
        "orientacao_procedural",
        "nao_inventar",
        "encaminhamento",
        "usar_historico",
        "formato_saida",
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
    """O tom acolhedor e objetivo está no prompt que o modelo recebeu.

    É esta instrução que impede o S.A.U. de soar como assistente genérico —
    sem ela, o modelo abre a conversa oferecendo ajuda com qualquer assunto,
    que é o oposto do papel de agente de orientação do `CONTEXT.md`.
    """
    prompt = _prompt_do_turno(fazer_cliente)

    assert TOM.instrucao in prompt
    assert prompt.count(TOM.instrucao) == 1


def test_a_regra_de_cortesia_chega_ao_modelo(
    fazer_cliente: FabricaCliente,
) -> None:
    """A cortesia com saudação, despedida e agradecimento está no prompt que o modelo recebeu.

    É esta instrução que impede o redator de tratar um "obrigado" como dúvida:
    sem ela, com trechos anexados pelo fallback, o redator escolhia o ramo do
    Encaminhamento e respondia o que o Aluno não perguntou — saudação não é
    pergunta, e os trechos ficam sem uso.
    """
    prompt = _prompt_do_turno(fazer_cliente)

    assert CORTESIA.instrucao in prompt
    assert prompt.count(CORTESIA.instrucao) == 1


def test_a_regra_de_escopo_de_estagio_chega_ao_modelo(
    fazer_cliente: FabricaCliente,
) -> None:
    """A restrição ao processo de estágio está no prompt que o modelo recebeu.

    É esta instrução que nomeia o que o agente orienta — prazos, documentação,
    contratos, seguro e a ordem das etapas — e o que fazer com o que está fora
    disso: dizer em uma frase que está fora e encerrar com Encaminhamento, sem
    responder ao assunto.

    A regra **não** dita o texto da resposta, e isso é o que o teste ao lado
    segura: pedir frase exata aqui dentro faz o 3B devolver a frase em vez de
    orientar.
    """
    prompt = _prompt_do_turno(fazer_cliente)

    assert ESCOPO_DE_ESTAGIO.instrucao in prompt
    assert prompt.count(ESCOPO_DE_ESTAGIO.instrucao) == 1


def test_a_regra_de_orientacao_procedural_chega_ao_modelo(
    fazer_cliente: FabricaCliente,
) -> None:
    """A orientação passo a passo está no prompt que o modelo recebeu.

    É esta instrução que faz o S.A.U. descrever o processo em etapas — o que
    preencher, quem assina, onde entregar, em qual prazo — e é dela que vem a
    pergunta pelos dados que faltam antes de concluir, e a ressalva de que
    parecer jurídico é Encaminhamento.
    """
    prompt = _prompt_do_turno(fazer_cliente)

    assert ORIENTACAO_PROCEDURAL.instrucao in prompt
    assert prompt.count(ORIENTACAO_PROCEDURAL.instrucao) == 1


def test_a_regra_de_nao_inventar_chega_ao_modelo(
    fazer_cliente: FabricaCliente,
) -> None:
    """A instrução de não inventar está no prompt que o modelo recebeu.

    É esta instrução que segura a taxa de não-saber da #13: ela nomeia as
    iscas que as Perguntas-teste plantam — prazo e data de assinatura, número
    de apólice e seguradora, valor, telefone e canal — porque sem a lista o
    modelo preenche a lacuna com o detalhe mais plausível, que é exatamente a
    Alucinação do `CONTEXT.md`.
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
    E ela fecha a porta do `f1` pelo outro lado — sem prometer prazo de
    resposta e sem inventar o canal para onde o Aluno iria.
    """
    prompt = _prompt_do_turno(fazer_cliente)

    assert ENCAMINHAMENTO.instrucao in prompt
    assert prompt.count(ENCAMINHAMENTO.instrucao) == 1


def test_a_regra_de_usar_historico_chega_ao_modelo(
    fazer_cliente: FabricaCliente,
) -> None:
    """O uso do histórico está no prompt que o modelo recebeu.

    É esta instrução que impede o S.A.U. de repedir pergunta sobre dado que o
    Aluno já informou: sem ela, a cadeia de Petrolina repete "qual cidade?" a
    cada turno, e o conforme da cadeia s1–s5 reprova.
    """
    prompt = _prompt_do_turno(fazer_cliente)

    assert USAR_HISTORICO.instrucao in prompt
    assert prompt.count(USAR_HISTORICO.instrucao) == 1


def test_a_regra_de_formato_saida_chega_ao_modelo(
    fazer_cliente: FabricaCliente,
) -> None:
    """O formato estrito de resposta está no prompt que o modelo recebeu.

    É esta instrução que impede o S.A.U. de devolver rótulo, marcador ou nome de
    regra junto da resposta: o Aluno lê o texto da resposta, não a estrutura do
    prompt.
    """
    prompt = _prompt_do_turno(fazer_cliente)

    assert FORMATO_SAIDA.instrucao in prompt
    assert prompt.count(FORMATO_SAIDA.instrucao) == 1


def test_o_titulo_de_cada_regra_chega_ao_modelo(fazer_cliente: FabricaCliente) -> None:
    """O `titulo` de cada regra vai no prompt junto da instrução.

    Os testes acima conferem a `instrucao` e não o `titulo`, então um
    `PERSONA` montado só com as instruções passaria por todos eles — que é
    exatamente o estado em que a persona estava, com parágrafos sem
    cabeçalho entregues a um modelo de 3B. Este teste é o que fecha a porta: o
    título nomeia a regra para quem lê o prompt, que é o modelo.
    """
    prompt = _prompt_do_turno(fazer_cliente)

    for regra in REGRAS:
        assert regra.titulo in prompt, f"o título da regra {regra.id!r} não chegou ao modelo"
        assert prompt.count(regra.titulo) == 1


# --- A conversa do Aluno: depois das regras, dentro da cerca ---


def test_a_conversa_do_aluno_vem_depois_das_regras_dentro_da_cerca(
    fazer_cliente: FabricaCliente,
) -> None:
    """A conversa chega verbatim, depois da persona, entre os dois marcadores.

    Quatro afirmações em uma: o texto do Aluno não é comida pela composição, ele
    não divide o prompt com as regras (vem depois da persona inteira), ele aparece
    uma vez só, e ele é a última coisa antes do fechamento.

    A última é a que a cerca torna possível: um marcador de abertura sem um de
    fechamento deixa aberto onde a citação acaba, e um prompt cuja última linha é a
    fala do Aluno é o que a ordem de leitura do modelo pequeno espera. O par de
    marcadores é o que dá a uma e a outra ao mesmo tempo.
    """
    prompt = _prompt_do_turno(fazer_cliente)

    assert PERSONA in prompt
    assert INICIO_CONVERSA in prompt
    assert FIM_CONVERSA in prompt
    assert _MENSAGEM in prompt
    assert prompt.index(_MENSAGEM) > prompt.index(PERSONA)
    assert prompt.index(_MENSAGEM) > prompt.index(INICIO_CONVERSA)
    assert prompt.index(FIM_CONVERSA) > prompt.index(_MENSAGEM)
    assert prompt.count(_MENSAGEM) == 1


def test_o_aviso_da_cerca_vem_antes_do_marcador_de_abertura(
    fazer_cliente: FabricaCliente,
) -> None:
    """O aviso diz o que é o texto do Aluno, e ele é lido antes de encontrá-lo.

    O aviso sem a ordem seria um parágrafo a mais: o modelo encontraria a
    delimitação e o texto do Aluno antes de ler que aquilo é citação e não ordem.
    Ele vem logo antes da abertura por isso.
    """
    prompt = _prompt_do_turno(fazer_cliente)

    assert AVISO_CONVERSA in prompt
    assert prompt.index(AVISO_CONVERSA) < prompt.index(INICIO_CONVERSA)
    assert prompt.index(AVISO_CONVERSA) > prompt.index(PERSONA)


def test_o_historico_da_conversa_vai_dentro_da_cerca() -> None:
    """O histórico entra cercado, e não antes dela.

    A cerca abre antes do histórico de propósito: as falas anteriores do Aluno são
    entrada não confiável tanto quanto a mensagem de agora, e as respostas
    anteriores do S.A.U. são saída de modelo, que é tão pouco confiável quanto a
    entrada. Um histórico montado antes da abertura deixaria a parte mais longa do
    prompt sem cerca nenhuma.

    E o corte da janela acontece dentro da cerca: o que não cabe em
    `MENSAGENS_NO_PROMPT` não entra no prompt, e o que entra vem inteiro. São nove
    falas e a janela guarda seis, então as três mais antigas saem — e o que a
    afirmação abaixo mede é que elas saem mesmo, e não que a cerca as esconde.
    """
    falas = [
        Mensagem(papel="aluno", texto=f"pergunta {indice}", em=float(indice))
        for indice in range(MENSAGENS_NO_PROMPT + 2)
    ]
    falas.append(
        Mensagem(papel="sau", texto="Antes: o Termo de Compromisso já está assinado?", em=99.0)
    )

    prompt = montar_prompt(_MENSAGEM, falas)

    # A mais antiga que sobra é a que abre a janela: ela vem depois da abertura.
    mais_antiga_que_sobra = f"pergunta {MENSAGENS_NO_PROMPT - 3}"
    assert prompt.index(INICIO_CONVERSA) < prompt.index(mais_antiga_que_sobra)
    assert prompt.index(mais_antiga_que_sobra) < prompt.index(FIM_CONVERSA)
    # E as três que não cabem não estão no prompt, nem dentro nem fora da cerca.
    for indice in range(MENSAGENS_NO_PROMPT - 3):
        assert f"pergunta {indice}" not in prompt
    # A mensagem do turno é a penúltima linha da conversa, antes do fechamento —
    # e rotulada, como toda fala do histórico.
    assert prompt.splitlines()[-3] == f"Aluno: {_MENSAGEM}"
    assert prompt.splitlines()[-2] == FIM_CONVERSA


def test_o_historico_vai_antes_da_mensagem_do_turno() -> None:
    """A troca anterior vem antes da pergunta de agora, como no grafo.

    Um histórico montado depois da mensagem do turno inverteria a conversa para o
    modelo: ele leria a pergunta, responderia a ela, e só então descobriria que
    aquilo era a fala de três trocas atrás.
    """
    falas = [
        Mensagem(papel="aluno", texto="qual o prazo do termo de compromisso?", em=1.0),
        Mensagem(papel="sau", texto="Antes: a assinatura já saiu?", em=2.0),
    ]

    prompt = montar_prompt(_MENSAGEM, falas)

    assert prompt.index("prazo do termo de compromisso") < prompt.index(_MENSAGEM)
    assert prompt.index("prazo do termo de compromisso") > prompt.index(PERSONA)


def test_a_mensagem_do_turno_vem_rotulada_e_separada_do_historico() -> None:
    """A pergunta atual tem cabeçalho próprio e rótulo `Aluno:`, como o histórico.

    Sem o cabeçalho, a mensagem nova colava no histórico com uma linha em
    branco de separação; sem o rótulo, era a única fala sem dizer quem falou.
    As duas metades importam: o cabeçalho diz que aquilo é o presente, e o
    rótulo dá à pergunta atual a mesma forma das antigas.
    """
    falas = [
        Mensagem(papel="aluno", texto="qual o prazo do termo de compromisso?", em=1.0),
        Mensagem(papel="sau", texto="Antes: a assinatura já saiu?", em=2.0),
    ]

    prompt = montar_prompt(_MENSAGEM, falas)

    assert APRESENTACAO_DO_HISTORICO in prompt
    assert APRESENTACAO_DA_MENSAGEM in prompt
    assert prompt.index(APRESENTACAO_DO_HISTORICO) < prompt.index("prazo do termo de compromisso")
    assert prompt.index(APRESENTACAO_DA_MENSAGEM) > prompt.index("a assinatura já saiu?")
    assert prompt.index(APRESENTACAO_DA_MENSAGEM) < prompt.index(f"Aluno: {_MENSAGEM}")
    assert prompt.count(APRESENTACAO_DO_HISTORICO) == 1
    assert prompt.count(APRESENTACAO_DA_MENSAGEM) == 1


def test_o_historico_vazio_ganha_marcador_de_primeira_mensagem() -> None:
    """Na estreia, o lugar do histórico tem marcador fixo, e não seção ausente.

    Seção ausente o modelo lê como bloco faltando; marcador fixo ele lê como
    primeira mensagem, que é o que ela é. E a mensagem do turno continua
    rotulada mesmo sem nada antes dela.
    """
    prompt = montar_prompt(_MENSAGEM)

    assert HISTORICO_VAZIO in prompt
    assert prompt.index(HISTORICO_VAZIO) > prompt.index(INICIO_CONVERSA)
    assert prompt.index(HISTORICO_VAZIO) < prompt.index(APRESENTACAO_DA_MENSAGEM)
    assert prompt.splitlines()[-3] == f"Aluno: {_MENSAGEM}"


def test_o_prefixo_da_persona_e_travado_por_cache_de_prefixo() -> None:
    """O prefixo até `INICIO_CONVERSA` inclusive é idêntico, byte a byte, em dois turnos.

    O cache de prefixo do Ollama só funciona quando os primeiros bytes são
    exatamente iguais. Mover a persona para depois da conversa — ou trocar uma
    vírgula, um espaço ou a ordem de um parágrafo — quebra esse alinhamento: o
    Ollama não consegue reaproveitar o que já leu, e **todo turno volta a custar
    a leitura inteira do prompt** (0,02 s → 3,8 s), do primeiro ao último Aluno
    de um tráfego esparso.

    A mensagem de falha é intencionalmente dura: quebrar este teste não é um
    "refactor inofensivo de prompt", é mudar o que o cache pode reaproveitar.
    O teste compara o prefixo dos dois prompts montados com Alunos diferentes e
    históricos diferentes — se ele passa, o cache de prefixo da persona continua
    valendo. Se falha, a culpa é de quem mudou o prefixo antes de `INICIO_CONVERSA`.
    """
    aluno_1 = "Até que dia preciso assinar o termo de compromisso?"
    aluno_2 = "Já entreguei o relatório. O que vem depois?"

    historico_a = [
        Mensagem(papel="aluno", texto="Oi, bom dia", em=1.0),
        Mensagem(papel="sau", texto="Oi! Sobre o seu estágio, o que você precisa?", em=2.0),
    ]
    historico_b = [
        Mensagem(papel="aluno", texto="Outro Aluno, outra conversa", em=10.0),
        Mensagem(papel="sau", texto="Vamos por partes.", em=11.0),
        Mensagem(papel="aluno", texto="Terceira fala diferente", em=12.0),
    ]

    prompt_a = montar_prompt(aluno_1, historico_a)
    prompt_b = montar_prompt(aluno_2, historico_b)

    # O prefixo comum termina em INICIO_CONVERSA (inclusive). Depois dele começa
    # a conversa — que é o que muda entre os dois turnos.
    indice_a = prompt_a.index(INICIO_CONVERSA)
    indice_b = prompt_b.index(INICIO_CONVERSA)

    prefixo_a = prompt_a[: indice_a + len(INICIO_CONVERSA)]
    prefixo_b = prompt_b[: indice_b + len(INICIO_CONVERSA)]

    assert prefixo_a == prefixo_b, (
        "O prefixo do prompt até `INICIO_CONVERSA` mudou entre dois turnos. "
        "Isso quebra o **cache de prefixo** do Ollama: os 852 tokens da persona "
        "deixam de ser reaproveitados e todo turno volta a custar a leitura "
        "inteira do prompt (0,02 s → 3,8 s), do primeiro ao último Aluno. "
        "Não mude este prefixo — nem espaço, nem parágrafo, nem ordem — sem "
        "reconferir a medição. "
        f"Tamanhos: {len(prefixo_a)} vs {len(prefixo_b)}"
    )


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


def test_nenhuma_resposta_ditada_fora_do_exemplo_declarado(
    fazer_cliente: FabricaCliente,
) -> None:
    """Só o exemplo de Encaminhamento mostra resposta pronta; o resto descreve.

    O defeito já aconteceu duas vezes. A regra de frase fixa verbatim saiu em
    `3400b32` porque virava atrator para o 3B; o realinhamento de domínio a
    trouxe de volta dentro de `escopo_de_estagio` e `nao_inventar`, e a rodada
    seguinte mediu o estrago: de 45 execuções saíram 5 textos distintos, todos
    cópia literal de frase escrita aqui dentro, com o substantivo da pergunta
    trocado no buraco. O `f1` — "não consigo dormir e quero desabafar" — recebeu
    "só posso ajudar com dúvidas sobre processos de estágio".

    O ADR-0009 volta atrás de propósito: a linha de base mostra o modelo sabendo
    *quando* encerrar e não conseguindo *como* — cinco Perguntas-teste em 5
    tokens —, e por isso a persona mostra a forma uma vez, no exemplo declarado.
    O critério muda junto: nenhuma resposta ditada *fora do exemplo*, e o exemplo
    passa a ser o ponto que o teste verifica — turno completo de fora de escopo,
    perguntado e respondido de ponta a ponta, com Encaminhamento à Coordenação.
    """
    proibidos = ("exatamente", "exatamente e apenas", "texto fixo", "verbatim", "literalmente")

    for regra in REGRAS:
        achados = [termo for termo in proibidos if termo in regra.instrucao.lower()]
        assert not achados, (
            f"a regra {regra.id!r} manda o modelo repetir um texto do prompt "
            f"({', '.join(repr(t) for t in achados)}). O 3B devolve a frase em vez "
            f"de orientar: ele preenche o buraco da frase e para de ler a "
            f"pergunta. Descreva o comportamento em vez de ditar a resposta."
        )

    prompt = _prompt_do_turno(fazer_cliente)

    assert EXEMPLO_DE_ENCAMINHAMENTO in prompt
    assert "Aluno:" in EXEMPLO_DE_ENCAMINHAMENTO
    assert "S.A.U.:" in EXEMPLO_DE_ENCAMINHAMENTO
    assert "Coordenação de Estágios" in EXEMPLO_DE_ENCAMINHAMENTO


# --- O grounding: responder só do material e citar a Fonte (título + página) ---


def test_a_orientacao_de_fonte_chega_ao_modelo(fazer_cliente: FabricaCliente) -> None:
    """O modelo recebe a ordem de responder só do material recuperado.

    É esta instrução que segura a Alucinação do `CONTEXT.md`: sem ela, o S.A.U.
    menos recusador para de dizer "não sei" e passa a dizer algo vindo do
    próprio conhecimento dele. Quem observa a obediência é a pessoa, lendo o
    output; o que este teste segura é que a ordem chegou — responder só do
    recuperado, citar a Fonte (título do slide com a página) de cada trecho que
    sustentar a afirmação, e dizer que não encontrou e Encaminhar quando nenhum
    trecho sustentar. A decisão de consultar saiu do prompt do redator na #36, e
    com ela a menção a `buscar_no_manual`.
    """
    prompt = _prompt_do_turno(fazer_cliente)

    assert ORIENTACAO_DE_FONTE in prompt
    assert prompt.count(ORIENTACAO_DE_FONTE) == 1


# --- A persona do roteador: o prompt enxuto que decide se consulta o Manual ---


def test_o_prompt_do_roteador_abre_pela_persona_enxuta() -> None:
    """O prompt do roteador abre pela `PERSONA_DE_ROTEAMENTO`, e não pela do redator.

    A separação da #36 existe para que o roteador não carregue as regras de
    redação nem a `ORIENTACAO_DE_FONTE`: é o prompt enxuto que faz o modelo
    pequeno chamar a ferramenta, medido contra a persona inteira no ADR-0010. Um
    roteador aberto pela `PERSONA` voltaria ao defeito que a medição apontou.
    """
    prompt = montar_prompt_de_roteamento(_MENSAGEM)

    assert prompt.startswith(PERSONA_DE_ROTEAMENTO)
    assert PERSONA not in prompt
    assert ORIENTACAO_DE_FONTE not in prompt
    assert EXEMPLO_DE_ENCAMINHAMENTO not in prompt


def test_o_roteador_responde_sem_busca_apos_o_resultado_da_ferramenta() -> None:
    """Após o resultado da ferramenta, sem outra consulta, o roteador responde curto.

    É a instrução que evita o rascunho descartado: depois de receber o `tool`,
    o roteador que não precisa de outra consulta responde só "sem busca", em
    vez de redigir a resposta final — quem escreve ao Aluno é outra etapa, o
    redator. Sem ela, cada turno factual pagava uma geração longa cujo texto o
    grafo jogava fora, ficando só com as chamadas.
    """
    assert "quem escreve a resposta final ao Aluno é outra etapa" in PERSONA_DE_ROTEAMENTO
    prompt = montar_prompt_de_roteamento(_MENSAGEM)

    assert "quem escreve a resposta final ao Aluno é outra etapa" in prompt


def test_o_prompt_do_roteador_cerca_a_conversa_como_o_do_redator() -> None:
    """A cerca, a ordem da conversa e o sufixo do roteador são os mesmos do redator.

    É a extração `_montar_com_cerca` que impede os dois prompts de divergirem: o
    roteador precisa do mesmo contexto cercado para decidir, e o teste de cerca
    do redator passa a valer para ele. O sufixo `S.A.U.:` continua induzindo onde
    o modelo começa a gerar.
    """
    falas = [
        Mensagem(papel="aluno", texto="qual o prazo do termo de compromisso?", em=1.0),
        Mensagem(papel="sau", texto="Antes: a assinatura já saiu?", em=2.0),
    ]

    prompt = montar_prompt_de_roteamento(_MENSAGEM, falas)

    assert AVISO_CONVERSA in prompt
    assert prompt.index(INICIO_CONVERSA) > prompt.index(PERSONA_DE_ROTEAMENTO)
    assert prompt.index("a assinatura já saiu?") > prompt.index(INICIO_CONVERSA)
    assert prompt.index("a assinatura já saiu?") < prompt.index(_MENSAGEM)
    assert prompt.index(_MENSAGEM) < prompt.index(FIM_CONVERSA)
    assert prompt.endswith("S.A.U.:")


def test_o_historico_vazio_do_roteador_ganha_o_marcador_de_primeira_mensagem() -> None:
    """Sem histórico, o roteador recebe o mesmo marcador fixo do redator.

    O roteador decide a partir da mensagem de agora; na estreia, o lugar do
    histórico tem o mesmo marcador, para que ele leia "primeira mensagem" em vez
    de "bloco faltando". E a mensagem do turno continua rotulada mesmo sem nada
    antes dela.
    """
    prompt = montar_prompt_de_roteamento(_MENSAGEM)

    assert HISTORICO_VAZIO in prompt
    assert prompt.splitlines()[-3] == f"Aluno: {_MENSAGEM}"
    assert prompt.splitlines()[-2] == FIM_CONVERSA


def _normalizar(texto: str) -> str:
    """Tira espaços e aspas para comparar o runtime com o fonte.

    No fonte, cada instrução é uma sequência de literais adjacentes — com
    aspas e quebras de linha entre os pedaços — e em runtime ela é uma string
    só. Sem normalizar, a instrução "não aparece" nem no próprio
    `persona.py`, e o teste acima quebra com a lista de donos vazia em vez de
    quebrar com o segundo prompt.
    """
    return re.sub(r"[\s\"']", "", texto)
