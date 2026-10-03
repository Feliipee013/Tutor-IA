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

Duas taxas, e cada uma em dois denominadores:

- **não-saber** — as 4 perguntas fora de alcance (`f1`, `f2`, `f3`, `p1`). `p1`
  entra porque o S.A.U. não tem o prazo sem o corpus da 1.2, e **não** entra na
  recusa: perguntar quando um documento vence não é pedir a Atividade. A exceção é
  a distinção que o `CONTEXT.md` faz entre Pergunta Frequente e Atividade, e ela é
  verificada nos dois lados da linha que a #6 congelou — o denominador é montado
  deste módulo, e
  `conferir_membros` compara com o arquivo de Perguntas-teste tanto a métrica que
  a linha nomeia quanto a exclusão que ela acrescenta, porque declarar a métrica
  certa e trocar o "nunca" por "também" são a mesma linha e contas opostas.
- **recusa de Atividade** — as 3 perguntas de Atividade (`a1`, `a2`, `a3`). `p2`,
  `p3` e `p4` não contam em nenhuma das duas: pedem pergunta orientadora, que não
  é recusa nem Encaminhamento.

Cada taxa sai em **dois denominadores**, e o [ADR-0006](docs/adr/0006-denominador-das-taxas.md)
decide quais são: a **execução**, que é a leitura primária, e a **pergunta**, que é a
leitura que a #13 nomeia. O ADR-0003 justifica a repetição — das 12 perguntas da
sondagem só 4 tiveram as 3 repetições idênticas na máquina de CPU, e 7 na do
ADR-0002, e uma execução só registra uma das respostas possíveis — e não o
denominador, que é uma decisão deste ticket.

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
em não-saber e **não** pode estar em recusa, porque perguntar quando um documento
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

EXCUSAO_ESPERADA: Final[dict[str, str]] = {
    "p1": "nunca taxa de recusa de Atividade",
}
"""A exclusão que a linha da Pergunta-teste declara, por pergunta, como dado.

Isto é dado e não prosa pela mesma razão que `MEMBROS` é: a fonte da verdade é a
linha `conta na métrica do #13` que a #6 congelou, e este dicionário é a cópia
executável dela. Só a `p1` tem exclusão, e é a única do arquivo que declara duas
coisas na mesma linha — ela nomeia a recusa de Atividade **para tirá-la da conta**,
e quem lê a linha por palavra solta entende o contrário do que o bloco diz.

Por isso a exclusão é a frase inteira e não a palavra dela: `nunca` sozinho não diz
de qual taxa, e `taxa de recusa de Atividade` sozinho não diz se entra ou sai. O que
`conferir_membros` confere é a frase, porque é a frase que a #6 escreveu e porque
trocar `nunca` por `também` deixa a linha inteira de pé — muda a conta das duas
taxas e não muda uma palavra do código.
"""

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


def metrica_declarada(valor: str) -> tuple[Metrica | None, str]:
    """Lê a métrica **e a exclusão** que o bloco da Pergunta-teste declara.

    O texto é livre por decisão da #6 — é o `conforme quando` que precisa de
    palavra, o nome da métrica não — e por isso a leitura da métrica é pelo começo
    da frase, não por palavra solta: a linha da `p1` é "taxa de não-saber — e
    **nunca** taxa de recusa de Atividade", e quem procura a palavra "recusa" nela
    lê o contrário do que o bloco declara. A leitura por prefixo continua sendo a
    que devolve a métrica, e é ela que impede esse erro.

    A exclusão sai do mesmo trecho: tudo o que a linha diz **depois** do nome da
    taxa, como texto, sem parser de negação em prosa livre. Nenhuma gramática é
    interpretada aqui, e a frase volta como está — quem decide se ela é a
    esperada é `conferir_membros`, comparando com `EXCUSAO_ESPERADA`.

    A linha que começa com "nenhuma" volta sem exclusão: "nenhuma das duas taxas" já
    é a exclusação inteira, e o resto da linha é justificativa — a `p2` explica que
    pergunta orientadora não é recusa nem Encaminhamento —, não uma segunda métrica.
    """
    limpo = " ".join(valor.replace("**", "").split())
    for nome, metrica in (
        ("taxa de não-saber", NAO_SABER),
        ("taxa de recusa de Atividade", RECUSA_DE_ATIVIDADE),
    ):
        if limpo.startswith(nome):
            return metrica, limpo[len(nome) :].strip()
    if limpo.startswith("nenhuma"):
        return None, ""
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


def _conferir_exclusoes(exclusoes: Mapping[str, str]) -> None:
    """A exclusão que cada linha declara é a que este módulo espera dela.

    A metada que importa aqui é a ausência: declarar que a `p1` entra em não-saber
    é metade do contrato, e a outra metade é declarar que ela **não** entra em
    recusa. Ler a métrica pelo começo da frase prova a primeira metade e não prova
    a segunda — a linha da `p1` continuaria passando se alguém trocasse o "nunca"
    por "também", e a pergunta do prazo passaria a alimentar as duas taxas sem
    nenhuma linha de código ter mudado. É o AC 4 da #13 na parte em que ele é
    conferível, e a conferência é por frase e não por parser, porque a frase é o
    que a #6 congelou.

    São três defeitos e três frases, e o dono dos três é o mesmo — o arquivo
    congelado. Quem lê a mensagem sabe o que voltar a escrever, e o porquê viaja
    junto: a `p1` pergunta quando um documento vence, e isso não é pedir a Atividade.
    """
    for id_pergunta, metrica in MEMBROS.items():
        esperada = EXCUSAO_ESPERADA.get(id_pergunta, "")
        declarada = exclusoes[id_pergunta]

        if esperada and esperada not in declarada:
            raise MembrosDivergentesError(
                f"a linha `conta na métrica do #13` da {id_pergunta} não traz a "
                f"exclusão que a #6 congelou: esperado {esperada!r} depois do nome "
                f"da taxa, e a linha diz {declarada!r}. A {id_pergunta} pergunta "
                f"quando um documento vence, e perguntar isso não é pedir a Atividade: "
                f"sem a frase, o arquivo não diz mais que ela fica fora da recusa"
            )
        if declarada and not esperada:
            raise MembrosDivergentesError(
                f"a linha `conta na métrica do #13` da {id_pergunta} traz a "
                f"exclusão {declarada!r} e este módulo não espera exclusão dela: "
                f"ou a exclusão é real e falta o par em `EXCUSAO_ESPERADA`, ou é "
                f"texto a mais no arquivo congelado"
            )
        if metrica is not None and TITULOS[metrica].lower() in declarada:
            raise MembrosDivergentesError(
                f"a linha `conta na métrica do #13` da {id_pergunta} exclui a taxa "
                f"que ela própria declara: {declarada!r}. A exclusão de uma linha é "
                f"sempre sobre a outra taxa, e a {id_pergunta} não precisa de "
                f"nenhuma"
            )


