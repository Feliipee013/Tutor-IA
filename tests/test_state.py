"""Testes do estado por conversa, sau/graph/state.py.

O que se prova aqui é o estado da conversa, e não o S.A.U.: o histórico de um Aluno
não aparece na conversa de outro; ele sobrevive a um reinício do serviço; conversa
inativa expira; e duas mensagens do mesmo Aluno não se embaralham.

Cada teste declara o contrato que precisa — o relógio, o `chat_id`, o texto — em vez
de importar o texto de outro arquivo de teste. As fakes de modelo e de Telegram são
de `test_webhook.py`, e aqui não há modelo nenhum: quem é exercitado é o registro.

**Nada aqui espera tempo de relógio.** O TTL recebe um relógio injetado e a fila recebe
um `threading.Event` controlado pelo próprio teste. Um teste de concorrência que dorme
é um teste que passa quase sempre.
"""

from __future__ import annotations

import dataclasses
import logging
import sqlite3
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from sau.graph.state import (
    MAXIMO_DE_MENSAGENS,
    TETO_DE_TURNOS_ESPERANDO,
    Mensagem,
    RegistroDeConversas,
)

_ALUNA = 55_512_345
_OUTRA_ALUNA = 55_512_346


class Relogio:
    """Um relógio que só anda quando o teste manda.

    Existe porque o TTL é a única parte do registro que depende de tempo, e esperar
    trinta minutos de verdade não é teste. `avancar` é o que faz o tempo passar: um
    registrador com este relógio no lugar de `time.time` é um registro cujo tempo o
    teste controla inteiro.
    """

    def __init__(self, agora: float = 1_700_000_000.0) -> None:
        self.agora = agora

    def __call__(self) -> float:
        return self.agora

    def avancar(self, minutos: float) -> None:
        self.agora += minutos * 60


@pytest.fixture
def relogio() -> Relogio:
    return Relogio()


@pytest.fixture
def registro(tmp_path: Path, relogio: Relogio) -> Iterator[RegistroDeConversas]:
    """Um registro novo em arquivo temporário, com o relógio do teste dentro."""
    registro_de_conversas = RegistroDeConversas(
        str(tmp_path / "conversas.db"), ttl_minutos=30, agora=relogio
    )
    yield registro_de_conversas
    registro_de_conversas.fechar()


def _troca(registro: RegistroDeConversas, chat_id: int, pergunta: str, resposta: str) -> None:
    """Grava um turno inteiro, do jeito que o `webhook` grava."""
    conversa = registro.conversa(chat_id)
    with conversa.em_ordem():
        conversa.registrar_do_aluno(pergunta, 0.0)
        conversa.registrar_do_sau(resposta, 0.0)


# --- Isolamento: a conversa de uma Aluna não é a da outra ---


def test_o_historico_de_uma_aluna_nao_aparece_na_conversa_da_outra(
    registro: RegistroDeConversas,
) -> None:
    """Duas `chat_id` no mesmo registro, e o histórico de uma não é o da outra.

    É o critério de isolamento da #9 na sua forma mais crua: o registro devolve por
    `chat_id`, e o que ele devolve é só daquela. Um registro com uma lista só de
    mensagens passaria por quase todo o resto da suíte — a falha só apareceria na
    resposta do modelo, ou seja, tarde demais para ser fácil.
    """
    _troca(registro, _ALUNA, "qual o prazo da Atividade 2?", "vence dia 12")
    _troca(registro, _OUTRA_ALUNA, "e a de inglês?", "vence dia 19")

    da_aluna = registro.historico(_ALUNA)
    da_outra = registro.historico(_OUTRA_ALUNA)

    assert [m.texto for m in da_aluna] == ["qual o prazo da Atividade 2?", "vence dia 12"]
    assert [m.texto for m in da_outra] == ["e a de inglês?", "vence dia 19"]
    assert all(m.texto != "vence dia 12" for m in da_outra)


