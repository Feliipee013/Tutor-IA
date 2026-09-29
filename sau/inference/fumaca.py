"""Prova de fumaça do modelo: ele responde de dentro do container?

Este script é a resposta direta ao segundo critério da #7 — "uma requisição de
dentro do container ao Ollama no host devolve resposta". Ele roda as checagens
de pré-requisito, manda uma pergunta ao modelo e mostra quanto tempo cada
etapa custou. Se qualquer uma das duas coisas falhar, ele sai com erro.

Três decisões que valem entrar no código:

- **Falha alta em CPU, por padrão.** Um Ollama servindo em CPU devolve um tempo
  médio plausível, e é por isso que a medição da #3 chama o número de
  velocidade de "o critério mais fácil de cumprir errado". Sem GPU, o script
  para. Quem realmente quiser medir em CPU passa `--permitir-cpu` e o número
  sai marcado como número de CPU — o mesmo caminho do `medir.py`.
- **Não lê `perguntas-teste/`.** As 10 Perguntas-teste são a régua da #12 e o
  arquivo está congelado; a fumaça só precisa provar que volta texto. Para
  mandar uma Pergunta-teste de verdade, use `--de-arquivo` com o texto dela
  copiado para um arquivo.
- **A resposta do modelo vai no log, não aqui.** O cliente escreve em INFO, e
  o log é o que a #7 pede. O bloco impresso no fim é o relatório de tempos,
  que é o que este script tem a mais.

Uso:

    python -m sau.inference.fumaca
    python -m sau.inference.fumaca --repeticoes 3
    python -m sau.inference.fumaca --pergunta "..."
    python -m sau.inference.fumaca --de-arquivo pergunta.txt
    python -m sau.inference.fumaca --permitir-cpu
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final, NoReturn, Sequence

from sau.config import carregar_configuracao
from sau.inference.ollama import (
    ClienteOllama,
    ErroDeInferencia,
    Resposta,
    formatar_numero,
)
from sau.main import configurar_logging
from sau.prereqs import PreRequisitoError, executar_checagens

PERGUNTA_PADRAO: Final = "Em uma frase, o que você faz por um aluno?"
"""A pergunta da fumaça, quando ninguém manda nenhuma.

É sintética e não é uma Pergunta-teste. O que este script precisa provar é que
o modelo devolve texto, e uma Pergunta-teste aqueceria: a #12 mede as 10 com
condições fixas para comparar, e um número medido aqui com outra pergunta e sem
`temperature` nem `seed` não entraria naquela comparação — e ainda assim
apareceria ao lado dela.
"""

REPETICOES_PADRAO: Final = 1
"""Uma geração por padrão.

