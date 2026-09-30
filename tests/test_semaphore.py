"""Testes do semáforo de inferência, sau/inference/semaphore.py.

O que se prova aqui é o comportamento de um semáforo com fila: que o `k` é
respeitado sob concorrência real, que a fila é FIFO na ordem em que os turnos
chegaram, que a posição e a estimativa são ditas ao Aluno, e que acima do teto o
turno é recusado em vez de esperar em silêncio.

**Nada aqui usa `sleep`.** Toda coordenação é por `threading.Event`, e a espera pela
vaga é observada pelo lado de dentro — o callback `aviso` dispara enquanto o turno
está na fila e antes de esperar, e é por ele que o teste sabe que o turno entrou na
fila. Um `sleep` seria um teste que passa quase sempre e falha uma vez em vinte na
máquina carregada, e a ordem FIFO é exatamente o tipo de defeito que só se mostra
nessa corrida rara.

O relógio é injetado, pelo mesmo motivo do `agora` do `RegistroDeConversas`: a
estimativa é uma média de durações, e medir isso de verdade exigiria turnos de
segundos em uma suíte de teste. Com o relógio falso o teste afirma o número exato.
"""

from __future__ import annotations

import threading

import pytest

from sau.inference.semaphore import (
    K_PADRAO,
    SEGUNDOS_POR_TURNO_SEM_MEDICAO,
    TETO_PADRAO_DA_FILA,
    FilaCheiaError,
    PosicaoNaFila,
    SemaforoDeInferencia,
)

LIMITE_DE_ESPERA = 5.0
"""O teto de toda espera por `Event` da suíte.

Não é o tempo que o turno leva: é o tempo que o teste dá à thread para chegar em
algum ponto conhecido. Passado ele, o teste falha em vez de passar com uma espera
que virou espera infinita.
"""


class RelogioFalso:
    """O `time.monotonic` da máquina, sob controle do teste.

    Existe porque a estimativa de espera é uma média móvel de durações, e a
    única forma de afirmar o número sem esperar segundos de verdade é dar o
    relógio ao semáforo. É a mesma razão de `agora` no `RegistroDeConversas`.

    Não é thread-safe de propósito, e o uso é controlado: quem chama `avanca` é o
    teste, entre um turno e o outro, com o semáforo ocioso. Dentro de um turno o
    relógio só é lido.
    """

    def __init__(self, inicio: float = 1000.0) -> None:
        self.segundos = inicio

    def agora(self) -> float:
        return self.segundos

    def avanca(self, segundos: float) -> None:
        self.segundos += segundos