def test_a_mensagem_do_aluno_e_a_do_sau_sao_gravadas_pelo_papel_certo(
    registro: RegistroDeConversas,
) -> None:
    """O `papel` sobrevive ao arquivo, porque é ele que desenha a linha do prompt.

    Um registro que gravasse tudo como `sau` faria o modelo ler a própria pergunta do
    Aluno como se ele a tivesse dito, e o histórico inteiro viraria uma alucinação
    estrutural. É por isso que `Mensagem.papel` é `Literal` e não `str`.
    """
    _troca(registro, _ALUNA, "qual o prazo da Atividade 2?", "vence dia 12")

    assert [m.papel for m in registro.historico(_ALUNA)] == ["aluno", "sau"]


def test_o_historico_de_uma_conversa_nova_e_vazio(registro: RegistroDeConversas) -> None:
    """Conversa que nunca falou tem histórico vazio, e não erro.

    `chat_id` que nunca apareceu é a primeira mensagem de todo Aluno novo, e é o caso
    mais comum do serviço. Um registro que devolvesse `None` aqui transformaria o
    primeiro turno de todo Aluno numa falha.
    """
    assert registro.historico(999) == []


# --- Persistência: o estado sobrevive ao reinício ---


def test_a_conversa_sobrevive_a_um_reinicio_do_servico(tmp_path: Path) -> None:
    """O estado sobrevive a um reinício, que é o critério de aceitação da #9.

    Grava, fecha, reabre no mesmo caminho e relê. É o caminho real do
    `docker compose down` seguido de `up` com o volume nomeado: o processo novo não
    tem memória nenhuma, e o que ele sabe do Aluno vem do arquivo.

    Sem o `fechar` explícito o teste passaria mesmo com o estado só em memória, porque
    a mesma `RegistroDeConversas` continua aberta — por isso o registro novo é uma
    instância de verdade, não um método que devolve a mesma.
    """
    caminho = str(tmp_path / "conversas.db")

    primeiro = RegistroDeConversas(caminho)
    _troca(primeiro, _ALUNA, "qual o prazo da Atividade 2?", "vence dia 12")
    primeiro.fechar()

    segundo = RegistroDeConversas(caminho)
    try:
        assert [m.texto for m in segundo.historico(_ALUNA)] == [
            "qual o prazo da Atividade 2?",
            "vence dia 12",
        ]
    finally:
        segundo.fechar()


def test_a_conversa_reaberta_no_arquivo_e_a_mesma_e_nao_outra(
    tmp_path: Path,
) -> None:
    """Reabrir devolve a conversa com o mesmo histórico, e não uma conversa nova.

    O `conversa()` do registro novo tem que achar as mensagens no arquivo. Se ele
    recriasse a linha e o histórico viesse da memória apenas, o critério anterior
    passaria e este quebraria — e o defeito é o mesmo visto pelo outro lado: o Aluno
    perdendo o contexto depois de um reinício do serviço.
    """
    caminho = str(tmp_path / "conversas.db")

    primeiro = RegistroDeConversas(caminho)
    _troca(primeiro, _ALUNA, "qual o prazo da Atividade 2?", "vence dia 12")
    primeiro.fechar()

    segundo = RegistroDeConversas(caminho)
    try:
        conversa = segundo.conversa(_ALUNA)
        assert [m.texto for m in conversa.historico()] == [
            "qual o prazo da Atividade 2?",
            "vence dia 12",
        ]
    finally:
        segundo.fechar()


def test_o_registro_abre_o_arquivo_em_wal(tmp_path: Path) -> None:
    """A conexão abre em `journal_mode=WAL`, e isto é uma afirmação de comportamento.

    Com WAL, a leitura do histórico de uma Aluna não bloqueia a escrita de outra. Sem
    ele o SQLite serializa tudo no arquivo, e a tranca interna do registro vira fila em
    vez de folga — o que o ADR-0001 rejeita, já que ele não quer serializar o serviço
    inteiro para ordenar turnos de uma conversa só.

    O `journal_mode` é lido do próprio arquivo aberto, e não de um atributo: um
    `PRAGMA` executado e ignorado passaria por qualquer teste que só olhasse o código.
    """
    caminho = str(tmp_path / "conversas.db")
    registro = RegistroDeConversas(caminho)
    registro.fechar()

    conexao = sqlite3.connect(caminho)
    try:
        modo = conexao.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        conexao.close()

    assert modo.lower() == "wal"


