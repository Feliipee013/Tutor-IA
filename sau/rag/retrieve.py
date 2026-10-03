"""Índice em memória do Corpus, montado das seções e nunca persistido.

O Corpus é quebrado em unidades de recuperação pela própria equipe: cada `##`
dentro de um documento responde a uma Pergunta Frequente, então o trecho
recuperado é a seção e o chunking é uma escolha da equipe, não uma heurística.
Este módulo lê essas seções, casa cada uma com o seu vetor e guarda o índice
que montou — e o expõe, para que a rodada do harness consiga declarar o que
realmente usou.

O que este módulo não faz, de propósito: busca top-k e matriz de
similaridade são do P3, e nada aqui escreve em disco. Um índice em disco é um
segundo artefato que precisa ser sincronizado com o Corpus, e um índice
desatualizado mede em silêncio.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from sau.rag.embed import ClienteEmbedding

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
    """Lê os documentos `*.md` do diretório, em ordem de nome, e devolve as seções."""
    secoes: list[Secao] = []
    for caminho in sorted(diretorio.glob("*.md")):
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

    def __post_init__(self) -> None:
        if len(self.secoes) != len(self.vetores):
            raise ValueError(
                f"Índice com {len(self.secoes)} seções e {len(self.vetores)} vetores: "
                "cada seção precisa do seu vetor."
            )


def montar_indice(diretorio: Path, cliente: ClienteEmbedding) -> Indice:
    """Monta o índice em memória a partir das seções do Corpus, sem escrever em disco."""
    secoes = carregar_corpus(diretorio)
    if not secoes:
        raise ValueError(f"Nenhuma seção no Corpus em {diretorio}: índice vazio não mede nada.")
    textos = [f"{secao.titulo}\n{secao.texto}" for secao in secoes]
    vetores = cliente.embutir(textos)
    indice = Indice(secoes=list(secoes), vetores=vetores)
    logger.info("Índice montado: %d seções de %s, em memória.", len(secoes), diretorio)
    return indice