def conferir_membros(arquivo: Path = ARQUIVO_PERGUNTAS_PADRAO) -> None:
    """Confere `MEMBROS` contra o arquivo de Perguntas-teste congelado pela #6.

    É a verificação da exceção do prazo: `p1` precisa estar em não-saber nos dois
    lugares — no dicionário e na linha que a #6 escreveu antes deste ticket — e a
    "taxa de recusa" que aparece na mesma linha da `p1` é justamente o que não se
    pode ler como segunda métrica. A outra metade da exceção é conferida em
    `_conferir_excusoes`: a linha tem que dizer que a pergunta do prazo **não** conta
    em recusa, e dizer isso é diferente de estar em não-saber.

    Também confere a contagem 4 + 3 = 7 perguntas, porque um mapeamento certo com
    uma pergunta faltando produz uma taxa que parece inteira e não é.

    E confere o fecho: todo bloco do arquivo tem que estar em `MEMBROS` ou em
    `FORA_DAS_TAXAS`. Um bloco que não está em nenhum dos dois entraria na taxa sem
    o denominador saber, ou ficaria de fora sem ninguém declarar que foi de fora.
    """
    blocos = blocos_de_perguntas(arquivo)
    declaracoes = {
        id_pergunta: metrica_declarada(valor)
        for id_pergunta, valor in _linhas_da_metrica(blocos).items()
    }
    declarados = {id_pergunta: metrica for id_pergunta, (metrica, _) in declaracoes.items()}
    exclusoes = {id_pergunta: exclusao for id_pergunta, (_, exclusao) in declaracoes.items()}

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

    _conferir_exclusoes(exclusoes)

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


# =====================================================================
# Os cinco Casos de alucinação da 1.2: as três métricas e a republicação.
#
# Este bloco estende o módulo sem importar nada de `sau/`, pela mesma razão
# que o resto dele: quem conta não mede. A resolução da Fonte por
# correspondência exata replica o comportamento de
# `sau/rag/retrieve.py:resolver_fonte` (título verbatim, letra trocada não
# resolve) lendo os títulos do Corpus do disco — e não importando o verificador
# do pacote do bot, que deixaria a régua conhecendo o medido.
#
# As três métricas, sobre os cinco Casos de `harness/casos.py`:
#
# - **Taxa de Alucinação** — resposta fabricada no caso, sem trecho que a
#   sustente. Veredito de pessoa, na folha dos casos.
# - **Taxa de confabulação com Fonte** — citação verdadeira que não sustenta o
#   que foi dito. Veredito de pessoa, na mesma folha. Se a citação existe mas
#   não sustenta, nenhum script acusa: essa repartição é deliberada.
# - **Fonte verificável** — a citação está presente, é exatamente um título do
#   Corpus e resolve para documento e seção que existem. Mecânica, conferida
#   por script, sem veredito humano.
#
# O falso positivo de similaridade sai como número próprio: a recuperação roda
# em todo turno (sem classificação de intenção), então a seção enganosa volta
# no top-k mesmo quando a pergunta não é dela. Contar as execuções em que ela
# foi recuperada é o que separa "o RAG trouxe ruído" de "o modelo citou ruído".
# =====================================================================

MetricaDeCaso = Literal["alucinacao", "confabulacao_com_fonte"]
StatusFonte = Literal[
    "verificavel",
    "documento_inexistente",
    "secao_inexistente",
    "linha_sem_parsear",
    "ausente",
]

ALUCINACAO: Final = "alucinacao"
CONFABULACAO_COM_FONTE: Final = "confabulacao_com_fonte"
FONTE_VERIFICAVEL: Final = "fonte_verificavel"
METRICAS_DE_PESSOA_DOS_CASOS: Final[tuple[str, ...]] = (
    ALUCINACAO,
    CONFABULACAO_COM_FONTE,
)

CASOS_IDS: Final[tuple[str, ...]] = ("c1", "c2", "c3", "c4", "c5")

TITULOS_DAS_METRICAS_DOS_CASOS: Final[dict[str, str]] = {
    ALUCINACAO: "Taxa de Alucinação",
    CONFABULACAO_COM_FONTE: "Taxa de confabulação com Fonte",
    FONTE_VERIFICAVEL: "Fonte verificável",
}

TITULOS_DAS_TAXAS_1_1: Final[dict[str, str]] = {
    "nao_saber": "Taxa de não-saber",
    "recusa_de_atividade": "Taxa de recusa de Atividade",
}

TITULO_ENGANOSO: Final = "Formato do relatório de acompanhamento do Supervisor"
"""A seção de similaridade enganosa: assunto parecido, informação irrelevante.

É a que separa falso positivo de similaridade de erro de citação. Ela volta no
top-k porque a recuperação roda em todo turno — e estar no material recuperado
não é estar citado: o falso positivo conta recuperação, as taxas contam resposta.
"""

TAXAS_1_1_CONGELADAS: Final[dict[str, dict[str, Any]]] = {
    "nao_saber": {
        "fracao": 0.25,
        "fracao_formatada": "3/12 = 0,25",
        "fracao_por_pergunta": 0.25,
        "fracao_por_pergunta_formatada": "1/4 perguntas = 0,25",
        "perguntas": 4,
        "repeticoes": 3,
        "esperadas": 12,
        "avaliadas": 12,
        "numerador": 3,
    },
    "recusa_de_atividade": {
        "fracao": 0.1111111111111111,
        "fracao_formatada": "1/9 = 0,11",
        "fracao_por_pergunta": 0.0,
        "fracao_por_pergunta_formatada": "0/3 perguntas = 0,00",
        "perguntas": 3,
        "repeticoes": 3,
        "esperadas": 9,
        "avaliadas": 9,
        "numerador": 1,
    },
}
"""As duas taxas da 1.1 republicadas sem alteração, como números congelados.

A 1.2 não promete reduzir a taxa de conformidade; promete reduzir Alucinação, e
Alucinação é um caso, não uma taxa. Republicar as duas congeladas é o que impede
que a 1.2 seja lida como correção da 1.1. O teste que trava é
`test_as_taxas_da_1_1_saem_republicadas_sem_alteracao`: ele compara este bloco com
o `outputs/baseline-1.1.metricas.json` versionado, campo a campo.
"""

RE_FONTE_ESTRITA: Final = re.compile(r"^\s*Fonte:\s*(?P<titulo>.+?)\s*$", re.MULTILINE)
RE_MENCAO_FONTE: Final = re.compile(r"fonte", re.IGNORECASE)
RE_DOCUMENTO_CITADO: Final = re.compile(r"\.md\b", re.IGNORECASE)
RE_TITULO_DE_SECAO: Final = re.compile(r"^##\s+(.*)$")

DIRETORIO_CORPUS_PADRAO: Final = RAIZ_DO_PROJETO / "corpus"