# --- TTL: conversa inativa expira ---


def test_conversa_inativa_expira_e_sai_da_memoria(
    registro: RegistroDeConversas, relogio: Relogio
) -> None:
    """Depois do TTL o registro apaga as linhas e a conversa sai do dicionário.

    Este é o critério "conversas inativas expiram, sem crescimento ilimitado", e ele
    tem duas metades porque as duas falham de jeitos diferentes: a linha no arquivo
    que continua lá é o arquivo crescendo; a `Conversa` no dicionário é a memória
    crescendo. Afirmar só a primeira deixaria a segunda de fora, e é a segunda que
    derruba o serviço depois de uma noite inteira de plantão.

    O relógio é o do teste, e por isso não há espera: `avancar(31)` é o que faz os
    trinta minutos do TTL passarem.
    """
    _troca(registro, _ALUNA, "qual o prazo da Atividade 2?", "vence dia 12")
    relogio.avancar(31)

    vencidas = registro.expirar()

    assert vencidas == [_ALUNA]
    assert registro.historico(_ALUNA) == []
    assert _ALUNA not in registro.conversas_vivas


def test_conversa_que_ainda_esta_no_ttl_sobrevive(
    registro: RegistroDeConversas, relogio: Relogio
) -> None:
    """Um minuto a menos que o TTL não expira, e isto é a outra metade do critério.

    O teste anterior provaria que a expiração acontece, e passaria com um TTL de
    zero. Este segura o outro lado: um Aluno que deu uma pausa curta de madrugada
    continua com a conversa quando volta, que é a diferença entre um produto e um
    cadastro de mensagens.
    """
    _troca(registro, _ALUNA, "qual o prazo da Atividade 2?", "vence dia 12")
    relogio.avancar(29)

    assert registro.expirar() == []
    assert [m.texto for m in registro.historico(_ALUNA)][0] == "qual o prazo da Atividade 2?"


def test_a_varredura_apaga_so_a_conversa_vencida(
    registro: RegistroDeConversas, relogio: Relogio
) -> None:
    """Duas conversas com idades diferentes: a varredura pega a velha e não a nova.

    Uma varredura que apaga tudo passa em todos os outros testes de TTL, e é por isso
    que este existe: o defeito de uma limpeza por horário é apagar a conversa de quem
    acabou de perguntar.

    A varredura acontece em `conversa()`, e não precisa de uma chamada separada: é o
    turno da segunda Aluna que varre, e o resultado é o mesmo. Por isso a afirmação é
    feita logo depois do turno, e não antes.
    """
    _troca(registro, _ALUNA, "qual o prazo da Atividade 2?", "vence dia 12")
    relogio.avancar(31)
    _troca(registro, _OUTRA_ALUNA, "e a de inglês?", "vence dia 19")

    assert registro.historico(_ALUNA) == []
    assert _ALUNA not in registro.conversas_vivas
    assert [m.texto for m in registro.historico(_OUTRA_ALUNA)] == ["e a de inglês?", "vence dia 19"]
    assert registro.conversas_vivas == [_OUTRA_ALUNA]


def test_a_varredura_acontece_no_caminho_do_turno(
    registro: RegistroDeConversas, relogio: Relogio
) -> None:
    """A limpeza é oportunista, e não há cron nem thread de fundo para chamá-la.

    Chamar `conversa()` de uma Aluna nova varre as inativas. É o que prende a memória
    à taxa real de turnos em vez de a um horário: num serviço parado a noite inteira,
    nada cresce; num serviço com movimento, a limpeza acontece no ritmo do movimento.

    Sem esta afirmação, uma implementação com `expirar()` exposto e nunca chamado
    passaria toda a suíte — o registro ficaria de pé, sem ninguém chamando a limpeza.
    """
    _troca(registro, _ALUNA, "qual o prazo da Atividade 2?", "vence dia 12")
    relogio.avancar(31)

    registro.conversa(_OUTRA_ALUNA)

    assert _ALUNA not in registro.conversas_vivas
    assert registro.historico(_ALUNA) == []


