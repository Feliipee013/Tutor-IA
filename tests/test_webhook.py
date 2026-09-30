"""Testes do handler do webhook do Telegram, sau/telegram/webhook.py.

O que se prova aqui é o fio do canal: update chega, update bruto é registrado, o
Aluno recebe o acuse de recibo sem esperar o modelo e, desde a #8, recebe a
resposta do modelo depois do acuse. Desde a #9 o turno também carrega a conversa do
Aluno: o histórico de um não vaza para o prompt de outro, e duas mensagens do mesmo
Aluno são respondidas na ordem em que chegaram. O transporte do Telegram e o do
modelo são falsos (`httpx.MockTransport`), então a suíte verifica as requisições que
sairiam de verdade em vez de simular o S.A.U.
"""

from __future__ import annotations

import json
import logging
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable, Iterator

import httpx
import pytest
from flask import Flask

from sau.config import carregar_configuracao
from sau.graph.state import RegistroDeConversas
from sau.inference.ollama import ErroDeInferencia, Resposta, TempoEsgotadoError
from sau.inference.semaphore import SemaforoDeInferencia
from sau.main import configurar_logging
from sau.persona import PERSONA
from sau.telegram import webhook
from sau.telegram.webhook import (
    CABECALHO_SECRET_TOKEN,
    TEXTO_ACK,
    TEXTO_BOAS_VINDAS,
    TEXTO_FALHA,
    TEXTO_FILA_CHEIA,
    TEXTO_REENGAJAMENTO,
    CredencialTelegramAusenteError,
    ExecutorTurno,
    criar_app,
    descobrir_url_publica,
    exigir_credenciais,
    main,
    registrar_webhook,
    texto_posicao_na_fila,
)

_TOKEN = "7123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw"
_SEGREDO = "chave-de-desenvolvimento"

_ENV_PADRAO = {
    "TELEGRAM_BOT_TOKEN": _TOKEN,
    "TELEGRAM_WEBHOOK_SECRET_TOKEN": _SEGREDO,
}

UPDATE_DO_ALUNO: dict[str, Any] = {
    "update_id": 999,
    "message": {
        "message_id": 42,
        "chat": {"id": 55_512_345, "type": "private"},
        "from": {"id": 55_512_345, "is_bot": False, "first_name": "Aluna"},
        "text": "qual o prazo de entrega da Atividade 2?",
    },
}

UPDATE_COM_FOTO: dict[str, Any] = {
    "update_id": 1000,
    "message": {
        "message_id": 43,
        "chat": {"id": 55_512_345, "type": "private"},
        "from": {"id": 55_512_345, "is_bot": False, "first_name": "Aluna"},
        "photo": [{"file_id": "AgAC...", "width": 90, "height": 90}],
        "caption": "olha essa imagem",
    },
}

LOGGER = "sau.telegram.webhook"

RESPOSTA_1 = "texto-resposta-1"
"""A resposta que o `ModeloQueEspelha` devolve no primeiro turno.

O texto é de fixture, e não uma frase que pareça conversa, por um motivo mecânico:
desde a #10 a persona entra no prompt de **todo** turno, e uma sentinela que
apareça em algum texto de regra faria as afirmações de vazamento do histórico
medirem a persona em vez da conversa do outro Aluno. Foi exatamente o que
"primeira resposta" virou, quando a regra de identidade passou a dizer "na
primeira resposta desta conversa". `test_a_sentinela_nao_esta_na_persona` trava
a condição.
"""

RESPOSTA_2 = "texto-resposta-2"
"""A resposta do modelo no segundo turno, pelo mesmo motivo da anterior."""


def _geracao(texto: str) -> dict[str, Any]:
    """O corpo de um `/api/generate` completo, como o `ClienteOllama` espera receber.

    Fica aqui, e não dentro da fixture que a usa, porque é o contrato do Ollama e
    não da guarda: a fixture registra o tráfego e precisa saber responder cada
    destino, e é esse "saber responder" que vira nome quando ele é uma função só.
    """
    return {
        "response": texto,
        "done": True,
        "done_reason": "stop",
        "eval_count": 11,
        "eval_duration": 1_000_000_000,
    }


class TelegramFalso:
    """Cliente do Telegram que registra o que o S.A.U. tentou enviar."""

    def __init__(
        self, status: int = 200, ao_entregar: Callable[[int, str], None] | None = None
    ) -> None:
        self.status = status
        self.requisicoes: list[httpx.Request] = []
        self.ao_entregar = ao_entregar
        self.cliente = httpx.Client(transport=httpx.MockTransport(self._responder))

    def _responder(self, request: httpx.Request) -> httpx.Response:
        self.requisicoes.append(request)
        if self.ao_entregar is not None and request.url.path.endswith("/sendMessage"):
            carga = json.loads(request.content)
            self.ao_entregar(carga["chat_id"], carga["text"])
        return httpx.Response(
            status_code=self.status,
            json={"ok": self.status == 200, "result": {"message_id": 1}},
            request=request,
        )

    def responder(self, url: Any) -> httpx.Response:
        """Responde a uma URL como se fosse o Telegram, sem passar por cliente.

        Existe para a guarda de "o acuse não espera o modelo": ela precisa
        registrar o tráfego de **qualquer** cliente, inclusive de um que o handler
        tenha aberto por conta própria para falar com o Ollama. A resposta
        continua sendo falsa, e é isso que mantém a promessa de nenhum teste
        depender de rede.
        """
        return self._responder(httpx.Request("POST", url))

    @property
    def enviados(self) -> list[httpx.Request]:
        """Só as chamadas de envio de mensagem, sem o resto do tráfico."""
        return [r for r in self.requisicoes if r.url.path.endswith("/sendMessage")]

    @property
    def textos(self) -> list[str]:
        """O texto de cada mensagem, na ordem em que o Aluno as receberia.

        A lista de `text` é a única afirmação que importa sobre o canal: o que o
        Aluno viu, e em que ordem. Ela aparece em quase todo teste de turno, e
        escrevê-la à mão a cada vez era o mesmo `json.loads` repetido seis vezes,
        com uma delas errando o campo e passando sem querer.
        """
        return [json.loads(envio.content)["text"] for envio in self.enviados]

    def textos_para(self, chat_id: int) -> list[str]:
        """O texto das mensagens de **um** Aluno, ignorando os outros.

        Desde a #11 existe mais de um Aluno por teste, porque a fila é por Aluno e
        afirmar a fila de um exige que exista outro atrás dele. Com o `textos`
        global, a posição que o segundo Aluno leu viria misturada com o acuse do
        primeiro, e o teste teria de escolher índices — que é a forma mais fácil de
        um teste de fila passar errado, porque o índice continua válido e o texto
        trocado não aparece em lugar nenhum.

        Filtrar por `chat_id` deixa cada afirmação sobre a fila do Aluno legível
        sem contagem manual, e é o mesmo `chat_id` que o update traz.
        """
        alvo = str(chat_id)
        return [
            json.loads(envio.content)["text"]
            for envio in self.enviados
            if json.loads(envio.content)["chat_id"] == alvo
        ]

    def fechar(self) -> None:
        self.cliente.close()


@pytest.fixture
def telegram() -> Iterator[TelegramFalso]:
    falso = TelegramFalso()
    yield falso
    falso.fechar()


# --- O aparato dos testes de fila e semáforo (a #11) ---

LIMITE_DE_ESPERA = 10.0
"""O teto de toda espera por evento destes testes.

Não é o tempo que um turno leva: é o tempo que o teste dá à thread do turno para
chegar em algum ponto conhecido. Passado ele, o teste falha em vez de passar com uma
espera que virou espera infinita — que é o defeito mais caro de um teste de
concorrência, porque passa no CI verde e trava no DEVELOPER.
"""


class Entregas:
    """O que cada Aluno já recebeu, e um jeito de o teste esperar por isso.

    Existe porque, desde a #11, o turno do Aluno entrega mensagens de fora do
    request: o acuse sai síncrono, mas a posição na fila e a resposta do modelo saem
    da thread do turno. Um teste que quisesse ver a posição do segundo Aluno teria
    de olhar a lista global e escolher o índice certo — e índice escolhido à mão é
    a forma mais fácil de um teste de fila passar errado, porque o índice continua
    válido mesmo quando o texto que ele deveria guardar mudou.

    Aqui a espera é por **condição**, com evento e prazo, e não por `sleep`: o teste
    diz quantas mensagens o Aluno `chat_id` deve ter recebido e espera até ter. A
    diferença entre esperar e reexaminar a lista é que o teste não depende de a
    thread ganhar a corrida contra o relógio da máquina.
    """

    def __init__(self) -> None:
        self._trava = threading.Lock()
        self._por_chat: dict[int, list[str]] = {}
        self._mudou = threading.Event()

    def ao_entregar(self, chat_id: int, texto: str) -> None:
        """Chamado pelo `TelegramFalso` a cada `sendMessage`, com o Aluno e o texto."""
        with self._trava:
            self._por_chat.setdefault(chat_id, []).append(texto)
        self._mudou.set()

    def textos(self, chat_id: int) -> list[str]:
        with self._trava:
            return list(self._por_chat.get(chat_id, []))

    def esperar(self, chat_id: int, quantos: int) -> list[str]:
        """Espera o Aluno `chat_id` ter recebido `quantos` mensagens, e as devolve.

        A espera é por `Event` com prazo, e o prazo existe para o teste **falhar**
        em vez de travar: um turno que nunca entrega é um turno quebrado, e a forma
        de descobrir isso é a asserção, não o timeout do pytest.
        """
        fim = time.monotonic() + LIMITE_DE_ESPERA
        while True:
            with self._trava:
                recebidas = list(self._por_chat.get(chat_id, []))
            if len(recebidas) >= quantos:
                return recebidas
            self._mudou.clear()
            if time.monotonic() > fim:
                raise AssertionError(
                    f"o Aluno {chat_id} recebeu {recebidas} e o teste esperava "
                    f"{quantos} mensagens"
                )
            self._mudou.wait(0.05)


class VooDePost:
    """Um POST no webhook rodando em thread, para o turno poder ficar esperando.

    O `_sincrono` roda o turno na thread do teste, o que é o que permite ao teste
    olhar o resultado do turno. Só que um turno que fica **esperando vaga** nunca
    termina, e um teste que espera por ele trava — daí a thread. O que o `VooDePost`
    troca é a asserção, nunca o tempo: ele só devolve o controle ao teste para que
    a outra mão do teste possa soltar a vaga.
    """

    def __init__(self, acao: Callable[[], None]) -> None:
        self.finalizado = threading.Event()
        self.erro: BaseException | None = None

        def rodar() -> None:
            try:
                acao()
            except BaseException as err:
                # O POST é de dentro do `app.test_client()`, e uma exceção que
                # morre na thread morre sem ninguém ver — que é como um teste de
                # fila passaria verde com o turno estourado.
                self.erro = err
            finally:
                self.finalizado.set()

        self.thread = threading.Thread(target=rodar, daemon=True)
        self.thread.start()

    def esperar(self) -> None:
        assert self.finalizado.wait(LIMITE_DE_ESPERA), "o POST não terminou"
        self.thread.join(timeout=LIMITE_DE_ESPERA)
        assert not self.thread.is_alive(), "a thread do POST sobreviveu ao teste"
        if self.erro is not None:
            raise self.erro




@pytest.fixture
def threads_do_turno(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[threading.Thread]]:
    """Captura as threads que o agendamento de produção criar, e as espera no fim.

    Só os dois testes do agendamento de verdade usam isto. A captura vem de um
    patch em `threading.Thread` porque a função de agendamento não devolve a
    thread que criou — ela chama `start()` e larga. A thread é a de verdade, e
    roda a ação; o patch só dá acesso ao objeto.

    O `join` no teardown é o que impede a thread de escrever depois do fim do
    caso: o `pytest` fecha a captura de log, e uma thread que escreve depois disso
    produz `Logging error` no meio da saída, escondendo a falha que a suíte
    deveria estar mostrando.
    """
    criada: list[threading.Thread] = []
    classe_real = threading.Thread

    def fabrica(*args: Any, **kwargs: Any) -> threading.Thread:
        thread = classe_real(*args, **kwargs)
        criada.append(thread)
        return thread

    monkeypatch.setattr(threading, "Thread", fabrica)
    yield criada
    for thread in criada:
        thread.join(timeout=5.0)


@pytest.fixture
def destinos_de_saida(monkeypatch: pytest.MonkeyPatch, telegram: TelegramFalso) -> list[str]:
    """Registra toda URL que o processo tentou chamar, venha de onde vier.

    O `TelegramFalso` só enxerga o `httpx.Client` que o teste injeta, e o handler
    pode abrir um cliente próprio para falar com o Ollama. Nesse caso nada seria
    registrado e uma guarda de "o acuse não espera o modelo" passaria com a
    garantia quebrada — foi o que a primeira versão desta PR fazia.

    Por isso o registro é no `httpx.Client.request`, e não no cliente injetado.
    Esse método é o funil por onde **todo** o tráfego HTTP do processo passa:
    `Client.post` e `Client.get` delegam a ele, e `httpx.post` e `httpx.request`
    de módulo abrem um `Client` e chamam o mesmo método. Patchear o `.post` — a
    versão anterior desta fixture — deixava passar de fininho uma chamada
    `.request`, que é a forma que a inferência da #8 usa para falar com o Ollama:
    a guarda ficava verde com a garantia quebrada.

    Cada destino é respondido no formato que ele espera: o Telegram recebe a
    resposta de `TelegramFalso` e o Ollama recebe um `/api/generate` de verdade,
    com o campo `response`. Sem isso o `ClienteOllama` real — que é o que a
    guarda precisa exercitar — cairia em "não devolveu o campo 'response'" e a
    prova da ordem viria de um turno que falhou por um motivo que não é o do
    teste.
    """
    destinos: list[str] = []
    endereco_do_modelo = carregar_configuracao(_ENV_PADRAO).ollama_base_url

    def request_do_cliente(
        _self: httpx.Client, *args: Any, **kwargs: Any
    ) -> httpx.Response:
        # As duas portas do funil chamam `request` de formas diferentes:
        # `Client.post` e `Client.get` passam `method` e `url` por posição, e o
        # `httpx.request` de módulo passa por nome. Uma substituta com `method` e
        # `url` declarados aceitaria as duas — o Python liga por nome quando a
        # chamada é nomeada. Pegamos de `args`/`kwargs` mesmo assim, para que a
        # forma da chamada deixe de ser informação que esta guarda carrega.
        url = kwargs["url"] if "url" in kwargs else args[1]
        destinos.append(str(url))
        if endereco_do_modelo in str(url):
            return httpx.Response(
                status_code=200,
                json=_geracao(ModeloFalso.texto),
                request=httpx.Request("POST", url),
            )
        return telegram.responder(url)

    monkeypatch.setattr(httpx.Client, "request", request_do_cliente)
    return destinos


