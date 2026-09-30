"""Estado por conversa: o histórico isolado de cada Aluno, que sobrevive ao reinício.

Antes da #9 o turno não tinha memória: o grafo era remontado a cada mensagem e o
`EstadoTurno` carregava só o que aquele turno produzia. Duas perguntas do mesmo
Aluno chegavam ao modelo como se a primeira nunca tivesse sido feita.

Isto é a parte do ADR-0001 que troca worker-por-Aluno por estado-por-conversa. O
que ele promete, em quatro frases: o histórico de uma conversa não aparece na
resposta de outra; ele sobrevive a um reinício do serviço; conversas inativas
expiram; e duas mensagens do mesmo Aluno não se embaralham.

Duas decisões de forma, e as duas importam mais que o resto do código:

- **A chave é o `chat_id`, e não o `from.id`.** O ADR-0001 decide por conversa, e
  não por pessoa: duas pessoas num grupo compartilham o estado, e esse é o limite
  conhecido desta chave. Ver `RegistroDeConversas.conversa`.
- **`RegistroDeConversas` é uma costura, não um casamento.** São quatro métodos —
  `conversa`, `historico`, `registrar` e `expirar` — e é o `webhook` que os chama,
  nunca o grafo. Se um dia o banco virar PostgreSQL, reescreve-se esta classe e
  nada acima dela muda.

**O grafo não faz I/O.** Quem lê e grava é o `webhook`, porque quem sabe qual é a
conversa é o `chat_id` do update, e não o grafo. O grafo recebe o `historico` já
pronto e devolve a resposta; é o que mantém a troca da persona (#10) como troca
de texto.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Literal

logger = logging.getLogger("sau.graph.state")

Papel = Literal["aluno", "sau"]
"""Quem falou. `aluno` é a mensagem que entrou; `sau` é o texto entregue ao Aluno.

`S.A.U.` seria o nome da identidade e `sau` é a chave no arquivo; a grafia do
prompt é de quem escreve a linha, e por isso ela mora em `Mensagem.como_linha` e
não aqui.
"""

TETO_DE_TURNOS_ESPERANDO = 5
"""Quantos turnos do mesmo Aluno podem ficar esperando o anterior antes do aviso.

O teto é **alarme, não válvula**: estourar não recusa e não descarta nada, e o
aviso vai para o log com quantos estão esperando. Quem recusa e quem comunica a
posição é a #11, junto com o semáforo, e recusar aqui seria pior do que esperar —
o acuse já saiu no request, então o Aluno leria "recebi sua mensagem" e não veria
resposta nenhuma.

O número 5 é arbitrário e declarado como tal. Com o `OLLAMA_TIMEOUT` de 30s e um
turno de poucos segundos, ele cobre a noite de alguém mandando perguntas coladas.
"""

MAXIMO_DE_MENSAGENS = 40
"""Quantas mensagens a mais recente fica guardada por conversa.

O histórico vai para o prompt com um recorte bem menor — as 6 mais recentes, três
trocas, pelo `num_ctx` de 2048 do cliente. O teto de 40 existe para o arquivo não
crescer sem limite entre uma limpeza e outra, e não para o prompt: ele segura o
registro, e o TTL da conversa é quem decide quando ele some.
"""

MINUTOS_POR_TTL_PADRAO = 30
"""Quanto tempo uma conversa fica sem ser tocada antes de ser apagada.

Trinta minutos é a escala do plantão da madrugada: uma pausa de trinta minutos
entre duas perguntas é conversa nova, não a mesma conversa retomada. O TTL é o que
faz o arquivo não crescer sem limite — sem ele, `docker compose down` sem `-v`
seria a única limpeza do sistema.
"""

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS conversa (
    chat_id INTEGER PRIMARY KEY,
    ultimo_turno REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS mensagem (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    papel TEXT NOT NULL,
    texto TEXT NOT NULL,
    em REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_mensagem_chat ON mensagem (chat_id, id);
CREATE INDEX IF NOT EXISTS idx_conversa_ultimo ON conversa (ultimo_turno);
"""