def test_um_turno_novao_nao_apaga_a_conversa_que_acabou_de_falar(
    registro: RegistroDeConversas, relogio: Relogio
) -> None:
    """Falar toca a conversa, e é o que impede o turno seguinte de se autoapagar.

    O `registrar` grava o `ultimo_turno` junto com a mensagem. Um registro que só
    escrevesse a mensagem deixaria a conversa envelhecer durante o próprio turno, e o
    Aluno que voltou depois de uma pausa longa perderia a mensagem que acabou de
    mandar — o pior dos dois jeitos de errar o TTL.
    """
    _troca(registro, _ALUNA, "primeira pergunta", "primeira resposta")
    relogio.avancar(29)
    _troca(registro, _ALUNA, "segunda pergunta", "segunda resposta")

    assert registro.expirar() == []
    assert len(registro.historico(_ALUNA)) == 4


# --- Ordem: duas mensagens do mesmo Aluno não se embaralham ---


def test_o_turno_que_veio_depois_espera_o_que_ja_estava_rodando(
    registro: RegistroDeConversas,
) -> None:
    """Dois turnos do mesmo `chat_id`, e o segundo não entra antes de o primeiro sair.

    A prova é o **evento**, e não o tempo: o segundo turno só chega ao `yield` depois
    que o primeiro liberou. Um teste que esperasse por tempo afirmaria uma coisa que
    também seria verdade com a fila quebrada e a máquina lenta.

    O primeiro turno segura o `em_ordem` num evento que o teste controla, e o segundo
    roda numa thread de verdade — que é como ele roda no serviço. Se a fila não
    existisse, o segundo `yield` aconteceria enquanto o primeiro ainda segurava, e o
    `esperado` marcaria os dois em ordem errada.
    """
    conversa = registro.conversa(_ALUNA)
    entrou_o_primeiro = threading.Event()
    solta_o_primeiro = threading.Event()
    ordem: list[str] = []

    def primeiro_turno() -> None:
        with conversa.em_ordem():
            ordem.append("primeiro começou")
            entrou_o_primeiro.set()
            solta_o_primeiro.wait(timeout=5.0)
            ordem.append("primeiro terminou")

    thread = threading.Thread(target=primeiro_turno)
    thread.start()
    assert entrou_o_primeiro.wait(5.0), "o primeiro turno não entrou na fila"

    segundo_passou = threading.Event()

    def segundo() -> None:
        with conversa.em_ordem():
            ordem.append("segundo começou")
            segundo_passou.set()

    thread_do_segundo = threading.Thread(target=segundo)
    thread_do_segundo.start()
    try:
        # O segundo ainda não pode ter passado: o primeiro segura a conversa. O
        # `wait` com timeout curto é o que torna a falha visível em vez de um
        # `assert` que passa só porque o teste terminou antes da thread.
        assert not segundo_passou.wait(0.2), (
            f"o segundo turno entrou antes do primeiro sair: {ordem}"
        )
    finally:
        solta_o_primeiro.set()
        thread.join(timeout=5.0)
        thread_do_segundo.join(timeout=5.0)

    assert ordem == ["primeiro começou", "primeiro terminou", "segundo começou"]


def test_alunos_diferentes_nao_esperam_um_pelo_outro(registro: RegistroDeConversas) -> None:
    """Conversas diferentes têm filas diferentes, e uma não segura a outra.

    A fila por conversa é o que garante a ordem do Aluno; ela não pode virar um lock
    global. Este teste segura a conversa de uma Aluna e roda o turno da outra sem
    esperar: se as filas fossem uma só, o turno da segunda Aluna ficaria preso atrás
    do primeiro, e o plantão da madrugada — que é de várias pessoas acordadas ao mesmo
    tempo — pararia.
    """
    primeira = registro.conversa(_ALUNA)
    segunda = registro.conversa(_OUTRA_ALUNA)
    solta = threading.Event()
    entrou = threading.Event()

    def segurando() -> None:
        with primeira.em_ordem():
            entrou.set()
            solta.wait(timeout=5.0)

    thread = threading.Thread(target=segurando)
    thread.start()
    assert entrou.wait(5.0)

    rodou = threading.Event()
    try:

        def da_outra() -> None:
            with segunda.em_ordem():
                rodou.set()

        thread_da_outra = threading.Thread(target=da_outra)
        thread_da_outra.start()
        thread_da_outra.join(timeout=5.0)
        assert rodou.is_set(), "a fila de uma Aluna segurou o turno de outra"
    finally:
        solta.set()
        thread.join(timeout=5.0)


