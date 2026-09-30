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
  fila de senha dá a ordem, e um `Condition` dá o despertar sem polling. E a fila
  é uma **coleção** de senhas, e não um contador: um turno pode morrer antes de
  entrar, e "passar a vez" tem de ser o próximo turno **vivo**, não o próximo
  número.
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

Sem deadlock, por construção, e por duas contas. A ordem dos dois travamentos é
sempre conversa → semáforo, e nenhum caminho a inverte. E **ninguém consome uma senha
sem servi-la**: quem entra tira a própria senha da fila, e quem sai pelo caminho
anormal — o `aviso` levantou, o `wait` foi interrompido — tira a dele no `finally` em
vez de sumir com ela. Sem essa segunda conta, um turno que morresse depois de tirar a
senha travaria para sempre todos os que estão atrás, sem log e sem mensagem: o
"backpressure comunicado, não escondido" que o ADR-0001 exige viraria o oposto.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
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
    chamado com ela, uma vez só, antes de esperar.

    Nenhuma saída deixa a fila suja, e são duas as contas. Quem chegou a ocupar vaga
    devolve a vaga no `finally`, mesmo com o corpo estourando — sem isso, um turno que
    estourou no grafo queimaria uma vaga pelo resto da madrugada, e o Aluno seguinte
    esperaria por um turno que já morreu. E quem saiu **antes** de ocupar vaga tira a
    própria senha da fila no mesmo `finally` — sem isso, um `sendMessage` que falha ao
    anunciar a posição trava a fila inteira, em silêncio, que é o defeito que o
    ADR-0001 diz que não pode existir.

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
        self._fila: deque[int] = deque()
        """As senhas dos turnos que tiraram a sua e ainda não entraram no modelo.

        A fila é a ordem, e é uma **coleção** e não um contador porque a ordem não é
        um número: um turno pode morrer antes de entrar — o `aviso` dele levantou —,
        e a fila precisa que o turno da vez passe a ser o próximo **vivo**. Com um
        contador, "passar a vez" seria somar um, e a soma pularia as senhas que
        continuam esperando: quem está atrás da que morreu ficaria preso para sempre,
        esperando um número que ninguém viria servir.

        É por isso que `_fila[0]` é a senha da vez, e é a fila que é consultada — nada
        de `_senha_servindo` —, porque dois contadores que discordam é como um
        deadlock entra em silêncio.

        O `remove` da saída anormal é uma varredura, e ela é barata por causa do teto:
        a fila tem no máximo `teto + k` senhas, que é um número de um dígito. Uma
        lista duplamente ligada daria o mesmo resultado com mais código e mais um
        lugar para errar.
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

        - **a senha** diz a ordem. Um turno que não é o primeiro da fila não toma vaga
          mesmo havendo vaga livre, e é isso que sustenta a ordem que o `aviso`
          acabou de anunciar;
        - **a vaga** diz se cabe. Tendo a vez, o turno espera até que uma vaga
          apareça.

        Nenhuma delas sozinha serve: sem a senha, a posição comunicada seria
        mentira; sem a vaga, o `k` não valeria nada.

        A senha sai da fila **ao entrar**, e não ao sair, e essa é a diferença entre um
        semáforo com `k` vagas e um semáforo com uma vaga só. Se saísse da fila na
        devolução, o turno de senha 1 esperaria o turno de senha 0 **terminar** antes
        de entrar — e com `k=2` o serviço atenderia um Aluno por vez, que é o oposto
        do que o `k` promete. Saindo na entrada, o turno de senha 1 entra assim que
        aparece vaga, e o `k` vale.

        A recusa vem **antes** da senha, e essa ordem é o que impede deadlock. Um
        turno recusado não entra na fila — se entrasse, ninguém viria servir aquele
        número e todos os que estão atrás esperariam para sempre.

        Entre quem espera vaga não há deadlock, e o motivo é uma regra só: **ninguém
        consome uma senha sem servi-la.** A senha sai da fila em dois lugares, e nos
        dois é o dono dela que tira a sua: na **entrada**, quando o turno passa a
        ocupar a vaga; e na **saída anormal**, quando o turno nem chegou a entrar — o
        `aviso` levantou, o `wait` foi interrompido. Toda saída notifica todo mundo.

        A saída anormal é a conta que fecha o caso, e ela tem um jeito só de ser feita:
        tirar **a própria senha** da fila, e deixar a fila dizer quem é o da vez. Um
        turno que pegasse a senha 7 e morresse antes de entrar deixaria a 7 na fila
        para sempre, e ninguém viria servi-la — todo mundo atrás espera a **sua**
        senha, e a 7 não é a de ninguém —: o serviço inteiro travaria sem log, sem
        recusa e sem resposta para o Aluno. O sintoma na tela é o pior possível: o
        `TETO_DE_TURNOS_ESPERANDO` da #9 passa a acusar fila cheia para turnos que não
        estão esperando por nada, porque `_esperando` vaza junto.

        E o erro de fazer isso "somando um" é o que a fila viva impede: o turno da
        senha 8 pode morrer antes do turno da senha 7 entrar — o `aviso` de um é
        rápido e o do outro não —, e `_senha_servindo = 8 + 1` pularia a 7. O turno
        da 7 esperaria para sempre, com a fila cheia de gente viva e nenhuma reclamação
        no log. Por isso a ordem é uma coleção, e não um contador.
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
            self._fila.append(minha_senha)

        # Antes do `try`, e `None` de propósito. A exceção dentro do `wait` — um
        # `KeyboardInterrupt`, que morre sem devolução nenhuma — não pode deixar
        # `inicio` sem valor para o `finally` ler. `None` é o que distingue "a vaga
        # foi tomada e a inferência está cronometrada" de "o turno nem chegou a
        # entrar": no segundo caso não há vaga para devolver e não há duração para
        # medir, porque nada rodou.
        inicio: float | None = None
        segurando_vaga = False
        # São dois campos, e não um, porque a janela entre tomar a vaga e ler o
        # relógio existe: se o `relogio` levantasse ali, `inicio` continuaria `None`
        # com a vaga já descontada, e o `finally` não devolveria nada. A flag é
        # escrita **na mesma trava** do desconto, o que fecha a janela.
        try:
            if posicao is not None and aviso is not None:
                # Fora da trava, e por dois motivos. O aviso é I/O — no `webhook` é um
                # `sendMessage` ao Telegram, com teto de 5 s — e segurar a condição
                # durante ele pararia a fila inteira. E nada no aviso reentra no
                # semáforo, então a trava cruzada que seria o problema de verdade não
                # existe; o teste da posição usa este mesmo ponto para acordar o teste.
                #
                # Dentro do `try`, e não fora: este `sendMessage` pode falhar de um
                # jeito que não é `httpx.HTTPError` — um `TELEGRAM_API_BASE`
                # malformado levanta `httpx.InvalidURL`, que não é subclasse —, e essa
                # exceção, fora do `try`, saía do gerador sem passar pelo `finally`.
                # A senha já estava consumida e ninguém viria servi-la: a fila inteira
                # travava em silêncio. É a razão de o `aviso` estar aqui e não ali.
                aviso(posicao)

            with self._condicao:
                while self._fila[0] != minha_senha or self._vagas_livres == 0:
                    self._condicao.wait()
                self._vagas_livres -= 1
                segurando_vaga = True
                # Sai da fila ao entrar no modelo: é a **entrada** que tira a senha da
                # fila, e não a devolução da vaga. Essa é a diferença entre respeitar
                # `k` e atender um Aluno por vez — se a senha só saísse da fila na
                # devolução, o turno de senha 1 esperaria o de senha 0 **terminar**
                # antes de entrar, e com `k=2` o serviço atenderia um Aluno por vez.
                #
                # O `popleft` só tira a senha da vez, que é a deste turno: a espera
                # acima garante que `minha_senha` é a da frente da fila.
                self._fila.popleft()
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
                if segurando_vaga:
                    # Saiu pelo caminho normal ou pelo corpo do `with`: a vaga foi
                    # tomada, e ela volta. Devolver uma vaga que não foi tomada
                    # inflaria o semáforo acima do `k` — com `k=1`, dois turnos no
                    # modelo ao mesmo tempo, que é o defeito que este módulo existe
                    # para impedir.
                    self._vagas_livres += 1
                    if inicio is not None:
                        self._medir_vaga(self._relogio() - inicio)
                else:
                    # Saiu **antes** de entrar, e a fila não pode ficar com uma senha
                    # servível-e-não-servida. O `remove` é o ponto: tira **a senha
                    # dele** da fila, e é a fila que passa a dizer quem é o da vez.
                    # Somar um ao contador da vez, que é o que parece natural, pularia
                    # toda senha viva que ainda está atrás — e quem é pulado fica
                    # esperando para sempre, sem log e sem recusa.
                    #
                    # Sem guarda, e não por descuido: o `popleft` só roda **depois** de
                    # `segurando_vaga` virar `True`, então vir aqui já garante que a
                    # senha deste turno continua na fila. E só o dono tira a sua, uma
                    # vez só, então o `remove` não tem como errar o alvo.
                    self._fila.remove(minha_senha)
                    if posicao is not None:
                        self._esperando -= 1
                # Notifica sempre, e inclusive quando nenhuma das contas acima valeu.
                # Perder um `notify_all` aqui custa um turno inteiro de espera, porque
                # quem está dormindo no `wait` só acorda por aqui.
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
