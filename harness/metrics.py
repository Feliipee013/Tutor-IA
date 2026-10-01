"""As duas taxas binárias da 1.1: não-saber e recusa de Atividade.

Este módulo **não julga**, e isso é decisão da #6 e não concessão: o
julgamento é humano. `preparar_julgamento` escreve a folha com o output de cada
execução na linha a julgar e o `conforme quando` e o `não conforme quando` da
sua Pergunta-teste no bloco `perguntas`, e uma pessoa marca `conforme` ou
`nao_conforme`. O que este módulo faz é contar, e contar com o output ao lado de
cada contagem.

A divisão importa para a banca. Um programa que decidisse sozinho se o S.A.U.
"encaminhou" ou "recusou" julgaria a forma, e a forma é exatamente o que a
Alucinação imita bem: quem lê a forma acha que ouviu o Encaminhamento. Quem
aplicou a régua foi a pessoa, quem somou foi o código, e o número sai
reproduzível a partir de dois arquivos versionados.

Duas taxas, dois denominadores, e nenhum deles é a pergunta:

- **não-saber** — as 4 perguntas fora de alcance (`f1`, `f2`, `f3`, `p1`). `p1`
  entra porque o S.A.U. não tem o prazo sem o corpus da 1.2, e **não** entra na
  recusa: perguntar quando a entrega vence não é pedir a Atividade. A exceção é a
  regra `PRAZO_NAO_E_ATIVIDADE` da persona, e ela é verificada em dois lugares
  independentes — o denominador é montado deste módulo, e `conferir_membros`
  compara este contrato com a linha `conta na métrica do #13` do arquivo de
  Perguntas-teste, que a #6 congelou antes deste ticket.
- **recusa de Atividade** — as 3 perguntas de Atividade (`a1`, `a2`, `a3`). `p2`,
  `p3` e `p4` não contam em nenhuma das duas: pedem pergunta orientadora, que não
  é recusa nem Encaminhamento.

Cada taxa sai em **dois denominadores**, e o [ADR-0006](docs/adr/0006-denominador-das-taxas.md)
decide quais são: a **execução**, que é a leitura primária, e a **pergunta**, que é a
leitura que a #13 nomeia. O ADR-0003 justifica a repetição — das 12 perguntas da
sondagem só 4 tiveram as 3 repetições idênticas, e uma execução só registra uma das
respostas possíveis — e não o denominador, que é uma decisão deste ticket.

As duas divergem quando há variação, e é aí que as duas são necessárias. Com a `f2`
errando 1 das 3 repetições, a leitura por execução dá `11/12 = 0,92` e a por pergunta
dá `3/4 = 0,75`. Uma Pergunta-teste conta como acerto por pergunta quando **todas**
as suas execuções avaliadas conferem, e pergunta sem execução avaliada fica fora do
denominador por pergunta, nunca como erro.

Ao lado dos dois números vai a **leitura de cada pergunta** (`por_pergunta`), que é
uma terceira coisa: o comportamento de uma Pergunta-teste, em `estavel`, `variavel` ou
`sem_avaliacao`. É ela que separa o comportamento que se sustentou na repetição do que
variou, e é o que distingue "o modelo falha sempre nisso" de "o modelo falha metade
das vezes nisso".

O que **não** entra no denominador sai listado em `fora_da_conta`, com o motivo: a
execução que o turno deixou com `erro`, a que a geração cortou por falta de espaço
(`motivo_de_parada == "length"`) e a que a pessoa marcou `nao_avaliavel` com a
razão anotada. Nenhuma delas vira `nao_conforme` por omissão. Resposta cortada tem
cara de resposta — é o que o próprio `harness/run.py` avisa — e um denominador que
engole falha de instrumento mede o instrumento, não o S.A.U.

A exclusão também é evidência, e carrega o `resposta_bruta` que a originou. Tirar uma
execução da conta move o número, e o motivo sozinho não permite conferir se a decisão
foi justa: ele diz por que a execução saiu, e não o que ela respondia. O campo é
`None` só na execução que falhou, que não tem resposta para evidenciar.

Todo número sai com a máquina. O JSON das métricas carrega as `condicoes` da
rodada (modelo, alocação, repetições, seed, `sha256` do prompt versionado) e o
`sha256` do arquivo da rodada, que é o ADR-0003 pedindo que toda afirmação diga de
onde veio. O arquivo não ganha data de cálculo de propósito: ele é reproduzível a
partir da rodada e do julgamento, e um carimbo de "hoje" seria a única coisa que
mudaria entre duas execuções idênticas.

Códigos de saída:

- `0` — as duas taxas foram calculadas e gravadas
- `1` — o julgamento está ausente, ilegível, incompleto ou inconsistente com a
  rodada; ou o contrato das taxas divergiu do arquivo de Perguntas-teste
- `2` — a rodada não está lá, não é um JSON de rodada, ou não fecha a conta que
  ela mesma declara
- `3` — o caminho não pôde ser lido ou gravado: permissão, disco, ou o arquivo
  de Perguntas-teste congelado não abre

Um arquivo fora de UTF-8 não é sempre `3`: o que decide é de quem é o arquivo. A
rodada fora de UTF-8 é `2`, porque quem refaz é a bateria; a folha fora de UTF-8
é `1`, porque quem preencheu é quem salvou com o encoding errado. Só o arquivo
das Perguntas-teste vira `3`, porque ninguém o escreve na hora de rodar o
comando.

O código de saída diz **quem** tem o que corrigir: nos casos de `1` é a folha, nos
casos de `2` é a bateria, e no `3` é o caminho ou a máquina. Uma folha preenchida
com cuidado não tem nada a ver com uma rodada que perdeu uma execução — e um disco
cheio não é defeito de nenhum dos dois.

A folha é o documento que a pessoa leu, e por isso as cópias que ela carrega da
rodada — a régua e o `resposta_bruta` de cada linha — são conferidas uma a uma
contra o arquivo da rodada na hora de carregar. Cópia desatualizada não é
inconveniente: é alguém julgando um output que a rodada não produziu, e o
veredito passaria pela conferência de cobertura porque o `id` e a `repeticao`
continuam certos.

Uso canônico:

    python -m harness.metrics --rodada outputs/baseline-1.1.json --preparar
    python -m harness.metrics --rodada outputs/baseline-1.1.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final, Literal, cast

RAIZ_DO_PROJETO: Final = Path(__file__).resolve().parent.parent
ARQUIVO_PERGUNTAS_PADRAO: Final = RAIZ_DO_PROJETO / "perguntas-teste" / "perguntas-teste.md"

Metrica = Literal["nao_saber", "recusa_de_atividade"]
Veredito = Literal["conforme", "nao_conforme", "nao_avaliavel"]
Leitura = Literal["estavel", "variavel", "sem_avaliacao"]
Motivo = Literal["erro", "cortada", "julgada"]

NAO_SABER: Final[Metrica] = "nao_saber"
RECUSA_DE_ATIVIDADE: Final[Metrica] = "recusa_de_atividade"
METRICAS: Final[tuple[Metrica, ...]] = (NAO_SABER, RECUSA_DE_ATIVIDADE)

TITULOS: Final[dict[Metrica, str]] = {
    NAO_SABER: "Taxa de não-saber",
    RECUSA_DE_ATIVIDADE: "Taxa de recusa de Atividade",
}
"""O nome de cada taxa como a documentação escreve, e não como o JSON guarda.

A chave do JSON é ascii para o arquivo ser legível por qualquer ferramenta, e o
título é o termo que a issue, o relato e a banca usam.
"""

MEMBROS: Final[dict[str, Metrica | None]] = {
    "a1": RECUSA_DE_ATIVIDADE,
    "a2": RECUSA_DE_ATIVIDADE,
    "a3": RECUSA_DE_ATIVIDADE,
    "f1": NAO_SABER,
    "f2": NAO_SABER,
    "f3": NAO_SABER,
    "p1": NAO_SABER,
    "p2": None,
    "p3": None,
    "p4": None,
}
"""Qual taxa cada Pergunta-teste alimenta: o contrato da #13, escrito em código.

`p1` é o ponto sensível do mapa e a razão de `conferir_membros` existir: ela conta
em não-saber e **não** pode estar em recusa, porque perguntar quando a entrega
vence não é pedir a Atividade. `p2`, `p3` e `p4` ficam fora das duas taxas — pedem
pergunta orientadora, que não é recusa nem Encaminhamento — e recontá-las quebraria
a conta 3 + 4 = 7.

Este dicionário não é a fonte da verdade: a fonte é a linha `conta na métrica do
#13` de cada bloco de `perguntas-teste/perguntas-teste.md`, escrita pela #6 antes
deste ticket. Ele é a cópia executável, e `conferir_membros` falha alto quando as
duas divergem, para que uma edição no arquivo congelado quebre o instrumento em
vez de mudar a conta em silêncio.
"""

DENOMINADOR_ESPERADO: Final[dict[Metrica, int]] = {
    NAO_SABER: 4,
    RECUSA_DE_ATIVIDADE: 3,
}
"""Quantas perguntas alimentam cada taxa, em perguntas e não em execuções."""

ORDEM_DA_CADEIA: Final[tuple[str, ...]] = ("s1", "s2", "s3", "s4", "s5")
"""A cadeia especial de `perguntas-teste.md`, na ordem que o Aluno a disse.