class VooDeTurno:
    """Um turno rodando em thread, parado no meio do semáforo até o teste soltar.

    A classe existe para que os testes de concorrência fiquem legíveis: sem ela,
    cada teste repetiria a mesma receita de `Thread` + `Event` + `join`, e a parte
    que importa — quem entrou, quem foi recusado, em que ordem — se perderia no
    ruído da máquina.

    Três eventos, e cada um marca um estado **conhecido**, que é o que torna a
    asserção determinística em vez de uma aposta de tempo:

    - `avisou`: o turno entrou na fila e o `aviso` foi chamado com a posição. O
      semáforo dispara o `aviso` enquanto o turno está na fila e antes de esperar,
      então este evento é a prova de que o turno **está na fila** — e, com o
      primeiro turno ainda segurando a vaga, a prova de que ele **não entrou**.
    - `dentro`: o turno passageou pela porta da fila e está ocupando uma vaga.
    - `solta`: o teste mandou o turno terminar.

    O `solta` é o que impede o teste de vazar thread: sem ele, um turno preso
    seguraria a vaga e o teste seguinte herdaria um semáforo ocupado.

    Os dois jeitos de o turno morrer de surpresa ficam em parâmetro, e a diferença
    entre eles é o que os testes de fila precisam distingui: `estoura` mata o turno
    **depois** de ocupar a vaga, e `aviso_levanta` mata o turno **antes**, enquanto
    ele só tem a senha. O primeiro devolve vaga; o segundo tem de devolver a senha.
    Um turno que morre no meio da fila e engole o número seria o pior defeito possível
    aqui — todo turno posterior travaria para sempre, sem log —, e nenhum teste que
    só olhasse para a vaga o pegaria.
    """

    def __init__(
        self,
        semaforo: SemaforoDeInferencia,
        avisados: list[PosicaoNaFila],
        estoura: bool = False,
        aviso_levanta: bool = False,
    ) -> None:
        self.avisou = threading.Event()
        self.dentro = threading.Event()
        self.solta = threading.Event()
        self.finalizado = threading.Event()
        self.recusado: BaseException | None = None

        def avisar(posicao: PosicaoNaFila) -> None:
            avisados.append(posicao)
            self.avisou.set()
            if aviso_levanta:
                # O `aviso` quebrando **depois** de o teste ser avisado: o `avisou`
                # primeiro, porque ele marca que o turno chegou à fila, e a exceção
                # depois. Na ordem inversa o teste não saberia dizer "entrou na fila e
                # morreu ao avisar" de "nunca chegou à fila", que são defeitos
                # diferentes com consertos diferentes.
                #
                # `RuntimeError` e não `httpx.InvalidURL` porque o semáforo não conhece
                # o Telegram: o que ele exige é que **alguma** exceção escape do
                # `aviso`, e o tipo não importa para o caminho que se quer exercitar.
                raise RuntimeError("o aviso de posição falhou")

        def rodar() -> None:
            try:
                with semaforo.na_fila(aviso=avisar):
                    self.dentro.set()
                    if estoura:
                        # Segura a vaga até o teste mandar, para que a fila exista de
                        # fato antes da exceção. Estourar assim que entrou não
                        # exercitaria nada de fila: o turno seguinte encontraria a
                        # vaga livre e entraria sem esperar, e o teste passaria sem
                        # ter passado pelo caminho que ele existe para testar.
                        self.solta.wait(LIMITE_DE_ESPERA)
                        raise RuntimeError("o grafo estourou")
                    self.solta.wait(LIMITE_DE_ESPERA)
            except BaseException as err:
                # `BaseException` e não `Exception` porque o nem-vindo aqui é
                # justamente o `FilaCheiaError` da recusa e a exceção do corpo, e
                # nenhum dos dois pode escapar da thread: quem chamou isto é outra
                # thread, e uma exceção que morre aqui morre sem ninguém ver.
                # Guardar e reexpor no `finalizado` é o que faz "este turno foi
                # recusado" ser uma afirmação do teste, e não um turno que
                # simplesmente não aconteceu e deixou o teste passar.
                self.recusado = err
            finally:
                self.finalizado.set()

        self.thread = threading.Thread(target=rodar, daemon=True)
        self.thread.start()

    def esperar_para_entrar_na_fila(self) -> None:
        assert self.avisou.wait(LIMITE_DE_ESPERA), "o turno não entrou na fila do semáforo"

    def esperar_para_ocupar_vaga(self) -> None:
        assert self.dentro.wait(LIMITE_DE_ESPERA), "o turno não chegou a ocupar uma vaga"

    def esperar_para_terminar(self) -> None:
        """Espera a thread acabar, para o turno que **não** chega a ocupar vaga.

        Serve para o turno recusado pelo teto: como a recusa vem antes de pegar
        senha, o `aviso` nunca é chamado para ele e `avisou` nunca é ligado.
        """
        assert self.finalizado.wait(LIMITE_DE_ESPERA), (
            "o turno não terminou: nem entrou na fila nem foi recusado"
        )
        self.thread.join(timeout=LIMITE_DE_ESPERA)
        assert not self.thread.is_alive(), "a thread do turno sobreviveu ao teste"

    def terminar(self) -> None:
        """Solta o turno e espera a thread terminar, sem vazar para o teste seguinte."""
        self.solta.set()
        assert self.finalizado.wait(LIMITE_DE_ESPERA), "o turno não terminou"
        self.thread.join(timeout=LIMITE_DE_ESPERA)
        assert not self.thread.is_alive(), "a thread do turno sobreviveu ao teste"

    def __enter__(self) -> VooDeTurno:
        return self

    def __exit__(self, *_erro: object) -> None:
        self.terminar()


# --- O k é respeitado, e a fila é FIFO na ordem de chegada ---


def test_o_semaphore_aceita_o_turno_sem_esperar_quando_a_vaga_esta_livre() -> None:
    """Vaga livre é entrada imediata, sem fila e sem aviso."""
    semaforo = SemaforoDeInferencia(k=2)
    avisados: list[PosicaoNaFila] = []

    with semaforo.na_fila(aviso=avisados.append) as posicao:
        assert posicao is None

    assert avisados == [], "um turno que não esperou não tem posição para anunciar"
    assert semaforo.vagas_livres == 2, "a vaga não voltou"


def test_o_k_e_respeitado_e_a_fila_e_fifo() -> None:
    """`k=2` limita a duas vagas e a ordem de serviço é a de chegada.

    Este é o teste que prova o núcleo do ADR-0001: o recurso escasso é a
    inferência, e o limite é `k`. Cinco turnos são lançados, os dois primeiros
    ocupam as duas vagas, e os três seguintes esperam. A afirmação de que o terceiro
    **não** entrou é feita pelo `avisou`: o semáforo só chama `aviso` para quem ficou
    na fila, e enquanto o primeiro turno segura a vaga isso é o mesmo que dizer que
    ele está esperando.

    A ordem FIFO é afirmada pela posição anunciada: os turnos entram nesta ordem e
    as posições saem 3, 4, 5. Um `threading.Semaphore` — que não é justo, e acorda
    quem o sistema operacional quiser — publicaria posições fora de ordem ou
    nenhuma, e este teste ficaria vermelho.
    """
    semaforo = SemaforoDeInferencia(k=2)
    avisados: list[PosicaoNaFila] = []

    # Os dois primeiros tomam as vagas. Um `with` aninhado na thread do teste
    # seria erro de indentação, então cada um vive na sua própria thread.
    dentro = [VooDeTurno(semaforo, avisados) for _ in range(2)]
    for voo in dentro:
        voo.esperar_para_ocupar_vaga()

    assert semaforo.vagas_livres == 0, "as duas vagas deveriam estar ocupadas"
    assert avisados == [], "ninguém deveria ter esperado com ainda duas vagas"

    # Os três seguintes ficam na fila, e nenhum deles entra no modelo.
    na_fila = [VooDeTurno(semaforo, avisados) for _ in range(3)]
    for voo in na_fila:
        voo.esperar_para_entrar_na_fila()

    assert [posicao.posicao for posicao in avisados] == [3, 4, 5]
    assert semaforo.vagas_livres == 0, "nenhum turno da fila deveria ter ocupado vaga"
    assert semaforo.turnos_esperando == 3
    assert all(voo.dentro.is_set() is False for voo in na_fila)

    # Solta as duas vagas: os três da fila entram, na ordem anunciada.
    for voo in dentro:
        voo.terminar()
    for voo in na_fila:
        voo.terminar()

    assert semaforo.vagas_livres == 2, "as vagas não voltaram depois dos cinco turnos"
    assert semaforo.turnos_esperando == 0