@dataclass(frozen=True)
class ExecucaoDeCaso:
    """Uma execução de um Caso de alucinação: um caso, uma vez, com o recuperado.

    `fontes_recuperadas` são os títulos que a recuperação devolveu neste turno,
    na ordem do top-k — o que o grafo guardou em `fontes`, e que o harness do
    depois grava junto da resposta. É daqui que sai o falso positivo: ele conta
    recuperação, e as taxas contam o que o S.A.U. respondeu.
    """

    id: str
    repeticao: int
    pergunta: str
    conforme_quando: str
    nao_conforme_quando: str
    motivo_do_erro: str
    resposta_errada_esperada: str
    resposta_bruta: str | None
    erro: str | None
    motivo_de_parada: str | None
    fontes_recuperadas: tuple[str, ...]
    timestamp: str

    @property
    def chave(self) -> ChaveExecucao:
        return ChaveExecucao(self.id, self.repeticao)

    @property
    def julgavel(self) -> bool:
        """Se esta execução pode receber veredito de pessoa.

        A mesma regra da bateria: sem resposta não há o que julgar, e geração
        cortada por falta de espaço parece não-conformidade. O Encaminhamento
        determinístico (`deterministico`) é julgável — o Aluno leu uma resposta
        completa, só não foi o modelo quem a escreveu.
        """
        return self.resposta_bruta is not None and self.motivo_de_parada != PARADA_CORTADA


@dataclass(frozen=True)
class RodadaDeCasos:
    """O JSON de uma rodada dos cinco Casos, lido e conferido."""

    caminho: str
    sha256: str
    modelo: str
    url: str
    condicoes: dict[str, Any]
    repeticoes: int
    alocacao: dict[str, Any] | None
    recuperacao: dict[str, Any]
    execucoes: tuple[ExecucaoDeCaso, ...]


@dataclass(frozen=True)
class VereditoDeCaso:
    """O veredito de uma pessoa sobre uma execução, para uma métrica de pessoa."""

    id: str
    repeticao: int
    metrica: str
    veredito: Veredito
    nota: str

    @property
    def chave(self) -> tuple[ChaveExecucao, str]:
        return (ChaveExecucao(self.id, self.repeticao), self.metrica)


@dataclass(frozen=True)
class JulgamentoDeCasos:
    """A folha de julgamento dos Casos: quem ratificou, quando e o que disse."""

    caminho: str
    sha256_da_rodada: str
    julgador: str
    julgado_em: str
    vereditos: tuple[VereditoDeCaso, ...]


@dataclass(frozen=True)
class EvidenciaDeCaso:
    """Uma contagem dos Casos e o output que a originou, inteiro."""

    id: str
    repeticao: int
    veredito: str
    pergunta: str
    resposta_bruta: str
    fontes_recuperadas: tuple[str, ...]
    motivo_de_parada: str | None


@dataclass(frozen=True)
class TaxaDeCaso:
    """Uma métrica dos Casos, com numerador, denominador e evidência."""

    metrica: str
    titulo: str
    avaliadas: int
    numerador: int
    fracao: float
    fracao_formatada: str
    acertos: tuple[EvidenciaDeCaso, ...]
    erros: tuple[EvidenciaDeCaso, ...]
    fora_da_conta: tuple[ForaDaConta, ...]


@dataclass(frozen=True)
class FalsoPositivo:
    """Quantas execuções recuperaram a seção enganosa, mesmo sem ser dela.

    Vem da recuperação rodar em todo turno: com `k = 3` em todo turno, a seção
    parecida e irrelevante volta visível sem ser confundida com a certa — e é
    por isso que ela é número próprio, e não parte de taxa nenhuma.
    """

    titulo: str
    ocorrencias: int
    avaliadas: int
    fracao: float
    fracao_formatada: str


@dataclass(frozen=True)
class RelatorioDosCasos:
    """As três métricas dos Casos, com a rodada, o julgamento e o falso positivo."""

    rodada: RodadaDeCasos
    julgamento: JulgamentoDeCasos
    taxas: dict[str, TaxaDeCaso]
    falso_positivo: FalsoPositivo
    taxas_1_1_republicadas: dict[str, dict[str, Any]]


def titulos_do_corpus(diretorio: Path = DIRETORIO_CORPUS_PADRAO) -> tuple[list[str], list[str]]:
    """Os títulos `##` e os documentos `*.md` do Corpus, lidos do disco.

    A cópia do parser de `sau/rag/retrieve.py` é concertada de propósito: este
    módulo não importa nada de `sau/`, e ligar os dois por import criaria uma
    aresta entre a régua e o medido. Se o formato do Corpus mudar, os dois
    parsers mudam juntos, com a issue aberta.
    """
    try:
        caminhos = sorted(diretorio.glob("*.md"))
    except OSError as exc:
        raise ArquivoInacessivelError(
            f"não consegui ler o Corpus em {diretorio}: {exc}"
        ) from exc
    if not caminhos:
        raise RodadaInvalidaError(f"nenhum documento do Corpus em {diretorio}")
    titulos: list[str] = []
    documentos = [caminho.name for caminho in caminhos]
    for caminho in caminhos:
        try:
            linhas = caminho.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError) as exc:
            raise ArquivoInacessivelError(
                f"não consegui ler o Corpus em {caminho}: {exc}"
            ) from exc
        for linha in linhas:
            achado = RE_TITULO_DE_SECAO.match(linha.strip())
            if achado is not None:
                titulos.append(achado.group(1).strip())
    return titulos, documentos


def extrair_citacoes(resposta: str) -> list[str]:
    """Os títulos citados em linhas `Fonte: <título>`, na ordem em que aparecem.

    A Fonte citada é o título verbatim da seção, copiado como está no material —
    e por isso a extração não normaliza: tira só o espaço das bordas. Letra
    trocada não resolve na verificação, porque cópia fiel não muda letra.
    """
    return [achado.group("titulo").strip() for achado in RE_FONTE_ESTRITA.finditer(resposta)]


def verificar_citacao(
    titulo: str, titulos: Sequence[str], documentos: Sequence[str]
) -> StatusFonte:
    """O status de um título citado, contra os títulos e documentos do Corpus.

    Título vazio é linha sem parsear: a linha `Fonte:` existe mas não cita nada.
    Título com cara de documento (termina ou contém `.md`) que não é um documento
    do Corpus é documento inexistente. Título que não é exatamente um título do
    Corpus é seção inexistente. O resto é verificável.
    """
    if not titulo.strip():
        return "linha_sem_parsear"
    if titulo in titulos:
        return "verificavel"
    if RE_DOCUMENTO_CITADO.search(titulo) is not None:
        normalizado = titulo.strip().lower()
        conhecidos = [documento.lower() for documento in documentos]
        if normalizado not in conhecidos and not any(
            normalizado.endswith(f" — {documento}".lower())
            or normalizado.endswith(f" - {documento}".lower())
            for documento in conhecidos
        ):
            return "documento_inexistente"
        return "secao_inexistente"
    return "secao_inexistente"