def test_o_turno_em_andamento_nao_conta_para_o_teto_de_espera(
    registro: RegistroDeConversas,
) -> None:
    """A contagem do teto vale só para a fila de espera, e o turno andando não conta.

    O teto é alarme, e um alarme que dispara com um Aluno só mandando mensagem é um
    alarme que ninguém lê. Este segura um turno e diz que a contagem é zero enquanto
    ele está rodando: é o que separa "um Aluno esperando" de "um Aluno esperando mais
    seis".
    """
    conversa = registro.conversa(_ALUNA)
    entrou = threading.Event()
    solta = threading.Event()

    def segurando() -> None:
        with conversa.em_ordem():
            entrou.set()
            solta.wait(timeout=5.0)

    thread = threading.Thread(target=segurando)
    thread.start()
    try:
        assert entrou.wait(5.0)
        assert conversa.turnos_esperando == 0, (
            f"o turno em andamento foi contado como espera: {conversa.turnos_esperando}"
        )
    finally:
        solta.set()
        thread.join(timeout=5.0)


def test_o_teto_de_turnos_esperando_avisa_e_nao_recusa(
    registro: RegistroDeConversas, caplog: pytest.LogCaptureFixture
) -> None:
    """Estourar o teto avisa no log, e nenhum turno é recusado.

    A distinção é o ponto do teto: recusar aqui seria pior do que esperar. O acuse já
    saiu no request, então um turno recusado deixaria o Aluno lendo "recebi sua
    mensagem" e sem resposta nenhuma. Quem recusa e quem comunica a posição é a #11,
    com o semáforo.

    A montagem é a do serviço: um turno segurando a conversa e, atrás dele, mais turnos
    do que o teto permite. O aviso é afirmado **enquanto a fila está cheia**, porque
    depois que tudo entra a fila zera e o aviso deixa de ser verdade — as duas metades
    da garantia estão neste teste, e é a segunda que impede um teto que recusa.
    """
    conversa = registro.conversa(_ALUNA)
    rodados: list[int] = []
    soltas: list[threading.Event] = []

    def segurar(numero: int, solta: threading.Event) -> None:
        with conversa.em_ordem():
            rodados.append(numero)
            solta.wait(timeout=5.0)

    def comeca(numero: int) -> threading.Thread:
        solta = threading.Event()
        soltas.append(solta)
        thread = threading.Thread(target=segurar, args=(numero, solta))
        thread.start()
        return thread

    threads: list[threading.Thread] = []
    try:
        # O `caplog` é instalado **antes** das threads: o aviso sai no `with` do turno
        # que entra, e uma janela aberta depois deixaria o primeiro aviso de fora —
        # que é justamente o aviso do primeiro turno acima do teto.
        with caplog.at_level(logging.WARNING, logger="sau.graph.state"):
            # O turno 0 segura a conversa e não conta para o teto; ele só abre caminho
            # para os outros entrarem na fila.
            threads.append(comeca(0))
            for numero in range(1, TETO_DE_TURNOS_ESPERANDO + 2):
                threads.append(comeca(numero))

            # Esperar o **aviso** aparecer, e não a contagem: a contagem é incrementada
            # antes de o aviso sair, e esperar por ela abriria uma janela em que o turno
            # já está na fila e o operador ainda não foi avisado. O aviso é a garantia.
            _espera_ate(
                lambda: any("turnos esperando" in r.getMessage() for r in caplog.records),
                f"a fila do Aluno não chegou ao teto: {conversa.turnos_esperando}",
            )
            avisos = [
                r.getMessage() for r in caplog.records if "turnos esperando" in r.getMessage()
            ]
    finally:
        for solta in soltas:
            solta.set()
        for thread in threads:
            thread.join(timeout=5.0)

    assert avisos, f"o teto de turnos esperando não avisou: {avisos}"
    # E ninguém foi recusado: todos os turnos, um a um, entraram e saíram.
    assert sorted(rodados) == list(range(TETO_DE_TURNOS_ESPERANDO + 2)), (
        f"algum turno foi recusado ou pulado: {sorted(rodados)}"
    )
    assert conversa.turnos_esperando == 0


