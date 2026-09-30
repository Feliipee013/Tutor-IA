"""Fila e semáforo em frente à inferência: a parte do ADR-0001 que decide quantos
turnos entram no modelo ao mesmo tempo.

Desde a #8 o `webhook` abre uma thread por turno, e a #9 deu a cada Aluno a fila
FIFO da própria conversa. O que ainda não existia era o **limite**: a thread
existe para que o Aluno não espere o modelo dentro do request, e nada além disso.
O recurso escasso do S.A.U. é um só — a chamada ao Ollama — e a VRAM é o que o
limita. Este módulo é o semáforo que o ADR-0001 pede na frente dessa chamada, com
fila de espera, teto e a posição contada para o Aluno.

Cinco decisões estão no código, e as duas primeiras são o que faz a posição
comunicada ser verdade em vez de enfeite:

- **A fila é de senha, e não um `threading.Semaphore`.** O `Semaphore` da stdlib
  não é justo: quem chega por último pode passar à frente de quem já estava
  esperando, porque a ordem de despertar é a ordem do sistema operacional. Com
  isso, o Aluno que lê "sua vez é a 3ª" pode ser atendido antes de quem leu "sua
  vez é a 2ª", e a mensagem deixa de descrever a fila que existe. É o mesmo
  argumento que a #9 usou para `Conversa.em_ordem()` e pelo mesmo motivo: uma
  fila de senha dá a ordem, e um `Condition` dá o despertar sem polling.
- **A posição contada é entre Alunos, e não entre turnos.** O semáforo é adquirido
  **dentro** de `conversa.em_ordem()`, e não fora. Adquirir fora seguraria uma
  vaga enquanto o turno espera a vez da *própria* conversa, e dois turnos do mesmo
  Aluno poderiam estar na vaga ao mesmo tempo. Dentro, "um Aluno nunca tem dois
  turnos processados ao mesmo tempo" é estrutural, e a posição contada é posição
  entre Alunos — que é o que o Aluno entende quando lê "sua vez é a 3ª". Por
  consequência, a fila do semáforo tem no máximo uma entrada por conversa.
- **A estimativa é medida, e não declarada.** Ela é a média móvel exponencial da
  duração observada das vagas, vezes o número de voltas que a posição implica. O
  que a issue pede medido na máquina alvo é o `k`, não a estimativa: a estimativa é
  adaptativa por natureza, e o piso declarado cobre o turno que chega antes da
  primeira medição.
- **Quem decide o texto é quem chama.** `na_fila` entrega uma `PosicaoNaFila` e
  quem chama decide o que escrever; este módulo não conhece o Telegram, e é o
  `webhook` que tem o `chat_id`. A única coisa que o semáforo fala é o que ele
  sabe medir.
- **O teto recusa, a conversa só avisa.** `TETO_DE_TURNOS_ESPERANDO` da #9 é alarme
  e não recusa nada; este é a válvula, e os dois coexistem de propósito — um é
  sensor, o outro é escape.

Sem deadlock, por construção: a ordem dos dois travamentos é sempre
conversa → semáforo, e a vaga volta no `finally` do contexto, mesmo quando o corpo
levanta exceção.
"""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass

K_PADRAO = 2
"""Quantos turnos entram no modelo ao mesmo tempo, por padrão.

Dois é o teto que o ADR-0001 descreve para a prática — "na prática aceita uma ou
duas gerações simultâneas porque a VRAM limita qualquer paralelismo maior" — e é o
que a placa de 4 GB do ADR-0002 comporta sem o modelo cair para CPU.

O número é **medido** na máquina alvo e não assumido, que é o que o ADR-0001 exige
e o primeiro critério da issue repete. A medição ainda não aconteceu: o campo `k`
de `docs/fila-e-semaforo.md` está em branco, e o procedimento para preenchê-lo
está no mesmo documento. Dois é o ponto de partida declarado, não o número
verificado — e é por isso que `INFERENCIA_K` existe.
"""