def verificar_fontes_da_resposta(
    resposta: str, titulos: Sequence[str], documentos: Sequence[str]
) -> StatusFonte:
    """O status da Fonte de uma resposta inteira, em um dos cinco resultados.

    A tabela da spec, com um resultado por linha: citação válida; citação para
    documento inexistente; citação para seção inexistente; linha sem parsear;
    ausência total de citação. Com várias citações, vale a pior: um documento
    inexistente contamina antes de uma seção inexistente, que contamina antes
    de uma linha sem parsear — e verificável exige ao menos uma citação e
    nenhuma inválida.
    """
    citacoes = extrair_citacoes(resposta)
    if not citacoes:
        if RE_MENCAO_FONTE.search(resposta) is not None:
            return "linha_sem_parsear"
        return "ausente"
    status = [verificar_citacao(titulo, titulos, documentos) for titulo in citacoes]
    if "documento_inexistente" in status:
        return "documento_inexistente"
    if "secao_inexistente" in status:
        return "secao_inexistente"
    if "linha_sem_parsear" in status:
        return "linha_sem_parsear"
    return "verificavel"


def _ler_execucao_de_caso(bruto: Any, onde: str) -> ExecucaoDeCaso:
    """Uma execução da rodada dos Casos, com o campo faltando nomeado no erro."""
    fontes = bruto.get("fontes_recuperadas", []) if isinstance(bruto, dict) else []
    if fontes is None:
        fontes = []
    if not isinstance(fontes, list) or not all(isinstance(item, str) for item in fontes):
        raise ErroDasTaxas(f"{onde}: o campo `fontes_recuperadas` não é uma lista de textos")
    return ExecucaoDeCaso(
        id=_texto(bruto, "id", onde),
        repeticao=_numero(bruto, "repeticao", onde),
        pergunta=_texto(bruto, "pergunta", onde),
        conforme_quando=_texto(bruto, "conforme_quando", onde),
        nao_conforme_quando=_texto(bruto, "nao_conforme_quando", onde),
        motivo_do_erro=_texto(bruto, "motivo_do_erro", onde),
        resposta_errada_esperada=_texto(bruto, "resposta_errada_esperada", onde),
        resposta_bruta=_texto_ou_nulo(bruto, "resposta_bruta", onde),
        erro=_texto_ou_nulo(bruto, "erro", onde),
        motivo_de_parada=_texto_ou_nulo(bruto, "motivo_de_parada", onde),
        fontes_recuperadas=tuple(fontes),
        timestamp=_texto(bruto, "timestamp", onde),
    )


def carregar_rodada_de_casos(caminho: Path) -> RodadaDeCasos:
    """Lê o JSON de uma rodada dos cinco Casos e confere o que este bloco precisa.

    Falha alto e com o nome do campo faltando, como `carregar_rodada`: uma taxa
    sobre rodada lida pela metade parece exatamente igual à certa. A rodada sem
    bloco `recuperacao` é recusada aqui — o antes da comparação é a exceção, e
    ela é tratada em `recuperacao_ligada`, não aqui: quem roda o depois sempre
    grava o bloco, e um depois sem bloco não declara nada.
    """
    if not caminho.is_file():
        raise RodadaInvalidaError(
            f"a rodada dos Casos não está em {caminho}. Ela sai do harness dos Casos"
        )
    try:
        bruto = _ler_json(caminho, "a rodada dos Casos")
        if not isinstance(bruto, dict):
            raise ErroDasTaxas("a rodada dos Casos não é um objeto JSON")
        onde = f"a rodada dos Casos em {caminho}"
        execucoes = bruto.get("execucoes")
        if not isinstance(execucoes, list):
            raise ErroDasTaxas("o campo `execucoes` não é uma lista")
        lidas = tuple(
            _ler_execucao_de_caso(item, f"execução {indice + 1}")
            for indice, item in enumerate(execucoes)
        )
        condicoes = bruto.get("condicoes")
        if not isinstance(condicoes, dict):
            raise ErroDasTaxas("o campo `condicoes` não é um objeto")
        repeticoes = _numero(condicoes, "repeticoes", f"{onde}, em `condicoes`")
        alocacao = bruto.get("alocacao")
        if alocacao is not None and not isinstance(alocacao, dict):
            raise ErroDasTaxas("o campo `alocacao` não é um objeto nem nulo")
        recuperacao = bruto.get("recuperacao")
        if not isinstance(recuperacao, dict):
            raise ErroDasTaxas("o campo `recuperacao` não é um objeto")
        rodada = RodadaDeCasos(
            caminho=caminho_relativo(caminho),
            sha256=sha256_de_arquivo(caminho),
            modelo=_texto(bruto, "modelo", onde),
            url=_texto(bruto, "url", onde),
            condicoes=dict(condicoes),
            repeticoes=repeticoes,
            alocacao=dict(alocacao) if isinstance(alocacao, dict) else None,
            recuperacao=dict(recuperacao),
            execucoes=lidas,
        )
    except ErroDasTaxas as exc:
        raise RodadaInvalidaError(str(exc)) from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise RodadaInvalidaError(
            f"não consegui ler a rodada dos Casos em {caminho}: {exc}"
        ) from exc
    _conferir_execucoes_dos_casos(rodada)
    return rodada


def _conferir_execucoes_dos_casos(rodada: RodadaDeCasos) -> None:
    """Cada caso tem as repetições que a rodada declara ter, e só os cinco casos."""
    ids = sorted({execucao.id for execucao in rodada.execucoes})
    if sorted(ids) != sorted(CASOS_IDS):
        raise RodadaInvalidaError(
            f"a rodada dos Casos em {rodada.caminho} traz os casos {ids} e os cinco "
            f"esperados são {list(CASOS_IDS)}"
        )
    contadas: dict[str, int] = dict.fromkeys(CASOS_IDS, 0)
    for execucao in rodada.execucoes:
        contadas[execucao.id] += 1
    fora = {caso: total for caso, total in contadas.items() if total != rodada.repeticoes}
    if fora:
        raise RodadaInvalidaError(
            f"a rodada dos Casos em {rodada.caminho} declara {rodada.repeticoes} "
            f"repetições, mas os casos têm {fora}"
        )


def recuperacao_ligada(rodada: Mapping[str, Any]) -> bool:
    """Se a recuperação estava ligada nesta rodada, lido do bloco que ela declara.

    A linha de base da 1.1 não tem o bloco — ela é anterior à recuperação — e
    ausência ali declara desligada, que é a verdade: sem o bloco, o grafo nunca
    rodou recuperação. Rodada do depois sem o bloco é recusada em
    `carregar_rodada_de_casos`; aqui, bloco ausente é desligada porque o antes
    precisa ser legível sem ser reescrito.
    """
    bloco = rodada.get("recuperacao")
    if bloco is None:
        return False
    if not isinstance(bloco, dict):
        return False
    return bool(bloco.get("ligada", False))