def _espera_ate(condicao: Callable[[], bool], mensagem: str) -> None:
    """Espera a condição ficar verdadeira, e falha com a mensagem se não ficar.

    Não é `sleep`: o tempo limite é o teto do teste, e a espera é pelo **estado**. Um
    `sleep(0.2)` seguido de um `assert` passa ou falha conforme a máquina, e é o jeito
    de escrever teste de concorrência que não se pode confiar.
    """
    limite = time.monotonic() + 5.0
    while time.monotonic() < limite:
        if condicao():
            return
        time.sleep(0.005)
    raise AssertionError(mensagem)


def test_fechar_o_registro_libera_quem_estava_na_fila(
    registro: RegistroDeConversas,
) -> None:
    """O `fechar` acorda quem estava na fila, e ninguém fica esperando para sempre.

    O limite conhecido do `em_ordem` é que a espera não tem teto de tempo — quem segura
    a fila é o `OLLAMA_TIMEOUT` e o `except` largo do turno, e é isso que garante a
    liberação no caminho normal. Este é o caminho **não** normal: a conversa morre
    enquanto um turno está em andamento e outro está atrás dele. Sem o `encerrar` do
    `fechar`, o segundo ficaria esperando uma senha que ninguém vai servir, e o
    `docker compose down` seguraria o processo.
    """
    conversa = registro.conversa(_ALUNA)
    entrou = threading.Event()
    solta_o_turno = threading.Event()

    def segurando() -> None:
        with conversa.em_ordem():
            entrou.set()
            solta_o_turno.wait(timeout=5.0)

    thread_do_turno = threading.Thread(target=segurando)
    thread_do_turno.start()
    assert entrou.wait(5.0), "o turno não entrou na fila"

    esperou = threading.Event()

    def na_fila() -> None:
        with conversa.em_ordem():
            esperou.set()

    thread_na_fila = threading.Thread(target=na_fila)
    thread_na_fila.start()
    try:
        registro.fechar()
        thread_na_fila.join(timeout=5.0)
        assert not thread_na_fila.is_alive(), (
            "quem estava na fila ficou esperando o registro fechar"
        )
        assert esperou.is_set(), "o turno da fila não chegou a rodar"
    finally:
        solta_o_turno.set()
        thread_do_turno.join(timeout=5.0)


def test_a_conversa_que_cai_no_ttl_libera_o_turno_que_a_esperava(
    registro: RegistroDeConversas, relogio: Relogio
) -> None:
    """A conversa que expira durante um turno acorda quem estava na fila dela.

    Sem isto, um turno que entrou na fila de uma conversa que o TTL apagou ficaria
    esperando por um `Event` que ninguém mais vai setar — e essa espera não tem teto.
    O turno perdido é um Aluno com o acuse na mão e nenhuma resposta, que é o pior
    estado em que o canal do Telegram pode ficar.
    """
    conversa = registro.conversa(_ALUNA)
    entrou = threading.Event()
    solta = threading.Event()

    def segurando() -> None:
        with conversa.em_ordem():
            entrou.set()
            solta.wait(timeout=5.0)

    thread = threading.Thread(target=segurando)
    thread.start()
    assert entrou.wait(5.0)

    esperando = threading.Event()
    rodou = threading.Event()

    def na_fila() -> None:
        with conversa.em_ordem():
            rodou.set()
        esperando.set()

    thread_na_fila = threading.Thread(target=na_fila)
    thread_na_fila.start()
    try:
        relogio.avancar(31)
        registro.expirar()
        thread_na_fila.join(timeout=5.0)
        assert rodou.is_set(), "o turno da conversa expirada ficou preso na fila"
    finally:
        solta.set()
        thread.join(timeout=5.0)


# --- Teto de mensagens por conversa ---


