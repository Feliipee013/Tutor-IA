"""Medição da recuperação híbrida sobre as perguntas cruzadas x1–x5 (issue #39).

Transcreve as cinco cruzadas de `perguntas-teste/bateria-manual.md`, roda
`buscar_no_indice` (vetorial puro) e `buscar_hibrida_no_indice` (híbrido
lexical + vetorial) sobre o Chroma do Manual, calcula quantas Fontes
esperadas aparecem no top-k por caminho (recall) e imprime a tabela.

Grava `docs/medicao-hibrido/resultado.md` com as condições (modelo de
embedding, `sha256` do PDF, limiar, k). Não inventa número: sem o PDF e sem
o Ollama, registra a limitação e para.

Uso:
    python docs/medicao-hibrido/medir.py --pdf corpus/manual-...-2026-2.pdf
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from sau.config import carregar_configuracao
from sau.manual.indice import (
    buscar_hibrida_no_indice,
    buscar_no_indice,
    carregar_ou_indexar,
    sha256_do_pdf,
)
from sau.rag.embed import MODELO_EMBEDDING_PADRAO, ClienteEmbedding


@dataclass(frozen=True)
class CasoCruzado:
    """Uma pergunta cruzada da bateria: id, pergunta e Fontes esperadas."""

    id: str
    pergunta: str
    fontes_esperadas: list[str]


CASOS: list[CasoCruzado] = [
    CasoCruzado(
        id="x1",
        pergunta=(
            "Sou de Enfermagem. A empresa precisa ter convênio com a faculdade? "
            "E qual supervisor eu preciso cadastrar — o de campo e o acadêmico?"
        ),
        fontes_esperadas=[
            "CAMPO DE ESTÁGIO | EMPRESA (p.6–7)",
            "SUPERVISOR ACADÊMICO (p.15)",
            "SUPERVISOR DE CAMPO (p.16)",
        ],
    ),
    CasoCruzado(
        id="x2",
        pergunta=(
            "Sou de Serviço Social. O supervisor de campo precisa de vínculo com a "
            "empresa? Por que a empresa não aparece para associar? E quantas horas "
            "ele pode ter?"
        ),
        fontes_esperadas=[
            "SUPERVISOR DE CAMPO (p.16)",
            "CADASTRO DE SUPERVISORES (p.18)",
            "ALTERAÇÃO DA CARGA HORARIA DO SUP. DE CAMPO DE SERVIÇO SOCIAL (p.29)",
        ],
    ),
    CasoCruzado(
        id="x3",
        pergunta=(
            "Quanto tempo o time leva para liberar o Termo de Compromisso e quanto "
            "para validar depois que eu envio? E existe um prazo para eu enviar a "
            "documentação?"
        ),
        fontes_esperadas=[
            "PRAZOS PARA ANÁLISE DOS CADASTROS NO COLABORAR (p.4)",
            "EDIÇÃO DO ESTÁGIO NO AVA (p.41)",
            "ENVIO DO TERMO DE COMPROMISSO E CADASTRO DE EMPRESA (p.46)",
        ],
    ),
    CasoCruzado(
        id="x4",
        pergunta=(
            "Quando eu mexo no cadastro da empresa, qual a diferença entre colocar "
            "em 'reedição' e fazer 'alteração de responsável'? Qual eu uso em cada caso?"
        ),
        fontes_esperadas=[
            "CADASTRO DA EMPRESA EM REEDIÇÃO (p.11)",
            "ALTERAÇÃO DE RESPONSÁVEL (p.12–13)",
            "REEDIÇÃO DE ALTERAÇÃO DE RESPONSÁVEL (p.14)",
        ],
    ),
    CasoCruzado(
        id="x5",
        pergunta=(
            "A empresa quer usar o modelo de Termo de Compromisso dela. O que ele "
            "precisa conter, como eu envio e quem assina?"
        ),
        fontes_esperadas=["TERMO DE COMPROMISSO MODELO EMPRESA (p.51–54)"],
    ),
]


def _paginas_da_fonte(fonte: str) -> set[int]:
    """As páginas de uma Fonte citável: "título (p.6–7)" vira {6, 7}.

    A comparação é por página, e não pelo título, porque o título do chunk é a
    primeira linha da página do PDF: um título de slide que quebra linha chega
    truncado ("TERMO DE COMPROMISSO MODELO" para "(Modelo Empresa)"), e casar o
    título inteiro da bateria subestimaria o recall. A página é o identificador
    estável dos dois lados da Fonte.
    """
    if "(p." not in fonte:
        return set()
    faixa = fonte.split("(p.", 1)[1].rstrip(")").strip()
    faixa = faixa.replace("\u2013", "-").replace("\u2014", "-")
    if "-" in faixa:
        inicio, _, fim = faixa.partition("-")
        return set(range(int(inicio), int(fim) + 1))
    return {int(faixa)}


def _paginas_obtidas(trechos: list[object]) -> set[int]:
    return {int(trecho.pagina) for trecho in trechos}  # type: ignore[attr-defined]


def _recall(esperadas: list[str], obtidas: set[int]) -> int:
    """Quantas Fontes esperadas têm a página entre as páginas obtidas."""
    return sum(1 for esperada in esperadas if _paginas_da_fonte(esperada) & obtidas)


def _ocr_disponivel() -> bool:
    """Diz se o tesseract está instalado, sem rodar OCR nenhum.

    Sem o binário, a ingestão segue só com o texto nativo e os slides em
    imagem entram vazios no índice: é a causa provável do recall baixo das
    cruzadas cujo conteúdo é figura, e por isso entra nas condições.
    """
    try:
        import pytesseract

        pytesseract.get_tesseract_version()
    except Exception:
        return False
    return True


def _montar_relatorio(
    *,
    vetorial: list[tuple[str, int, int]],
    hibrido: list[tuple[str, int, int]],
    total_esperado: int,
    condicoes: list[str],
    limitacoes: list[str],
) -> str:
    linhas = [
        "# Medição da recuperação híbrida (fase avançada)\n\n",
        "**Objetivo:** comparar vetorial puro vs híbrido (BM25 + RRF) nas perguntas "
        "cruzadas x1–x5 da bateria do Manual.\n\n",
        "## Condições\n\n",
    ]
    linhas += [f"- {condicao}\n" for condicao in condicoes]
    linhas.append("\n## Resultados por pergunta (recall por Fonte esperada)\n\n")
    linhas.append("| id | vetorial (Fontes presentes/esperadas) | híbrido (Fontes presentes/esperadas) | delta |\n")
    linhas.append("| --- | --- | --- | --- |\n")
    soma_vet = 0
    soma_hib = 0
    for (id_, v, total), (_, h, _) in zip(vetorial, hibrido, strict=True):
        soma_vet += v
        soma_hib += h
        linhas.append(f"| {id_} | {v}/{total} | {h}/{total} | {h - v:+d} |\n")

    linhas.append("\n## Agregado\n\n")
    linhas.append(f"- Recall vetorial: {soma_vet}/{total_esperado}\n")
    linhas.append(f"- Recall híbrido: {soma_hib}/{total_esperado}\n")
    linhas.append(f"- Delta: {soma_hib - soma_vet:+d}\n")

    linhas.append("\n## Veredito\n\n")
    if soma_hib > soma_vet:
        linhas.append("O híbrido mostra ganho de recall nas cruzadas x1–x5.\n")
    elif soma_hib == soma_vet:
        linhas.append("Sem variação de recall nas cruzadas x1–x5 nestas condições.\n")
    else:
        linhas.append("O híbrido apresentou recall inferior neste ensaio.\n")

    linhas.append("\n## Limitações\n\n")
    linhas += [f"- {limitacao}\n" for limitacao in limitacoes]
    return "".join(linhas)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Mede a recuperação híbrida das cruzadas x1–x5.")
    parser.add_argument("--pdf", type=Path, default=None, help="Caminho do PDF do Manual.")
    parser.add_argument("--chroma", type=Path, default=None, help="Diretório do Chroma.")
    parser.add_argument("--colecao", type=str, default=None, help="Nome da coleção no Chroma.")
    parser.add_argument("--k", type=int, default=None, help="Quantos trechos por busca.")
    parser.add_argument("--limiar", type=float, default=None, help="Limiar (registrado nas condições).")
    parser.add_argument(
        "--ollama-url",
        type=str,
        default=None,
        help="Base URL do Ollama (padrão: OLLAMA_BASE_URL ou http://localhost:11434).",
    )
    parser.add_argument(
        "--modelo-embedding",
        type=str,
        default=None,
        help="Modelo de embedding (padrão: nomic-embed-text).",
    )
    args = parser.parse_args(argv)

    config = carregar_configuracao()
    pdf = args.pdf or Path(config.manual_pdf_caminho)
    chroma = args.chroma or Path(config.manual_chroma_caminho)
    colecao = args.colecao or config.manual_colecao
    k = args.k or config.manual_k_padrao
    limiar = args.limiar if args.limiar is not None else config.manual_limiar_similaridade
    modelo = args.modelo_embedding or MODELO_EMBEDDING_PADRAO
    ollama_url = (
        args.ollama_url
        or ("http://localhost:11434" if config.ollama_base_url.startswith("http://host.docker") else config.ollama_base_url)
    )

    saida = Path(__file__).resolve().parent / "resultado.md"
    ocr_ok = _ocr_disponivel()

    if not pdf.exists():
        saida.write_text(
            _montar_relatorio(
                vetorial=[],
                hibrido=[],
                total_esperado=0,
                condicoes=[f"PDF ausente: esperado em {pdf}."],
                limitacoes=[
                    "Sem o PDF do Manual não há medição; nenhum número foi produzido.",
                    "O PDF é material institucional e não entra no git (ver corpus/README.md).",
                ],
            ),
            encoding="utf-8",
        )
        print(f"PDF ausente em {pdf}; resultado.md registra a limitação.", file=sys.stderr)
        return 1

    cliente = ClienteEmbedding(ollama_url, modelo)
    print(f"Indexando {pdf.name} em {chroma} (coleção {colecao})...", file=sys.stderr)
    estado = carregar_ou_indexar(pdf, chroma, colecao, cliente)

    condicoes = [
        f"PDF: {pdf.name}",
        f"sha256 do PDF: {sha256_do_pdf(pdf)}",
        f"sha256 indexado: {estado.pdf_sha256}",
        f"Índice: {chroma}",
        f"Coleção: {colecao}",
        f"Modelo de embedding: {modelo}",
        f"Ollama: {ollama_url}",
        f"k: {k}",
        f"limiar (registrado): {limiar}",
        f"chunks no índice: {estado.total_chunks}",
        f"OCR (tesseract) disponível: {'sim' if ocr_ok else 'não'}",
    ]
    limitacoes = [
        "O PDF do Manual é material institucional e não entra no git (ver corpus/README.md).",
        "A medição exige o Ollama no host com o modelo de embedding.",
    ]
    if not ocr_ok:
        limitacoes.append(
            "Sem tesseract no host, os slides em imagem entraram sem OCR: só o texto "
            "nativo foi indexado. Isso reduz o recall absoluto das perguntas cujo "
            "conteúdo mora em figura, e vale para os dois caminhos."
        )

    vetorial: list[tuple[str, int, int]] = []
    hibrido: list[tuple[str, int, int]] = []
    total_esperado = 0
    for caso in CASOS:
        total_esperado += len(caso.fontes_esperadas)
        trechos_vetoriais = buscar_no_indice(chroma, colecao, caso.pergunta, cliente, k=k)
        trechos_hibridos = buscar_hibrida_no_indice(chroma, colecao, caso.pergunta, cliente, k=k)
        obtidos_vetoriais = _paginas_obtidas(list(trechos_vetoriais))
        obtidos_hibridos = _paginas_obtidas(list(trechos_hibridos))
        v = _recall(caso.fontes_esperadas, obtidos_vetoriais)
        h = _recall(caso.fontes_esperadas, obtidos_hibridos)
        vetorial.append((caso.id, v, len(caso.fontes_esperadas)))
        hibrido.append((caso.id, h, len(caso.fontes_esperadas)))
        print(f"{caso.id}: vetorial {v} | híbrido {h}")

    relatorio = _montar_relatorio(
        vetorial=vetorial,
        hibrido=hibrido,
        total_esperado=total_esperado,
        condicoes=condicoes,
        limitacoes=limitacoes,
    )
    saida.write_text(relatorio, encoding="utf-8")
    print(relatorio)
    print(f"resultado.md gravado em {saida}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