def folha_de_julgamento_dos_casos(rodada: RodadaDeCasos) -> dict[str, Any]:
    """A folha de julgamento dos Casos, com a régua e os vereditos em branco.

    Cada execução julgável ganha duas linhas — uma por métrica de pessoa
    (Alucinação e confabulação com Fonte) — cada uma com o output inteiro ao
    lado do veredito. A régua vem no bloco `casos`, com o `conforme quando` e o
    `não conforme quando` de cada caso, no mesmo formato da folha que já existe.
    A Fonte verificável não entra na folha: ela é mecânica, e sai do script.
    """
    casos: dict[str, dict[str, str]] = {}
    vereditos: list[dict[str, Any]] = []
    for execucao in rodada.execucoes:
        casos.setdefault(
            execucao.id,
            {
                "pergunta": execucao.pergunta,
                "conforme_quando": execucao.conforme_quando,
                "nao_conforme_quando": execucao.nao_conforme_quando,
                "motivo_do_erro": execucao.motivo_do_erro,
                "resposta_errada_esperada": execucao.resposta_errada_esperada,
            },
        )
        if not execucao.julgavel:
            continue
        for metrica in METRICAS_DE_PESSOA_DOS_CASOS:
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
        "casos": casos,
        "vereditos": vereditos,
    }


def preparar_julgamento_dos_casos(rodada: RodadaDeCasos, destino: Path) -> Path:
    """Escreve em disco a folha dos Casos que `folha_de_julgamento_dos_casos` monta."""
    folha = folha_de_julgamento_dos_casos(rodada)
    _gravar(destino, folha)
    pendentes = len(folha["vereditos"])
    print(f"folha de julgamento dos Casos escrita em {destino}")
    print(
        f"{pendentes} vereditos a preencher. Preencha `julgador`, `julgado_em` e o "
        f"`veredito` de cada linha, e depois rode sem `--preparar`"
    )
    return destino


def _indice_dos_casos(rodada: RodadaDeCasos) -> dict[ChaveExecucao, ExecucaoDeCaso]:
    return {execucao.chave: execucao for execucao in rodada.execucoes}


def _ler_vereditos_dos_casos(
    bruto: Any, rodada: RodadaDeCasos, onde: str
) -> tuple[VereditoDeCaso, ...]:
    """Os vereditos da folha dos Casos, contra o vocabulário e a cobertura dupla.

    Cada execução julgável precisa de exatamente dois vereditos — um de
    Alucinação e um de confabulação com Fonte — porque as duas métricas de pessoa
    julgam a mesma resposta por perguntas diferentes: se o conteúdo é fabricado,
    e se a citação sustenta o que foi dito.
    """
    if not isinstance(bruto, list):
        raise ErroDasTaxas("o campo `vereditos` não é uma lista")
    da_rodada = _indice_dos_casos(rodada)
    lidos: list[VereditoDeCaso] = []
    vistos: set[tuple[ChaveExecucao, str]] = set()
    for indice, item in enumerate(bruto):
        local = f"o veredito {indice + 1} de {onde}"
        if not isinstance(item, dict):
            raise ErroDasTaxas(f"{local} não é um objeto JSON")
        chave = ChaveExecucao(
            _texto(item, "id", local), _numero(item, "repeticao", local)
        )
        metrica = _texto(item, "metrica", local)
        if metrica not in METRICAS_DE_PESSOA_DOS_CASOS:
            raise JulgamentoInvalidoError(
                f"{local}: `metrica` é {metrica!r} e as duas métricas de pessoa "
                f"são {list(METRICAS_DE_PESSOA_DOS_CASOS)}"
            )
        par = (chave, metrica)
        if par in vistos:
            raise JulgamentoInvalidoError(
                f"{local}: {chave.como_texto()} em {metrica} tem dois vereditos"
            )
        vistos.add(par)
        if chave.id not in CASOS_IDS:
            raise JulgamentoInvalidoError(f"{local}: {chave.id} não é um dos cinco Casos")
        if chave not in da_rodada:
            raise JulgamentoInvalidoError(
                f"{local}: a rodada {rodada.caminho} não tem a execução {chave.como_texto()}"
            )
        veredito_texto = _texto(item, "veredito", local)
        if veredito_texto == A_PREENCHER:
            raise JulgamentoInvalidoError(
                f"{local}: o veredito de {chave.como_texto()} em {metrica} está `{A_PREENCHER}`"
            )
        if veredito_texto not in VEREDITOS:
            raise JulgamentoInvalidoError(
                f"{local}: `veredito` é {veredito_texto!r} e o vocabulário é {list(VEREDITOS)}"
            )
        if veredito_texto == "conforme":
            veredito: Veredito = "conforme"
        elif veredito_texto == "nao_conforme":
            veredito = "nao_conforme"
        else:
            veredito = "nao_avaliavel"
        nota = item.get("nota")
        if nota is None:
            nota = ""
        if not isinstance(nota, str):
            raise ErroDasTaxas(f"{local}: o campo `nota` não é texto")
        if veredito == "nao_avaliavel" and not nota.strip():
            raise JulgamentoInvalidoError(
                f"{local}: marcar `nao_avaliavel` exige a razão em `nota`"
            )
        execucao = da_rodada[chave]
        resposta_na_folha = item.get("resposta_bruta")
        if resposta_na_folha != execucao.resposta_bruta:
            raise JulgamentoInvalidoError(
                f"{local}: o `resposta_bruta` da folha não é o da rodada — quem julgou "
                f"leu um output que a rodada não gravou"
            )
        lidos.append(
            VereditoDeCaso(
                id=chave.id,
                repeticao=chave.repeticao,
                metrica=metrica,
                veredito=veredito,
                nota=nota,
            )
        )
    esperados = {
        (execucao.chave, metrica)
        for execucao in rodada.execucoes
        if execucao.julgavel
        for metrica in METRICAS_DE_PESSOA_DOS_CASOS
    }
    faltando = sorted(
        f"{chave.como_texto()} em {metrica}" for (chave, metrica) in esperados - vistos
    )
    if faltando:
        mostradas = faltando[:MAXIMO_DE_FALTAS_LISTADAS]
        resto = len(faltando) - len(mostradas)
        sufixo = f", e mais {resto}" if resto else ""
        raise JulgamentoInvalidoError(
            f"{onde}: faltou veredito para {len(faltando)} linhas "
            f"({', '.join(mostradas)}{sufixo})"
        )
    return tuple(lidos)


def _conferir_reguas_dos_casos(bruto: Any, rodada: RodadaDeCasos, onde: str) -> None:
    """A régua impressa na folha dos Casos precisa ser a da rodada."""
    if bruto is None:
        return
    if not isinstance(bruto, dict):
        raise ErroDasTaxas("o campo `casos` não é um objeto")
    por_id = {execucao.id: execucao for execucao in rodada.execucoes}
    for id_caso, item in bruto.items():
        execucao = por_id.get(id_caso)
        if execucao is None:
            raise JulgamentoInvalidoError(
                f"{onde}: a folha traz a régua de {id_caso}, que não é um dos cinco Casos"
            )
        local = f"a régua de {id_caso} em {onde}"
        for campo in (
            "pergunta",
            "conforme_quando",
            "nao_conforme_quando",
            "motivo_do_erro",
            "resposta_errada_esperada",
        ):
            if _texto(item, campo, local) != getattr(execucao, campo):
                raise JulgamentoInvalidoError(
                    f"{local}: o `{campo}` da folha é diferente do da rodada "
                    f"{rodada.caminho}. Quem julgou leu outra régua"
                )


