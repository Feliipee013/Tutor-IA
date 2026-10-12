"""Máscara de dados ilustrativos do Manual antes da indexação (ADR-0011).

Número de apólice, CNPJ, CPF, matrícula, nomes próprios em tabelas, telefone
e e-mail que aparecem no Manual são **exemplo**, não fato: se entrassem no
índice como estão, o S.A.U. citaria um dado de mentira com Fonte de verdade.
Tudo isso vira um marcador neutro antes de indexar.

A exceção é o contato da Coordenação de Estágios: telefone e e-mail
**seguem indexáveis e citáveis** quando o trecho é normativo ou de
Encaminhamento e indica o contato da Coordenação (`e_contato_da_coordenacao`).
O Manual 2026/2 não tem seção assim — só Encaminhamento via chamado no
ServiceNow, sem telefone nem e-mail — então na prática atual a máscara cobre
tudo, e a exceção existe para o Manual futuro sem inventar contato onde não
há (ver `corpus/README.md`).
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger("sau.manual.mascara")

MARCADOR = "[dado ilustrativo]"
"""O marcador neutro que substitui todo dado ilustrativo, de qualquer categoria.

Um marcador só, e não um por categoria: a categoria ("era um CPF") já seria
informação sobre o exemplo, e o índice não precisa dela para responder sobre
processo, Prazos e Documentação de Estágio.
"""

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_CNPJ = re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b")
_CPF = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")
_TELEFONE = re.compile(r"(?<!\d)\(?\d{2}\)?[\s.\-]?\d{4,5}[\s.\-]?\d{4}(?!\d)")
_APOLICE = re.compile(
    r"apólice(\s+de\s+seguro)?\s+(nº|n\.|n°|número|numero)\s*[:.]?\s*[\w.\-/]+"
    r"|\bapólice(\s+de\s+seguro)?\s+[\w.\-/]*\d[\w.\-/]*",
    re.IGNORECASE,
)
"""Só mascara a apólice quando há número junto: com `nº` explícito ou com dígito.

"Apólice de Seguro" sozinha é nome de cobertura ou de filtro do ServiceNow —
matéria normativa e citável — e "apólice vigente" sem número não é dado. O
que nunca vira fato é o número, que é o que as duas alternativas exigem."""
_VIGENCIA_COM_DATA = re.compile(
    r"vigência\s*[:.]?\s*\d[\d/\-.]*", re.IGNORECASE
)
_MATRICULA = re.compile(
    r"(matrícula|matricula|\bRA\b)\s*((nº|n\.|n°)\s*[:.]?\s*)?\d[\d.\-]*",
    re.IGNORECASE,
)

_MARCADOR_TABELA = ("✓", "|", "\t", "•", "·")
_ESPACOS_DE_COLUNA = re.compile(r" {2,}")
_NOME_PROPRIO = re.compile(
    r"\b[A-ZÀ-Ú][a-zà-ú]+(?:\s+(?:d[aeo]s?|e)\s+[A-ZÀ-Ú][a-zà-ú]+|\s+[A-ZÀ-Ú][a-zà-ú]+)+"
)

_TERMOS_NORMATIVOS_PRESERVADOS = (
    "termo de compromisso",
    "estágio obrigatório",
    "estágio curricular",
    "seguro de acidentes pessoais",
    "acidentes pessoais",
    "coordenação de estágios",
    "coordenação de curso",
    "coordenação",
    "time de estágio",
    "time de estágios",
    "time de convênios",
    "base de conhecimento",
    "campo de estágio",
    "cadastro de empresa",
    "supervisor de campo",
    "supervisor acadêmico",
    "responsável legal",
    "instituição de ensino",
    "ensino fundamental",
    "serviço social",
    "ficha de coleta de dados",
    "guia de instruções",
    "formações acadêmicas",
    "declaração de dispensa",
)
"""Termos do domínio que nunca são nome próprio, mesmo em linha de tabela.

Sem esta lista, a máscara de nomes cobriria "Termo de Compromisso" ou
"Seguro de Acidentes Pessoais" — que são o assunto normativo do trecho, e
não quem o exemplifica. Os termos vêm do `CONTEXT.md` e dos títulos do
próprio Manual.
"""


def e_contato_da_coordenacao(titulo: str, corpo: str) -> bool:
    """Diz se o trecho indica o contato da Coordenação de Estágios.

    Só vale o contato **da Coordenação**: o trecho precisa nomear a
    Coordenação e indicar contato (`contato`, `fale conosco`, `canal`). Um
    trecho que pede "e-mail do Aluno" ou cita a Coordenação sem contato não
    abre exceção — e é por isso que a condição é a conjunção, e não cada
    metade sozinha.
    """
    texto = f"{titulo}\n{corpo}".lower()
    if "coordenação" not in texto:
        return False
    return "contato" in texto or "fale conosco" in texto or "canal" in texto


def _e_linha_de_tabela(linha: str) -> bool:
    """Diz se a linha tem cara de tabela: separador ou coluna espaçada."""
    return any(marca in linha for marca in _MARCADOR_TABELA) or bool(
        _ESPACOS_DE_COLUNA.search(linha)
    )


def _mascarar_nome_proprio(candidato: str) -> str:
    """Mantém o termo normativo e mascara o nome próprio de exemplo."""
    if any(termo in candidato.lower() for termo in _TERMOS_NORMATIVOS_PRESERVADOS):
        return candidato
    logger.debug("Nome próprio em tabela mascarado: %r.", candidato)
    return MARCADOR


def _mascarar_nomes_em_tabelas(texto: str) -> str:
    """Mascara nomes próprios só em linha com cara de tabela.

    Nome próprio em texto corrido não é mascarado: fora de tabela, "Escola"
    ou "João" pode ser o assunto do exemplo didático que o trecho explica —
    e tirar o assunto do trecho é tirar a resposta. Em tabela, sequência de
    nome é dado de captura (Aluno de exemplo), e aí mascara.
    """
    linhas: list[str] = []
    for linha in texto.splitlines():
        if _e_linha_de_tabela(linha):
            linha = _NOME_PROPRIO.sub(lambda m: _mascarar_nome_proprio(m.group(0)), linha)
        linhas.append(linha)
    return "\n".join(linhas)


def mascarar(texto: str, *, preservar_contato: bool = False) -> str:
    """Aplica a máscara de dados ilustrativos e devolve o texto indexável.

    Com `preservar_contato`, telefone e e-mail passam intactos: é a exceção
    do contato da Coordenação de Estágios, e quem decide é o `chunks.py` pela
    regra de `e_contato_da_coordenacao` — nunca este módulo sozinho.
    """
    mascarado = texto
    if not preservar_contato:
        mascarado = _EMAIL.sub(MARCADOR, mascarado)
    mascarado = _CNPJ.sub(MARCADOR, mascarado)
    mascarado = _CPF.sub(MARCADOR, mascarado)
    if not preservar_contato:
        mascarado = _TELEFONE.sub(MARCADOR, mascarado)
    mascarado = _APOLICE.sub(MARCADOR, mascarado)
    mascarado = _VIGENCIA_COM_DATA.sub(MARCADOR, mascarado)
    mascarado = _MATRICULA.sub(MARCADOR, mascarado)
    mascarado = _mascarar_nomes_em_tabelas(mascarado)
    if mascarado != texto:
        logger.debug("Trecho com dado ilustrativo mascarado para o índice.")
    return mascarado
