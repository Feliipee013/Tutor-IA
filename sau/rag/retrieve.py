"""Índice em memória do Corpus, montado das seções e nunca persistido.

O Corpus é quebrado em unidades de recuperação pela própria equipe: cada `##`
dentro de um documento responde a uma Pergunta Frequente, então o trecho
recuperado é a seção e o chunking é uma escolha da equipe, não uma heurística.
Este módulo lê essas seções, casa cada uma com o seu vetor e guarda o índice
que montou — e o expõe, para que a rodada do harness consiga declarar o que
realmente usou.

O que este módulo não faz, de propósito: nada aqui escreve em disco. Um índice
em disco é um segundo artefato que precisa ser sincronizado com o Corpus, e um
índice desatualizado mede em silêncio.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from sau.rag.embed import ProtocoloEmbedding, cosseno

logger = logging.getLogger("sau.rag.retrieve")

_MARCADOR_COMENTARIO = re.compile(r"<!--.*?-->", re.DOTALL)
_MARCADOR_TITULO = re.compile(r"^##\s+(.*)$")


@dataclass(frozen=True)
class Secao:
    """Um trecho recuperável do Corpus: o documento e a seção que o S.A.U. cita."""

    documento: str
    """O arquivo do Corpus, ex. `prazos.md`: a primeira metade da Fonte."""

    titulo: str
    """O título da seção `##`: a segunda metade da Fonte, único no Corpus inteiro."""

    texto: str
    """O corpo da seção, sem os marcadores `<!-- caso: ... -->` da equipe.

    Os marcadores nomeiam o caso que o defeito planta, e vetor de anotação de
    bancada não entra no índice: o que o S.A.U. recupera é o que o Aluno lê.
    """


def ler_secoes_corpus(caminho: Path) -> list[Secao]:
    """Lê um documento do Corpus e devolve as suas seções `##`, sem os marcadores."""
    linhas = caminho.read_text(encoding="utf-8").splitlines()
    secoes: list[Secao] = []
    titulo: str | None = None
    corpo: list[str] = []

    def descarregar() -> None:
        if titulo is not None:
            texto = _MARCADOR_COMENTARIO.sub("", "\n".join(corpo)).strip()
            secoes.append(Secao(documento=caminho.name, titulo=titulo, texto=texto))

    for linha in linhas:
        achado = _MARCADOR_TITULO.match(linha.strip())
        if achado is not None:
            descarregar()
            titulo = achado.group(1).strip()
            corpo = []
        elif titulo is not None:
            corpo.append(linha)

    descarregar()
    return secoes


def carregar_corpus(diretorio: Path) -> list[Secao]:
    """Lê os documentos `*.md` do diretório, em ordem de nome, e devolve as seções.

    O `README.md` nunca é material: desde a #40 a base é o PDF do Manual
    (ADR-0011) e o `corpus/` não tem mais `.md` sintético. Sem este filtro,
    os títulos `##` do README virariam Fonte citável em produção — que agora
    degrada para recuperação desligada até a #36 religar o turno no Chroma.
    """
    secoes: list[Secao] = []
    for caminho in sorted(diretorio.glob("*.md")):
        if caminho.name.upper() == "README.MD":
            continue
        secoes.extend(ler_secoes_corpus(caminho))
    return secoes


def titulos_duplicados(secoes: list[Secao]) -> list[str]:
    """Devolve os títulos que aparecem mais de uma vez, em ordem alfabética.

    Título repetido quebra a Fonte citada por correspondência exata — e é por
    isso que a unicidade é verificada por teste, com um caso repetido de
    propósito.
    """
    vistos: set[str] = set()
    repetidos: set[str] = set()
    for secao in secoes:
        if secao.titulo in vistos:
            repetidos.add(secao.titulo)
        vistos.add(secao.titulo)
    return sorted(repetidos)


@dataclass
class Indice:
    """O índice montado: as seções do Corpus com um vetor por seção, em memória.

    Guarda o que montou e o expõe em `secoes`, para que a rodada declare o que
    realmente usou. Não há `salvar` porque não há onde salvar: persistir o
    índice criaria o segundo artefato que este módulo existe para não ter.
    """

    secoes: list[Secao]
    vetores: list[list[float]] = field(repr=False)
    modelo_embedding: str = ""
    """O modelo que produziu os vetores: o que a rodada declara como usado."""

    def __post_init__(self) -> None:
        if len(self.secoes) != len(self.vetores):
            raise ValueError(
                f"Índice com {len(self.secoes)} seções e {len(self.vetores)} vetores: "
                "cada seção precisa do seu vetor."
            )


@dataclass(frozen=True)
class TrechoRecuperado:
    """Um trecho devolvido pela busca: a seção do Corpus com a similaridade.

    Carrega documento, seção, texto e similaridade para que a busca seja
    inspecionável: dá para ver por que um trecho voltou e o outro não. A
    seção citada como Fonte é o título, copiado verbatim do trecho que o
    modelo tem na mão — e a verificação é correspondência exata contra os
    títulos do Corpus, que são únicos.
    """

    documento: str
    """O arquivo do Corpus, ex. `prazos.md`: a primeira metade da Fonte."""

    titulo: str
    """O título da seção `##`, único no Corpus inteiro: a Fonte citada."""

    texto: str
    """O corpo da seção, como o Aluno a lê."""

    similaridade: float
    """O cosseno entre o vetor da seção e o da consulta: por que voltou."""


def similaridades(indice: Indice, vetor_consulta: list[float]) -> list[float]:
    """O cosseno da consulta contra cada seção, na ordem do índice.

    É a matriz de similaridade inspecionável: um vetor por seção, na mesma
    ordem de `indice.secoes`, para que a equipe discuta por que um trecho
    voltou e o outro não em vez de ler uma caixa-preta.
    """
    return [cosseno(vetor, vetor_consulta) for vetor in indice.vetores]


K_PADRAO = 3
"""Quantos trechos a busca devolve: parâmetro de orçamento, não de qualidade.