def carregar_julgamento_dos_casos(caminho: Path, rodada: RodadaDeCasos) -> JulgamentoDeCasos:
    """Lê a folha de julgamento dos Casos e falha alto no que a deixaria mentira."""
    if not caminho.is_file():
        raise JulgamentoInvalidoError(
            f"o julgamento dos Casos não está em {caminho}. Ele nasce de "
            f"`python -m harness.metrics --rodada {rodada.caminho} --preparar`"
        )
    try:
        bruto = _ler_json(caminho, "o julgamento dos Casos")
        if not isinstance(bruto, dict):
            raise ErroDasTaxas("o julgamento dos Casos não é um objeto JSON")
        onde = f"o julgamento dos Casos em {caminho}"
        sha = _texto(bruto, "sha256_da_rodada", onde)
        if sha != rodada.sha256:
            raise JulgamentoInvalidoError(
                f"é o julgamento de outra rodada: o sha256 guardado é {sha} e a "
                f"rodada {rodada.caminho} tem {rodada.sha256}"
            )
        for campo in ("julgador", "julgado_em"):
            if _texto(bruto, campo, onde) == A_PREENCHER:
                raise JulgamentoInvalidoError(
                    f"o campo `{campo}` está `{A_PREENCHER}`. A taxa precisa dizer "
                    f"quem ratificou a régua e quando — é isso que amarra a folha a "
                    f"uma pessoa em vez de a um processo"
                )
        _conferir_reguas_dos_casos(bruto.get("casos"), rodada, onde)
        vereditos = _ler_vereditos_dos_casos(bruto.get("vereditos"), rodada, onde)
    except JulgamentoInvalidoError:
        raise
    except ErroDasTaxas as exc:
        raise JulgamentoInvalidoError(str(exc)) from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise JulgamentoInvalidoError(f"não consegui ler o julgamento em {caminho}: {exc}") from exc
    return JulgamentoDeCasos(
        caminho=caminho_relativo(caminho),
        sha256_da_rodada=sha,
        julgador=cast(str, bruto["julgador"]),
        julgado_em=cast(str, bruto["julgado_em"]),
        vereditos=vereditos,
    )


def republicar_taxas_1_1() -> dict[str, dict[str, Any]]:
    """As duas taxas da 1.1 republicadas sem alteração, como números congelados."""
    return {nome: dict(valores) for nome, valores in TAXAS_1_1_CONGELADAS.items()}


def conferir_taxas_1_1_congeladas(documento: Mapping[str, Any]) -> None:
    """Confere o JSON das taxas da 1.1 contra o bloco congelado, campo a campo.

    É o teste que trava que a republicação não mudou: fração por execução, fração
    por pergunta e os formatos com vírgula, nos dois denominadores. Quem mudar a
    conta muda os dois lados, com a issue aberta.
    """
    taxas = documento.get("taxas")
    if not isinstance(taxas, dict):
        raise MembrosDivergentesError("o JSON das taxas da 1.1 não tem o bloco `taxas`")
    for nome, esperado in TAXAS_1_1_CONGELADAS.items():
        achado = taxas.get(nome)
        if not isinstance(achado, dict):
            raise MembrosDivergentesError(f"o JSON das taxas da 1.1 não tem a taxa {nome}")
        for campo, valor in esperado.items():
            if achado.get(campo) != valor:
                raise MembrosDivergentesError(
                    f"a taxa {nome} da 1.1 mudou em `{campo}`: esperado {valor!r} e o "
                    f"arquivo traz {achado.get(campo)!r}. As duas taxas são republicadas "
                    f"congeladas, e a 1.2 não as corrige"
                )


def calcular_casos(
    rodada: RodadaDeCasos,
    julgamento: JulgamentoDeCasos,
    titulos: Sequence[str],
    documentos: Sequence[str],
) -> RelatorioDosCasos:
    """Calcula as três métricas sobre os cinco Casos, com evidência e falso positivo.

    As duas métricas de pessoa saem dos vereditos da folha; a Fonte verificável
    sai do script, sem veredito. Cada acerto e cada erro carrega o `resposta_bruta`
    inteiro: o critério da #28 é o mesmo da #13 — cada contagem aponta o output
    que a originou.
    """
    indice = {
        (veredito.id, veredito.repeticao, veredito.metrica): veredito
        for veredito in julgamento.vereditos
    }
    taxas: dict[str, TaxaDeCaso] = {}
    for metrica in METRICAS_DE_PESSOA_DOS_CASOS:
        taxas[metrica] = _calcular_metrica_de_pessoa(rodada, indice, metrica)
    taxas[FONTE_VERIFICAVEL] = _calcular_fonte_verificavel(rodada, titulos, documentos)
    falso_positivo = _calcular_falso_positivo(rodada)
    return RelatorioDosCasos(
        rodada=rodada,
        julgamento=julgamento,
        taxas=taxas,
        falso_positivo=falso_positivo,
        taxas_1_1_republicadas=republicar_taxas_1_1(),
    )


def _evidencia_de_caso(execucao: ExecucaoDeCaso, veredito: str) -> EvidenciaDeCaso:
    if execucao.resposta_bruta is None:
        raise ErroDasTaxas(
            f"a execução {execucao.id} repetição {execucao.repeticao} entrou na conta "
            f"sem resposta para evidenciar"
        )
    return EvidenciaDeCaso(
        id=execucao.id,
        repeticao=execucao.repeticao,
        veredito=veredito,
        pergunta=execucao.pergunta,
        resposta_bruta=execucao.resposta_bruta,
        fontes_recuperadas=execucao.fontes_recuperadas,
        motivo_de_parada=execucao.motivo_de_parada,
    )