Copiado do `harness/run.py` em vez de importado, e a cópia é concertada de propósito:
o `run.py` é quem mede o modelo e este módulo é quem conta, e ligar os dois por
import criaria uma aresta entre as duas metades do harness que só existe por causa
das perguntas. Se a #11 acrescentar um passo à cadeia, `conferir_membros` quebra e
a cópia é atualizada com a issue aberta.
"""

FORA_DAS_TAXAS: Final[frozenset[str]] = frozenset(ORDEM_DA_CADEIA)
"""Os blocos do arquivo que existem e não alimentam nenhuma das duas taxas.

A cadeia especial da #11 é o caso, e ficar fora é decisão, não esquecimento: ela roda
com histórico acumulado, o `harness/run.py` a grava na chave `cadeia` da rodada —
separada de `execucoes` — e nenhuma das duas taxas deste módulo a lê. Os passos `s1` a
`s5` também não trazem a linha `conta na métrica do #13`, porque a #6 as congelou
antes da cadeia existir.

Estar aqui é o que fecha o furo: `conferir_membros` comparava `MEMBROS` só com os
blocos que *tinham* a linha, então um bloco acrescentado ao arquivo sem ela não
entrava em nenhum dos dois conjuntos e o check passava verde. Declarar a cadeia
fora das taxas faz o próximo bloco novo quebrar o instrumento, em vez de mudar a
conta em silêncio.
"""

VEREDITOS: Final[tuple[Veredito, ...]] = ("conforme", "nao_conforme", "nao_avaliavel")

A_PREENCHER: Final = "a preencher"
PARADA_CORTADA: Final = "length"
TAMANHO_DO_TRECHO: Final = 160
"""Quantos caracteres do output bruto vão no resumo em markdown.

O resumo é uma página para ler; a evidência inteira fica no JSON das métricas e no
da rodada. Cortar no meio da resposta seria perigoso — o corte que o modelo faz é
justamente o defeito que a taxa precisa enxergar — e por isso o trecho leva
reticências quando é truncado, para ninguém ler uma frase que o S.A.U. não
terminou.
"""

SAIDA_OK: Final = 0
SAIDA_JULGAMENTO_INVALIDO: Final = 1
SAIDA_RODADA_INVALIDA: Final = 2
SAIDA_ARQUIVO_INACESSIVEL: Final = 3

MAXIMO_DE_FALTAS_LISTADAS: Final = 10


class ErroDasTaxas(Exception):
    """Base das falhas da #13 que não são da rodada nem do julgamento."""


class RodadaInvalidaError(ErroDasTaxas):
    """A rodada não está no arquivo, não tem o formato que a #12 grava, ou não
    fecha a conta que ela mesma declara."""


class JulgamentoInvalidoError(ErroDasTaxas):
    """O julgamento está ausente, incompleto ou não casa com a rodada."""


class MembrosDivergentesError(ErroDasTaxas):
    """O contrato das taxas diverge da linha declarada no arquivo de Perguntas-teste."""


class ArquivoInacessivelError(ErroDasTaxas):
    """A ferramenta não conseguiu ler ou gravar um arquivo.

    Não é defeito da folha nem da bateria: é o caminho, a permissão ou o disco.
    Sem este erro próprio, uma `FileNotFoundError` sozinha cairia no código do
    julgamento e mandaria a pessoa caçar um veredito que está correto.
    """


SAIDA_POR_ERRO: Final[dict[type[ErroDasTaxas], int]] = {
    RodadaInvalidaError: SAIDA_RODADA_INVALIDA,
    JulgamentoInvalidoError: SAIDA_JULGAMENTO_INVALIDO,
    MembrosDivergentesError: SAIDA_JULGAMENTO_INVALIDO,
    ArquivoInacessivelError: SAIDA_ARQUIVO_INACESSIVEL,
}


@dataclass(frozen=True)
class Execucao:
    """Uma execução da rodada: uma Pergunta-teste, uma vez.

    Vem do `execucoes[]` que o `harness/run.py` grava. Os campos que importam
    aqui são três: `resposta_bruta` diz se há o que julgar, `motivo_de_parada`
    separa a resposta cortada da completa, e `id` com `repeticao` dizem a qual
    output um veredito está se referindo.
    """

    id: str
    repeticao: int
    pergunta: str
    conforme_quando: str
    nao_conforme_quando: str
    resposta_bruta: str | None
    erro: str | None
    motivo_de_parada: str | None

    @property
    def chave(self) -> ChaveExecucao:
        return ChaveExecucao(self.id, self.repeticao)
    timestamp: str

    @property
    def julgavel(self) -> bool:
        """Se esta execução pode receber veredito de quem julga.

        Não pode quem não tem resposta — o turno falhou — nem quem teve a geração
        cortada por falta de espaço. O `harness/run.py` avisa disso na rodada
        porque a resposta cortada sai com cara de resposta e parece
        não-conformidade; julgar uma delas seria cobrar veredito de um output que
        o modelo não terminou de escrever.
        """
        return self.resposta_bruta is not None and self.motivo_de_parada != PARADA_CORTADA


@dataclass(frozen=True)
class Rodada:
    """O JSON de uma rodada, lido e conferido.

    `repeticoes` é o único campo de `condicoes` que o cálculo usa, e ele é
    validado como inteiro na leitura — um denominador que só é inteiro na
    hora de multiplicar adia o erro para o meio do cálculo, onde ele vaza
    `traceback` em vez de virar a falha de rodada que é.
    """

    caminho: str
    sha256: str
    modelo: str
    url: str
    condicoes: dict[str, Any]
    repeticoes: int
    alocacao: dict[str, Any] | None
    execucoes: tuple[Execucao, ...]


@dataclass(frozen=True)
class ChaveExecucao:
    """A identidade de uma execução: a pergunta e a repetição.

    Viajou como `tuple[str, int]` cru por todo o módulo — no índice do cálculo, no
    seen set da leitura da folha, na conferência de cobertura e na conferência das
    cópias. Um par solto desses é legível nas cinco linhas em que aparece e ilegível
    na sexta, onde trocar a ordem dos campos troca o significado em silêncio.

    O tipo também segura a frase que o erro precisa: `a1` repetição 3 aparece em
    quatro mensagens de falha diferentes, e escrevê-la à mão em cada uma é como o
    texto sai inconsistente entre elas.
    """

    id: str
    repeticao: int

    def como_texto(self) -> str:
        """Como o erro nomeia a execução: `a1` repetição 3."""
        return f"{self.id} repetição {self.repeticao}"


@dataclass(frozen=True)
class LinhaDaFolha:
    """Uma linha da folha de julgamento, lida e tipada.

    A folha é um JSON escrito para uma pessoa preencher, então a leitura dela chega
    como `dict` cru. Tipar a linha no ponto de entrada é o que deixa a validação
    inteira rodar sobre um objeto, com o mypy `strict` conferindo, em vez de seis
    chamadas a `_texto(item, ...)` espalhadas pelo meio da lógica.
    """

    id: str
    repeticao: int
    metrica: str
    resposta_bruta: str | None
    veredito: str
    nota: str | None

    @property
    def chave(self) -> ChaveExecucao:
        return ChaveExecucao(self.id, self.repeticao)


@dataclass(frozen=True)
class VereditoDeExecucao:
    """O veredito de uma pessoa sobre uma execução, para uma taxa."""

    id: str
    repeticao: int
    metrica: Metrica
    veredito: Veredito
    nota: str

    @property
    def chave(self) -> ChaveExecucao:
        return ChaveExecucao(self.id, self.repeticao)


@dataclass(frozen=True)
class Julgamento:
    """A folha de julgamento de uma rodada: quem julgou, quando e o que disse."""

    caminho: str
    sha256_da_rodada: str
    julgador: str
    julgado_em: str
    vereditos: tuple[VereditoDeExecucao, ...]


@dataclass(frozen=True)
class Evidencia:
    """Uma contagem e o output que a originou, inteiro.

    `resposta_bruta` vai sem corte: é o critério de aceitação da #13 — cada
    contagem aponta o output que a originou, para nenhuma taxa ficar sem
    evidência. Um resumo de uma linha serviria ao olho e não a quem precisar
    conferir o número depois.
    """

    id: str
    repeticao: int
    veredito: Veredito
    pergunta: str
    resposta_bruta: str
    timestamp: str
    motivo_de_parada: str | None

    @property
    def chave(self) -> ChaveExecucao:
        return ChaveExecucao(self.id, self.repeticao)


@dataclass(frozen=True)
class LeituraDaPergunta:
    """A mesma métrica lida por pergunta: acertou sempre, errou sempre ou variou."""

    id: str
    metrica: Metrica
    conformes: int
    avaliadas: int
    leitura: Leitura


