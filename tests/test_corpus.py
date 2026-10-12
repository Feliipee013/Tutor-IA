"""Testes do diretório do Manual, `corpus/` (issue #40, ADR-0011).

O que se prova aqui é o contrato novo do diretório: que ele guarda o PDF do
Manual de Estágio Obrigatório do Polo 2026/2 fora do git, com o README
dizendo qual arquivo colocar e o que acontece sem ele.

Justificativa da reescrita (a #40 quebrou estes testes de propósito): até a
#40 este diretório tinha quatro `.md` sintéticos do instrumento, e cada teste
antigo provava o conteúdo deles — seções por Pergunta Frequente, títulos
únicos, defeitos plantados. A #40 remove os sintéticos e o Manual em PDF vira
a base, então provar `.md` aqui seria provar material que não existe mais. A
bateria que media sobre aquele Corpus será reconstruída na #38; o que este
arquivo guarda é o contrato que a #40 entrega.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

_RAIZ = Path(__file__).resolve().parent.parent
_CORPUS = _RAIZ / "corpus"
_PDF_ESPERADO = "manual-estagio-obrigatorio-polo-2026-2.pdf"


def test_corpus_tem_readme_e_gitkeep_versionados() -> None:
    assert (_CORPUS / "README.md").is_file()
    assert (_CORPUS / ".gitkeep").is_file()


def test_nenhum_md_sintetico_no_corpus() -> None:
    """Os sintéticos saíram na #40: a base agora é o PDF do Manual."""
    assert list(_CORPUS.glob("*.md")) == [(_CORPUS / "README.md")]


def test_readme_diz_qual_pdf_colocar_e_o_que_acontece_sem_ele() -> None:
    texto = (_CORPUS / "README.md").read_text(encoding="utf-8")

    assert _PDF_ESPERADO in texto
    assert "corpus/README.md" in texto


def test_pdf_do_manual_esta_ignorado_pelo_git() -> None:
    """O PDF nunca entra no git: chega ao container por bind mount."""
    saida = subprocess.run(
        ["git", "check-ignore", "-q", f"corpus/{_PDF_ESPERADO}"],
        cwd=_RAIZ,
        check=False,
    )

    assert saida.returncode == 0, f"corpus/{_PDF_ESPERADO} não está ignorado"