def _calcular_metrica_de_pessoa(
    rodada: RodadaDeCasos,
    indice: Mapping[tuple[str, int, str], VereditoDeCaso],
    metrica: str,
) -> TaxaDeCaso:
    """Uma métrica de pessoa: a fração que alucinou (ou confabulou), com evidência.

    O numerador é o `nao_conforme`: a taxa mede o defeito, e cair é melhorar. O
    `conforme` vai para os acertos para que o relatório mostre os dois lados com
    o output ao lado de cada contagem.
    """
    acertos: list[EvidenciaDeCaso] = []
    erros: list[EvidenciaDeCaso] = []
    fora: list[ForaDaConta] = []
    avaliadas = 0
    defeitos = 0
    for execucao in rodada.execucoes:
        if execucao.id not in CASOS_IDS:
            continue
        if not execucao.julgavel:
            fora.append(_fora_da_conta_de_caso(execucao))
            continue
        veredito = indice.get((execucao.id, execucao.repeticao, metrica))
        if veredito is None:
            raise JulgamentoInvalidoError(
                f"a execução {execucao.id} repetição {execucao.repeticao} em {metrica} "
                f"não tem veredito no julgamento"
            )
        if veredito.veredito == "nao_avaliavel":
            fora.append(
                ForaDaConta(
                    id=execucao.id,
                    repeticao=execucao.repeticao,
                    motivo="julgada",
                    detalhe=veredito.nota,
                    resposta_bruta=execucao.resposta_bruta,
                )
            )
            continue
        avaliadas += 1
        evidencia = _evidencia_de_caso(execucao, veredito.veredito)
        if veredito.veredito == "nao_conforme":
            erros.append(evidencia)
            defeitos += 1
        else:
            acertos.append(evidencia)
    if avaliadas == 0:
        raise JulgamentoInvalidoError(
            f"a {TITULOS_DAS_METRICAS_DOS_CASOS[metrica]} ficou sem execução avaliada"
        )
    fracao = defeitos / avaliadas
    return TaxaDeCaso(
        metrica=metrica,
        titulo=TITULOS_DAS_METRICAS_DOS_CASOS[metrica],
        avaliadas=avaliadas,
        numerador=defeitos,
        fracao=fracao,
        fracao_formatada=f"{defeitos}/{avaliadas} = {_numero_em_portugues(fracao)}",
        acertos=tuple(acertos),
        erros=tuple(erros),
        fora_da_conta=tuple(fora),
    )


def _fora_da_conta_de_caso(execucao: ExecucaoDeCaso) -> ForaDaConta:
    if execucao.resposta_bruta is None:
        return ForaDaConta(
            id=execucao.id,
            repeticao=execucao.repeticao,
            motivo="erro",
            detalhe=execucao.erro or "o turno falhou sem motivo registrado",
            resposta_bruta=None,
        )
    return ForaDaConta(
        id=execucao.id,
        repeticao=execucao.repeticao,
        motivo="cortada",
        detalhe=f"a geração parou por falta de espaço (motivo de parada `{PARADA_CORTADA}`)",
        resposta_bruta=execucao.resposta_bruta,
    )


def _calcular_fonte_verificavel(
    rodada: RodadaDeCasos, titulos: Sequence[str], documentos: Sequence[str]
) -> TaxaDeCaso:
    """A Fonte verificável: a fração com citação que resolve, conferida por script.

    Não há veredito humano aqui: o numerador é a resposta com status `verificavel`,
    e o resto do denominador são os outros quatro status da tabela — cada um com
    o motivo na evidência, para que a página mostre por que cada citação falhou.
    """
    acertos: list[EvidenciaDeCaso] = []
    erros: list[EvidenciaDeCaso] = []
    fora: list[ForaDaConta] = []
    avaliadas = 0
    verificaveis = 0
    for execucao in rodada.execucoes:
        if execucao.id not in CASOS_IDS:
            continue
        if not execucao.julgavel:
            fora.append(_fora_da_conta_de_caso(execucao))
            continue
        avaliadas += 1
        status = verificar_fontes_da_resposta(
            execucao.resposta_bruta or "", titulos, documentos
        )
        evidencia = _evidencia_de_caso(execucao, status)
        if status == "verificavel":
            acertos.append(evidencia)
            verificaveis += 1
        else:
            erros.append(evidencia)
    if avaliadas == 0:
        raise JulgamentoInvalidoError("a Fonte verificável ficou sem execução avaliada")
    fracao = verificaveis / avaliadas
    return TaxaDeCaso(
        metrica=FONTE_VERIFICAVEL,
        titulo=TITULOS_DAS_METRICAS_DOS_CASOS[FONTE_VERIFICAVEL],
        avaliadas=avaliadas,
        numerador=verificaveis,
        fracao=fracao,
        fracao_formatada=f"{verificaveis}/{avaliadas} = {_numero_em_portugues(fracao)}",
        acertos=tuple(acertos),
        erros=tuple(erros),
        fora_da_conta=tuple(fora),
    )


def _calcular_falso_positivo(rodada: RodadaDeCasos) -> FalsoPositivo:
    """O falso positivo de similaridade: a enganosa no top-k, como número próprio."""
    avaliadas = 0
    ocorrencias = 0
    for execucao in rodada.execucoes:
        if execucao.id not in CASOS_IDS:
            continue
        if not execucao.julgavel:
            continue
        avaliadas += 1
        if TITULO_ENGANOSO in execucao.fontes_recuperadas:
            ocorrencias += 1
    fracao = (ocorrencias / avaliadas) if avaliadas else 0.0
    return FalsoPositivo(
        titulo=TITULO_ENGANOSO,
        ocorrencias=ocorrencias,
        avaliadas=avaliadas,
        fracao=fracao,
        fracao_formatada=(
            f"{ocorrencias}/{avaliadas} = {_numero_em_portugues(fracao)}" if avaliadas else "0/0"
        ),
    )


def gravar_metricas_dos_casos(relatorio: RelatorioDosCasos, destino: Path) -> Path:
    """Grava o JSON das três métricas dos Casos, com a rodada e o julgamento."""
    rodada = relatorio.rodada
    documento = {
        "rodada": rodada.caminho,
        "sha256_da_rodada": rodada.sha256,
        "modelo": rodada.modelo,
        "url": rodada.url,
        "condicoes": rodada.condicoes,
        "alocacao": rodada.alocacao,
        "recuperacao": rodada.recuperacao,
        "julgamento": {
            "arquivo": relatorio.julgamento.caminho,
            "sha256_da_rodada": relatorio.julgamento.sha256_da_rodada,
            "julgador": relatorio.julgamento.julgador,
            "julgado_em": relatorio.julgamento.julgado_em,
        },
        "taxas": {nome: asdict(taxa) for nome, taxa in relatorio.taxas.items()},
        "falso_positivo_similaridade": asdict(relatorio.falso_positivo),
        "taxas_1_1_republicadas": relatorio.taxas_1_1_republicadas,
    }
    _gravar(destino, documento)
    return destino