A separação entre o primeiro Aluno, que paga a carga do modelo, e os outros, que
não pagam, é o que o tempo de primeira resposta do ADR-0003 mede. Uma geração só
não separa nada; quem quiser ver as duas, passa `--repeticoes 3`.
"""


def falhar(mensagem: str) -> NoReturn:
    """Para a fumaça com o motivo, e sai com código diferente de zero."""
    print(f"\nFALHA: {mensagem}", file=sys.stderr)
    raise SystemExit(1)


def _analisar(argv: Sequence[str] | None = None) -> argparse.Namespace:
    analisador = argparse.ArgumentParser(
        description=(
            "Prova que o modelo escolhido responde de dentro do container, "
            "e mostra o tempo de cada etapa da geração."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    grupo = analisador.add_mutually_exclusive_group()
    grupo.add_argument(
        "--pergunta",
        default=None,
        help="texto da pergunta a mandar ao modelo",
    )
    grupo.add_argument(
        "--de-arquivo",
        default=None,
        metavar="CAMINHO",
        help="arquivo com o texto da pergunta",
    )
    analisador.add_argument(
        "--repeticoes",
        type=int,
        default=REPETICOES_PADRAO,
        help=f"gerações a fazer (padrão: {REPETICOES_PADRAO})",
    )
    analisador.add_argument(
        "--permitir-cpu",
        action="store_true",
        help=(
            "roda mesmo com o modelo em CPU. O padrão é exigir a GPU do host e "
            "parar, conforme o ADR-0002: um tempo médio em CPU é plausível e "
            "errado ao mesmo tempo. Com esta flag os tempos medidos são de CPU "
            "e não descrevem a máquina do ADR-0002."
        ),
    )
    return analisador.parse_args(argv)


@dataclass(frozen=True)
class Opcoes:
    """As opções da fumaça, já com o tipo que elas de fato têm.

    Vem do `argparse`, que entrega tudo como `Any`. A dataclass é o lugar onde
    cada campo ganha o tipo, e é também a lista do que a fumaça sabe fazer.
    """

    pergunta: str | None
    de_arquivo: str | None
    repeticoes: int
    permitir_cpu: bool

    @classmethod
    def de_argumentos(cls, argv: Sequence[str] | None = None) -> Opcoes:
        bruto = _analisar(argv)
        return cls(
            pergunta=bruto.pergunta,
            de_arquivo=bruto.de_arquivo,
            repeticoes=bruto.repeticoes,
            permitir_cpu=bruto.permitir_cpu,
        )


def ler_pergunta(args: Opcoes) -> str:
    """A pergunta vem da flag, do arquivo, ou do padrão.

    O arquivo é lido aqui e não pela flag porque o texto de uma Pergunta-teste
    tem várias linhas, e uma pergunta que chega ao modelo em uma linha só não é
    a mesma pergunta.
    """
    if args.pergunta is not None:
        texto = args.pergunta.strip()
        if not texto:
            falhar("--pergunta veio vazio")
        return texto

    if args.de_arquivo is not None:
        caminho = Path(args.de_arquivo)
        try:
            texto = caminho.read_text(encoding="utf-8").strip()
        except OSError as err:
            falhar(f"não consegui ler a pergunta em '{caminho}': {err}")
        if not texto:
            falhar(f"o arquivo '{caminho}' está vazio")
        return texto

    return PERGUNTA_PADRAO


def imprimir_bloco(resposta: Resposta, indice: int, total: int) -> None:
    """Imprime os tempos de uma geração.

    O campo mais importante é o primeiro: `ttft` é a régua do ADR-0003, e é a
    soma de `carga` com `prompt_eval`, mostrados ao lado para que dê para ver
    de onde veio o tempo. `carga` é zero quando o modelo já estava carregado, e
    é isso que separa o primeiro Aluno da madrugada dos outros.
    """
    if total > 1:
        print(f"\n--- geração {indice}/{total} ---")
    print("=" * 72)
    print("TEMPOS DA GERAÇÃO")
    print(f"  primeiro token (ttft):  {resposta.primeiro_token_segundos:.3f} s")
    print(f"  carga do modelo:         {resposta.carga_segundos:.3f} s")
    print(f"  leitura do prompt:      {resposta.avaliacao_prompt_segundos:.3f} s")
    print(f"  total:                  {resposta.segundos_totais:.3f} s")
    print(f"  velocidade:             {formatar_numero(resposta.tokens_por_segundo)} tok/s")
    print(f"  tokens gerados:         {formatar_numero(resposta.tokens_gerados)}")
    print(f"  parou porque:           {resposta.motivo_de_parada or '(o Ollama não informado)'}")
    if not resposta.concluida:
        # Uma geração que não terminou devolve texto pela metade, e texto pela
        # metade é o jeito mais fácil de um modelo parecer que respondeu.
        print("  ATENÇÃO: a geração NÃO terminou (done: false).")
    print("=" * 72)


def main(argv: Sequence[str] | None = None) -> int:
    args = Opcoes.de_argumentos(argv)
    if args.repeticoes < 1:
        falhar("--repeticoes precisa ser pelo menos 1")

    # O log sai no mesmo formato do serviço, com o prefixo [SAU], porque a
    # resposta do modelo é a evidência do quinto critério da #7 e o critério
    # fala em log. O prefixo é do S.A.U.; quem emitiu a linha é o nome do
    # módulo nela mesma, e não o prefixo.
    configurar_logging()

    pergunta = ler_pergunta(args)

    try:
        config = carregar_configuracao()
    except ValueError as err:
        falhar(str(err))

    if args.permitir_cpu:
        # `--permitir-cpu` autoriza esta execução, e só esta. A configuração
        # continua descrevendo a máquina; o que muda é a decisão de rodar
        # mesmo com o modelo em CPU.
        config = dataclasses.replace(config, ollama_allow_cpu=True)

    print("=" * 72)
    print("FUMAÇA DA INFERÊNCIA DO S.A.U.")
    print(f"  modelo:    {config.ollama_model}")
    print(f"  Ollama:    {config.ollama_base_url}")
    print(f"  repetições: {args.repeticoes}")
    print(f"  pergunta:  {pergunta}")
    print("=" * 72)

    try:
        executar_checagens(config)
    except PreRequisitoError as err:
        falhar(
            "a checagem de pré-requisito não passou, e sem ela não há o que "
            f"medir:\n{err}"
        )

    cliente = ClienteOllama(
        config.ollama_base_url,
        config.ollama_model,
        timeout=config.ollama_timeout,
    )

    respostas: list[Resposta] = []
    for indice in range(1, args.repeticoes + 1):
        try:
            resposta = cliente.responder(pergunta)
        except ErroDeInferencia as err:
            falhar(f"o modelo não respondeu:\n{err}")
        respostas.append(resposta)
        imprimir_bloco(resposta, indice, args.repeticoes)

    _imprimir_resumo(respostas, permitir_cpu=args.permitir_cpu)
    return 0


def _imprimir_resumo(respostas: list[Resposta], *, permitir_cpu: bool) -> None:
    """Fecha com a régua do ADR-0003: o primeiro token de cada geração.

    Quando há mais de uma geração, a primeira carregou o modelo e as outras não.
    A média das duas coisas seria um número que nenhuma delas pagou, então elas
    ficam separadas: a primeira é o que o primeiro Aluno da madrugada espera, e
    as outras são o que os Alunos seguintes esperam.
    """
    if len(respostas) > 1:
        print("=" * 72)
        print("TEMPO DE PRIMEIRA RESPOSTA (ttft)")
        print(f"  1ª geração, com a carga do modelo:  {respostas[0].primeiro_token_segundos:.3f} s")
        seguintes = [r.primeiro_token_segundos for r in respostas[1:]]
        media = sum(seguintes) / len(seguintes)
        print(f"  demais gerações, modelo carregado: {media:.3f} s (média de {len(seguintes)})")
        print("=" * 72)

    if permitir_cpu:
        print(
            "\nATENÇÃO: isto foi medido com --permitir-cpu. O número acima é de CPU "
            "e não descreve a máquina do ADR-0002."
        )


if __name__ == "__main__":
    raise SystemExit(main())