@dataclass(frozen=True)
class Mensagem:
    """Uma linha do histórico: quem falou, o que disse e quando.

    Congelada de propósito: a conversa é compartilhada por várias threads — a que
    segura o turno e as que esperam na fila — e uma mensagem mutável no meio delas
    é uma escrita que ninguém pediu.
    """

    papel: Papel
    texto: str
    em: float

    def como_linha(self) -> str:
        """A linha que vai no prompt, com quem falou na frente.

        `S.A.U.:` e não `bot:`, e `Aluno:` e não `user:` — é o vocabulário do
        `CONTEXT.md`. Um modelo que lê "user:" no prompt responde na voz de quem
        escreveu o prompt, não na da identidade que ele está representando.
        """
        rotulo = "S.A.U." if self.papel == "sau" else "Aluno"
        return f"{rotulo}: {self.texto}"


@dataclass
class Conversa:
    """O estado de uma conversa: o histórico dela e a fila FIFO dos seus turnos.

    A conversa carrega o registro porque é por ela que as mensagens entram no
    arquivo, e o `chat_id` porque é a chave que a fila protege — duas conversas
    com o mesmo `chat_id` nunca coexistem, e é isso que torna a fila dela um
    caminho sem bifurcação.
    """

    chat_id: int
    registro: RegistroDeConversas
    _condicao: threading.Condition = field(default_factory=threading.Condition)
    _proxima_senha: int = 0
    _senha_servindo: int = 0
    _encerrada: bool = False
    turnos_esperando: int = 0
    """Quantos turnos pegaram senha e ainda não começaram. O turno que está rodando
    já não conta, e é o que faz o teto valer para a fila de espera e não para o
    histórico inteiro do Aluno."""

    def historico(self) -> list[Mensagem]:
        """O histórico completo da conversa, do mais antigo ao mais recente."""
        return self.registro.historico(self.chat_id)

    def registrar_do_aluno(self, texto: str, em: float) -> None:
        """Grava a mensagem que o Aluno mandou.

        Ela entra **antes** do grafo rodar, e não depois: se o turno falhar, o Aluno
        mandou a pergunta e ela é parte da conversa dele de qualquer jeito. O que
        entra no histórico é o que o Aluno viu, e ele viu a pergunta.
        """
        self.registro.registrar(self.chat_id, Mensagem(papel="aluno", texto=texto, em=em))

    def registrar_do_sau(self, texto: str, em: float) -> None:
        """Grava o texto que o S.A.U. entregou ao Aluno.

        A `TEXTO_FALHA` entra como qualquer outra resposta. O histórico não pode
        divergir da conversa que o Aluno teve: se a falha ficasse de fora, o turno
        seguinte mostraria ao modelo uma conversa que saltou da pergunta do Aluno
        direto para uma resposta sem pergunta nenhuma — que é a forma mais barata
        de fabricar Alucinação.
        """
        self.registro.registrar(self.chat_id, Mensagem(papel="sau", texto=texto, em=em))

    @contextmanager
    def em_ordem(self) -> Iterator[None]:
        """Segura a vez desta conversa, e só dela.

        A ordem é por `chat_id`, e é o ADR-0001 quem decide isso: duas mensagens
        do mesmo Aluno não se embaralham, e as mensagens de Alunos diferentes correm
        em paralelo livremente. Um `threading.Lock` do serviço inteiro serializaria
        todo mundo para garantir o que só precisa ser garantido dentro de uma
        conversa — e é o semáforo da #11, não este lock, que limita quantas
        inferências correm ao mesmo tempo.

        A fila é de **senha**, e não um `Lock` nem um `Event`. Um `Lock` serializa sem
        ordem — o próximo a acordar é quem acordou primeiro, o que não é FIFO. Um
        `Event` é pior aqui: ele acorda *todos* os que estão esperando, e dois turnos do
        mesmo Aluno rodariam juntos, que é exatamente o defeito que a #9 fecha. A senha
        dá a ordem, e o `Condition` dá o despertar sem polling.

        A contagem decresce **antes** do `yield`, e é o que faz o teto valer só para
        a fila de espera: o turno em andamento não está esperando por ninguém, e
        contá-lo faria o teto estourar com um Aluno só mandando mensagem.
        """
        with self._condicao:
            self.turnos_esperando += 1
            if self.turnos_esperando > TETO_DE_TURNOS_ESPERANDO:
                logger.warning(
                    "A fila do Aluno %s tem %d turnos esperando, acima do teto de %d. "
                    "Nenhum turno foi recusado: este é um alarme, e a fila com "
                    "backpressure e mensagem de posição para o Aluno é a #11.",
                    self.chat_id,
                    self.turnos_esperando,
                    TETO_DE_TURNOS_ESPERANDO,
                )
            minha_senha = self._proxima_senha
            self._proxima_senha += 1

        try:
            with self._condicao:
                while self._senha_servindo != minha_senha and not self._encerrada:
                    self._condicao.wait()
                self.turnos_esperando -= 1
            yield
        finally:
            with self._condicao:
                if not self._encerrada:
                    self._senha_servindo += 1
                self._condicao.notify_all()

    def encerrar(self) -> None:
        """Libera quem estiver esperando por esta conversa.

        Chamado quando a conversa expira e quando o registro fecha: sem isto, um
        turno que já estava na fila ficaria esperando uma senha que ninguém vai mais
        servir, e essa espera não tem teto de tempo. A conversa marcada como encerrada
        não volta a serializar — ela já saiu do dicionário do registro, e quem chegar
        depois recebe uma conversa nova.
        """
        with self._condicao:
            self._encerrada = True
            self._condicao.notify_all()