TETO_PADRAO_DA_FILA = 10
"""Quantos turnos podem ficar esperando uma vaga antes de o próximo ser recusado.

O teto existe porque a espera silenciosa é o defeito que o ADR-0001 nomeia: um
Aluno às duas da manhã esperando sem saber o que está acontecendo "destrói a
promessa do produto". Com teto, o turno que passa da conta é **recusado com
educação** — o que é uma resposta, e resposta é o oposto de silêncio.

Dez é arbitrário e declarado como tal, no mesmo espírito do
`TETO_DE_TURNOS_ESPERANDO`: na escala de turnos de poucos segundos medidos em
`docs/tempo-primeira-resposta.md`, é a diferença entre "você está na fila" e "volta
mais tarde".

O teto conta **a fila de espera**, e não quem está no modelo: quem já está
atendendo não está esperando por ninguém, e contá-lo faria o teto estourar com um
Aluno só mandando mensagem.
"""

SEGUNDOS_POR_TURNO_SEM_MEDICAO = 10.0
"""O piso da estimativa, usado enquanto nenhuma vaga foi medida.

Dez segundos é o caso frio medido na máquina do ADR-0002, arredondado para cima:
`docs/tempo-primeira-resposta.md` registra 4,9 s para um turno de prefixo frio, e
um turno que entra na fila pode ainda pagar a carga do modelo se ele descarregou.
O piso é declarado e não medido desta noite — o que entra na média é a primeira
vaga que sair, e é isso que torna a estimativa adaptativa em vez de fixa.

**Uma vaga de duração zero não entra na média**, e a guarda é o que faz o piso
continuar valendo. Com o relógio de verdade, uma vaga de teste dura microssegundos
e envenenaria a estimativa da noite inteira com um zero; com o relógio falso do
teste, a ausência de medição continua sendo ausência de medição.
"""

PESO_DA_MEDIA_MOVEL = 0.2
"""Quanto da última vaga observada entra na média da estimativa.

Um quinto é o meio-termo entre duas propriedades que se brigam. A média móvel
responde à noite de hoje, que é o que o Aluno da madrugada espera; e o `0,2` impede
que **um** turno estranho — a carga do modelo que ainda não acabou, uma geração
que travou, outra coisa rodando na máquina — mande na estimativa do resto da
noite. Com peso `1,0` a estimativa seria o último turno e com peso `0` seria a
média da noite inteira, que não responde ao que está acontecendo agora.
"""


@dataclass(frozen=True)
class PosicaoNaFila:
    """Onde o turno está na fila e quanto tempo ele espera.

    Congelada pelo mesmo motivo da `Mensagem` da #9: o objeto é entregue a quem
    chamou, atravessa a espera e volta para o log, e uma posição que muda sozinha
    no meio disso é um número que ninguém consegue ler duas vezes igual.
    """

    posicao: int
    """Quantos turnos começam antes deste. Um é a vez dele; dois, há um na frente."""

    espera_estimada: float
    """A espera, em segundos de ponto flutuante.

    Flutuante porque vem da média, e arredondado para cima em **voltas** e não em
    segundos: a granulação honesta é o turno, e quem escreve a frase para o Aluno
    é quem chamou — a formatação de "cerca de 2 minutos" mora no `webhook`.
    """


class FilaCheiaError(RuntimeError):
    """A fila de espera passou do teto e o turno não entrou.

    `RuntimeError` e não `ValueError` porque a configuração é válida, o `k` é
    válido e o teto é válido: o que houve é o serviço ter mais Alunos na porta do
    que ele atende de uma vez, e isso é condição de operação, não erro de escrita
    de configuração. Quem levanta é o semáforo; quem transforma em frase para o
    Aluno é o `webhook`, porque só ele sabe quem é o Aluno.
    """