@dataclass(frozen=True)
class ForaDaConta:
    """Uma execução que existe na rodada e não entra em nenhuma contagem.

    Carrega o `resposta_bruta` pela mesma razão que a `Evidencia` carrega: o
    critério de aceitação da #13 exige evidência por contagem, e uma execução
    excluída da conta também é uma decisão que o número descreve. Quem lê a
    exclusão precisa ver o que foi excluído — o motivo diz por que a execução saiu
    da conta, e não o que a resposta dizia.

    É `None` só no caso de erro: a execução que falhou não tem resposta para
    evidenciar, e `None` é o que a rodada grava nessa situação.
    """

    id: str
    repeticao: int
    motivo: Motivo
    detalhe: str
    resposta_bruta: str | None = None

    @property
    def chave(self) -> ChaveExecucao:
        return ChaveExecucao(self.id, self.repeticao)


@dataclass(frozen=True)
class Taxa:
    """Uma das duas taxas, com o numerador, o denominador e a evidência dos dois.

    São dois denominadores, e o nome de cada campo diz de quem é. `fracao` e
    `fracao_formatada` são a leitura por execução, que é a primária; `fracao_por_
    pergunta` e `fracao_por_pergunta_formatada` são a leitura por pergunta, que é a
    que a #13 nomeia. As duas estão no ADR-0006, e o motivo de as duas existirem é
    que elas divergem quando há variação: com a `f2` em 2 de 3, uma dá 11/12 e a
    outra 3/4.
    """

    metrica: Metrica
    perguntas: int
    repeticoes: int
    esperadas: int
    avaliadas: int
    numerador: int
    fracao: float
    fracao_formatada: str
    perguntas_conformes: int
    perguntas_avaliadas: int
    fracao_por_pergunta: float
    fracao_por_pergunta_formatada: str
    acertos: tuple[Evidencia, ...]
    erros: tuple[Evidencia, ...]
    por_pergunta: tuple[LeituraDaPergunta, ...]
    fora_da_conta: tuple[ForaDaConta, ...]


@dataclass(frozen=True)
class RelatorioDasTaxas:
    """As duas taxas de uma rodada, com a rodada e o julgamento que as produziram."""

    rodada: Rodada
    julgamento: Julgamento
    taxas: dict[Metrica, Taxa]


ID_DE_FIM: Final = "fim"
"""O marcador que fecha o texto da Pergunta-teste dentro do bloco dela.

Ele é a mesma coisa que um marcador de pergunta para quem lê o arquivo, e não é
uma pergunta para quem mede: a tabela de comportamento esperado vem **depois**
dele. Confundir os dois faz cada bloco parecer sem linha — ou pior, faz a linha
da `a1` parecer declarada no bloco da `a2`.
"""

RE_MARCADOR: Final = re.compile(r"<!--\s*pergunta:(?P<id>[a-z0-9_-]+)\s*-->")
RE_LINHA_DA_METRICA: Final = re.compile(
    r"^\|\s*conta na métrica do #13\s*\|\s*(?P<valor>.*?)\s*\|\s*$", re.MULTILINE
)


def sha256_de_arquivo(caminho: Path) -> str:
    """O `sha256` do arquivo, para amarrar um julgamento à rodada que ele julga.

    A folha de julgamento é escrita contra uma rodada específica; aplicada a
    outra, mede a rodada errada sem reclamar. O hash é o que faz a folha parar de
    valer no instante em que a rodada muda.
    """
    return hashlib.sha256(caminho.read_bytes()).hexdigest()


def caminho_relativo(caminho: Path) -> str:
    """O caminho como se escreve no repositório, para o JSON versionado.

    Um caminho absoluto entra no `outputs/baseline-1.1.julgamento.json` com o nome
    da máquina de quem rodou, e o arquivo deixa de ser comparável com o da outra
    pessoa. Fora da árvore do projeto o caminho vai como veio: ali não há
    referência, e inventar uma seria pior.
    """
    try:
        return str(caminho.resolve().relative_to(RAIZ_DO_PROJETO))
    except ValueError:
        return str(caminho)


def metrica_declarada(valor: str) -> Metrica | None:
    """Lê a métrica que o bloco da Pergunta-teste declara para a #13.

    O texto é livre por decisão da #6 — é o `conforme quando` que precisa de
    palavra, o nome da métrica não — e por isso a leitura é pelo começo da frase,
    não por palavra solta: a linha da `p1` é "taxa de não-saber — e **nunca** taxa
    de recusa de Atividade", e quem procura a palavra "recusa" nela lê o
    contrário do que o bloco declara.
    """
    limpo = valor.replace("**", "").strip()
    if limpo.startswith("taxa de não-saber"):
        return NAO_SABER
    if limpo.startswith("taxa de recusa"):
        return RECUSA_DE_ATIVIDADE
    if limpo.startswith("nenhuma"):
        return None
    raise MembrosDivergentesError(
        f"a linha `conta na métrica do #13` começou com {limpo!r}, e este módulo só "
        f"reconhece as três formas declaradas: taxa de não-saber, taxa de recusa "
        f"de Atividade e nenhuma das duas taxas"
    )


def _blocos_do_arquivo(conteudo: str) -> dict[str, str]:
    """Cada bloco de Pergunta-teste, do marcador dela até o marcador da próxima.

    Os marcadores que não abrem pergunta são deixados de fora, e é por isso que
    `ID_DE_FIM` existe: com eles dentro, o bloco da `a1` terminaria no
    `<!-- pergunta:fim -->` e a tabela de comportamento esperado — que vem depois
    dele — ficaria do lado de fora da busca.
    """
    marcadores = [
        achado for achado in RE_MARCADOR.finditer(conteudo) if achado.group("id") != ID_DE_FIM
    ]
    blocos: dict[str, str] = {}
    for indice, marcador in enumerate(marcadores):
        seguinte = marcadores[indice + 1].start() if indice + 1 < len(marcadores) else len(conteudo)
        blocos[marcador.group("id")] = conteudo[marcador.start() : seguinte]
    return blocos


def metricas_declaradas(arquivo: Path = ARQUIVO_PERGUNTAS_PADRAO) -> dict[str, str]:
    """O valor cru da linha `conta na métrica do #13` de cada bloco, por id.

    A linha é o que a #6 escreveu e é a fonte do contrato das taxas. Ela vem
    crua, sem interpretar, porque o texto é dela: quem lê esta função está
    olhando o que o arquivo diz, e a interpretação é `metrica_declarada`.

    Um bloco sem a linha não aparece no resultado — e `conferir_membros` trata a
    ausência como erro, em vez de deixar um denominador mudar em silêncio.
    """
    return _linhas_da_metrica(blocos_de_perguntas(arquivo))


def _linhas_da_metrica(blocos: Mapping[str, str]) -> dict[str, str]:
    """O valor cru da linha da métrica de cada bloco, a partir dos blocos já lidos.

    Existe para o arquivo ser lido uma vez só: `conferir_membros` precisa dos blocos
    inteiros, para conferir o fecho, e dos valores declarados, e ler o arquivo duas
    vezes abriria a chance de as duas leituras discordarem.
    """
    declaradas: dict[str, str] = {}
    for id_pergunta, bloco in blocos.items():
        achado = RE_LINHA_DA_METRICA.search(bloco)
        if achado is not None:
            declaradas[id_pergunta] = achado.group("valor").strip()
    return declaradas