class RegistroDeConversas:
    """O registro de todas as conversas: o arquivo, o TTL e o dicionário em memória.

    Uma conexão só, com `check_same_thread=False`, e uma tranca em torno de cada
    operação. A conexão única é o que evita a corrida do `sqlite3` entre threads: o
    módulo é thread-safe, mas duas conexões para o mesmo arquivo escrevendo ao mesmo
    tempo dão `database is locked` sem aviso — e é a falha que aparece em produção
    e não no teste, porque o teste tem uma thread por vez.

    `journal_mode=WAL` não é detalhe: com ele a leitura do histórico de um Aluno não
    bloqueia a escrita de outro. Sem ele o SQLite serializa tudo no arquivo, e a
    tranca interna do registro vira fila em vez de folga.

    `agora` é o relógio, e é injetável porque o TTL precisa ser testado sem
    `sleep`. Testar expiração esperando trinta minutos de verdade não é teste.
    """

    def __init__(
        self,
        caminho: str,
        ttl_minutos: int = MINUTOS_POR_TTL_PADRAO,
        agora: Callable[[], float] | None = None,
    ) -> None:
        self.caminho = caminho
        self.ttl_minutos = ttl_minutos
        self._agora = agora or time.time
        self._conversas: dict[int, Conversa] = {}
        self._tranca = threading.Lock()
        self._conexao = sqlite3.connect(caminho, check_same_thread=False)
        self._conexao.row_factory = sqlite3.Row
        with self._tranca:
            self._conexao.execute("PRAGMA journal_mode=WAL")
            self._conexao.executescript(_ESQUEMA)
            self._conexao.commit()

    @property
    def conversas_vivas(self) -> Sequence[int]:
        """Os `chat_id` que o registro tem em memória agora.

        Existe para o teste afirmar que a conversa expirada saiu do dicionário, e é
        uma `Sequence` de verdade em vez do dicionário: quem pergunta não pode
        mutar o registro por acidente.
        """
        with self._tranca:
            return sorted(self._conversas)

    def conversa(self, chat_id: int) -> Conversa:
        """A conversa deste `chat_id`, criada se for a primeira vez.

        A chave é o `chat_id` do Telegram e não o `from.id`, e é o ADR-0001 quem
        decide: o estado é por conversa, não por pessoa. O limite conhecido é o
        grupo — duas pessoas num grupo compartilhado compartilham o estado, e o
        S.A.U. conversa com a turma em vez de com uma pessoa. No plantão da
        madrugada, que é conversa particular, o limite não aparece.

        Chamar isto também é o que **varre as conversas inativas**. A limpeza é
        oportunista e acontece no caminho do turno, e não num cron: o ADR-0001
        rejeita mecanismo externo, e varrer aqui prende a memória à taxa real de
        turnos em vez de a um horário — que é o que o critério "sem crescimento
        ilimitado" pede.
        """
        with self._tranca:
            vencidas = self._expirar()
            existente = self._conversas.get(chat_id)
            if existente is not None and chat_id not in vencidas:
                return existente
            nova = Conversa(chat_id=chat_id, registro=self)
            self._conversas[chat_id] = nova
            self._conexao.execute(
                "INSERT OR REPLACE INTO conversa (chat_id, ultimo_turno) VALUES (?, ?)",
                (chat_id, self._agora()),
            )
            self._conexao.commit()
            return nova

    def historico(self, chat_id: int) -> list[Mensagem]:
        """O que já foi dito nesta conversa, do mais antigo ao mais recente.

        A ordem vem do `id` monotônico e não do `em`: dois `time.time()` na mesma
        fração de segundo, em dois inserts seguidos, são indistinguíveis quando o
        relógio vira a chave da ordenação. `enfileirar` e `desenfileirar` dos testes
        dependem dessa ordem para afirmar que nada se embaralhou.

        O teto de `MAXIMO_DE_MENSAGENS` é aplicado aqui, na leitura, e não na
        escrita: apagar a linha antiga a cada insert faria uma escrita por turno
        além da do próprio turno, e o que o teto quer é que a *leitura* nunca
        carregue conversa demais. O arquivo continua guardando tudo até o TTL, que
        é quem apaga de verdade.
        """
        with self._tranca:
            linhas = self._conexao.execute(
                "SELECT id, papel, texto, em FROM mensagem WHERE chat_id = ? ORDER BY id",
                (chat_id,),
            ).fetchall()[-MAXIMO_DE_MENSAGENS:]
        return [
            Mensagem(papel=_papel(linha["papel"]), texto=linha["texto"], em=linha["em"])
            for linha in linhas
        ]

    def registrar(self, chat_id: int, mensagem: Mensagem) -> None:
        """Grava uma mensagem e toca a conversa, para que ela não expire agora."""
        with self._tranca:
            self._conexao.execute(
                "INSERT INTO mensagem (chat_id, papel, texto, em) VALUES (?, ?, ?, ?)",
                (chat_id, mensagem.papel, mensagem.texto, mensagem.em),
            )
            self._gravar_ultimo_turno(chat_id)
            self._conexao.commit()

    def expirar(self) -> list[int]:
        """Apaga as conversas sem contato há mais que o TTL.

        Oportunista: quem chama é o turno. Um `DELETE` indexado por `chat_id`, mais
        a remoção do dicionário em memória, e o `encerrar` para acordar quem
        estivesse na fila de uma conversa que acabou de morrer. Devolve os `chat_id`
        que saíram, que é o que o teste afirma e o que o log do operador usa.
        """
        with self._tranca:
            vencidas = self._expirar()
        return vencidas

    def fechar(self) -> None:
        """Fecha a conexão, depois de acordar quem estiver esperando.

        Sem o `encerrar` antes, um `docker compose down` com um turno na fila
        deixaria a thread presa num `Event` que ninguém vai mais setar.
        """
        with self._tranca:
            for conversa in self._conversas.values():
                conversa.encerrar()
            self._conversas.clear()
            self._conexao.close()

    def _expirar(self) -> list[int]:
        """O `expirar` de verdade, sem a tranca — quem chama já a pegou."""
        corte = self._agora() - self.ttl_minutos * 60
        vencidas = [
            linha["chat_id"]
            for linha in self._conexao.execute(
                "SELECT chat_id FROM conversa WHERE ultimo_turno < ?", (corte,)
            )
        ]
        if not vencidas:
            return []

        # Os `chat_id` vêm de um SELECT desta mesma conexão e são `int`, nunca texto
        # que venha de fora; os marcadores existem porque `IN` não aceita lista.
        marcadores = ", ".join("?" * len(vencidas))
        self._conexao.execute(f"DELETE FROM mensagem WHERE chat_id IN ({marcadores})", vencidas)
        self._conexao.execute(f"DELETE FROM conversa WHERE chat_id IN ({marcadores})", vencidas)
        self._conexao.commit()

        mortas = [
            self._conversas.pop(chat_id) for chat_id in vencidas if chat_id in self._conversas
        ]
        for morta in mortas:
            morta.encerrar()
        logger.info(
            "Conversas sem contato há mais de %d minutos apagadas: %s.",
            self.ttl_minutos,
            vencidas,
        )
        return vencidas

    def _gravar_ultimo_turno(self, chat_id: int) -> None:
        """Marca a conversa como acabada de ser tocada. Sem a tranca: quem chama já a pegou."""
        self._conexao.execute(
            "INSERT OR REPLACE INTO conversa (chat_id, ultimo_turno) VALUES (?, ?)",
            (chat_id, self._agora()),
        )

    def __enter__(self) -> RegistroDeConversas:
        return self

    def __exit__(self, *_erro: object) -> None:
        self.fechar()


def _papel(valor: str) -> Papel:
    """Converte o texto do SQLite no `Papel`, com o desconhecido virando `aluno`.

    O `papel` é gravado por este módulo e nunca por fora, então o valor estranho é um
    arquivo editado à mão — e nesse arquivo um texto que não se sabe de quem é é
    melhor tratado como mensagem do Aluno, que é o papel que não se apresenta como o
    S.A.U. errando.
    """
    return "sau" if valor == "sau" else "aluno"