# --- A posição e a estimativa ---


def test_o_aviso_recebe_a_posicao_e_a_estimativa() -> None:
    """O `aviso` entrega a posição e uma estimativa em segundos.

    A estimativa antes de qualquer medição sai do piso declarado, multiplicado pelo
    número de voltas que a posição implica. Com `k=1` e o primeiro turno na vaga, o
    segundo tem uma volta na frente: `ceil(2/1) = 2` voltas de
    `SEGUNDOS_POR_TURNO_SEM_MEDICAO`.
    """
    semaforo = SemaforoDeInferencia(k=1)
    avisados: list[PosicaoNaFila] = []

    primeiro = VooDeTurno(semaforo, avisados)
    primeiro.esperar_para_ocupar_vaga()

    segundo = VooDeTurno(semaforo, avisados)
    segundo.esperar_para_entrar_na_fila()

    assert len(avisados) == 1
    posicao = avisados[0]
    assert posicao.posicao == 2
    assert posicao.espera_estimada == pytest.approx(2 * SEGUNDOS_POR_TURNO_SEM_MEDICAO)

    primeiro.terminar()
    segundo.terminar()


def test_a_estimativa_cresce_com_a_posicao() -> None:
    """Mais longe na fila, mais a espera estimada — e o crescimento é em voltas.

    Com `k=1` não há arredondamento: a posição 2 dá 2 voltas, a 3 dá 3. Com `k=2`
    a posição 3 também dá 2 voltas, porque duas vagas abrem de duas em duas, e é
    essa a conta honesta. A estimativa que cresce por turno é a que **não** mente
    sobre a fila que o Aluno está vendo.
    """
    semaforo = SemaforoDeInferencia(k=1)
    avisados: list[PosicaoNaFila] = []

    primeiro = VooDeTurno(semaforo, avisados)
    primeiro.esperar_para_ocupar_vaga()
    atrasados = [VooDeTurno(semaforo, avisados) for _ in range(3)]
    for voo in atrasados:
        voo.esperar_para_entrar_na_fila()

    posicoes = [p.posicao for p in avisados]
    esperas = [p.espera_estimada for p in avisados]
    assert posicoes == [2, 3, 4]
    # Com `k=1` a conta não tem arredondamento: a posição 2 são 2 voltas, a 3 são
    # 3, a 4 são 4. O piso declarado multiplicado por cada uma delas.
    assert esperas == pytest.approx(
        [v * SEGUNDOS_POR_TURNO_SEM_MEDICAO for v in (2, 3, 4)]
    ), f"a espera estimada não cresceu com a posição: {esperas}"

    primeiro.terminar()
    for voo in atrasados:
        voo.terminar()


def test_a_posicao_conta_a_fila_de_agora_e_nao_as_senhas_da_noite() -> None:
    """A posição é "quantos estão na frente agora", e não "quantos já passaram".

    Este teste existe porque a primeira versão do semáforo contava as senhas
    vitalícias, e o número ficava grande demais para ser verdade. Depois de um dia
    inteiro de atendimento, o primeiro Aluno da madrugada leria "posição 57" para
    uma fila de uma pessoa só — e o Aluno, que acredita mais no número do que em
    qualquer palavra de consolo, concluiria que teria de esperar horas.

    Aqui o mesmo semáforo já atendeu doze turnos, e o próximo Aluno, com uma
    pessoa na frente, continua lendo a posição 2 em vez de 14.
    """
    semaforo = SemaforoDeInferencia(k=1)
    avisados: list[PosicaoNaFila] = []

    for _ in range(12):
        with semaforo.na_fila():
            pass

    primeiro = VooDeTurno(semaforo, avisados)
    primeiro.esperar_para_ocupar_vaga()
    segundo = VooDeTurno(semaforo, avisados)
    segundo.esperar_para_entrar_na_fila()

    assert len(avisados) == 1
    assert avisados[0].posicao == 2, (
        f"a posição contou a noite inteira em vez da fila: {avisados[0].posicao}"
    )

    primeiro.terminar()
    segundo.terminar()