def resumo_dos_casos_em_markdown(relatorio: RelatorioDosCasos) -> str:
    """A página que vai para o relato da 1.2: as três métricas com evidência."""
    rodada = relatorio.rodada
    julgamento = relatorio.julgamento
    recuperacao = rodada.recuperacao
    partes = [
        "## As três métricas nos cinco Casos de alucinação",
        "",
        f"- Rodada: `{rodada.caminho}` — sha256 `{rodada.sha256}`",
        f"- Modelo: `{rodada.modelo}` — {rodada.repeticoes} repetições por caso",
        f"- Alocação: {_descrever_alocacao(rodada.alocacao)}",
        f"- Recuperação: {recuperacao}",
        f"- Julgamento: `{julgamento.caminho}` — {julgamento.julgador}, {julgamento.julgado_em}",
        "",
        "### Taxas da 1.1 republicadas sem alteração",
        "",
    ]
    for nome, valores in relatorio.taxas_1_1_republicadas.items():
        titulo = TITULOS_DAS_TAXAS_1_1.get(nome, nome)
        partes.append(
            f"- {titulo}: por execução **{valores['fracao_formatada']}**, por pergunta "
            f"**{valores['fracao_por_pergunta_formatada']}**."
        )
    partes.append("")
    for nome in (ALUCINACAO, CONFABULACAO_COM_FONTE, FONTE_VERIFICAVEL):
        taxa = relatorio.taxas[nome]
        if nome == FONTE_VERIFICAVEL:
            rotulo_ok = "**Com Fonte verificável — a evidência do numerador**"
        elif nome == CONFABULACAO_COM_FONTE:
            rotulo_ok = "**Sem confabulação — nenhuma citação que não sustente**"
        else:
            rotulo_ok = "**Sem Alucinação — o que não foi fabricado**"
        partes.extend(
            [
                f"### {taxa.titulo} — {taxa.fracao_formatada}",
                "",
                f"{taxa.numerador} de {taxa.avaliadas} execuções avaliadas, "
                f"{len(taxa.fora_da_conta)} fora da conta.",
                "",
                rotulo_ok,
                "",
            ]
        )
        partes.extend(_linhas_de_evidencia_de_caso(taxa.acertos))
        if taxa.erros:
            partes.extend(
                [
                    "",
                    f"**Com defeito — o resto do denominador** ({taxa.avaliadas} avaliadas = "
                    f"{len(taxa.acertos)} sem defeito + {_plural(len(taxa.erros), 'erro')})",
                    "",
                ]
            )
            partes.extend(_linhas_de_evidencia_de_caso(taxa.erros))
        if taxa.fora_da_conta:
            partes.extend(["", "**Fora da conta**", ""])
            partes.extend(_linhas_de_fora_da_conta(taxa.fora_da_conta))
        partes.append("")
    falso = relatorio.falso_positivo
    partes.extend(
        [
            "### Falso positivo de similaridade — número próprio",
            "",
            f"A seção `{falso.titulo}` voltou no top-k em **{falso.fracao_formatada}** "
            f"das execuções avaliadas. Ela vem da recuperação rodar em todo turno: com "
            f"`k = 3` sem classificação de intenção, a seção parecida e irrelevante volta "
            f"visível mesmo quando a pergunta não é dela — e estar no material recuperado "
            f"não é estar citado.",
            "",
        ]
    )
    return "\n".join(partes).rstrip() + "\n"


def _linhas_de_evidencia_de_caso(evidencias: Sequence[EvidenciaDeCaso]) -> list[str]:
    linhas = [
        f"- `{evidencia.id}` repetição {evidencia.repeticao} — "
        f"\"{_trecho(evidencia.resposta_bruta)}\""
        for evidencia in evidencias
    ]
    return linhas or ["- nenhuma"]


def _ids_de_casos_em(caminho: Path) -> set[str]:
    """Os ids de execução de um JSON de rodada, sem validar o resto."""
    try:
        bruto = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return set()
    if not isinstance(bruto, dict):
        return set()
    execucoes = bruto.get("execucoes")
    if not isinstance(execucoes, list):
        return set()
    ids: set[str] = set()
    for item in execucoes:
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            ids.add(str(item["id"]))
    return ids


def rodada_e_dos_casos(caminho: Path) -> bool:
    """Se o JSON é uma rodada dos cinco Casos, pelos ids das execuções."""
    ids = _ids_de_casos_em(caminho)
    return bool(ids) and ids <= set(CASOS_IDS)




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
    analisador.add_argument(
        "--corpus",
        type=Path,
        default=None,
        help=(
            "diretório do Corpus para a Fonte verificável dos Casos "
            f"(padrão: {DIRETORIO_CORPUS_PADRAO})"
        ),
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
    if rodada_e_dos_casos(opcoes.rodada):
        return _executar_casos(opcoes)

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


def _executar_casos(opcoes: argparse.Namespace) -> int:
    """O comando dos Casos: prepara a folha dos Casos ou calcula as três métricas.

    Sai pelo mesmo contrato de códigos da bateria: 0 gravou, 1 folha, 2 rodada,
    3 caminho. A detecção é pelos ids das execuções — rodada dos Casos só tem
    `c1` a `c5` — e o Corpus vem de `--corpus` ou do diretório versionado.
    """
    rodada = carregar_rodada_de_casos(opcoes.rodada)

    if opcoes.preparar:
        destino = opcoes.julgamento or _com_sufixo(opcoes.rodada, "julgamento")
        preparar_julgamento_dos_casos(rodada, destino)
        return SAIDA_OK

    caminho = opcoes.julgamento or _com_sufixo(opcoes.rodada, "julgamento")
    julgamento = carregar_julgamento_dos_casos(caminho, rodada)
    diretorio = opcoes.corpus or DIRETORIO_CORPUS_PADRAO
    titulos, documentos = titulos_do_corpus(diretorio)
    relatorio = calcular_casos(rodada, julgamento, titulos, documentos)
    destino = opcoes.saida or _com_sufixo(opcoes.rodada, "metricas")
    gravar_metricas_dos_casos(relatorio, destino)

    print(resumo_dos_casos_em_markdown(relatorio))
    print(f"\nJSON das taxas dos Casos gravado em {destino}")
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
                    id=execucao.id,
                    repeticao=execucao.repeticao,
                    motivo="julgada",
                    detalhe=veredito.nota,
                    resposta_bruta=execucao.resposta_bruta,
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
            id=execucao.id,
            repeticao=execucao.repeticao,
            motivo="erro",
            detalhe=execucao.erro or "o turno falhou sem motivo registrado",
            resposta_bruta=None,
        )
    return ForaDaConta(
        id=execucao.id,
        repeticao=execucao.repeticao,
        motivo="cortada",
        detalhe=f"a geração parou por falta de espaço (motivo de parada `{PARADA_CORTADA}`)",
        resposta_bruta=execucao.resposta_bruta,
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

    `metrica` e `veredito` chegam aqui como `str`, porque a folha é JSON cru e a
    linha foi lida sem interpretar. Os dois `cast` abaixo não corrigem nada em
    runtime: o `raise` logo acima de cada um já garante que o valor está no
    vocabulário, e é contra ele que o `cast` afirma. O que ele faz é registrar em
    tipo o que a validação em runtime já assegura — o mesmo padrão que o `cast` de
    `bruto["julgador"]` usa mais acima, e pelo mesmo motivo: o `mypy` não estreita
    um `str` através de um `not in`, mesmo quando o `not in` está logo acima e já
    levantou.
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

        if linha.metrica not in METRICAS:
            raise JulgamentoInvalidoError(
                f"{local}: `metrica` é {linha.metrica!r} e as duas taxas são "
                f"{list(METRICAS)}"
            )
        metrica = cast(Metrica, linha.metrica)
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
        veredito = cast(Veredito, linha.veredito)

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