def test_o_historico_lido_nao_passa_do_teto_de_mensagens(
    registro: RegistroDeConversas,
) -> None:
    """Mais de `MAXIMO_DE_MENSAGENS` mensagens entram, e a leitura devolve as últimas.

    O teto é do **prompt** e da leitura, não da escrita: o registro continua gravando
    tudo até o TTL, porque apagar a linha antiga a cada insert seria uma segunda
    escrita por turno, e o que o teto quer é que ninguém leia conversa demais.

    As mensagens mais antigas ficam de fora da leitura, e é esse o ponto: o que o
    modelo vê é a conversa mais recente, e o que o arquivo guarda é tudo.
    """
    for numero in range(MAXIMO_DE_MENSAGENS + 10):
        _troca(registro, _ALUNA, f"pergunta {numero}", f"resposta {numero}")

    historico = registro.historico(_ALUNA)
    # 50 turnos são 100 linhas, e o teto corta as 60 primeiras. Cada turno escreve
    # duas linhas, então o que sobra começa na 31ª pergunta.
    assert len(historico) == MAXIMO_DE_MENSAGENS
    assert historico[0].texto == "pergunta 30"
    assert historico[-1].texto == f"resposta {MAXIMO_DE_MENSAGENS + 9}"


def test_a_escrita_nao_corta_o_historico_e_a_leitura_corta(
    registro: RegistroDeConversas,
) -> None:
    """O arquivo guarda tudo; o que a leitura devolve é o recorte.

    Um registro que apagasse a mensagem antiga na escrita passaria pelo teste do teto e
    falharia aqui — e a diferença importa porque o arquivo é o que sobrevive ao
    reinício: cortar na escrita é perder conversa de um Aluno que deu um dia de plantão.
    A afirmação é a separação, e não o número do teto.
    """
    for numero in range(MAXIMO_DE_MENSAGENS + 2):
        _troca(registro, _ALUNA, f"pergunta {numero}", f"resposta {numero}")

    caminho = registro.caminho
    linhas = _total_de_linhas_no_arquivo(caminho)
    assert linhas == MAXIMO_DE_MENSAGENS * 2 + 4


def _total_de_linhas_no_arquivo(caminho: str) -> int:
    """Quantas linhas de mensagem o arquivo tem, contando por fora do registro.

    Abre uma segunda conexão de leitura só para isso: é o que prova que o corte é do
    registro e não um esquecimento do histórico em memória.
    """
    conexao = sqlite3.connect(caminho)
    try:
        return int(conexao.execute("SELECT COUNT(*) FROM mensagem").fetchone()[0])
    finally:
        conexao.close()


# --- A linha que vai no prompt ---


def test_a_linha_do_prompt_diz_quem_falou_com_as_palavras_do_projeto() -> None:
    """`S.A.U.:` e `Aluno:` no prompt, e não `bot:` nem `user:`.

    Não é preferência de texto: é o vocabulário do `CONTEXT.md`, e o modelo lê essas
    linhas como quem está falando. Um prompt que apresente "user:" faz o modelo
    responder na voz de quem escreveu o prompt em vez de na da identidade que ele
    representa.
    """
    assert Mensagem(papel="aluno", texto="qual o prazo?", em=0.0).como_linha() == (
        "Aluno: qual o prazo?"
    )
    assert Mensagem(papel="sau", texto="vence dia 12", em=0.0).como_linha() == (
        "S.A.U.: vence dia 12"
    )


def test_a_mensagem_e_congelada(registro: RegistroDeConversas) -> None:
    """`Mensagem` é imutável, e a fila é compartilhada por várias threads.

    A conversa é usada pela thread que segura o turno e pelas que esperam atrás. Uma
    `Mensagem` mutável no meio delas é uma escrita que ninguém pediu, e a conversa do
    Aluno mudando debaixo do turno é a forma mais difícil de depurar que existe.
    """
    mensagem = Mensagem(papel="aluno", texto="qual o prazo?", em=0.0)

    with pytest.raises(dataclasses.FrozenInstanceError):
        mensagem.texto = "outra coisa"  # type: ignore[misc]

    # E o registro entrega a mesma forma, e não um dicionário.
    _troca(registro, _ALUNA, "qual o prazo?", "vence dia 12")
    assert isinstance(registro.historico(_ALUNA)[0], Mensagem)