class ModeloFalso:
    """O `ClienteOllama` do turno, falso: nenhum byte sai para o host.

    O grafo e o nó são os de verdade — só o modelo é falso. Um turno inteiro com
    o grafo falso passaria com o `webhook` desconectado do grafo, que é o
    defeito que a #8 fecha.
    """

    texto: str = "O prazo da entrega eu não sei."
    erro: ErroDeInferencia | None = None

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        self.prompts: list[str] = []

    def responder(self, prompt: str, *, opcoes: dict[str, Any] | None = None) -> Resposta:
        self.prompts.append(prompt)
        if self.erro is not None:
            raise self.erro
        return Resposta(
            texto=self.texto,
            primeiro_token_segundos=0.0,
            carga_segundos=0.0,
            avaliacao_prompt_segundos=0.0,
            segundos_totais=0.0,
            tokens_por_segundo=None,
            tokens_gerados=None,
            concluida=True,
            motivo_de_parada="stop",
        )


class ModeloQueFalha(ModeloFalso):
    """O mesmo modelo, com o Ollama fora do ar — a falha que a #8 precisa fechar."""

    texto = ""
    erro = ErroDeInferencia(
        "FALHA CRÍTICA: não consegui falar com o Ollama em "
        "http://host.docker.internal:11434/api/generate: Connection refused."
    )


class ModeloQueTempoAcabou(ModeloFalso):
    """O mesmo modelo, lento demais: o `OLLAMA_TIMEOUT` do `webhook` estourou."""

    texto = ""
    erro = TempoEsgotadoError(
        "FALHA CRÍTICA: o modelo 'llama3.2:3b' não respondeu em 120s. O Aluno teria "
        "ficado esperando esse tempo todo antes de qualquer erro, então a espera é o "
        "defeito e não a ausência de resposta."
    )


class ModeloQueNaoResponde(ModeloFalso):
    """O mesmo modelo, que volta sem escrever nada: falha sem exceção."""

    texto = "   \n  "


class ModeloQueSeguraAVaga(ModeloFalso):
    """O modelo que fica segurando a vaga até o teste mandar seguir.

    O `ModeloFalso` responde na hora, e com ele a vaga do semáforo dura o tempo de um
    `responder` — tempo demais curto para o teste meter um segundo Aluno na fila
    antes de a vaga voltar. Este modelo **para dentro do semáforo**: a chamada
    acontece, a vaga está ocupada, e o turno só devolve a resposta quando o teste
    manda. É o que transforma "vaga ocupada" em um estado que o teste controla, em
    vez de uma janela de tempo que o teste torce para acertar.

    A guarda do `maximo_simultaneo` é o que fecha o critério de paralelismo: ela
    guarda o **maior** número de chamadas que coexistiram, e não o total. O total
    não diria nada — cinco chamadas em série e cinco chamadas ao mesmo tempo dão
    o mesmo total, e só a segunda coisa é paralelismo. O contador de `chegadas` é o
    que permite ao teste esperar por "os dois já entraram" sem `sleep` e sem olhar o
    meio do caminho.

    O estado é todo de classe porque o modelo entra por `monkeypatch.setattr` e o
    turno instancia um objeto novo a cada chamada: com estado de instância, cada
    `responder` teria um portão seu e o teste não teria como sinalizar nenhum deles.
    O `destravar` zera tudo, porque estado de classe que sobrevive ao teste é a
    forma mais curta de um teste passar porque o anterior deixou o portão aberto.

    A trava cobre os contadores e **não** o `responder`: o `responder` é justamente
    o que fica parado segurando a vaga, e trancá-lo tornaria o modelo uma fila.
    """

    texto: str = "O prazo da entrega eu não sei."

    _tranca: threading.Lock = threading.Lock()
    _chegou: threading.Event = threading.Event()
    _solta: threading.Event = threading.Event()
    _dentro: int = 0
    _chegadas: int = 0
    maximo_simultaneo: int = 0
    turnos: list[str] = []

    @classmethod
    def destravar(cls) -> None:
        """Zera o portão e os contadores antes de cada teste, para não herdar nada."""
        cls._chegou = threading.Event()
        cls._solta = threading.Event()
        cls._dentro = 0
        cls._chegadas = 0
        cls.maximo_simultaneo = 0
        cls.turnos = []

    @classmethod
    def esperar_chegadas(cls, quantas: int) -> None:
        """Espera `quantas` chamadas terem começado, e falha com o número que ficou.

        É a espera por "os dois Alunos já estão no modelo". Ela é por evento com
        prazo e não por `sleep`, para que a falha seja uma asserção dizendo quantos
        chegaram e qual foi o maior paralelismo, e não um travamento do pytest.

        A trava é tomada só para **ler** o contador e largada antes de esperar, e essa
        é a diferença entre funcionar e travar: quem liga o evento é o `responder`, e
        ele precisa da mesma trava para contar a chegada. Esperar com a trava na mão
        seria um deadlock cujo sintoma é que nada chega jamais: o contador ficaria
        em zero para sempre e o teste só terminaria no prazo, sem nunca ter visto uma
        chamada.
        """
        fim = time.monotonic() + LIMITE_DE_ESPERA
        while True:
            with cls._tranca:
                if cls._chegadas >= quantas:
                    return
            restante = fim - time.monotonic()
            if restante <= 0:
                with cls._tranca:
                    raise AssertionError(
                        f"só {cls._chegadas} de {quantas} chamadas chegaram ao modelo, "
                        f"e o maior paralelismo visto foi {cls.maximo_simultaneo}"
                    )
            # A releitura do contador é o que fecha a janela entre lê-lo e
            # esperar: se a chegada acontecer nesse meio-tempo, o evento já está ligado
            # e o `wait` volta na hora, sem perder o sinal.
            cls._chegou.wait(restante)
            cls._chegou.clear()

    @classmethod
    def soltar(cls) -> None:
        """Libera todos os turnos que estão segurando a vaga."""
        cls._solta.set()

    def responder(self, prompt: str, *, opcoes: dict[str, Any] | None = None) -> Resposta:
        self.prompts.append(prompt)
        cls = type(self)
        with cls._tranca:
            cls.turnos.append(prompt)
            cls._dentro += 1
            cls._chegadas += 1
            cls.maximo_simultaneo = max(cls.maximo_simultaneo, cls._dentro)
            cls._chegou.set()
        cls._solta.wait(LIMITE_DE_ESPERA)
        with cls._tranca:
            cls._dentro -= 1
        return Resposta(
            texto=self.texto,
            primeiro_token_segundos=0.0,
            carga_segundos=0.0,
            avaliacao_prompt_segundos=0.0,
            segundos_totais=0.0,
            tokens_por_segundo=None,
            tokens_gerados=None,
            concluida=True,
            motivo_de_parada="stop",
        )


def _sem_turno(*_args: Any) -> None:
    """Executor que não roda turno nenhum, para os testes que não são sobre o turno."""


def _anotando(registros: list[str]) -> ExecutorTurno:
    """Executor que anota a mensagem de cada turno, para afirmar o que entrou nele.

    O que interessa nesses testes é a lista, não o executor: o grafo está sendo
    ignorado de propósito, e a pergunta é só o que o `webhook` entregou a ele.

    A assinatura acompanha a do `ExecutorTurno` inteiro, `registro` e `semaforo`
    incluídos, porque é o que o `_atender_webhook` passa. Um executor com menos
    parâmetros funciona em tempo de execução e quebra o mypy — e o que o mypy barra
    aqui é o caminho em que a assinatura do executor sai de sincronia com a do turno
    de produção sem ninguém perceber, que é a forma como o turno real deixaria de
    ser testado.
    """

    def anotar(
        _config: Any,
        _chat_id: int,
        texto: str,
        _registro: Any,
        _semaforo: SemaforoDeInferencia,
        _client: Any,
    ) -> None:
        registros.append(texto)

    return anotar


def _sincrono(acao: Callable[[], None]) -> None:
    """Agenda o turno na thread do próprio teste, para poder esperar por ele."""
    acao()


def _app(
    telegram: TelegramFalso,
    registro: RegistroDeConversas | None = None,
    env: dict[str, str] | None = None,
    executor: ExecutorTurno | None = _sem_turno,
    agendar: Callable[[Callable[[], None]], None] | None = _sincrono,
    semaforo: SemaforoDeInferencia | None = None,
) -> Flask:
    """Monta o app com o registro, o turno, o agendamento e o semáforo injetados.

    O executor e o agendamento são substituídos em **quase** todos os testes daqui.
    O executor de produção monta um `ClienteOllama` de verdade e tentaria falar
    com o Ollama da máquina: a suíte passaria a depender da rede, e a thread
    poderia rodar depois do fim do teste, com o cliente de Telegram já fechado. Foi
    o que aconteceu na primeira versão desta PR — o teste do acuse ficou vermelho
    por causa de um `RuntimeError` de thread órfã.

    O `registro` é substituído pela mesma razão e por uma a mais: sem ele o `criar_app`
    abriria `conversas.db` no diretório de trabalho, que é a raiz do repositório, e a
    suíte passaria a escrever no meio dos arquivos versionados. Passar `None` é o
    caminho de produção: `criar_app` monta o registro a partir da configuração. É
    assim que os testes do turno rodam o `webhook` de verdade sem sair da rede — e,
    nos dois que passam `agendar=None`, a thread de verdade também.

    O `semaforo` é a terceira substituição com a mesma função: os testes de fila
    precisam de um `k` conhecido e de conseguir **segurar** a vaga para que outro
    turno encontre a fila ocupada, e o semáforo de produção com o `k=2` do ambiente
    não deixa o teste afirmar nem "um turno" nem "dois". Passar `None` é o caminho de
    produção: `criar_app` monta o semáforo a partir de `INFERENCIA_K`.
    """
    config = carregar_configuracao({**_ENV_PADRAO, **(env or {})})
    registro_do_turno = registro or _registro_de_teste()
    return criar_app(
        config, telegram.cliente, registro_do_turno, executor, agendar, semaforo
    )


class RegistroDeTeste:
    """Um `RegistroDeConversas` num arquivo temporário, com a pasta que o segura.

    Existe como classe e não como função porque o `TemporaryDirectory` precisa
    sobreviver ao registro: apagada a pasta antes de `fechar()`, a conexão fica
    apontando para arquivo que não existe. A pasta é do `TemporaryDirectory`, e o
    `TemporaryDirectory` é registrado para ser limpo no fim do teste pela fixture
    `_fecha_registros`, que é o que garante que nem o `.db` nem o `-wal` fiquem na
    raiz do repositório.

    O caminho é único por instância justamente para que dois testes rodando ao mesmo
    tempo não compartilhem arquivo — o SQLite serializa escrita, e um teste que
    espera outro é um teste que passa por acidente.
    """

    def __init__(self, diretorio: Path | None = None) -> None:
        self.dono: tempfile.TemporaryDirectory[str] | None = None
        if diretorio is None:
            self.dono = tempfile.TemporaryDirectory(prefix="sau-conversas-")
            pasta = Path(self.dono.name)
        else:
            pasta = diretorio
        self.registro = RegistroDeConversas(str(pasta / "conversas.db"))


_REISTROS_ABERTOS: list[RegistroDeTeste] = []


def _registro_de_teste() -> RegistroDeConversas:
    """Fabrica o registro do turno com um arquivo temporário atrás dele."""
    teste = RegistroDeTeste()
    _REISTROS_ABERTOS.append(teste)
    return teste.registro


@pytest.fixture(autouse=True)
def _fecha_registros() -> Iterator[None]:
    """Fecha os registros que os testes abriram e apaga os arquivos deles.

    Autouse e depois das outras fixtures de propósito: um `registro` aberto
    sobreviveria ao fim do teste com a conexão viva, e o `TemporaryDirectory`
    apagado embaixo dela deixaria a pasta `-wal` para trás. Fechar na saída garante
    que a pasta some inteira.
    """
    yield
    for teste in _REISTROS_ABERTOS:
        teste.registro.fechar()
        if teste.dono is not None:
            teste.dono.cleanup()
    _REISTROS_ABERTOS.clear()


def _postar(app: Flask, update: Any, *, segredo: str | None = _SEGREDO) -> Any:
    """POST no webhook. Sem `segredo`, vai sem o header, como o Telegram faria
    se o `setWebhook` tivesse sido feito sem `secret_token`."""
    cabecalhos = {} if segredo is None else {CABECALHO_SECRET_TOKEN: segredo}
    return app.test_client().post("/webhook", json=update, headers=cabecalhos)


# --- O update bruto é registrado, que é o que o ticket promete depurar ---


def test_webhook_registra_o_update_bruto(
    telegram: TelegramFalso, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger=LOGGER):
        _postar(_app(telegram), UPDATE_DO_ALUNO)

    registros = [r.getMessage() for r in caplog.records]
    algum = next((r for r in registros if "update_telegram bruto" in r), None)
    assert algum is not None, f"o update bruto não foi registrado: {registros}"
    # O update inteiro, não um resumo: é o que serve para depurar o payload.
    assert json.loads(algum.split("bruto: ", 1)[1]) == UPDATE_DO_ALUNO