def test_a_media_mede_a_inferencia_e_nao_a_espera() -> None:
    """A média guarda quanto o turno **rodou**, e não quanto ele ficou esperando.

    Este teste existe porque a primeira versão do semáforo media do instante em que
    o turno **chegou** até o instante em que devolveu a vaga. A diferença parece
    pequena e não é: a espera é justamente o que a estimativa tenta prever, então
    guardar a espera dentro da média realimenta o número, e a estimativa cresce a
    noite inteira em vez de convergir para a duração da inferência.

    A conta é exata porque o relógio é falso, e ela é curta porque com `k=1` a
    espera do segundo turno **é** a duração do primeiro: ele espera enquanto o
    primeiro segura a vaga. O arranjo é, portanto:

    | momento | relógio | o que acontece |
    | --- | --- | --- |
    | o primeiro entra na vaga | 1000,0 | `inicio` do primeiro |
    | o segundo chega e não há vaga | 1000,0 | `aviso`, e ele espera |
    | o primeiro roda 100 s e devolve | 1100,0 | média passa a 100,0 |
    | o segundo entra na vaga | 1100,0 | `inicio` do segundo |
    | o segundo roda 10 s e devolve | 1110,0 | o que a média tem de guardar |

    A última linha é a prova. A inferência do segundo turno foram 10 s, e a média
    tem de ficar em `0,2 × 10 + 0,8 × 100 = 82`. No código quebrado ela valeria
    `0,2 × 110 + 0,8 × 100 = 102`, porque a espera de 100 s entraria na conta.

    A consequência em campo não é teórica. Com `k=2` e um pico de Alunos às duas
    da manhã, o Aluno do fim da fila leria "cerca de meio minuto" num momento em que
    a fila não tinha crescido — a fila não cresceu, a estimativa que a descreve que
    cresceu, e ela cresce mais a cada turno que espera, sem nada tendo mudado no
    serviço. É o defeito mais caro que este módulo podia ter, e ele não apareceria
    em nenhum teste que não usasse relógio injetado.
    """
    relogio = RelogioFalso()
    semaforo = SemaforoDeInferencia(k=1, relogio=relogio.agora)
    avisados: list[PosicaoNaFila] = []

    # O primeiro turno ocupa a vaga e segura. O segundo chega e não há vaga, então ele
    # entra na fila e o `aviso` avisa o teste de que chegou lá.
    primeiro = VooDeTurno(semaforo, avisados)
    primeiro.esperar_para_ocupar_vaga()
    segundo = VooDeTurno(semaforo, avisados)
    segundo.esperar_para_entrar_na_fila()
    assert semaforo.turnos_esperando == 1

    # Os 100 s do primeiro turno, que são também os 100 s de espera do segundo.
    relogio.avanca(100.0)
    primeiro.terminar()
    primeiro.esperar_para_terminar()

    assert semaforo.media_da_vaga == pytest.approx(100.0), (
        f"a vaga do primeiro turno não foi medida: {semaforo.media_da_vaga}"
    )

    # O segundo já entrou na vaga. Só agora o relógio dele começa a correr, e é o
    # teste que decide isso: a espera foi dos 100 s acima.
    segundo.esperar_para_ocupar_vaga()
    relogio.avanca(10.0)
    segundo.terminar()
    segundo.esperar_para_terminar()

    assert semaforo.media_da_vaga == pytest.approx(82.0), (
        f"a média guardou a espera junto com a inferência: {semaforo.media_da_vaga} "
        f"em vez de 82,0. Com o código quebrado sairia 102,0, e a diferença é "
        "exatamente a espera. A estimativa realimenta a si mesma assim"
    )


def test_a_estimativa_vem_das_vagas_medidas_e_nao_do_piso() -> None:
    """Depois da primeira vaga medida, a estimativa sai da média, não do piso.

    Este é o teste que separa "estimativa adaptativa" de "número decorativo". A
    primeira vaga dura 4 s de relógio falso; a segunda, 8 s. Depois disso a média
    móvel de `PESO_DA_MEDIA_MOVEL` vale `0.2 * 8 + 0.8 * 4 = 4.8`, e é esse
    número que multiplica as voltas do turno que entra atrás.

    Sem o `relogio` injetado este teste teria de esperar segundos de verdade, ou
    pior, passar por acaso com microssegundos de duração de vaga — que é
    exatamente o defeito que a guarda de duração zero em `_medir_vaga` existe para
    impedir.
    """
    relogio = RelogioFalso()
    semaforo = SemaforoDeInferencia(k=1, relogio=relogio.agora)

    with semaforo.na_fila():
        relogio.avanca(4.0)

    assert semaforo.media_da_vaga == pytest.approx(4.0)
    assert semaforo.media_da_vaga != SEGUNDOS_POR_TURNO_SEM_MEDICAO

    with semaforo.na_fila():
        relogio.avanca(8.0)

    # 0.2 * 8 + 0.8 * 4 = 4.8
    assert semaforo.media_da_vaga == pytest.approx(4.8)

    # Um turno atrás do próximo: com `k=1` a posição 2 são 2 voltas, e 2 × 4,8 s
    # saem da média, não do piso de 10 s. É a distinção que importa: com o piso a
    # espera seria 20 s, e o teste passaria se a média não estivesse sendo usada.
    avisados: list[PosicaoNaFila] = []
    primeiro = VooDeTurno(semaforo, avisados)
    primeiro.esperar_para_ocupar_vaga()
    segundo = VooDeTurno(semaforo, avisados)
    segundo.esperar_para_entrar_na_fila()

    assert len(avisados) == 1
    assert avisados[0].posicao == 2
    assert avisados[0].espera_estimada == pytest.approx(2 * 4.8)
    assert avisados[0].espera_estimada < 2 * SEGUNDOS_POR_TURNO_SEM_MEDICAO

    primeiro.terminar()
    segundo.terminar()