O `num_ctx` é 4096 e não é tocado, e as seções do Corpus são curtas de
propósito para caber: três trechos é o que cabe antes de a conversa perder
contexto.
"""


def buscar(
    indice: Indice, vetor_consulta: list[float], k: int = K_PADRAO
) -> list[TrechoRecuperado]:
    """Devolve os `k` trechos mais próximos da consulta, com a similaridade.

    A ordenação é pelo sentido da pergunta — o cosseno entre vetores — e não
    por palavra-chave: seção sem uma palavra em comum com a consulta volta
    quando o vetor dela é o mais próximo. Índice vazio devolve lista vazia,
    que é o que o grafo lê como recuperação desligada.
    """
    if k < 1:
        raise ValueError(f"A busca precisa de ao menos um trecho: k foi {k}.")
    pontuados = [
        (similaridade, posicao)
        for posicao, similaridade in enumerate(similaridades(indice, vetor_consulta))
    ]
    pontuados.sort(key=lambda item: item[0], reverse=True)
    trechos: list[TrechoRecuperado] = []
    for similaridade, posicao in pontuados[:k]:
        secao = indice.secoes[posicao]
        trechos.append(
            TrechoRecuperado(
                documento=secao.documento,
                titulo=secao.titulo,
                texto=secao.texto,
                similaridade=similaridade,
            )
        )
    return trechos


def resolver_fonte(titulo: str, secoes: list[Secao]) -> Secao | None:
    """Resolve a Fonte citada para a seção do Corpus, por correspondência exata.

    É o verificador mecânico da Fonte — o que a spec chama de "Fonte
    verificável ... conferida por script": dado um título citado, diz se ele
    é exatamente um título do Corpus e qual seção ele sustenta. Por isso vive
    aqui e é exercitado por teste de tabela sobre fixture (`test_busca.py`):
    quem o chama é o script que confere a rodada, e não o turno — o turno não
    parseia a própria resposta, e obediência do modelo à instrução de citar
    continua veredito de pessoa (confabulação com Fonte). Maiúscula trocada
    não resolve — a Fonte é copiada verbatim do trecho recuperado, e cópia
    fiel não muda letra.
    """
    for secao in secoes:
        if secao.titulo == titulo:
            return secao
    return None


_ULTIMO_INDICE: Indice | None = None
"""O índice que a última montagem guardou, para a rodada declarar o que usou.

É o mesmo papel que já cumprem o modelo, a alocação e o `sha256` do prompt:
separar "o RAG mudou" de "o RAG nem estava ligado". Vazio significa bloco
declarando recuperação desligada — que é a verdade, e é o que dá valor ao
campo.
"""


def ultimo_indice() -> Indice | None:
    """O índice montado por último, ou `None` se a recuperação nunca rodou."""
    return _ULTIMO_INDICE


def limpar_ultimo_indice() -> None:
    """Esvazia o índice guardado, para os testes.

    Sem isto, um helper de teste que monta o índice direto (`montar_indice`)
    deixaria o global apontando para o índice dele, e a rodada declararia
    "o que o vizinho usou" em vez de "o que realmente usou". Produção nunca
    chama isto: lá o global nasce vazio com o processo e só a recuperação o
    preenche.
    """
    global _ULTIMO_INDICE
    _ULTIMO_INDICE = None


def montar_indice(diretorio: Path, cliente: ProtocoloEmbedding) -> Indice:
    """Monta o índice em memória a partir das seções do Corpus, sem escrever em disco."""
    secoes = carregar_corpus(diretorio)
    if not secoes:
        raise ValueError(f"Nenhuma seção no Corpus em {diretorio}: índice vazio não mede nada.")
    textos = [f"{secao.titulo}\n{secao.texto}" for secao in secoes]
    vetores = cliente.embutir(textos)
    indice = Indice(secoes=list(secoes), vetores=vetores, modelo_embedding=cliente.modelo_embedding)
    global _ULTIMO_INDICE
    _ULTIMO_INDICE = indice
    logger.info("Índice montado: %d seções de %s, em memória.", len(secoes), diretorio)
    return indice