def test_update_bruto_sai_no_stdout_com_o_log_do_operador(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """O update bruto precisa sair onde o operador olha, que é o AC #3.

    A primeira versão desta PR logava em INFO num logger sem handler.
    `logging.getLogger(__name__)` sozinho fica com nível efetivo WARNING, então o
    registro era descartado antes de chegar a qualquer handler: o único log que
    saía era o de payload inválido, ou seja, o log real registrava um update que
    não chegou e o que chegou sumia.

    A diferença em relação ao teste acima é que aqui passa pelo
    `configurar_logging` de verdade, o mesmo que o `main` chama na subida. Com
    `caplog` o teste instala o próprio handler e passaria mesmo com a
    configuração quebrada — que era exatamente o defeito, e por isso ele ficava
    invisível. Aqui a afirmação é sobre o stdout que o operador recebe.
    """
    raiz = logging.getLogger()
    handlers, nivel = raiz.handlers[:], raiz.level
    try:
        configurar_logging()
        telegram = TelegramFalso()
        try:
            _postar(_app(telegram), UPDATE_DO_ALUNO)
        finally:
            telegram.fechar()
    finally:
        raiz.handlers[:] = handlers
        raiz.setLevel(nivel)

    saida = capsys.readouterr().out
    assert "update_telegram bruto" in saida, f"o update bruto não saiu no stdout: {saida!r}"
    assert str(UPDATE_DO_ALUNO["update_id"]) in saida


def _nao_sobe_servidor(*_args: Any, **_kwargs: Any) -> None:
    """Substitui `Flask.run` para o teste do entrypoint não abrir uma porta."""


def test_entrypoint_do_webhook_configura_o_log_antes_do_banner(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """O `main` do webhook precisa configurar o log, e este é o AC #3.

    O teste anterior já prova que o update bruto sai no stdout **quando** o log
    está configurado, mas ele configura o log com a própria mão. Ninguém o
    provava: os dois testes passavam mesmo com o `configurar_logging` removido
    do `main`, porque nenhum deles passa pelo entrypoint. Este passa — chama o
    `main` de verdade, com as duas credenciais no ambiente, e só neutraliza o
    `Flask.run` para não subir servidor.

    O banner é o que faz a asserção: um `logger.info` num logger sem handler, em
    raiz WARNING, é descartado antes de chegar a lugar nenhum. Ele aparece no
    stdout se, e somente se, o `configurar_logging` rodou.
    """
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", _TOKEN)
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET_TOKEN", _SEGREDO)
    monkeypatch.setattr(Flask, "run", _nao_sobe_servidor)

    raiz = logging.getLogger()
    handlers, nivel = raiz.handlers[:], raiz.level
    try:
        # O estado de quem não configurou log nenhum: raiz sem handler, em
        # WARNING. Deixá-lo explícito é o que torna a falha limpa em vez de
        # depender do que o teste anterior deixou por trás.
        raiz.handlers[:] = []
        raiz.setLevel(logging.WARNING)
        main()
    finally:
        raiz.handlers[:] = handlers
        raiz.setLevel(nivel)

    saida = capsys.readouterr().out
    assert "S.A.U. - webhook do Telegram" in saida, f"o banner não saiu no stdout: {saida!r}"


def test_entrypoint_do_webhook_aplica_o_log_level_do_ambiente(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """O `LOG_LEVEL` do ambiente precisa chegar ao log do serviço, e este é o AC #3.

    O `main` do webhook chama `configurar_logging` duas vezes: uma antes de ler a
    configuração, para que uma configuração inválida saia no mesmo formato de todo
    o resto, e outra depois, com o nível que a própria configuração pediu. Ninguém
    provava a segunda. A suíte ficava verde com ela removida — `LOG_LEVEL` era
    lido do ambiente e jogado fora, e o operador que pedia `DEBUG` para depurar
    recebia `INFO` sem nenhum aviso.

    O módulo do webhook não tem nenhum `logger.debug`, então este teste não pode
    procurar um registro que não existe. Ele faz as duas coisas que importam:
    confere o nível efetivo da raiz, e emite de verdade um registro de DEBUG
    **depois** do `main`, para o stdout. A segunda é a que vale — prova que o
    operador veria a linha, e não só que uma configuração mudou.
    """
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", _TOKEN)
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET_TOKEN", _SEGREDO)
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setattr(Flask, "run", _nao_sobe_servidor)

    marcador = "marcador de depuração que o operador precisa ver"
    raiz = logging.getLogger()
    handlers, nivel = raiz.handlers[:], raiz.level
    try:
        raiz.handlers[:] = []
        raiz.setLevel(logging.WARNING)
        main()
        assert raiz.level == logging.DEBUG, (
            f"o LOG_LEVEL=DEBUG do ambiente não foi aplicado: raiz ficou em {raiz.level}"
        )
        # Depois do `main`, com o nível que ele deixou: é o caminho do operador.
        logging.getLogger(LOGGER).debug(marcador)
    finally:
        raiz.handlers[:] = handlers
        raiz.setLevel(nivel)

    saida = capsys.readouterr().out
    assert marcador in saida, f"o DEBUG não chegou ao stdout do operador: {saida!r}"


def test_linha_de_log_do_webhook_traz_o_prefixo_do_sau_e_o_nome_do_servico(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A linha do webhook diz `[SAU]` e o nome do serviço que a emitiu.

    O prefixo é do S.A.U. e não do serviço: `bot` está na seção *Evite* do
    `CONTEXT.md`, e o serviço já está identificado na própria linha pelo nome do
    módulo — `sau.telegram.webhook` contra `sau.main`. O prefixo `[SAU-BOT]`
    rotulava como "bot" a linha de um serviço que é o canal do Telegram, e
    apontava para o serviço errado para quem fosse filtrar por ele.

    Passa pelo `main` de verdade porque é a linha que o operador recebe que está
    em questão, não o que o `configurar_logging` produziria chamado na mão.
    """
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", _TOKEN)
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET_TOKEN", _SEGREDO)
    monkeypatch.setattr(Flask, "run", _nao_sobe_servidor)

    raiz = logging.getLogger()
    handlers, nivel = raiz.handlers[:], raiz.level
    try:
        main()
    finally:
        raiz.handlers[:] = handlers
        raiz.setLevel(nivel)

    saida = capsys.readouterr().out
    linha = next(
        (texto for texto in saida.splitlines() if "S.A.U. - webhook do Telegram" in texto),
        None,
    )
    assert linha is not None, f"o banner não saiu no stdout: {saida!r}"
    # `[SAU]` fecha com o colchete, e é isso que barra o prefixo antigo:
    # `[SAU-BOT]` não contém `[SAU]`.
    assert "[SAU]" in linha, f"o prefixo do S.A.U. não está na linha: {linha!r}"
    assert f"{LOGGER}:" in linha, f"o nome do serviço não está na linha: {linha!r}"


# --- O Aluno recebe o acuse de recibo, que é o que dá nome ao ticket ---


def test_webhook_envia_o_acuse_ao_aluno(telegram: TelegramFalso) -> None:
    _postar(_app(telegram), UPDATE_DO_ALUNO)

    assert len(telegram.enviados) == 1
    envio = telegram.enviados[0]
    assert envio.method == "POST"
    assert envio.url.path == f"/bot{_TOKEN}/sendMessage"
    assert json.loads(envio.content) == {"chat_id": 55_512_345, "text": TEXTO_ACK}


def test_webhook_responde_200_ao_telegram(telegram: TelegramFalso) -> None:
    assert _postar(_app(telegram), UPDATE_DO_ALUNO).status_code == 200


def test_o_acuse_sai_antes_de_o_turno_comecar(
    telegram: TelegramFalso, destinos_de_saida: list[str]
) -> None:
    """O acuse sai antes de o turno começar. Esta é a garantia da #5 desde a #8.

    Antes da #8 o teste afirmava que nenhum tráfico de modelo saía do processo, o
    que era verdade porque não havia inferência nenhuma. Com o turno no
    `webhook` essa afirmação não pode continuar: o modelo é chamado, e é chamado
    por este mesmo serviço. O que continua verdadeiro, e é o que o ADR-0001 pede,
    é a **ordem**: o Aluno levou o acuse antes de qualquer inferência começar.

    A ordem é afirmada pela **sequência inteira de tráfego**, e não por uma
    contagem vista de dentro do turno. Aqui vão as três peças de verdade — o
    `ClienteOllama` real, o grafo real e o `sendMessage` real —, e a fixture
    registra toda URL que saiu do processo, venha de onde vier. A lista sai nesta
    ordem: Telegram, modelo, Telegram. Um turno disparado antes do acuse a
    inverteria para modelo, Telegram, Telegram, e a lista inteira é a asserção —
    não só o seu primeiro elemento.

    A versão anterior desta guarda afirmava duas coisas que nada exercitava: que
    nenhum destino estava fora do Telegram, e que o acuse não esperou o modelo.
    Com o executor injetado as duas eram verdade por construção, porque o modelo
    nunca era chamado: a guarda media o vazio e passava. Aqui quem chama o modelo
    é o `ClienteOllama` de verdade, e as duas viram consequência da sequência.
    """
    config = carregar_configuracao(_ENV_PADRAO)
    para_o_telegram = f"{config.telegram_api_base}/bot{_TOKEN}/sendMessage"
    para_o_modelo = f"{config.ollama_base_url}/api/generate"

    _postar(_app(telegram, executor=None), UPDATE_DO_ALUNO)

    assert destinos_de_saida == [para_o_telegram, para_o_modelo, para_o_telegram], (
        f"o turno não rodou depois do acuse, ou rodou por outra via: {destinos_de_saida}"
    )


# --- O turno: a mensagem do Aluno chega ao modelo e a resposta volta ---


def test_a_mensagem_do_aluno_chega_ao_modelo_e_a_resposta_volta(
    telegram: TelegramFalso, monkeypatch: pytest.MonkeyPatch
) -> None:
    """O caminho da #8 inteiro, com o grafo, o nó e o modelo de verdade.

    A lista de textos enviados ao Telegram é a prova de ponta a ponta: acuse
    primeiro, resposta do modelo depois, na ordem em que o Aluno recebe. É o
    critério de aceitação da issue, e ele é de observável — o que o Aluno leva —
    e não de estado interno do grafo.
    """
    monkeypatch.setattr(webhook, "ClienteOllama", ModeloFalso)

    _postar(_app(telegram, executor=None), UPDATE_DO_ALUNO)

    assert telegram.textos == [TEXTO_ACK, ModeloFalso.texto]
    assert all(
        json.loads(envio.content)["chat_id"] == 55_512_345
        for envio in telegram.enviados
    )


def test_o_texto_do_aluno_e_a_mensagem_que_o_grafo_recebe(
    telegram: TelegramFalso, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pergunta do modelo é a do Aluno, e não uma constante do grafo.

    Um turno que respondesse a uma pergunta fixa passaria pelo teste do caminho
    inteiro acima, porque o texto do modelo voltaria igual. Aqui o modelo falso
    guarda o prompt que recebeu, e ele tem que conter a mensagem do update.

    A afirmação é `in` e não `endswith` desde a #10: o prompt termina no marcador
    de fechamento da cerca, que é o que impede a mensagem do Aluno de ser lida como
    instrução. Que a fala do Aluno seja a última antes do fechamento é o que
    `test_persona.py` afirma, no módulo que monta o prompt.
    """
    prompts: list[str] = []

    class ModeloQueGuarda(ModeloFalso):
        def responder(self, prompt: str, *, opcoes: dict[str, Any] | None = None) -> Resposta:
            prompts.append(prompt)
            return super().responder(prompt, opcoes=opcoes)

    monkeypatch.setattr(webhook, "ClienteOllama", ModeloQueGuarda)

    _postar(_app(telegram, executor=None), UPDATE_DO_ALUNO)

    assert len(prompts) == 1
    assert UPDATE_DO_ALUNO["message"]["text"] in prompts[0]


def test_falha_do_modelo_vira_mensagem_ao_aluno_e_nao_stack_trace(
    telegram: TelegramFalso,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Ollama fora vira frase amigável, e o motivo fica com o operador.

    As duas metades importam. O Aluno recebe `TEXTO_FALHA`, que não é stack trace
    e não é a mensagem técnica do `ErroDeInferencia` — ela diz "FALHA CRÍTICA",
    a URL e a porta do host, e nenhuma dessas pertence a quem perguntou. O
    operador recebe o motivo inteiro no log do turno, porque a frase do Aluno não
    diz por que a resposta não veio.
    """
    monkeypatch.setattr(webhook, "ClienteOllama", ModeloQueFalha)

    with caplog.at_level(logging.ERROR, logger=LOGGER):
        resposta = _postar(_app(telegram, executor=None), UPDATE_DO_ALUNO)

    assert resposta.status_code == 200
    assert telegram.textos == [TEXTO_ACK, TEXTO_FALHA]

    # O motivo completo foi para o log, e não para o Aluno.
    assert "FALHA CRÍTICA" in caplog.text
    assert "11434" in caplog.text
    assert not any(
        "FALHA CRÍTICA" in texto or "11434" in texto for texto in telegram.textos
    )


def test_timeout_do_modelo_vira_mensagem_ao_aluno(
    telegram: TelegramFalso,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """O timeout é caminho próprio, e não o mesmo erro por herança.

    `TempoEsgotadoError` é subclasse de `ErroDeInferencia`, então o `except` do
    turno pega as duas sem um braço só para o timeout. O risco é esse mesmo: um
    `except ErroDeInferencia` estreitado por engano deixaria o timeout escapar, e
    o teste da falha de conexão continuaria verde.

    A espera é o defeito que importa aqui, e é o que a mensagem do log diz: o
    modelo não estava fora, estava lento. O Aluno recebe a mesma frase de sempre,
    porque para ele a diferença não muda nada — ele não recebeu resposta.
    """
    monkeypatch.setattr(webhook, "ClienteOllama", ModeloQueTempoAcabou)

    with caplog.at_level(logging.ERROR, logger=LOGGER):
        _postar(_app(telegram, executor=None), UPDATE_DO_ALUNO)

    assert telegram.textos == [TEXTO_ACK, TEXTO_FALHA]
    assert "não respondeu em" in caplog.text


def test_resposta_vazia_do_modelo_vira_mensagem_de_falha(
    telegram: TelegramFalso,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Resposta sem texto não vira `sendMessage` com texto vazio.

    O `ClienteOllama` trata `response` ausente como erro, mas `response` vazio é
    resposta válida para ele: o Ollama devolve isso quando o modelo para sem
    escrever. Entregar esse vazio ao Telegram é pior que falhar — o `sendMessage`
    é recusado com 400, o turno não vira erro nenhum, e o Aluno fica com o acuse e
    sem nenhum sinal do motivo.

    O teste usa um texto só de espaço, e não string vazia, porque é esse o caso
    que a checagem precisa pegar: o Telegram também recusa um texto que não tem
    nada visível, mesmo que o envio seja aceito.
    """
    monkeypatch.setattr(webhook, "ClienteOllama", ModeloQueNaoResponde)

    with caplog.at_level(logging.ERROR, logger=LOGGER):
        _postar(_app(telegram, executor=None), UPDATE_DO_ALUNO)

    assert telegram.textos == [TEXTO_ACK, TEXTO_FALHA]
    assert "sem texto" in caplog.text


def test_o_turno_roda_na_thread_de_producao(
    telegram: TelegramFalso,
    destinos_de_saida: list[str],
    threads_do_turno: list[threading.Thread],
) -> None:
    """O caminho de produção inteiro: thread de verdade, cliente de verdade, ordem de verdade.

    Todo o resto da suíte agenda o turno de forma síncrona, porque é assim que se
    afirma uma ordem sem corrida. Esta é a exceção: aqui a agendação é a de
    verdade, a do `criar_app` sem parâmetro, o `ClienteOllama` é o de verdade e o
    grafo é o de verdade. Só o transporte é falso.

    E a afirmação é a **ordem do tráfego inteiro**, a mesma de
    `test_o_acuse_sai_antes_de_o_turno_comecar`, e não a contagem de mensagens. A
    contagem passaria com o turno rodando antes do acuse, desde que as duas
    mensagens saíssem; a ordem não passa. Sem isto, a garantia do ADR-0001 valeria
    só no agendamento do teste, e o agendamento de produção — que é o que o
    `docker compose` sobe — ficaria sem prova.

    A thread precisa ser esperada antes de afirmar: o `post` volta antes de o
    turno terminar, e o caso acabaria com a thread ainda escrevendo depois do fim
    dele. A fixture `threads_do_turno` é quem espera.

    O que o Aluno recebeu não é afirmado aqui, e é de propósito: sob a
    `destinos_de_saida` o Telegram é respondido pela própria fixture, com uma
    requisição sintetizada e sem corpo, então os textos entregues são de outro
    teste — o `test_a_mensagem_do_aluno_chega_ao_modelo_e_a_resposta_volta`, que
    usa o cliente do `TelegramFalso` de verdade. A sequência de tráfego já prova
    que as duas mensagens saíram, e em que ordem.
    """
    config = carregar_configuracao(_ENV_PADRAO)

    resposta = _postar(_app(telegram, executor=None, agendar=None), UPDATE_DO_ALUNO)
    for thread in threads_do_turno:
        thread.join(timeout=5.0)

    assert resposta.status_code == 200
    assert destinos_de_saida == [
        f"{config.telegram_api_base}/bot{_TOKEN}/sendMessage",
        f"{config.ollama_base_url}/api/generate",
        f"{config.telegram_api_base}/bot{_TOKEN}/sendMessage",
    ], f"o turno não rodou depois do acuse, ou rodou por outra via: {destinos_de_saida}"


def test_a_thread_do_turno_e_daemon(threads_do_turno: list[threading.Thread]) -> None:
    """A thread do turno é daemon, e a razão é o `docker compose down`.

    Uma thread presa no timeout do modelo não pode segurar o processo na hora de
    derrubar a stack: o `down` ficaria esperando um modelo que não responde. Com
    `daemon=True` o processo sai e a thread morre junto.

    O teste chama a função de agendamento direto, e não o app inteiro, porque o
    que se afirma aqui é o `daemon` da thread — e o turno inteiro em thread real
    já é o teste de cima. Uma ação que não faz nada basta: a thread é criada do
    mesmo jeito, com a mesma flag.
    """
    rodou = threading.Event()
    webhook._agendar(rodou.set)

    assert rodou.wait(5.0), "a thread do turno não rodou a ação"
    assert [t.daemon for t in threads_do_turno] == [True]


def test_erro_inesperado_no_turno_vira_mensagem_ao_aluno(
    telegram: TelegramFalso,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Um erro que não é do modelo também vira frase para o Aluno.

    `ErroDeInferencia` é o caminho previsto: o `ClienteOllama` transforma timeout,
    conexão, HTTP e JSON inválido nela. Mas o grafo também pode estourar, e um
    `KeyError` de estado faltando não é `ErroDeInferencia`. Quem está do outro
    lado é uma thread, e exceção que sai de uma thread morre com ela: sem log e sem
    o Aluno saber que o turno nem aconteceu. O `except` largo no executor existe
    para essa borda, e este teste é o que a segura.

    A diferença em relação ao teste do `ErroDeInferencia` está no log: aqui a
    stack tem de estar lá. O Aluno recebe a mesma frase nos dois casos, porque para
    ele é a mesma coisa; quem conserta o serviço só consegue fazer isso se o motivo
    técnico tiver sobrevivido.
    """

    class ModeloQueEstoura(ModeloFalso):
        def responder(self, prompt: str, *, opcoes: dict[str, Any] | None = None) -> Resposta:
            raise KeyError("resposta")

    monkeypatch.setattr(webhook, "ClienteOllama", ModeloQueEstoura)

    with caplog.at_level(logging.ERROR, logger=LOGGER):
        _postar(_app(telegram, executor=None), UPDATE_DO_ALUNO)

    assert telegram.textos == [TEXTO_ACK, TEXTO_FALHA]
    assert "erro que não é do modelo" in caplog.text
    assert "KeyError" in caplog.text, "a stack do erro inesperado não foi para o log"


def test_telegram_recusando_a_resposta_nao_vira_5xx_e_nao_vira_excecao(
    telegram: TelegramFalso, caplog: pytest.LogCaptureFixture
) -> None:
    """O Telegram recusando a resposta é registrado, e o webhook segue de pé.

    Este é o furo honesto que sobrou depois do caminho feliz: o acuse sai, o turno
    roda, e a entrega da resposta é recusada pela API. O Aluno fica com o acuse e
    silêncio. Não há o que fazer no `#8` — a mensagem saiu do sistema e o Telegram
    não quis —, e devolver 5xx pioraria: faria o update ser reentregue e o Aluno
    levaria o acuse duas vezes.

    O que dá para fazer, e é o que este teste fixa, é o comportamento interno: o
    erro fica registrado para o operador e nada sobe. A reentrega do que falhou é
    a fila da #11, e é lá que o Aluno volta a receber a resposta.
    """
    telegram.status = 500

    with caplog.at_level(logging.ERROR, logger=LOGGER):
        resposta = _postar(_app(telegram, executor=None), UPDATE_DO_ALUNO)

    assert resposta.status_code == 200
    assert len(telegram.enviados) == 2, "o turno nem foi tentado depois do acuse"
    assert any("recusou a mensagem" in r.getMessage() for r in caplog.records)


def test_o_tempo_do_turno_vai_no_log(
    telegram: TelegramFalso, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """O tempo do turno inteiro, do começo à entrega, é o número que se vê na madrugada.

    O critério "a resposta chega em tempo aceitável para alguém acordado às 2h da
    manhã" é o único da issue que não dá para afirmar com um teste de tempo: a
    latência aqui é a do transporte falso, que responde na microsegunda, e um
    assert sobre ela passaria com o modelo mais lento do mundo. O que dá para
    garantir é que o número **existe**, por turno, com o desfecho junto — e que
    quem opera o serviço consegue responder "quanto tempo levou" semcronizar
    thread, relógio e log.

    A medição da máquina, essa sim é um número de verdade, e ela está em
    `docs/tempo-primeira-resposta.md`. Este é o do serviço, por turno.
    """
    monkeypatch.setattr(webhook, "ClienteOllama", ModeloFalso)

    with caplog.at_level(logging.INFO, logger=LOGGER):
        _postar(_app(telegram, executor=None), UPDATE_DO_ALUNO)

    tempos = [r.getMessage() for r in caplog.records if "entregue em" in r.getMessage()]
    assert len(tempos) == 1, f"o tempo do turno não foi registrado: {tempos}"
    assert "55_512_345" in tempos[0] or "55512345" in tempos[0], tempos[0]
    assert "(resposta do modelo)" in tempos[0], tempos[0]


def test_mensagem_sem_texto_e_acusejada_e_nao_gera_turno(telegram: TelegramFalso) -> None:
    """Foto, áudio e comando de teclado são acusejados e não viram turno.

    O grafo da #8 recebe mensagem escrita. Um turno sobre uma foto seria o S.A.U.
    inventando a pergunta do Aluno, e inventar a pergunta é o defeito que a
    persona da #10 vem justamente para fechar. O acuse sai do mesmo jeito, porque
    o que o Aluno precisa é saber que a mensagem chegou.

    O caso do `caption` é o que dá nome a este teste: o Telegram manda a legenda
    da foto no campo `caption`, e não em `text`. Ler `text` é o que impede que a
    legenda vire pergunta. Se a legenda um dia passar a contar, essa é a decisão da
    #10 — e ela precisa de um teste aqui do outro lado.
    """
    textos_dos_turnos: list[str] = []

    resposta = _postar(_app(telegram, executor=_anotando(textos_dos_turnos)), UPDATE_COM_FOTO)

    assert resposta.status_code == 200
    assert textos_dos_turnos == []
    assert telegram.textos == [TEXTO_ACK]


@pytest.mark.parametrize(
    "update",
    [
        {"update_id": 1, "message": {"chat": {"id": 55_512_345}, "text": ""}},
        {"update_id": 1, "message": {"chat": {"id": 55_512_345}, "text": "   \n  "}},
        {"update_id": 1, "message": {"chat": {"id": 55_512_345}, "text": 42}},
    ],
    ids=["texto-vazio", "texto-so-espaco", "texto-nao-string"],
)
def test_update_com_texto_que_nao_e_texto_nao_chega_ao_grafo(
    telegram: TelegramFalso, update: Any
) -> None:
    """Texto que não é texto escrito não entra no grafo.

    Update malformado não é o mesmo que foto: aqui o `text` existe, mas é vazio,
    é só espaço, ou nem é string. Ler `text` resolve os três, e é a mesma leitura
    que evita que o handler caia em cima de um `strip()` de um inteiro. A foto,
    que não tem `text` nenhum, tem teste próprio acima.
    """
    textos_dos_turnos: list[str] = []

    resposta = _postar(_app(telegram, executor=_anotando(textos_dos_turnos)), update)

    assert resposta.status_code == 200
    assert textos_dos_turnos == []


def test_o_turno_usa_o_timeout_do_ambiente(
    telegram: TelegramFalso, monkeypatch: pytest.MonkeyPatch
) -> None:
    """O `OLLAMA_TIMEOUT` do ambiente é o relógio do turno.

    O `webhook` não roda a checagem de pré-requisito do `bot`, e essa é a diferença
    de propósito entre os dois serviços. O que o turno herda do `bot` é o relógio:
    geração e checagem precisam esperar pelo mesmo tempo, ou a mesma máquina
    passa a ter dois tetos diferentes para o mesmo defeito.
    """
    timeouts: list[float] = []

    class ModeloQueMede(ModeloFalso):
        def __init__(self, _base_url: str, _modelo: str, timeout: float = 0.0) -> None:
            super().__init__()
            timeouts.append(timeout)

    monkeypatch.setattr(webhook, "ClienteOllama", ModeloQueMede)

    _postar(_app(telegram, env={"OLLAMA_TIMEOUT": "12.5"}, executor=None), UPDATE_DO_ALUNO)

    assert timeouts == [12.5]


# --- O estado por conversa, que é a #9 ---


def _update_de(chat_id: int, texto: str) -> dict[str, Any]:
    """Um update do Telegram de um `chat_id` qualquer, com o texto dado.

    Existe para os dois testes da conversa: o isolamento e a ordem precisam de duas
    contas, e construir o update na mão em cada um dos dois evitaria a dependência do
    `UPDATE_DO_ALUNO`, que é de um `chat_id` só. O corpo é o mesmo que o Telegram
    manda; só o `chat.id` e o `text` mudam.
    """
    return {
        "update_id": chat_id,
        "message": {
            "message_id": 1,
            "chat": {"id": chat_id, "type": "private"},
            "from": {"id": chat_id, "is_bot": False, "first_name": "Aluna"},
            "text": texto,
        },
    }


class ModeloQueEspelha(ModeloFalso):
    """O modelo do turno, que guarda o prompt e responde com um texto por turno.

    A resposta precisa variar por turno porque o teste da ordem afirma que o segundo
    prompt carrega a troca **completa**: pergunta e resposta. Com a resposta fixa dos
    outros testes, a afirmação passaria com a pergunta do primeiro turno no histórico e
    a resposta errada — que ainda é um histórico, ainda é um bug, mas é outro.
    """

    prompts: list[str] = []
    """Os prompts de todos os turnos, na ordem. É de classe porque o modelo é
    recriado a cada turno — o `webhook` monta um `ClienteOllama` por turno — e a
    lista precisa sobreviver à recriação."""

    respostas: list[str] = [RESPOSTA_1, RESPOSTA_2]
    """A resposta de cada turno, na ordem dos prompts. Variar por turno é o que
    permite ao teste da ordem afirmar que o histórico do segundo turno tem a troca
    inteira, e não só a pergunta anterior."""

    def responder(self, prompt: str, *, opcoes: dict[str, Any] | None = None) -> Resposta:
        ModeloQueEspelha.prompts.append(prompt)
        indice = len(ModeloQueEspelha.prompts) - 1
        return Resposta(
            texto=ModeloQueEspelha.respostas[indice % len(ModeloQueEspelha.respostas)],
            primeiro_token_segundos=0.0,
            carga_segundos=0.0,
            avaliacao_prompt_segundos=0.0,
            segundos_totais=0.0,
            tokens_por_segundo=None,
            tokens_gerados=None,
            concluida=True,
            motivo_de_parada="stop",
        )


def test_a_sentinela_nao_esta_na_persona() -> None:
    """A resposta de fixture não pode ser uma palavra que a persona usa.

    A persona entra no prompt de todo turno, então uma sentinela que apareça num
    texto de regra está em todo prompt — e as afirmações de vazamento do histórico
    passam a medir a persona. `test_o_historico_de_um_aluno_nao_vai_para_o_prompt_de_outro`
    affirmava "a resposta da primeira Aluna não vazou" com a frase "primeira
    resposta", que a regra de identidade passou a usar: o teste ficou vermelho
    apontando um vazamento que não existia, e o que ele não mais provava era o
    isolamento.

    O defeito é silencioso pelo lado certo também: o isolamento está provado nos
    testes de conversa, e a persona nunca é o que eles medem. Se um dia uma regra
    usar a palavra de uma sentinela, este teste fica vermelho apontando a origem —
    que é a forma como ele devia ter ficado vermelho da primeira vez.
    """
    for sentinela in (RESPOSTA_1, RESPOSTA_2):
        assert sentinela not in PERSONA, (
            f"a sentinela {sentinela!r} está na persona: as afirmações de vazamento "
            "do histórico passariam a medir a persona em vez da conversa"
        )


def test_o_historico_de_um_aluno_nao_vai_para_o_prompt_de_outro(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """O critério de isolamento da #9, com duas contas e o webhook de verdade.

    Duas contas, e não dois `chat_id` num teste de unidade: o defeito que este teste
    fecha é o `webhook` entregar o histórico de um Aluno ao turno de outro, e ele mora
    no caminho entre o update e o prompt — que é o caminho que o `webhook` de verdade
    percorre.

    São três turnos porque o critério tem duas metades, e elas precisam das duas
    afirmadas no mesmo teste. A segunda pergunta da primeira Aluna carrega a troca
    anterior — sem isso, um registro que devolvesse sempre lista vazia passaria, e esse
    é o defeito oposto ao deste ticket, com a mesma causa. O turno da segunda Aluna não
    traz nada da primeira — que é o isolamento.

    O modelo falso guarda os prompts. Um registro que devolvesse a conversa errada
    passaria se o teste afirmasse só que "o histórico aparece", e o defeito é justamente
    o histórico *a mais*, não o de menos.

    O registro entra por injeção com o `tmp_path` do pytest, e não pelo padrão
    relativo ao diretório de trabalho: um teste que cria `conversas.db` na raiz do
    repositório deixa o arquivo para trás e continua passando.
    """
    telegram = TelegramFalso()
    registro = RegistroDeConversas(str(tmp_path / "conversas.db"))
    ModeloQueEspelha.prompts = []
    try:
        monkeypatch.setattr(webhook, "ClienteOllama", ModeloQueEspelha)
        app = _app(telegram, registro=registro, executor=None)

        # Três turnos: duas perguntas da primeira Aluna e uma da segunda. Com duas
        # perguntas só, a conversa da primeira nunca é lida de volta e o teste não
        # distingue "o histórico funciona" de "o histórico é sempre vazio" — e as duas
        # coisas são defeitos, um pelo motivo oposto ao outro.
        _postar(app, _update_de(11, "qual o prazo da Atividade 2?"))
        _postar(app, _update_de(11, "e a de matemática?"))
        _postar(app, _update_de(22, "e aquela atividade de inglês?"))
    finally:
        registro.fechar()
        telegram.fechar()

    assert len(ModeloQueEspelha.prompts) == 3, "um dos turnos não chegou ao modelo"
    da_aluna, da_aluna_ainda, da_outra = ModeloQueEspelha.prompts
    # A segunda pergunta da primeira Aluna carrega a troca inteira da primeira vez.
    assert "Atividade 2" in da_aluna_ainda, (
        f"o segundo turno da Aluna não recebeu o histórico: {da_aluna_ainda!r}"
    )
    assert RESPOSTA_1 in da_aluna_ainda, (
        f"o histórico não trouxe a resposta anterior: {da_aluna_ainda!r}"
    )
    # E a outra Aluna não viu nada da primeira, nem da pergunta nem da resposta.
    assert "Atividade 2" not in da_outra, "a pergunta da primeira Aluna vazou para a segunda"
    assert "matemática" not in da_outra, "a conversa da primeira Aluna vazou inteira"
    assert RESPOSTA_1 not in da_outra, "a resposta da primeira Aluna vazou"
    assert "atividade de inglês" in da_outra


def test_as_mensagens_do_mesmo_aluno_sao_respondidas_em_ordem(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    threads_do_turno: list[threading.Thread],
) -> None:
    """O critério de ordem da #9, com o primeiro turno segurado por um evento.

    A prova é o **prompt** do segundo turno: sem a fila, ele leria o histórico antes de
    o primeiro turno ter gravado a resposta, e o prompt dele não teria a troca. Como o
    grafo e o nó são os de verdade e o modelo é falso, o que se vê é o que o modelo
    receberia.

    Determinismo é o ponto, e é por isso que o primeiro turno é segurado por um
    `threading.Event` em vez de um `time.sleep`: o teste solta o primeiro turno só
    depois de o segundo ter entrado na fila, o que torna a corrida impossível em vez de
    improvável. Um `sleep` seria um teste que passa quase sempre e falha uma vez em
    vinte, na máquina carregada.

    O agendamento é o de produção, `agendar=None`, e a thread é esperada pela fixture
    `threads_do_turno`. É o caminho real do serviço: grafo, nó, registro e fila reais.
    """
    telegram = TelegramFalso()
    registro = RegistroDeConversas(str(tmp_path / "conversas.db"))
    ModeloQueEspelha.prompts = []
    chegou_na_fila = threading.Event()
    solta_o_primeiro = threading.Event()
    try:
        class ModeloQueEspera(ModeloQueEspelha):
            """O modelo do primeiro turno, que segura o turno até o teste soltar."""

            def responder(
                self, prompt: str, *, opcoes: dict[str, Any] | None = None
            ) -> Resposta:
                resposta = super().responder(prompt, opcoes=opcoes)
                if len(ModeloQueEspelha.prompts) == 1:
                    chegou_na_fila.set()
                    solta_o_primeiro.wait(timeout=5.0)
                return resposta

        monkeypatch.setattr(webhook, "ClienteOllama", ModeloQueEspera)
        app = _app(telegram, registro=registro, executor=None, agendar=None)

        _postar(app, _update_de(31, "qual o prazo da Atividade 1?"))
        assert chegou_na_fila.wait(5.0), "o primeiro turno não chegou ao modelo"

        _postar(app, _update_de(31, "e a de matemática?"))

        solta_o_primeiro.set()
        for thread in threads_do_turno:
            thread.join(timeout=5.0)
    finally:
        solta_o_primeiro.set()
        registro.fechar()
        telegram.fechar()

    assert len(ModeloQueEspelha.prompts) == 2, "um dos turnos não chegou ao modelo"
    primeiro, segundo = ModeloQueEspelha.prompts
    # O segundo turno só existe depois do primeiro ter gravado a resposta, e é isso
    # que a fila garante.
    assert RESPOSTA_1 in segundo, (
        f"o segundo turno rodou antes do primeiro gravar a resposta: {segundo!r}"
    )
    assert "Atividade 1" in segundo
    assert "matemática" in segundo
    # E a entrega saiu na ordem em que o Aluno perguntou.
    assert telegram.textos == [TEXTO_ACK, TEXTO_ACK, RESPOSTA_1, RESPOSTA_2]


def test_a_conversa_registra_a_falha_como_parte_do_que_o_aluno_viu(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `TEXTO_FALHA` entra no histórico, e o turno seguinte sabe que houve falha.

    Sem isso, o histórico mostraria ao modelo uma conversa em que a pergunta do Aluno
    foi seguida de uma resposta que não veio — e o modelo tenderia a responder como se
    a pergunta anterior tivesse sido atendida. O histórico não pode divergir da conversa
    que o Aluno teve, e ele viu a mensagem de falha.
    """
    telegram = TelegramFalso()
    registro = RegistroDeConversas(str(tmp_path / "conversas.db"))
    ModeloQueEspelha.prompts = []
    try:
        monkeypatch.setattr(webhook, "ClienteOllama", ModeloQueFalha)
        app = _app(telegram, registro=registro, executor=None)
        _postar(app, _update_de(41, "qual o prazo da Atividade 1?"))
        monkeypatch.setattr(webhook, "ClienteOllama", ModeloQueEspelha)
        _postar(app, _update_de(41, "e a de matemática?"))
        # A conversa é lida antes do `fechar`: ler depois é ler um registro fechado,
        # e o teste passaria a estar exercitando o `sqlite3` e não o turno.
        historico = registro.historico(41)
    finally:
        registro.fechar()
        telegram.fechar()

    assert [(m.papel, m.texto) for m in historico] == [
        ("aluno", "qual o prazo da Atividade 1?"),
        ("sau", TEXTO_FALHA),
        ("aluno", "e a de matemática?"),
        ("sau", RESPOSTA_1),
    ], f"a conversa gravada não é a que o Aluno teve: {historico}"
    assert TEXTO_FALHA in ModeloQueEspelha.prompts[0], (
        f"o turno seguinte não viu a falha anterior: {ModeloQueEspelha.prompts[0]!r}"
    )


# --- Boas-vindas e reengajamento: os dois caminhos sem inferência total ---


def test_start_devolve_boas_vindas_sem_chamar_o_modelo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """O `/start` é comando, não pergunta: volta fixa, sem geração.

    Mandar para o modelo rendeu o "Olá novamente!" da conversa real — além de
    errado, um turno de inferência gasto à toa. A conversa gravada é a que o
    Aluno teve: o comando como `aluno` e as boas-vindas como `sau`.
    """
    telegram = TelegramFalso()
    registro = RegistroDeConversas(str(tmp_path / "conversas.db"))
    ModeloQueEspelha.prompts = []
    try:
        monkeypatch.setattr(webhook, "ClienteOllama", ModeloQueEspelha)
        app = _app(telegram, registro=registro, executor=None)
        _postar(app, _update_de(44, "/start"))
        historico = registro.historico(44)
    finally:
        registro.fechar()
        telegram.fechar()

    assert telegram.textos == [TEXTO_ACK, TEXTO_BOAS_VINDAS]
    assert ModeloQueEspelha.prompts == []
    assert [(m.papel, m.texto) for m in historico] == [
        ("aluno", "/start"),
        ("sau", TEXTO_BOAS_VINDAS),
    ]


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("/start", True),
        ("/START", True),
        ("/start carga-do-botao", True),
        ("/start@saubot", True),
        ("qual o prazo?", False),
        ("começar", False),
        ("/status", False),
    ],
)
def test_eh_comando_start(texto: str, esperado: bool) -> None:
    """Só o comando com fronteira é `/start`: carga e menção passam, resto não."""
    assert webhook._eh_comando_start(texto) is esperado


def test_volta_depois_do_ttl_gruda_reengajamento_na_resposta(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Quem voltou depois da expiração lê o "que bom te ver de novo" na frente.

    A frase vai grudada na resposta do turno, e não como mensagem separada: o
    Aluno já levou o acuse, e terceira mensagem viraria espera. O primeiro turno
    sai puro — o sinal só nasce da expiração.
    """
    agora = [1_700_000_000.0]
    telegram = TelegramFalso()
    registro = RegistroDeConversas(
        str(tmp_path / "conversas.db"), ttl_minutos=30, agora=lambda: agora[0]
    )
    try:
        monkeypatch.setattr(webhook, "ClienteOllama", ModeloFalso)
        app = _app(telegram, registro=registro, executor=None)
        _postar(app, _update_de(45, "qual o prazo?"))
        agora[0] += 31 * 60
        _postar(app, _update_de(45, "e o formato?"))
    finally:
        registro.fechar()
        telegram.fechar()

    assert telegram.textos == [
        TEXTO_ACK,
        ModeloFalso.texto,
        TEXTO_ACK,
        f"{TEXTO_REENGAJAMENTO}\n\n{ModeloFalso.texto}",
    ]


def test_start_vence_o_reengajamento_e_consome_o_sinal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A volta que começou pelo comando já foi saudada: sem frase grudada.

    O sinal é consumido de qualquer jeito — se vazasse, o turno seguinte
    reengajaria uma conversa que acabou de receber as boas-vindas.
    """
    agora = [1_700_000_000.0]
    telegram = TelegramFalso()
    registro = RegistroDeConversas(
        str(tmp_path / "conversas.db"), ttl_minutos=30, agora=lambda: agora[0]
    )
    try:
        monkeypatch.setattr(webhook, "ClienteOllama", ModeloFalso)
        app = _app(telegram, registro=registro, executor=None)
        _postar(app, _update_de(46, "qual o prazo?"))
        agora[0] += 31 * 60
        _postar(app, _update_de(46, "/start"))
        _postar(app, _update_de(46, "e o formato?"))
    finally:
        registro.fechar()
        telegram.fechar()

    assert telegram.textos == [
        TEXTO_ACK,
        ModeloFalso.texto,
        TEXTO_ACK,
        TEXTO_BOAS_VINDAS,
        TEXTO_ACK,
        ModeloFalso.texto,
    ]


# --- Payload inválido ---


@pytest.mark.parametrize("payload", [None, [], "texto solto", 7])
def test_webhook_recusa_payload_que_nao_e_objeto(
    telegram: TelegramFalso, payload: Any
) -> None:
    resposta = _postar(_app(telegram), payload)
    assert resposta.status_code == 400
    assert telegram.enviados == []


def test_webhook_ignora_o_corpo_invalido(
    telegram: TelegramFalso, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        resposta = _app(telegram).test_client().post(
            "/webhook",
            data=b"isto nao e json",
            headers={CABECALHO_SECRET_TOKEN: _SEGREDO},
        )

    assert resposta.status_code == 400
    assert any("não é um objeto JSON" in r.getMessage() for r in caplog.records)


# --- O header que fecha a porta pública do túnel ---


def test_webhook_recusa_post_sem_o_secret_token(telegram: TelegramFalso) -> None:
    resposta = _postar(_app(telegram), UPDATE_DO_ALUNO, segredo=None)
    assert resposta.status_code == 403
    assert telegram.enviados == []


def test_webhook_recusa_secret_token_divergente(telegram: TelegramFalso) -> None:
    resposta = _postar(_app(telegram), UPDATE_DO_ALUNO, segredo="chave-de-outra-pessoa")
    assert resposta.status_code == 403
    assert telegram.enviados == []


def test_webhook_aceita_o_secret_token_correto(telegram: TelegramFalso) -> None:
    resposta = _postar(_app(telegram), UPDATE_DO_ALUNO)
    assert resposta.status_code == 200
    assert len(telegram.enviados) == 1


def test_webhook_fica_aberto_quando_nao_ha_secret_token(telegram: TelegramFalso) -> None:
    """Sem a credencial no ambiente não há o que conferir.

    O serviço sobe sem ela quem não usa o canal; com a variável presente, conferir
    a chegada é o que fecha a porta.
    """
    app = _app(telegram, env={"TELEGRAM_WEBHOOK_SECRET_TOKEN": ""})
    assert _postar(app, UPDATE_DO_ALUNO, segredo=None).status_code == 200


# --- Update que não é mensagem do Aluno ---


@pytest.mark.parametrize(
    "update",
    [
        {"update_id": 1, "edited_message": {"text": "corrigindo"}},
        {"update_id": 1, "message_reaction": {"chat": {"id": 55_512_345}}},
        {"update_id": 1, "message": {"text": "sem chat"}},
        {"update_id": 1, "message": {"chat": {"id": "55.512.345"}}},
        {"update_id": 1, "message": {"chat": {"id": True}}},
    ],
    ids=["editado", "reacao", "sem-chat", "id-string", "id-bool"],
)
def test_webhook_update_sem_aluno_nao_acuseja(
    telegram: TelegramFalso, update: dict[str, Any]
) -> None:
    resposta = _postar(_app(telegram), update)
    # 2xx de propósito: erro faria o Telegram reentregar o mesmo update sempre.
    assert resposta.status_code == 200
    assert telegram.enviados == []


def test_webhook_update_sem_mensagem_e_registrado(
    telegram: TelegramFalso, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger=LOGGER):
        _postar(_app(telegram), {"update_id": 1, "edited_message": {"text": "corrigindo"}})
    assert any("sem mensagem do Aluno" in r.getMessage() for r in caplog.records)


# --- Falha do Telegram não pode virar update reentregue ---


def test_webhook_erro_do_telegram_nao_vira_5xx(
    telegram: TelegramFalso, caplog: pytest.LogCaptureFixture
) -> None:
    telegram.status = 500
    with caplog.at_level(logging.ERROR, logger=LOGGER):
        resposta = _postar(_app(telegram), UPDATE_DO_ALUNO)

    # Um 5xx faria o Telegram reentregar e o Aluno levaria o acuse duas vezes.
    assert resposta.status_code == 200
    assert any("recusou a mensagem" in r.getMessage() for r in caplog.records)


def test_webhook_falha_de_rede_nao_vira_5xx(caplog: pytest.LogCaptureFixture) -> None:
    def cair(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    cliente = httpx.Client(transport=httpx.MockTransport(cair))
    try:
        with caplog.at_level(logging.ERROR, logger=LOGGER):
            resposta = _postar(
                criar_app(
                    carregar_configuracao(_ENV_PADRAO),
                    cliente,
                    _registro_de_teste(),
                    _sem_turno,
                    _sincrono,
                ),
                UPDATE_DO_ALUNO,
            )
    finally:
        cliente.close()

    assert resposta.status_code == 200
    assert any("Falha de rede" in r.getMessage() for r in caplog.records)


# --- O consumo é por webhook, não por long polling (ADR-0001) ---


def test_webhook_so_aceita_post(telegram: TelegramFalso) -> None:
    assert _app(telegram).test_client().get("/webhook").status_code == 405
    assert telegram.requisicoes == []


# --- Falha alta na ausência de credencial ---


def test_exigir_credenciais_recusa_o_token_do_sau_ausente() -> None:
    config = carregar_configuracao({"TELEGRAM_WEBHOOK_SECRET_TOKEN": _SEGREDO})
    with pytest.raises(CredencialTelegramAusenteError) as exc_info:
        exigir_credenciais(config)

    mensagem = str(exc_info.value)
    assert "TELEGRAM_BOT_TOKEN" in mensagem
    assert "@BotFather" in mensagem
    assert "TELEGRAM_WEBHOOK_SECRET_TOKEN" not in mensagem


def test_exigir_credenciais_recusa_o_secret_token_ausente() -> None:
    config = carregar_configuracao({"TELEGRAM_BOT_TOKEN": _TOKEN})
    with pytest.raises(CredencialTelegramAusenteError) as exc_info:
        exigir_credenciais(config)

    mensagem = str(exc_info.value)
    assert "TELEGRAM_WEBHOOK_SECRET_TOKEN" in mensagem
    assert "openssl rand -hex 16" in mensagem
    assert "TELEGRAM_BOT_TOKEN:" not in mensagem


def test_exigir_credenciais_recusa_as_duas_ausentes() -> None:
    with pytest.raises(CredencialTelegramAusenteError) as exc_info:
        exigir_credenciais(carregar_configuracao({}))

    mensagem = str(exc_info.value)
    assert "TELEGRAM_BOT_TOKEN" in mensagem
    assert "TELEGRAM_WEBHOOK_SECRET_TOKEN" in mensagem


def test_exigir_credenciais_aceita_as_duas_presentes() -> None:
    exigir_credenciais(carregar_configuracao(_ENV_PADRAO))


def test_sem_token_o_acuse_e_registrado_como_ausente(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """App montado sem passar por `main` não pode falhar em silêncio."""
    telegram = TelegramFalso()
    try:
        with caplog.at_level(logging.ERROR, logger=LOGGER):
            _postar(
                criar_app(
                    carregar_configuracao({}),
                    telegram.cliente,
                    _registro_de_teste(),
                    _sem_turno,
                    _sincrono,
                ),
                UPDATE_DO_ALUNO,
            )
    finally:
        telegram.fechar()

    assert telegram.enviados == []
    assert any("TELEGRAM_BOT_TOKEN ausente" in r.getMessage() for r in caplog.records)


# --- Registro automático do webhook no compose dev ---


def test_descobrir_prefere_telegram_public_url_e_registra_com_secret() -> None:
    """A TELEGRAM_PUBLIC_URL vence a descoberta e vira setWebhook com secret.

    É o caminho de quem abre o túnel na mão, fora do compose dev: o ngrok nem
    é consultado, e o registro leva a URL com `/webhook` mais o secret que
    fecha a porta do endpoint.
    """
    url_manual = "https://manual-1234.ngrok-free.app"
    config = carregar_configuracao(
        {**_ENV_PADRAO, "TELEGRAM_PUBLIC_URL": url_manual, "NGROK_API_URL": "http://ngrok:4040"}
    )

    def explodir(requisicao: httpx.Request) -> httpx.Response:
        raise AssertionError("o ngrok não deveria ser consultado com TELEGRAM_PUBLIC_URL presente")

    cliente_ngrok = httpx.Client(transport=httpx.MockTransport(explodir))
    try:
        assert descobrir_url_publica(config, cliente_ngrok, dormir=lambda _: None) == url_manual
    finally:
        cliente_ngrok.close()

    enviadas: list[httpx.Request] = []

    def responder_setwebhook(requisicao: httpx.Request) -> httpx.Response:
        enviadas.append(requisicao)
        return httpx.Response(
            status_code=200, json={"ok": True, "result": True}, request=requisicao
        )

    cliente_telegram = httpx.Client(transport=httpx.MockTransport(responder_setwebhook))
    try:
        registrar_webhook(config, url_manual, cliente_telegram)
    finally:
        cliente_telegram.close()

    assert len(enviadas) == 1
    chamada = enviadas[0]
    assert chamada.url.path == f"/bot{_TOKEN}/setWebhook"
    corpo = json.loads(chamada.content)
    assert corpo == {"url": f"{url_manual}/webhook", "secret_token": _SEGREDO}


def test_descobrir_via_api_do_ngrok_e_registra_o_webhook() -> None:
    """Sem URL manual, a descoberta lê o /api/tunnels e registra o https.

    O túnel http fica de fora de propósito: o Telegram só entrega em 443, 80,
    88 e 8443, então só o https serve ao Aluno.
    """
    url_do_tunel = "https://aleatorio-1234.ngrok-free.app"
    config = carregar_configuracao({**_ENV_PADRAO, "NGROK_API_URL": "http://ngrok:4040"})

    def responder_tuneis(requisicao: httpx.Request) -> httpx.Response:
        assert requisicao.url.path == "/api/tunnels"
        return httpx.Response(
            status_code=200,
            json={
                "tunnels": [
                    {"public_url": "http://sem-https.ngrok-free.app", "proto": "http"},
                    {"public_url": url_do_tunel, "proto": "https"},
                ]
            },
            request=requisicao,
        )

    cliente_tuneis = httpx.Client(transport=httpx.MockTransport(responder_tuneis))
    try:
        assert descobrir_url_publica(config, cliente_tuneis, dormir=lambda _: None) == url_do_tunel
    finally:
        cliente_tuneis.close()

    enviadas: list[httpx.Request] = []

    def responder_setwebhook(requisicao: httpx.Request) -> httpx.Response:
        enviadas.append(requisicao)
        return httpx.Response(
            status_code=200, json={"ok": True, "result": True}, request=requisicao
        )

    cliente_telegram = httpx.Client(transport=httpx.MockTransport(responder_setwebhook))
    try:
        registrar_webhook(config, url_do_tunel, cliente_telegram)
    finally:
        cliente_telegram.close()

    assert len(enviadas) == 1
    corpo = json.loads(enviadas[0].content)
    assert corpo["url"] == f"{url_do_tunel}/webhook"
    assert corpo["secret_token"] == _SEGREDO


def test_sem_url_publica_o_main_sobe_sem_http_extra(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Em prod, sem TELEGRAM_PUBLIC_URL e sem NGROK_API_URL, nada extra sai.

    A descoberta devolve None sem tocar na rede, o `main` sobe sem registrar e
    o token do S.A.U. nunca aparece no log — só a ausência da URL pública.
    """
    config = carregar_configuracao(_ENV_PADRAO)
    assert config.telegram_public_url is None
    assert config.ngrok_api_url is None

    def explodir(requisicao: httpx.Request) -> httpx.Response:
        raise AssertionError("nenhum HTTP deveria sair sem URL pública")

    cliente = httpx.Client(transport=httpx.MockTransport(explodir))
    try:
        assert descobrir_url_publica(config, cliente, dormir=lambda _: None) is None
    finally:
        cliente.close()

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", _TOKEN)
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET_TOKEN", _SEGREDO)
    monkeypatch.delenv("TELEGRAM_PUBLIC_URL", raising=False)
    monkeypatch.delenv("NGROK_API_URL", raising=False)
    monkeypatch.setattr(Flask, "run", _nao_sobe_servidor)

    def explodir_request(_eu: httpx.Client, *args: Any, **kwargs: Any) -> httpx.Response:
        raise AssertionError("o main não deveria fazer HTTP sem URL pública")

    monkeypatch.setattr(httpx.Client, "request", explodir_request)

    raiz = logging.getLogger()
    handlers, nivel = raiz.handlers[:], raiz.level
    try:
        main()
    finally:
        raiz.handlers[:] = handlers
        raiz.setLevel(nivel)

    saida = capsys.readouterr().out
    assert "Sem URL pública" in saida
    assert _TOKEN not in saida


# --- A fila e o semáforo de inferência (a #11) ---
#
# Todos os testes daqui rodam o turno de verdade (`executor=None`) com o grafo, o nó e o
# registro reais, e só o modelo e o Telegram falsos. A razão é a mesma dos testes da
# conversa: o defeito que a #11 fecha mora no caminho entre a fila do Aluno e a chamada
# do modelo, e um teste de unidade do semáforo não passa por esse caminho.
#
# A vaga ocupada é um **estado controlado**, nunca uma janela de tempo. O
# `ModeloQueSeguraAVaga` para dentro do semáforo e espera o teste mandar seguir, de modo
# que "a vaga está ocupada" é uma afirmação que o teste fez e não um `sleep` que o teste
# torceu para acertar. Todo POST vai em `VooDePost` porque um turno que espera vaga não
# termina, e um teste que espera por ele trava.


# --- A frase que o Aluno lê, e só ela ---

# O semaphore testado prova a mecânica. Isto prova a frase, e a frase é o critério
# da issue: "o Aluno recebe a posição na fila e uma estimativa de espera" é sobre o
# que ele lê, e um teste que só affirmasse a substring "posição 2" deixaria passar
# "você é o número 2" e "posición 2" sem acento. A formatação é comportamento, e
# comportamento sem teste é comportamento que ninguém olha duas vezes.


def test_a_posicao_aparece_com_um_numero_exato_e_nunca_com_aproximacao() -> None:
    """O número é exato, e é o número que o Aluno vai repetir para alguém."""
    texto = texto_posicao_na_fila(3, 90.0)
    assert "posição 3" in texto, texto
    assert "~" not in texto and "aprox" not in texto


def test_a_estimativa_abaixo_de_um_minuto_e_em_segundos() -> None:
    """Abaixo de um minuto, segundos: "cerca de meio minuto" é mais difícil de ler."""
    assert "20 segundos" in texto_posicao_na_fila(2, 20.0)


def test_a_estimativa_acima_de_um_minuto_e_em_minutos_arredondados_para_cima() -> None:
    """A partir de um minuto, minutos, e sempre para cima.

    O arredondamento para cima é a escolha honesta: com `k=2` as vagas abrem de duas
    em duas, e o turno na posição 5 espera duas voltas inteiras. Prometer menos do
    que a espera provavelmente vai durar é pior que a espera, porque o Aluno que vê
    o prazo vencido para de acreditar no prazo.
    """
    assert "2 minutos" in texto_posicao_na_fila(3, 90.0)
    # 3,7 minutos arredonda para 4, e nunca para 3.
    assert "4 minutos" in texto_posicao_na_fila(4, 220.0)
    assert "3 minutos" not in texto_posicao_na_fila(4, 220.0)


def test_um_minuto_ou_exatamente_sao_minutos_e_nao_segundos() -> None:
    """O limite é o minuto fechado, e o singular de 1 minuto é o caso que existe."""
    assert "1 minuto." in texto_posicao_na_fila(2, 60.0)
    assert "segundos" not in texto_posicao_na_fila(2, 60.0)


def test_uma_estimativa_de_zero_vira_um_segundo_e_nao_zero() -> None:
    """"Cerca de 0 segundos" é pior que não dizer nada: parece que o S.A.U. travou.

    O caso é legítimo, e não é teórico: a média móvel de uma vaga muito rápida
    arredonda para zero, e o piso de 10 s só vale enquanto nada foi medido.
    """
    assert "1 segundo" in texto_posicao_na_fila(2, 0.0)
    assert "0 segundos" not in texto_posicao_na_fila(2, 0.0)


def test_estimativa_negativa_e_recusada_com_valor_erro() -> None:
    """Uma espera negativa é defeito no semáforo, e `ValueError` é o que diz isso.

    Foi `assert` até o primeiro code-review, e `assert` é descartado por
    `python -O`: o serviço rodando com `-O` leria "cerca de -20 segundos" para o
    Aluno, sem nenhuma exceção e sem nenhum sinal. A guarda de produção do
    repositório é exceção — o que o `SemaforoDeInferencia.__init__` e o
    `carregar_configuracao` fazem pelo mesmo motivo.
    """
    with pytest.raises(ValueError, match="negativa"):
        texto_posicao_na_fila(2, -1.0)


def test_quando_a_vaga_esta_ocupada_o_aluno_recebe_a_posicao_e_a_estimativa(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """O critério de communicated da #11, com uma Aluna na frente e a vaga ocupada.

    A Aluna 41 ocupa a vaga e segura o modelo. A Aluna 42 chega, não há vaga, e por isso
    seu turno **fica na fila do semáforo** — e é nesse ponto que ela tem de ler onde está
    e quanto vai esperar. Sem a #11, esse turno entraria em silêncio e a Aluna ficaria
    olhando o acuse sem saber de mais nada.

    As três coisas afirmadas são o que o ADR-0001 chama de backpressure comunicado:

    1. a posição sai, e sai certa — 2, porque há uma pessoa na frente segurando a vaga;
    2. a estimativa sai junto, e sai com "cerca de", que é o que uma média móvel merece;
    3. **o modelo não foi chamado** para a Aluna 42 enquanto ela espera. Este é o ponto
       que mais fácil passa: se o turno chamasse o modelo antes de o semáforo liberar, o
       `k` não limitaria nada e o teste continuaria verde, porque o texto da posição
       também sairia.

    E a última afirmação é que a entrega é a mesma do turno que não esperou: a posição
    é uma mensagem a mais, e não uma resposta no lugar da resposta.
    """
    entregas = Entregas()
    telegram = TelegramFalso(ao_entregar=entregas.ao_entregar)
    ModeloQueSeguraAVaga.destravar()
    try:
        monkeypatch.setattr(webhook, "ClienteOllama", ModeloQueSeguraAVaga)
        semaforo = SemaforoDeInferencia(k=1)
        app = _app(telegram, executor=None, semaforo=semaforo)

        primeiro = VooDePost(
            lambda: _postar(app, _update_de(41, "qual o prazo da Atividade 1?"))
        )
        ModeloQueSeguraAVaga.esperar_chegadas(1)

        segundo = VooDePost(
            lambda: _postar(app, _update_de(42, "e a de matemática?"))
        )
        recebidas = entregas.esperar(42, 2)

        assert recebidas[0] == TEXTO_ACK, f"o acuse não foi o primeiro: {recebidas}"
        assert "posição 2" in recebidas[1], (
            f"a posição não foi comunicada ao Aluno: {recebidas[1]!r}"
        )
        assert "cerca de" in recebidas[1], (
            f"a estimativa saiu sem o 'cerca de' de uma média móvel: {recebidas[1]!r}"
        )
        assert len(ModeloQueSeguraAVaga.turnos) == 1, (
            "o turno que esperava vaga chamou o modelo assim mesmo: o k não estaria "
            "limitando nada"
        )

        ModeloQueSeguraAVaga.soltar()
        segundo.esperar()
        primeiro.esperar()

        assert entregas.textos(42) == [
            TEXTO_ACK,
            recebidas[1],
            ModeloQueSeguraAVaga.texto,
        ], "a posição não foi uma mensagem a mais: ela substituiu a resposta"
    finally:
        ModeloQueSeguraAVaga.soltar()
        telegram.fechar()


def test_sem_vaga_o_aluno_recebe_a_posicao_e_a_estimativa(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cada Aluno da fila lê **a sua** posição, e a numeração é a da fila que ele vê.

    Uma vaga, uma Aluna segurando o modelo e duas atrás: as posições saem 2 e 3. É o
    teste que distingue a fila de verdade de um contador qualquer, e ele existe porque a
    posição errada aqui não quebraria nada visível: a Aluna 42 leria "posição 2" e a
    Aluna 43 leria "posição 3" mesmo que ambas lessem 2, e ninguém perceberia sem contar.

    A ordem dos posts é o que fixa a ordem das posições. Com `k=1` a vaga não abre para
    dois, de modo que quem pega a senha primeiro é quem foi servido primeiro — e é a
    ordem em que o Aluno espera, a ordem em que ele deve ser servido.
    """
    entregas = Entregas()
    telegram = TelegramFalso(ao_entregar=entregas.ao_entregar)
    ModeloQueSeguraAVaga.destravar()
    try:
        monkeypatch.setattr(webhook, "ClienteOllama", ModeloQueSeguraAVaga)
        app = _app(telegram, executor=None, semaforo=SemaforoDeInferencia(k=1))

        primeiro = VooDePost(
            lambda: _postar(app, _update_de(51, "qual o prazo da Atividade 1?"))
        )
        ModeloQueSeguraAVaga.esperar_chegadas(1)

        segunda = VooDePost(lambda: _postar(app, _update_de(52, "e a de matemática?")))
        textos_da_segunda = entregas.esperar(52, 2)
        terceira = VooDePost(
            lambda: _postar(app, _update_de(53, "e a de história?"))
        )
        textos_da_terceira = entregas.esperar(53, 2)

        assert "posição 2" in textos_da_segunda[1], textos_da_segunda[1]
        assert "posição 3" in textos_da_terceira[1], textos_da_terceira[1]
        # A terceira Aluna espera mais que a segunda, e a estimativa precisa refletir
        # isso: é a estimativa que cresce por posição que diz alguma coisa, porque a
        # posição sozinha já está no número.
        assert textos_da_terceira[1] != textos_da_segunda[1], (
            "as duas Alunas da fila leram a mesma mensagem, e uma delas está mais longe"
        )
        assert len(ModeloQueSeguraAVaga.turnos) == 1, (
            "alguém da fila chamou o modelo antes de a vaga aparecer"
        )

        ModeloQueSeguraAVaga.soltar()
        terceira.esperar()
        segunda.esperar()
        primeiro.esperar()

        # E a fila anda: as três receberam resposta, e na ordem em que entraram.
        assert entregas.textos(53)[-1] == ModeloQueSeguraAVaga.texto
        assert entregas.textos(52)[-1] == ModeloQueSeguraAVaga.texto
        assert entregas.textos(51)[-1] == ModeloQueSeguraAVaga.texto
    finally:
        ModeloQueSeguraAVaga.soltar()
        telegram.fechar()


def test_a_posicao_na_fila_entra_na_conversa_e_nao_no_historico(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A posição vai para o Aluno e **não** vai para o histórico. As duas coisas.

    A recusa vai para os dois, e a posição só para o Aluno. A diferença não é
    inconsistência, é a natureza de cada mensagem: a recusa é uma **resposta** — o
    Aluno leu, e a conversa dele precisa mostrar que aquilo foi tudo o que ele recebeu
    —, enquanto a posição é sobre a **espera**, e a espera não é fala do S.A.U.

    O que aconteceria se a posição entrasse no histórico é pior do que um histórico
    comprido: o modelo leria "você está na posição 3 da fila, e a resposta deve sair
    em cerca de 2 minutos" como se o Tutor tivesse dito aquilo. Ele passaria a
    comentar a própria fila, e o próximo turno da Aluna comecaria por um turno que
    o S.A.U. não deu. É o tipo de dano que a suíte não perceberia sozinha: o turno
    continua respondendo, a resposta continua chegando, e o defeito é só o Tutor
    falando de coisa que não é assunto dele.

    A conversa da Aluna 62 é a prova, e ela é a do turno **completo**: a pergunta
    dela e a resposta do modelo, e nada entre as duas. Uma posição extra aqui
    significaria que alguém gravou a espera como se fosse conversa.
    """
    entregas = Entregas()
    telegram = TelegramFalso(ao_entregar=entregas.ao_entregar)
    registro = RegistroDeConversas(str(tmp_path / "conversas.db"))
    ModeloQueSeguraAVaga.destravar()
    try:
        monkeypatch.setattr(webhook, "ClienteOllama", ModeloQueSeguraAVaga)
        app = _app(
            telegram, registro=registro, executor=None, semaforo=SemaforoDeInferencia(k=1)
        )

        primeiro = VooDePost(
            lambda: _postar(app, _update_de(62, "qual o prazo da Atividade 1?"))
        )
        ModeloQueSeguraAVaga.esperar_chegadas(1)
        segundo = VooDePost(lambda: _postar(app, _update_de(63, "e a de matemática?")))
        # A 63 foi avisada da posição, ou seja, a espera existiu de verdade.
        assert "posição 2" in entregas.esperar(63, 2)[1]

        ModeloQueSeguraAVaga.soltar()
        segundo.esperar()
        primeiro.esperar()
        assert len(entregas.esperar(63, 3)) == 3

        # A 63 recebeu três mensagens ao Aluno, e a conversa dela tem duas falas.
        assert len(entregas.textos(63)) == 3, entregas.textos(63)
        assert [m.texto for m in registro.conversa(63).historico()] == [
            "e a de matemática?",
            ModeloQueSeguraAVaga.texto,
        ], (
            "a posição na fila entrou no histórico: o modelo vai ler a espera do Aluno "
            "como se o Tutor tivesse falado sobre a própria fila"
        )
    finally:
        ModeloQueSeguraAVaga.soltar()
        registro.fechar()
        telegram.fechar()


def test_o_mesmo_aluno_nunca_tem_dois_turnos_dentro_do_semaphore(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dois turnos do mesmo Aluno, `k=2` livre, e mesmo assim nunca dois ao mesmo tempo.

    Este é o critério mais fácil de cumprir por acidente e o mais fácil de quebrar sem
    perceber. Aqui o semáforo tem **vaga sobrando** — `k=2` e só um turno dentro — e o
    segundo turno do mesmo Aluno mesmo assim não entra. Ele está atrás da fila da
    **própria conversa**, que vem antes do semáforo, e é por isso que ele nunca chega a
    olhar vaga nenhuma.

    A afirmação é o `maximo_simultaneo`, e não a ausência da mensagem de posição: com
    `k=2` e uma vaga ocupada, um segundo turno do mesmo Aluno que passasse pelo caminho
    errado entraria **sem** mensagem de posição nenhuma, e um teste que só olhasse o
    texto não veria nada de errado. O maior paralelismo visto é o que diz a verdade.

    A segunda afirmação é a ausência da posição na fila, e é ela que mostra onde a
    espera do Aluno realmente acontece: atrás da conversa dele, e não do mundo. Um turno
    do mesmo Aluno não tem posição de ninguém — ele já sabe que mandou antes, e a espera
    dele não é inexplicável.
    """
    entregas = Entregas()
    telegram = TelegramFalso(ao_entregar=entregas.ao_entregar)
    ModeloQueSeguraAVaga.destravar()
    try:
        monkeypatch.setattr(webhook, "ClienteOllama", ModeloQueSeguraAVaga)
        semaforo = SemaforoDeInferencia(k=2)
        app = _app(telegram, executor=None, semaforo=semaforo)

        primeiro = VooDePost(
            lambda: _postar(app, _update_de(61, "qual o prazo da Atividade 1?"))
        )
        ModeloQueSeguraAVaga.esperar_chegadas(1)
        segundo = VooDePost(
            lambda: _postar(app, _update_de(61, "e a de matemática?"))
        )
        # Espera o **acuse** da segunda mensagem, que é o ponto em que o turno do
        # segundo existe. O `VooDePost` só diz que a thread subiu; ele não diz que o
        # request chegou ao fim, e ler `turnos_esperando` logo depois seria medir a
        # corrida e não a fila. O acuse é o observável que não mente: ele sai do
        # request, e o request já chamou o agendador quando o entrega.
        assert len(entregas.esperar(61, 2)) == 2, "a segunda mensagem não foi acusejada"

        # Com `k=2` e uma vaga livre, qualquer coisa que tivesse entrado aqui seria o
        # defeito — e ela não entra, porque está atrás da conversa do próprio Aluno.
        assert semaforo.vagas_livres == 1, (
            f"as vagas não estão como o teste montou: {semaforo.vagas_livres}"
        )
        assert len(ModeloQueSeguraAVaga.turnos) == 1, (
            "os dois turnos do mesmo Aluno chamaram o modelo ao mesmo tempo"
        )

        ModeloQueSeguraAVaga.soltar()
        primeiro.esperar()
        segundo.esperar()
        assert len(entregas.esperar(61, 4)) == 4

        assert ModeloQueSeguraAVaga.maximo_simultaneo == 1, (
            "um Aluno teve dois turnos no modelo ao mesmo tempo: "
            f"{ModeloQueSeguraAVaga.maximo_simultaneo}"
        )
        assert semaforo.vagas_livres == 2
        # Nenhuma posição na fila para o mesmo Aluno: a espera dele foi a conversa, e
        # não a fila do semáforo. A afirmação é a **ausência** da mensagem de posição
        # e não a igualdade da lista: os dois acuses saem dos dois requests, ambos
        # antes de o primeiro turno responder, e a ordem entre eles não é o que este
        # teste está medindo. O que ele mede é que nada entrou na fila do semáforo.
        recebidas = entregas.textos(61)
        assert not [texto for texto in recebidas if "posição" in texto], (
            f"o mesmo Aluno levou mensagem de fila, e a espera dele é a conversa: {recebidas}"
        )
        assert recebidas.count(ModeloQueSeguraAVaga.texto) == 2, (
            f"os dois turnos do mesmo Aluno não foram respondidos: {recebidas}"
        )
    finally:
        ModeloQueSeguraAVaga.soltar()
        telegram.fechar()


@pytest.mark.parametrize("origem", ["injetado", "da-configuracao"])
def test_acima_do_teto_o_turno_e_recusado(
    origem: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Passado o teto, o turno é recusado — e a recusa vem por **qualquer** das origens.

    Uma vaga, teto de um: a Aluna 71 segura o modelo, a 72 espera, e a 73 é recusada. O
    que a parametrização prova é que o teto funciona nos dois caminhos, e que os dois
    caminhos são de fato Exercitados:

    - `injetado` monta um semáforo na mão e passa no `criar_app`. É o caminho dos testes
      de fila, em que a vaga precisa ser segurada em estado que o teste controle.
    - `da-configuracao` não passa semáforo nenhum: o `criar_app` monta o dele a partir
      de `INFERENCIA_K` e `INFERENCIA_FILA_TETO`. É o caminho de produção, e sem ele a
      parametrização seria meia verdade — o teto testado seria o do objeto de teste, e o
      do `.env` ficaria sem prova nenhuma.

    E o que a recusa não pode fazer é chamar o modelo: recusar por fila cheia antes de
    inferir é o que evita gastar a única VRAM da máquina com um turno que já foi
    recusado. É a asserção `turnos == 1` com a vaga ainda ocupada.
    """
    entregas = Entregas()
    telegram = TelegramFalso(ao_entregar=entregas.ao_entregar)
    ModeloQueSeguraAVaga.destravar()
    try:
        monkeypatch.setattr(webhook, "ClienteOllama", ModeloQueSeguraAVaga)
        if origem == "injetado":
            semaforo = SemaforoDeInferencia(k=1, teto=1)
            app = _app(telegram, executor=None, semaforo=semaforo)
        else:
            # O caminho de produção monta o semáforo dentro do `criar_app`, e aí o
            # teste não tem a referência dele para olhar. Registrar a instância
            # construída é o que fecha este caminho: sem o registro, a única
            # alternativa seria afirmar só o texto do Aluno, e um `criar_app` que
            # ignorasse o `INFERENCIA_K` e montasse `k=100` passaria — porque com
            # `k=100` a fila nunca enche e o teto nunca recusa.
            montados: list[SemaforoDeInferencia] = []

            class SemaforoQueSeRegistra(SemaforoDeInferencia):
                """O semáforo de produção, que anota a si mesmo ao ser montado."""

                def __init__(self, k: int, teto: int) -> None:
                    super().__init__(k, teto)
                    montados.append(self)

            monkeypatch.setattr(webhook, "SemaforoDeInferencia", SemaforoQueSeRegistra)
            app = _app(
                telegram,
                executor=None,
                env={"INFERENCIA_K": "1", "INFERENCIA_FILA_TETO": "1"},
            )
            assert len(montados) == 1, f"o app não montou semáforo nenhum: {montados}"
            semaforo = montados[0]
            assert semaforo.k == 1 and semaforo.teto == 1, (
                f"o semáforo do app ignorou o ambiente: k={semaforo.k}, "
                f"teto={semaforo.teto}"
            )

        primeiro = VooDePost(
            lambda: _postar(app, _update_de(71, "qual o prazo da Atividade 1?"))
        )
        ModeloQueSeguraAVaga.esperar_chegadas(1)
        segundo = VooDePost(lambda: _postar(app, _update_de(72, "e a de matemática?")))
        # A 72 tem de estar de fato na fila antes de a 73 chegar, senão o teto seria
        # testado com a fila vazia e a recusa viria por outro motivo. A espera é pela
        # mensagem de posição da 72, que é o próprio sinal de "entrei na fila" — e é
        # o que evita ler `turnos_esperando` no meio de uma corrida.
        textos_da_72 = entregas.esperar(72, 2)
        assert "posição 2" in textos_da_72[1], textos_da_72[1]
        terceiro = VooDePost(lambda: _postar(app, _update_de(73, "e a de história?")))

        assert entregas.esperar(73, 2) == [TEXTO_ACK, TEXTO_FILA_CHEIA], (
            f"o turno acima do teto não recebeu a recusa: {entregas.textos(73)}"
        )
        assert len(ModeloQueSeguraAVaga.turnos) == 1, (
            "o turno recusado chamou o modelo: a VRAM foi gasta com um turno recusado"
        )

        ModeloQueSeguraAVaga.soltar()
        terceiro.esperar()
        segundo.esperar()
        primeiro.esperar()

        # E a recusa não quebrou a fila: quem já estava esperando foi atendido.
        assert len(ModeloQueSeguraAVaga.turnos) == 2, (
            f"só {len(ModeloQueSeguraAVaga.turnos)} turnos chegaram ao modelo, e "
            "quem já estava na fila devia ter sido atendido"
        )
        assert entregas.textos(72)[-1] == ModeloQueSeguraAVaga.texto
    finally:
        ModeloQueSeguraAVaga.soltar()
        telegram.fechar()


def test_a_fila_cheia_recusa_o_aluno_com_educacao(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A recusa é uma resposta completa: educada no texto, `warning` no log, no histórico.

    São três afirmações sobre três públicos, e as três importam:

    - **o Aluno** lê a frase da recusa e não a de falha. As duas mensagens existem
      porque os diagnósticos são diferentes: a falha diz que algo quebrou, a recusa diz
      que a fila encheu. Um turno que devolvesse a `TEXTO_FALHA` diria ao Aluno que o
      S.A.U. quebrou quando o que houve foi muito Aluno perguntando ao mesmo tempo.
    - **o operador** lê um `warning` e não um `error`. Nada quebrou — a fila encheu, que
      é o que o teto existe para transformar em resposta. Um `error` aqui seria alarme
      falso em cima de um sistema que está funcionando como projetado.
    - **o próximo turno do mesmo Aluno** lê um histórico que contém a recusa. A
      invariante é a da #9: o histórico não pode divergir do que o Aluno leu. Se a
      recusa não entrasse, o modelo veria uma pergunta sem resposta e tenderia a tratar
      a Atividade como já respondida.

    A recusa entra pelo mesmo `registrar_do_sau` da falha, e é por isso que a terceira
    afirmação não é uma exceção no caminho: é o caminho normal do turno recusado.
    """
    entregas = Entregas()
    telegram = TelegramFalso(ao_entregar=entregas.ao_entregar)
    registro = RegistroDeConversas(str(tmp_path / "conversas.db"))
    ModeloQueSeguraAVaga.destravar()
    try:
        monkeypatch.setattr(webhook, "ClienteOllama", ModeloQueSeguraAVaga)
        semaforo = SemaforoDeInferencia(k=1, teto=1)
        app = _app(telegram, registro=registro, executor=None, semaforo=semaforo)

        with caplog.at_level(logging.WARNING, logger=LOGGER):
            primeiro = VooDePost(
                lambda: _postar(app, _update_de(81, "qual o prazo da Atividade 1?"))
            )
            ModeloQueSeguraAVaga.esperar_chegadas(1)
            segundo = VooDePost(
                lambda: _postar(app, _update_de(82, "e a de matemática?"))
            )
            # A 82 na fila pelo observável, e não por leitura do contador: a mensagem de
            # posição é o sinal de que ela entrou, e esperar por ela tira a corrida da
            # afirmação seguinte.
            assert "posição 2" in entregas.esperar(82, 2)[1]
            recusado = VooDePost(
                lambda: _postar(app, _update_de(83, "e a de história?"))
            )
            # A recusa chega da thread do turno, e por isso se espera por ela como se
            # espera por qualquer entrega: o `VooDePost` ter subido não diz que o
            # turno já rodou.
            assert entregas.esperar(83, 2) == [TEXTO_ACK, TEXTO_FILA_CHEIA]

            ModeloQueSeguraAVaga.soltar()
            recusado.esperar()
            segundo.esperar()
            primeiro.esperar()

        assert TEXTO_FILA_CHEIA != TEXTO_FALHA, (
            "a recusa virou a mensagem de falha: o Aluno leria que o S.A.U. quebrou"
        )
        registros_do_aluno = [
            r for r in caplog.records if r.levelno == logging.WARNING and "83" in r.getMessage()
        ]
        assert registros_do_aluno, (
            "a recusa não deixou nenhum warning no log: o operador não descobre por que "
            "o Aluno foi recusado"
        )
        assert not [
            r
            for r in caplog.records
            if r.levelno >= logging.ERROR and "83" in r.getMessage()
        ], "a recusa foi logada como erro: a fila encheu, e nada quebrou"

        # E a recusa entrou na conversa, para o próximo turno do mesmo Aluno.
        historico = registro.conversa(83).historico()
        assert [m.texto for m in historico] == [
            "e a de história?",
            TEXTO_FILA_CHEIA,
        ], f"a conversa do Aluno recusado não é a conversa que ele teve: {historico}"
    finally:
        ModeloQueSeguraAVaga.soltar()
        registro.fechar()
        telegram.fechar()


def test_dois_alunos_sao_atendidos_ao_mesmo_tempo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`k=2` atende dois Alunos ao mesmo tempo — o que é o ponto inteiro do `k`.

    Este é o teste que impede o semáforo de ser um semáforo de **uma** vaga com nome de
    limite: com `k=2` e dois Alunos, os dois têm de estar dentro do modelo juntos. A
    primeira versão deste módulo tinha exatamente esse defeito — a senha só avançava na
    devolução da vaga, então o segundo turno esperava o primeiro **terminar**, e o `k`
    limitava uma pessoa por vez sem que nada disso aparecesse no código de quem lê.

    A afirmação é o **maior** paralelismo visto, e não o total de chamadas: duas chamadas
    em série e duas juntas dão o mesmo total, e só a segunda coisa é o que o `k`
    promete. Por isso o `ModeloQueSeguraAVaga` conta o máximo de chamadas que coexistem
    em vez de contar chamadas.

    Os dois Alunos esperam a mesma estimativa, e ambos recebem a resposta depois. A
    estimativa igual não é detalhe: ela mostra que a contagem de posição não é um contador
    vitalício, e os dois leram a mesma espera porque estão na mesma situação de fato.
    """
    entregas = Entregas()
    telegram = TelegramFalso(ao_entregar=entregas.ao_entregar)
    ModeloQueSeguraAVaga.destravar()
    try:
        monkeypatch.setattr(webhook, "ClienteOllama", ModeloQueSeguraAVaga)
        semaforo = SemaforoDeInferencia(k=2)
        app = _app(telegram, executor=None, semaforo=semaforo)

        primeiro = VooDePost(
            lambda: _postar(app, _update_de(91, "qual o prazo da Atividade 1?"))
        )
        segundo = VooDePost(lambda: _postar(app, _update_de(92, "e a de matemática?")))

        ModeloQueSeguraAVaga.esperar_chegadas(2)
        assert semaforo.vagas_livres == 0, "as duas vagas deveriam estar ocupadas"
        assert ModeloQueSeguraAVaga.maximo_simultaneo == 2, (
            "com k=2 os dois Alunos não entraram juntos: o maior paralelismo foi "
            f"{ModeloQueSeguraAVaga.maximo_simultaneo}, e o k não está limitando nada"
        )
        # Nenhum dos dois leu posição: com vaga livre o turno entra sem esperar, e uma
        # posição seria uma mentira sobre a fila que ele está vendo.
        assert len(entregas.textos(91)) == 1, entregas.textos(91)
        assert len(entregas.textos(92)) == 1, entregas.textos(92)

        ModeloQueSeguraAVaga.soltar()
        segundo.esperar()
        primeiro.esperar()

        assert entregas.textos(91) == [TEXTO_ACK, ModeloQueSeguraAVaga.texto]
        assert entregas.textos(92) == [TEXTO_ACK, ModeloQueSeguraAVaga.texto]
        assert semaforo.vagas_livres == 2, "as vagas não voltaram depois dos dois turnos"
    finally:
        ModeloQueSeguraAVaga.soltar()
        telegram.fechar()