class SemaforoDeInferencia:
    """O limite de `k` vagas para o modelo, com fila FIFO e teto.

    O uso inteiro é o de um context manager:

    ```python
    with semaforo.na_fila(aviso=avisar_o_aluno) as posicao:
        entrega = executar_turno(cliente, texto, historico)
    ```

    `na_fila` entrega `None` quando o turno entrou sem esperar e uma
    `PosicaoNaFila` quando ficou atrás de alguém. No segundo caso o `aviso` já foi
    chamado com ela, uma vez só, antes de esperar. A vaga volta no `finally` mesmo
    quando o corpo levanta — sem isso, um turno que estourou no grafo queimaria uma
    vaga pelo resto da madrugada, e o Aluno seguinte esperaria por um turno que já
    morreu.

    O semáforo é adquirido **dentro** de `conversa.em_ordem()`, e é o módulo do
    `webhook` que garante isso. A ordem dos travamentos é sempre
    conversa → semáforo, e nenhum caminho os inverte.

    `relogio` é injetável pelo mesmo motivo do `agora` do `RegistroDeConversas`:
    a estimativa precisa ser testada sem `sleep`. O padrão é `time.monotonic` e não
    `time.time` porque o monotônico não anda para trás quando o relógio do sistema
    é corrigido — um turno que atravessasse uma correção mediria um tempo negativo
    e envenenaria a média da noite.
    """

    def __init__(
        self,
        k: int = K_PADRAO,
        teto: int = TETO_PADRAO_DA_FILA,
        relogio: Callable[[], float] | None = None,
    ) -> None:
        if k < 1:
            raise ValueError(
                f"Valor inválido para k do semáforo: {k}. Esperado inteiro positivo: "
                "com zero nenhuma vaga existe e todo turno ficaria esperando para "
                "sempre, sem nenhum sinal de que isso acontece."
            )
        if teto < 1:
            raise ValueError(
                f"Valor inválido para o teto da fila do semáforo: {teto}. Esperado "
                "inteiro positivo: com zero o primeiro turno fora de vaga seria "
                "recusado antes de a fila existir."
            )
        self.k = k
        self.teto = teto
        self._relogio = relogio or time.monotonic
        self._condicao = threading.Condition()
        self._vagas_livres = k
        self._esperando = 0
        self._proxima_senha = 0
        self._senha_servindo = 0
        """A menor senha que ainda não entrou no modelo.

        Avança na **entrada** de quem a tinha, e não na devolução da vaga: é essa a
        diferença entre respeitar `k` e atender um Aluno por vez. Todo mundo com
        senha acima desta está na fila, e todo mundo com senha abaixo já entrou,
        ocupando uma vaga ou não.
        """
        self._media_da_vaga: float | None = None
        """A média móvel da duração da vaga, e `None` enquanto nada foi medido.

        Nenhuma medição é o estado inicial, e é por isso que a estimativa tem piso:
        começar em zero faria o primeiro Aluno da noite ler "sua vez é a 3ª, cerca
        de 0 segundos", que é pior do que não dizer nada.
        """

    @property
    def vagas_livres(self) -> int:
        """Quantas vagas estão livres agora.

        Existe para o operador e para o teste olharem o estado sem inferir de
        threads. Não é a fila: quem está esperando **não** tem vaga, e por isso o
        nome é de vaga e não de lugar.
        """
        with self._condicao:
            return self._vagas_livres

    @property
    def turnos_esperando(self) -> int:
        """Quantos turnos estão na fila esperando uma vaga.

        É o número que o teto compara e o que o log do operador usa para dizer por
        que o Aluno está esperando. Não conta quem já está no modelo.
        """
        with self._condicao:
            return self._esperando

    @property
    def media_da_vaga(self) -> float | None:
        """A média móvel da vaga, ou `None` enquanto nenhuma vaga foi medida."""
        with self._condicao:
            return self._media_da_vaga

    @contextmanager
    def na_fila(
        self, aviso: Callable[[PosicaoNaFila], None] | None = None
    ) -> Iterator[PosicaoNaFila | None]:
        """Toma uma vaga, ou espera na fila até que uma apareça.

        Devolve `None` quando entrou sem esperar e uma `PosicaoNaFila` quando ficou
        atrás de alguém. O `aviso` — quando vem — é chamado com a posição **uma vez
        só**, enquanto o turno está na fila e antes de esperar. Quem não passa
        `aviso` tem o mesmo comportamento, só que ninguém é avisado: o parâmetro
        é opcional porque nem todo chamador tem Aluno para avisar.

        A espera tem duas condições, e as duas são a mesma fila:

        - **a senha** diz a ordem. Um turno que ainda não é o da vez não toma vaga
          mesmo havendo vaga livre, e é isso que sustenta a ordem que o `aviso`
          acabou de anunciar;
        - **a vaga** diz se cabe. Tendo a vez, o turno espera até que uma vaga
          apareça.

        Nenhuma delas sozinha serve: sem a senha, a posição comunicada seria
        mentira; sem a vaga, o `k` não valeria nada.

        A senha avança **ao entrar**, e não ao sair, e essa é a diferença entre um
        semáforo com `k` vagas e um semáforo com uma vaga só. Se a senha só
        avançasse na devolução, o turno de senha 1 esperaria o turno de senha 0
        **terminar** antes de entrar — e com `k=2` o serviço atenderia um Aluno por
        vez, que é o oposto do que o `k` promete. Avançando na entrada, o turno de
        senha 1 entra assim que aparece vaga, e o `k` vale.

        A recusa vem **antes** da senha, e essa ordem é o que impede deadlock. Um
        turno recusado não consome número de senha — se consumisse, ninguém viria
        servir aquele número e todos os que estão atrás esperariam para sempre.

        Entre takers de vaga não há deadlock: a senha avança sozinha, na entrada de
        quem a tinha, e toda devolução notifica todo mundo. A trava do `webhook` vem
        antes desta e é sempre a mesma — `conversa.em_ordem()` —, então a ordem dos
        dois travamentos é sempre conversa e depois semáforo, e nenhum caminho a
        inverte.
        """
        with self._condicao:
            tem_vaga = self._vagas_livres > 0
            if not tem_vaga and self._esperando >= self.teto:
                raise FilaCheiaError(
                    f"fila do semáforo cheia: {self._esperando} turnos esperando, acima "
                    f"do teto de {self.teto}. Este turno não entrou e nada foi "
                    "descartado: quem já estava na fila segue esperando."
                )
            posicao: PosicaoNaFila | None = None
            if not tem_vaga:
                # Quem está na frente do turno que acabou de chegar são (a) todos que
                # ocupam vaga — e, como não há vaga livre, são exatamente os `k` — e
                # (b) todos os que já estavam na fila. Somados a ele mesmo, dão a
                # posição que o Aluno lê.
                #
                # A conta é de **quem está esperando agora**, e não de quantas senhas o
                # serviço entregou a noite inteira. A diferença aparece às duas da
                # manhã: com um contador vitalício, o primeiro Aluno da madrugada leria
                # "posição 57" para uma fila de uma pessoa só, e o número — que é a
                # coisa que o Aluno mais acredita — estaria mentindo sobre a fila que
                # ele está de fato vendo.
                #
                # `_esperando` ainda não conta este turno, e é por isso que o `+ 1` é
                # dele: a posição 1 é a vez dele, e a contagem de quem está na frente
                # entra antes.
                posicao = PosicaoNaFila(
                    posicao=self.k + self._esperando + 1,
                    espera_estimada=self._estimar_espera(self.k + self._esperando + 1),
                )
                self._esperando += 1
            minha_senha = self._proxima_senha
            self._proxima_senha += 1

        if posicao is not None and aviso is not None:
            # Fora da tranca, e por dois motivos. O aviso é I/O — no `webhook` é um
            # `sendMessage` ao Telegram, com teto de 5 s — e segurar a condição
            # durante ele pararia a fila inteira. E nada no aviso reentra no
            # semáforo, então a trava cruzada que seria o problema de verdade não
            # existe; o teste da posição usa este mesmo ponto para acordar o teste.
            aviso(posicao)

        # Antes do `try`, e `None` de propósito. A exceção dentro do `wait` — um
        # `KeyboardInterrupt`, que morre sem devolução nenhuma — não pode deixar
        # `inicio` sem valor para o `finally` ler. `None` é o que distingue "a vaga
        # foi tomada e a inferência está cronometrada" de "o turno nem chegou a
        # entrar": no segundo caso não há duração para medir, porque nada rodou.
        inicio: float | None = None
        try:
            with self._condicao:
                while self._senha_servindo != minha_senha or self._vagas_livres == 0:
                    self._condicao.wait()
                self._vagas_livres -= 1
                # A senha avança na **entrada**, e é isso que faz o `k` valer: o
                # próximo da fila deixa de estar atrás deste e passa a disputar a
                # vaga que aparecer. Se ela só avançasse na devolução, o `k` viraria
                # 1 sem ninguém perceber.
                self._senha_servindo = minha_senha + 1
                if posicao is not None:
                    # Saiu da fila ao entrar no modelo: a partir de agora ele não
                    # está mais esperando por ninguém, e é isso que faz o teto valer
                    # para a fila e não para o número de Alunos atendidos.
                    self._esperando -= 1
                # O relógio da vaga começa **aqui**, quando a vaga foi tomada, e não
                # quando o turno chegou. A diferença é toda a estimativa: a espera é
                # justamente o que a estimativa tenta prever, então cronometrar desde
                # a chegada faria a média guardar o próprio objeto do palpite, e o
                # número se realimentaria — crescendo a noite inteira sem que nada
                # tivesse mudado no serviço. Uma vaga medida é a **inferência**, e
                # nada mais.
                inicio = self._relogio()
            yield posicao
        finally:
            with self._condicao:
                self._vagas_livres += 1
                if inicio is not None:
                    self._medir_vaga(self._relogio() - inicio)
                self._condicao.notify_all()

    def _estimar_espera(self, posicao: int) -> float:
        """Quantos segundos o turno desta posição espera, no melhor palpite disponível.

        A conta é a duração de uma vaga vezes o número de voltas que a posição
        implica, com as voltas arredondadas **para cima**: `ceil(posicao / k)`. Com
        `k=2` e posição 3 são duas voltas — é o que a pessoa espera, porque duas
        vagas abrem de duas em duas. Arredondar para baixo prometeria menos do que o
        turno provavelmente leva, e promessa de espera que não se cumpre é pior do
        que a espera.

        O que multiplica as voltas é a média móvel das vagas já medidas, e não um
        número fixo: `SEGUNDOS_POR_TURNO_SEM_MEDICAO` entra só enquanto nenhuma
        vaga foi medida. A estimativa é adaptativa, e a adaptação é o que corrige a
        noite seguinte.
        """
        segundos_por_vaga = (
            self._media_da_vaga
            if self._media_da_vaga is not None
            else SEGUNDOS_POR_TURNO_SEM_MEDICAO
        )
        voltas = math.ceil(posicao / self.k)
        return segundos_por_vaga * voltas

    def _medir_vaga(self, duracao: float) -> None:
        """Atualiza a média móvel com a vaga que acabou de terminar.

        Ignora durações zero ou negativas, e a guarda não é preciosismo: com o
        relógio de verdade, uma vaga de teste dura microssegundos e puxaria a
        estimativa da noite para perto de zero. O sintoma apareceria como "sua vez é
        a 3ª, cerca de 0 segundos" para o Aluno real de logo depois, e a média não
        se recupera sozinha: uma noite de microssegundos não volta a dez segundos
        sem que a noite recomece. Com o relógio falso do teste, a ausência de
        medição continua sendo ausência de medição.

        Chamada **sob a tranca**, do `finally` de `na_fila`, que a segura para
        devolver a vaga e acordar quem espera. Precisa: a média é lida por
        `_estimar_espera` de outro turno, e ler um `float` meio escrito é a forma
        mais curta de a estimativa pular de um valor para outro sem que ninguém veja
        a troca.
        """
        if duracao <= 0:
            return
        if self._media_da_vaga is None:
            # A primeira medição é a média: um ponto só não tem média, e começar de
            # zero faria o primeiro Aluno da noite ler uma espera de 0 s.
            self._media_da_vaga = duracao
        else:
            self._media_da_vaga = (
                PESO_DA_MEDIA_MOVEL * duracao
                + (1 - PESO_DA_MEDIA_MOVEL) * self._media_da_vaga
            )