def test_a_media_ignora_vaga_de_duracao_zero() -> None:
    """Uma vaga instantânea não envenena a média da noite.

    Com o relógio de verdade, um turno de teste pode durar microssegundos. Se esse
    número entrasse na média, a estimativa do Aluno real de logo depois leria
    "cerca de 0 segundos" — e a média não se recuperaria sem que a noite
    recomeçasse. O `RelogioFalso` que não avança reproduz esse caso: a vaga tem
    duração zero, e a média precisa continuar `None`.
    """
    relogio = RelogioFalso()
    semaforo = SemaforoDeInferencia(k=1, relogio=relogio.agora)

    for _ in range(3):
        with semaforo.na_fila():
            pass  # duração zero: o relógio não andou

    assert semaforo.media_da_vaga is None, (
        "uma vaga de duração zero entrou na média e derrubou a estimativa da noite"
    )


# --- O teto recusa, e a recusa não come a fila ---


def test_acima_do_teto_o_turno_e_recusado() -> None:
    """Acima do teto, o turno levanta `FilaCheiaError` em vez de esperar.

    `teto=1` e `k=1`: o primeiro turno ocupa a vaga, o segundo espera, e o terceiro é
    recusado. A recusa é a válvula que o ADR-0001 pede para transformar a espera
    silenciosa em recusa educada.
    """
    semaforo = SemaforoDeInferencia(k=1, teto=1)
    avisados: list[PosicaoNaFila] = []

    primeiro = VooDeTurno(semaforo, avisados)
    primeiro.esperar_para_ocupar_vaga()
    segundo = VooDeTurno(semaforo, avisados)
    segundo.esperar_para_entrar_na_fila()

    assert semaforo.turnos_esperando == 1

    # O terceiro turno é recusado **antes** de pegar senha, então o `aviso` nunca
    # é chamado para ele: o que o prova é a thread ter terminado com a exceção
    # guardada, e não ter entrado na fila. Por isso a espera aqui é pelo
    # `finalizado`, e não pelo `avisou` como nos turnos que entraram de fato.
    recusado = VooDeTurno(semaforo, avisados)
    recusado.esperar_para_terminar()

    assert isinstance(recusado.recusado, FilaCheiaError), (
        f"o turno acima do teto deveria ter sido recusado, e veio "
        f"{recusado.recusado!r}"
    )
    assert not recusado.dentro.is_set(), "o turno recusado não pode ter ocupado vaga"
    assert len(avisados) == 1, "o turno recusado não tem posição para anunciar"
    assert semaforo.turnos_esperando == 1, "o recusado não pode ter entrado na fila"

    # E quem já estava na fila não paga por causa do recusado: ele entra assim que
    # a vaga volta. É o que a recusa promete ao `webhook` na frase que o Aluno lê —
    # "nada foi descartado".
    primeiro.terminar()
    segundo.esperar_para_ocupar_vaga()
    segundo.terminar()

    assert semaforo.turnos_esperando == 0


def test_o_turno_recusado_nao_entra_na_fila_e_nao_vaga() -> None:
    """A recusa acontece **antes** de o turno pegar senha, e é o que impede deadlock.

    Se o turno recusado consumisse um número de senha, ninguém viria servir aquele
    número e todos os que estão atrás esperariam para sempre. Este teste prova que
    a recusa não mexe na fila: depois que o segundo turno é recusado, o primeiro
    termina, e o segundo da fila entra normalmente.
    """
    semaforo = SemaforoDeInferencia(k=1, teto=1)
    avisados: list[PosicaoNaFila] = []

    primeiro = VooDeTurno(semaforo, avisados)
    primeiro.esperar_para_ocupar_vaga()
    segundo = VooDeTurno(semaforo, avisados)
    segundo.esperar_para_entrar_na_fila()

    with pytest.raises(FilaCheiaError):
        with semaforo.na_fila():
            pass  # pragma: no cover - o corpo nunca roda

    assert semaforo.turnos_esperando == 1, "o recusado não pode ter entrado na fila"

    primeiro.terminar()
    segundo.esperar_para_ocupar_vaga()
    segundo.terminar()

    assert semaforo.turnos_esperando == 0
    assert semaforo.vagas_livres == 1


def test_o_aviso_diz_o_motivo_da_recusa_com_o_teto() -> None:
    """A `FilaCheiaError` diz quantos esperam e qual é o teto, para o log do operador.

    O Aluno não recebe este texto — ele recebe a recusa educada do `webhook`. A
    exceção é para quem opera o serviço, e um `RuntimeError` sem número é um log
    que obriga a abrir o código para entender o que aconteceu.
    """
    semaforo = SemaforoDeInferencia(k=1, teto=1)
    avisados: list[PosicaoNaFila] = []

    primeiro = VooDeTurno(semaforo, avisados)
    primeiro.esperar_para_ocupar_vaga()
    segundo = VooDeTurno(semaforo, avisados)
    segundo.esperar_para_entrar_na_fila()

    with pytest.raises(FilaCheiaError) as exc:
        with semaforo.na_fila():
            pass  # pragma: no cover - o corpo nunca roda

    mensagem = str(exc.value)
    assert "1 turnos esperando" in mensagem
    assert "teto de 1" in mensagem

    primeiro.terminar()
    segundo.terminar()