def blocos_de_perguntas(arquivo: Path = ARQUIVO_PERGUNTAS_PADRAO) -> dict[str, str]:
    """O arquivo de Perguntas-teste lido e partido em blocos, ou o erro do contrato.

    Esta é a **única** leitura do arquivo, e ela existe para ser o único lugar onde
    o `OSError` e o `UnicodeDecodeError` são convertidos. Antes estas duas classes
    escapavam daqui e subiam como `traceback`, com o código de saída do interpretador
    — que é `1`, o código do julgamento. Duas consequências ruins de uma vez: quem
    preenche a folha lia uma pilha de Python em vez de uma frase, e o `1` mandava
    caçar um veredito que está correto quando o defeito era o caminho. O `docstring`
    do módulo e o `SETUP.md` prometem o `3` para permissão negada, disco cheio e
    "um arquivo que não é UTF-8"; esta é a **única** leitura onde a última se
    cumpre. O não-UTF-8 nos outros dois arquivos tem dono diferente, e por isso
    outro código: a rodada é `2` e a folha é `1`, porque quem refaz cada uma
    delas é quem a escreveu.

    Um arquivo que não existe é outra falha, com outro dono: é o contrato das taxas
    que não tem com o que ser conferido, e quem tem que corrigir é quem responde
    pelas Perguntas-teste, não quem rodou o comando. Daí o `1`, e não o `3`.
    """
    if not arquivo.is_file():
        raise MembrosDivergentesError(
            f"o arquivo de Perguntas-teste não está em {arquivo}, e sem ele o "
            f"contrato das taxas não tem com o que ser conferido"
        )

    try:
        return _blocos_do_arquivo(arquivo.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        raise ArquivoInacessivelError(
            f"não consegui ler as Perguntas-teste em {arquivo}: {exc}. O caminho "
            f"existe e tem permissão de leitura?"
        ) from exc


def conferir_membros(arquivo: Path = ARQUIVO_PERGUNTAS_PADRAO) -> None:
    """Confere `MEMBROS` contra o arquivo de Perguntas-teste congelado pela #6.

    É a verificação da exceção do prazo: `p1` precisa estar em não-saber nos dois
    lugares — no dicionário e na linha que a #6 escreveu antes deste ticket — e a
    "taxa de recusa" que aparece na mesma linha da `p1` é justamente o que não se
    pode ler como segunda métrica.

    Também confere a contagem 4 + 3 = 7 perguntas, porque um mapeamento certo com
    uma pergunta faltando produz uma taxa que parece inteira e não é.

    E confere o fecho: todo bloco do arquivo tem que estar em `MEMBROS` ou em
    `FORA_DAS_TAXAS`. Um bloco que não está em nenhum dos dois entraria na taxa sem
    o denominador saber, ou ficaria de fora sem ninguém declarar que foi de fora.
    """
    blocos = blocos_de_perguntas(arquivo)
    declarados = {
        id_pergunta: metrica_declarada(valor)
        for id_pergunta, valor in _linhas_da_metrica(blocos).items()
    }

    faltando = sorted(set(MEMBROS) - set(declarados))
    sobrando = sorted(set(declarados) - set(MEMBROS))
    if faltando or sobrando:
        raise MembrosDivergentesError(
            f"as perguntas com a linha `conta na métrica do #13` não batem com as "
            f"perguntas que este módulo mede — sem a linha no arquivo: {faltando}; "
            f"sem métrica neste módulo: {sobrando}"
        )

    divergentes = sorted(
        id_pergunta
        for id_pergunta, metrica in MEMBROS.items()
        if declarados[id_pergunta] != metrica
    )
    if divergentes:
        raise MembrosDivergentesError(
            f"o arquivo de Perguntas-teste declara outra métrica para {divergentes}. "
            f"O arquivo é congelado pela #6: quem muda a conta muda os dois lados, "
            f"com a issue aberta"
        )

    contagens = {
        metrica: sum(1 for valor in MEMBROS.values() if valor == metrica)
        for metrica in METRICAS
    }
    if contagens != DENOMINADOR_ESPERADO:
        raise MembrosDivergentesError(
            f"as taxas esperam {DENOMINADOR_ESPERADO} perguntas cada e o contrato tem "
            f"{contagens}"
        )

    sem_destino = sorted(set(blocos) - set(MEMBROS) - FORA_DAS_TAXAS)
    if sem_destino:
        raise MembrosDivergentesError(
            f"os blocos {sem_destino} do arquivo de Perguntas-teste não declaram "
            f"`conta na métrica do #13` e não estão em `FORA_DAS_TAXAS`: ou o bloco "
            f"declara a taxa em que entra, ou entra na cadeia especial, que é o que "
            f"`{', '.join(ORDEM_DA_CADEIA)}` faz. Sem uma das duas, o denominador "
            f"mede um conjunto que o arquivo não descreve"
        )


def carregar_rodada(caminho: Path) -> Rodada:
    """Lê o JSON de uma rodada do `harness/run.py` e confere o que este módulo precisa.

    Falha alto e com o nome do campo faltando, porque rodada é a evidência de tudo
    aqui: uma taxa calculada sobre uma rodada lida pela metade é um número que
    parece exatamente igual ao número certo.

    `condicoes.repeticoes` é obrigatório e inteiro, conferido aqui e não na hora
    de calcular. A leitura é o último lugar onde o defeito ainda é nomeável: no
    cálculo ele é só um denominador, e um denominador que não é inteiro aparece
    como `ValueError` de `int()` no meio da multiplicação — pilha de Python para
    quem preencheu a folha direito. O `harness/run.py` sempre grava o campo, com
    o `--repeticoes` já validado como inteiro maior ou igual a 1, então a
    conferida aqui não fecha porta que a bateria abre.
    """
    if not caminho.is_file():
        raise RodadaInvalidaError(
            f"a rodada não está em {caminho}. Ela sai de "
            f"`python -m harness.run --saida outputs/baseline-1.1.json`"
        )

    try:
        bruto = _ler_json(caminho, "a rodada")
        if not isinstance(bruto, dict):
            raise ErroDasTaxas("a rodada não é um objeto JSON")
        onde = f"a rodada em {caminho}"

        execucoes = bruto.get("execucoes")
        if not isinstance(execucoes, list):
            raise ErroDasTaxas("o campo `execucoes` não é uma lista")
        lidas = tuple(
            _ler_execucao(item, f"execução {indice + 1}")
            for indice, item in enumerate(execucoes)
        )
        condicoes = bruto.get("condicoes")
        if not isinstance(condicoes, dict):
            raise ErroDasTaxas("o campo `condicoes` não é um objeto")
        repeticoes = _numero(condicoes, "repeticoes", f"{onde}, em `condicoes`")
        alocacao = bruto.get("alocacao")
        if alocacao is not None and not isinstance(alocacao, dict):
            raise ErroDasTaxas("o campo `alocacao` não é um objeto nem nulo")
        rodada = Rodada(
            caminho=caminho_relativo(caminho),
            sha256=sha256_de_arquivo(caminho),
            modelo=_texto(bruto, "modelo", onde),
            url=_texto(bruto, "url", onde),
            condicoes=dict(condicoes),
            repeticoes=repeticoes,
            alocacao=dict(alocacao) if isinstance(alocacao, dict) else None,
            execucoes=lidas,
        )
    except ErroDasTaxas as exc:
        raise RodadaInvalidaError(str(exc)) from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise RodadaInvalidaError(
            f"não consegui ler a rodada em {caminho}: {exc}"
        ) from exc
    return rodada


def folha_de_julgamento(rodada: Rodada) -> dict[str, Any]:
    """A folha de julgamento de uma rodada, com a régua e os vereditos em branco.

    Cada linha traz **o output que se está julgando**, inteiro, ao lado do
    `veredito`. Sem o output aqui, julgar exigiria abrir o JSON da rodada e cruzar
    30 execuções à mão por `id` e `repeticao` — e é justamente a pessoa que
    precisa ler a resposta para aplicar a régua que não deveria ter caça aberta ao
    arquivo bruto. O texto vem repetido no JSON das taxas, e a duplicação é o
    preço: uma folha que não se sustenta sozinha não é folha, é índice.

    A régua vem no bloco `perguntas`, com o `conforme quando` e o `não conforme
    quando` de cada pergunta que conta, para que ninguém abra outro arquivo para
    saber contra o que está julgando. São 4 perguntas de não-saber e 3 de
    Atividade, cada uma com as repetições da rodada.

    Execução sem resposta e execução cortada **não** ganham linha: não há o que
    julgar nelas, e uma linha vazia na folha só faria a pessoa procurar veredito
    para um output que o modelo não terminou de escrever. Elas entram na taxa como
    `fora_da_conta`, com o motivo, no momento do cálculo.
    """
    perguntas: dict[str, dict[str, str]] = {}
    vereditos: list[dict[str, Any]] = []
    for execucao in rodada.execucoes:
        metrica = MEMBROS.get(execucao.id)
        if metrica is None:
            continue
        perguntas.setdefault(
            execucao.id,
            {
                "pergunta": execucao.pergunta,
                "conforme_quando": execucao.conforme_quando,
                "nao_conforme_quando": execucao.nao_conforme_quando,
            },
        )
        if not execucao.julgavel:
            continue
        vereditos.append(
            {
                "id": execucao.id,
                "repeticao": execucao.repeticao,
                "metrica": metrica,
                "resposta_bruta": execucao.resposta_bruta,
                "veredito": A_PREENCHER,
                "nota": "",
            }
        )
    return {
        "rodada": rodada.caminho,
        "sha256_da_rodada": rodada.sha256,
        "julgador": A_PREENCHER,
        "julgado_em": A_PREENCHER,
        "perguntas": perguntas,
        "vereditos": vereditos,
    }


def preparar_julgamento(rodada: Rodada, destino: Path) -> Path:
    """Escreve em disco a folha que `folha_de_julgamento` monta, e diz quantas linhas."""
    folha = folha_de_julgamento(rodada)
    _gravar(destino, folha)
    pendentes = len(folha["vereditos"])
    print(f"folha de julgamento escrita em {destino}")
    print(
        f"{pendentes} vereditos a preencher. Preencha `julgador`, `julgado_em` e o "
        f"`veredito` de cada linha, e depois rode sem `--preparar`"
    )
    return destino


def carregar_julgamento(caminho: Path, rodada: Rodada) -> Julgamento:
    """Lê a folha de julgamento e falha alto em tudo que a deixaria menteira.

    São seis conferências, e cada uma cobre um modo concreto de o número sair
    errado sem ninguém perceber: hash de outra rodada, quem julgou em branco, régua
    divergente da rodada, veredito fora do vocabulário, veredito de pergunta que não
    conta em taxa nenhuma, e execução sem veredito — o caso em que a taxa sai com
    denominador curto e parece firme.
    """
    if not caminho.is_file():
        raise JulgamentoInvalidoError(
            f"o julgamento não está em {caminho}. Ele nasce de "
            f"`python -m harness.metrics --rodada {rodada.caminho} --preparar`"
        )

    try:
        bruto = _ler_json(caminho, "o julgamento")
        if not isinstance(bruto, dict):
            raise ErroDasTaxas("o julgamento não é um objeto JSON")
        onde = f"o julgamento em {caminho}"

        sha = _texto(bruto, "sha256_da_rodada", onde)
        if sha != rodada.sha256:
            raise JulgamentoInvalidoError(
                f"é o julgamento de outra rodada: o sha256 guardado é {sha} e a "
                f"rodada {rodada.caminho} tem {rodada.sha256}. Veredito de uma "
                f"rodada aplicado a outra mede a rodada errada"
            )

        for campo in ("julgador", "julgado_em"):
            if _texto(bruto, campo, onde) == A_PREENCHER:
                raise JulgamentoInvalidoError(
                    f"o campo `{campo}` está `{A_PREENCHER}`. A taxa precisa dizer "
                    f"quem aplicou a régua e quando — é isso que separa um número de "
                    f"uma opinião"
                )

        _conferir_reguas_da_folha(bruto.get("perguntas"), rodada, onde)
        vereditos = _ler_vereditos(bruto.get("vereditos"), rodada, onde)
        _conferir_cobertura(vereditos, rodada, onde)
    except JulgamentoInvalidoError:
        raise
    except ErroDasTaxas as exc:
        raise JulgamentoInvalidoError(str(exc)) from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise JulgamentoInvalidoError(
            f"não consegui ler o julgamento em {caminho}: {exc}"
        ) from exc

    return Julgamento(
        caminho=caminho_relativo(caminho),
        sha256_da_rodada=sha,
        julgador=cast(str, bruto["julgador"]),
        julgado_em=cast(str, bruto["julgado_em"]),
        vereditos=vereditos,
    )


def calcular(rodada: Rodada, julgamento: Julgamento) -> RelatorioDasTaxas:
    """Calcula as duas taxas, com a evidência de cada contagem.

    O denominador é a execução julgada de cada pergunta que conta na taxa; o que
    sobra da rodada vai para `fora_da_conta` com o motivo, nunca para o
    denominador. Cada acerto e cada erro carrega o `resposta_bruta` inteiro,
    resolvido por `id` e `repeticao` — nunca por índice, que trocaria de output no
    dia em que alguém reordenar a bateria.
    """
    indice = {veredito.chave: veredito for veredito in julgamento.vereditos}
    taxas = {metrica: _calcular_uma(rodada, indice, metrica) for metrica in METRICAS}
    return RelatorioDasTaxas(rodada=rodada, julgamento=julgamento, taxas=taxas)


def gravar_metricas(relatorio: RelatorioDasTaxas, destino: Path) -> Path:
    """Grava o JSON das taxas: os números, a evidência e de onde saíram.

    `condicoes` e `alocacao` vêm da rodada, e não são enfeite: sem o modelo, a
    alocação e o `sha256` do prompt versionado ao lado do número, a taxa da 1.1 não
    é comparável com a da 1.2 e a afirmação qualitativa não diz de qual máquina
    veio — que é o defeito que o ADR-0003 existe para impedir.
    """
    rodada = relatorio.rodada
    documento = {
        "rodada": rodada.caminho,
        "sha256_da_rodada": rodada.sha256,
        "modelo": rodada.modelo,
        "url": rodada.url,
        "condicoes": rodada.condicoes,
        "alocacao": rodada.alocacao,
        "julgamento": {
            "arquivo": relatorio.julgamento.caminho,
            "sha256_da_rodada": relatorio.julgamento.sha256_da_rodada,
            "julgador": relatorio.julgamento.julgador,
            "julgado_em": relatorio.julgamento.julgado_em,
        },
        "taxas": {metrica: asdict(taxa) for metrica, taxa in relatorio.taxas.items()},
    }
    _gravar(destino, documento)
    return destino


def resumo_em_markdown(relatorio: RelatorioDasTaxas) -> str:
    """A página que vai para o relato: os dois números, a evidência e a régua.

    Sai com os dois denominadores declarados — o por execução e o por pergunta, que é
    o que o ADR-0006 pede — e com o trecho do output de cada contagem. O texto inteiro
    fica no JSON. A régua vai no fim, inteira, porque a página precisa responder sozinha
    a "contra o que isso foi medido".
    """
    rodada = relatorio.rodada
    julgamento = relatorio.julgamento
    partes = [
        "## As duas taxas da 1.1",
        "",
        f"- Rodada: `{rodada.caminho}` — sha256 `{rodada.sha256}`",
        f"- Modelo: `{rodada.modelo}` — {rodada.repeticoes} repetições",
        f"- Alocação: {_descrever_alocacao(rodada.alocacao)}",
        f"- Julgamento: `{julgamento.caminho}` — {julgamento.julgador}, "
        f"{julgamento.julgado_em}",
        "",
    ]

    for metrica in METRICAS:
        taxa = relatorio.taxas[metrica]
        partes.extend(
            [
                f"### {TITULOS[metrica]} — {taxa.fracao_formatada}",
                "",
                f"Por pergunta: **{taxa.fracao_por_pergunta_formatada}**.",
                "",
                f"Denominador por execução: {taxa.perguntas} perguntas × "
                f"{taxa.repeticoes} repetições = {taxa.esperadas} execuções, "
                f"{taxa.avaliadas} avaliadas, {len(taxa.fora_da_conta)} fora da conta.",
                f"Denominador por pergunta: {taxa.perguntas_avaliadas} das "
                f"{taxa.perguntas} perguntas tiveram execução avaliada, e "
                f"{taxa.perguntas_conformes} conferam em todas.",
                "",
                "| Pergunta | Acerto | Avaliadas | Comportamento |",
                "| --- | --- | --- | --- |",
            ]
        )
        partes.extend(
            f"| `{leitura.id}` | {leitura.conformes} | {leitura.avaliadas} "
            f"| {leitura.leitura} |"
            for leitura in taxa.por_pergunta
        )
        partes.extend(["", "**Acerto — a evidência do numerador**", ""])
        partes.extend(_linhas_de_evidencia(taxa.acertos))
        if taxa.erros:
            partes.extend(
                [
                    "",
                    f"**Erro — o resto do denominador** ({taxa.avaliadas} avaliadas = "
                    f"{taxa.numerador} acertos + {_plural(len(taxa.erros), 'erro')})",
                    "",
                ]
            )
            partes.extend(_linhas_de_evidencia(taxa.erros))
        if taxa.fora_da_conta:
            partes.extend(["", "**Fora da conta**", ""])
            partes.extend(_linhas_de_fora_da_conta(taxa.fora_da_conta))
        partes.append("")

    partes.extend(
        [
            "### Régua de cada Pergunta-teste",
            "",
            "O veredito foi aplicado nesta frente, e nenhuma outra.",
            "",
        ]
    )
    for metrica in METRICAS:
        partes.extend([f"**{TITULOS[metrica]}**", ""])
        for leitura in relatorio.taxas[metrica].por_pergunta:
            regua = _regua_de(rodada, leitura.id)
            partes.append(f"- `{leitura.id}` — {regua['pergunta']}")
            partes.append(f"  - conforme quando: {regua['conforme_quando']}")
            partes.append(f"  - não conforme quando: {regua['nao_conforme_quando']}")
        partes.append("")

    return "\n".join(partes).rstrip() + "\n"


def montar_argumentos(argumentos: Sequence[str] | None = None) -> argparse.Namespace:
    analisador = argparse.ArgumentParser(
        description=(
            "Calcula a taxa de não-saber e a taxa de recusa de Atividade sobre uma "
            "rodada do harness. O julgamento é humano (decisão da #6): este módulo "
            "prepara a folha e conta, ele não decide conforme nem não conforme."
        ),
        epilog=(
            "Uso normal em dois passos: primeiro --preparar para escrever a folha de "
            "julgamento, depois sem a flag para calcular as taxas. Os nomes de "
            "arquivo saem do nome da rodada: baseline-1.1.json vira "
            "baseline-1.1.julgamento.json e baseline-1.1.metricas.json. "
            "Saídas, e cada uma diz quem tem o que corrigir: 0 as duas taxas foram "
            "gravadas; 1 o julgamento está ausente, ilegível, incompleto ou "
            "inconsistente com a rodada, ou o contrato das taxas divergiu do "
            "arquivo de Perguntas-teste — corrija a folha; 2 a rodada está "
            "ausente, ilegível ou não fecha a conta que ela declara — corrija a "
            "bateria; 3 o caminho não pôde ser lido ou gravado — confira a "
            "permissão e o disco. argparse também sai com 2 em argumento "
            "inválido, e nesse caso o 2 é do argparse, não desta tabela."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    analisador.add_argument(
        "--rodada",
        type=Path,
        required=True,
        help="JSON da rodada do harness (ex.: outputs/baseline-1.1.json)",
    )
    analisador.add_argument(
        "--preparar",
        action="store_true",
        help="escreve a folha de julgamento em branco em vez de calcular as taxas",
    )
    analisador.add_argument(
        "--julgamento",
        type=Path,
        default=None,
        help="folha de julgamento (padrão: a rodada com o sufixo .julgamento.json)",
    )
    analisador.add_argument(
        "--saida",
        type=Path,
        default=None,
        help="JSON das taxas (padrão: a rodada com o sufixo .metricas.json)",
    )
    return analisador.parse_args(argumentos)


def main(argumentos: Sequence[str] | None = None) -> int:
    """O comando das duas taxas: prepara a folha ou calcula, e diz como saiu.

    Todo erro das taxas sai pelo mesmo lugar, com o código de saída tirado do
    próprio erro, e ele diz **quem** tem o que corrigir: uma falha de rodada é 2 e
    manda voltar à bateria; uma falha de julgamento é 1 e manda voltar à folha;
    um caminho que não abre para leitura ou escrita é 3 e manda conferir a
    permissão e o disco. A rodada cuja contagem não fecha com as repetições que
    ela declara é falha de rodada como as outras, e sai 2 — dizer 1 mandaria a
    pessoa caçar um veredito que está correto.

    A rodada que declara as repetições fora de um inteiro é a mesma coisa, e sai 2
    pelos dois passos: `carregar_rodada` roda antes do `--preparar`, de modo que a
    folha não é escrita para uma rodada que o cálculo recusaria. Um `--preparar`
    que sai 0 numa rodada que não fecha é sucesso falso na pior hora — a pessoa
    preenche a folha inteira antes de descobrir que a evidência não existe.

    Um `traceback` aqui seria pior que a mensagem: quem preenche a folha não vai
    ler pilha de Python para saber o que digitou de errado. Por isso as leituras
    e as escritas convertem `OSError` e `UnicodeDecodeError` no erro do contrato
    que lhes cabe, em vez de deixá-las escapar: um arquivo que não é UTF-8 e um
    disco cheio são defeitos de arquivo, não de folha nem de bateria. E o
    denominador é conferido na leitura pelo mesmo motivo: ele é o único número
    que vem do texto cru da rodada, e um `int()` no meio do cálculo é a forma mais
    barata de produzir `traceback` num caminho que já prometeu não produzir
    nenhum.
    """
    try:
        return _executar(montar_argumentos(argumentos))
    except ErroDasTaxas as exc:
        print(f"\nFALHA: {exc}", file=sys.stderr)
        return SAIDA_POR_ERRO.get(type(exc), SAIDA_JULGAMENTO_INVALIDO)


def _executar(opcoes: argparse.Namespace) -> int:
    conferir_membros()
    rodada = carregar_rodada(opcoes.rodada)

    if opcoes.preparar:
        destino = opcoes.julgamento or _com_sufixo(opcoes.rodada, "julgamento")
        preparar_julgamento(rodada, destino)
        return SAIDA_OK

    caminho = opcoes.julgamento or _com_sufixo(opcoes.rodada, "julgamento")
    julgamento = carregar_julgamento(caminho, rodada)
    relatorio = calcular(rodada, julgamento)
    destino = opcoes.saida or _com_sufixo(opcoes.rodada, "metricas")
    gravar_metricas(relatorio, destino)

    print(resumo_em_markdown(relatorio))
    print(f"\nJSON das taxas gravado em {destino}")
    return SAIDA_OK


def _com_sufixo(caminho: Path, sufixo: str) -> Path:
    """`outputs/baseline-1.1.json` vira `outputs/baseline-1.1.julgamento.json`.

    O nome sai da rodada de propósito: julgamento e métricas são arquivos de uma
    rodada, e o `.gitignore` já preserva `outputs/baseline-*.json` — o que faz os
    três artefatos entrarem juntos como a evidência de uma linha de base, sem
    regra nova.
    """
    return caminho.with_name(f"{caminho.stem}.{sufixo}.json")


def _calcular_uma(
    rodada: Rodada,
    indice: dict[ChaveExecucao, VereditoDeExecucao],
    metrica: Metrica,
) -> Taxa:
    """A taxa de uma métrica, com os dois denominadores do ADR-0006.

    O denominador por execução vem de `rodada.repeticoes`, que `carregar_rodada` já
    conferiu como inteiro. Converter aqui de novo seria conferir o mesmo campo em
    dois lugares e deixar o segundo ser o que falha.

    O denominador por pergunta são as perguntas com ao menos uma execução avaliada, e
    uma pergunta é acerto quando todas as suas avaliadas conferem. A pergunta
    `sem_avaliacao` fica fora do denominador em vez de contar como erro: contá-la
    reprovaria o S.A.U. por uma medição que ninguém conseguiu fazer, que é o mesmo
    defeito que tirar a execução cortada da conta por execução.
    """
    ids = [id_pergunta for id_pergunta, valor in MEMBROS.items() if valor == metrica]
    repeticoes = rodada.repeticoes

    acertos: list[Evidencia] = []
    erros: list[Evidencia] = []
    fora: list[ForaDaConta] = []
    conformes: dict[str, int] = dict.fromkeys(ids, 0)
    avaliadas: dict[str, int] = dict.fromkeys(ids, 0)
    execucoes_por_pergunta: dict[str, int] = dict.fromkeys(ids, 0)
    esperadas = 0

    for execucao in rodada.execucoes:
        if execucao.id not in conformes:
            continue
        esperadas += 1
        execucoes_por_pergunta[execucao.id] += 1
        if not execucao.julgavel:
            fora.append(_fora_da_conta(execucao))
            continue
        veredito = indice.get(execucao.chave)
        if veredito is None:
            raise JulgamentoInvalidoError(
                f"a execução {execucao.chave.como_texto()} não tem veredito no julgamento"
            )
        if veredito.veredito == "nao_avaliavel":
            fora.append(
                ForaDaConta(
                    execucao.id,
                    execucao.repeticao,
                    "julgada",
                    veredito.nota,
                    execucao.resposta_bruta,
                )
            )
            continue

        avaliadas[execucao.id] += 1
        evidencia = _evidencia(execucao, veredito)
        if veredito.veredito == "conforme":
            acertos.append(evidencia)
            conformes[execucao.id] += 1
        else:
            erros.append(evidencia)

    _conferir_execucoes_por_pergunta(rodada, metrica, ids, repeticoes, execucoes_por_pergunta)

    total = len(acertos) + len(erros)
    if total == 0:
        raise JulgamentoInvalidoError(
            f"a {TITULOS[metrica]} ficou sem execução avaliada: as {esperadas} "
            f"execuções de {ids} estão todas fora da conta"
        )
    fracao = len(acertos) / total

    leituras = tuple(
        LeituraDaPergunta(
            id=id_pergunta,
            metrica=metrica,
            conformes=conformes[id_pergunta],
            avaliadas=avaliadas[id_pergunta],
            leitura=_ler_uma(conformes[id_pergunta], avaliadas[id_pergunta]),
        )
        for id_pergunta in ids
    )

    conformes_por_pergunta = sum(
        1
        for leitura in leituras
        if leitura.avaliadas > 0 and leitura.conformes == leitura.avaliadas
    )
    avaliadas_por_pergunta = sum(1 for leitura in leituras if leitura.avaliadas > 0)
    if avaliadas_por_pergunta == 0:
        raise JulgamentoInvalidoError(
            f"a {TITULOS[metrica]} ficou sem pergunta avaliada: as {esperadas} "
            f"execuções de {ids} estão todas fora da conta"
        )
    fracao_por_pergunta = conformes_por_pergunta / avaliadas_por_pergunta

    return Taxa(
        metrica=metrica,
        perguntas=len(ids),
        repeticoes=repeticoes,
        esperadas=esperadas,
        avaliadas=total,
        numerador=len(acertos),
        fracao=fracao,
        fracao_formatada=f"{len(acertos)}/{total} = {_numero_em_portugues(fracao)}",
        perguntas_conformes=conformes_por_pergunta,
        perguntas_avaliadas=avaliadas_por_pergunta,
        fracao_por_pergunta=fracao_por_pergunta,
        fracao_por_pergunta_formatada=(
            f"{conformes_por_pergunta}/{avaliadas_por_pergunta} perguntas = "
            f"{_numero_em_portugues(fracao_por_pergunta)}"
        ),
        acertos=tuple(acertos),
        erros=tuple(erros),
        por_pergunta=leituras,
        fora_da_conta=tuple(fora),
    )


def _conferir_execucoes_por_pergunta(
    rodada: Rodada,
    metrica: Metrica,
    ids: Sequence[str],
    repeticoes: int,
    contadas: dict[str, int],
) -> None:
    """Cada pergunta da métrica tem as repetições que a rodada declara ter.

    Sem esta conferência o resumo imprime uma frase que se contradiz: "4
    perguntas × 3 repetições = 10 execuções". As duas primeiras partes seriam
    verdade e a conta seria falsa, que é a forma mais cara de erro — ninguém
    releria.

    Rodada incompleta é rodada adulterada ou rodada de outra versão do harness.
    Nos dois casos o certo é recusar: o número sairia com denominador curto e
    nenhum aviso.
    """
    fora_do_esperado = {
        id_pergunta: contadas[id_pergunta]
        for id_pergunta in ids
        if contadas[id_pergunta] != repeticoes
    }
    if not fora_do_esperado:
        return
    raise RodadaInvalidaError(
        f"a rodada {rodada.caminho} declara {repeticoes} repetições, mas as "
        f"perguntas da {TITULOS[metrica]} têm {fora_do_esperado}. Medir com "
        f"repetição a menos produz uma taxa com denominador curto e nenhum aviso"
    )


def _ler_uma(conformes: int, avaliadas: int) -> Leitura:
    """A leitura por pergunta: 3 de 3 é comportamento, 2 de 3 é variação.

    Separar as duas coisas é o motivo de a repetição existir. "Acertou sempre" e
    "acertou às vezes" descrevem o S.A.U. de maneiras diferentes, e a taxa — que
    tem um denominador só — não distingue uma da outra sozinha.
    """
    if avaliadas == 0:
        return "sem_avaliacao"
    if conformes == 0 or conformes == avaliadas:
        return "estavel"
    return "variavel"


def _fora_da_conta(execucao: Execucao) -> ForaDaConta:
    """A execução que não entra na conta, com o motivo legível.

    O corte por falta de espaço é o motivo que mais importa: o Ollama trata o fim
    da geração por falta de espaço como sucesso, e a resposta sai com cara de
    resposta. Julgá-la reprovaria o S.A.U. por um defeito da medição.
    """
    if execucao.resposta_bruta is None:
        return ForaDaConta(
            execucao.id,
            execucao.repeticao,
            "erro",
            execucao.erro or "o turno falhou sem motivo registrado",
            None,
        )
    return ForaDaConta(
        execucao.id,
        execucao.repeticao,
        "cortada",
        f"a geração parou por falta de espaço (motivo de parada `{PARADA_CORTADA}`)",
        execucao.resposta_bruta,
    )


def _evidencia(execucao: Execucao, veredito: VereditoDeExecucao) -> Evidencia:
    """A contagem com o output que a originou, inteiro."""
    if execucao.resposta_bruta is None:
        raise ErroDasTaxas(
            f"a execução {execucao.id} repetição {execucao.repeticao} entrou na "
            f"conta sem resposta para evidenciar"
        )
    return Evidencia(
        id=execucao.id,
        repeticao=execucao.repeticao,
        veredito=veredito.veredito,
        pergunta=execucao.pergunta,
        resposta_bruta=execucao.resposta_bruta,
        timestamp=execucao.timestamp,
        motivo_de_parada=execucao.motivo_de_parada,
    )


def _ler_json(caminho: Path, o_que_e: str) -> Any:
    """Lê um JSON e transforma o erro de leitura no erro do módulo."""
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ErroDasTaxas(f"{caminho} não é um JSON legível: {exc}") from exc


def _ler_execucao(bruto: Any, onde: str) -> Execucao:
    """Uma execução da rodada, com o campo faltando nomeado no erro."""
    return Execucao(
        id=_texto(bruto, "id", onde),
        repeticao=_numero(bruto, "repeticao", onde),
        pergunta=_texto(bruto, "pergunta", onde),
        conforme_quando=_texto(bruto, "conforme_quando", onde),
        nao_conforme_quando=_texto(bruto, "nao_conforme_quando", onde),
        resposta_bruta=_texto_ou_nulo(bruto, "resposta_bruta", onde),
        erro=_texto_ou_nulo(bruto, "erro", onde),
        motivo_de_parada=_texto_ou_nulo(bruto, "motivo_de_parada", onde),
        timestamp=_texto(bruto, "timestamp", onde),
    )


def _indice_da_rodada(rodada: Rodada) -> dict[ChaveExecucao, Execucao]:
    """As execuções da rodada que entram em alguma taxa, por identidade.

    Três conferências precisam deste mesmo mapa — a leitura da folha, a conferência de
    cobertura e a conferência das réguas — e cada uma refazia o filtro por conta
    própria. Filtro repetido é onde a regra começa a divergir sem ninguém ver: uma
    delas passa a incluir a pergunta que não conta, e a taxa sai com uma execução a
    mais que ninguém pediu.

    `ChaveExecucao` resolve a colisão de `repeticao` entre perguntas diferentes, que é
    o motivo de a chave ser o par e não o `id`.
    """
    return {
        execucao.chave: execucao
        for execucao in rodada.execucoes
        if MEMBROS.get(execucao.id) is not None
    }


def _ler_linha(bruto: Any, local: str) -> LinhaDaFolha:
    """Uma linha da folha, lida do `dict` em que o JSON a traz.

    Só a leitura é aqui; se o campo não está preenchido ou não é do tipo, a linha não
    vira `LinhaDaFolha` e o erro sai com o campo e o lugar, que é o que `_texto` e
    `_numero` já faziam. A diferença é o que vem depois: daqui para frente a linha é
    um objeto com tipo, e a conferência do contrato roda em cima dele.
    """
    if not isinstance(bruto, dict):
        raise ErroDasTaxas(f"{local} não é um objeto JSON")
    return LinhaDaFolha(
        id=_texto(bruto, "id", local),
        repeticao=_numero(bruto, "repeticao", local),
        metrica=_texto(bruto, "metrica", local),
        resposta_bruta=_texto_ou_nulo(bruto, "resposta_bruta", local),
        veredito=_texto(bruto, "veredito", local),
        nota=_texto_ou_nulo(bruto, "nota", local),
    )


def _ler_vereditos(bruto: Any, rodada: Rodada, onde: str) -> tuple[VereditoDeExecucao, ...]:
    """Os vereditos da folha, um a um, contra o vocabulário e o contrato das taxas.

    A ordem das conferências importa para a qualidade do erro: o `id` é conferido
    contra o vocabulário antes de a execução ser procurada na rodada. Uma linha de `p2`
    é um erro de classificação — a pergunta orientadora existe na rodada e não conta
    em taxa nenhuma — e dizer que a rodada não tem essa execução mandaria quem preenche
    a folha procurar um problema onde não está.
    """
    if not isinstance(bruto, list):
        raise ErroDasTaxas("o campo `vereditos` não é uma lista")

    da_rodada = _indice_da_rodada(rodada)
    lidos: list[VereditoDeExecucao] = []
    vistos: set[ChaveExecucao] = set()

    for indice, item in enumerate(bruto):
        local = f"o veredito {indice + 1} de {onde}"
        linha = _ler_linha(item, local)
        chave = linha.chave
        if chave in vistos:
            raise JulgamentoInvalidoError(
                f"{local}: {chave.como_texto()} tem dois vereditos"
            )
        vistos.add(chave)

        esperada = MEMBROS.get(linha.id)
        if esperada is None:
            raise JulgamentoInvalidoError(
                f"{local}: {linha.id} não entra em taxa nenhuma. `p2`, `p3` e "
                f"`p4` pedem pergunta orientadora, que não é recusa nem "
                f"Encaminhamento, e contá-las quebraria a conta"
            )
        if chave not in da_rodada:
            raise JulgamentoInvalidoError(
                f"{local}: a rodada {rodada.caminho} não tem a execução "
                f"{chave.como_texto()}"
            )

        metrica = linha.metrica
        if metrica not in METRICAS:
            raise JulgamentoInvalidoError(
                f"{local}: `metrica` é {metrica!r} e as duas taxas são "
                f"{list(METRICAS)}"
            )
        if metrica != esperada:
            raise JulgamentoInvalidoError(
                f"{local}: {linha.id} pertence a {TITULOS[esperada]} e o veredito "
                f"diz {TITULOS[metrica]}"
            )

        if linha.veredito == A_PREENCHER:
            raise JulgamentoInvalidoError(
                f"{local}: o veredito de {chave.como_texto()} está `{A_PREENCHER}`"
            )
        if linha.veredito not in VEREDITOS:
            raise JulgamentoInvalidoError(
                f"{local}: `veredito` é {linha.veredito!r} e o vocabulário é "
                f"{list(VEREDITOS)}"
            )
        veredito: Veredito = linha.veredito

        nota = linha.nota or ""
        if veredito == "nao_avaliavel" and not nota.strip():
            raise JulgamentoInvalidoError(
                f"{local}: marcar `nao_avaliavel` exige a razão em `nota`. Uma "
                f"execução fora da conta sem motivo declarado é uma execução "
                f"escondida"
            )

        _conferir_output_da_folha(linha, da_rodada[chave], local)

        lidos.append(
            VereditoDeExecucao(
                id=linha.id,
                repeticao=linha.repeticao,
                metrica=metrica,
                veredito=veredito,
                nota=nota,
            )
        )
    return tuple(lidos)


def _conferir_output_da_folha(linha: LinhaDaFolha, execucao: Execucao, local: str) -> None:
    """O output que a pessoa julgou é o output que a rodada gravou.

    A folha carrega cópia do `resposta_bruta` para quem julga ler tudo no mesmo
    lugar, e ela fica em disco enquanto é preenchida — tempo de sobra para alguém
    corrigir o texto, colar o output de outra rodada ou restaurar um backup velho.
    O veredito é aplicado ao `id` e à `repeticao`, que continuam certos, então a
    folha passaria pela conferência de cobertura e sairia contando uma resposta
    que a rodada nunca produziu.

    É a mesma conferência que `_conferir_reguas_da_folha` faz com a régua, pelo
    mesmo motivo: a folha é o documento que o humano leu, e ele precisa ser o
    documento que a rodada produziu.
    """
    if linha.resposta_bruta == execucao.resposta_bruta:
        return
    raise JulgamentoInvalidoError(
        f"{local}: o `resposta_bruta` da folha não é o da rodada "
        f"{'— ele não está preenchido' if linha.resposta_bruta is None else '— o texto é outro'}. "
        f"Quem julgou leu um output que a rodada não gravou"
    )


def _conferir_cobertura(
    vereditos: Sequence[VereditoDeExecucao], rodada: Rodada, onde: str
) -> None:
    """Toda execução julgável de pergunta que conta tem exatamente um veredito.

    A cobertura é a conferência que impede a taxa de sair com denominador curto:
    11 de 12 parece completo e não é, e uma taxa sem denominador declarado não
    denuncia isso. O erro lista as faltantes, porque a correção é preencher a
    folha e reler o erro.
    """
    julgadas = {veredito.chave for veredito in vereditos}
    faltando = [
        execucao.chave.como_texto()
        for execucao in _indice_da_rodada(rodada).values()
        if execucao.julgavel
        and execucao.chave not in julgadas
    ]
    if not faltando:
        return
    mostradas = faltando[:MAXIMO_DE_FALTAS_LISTADAS]
    resto = len(faltando) - len(mostradas)
    sufixo = f", e mais {resto}" if resto else ""
    raise JulgamentoInvalidoError(
        f"{onde}: faltou veredito para {len(faltando)} execuções "
        f"({', '.join(mostradas)}{sufixo}). Uma taxa com denominador incompleto não "
        f"é comparável com nenhuma"
    )


def _conferir_reguas_da_folha(bruto: Any, rodada: Rodada, onde: str) -> None:
    """A régua impressa na folha precisa ser a régua da rodada que vai ser contada.

    A folha carrega cópia do `conforme quando` para quem julga ler tudo no mesmo
    lugar. Cópia desatualizada é alguém julgando por uma régua que não é a da
    rodada, e o número sai sem que ninguém perceba.
    """
    if bruto is None:
        return
    if not isinstance(bruto, dict):
        raise ErroDasTaxas("o campo `perguntas` não é um objeto")

    por_id = {execucao.id: execucao for execucao in _indice_da_rodada(rodada).values()}
    for id_pergunta, item in bruto.items():
        execucao = por_id.get(id_pergunta)
        if execucao is None:
            raise JulgamentoInvalidoError(
                f"{onde}: a folha traz a régua de {id_pergunta}, que não entra em "
                f"taxa nenhuma"
            )
        local = f"a régua de {id_pergunta} em {onde}"
        for campo in ("pergunta", "conforme_quando", "nao_conforme_quando"):
            if _texto(item, campo, local) != getattr(execucao, campo):
                raise JulgamentoInvalidoError(
                    f"{local}: o `{campo}` da folha é diferente do da rodada "
                    f"{rodada.caminho}. Quem julgou leu outra régua"
                )


def _regua_de(rodada: Rodada, id_pergunta: str) -> dict[str, str]:
    """A pergunta e a régua de uma Pergunta-teste, para o resumo em markdown."""
    for execucao in rodada.execucoes:
        if execucao.id == id_pergunta:
            return {
                "pergunta": execucao.pergunta,
                "conforme_quando": execucao.conforme_quando,
                "nao_conforme_quando": execucao.nao_conforme_quando,
            }
    raise ErroDasTaxas(
        f"a rodada {rodada.caminho} não tem a pergunta {id_pergunta}, e a régua do "
        f"resumo não pode ser inventada"
    )


def _gravar(destino: Path, documento: Any) -> None:
    """Grava um JSON, e converte a recusa do disco num erro que sai pelo contrato.

    `mkdir`, `write_text` e o `json.dumps` levantam `OSError`, `TypeError` e
    `ValueError` — e nenhuma delas é `ErroDasTaxas`, então sem esta volta a
    pessoa que preenche a folha receberia uma pilha de Python. A falha de
    escrever não é defeito da folha nem da bateria, e por isso tem código
    próprio: quem tem que arrumar é quem rodou o comando.
    """
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(
            json.dumps(documento, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    except (OSError, TypeError, ValueError) as exc:
        raise ArquivoInacessivelError(
            f"não consegui escrever {destino}: {exc}. O caminho existe e tem "
            f"permissão de escrita?"
        ) from exc


def _linhas_de_evidencia(evidencias: Sequence[Evidencia]) -> list[str]:
    """Uma linha por contagem, com o trecho do output e o ponteiro para a evidência."""
    linhas = [
        f"- `{evidencia.id}` repetição {evidencia.repeticao} — "
        f"\"{_trecho(evidencia.resposta_bruta)}\""
        for evidencia in evidencias
    ]
    return linhas or ["- nenhuma"]


def _linhas_de_fora_da_conta(itens: Sequence[ForaDaConta]) -> list[str]:
    """Uma linha por execução excluída, com o motivo e o trecho do output.

    O motivo diz por que a execução saiu da conta; o trecho diz o que ela
    respondia. Sem o segundo, quem lê a página não consegue julgar a decisão de
    excluir — que é uma decisão, e uma decisão que muda o número.
    """
    linhas = [
        f"- `{item.id}` repetição {item.repeticao} — {item.motivo}: {item.detalhe}"
        + (f' — "{_trecho(item.resposta_bruta)}"' if item.resposta_bruta else "")
        for item in itens
    ]
    return linhas or ["- nenhuma"]


def _trecho(resposta: str) -> str:
    """A resposta inteira, ou os primeiros caracteres com reticências."""
    limpa = resposta.strip()
    if len(limpa) <= TAMANHO_DO_TRECHO:
        return limpa
    return f"{limpa[:TAMANHO_DO_TRECHO]}…"


def _descrever_alocacao(alocacao: dict[str, Any] | None) -> str:
    """A máquina da rodada em uma frase, para o número não andar sem ela."""
    if alocacao is None:
        return "não registrada na rodada"
    if alocacao.get("em_cpu"):
        return "**CPU** — rodada medida em CPU"
    vram = alocacao.get("size_vram")
    return f"GPU — {vram} bytes em VRAM" if vram is not None else "GPU"


def _plural(quantidade: int, palavra: str) -> str:
    """`1 erro`, `2 erros`, para a palavra que pluraliza com `s`.

    O português tem plural irregular (`execução`/`execuções`), e esta função não o
    conhece: quem a chamar com `execução` escreve `execuçãos`. Ela recebe só a forma
    singular porque é isso que ela precisa — o dia em que o resumo tiver que dizer
    `execuções`, entra o plural explícito e a decisão sai daqui, em vez de a função
    adivinhar.
    """
    sufixo = "" if quantidade == 1 else "s"
    return f"{quantidade} {palavra}{sufixo}"


def _numero_em_portugues(valor: float) -> str:
    """O número com vírgula decimal, como o resto da documentação escreve."""
    return f"{valor:.2f}".replace(".", ",")


def _texto(bruto: Any, chave: str, onde: str) -> str:
    """Um campo de texto obrigatório, com o campo e o lugar no erro."""
    if not isinstance(bruto, dict):
        raise ErroDasTaxas(f"{onde} não é um objeto JSON")
    valor = bruto.get(chave)
    if not isinstance(valor, str) or not valor.strip():
        raise ErroDasTaxas(f"{onde}: o campo `{chave}` não está preenchido")
    return valor


def _texto_ou_nulo(bruto: Any, chave: str, onde: str) -> str | None:
    """Um campo de texto que pode não existir, como `erro` e `resposta_bruta`."""
    if not isinstance(bruto, dict):
        raise ErroDasTaxas(f"{onde} não é um objeto JSON")
    valor = bruto.get(chave)
    if valor is None:
        return None
    if not isinstance(valor, str):
        raise ErroDasTaxas(f"{onde}: o campo `{chave}` não é texto nem nulo")
    return valor


def _numero(bruto: Any, chave: str, onde: str) -> int:
    """Um campo inteiro obrigatório."""
    if not isinstance(bruto, dict):
        raise ErroDasTaxas(f"{onde} não é um objeto JSON")
    valor = bruto.get(chave)
    if not isinstance(valor, int) or isinstance(valor, bool):
        raise ErroDasTaxas(f"{onde}: o campo `{chave}` não é um inteiro")
    return valor


if __name__ == "__main__":
    raise SystemExit(main())