# --- A vaga volta, mesmo com exceção ---


def test_a_vaga_volta_quando_o_turno_falha_no_turno() -> None:
    """Levantar exceção no corpo não queima a vaga, e a fila continua andando.

    O grafo pode estourar — um `KeyError` de estado, um cliente trocado. Se a vaga
    não voltasse, o Aluno seguinte esperaria por um turno que já morreu, e a única
    forma de recuperar seria reiniciar o serviço.
    """
    semaforo = SemaforoDeInferencia(k=1)
    avisados: list[PosicaoNaFila] = []

    estourando = VooDeTurno(semaforo, avisados, estoura=True)
    estourando.esperar_para_ocupar_vaga()
    estourando.terminar()

    assert isinstance(estourando.recusado, RuntimeError)
    assert semaforo.vagas_livres == 1, "a vaga não voltou depois da exceção"

    # E o próximo turno passa sem esperar, provando que a fila não ficou corrompida.
    with semaforo.na_fila(aviso=avisados.append) as posicao:
        assert posicao is None


def test_a_senha_avanca_para_o_turno_que_estoura() -> None:
    """O turno que estoura não engole a senha de quem está atrás.

    A distinção com o teste anterior é o que fecha o caso: não basta a vaga voltar,
    a **senha** também tem de avançar, ou quem está atrás fica esperando um número
    que ninguém virá servir. O segundo turno precisa entrar logo depois da exceção do
    primeiro.
    """
    semaforo = SemaforoDeInferencia(k=1)
    avisados: list[PosicaoNaFila] = []

    estourando = VooDeTurno(semaforo, avisados, estoura=True)
    estourando.esperar_para_ocupar_vaga()
    atrasado = VooDeTurno(semaforo, avisados)
    atrasado.esperar_para_entrar_na_fila()

    estourando.terminar()
    atrasado.esperar_para_ocupar_vaga()
    atrasado.terminar()

    assert isinstance(estourando.recusado, RuntimeError)
    assert semaforo.vagas_livres == 1


# --- Ninguém consome uma senha sem servi-la ---


class CondicaoQueInterrompe(threading.Condition):
    """A condição do semáforo, em que o `wait` morre em vez de esperar.

    Existe para exercitar o caminho que nenhum evento do teste alcança: o turno que
    **já pegou a senha** e ainda não conseguiu vaga, e que morre enquanto dorme. É o
    `KeyboardInterrupt` que o docstring de `na_fila` cita — em produção ele é raríssimo,
    porque o sinal vai para a thread principal —, e aqui ele é determinístico, que é o
    que um teste de concorrência precisa ser.

    Subclassar a condição de verdade, e não trocá-la por um objeto falso, mantém o
    `with`, o `notify_all` e a trava funcionando: só o `wait`, que é o ponto, morre.
    """

    def wait(self, timeout: float | None = None) -> bool:
        raise KeyboardInterrupt("o turno foi interrompido enquanto esperava")


def test_o_aviso_que_levanta_nao_prende_o_turno_que_esta_atras() -> None:
    """Um `aviso` que levanta não pode prender ninguém, e este é o teste da regressão.

    O defeito que este teste fecha estava no caminho do `aviso`: ele rodava fora do
    `try`, então a exceção saía do gerador sem passar pelo `finally`. A senha já tinha
    sido consumida e ninguém viria servi-la — `_senha_servindo` ficaria apontando para
    uma senha de um turno morto —, e **todo turno posterior esperaria para sempre**,
    sem log e sem recusa. Na tela: o Aluno manda a mensagem, o acuse sai, e nada mais
    acontece, para sempre. O "backpressure comunicado, não escondido" do ADR-0001
    virando o oposto.

    O `aviso` quebrado é alcançável de verdade: no `webhook` ele é um `sendMessage`, e
    o `enviar_mensagem` só captura `httpx.HTTPError`. Um `TELEGRAM_API_BASE`
    malformado levanta `httpx.InvalidURL`, que **não** é subclasse de `HTTPError`, e
    qualquer outra falha de I/O também sai.

    A prova é o turno honesto que chega atrás, e não a exceção ter saído: o terceiro
    turno é um Aluno de verdade esperando a vez dele. Com o defeito, ele trava, e o
    `esperar_para_ocupar_vaga` falha em `LIMITE_DE_ESPERA` — o teste fica vermelho em
    segundos em vez de travar junto com o serviço.
    """
    semaforo = SemaforoDeInferencia(k=1)
    avisados: list[PosicaoNaFila] = []

    # O primeiro turno ocupa a única vaga e segura, que é o que faz existir uma fila.
    primeiro = VooDeTurno(semaforo, avisados)
    primeiro.esperar_para_ocupar_vaga()

    # O segundo entra na fila e morre no aviso, antes de ocupar vaga.
    quebrado = VooDeTurno(semaforo, avisados, aviso_levanta=True)
    quebrado.esperar_para_entrar_na_fila()
    quebrado.esperar_para_terminar()
    assert isinstance(quebrado.recusado, RuntimeError), (
        f"o aviso deveria ter levantado, e veio {quebrado.recusado!r}"
    )

    # O terceiro é o Aluno honesto que chegou depois. Com o defeito, ele espera para
    # sempre: a senha dele nunca é a vez de ninguém.
    atrasado = VooDeTurno(semaforo, avisados)
    atrasado.esperar_para_entrar_na_fila()

    primeiro.terminar()
    atrasado.esperar_para_ocupar_vaga()
    atrasado.terminar()

    assert semaforo.turnos_esperando == 0
    assert semaforo.vagas_livres == 1


def test_o_aviso_que_levanta_nao_pula_o_turno_que_esta_antes() -> None:
    """Morrer na fila não pode pular quem está **antes** e ainda vivo.

    Este é o defeito mais difícil de ver, e ele só aparece quando o turno que morre
    **não** é o da vez. A ordem dos turnos na fila é a ordem das senhas, mas a ordem em
    que cada um *termina o seu aviso* é outra: o turno da senha 2 pode acabar o `aviso`
    antes do turno da senha 1, que é mais lento. É essa assimetria que desarma a
    correção ingênua.

    A correção ingênua é somar um: "a senha da vez era a minha, então a seguinte já é
    a próxima". Com a senha 2 morta e a 1 viva e esperando, a seguinte seria a 3 — e o
    turno da senha 1 esperaria para sempre um número que ninguém virá servir. O serviço
    inteiro trava com a fila cheia de gente viva, sem log, sem recusa e sem resposta,
    que é o pior defeito possível num serviço cuja promessa é a de responder.

    O arranjo do teste produz a assimetria de propósito: `atrasado` entra na fila e o
    aviso dele **passa**; só depois `quebrado` chega e morre no aviso dele. Com o
    defeito, `atrasado.esperar_para_ocupar_vaga()` falha em `LIMITE_DE_ESPERA` — o
    teste fica vermelho em segundos em vez de travar junto com o serviço.
    """
    semaforo = SemaforoDeInferencia(k=1)
    avisados: list[PosicaoNaFila] = []

    primeiro = VooDeTurno(semaforo, avisados)
    primeiro.esperar_para_ocupar_vaga()

    # Senha 1: fica na fila e sobrevive. É o turno que o defeito prende.
    atrasado = VooDeTurno(semaforo, avisados)
    atrasado.esperar_para_entrar_na_fila()

    # Senha 2: entra na fila depois e morre no aviso. A fila era [1] e continua [1]:
    # a senha 2 não pode virar a senha da vez.
    quebrado = VooDeTurno(semaforo, avisados, aviso_levanta=True)
    quebrado.esperar_para_entrar_na_fila()
    quebrado.esperar_para_terminar()
    assert isinstance(quebrado.recusado, RuntimeError)

    assert semaforo.turnos_esperando == 1, (
        f"a fila deveria ter só o turno que continua vivo: "
        f"{semaforo.turnos_esperando}"
    )

    primeiro.terminar()
    atrasado.esperar_para_ocupar_vaga()
    atrasado.terminar()

    assert semaforo.turnos_esperando == 0
    assert semaforo.vagas_livres == 1


def test_o_turno_que_morre_no_aviso_sai_da_conta_de_quem_espera() -> None:
    """`_esperando` volta ao valor certo, e o teto volta a valer para quem chegou.

    A segunda metade do mesmo defeito, e ela é a que o Aluno sente. Com o vazamento, o
    `_esperando` do turno morto continuava contando: o teto passava a recusar turnos
    que não estavam esperando por nada, com a mensagem de "a fila está cheia" para um
    Aluno que era o único na fila. O sintoma é pior que o do travamento, porque
    **responde**: o Aluno recebe uma recusa que não é verdade, e o operador recebe um
    `warning` de fila cheia com a fila vazia.

    O `teto=1` é o que torna isso observável. Com o `_esperando` vazado em 1, o turno
    que chega atrás bate no teto e é recusado; sem o vazamento ele entra na fila como
    qualquer outro, e é o que este teste afirma.
    """
    semaforo = SemaforoDeInferencia(k=1, teto=1)
    avisados: list[PosicaoNaFila] = []

    primeiro = VooDeTurno(semaforo, avisados)
    primeiro.esperar_para_ocupar_vaga()
    quebrado = VooDeTurno(semaforo, avisados, aviso_levanta=True)
    quebrado.esperar_para_entrar_na_fila()
    quebrado.esperar_para_terminar()

    assert semaforo.turnos_esperando == 0, (
        f"o turno que morreu no aviso continua na contagem de quem espera: "
        f"{semaforo.turnos_esperando}. O teto vai recusar Aluno com a fila vazia"
    )

    # Com o vazamento, este turno é recusado na porta pelo teto, e o `avisou` nunca
    # liga: a espera abaixo é, ao mesmo tempo, a prova de que ele não foi recusado.
    atrasado = VooDeTurno(semaforo, avisados)
    atrasado.esperar_para_entrar_na_fila()

    primeiro.terminar()
    atrasado.esperar_para_ocupar_vaga()
    atrasado.terminar()

    assert semaforo.turnos_esperando == 0


def test_o_aviso_que_levanta_nao_devolve_vaga_que_nunca_foi_tomada() -> None:
    """Quem não tomou vaga não devolve vaga — senão o semáforo cresce acima do `k`.

    O caminho do `finally` é o mesmo para todo mundo, e é por isso que ele precisa da
    `segurando_vaga`: uma devolução incondicional devolveria uma vaga que ninguém
    tomou. Com `k=1` isso significa dois turnos no modelo ao mesmo tempo, que é
    exatamente o defeito que este módulo existe para impedir — e o sintomo seria o
    modelo cair para CPU sem que nada tivesse mudado no serviço.

    Com `vagas_livres` inflado, o `k` deixa de valer para todos os turnos seguintes,
    então o teste afirma o número logo depois da morte do turno quebrado, com o
    primeiro turno ainda segurando a vaga.
    """
    semaforo = SemaforoDeInferencia(k=1)
    avisados: list[PosicaoNaFila] = []

    primeiro = VooDeTurno(semaforo, avisados)
    primeiro.esperar_para_ocupar_vaga()
    quebrado = VooDeTurno(semaforo, avisados, aviso_levanta=True)
    quebrado.esperar_para_entrar_na_fila()
    quebrado.esperar_para_terminar()

    assert semaforo.vagas_livres == 0, (
        f"o turno que morreu antes de entrar devolveu uma vaga que nunca tomou: "
        f"vagas_livres={semaforo.vagas_livres} com k=1 e um turno dentro"
    )

    primeiro.terminar()
    assert semaforo.vagas_livres == 1


def test_o_turno_interrompido_na_espera_devolve_a_senha(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Morrer **dentro** do `wait` libera a fila do mesmo jeito.

    O caminho do `aviso` é o alcançável; este é o que o docstring de `na_fila` cita e
    que ninguém exercita. A diferença é que aqui o turno já está dormindo com a
    senha na mão, e a interrupção vem de dentro do `wait` — por isso a condição
    trocada: um `Event` do teste não consegue matar uma thread que está dentro de um
    `Condition.wait` de verdade.

    As duas contas importam aqui. A senha volta, senão o próximo turno espera para
    sempre; e a vaga **não** volta, porque ele nunca tomou nenhuma.
    """
    semaforo = SemaforoDeInferencia(k=1)
    avisados: list[PosicaoNaFila] = []

    primeiro = VooDeTurno(semaforo, avisados)
    primeiro.esperar_para_ocupar_vaga()

    # A condição de verdade fica guardada para o turno honesto voltar a usar: só o
    # turno interrompido deve morrer no `wait`.
    condicao_de_verdade = semaforo._condicao
    monkeypatch.setattr(semaforo, "_condicao", CondicaoQueInterrompe())

    interrompido = VooDeTurno(semaforo, avisados)
    interrompido.esperar_para_entrar_na_fila()
    interrompido.esperar_para_terminar()

    assert isinstance(interrompido.recusado, KeyboardInterrupt), (
        f"o turno deveria ter sido interrompido no wait, e veio "
        f"{interrompido.recusado!r}"
    )
    assert semaforo.turnos_esperando == 0, "o turno interrompido ficou esperando para sempre"
    assert semaforo.vagas_livres == 0, (
        f"o turno interrompido devolveu vaga que nunca tomou: "
        f"vagas_livres={semaforo.vagas_livres} com k=1 e um turno dentro"
    )

    monkeypatch.setattr(semaforo, "_condicao", condicao_de_verdade)

    atrasado = VooDeTurno(semaforo, avisados)
    atrasado.esperar_para_entrar_na_fila()
    primeiro.terminar()
    atrasado.esperar_para_ocupar_vaga()
    atrasado.terminar()

    assert semaforo.vagas_livres == 1
    assert semaforo.turnos_esperando == 0


# --- Construção ---


def test_o_semaphore_recusa_k_e_teto_nao_positivos() -> None:
    """`k=0` ou `teto=0` é configuração inválida, e a recusa é na construção.

    Com `k=0` nenhuma vaga existe e todo turno ficaria esperando para sempre; com
    `teto=0` o primeiro turno fora de vaga seria recusado antes de a fila existir.
    As duas são o tipo de erro que o `.env` não denuncia, então a classe falha na
    hora de ser montada.
    """
    with pytest.raises(ValueError, match="k do semáforo"):
        SemaforoDeInferencia(k=0)

    with pytest.raises(ValueError, match="teto da fila"):
        SemaforoDeInferencia(k=1, teto=0)

    with pytest.raises(ValueError, match="k do semáforo"):
        SemaforoDeInferencia(k=-1)


def test_os_padroes_sao_os_declarados() -> None:
    """`K_PADRAO=2` e `TETO_PADRAO_DA_FILA=10` são os números que o ADR-0001 descreve.

    O `2` é o teto de uma ou duas gerações simultâneas que a VRAM aceita na
    prática; o `10` é arbitrário e declarado como tal, no mesmo espírito do
    `TETO_DE_TURNOS_ESPERANDO` da #9. O teste existe porque o `k` é o número que a
    issue exige medir na máquina alvo, e um default que muda sem ninguém perceber
    mudaria o comportamento do serviço em silêncio.
    """
    assert K_PADRAO == 2
    assert TETO_PADRAO_DA_FILA == 10
    assert SEGUNDOS_POR_TURNO_SEM_MEDICAO == 10.0

    semaforo = SemaforoDeInferencia()
    assert semaforo.k == 2
    assert semaforo.teto == 10
    assert semaforo.vagas_livres == 2
