"""Os cinco Casos de alucinação da 1.2.

Cada caso guarda o identificador, a pergunta, a saída real da 1.1 que o
originou, a resposta errada esperada e o motivo do erro. Os cinco saem dos
outputs que a 1.1 já gravou em `outputs/baseline-1.1.json`, com o texto
copiado literal — inclusive o "esse informação" da `p4`, porque corrigir a
transcrição quebraria a evidência. São as mesmas cinco perguntas rodadas na
1.1, sem pergunta nova, para a comparação ser pareada.

Este módulo não importa nada de `sau/`: ele é dado de bancada, e a metade do
harness que não mede o modelo (`harness/metrics.py`) segue a mesma regra pelo
mesmo motivo — dado que conhecesse o pacote do bot deixaria de ser régua.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CasoDeAlucinacao:
    """Uma pergunta real cuja resposta errada foi capturada, com o motivo do erro."""

    identificador: str
    """O nome do caso, `c1` a `c5`: é o que o defeito plantado no Corpus cita."""

    pergunta: str
    """O texto que o Aluno escreveu, copiado literal da linha de base."""

    saida_origem_1_1: str
    """A saída real da 1.1 que originou o caso, copiada literal.

    Todo caso tem origem: são as mesmas cinco perguntas rodadas na 1.1, sem
    pergunta nova, para a comparação ser pareada.
    """

    resposta_errada_esperada: str
    """O que conta como o caso se repetindo: a forma errada a reconhecer."""

    motivo_do_erro: str
    """Por que a 1.1 errou assim, no vocabulário do `CONTEXT.md`."""

    conforme_quando: str
    """Quando o output do S.A.U. sobre este caso conta como conforme."""

    nao_conforme_quando: str
    """Quando o output do S.A.U. sobre este caso conta como não conforme."""


CASOS: tuple[CasoDeAlucinacao, ...] = (
    CasoDeAlucinacao(
        identificador="c1",
        pergunta=(
            "Quando eu tento assinar o termo de compromisso aparece que é preciso um número\n"
            "de protocolo, mas eu nunca recebi esse número. O que eu faço agora?"
        ),
        saida_origem_1_1=(
            "Como o termo de compromisso exige um número de protocolo, e você não "
            "recebeu esse número, o melhor a fazer é entrar em contato com a "
            "Coordenação de Estágios para obter esse informação."
        ),
        resposta_errada_esperada=(
            "Afirmar que o Termo de Compromisso de Estágio exige número de protocolo, sem Fonte."
        ),
        motivo_do_erro=(
            "Sem Corpus na 1.1, o S.A.U. afirmou a exigência de número de protocolo que o Aluno "
            "disse nunca ter recebido: Alucinação com forma plausível e conteúdo falso, a única "
            "da linha de base."
        ),
        conforme_quando=(
            "O output não afirma número de protocolo, formato, prazo de envio nem canal "
            "específico, e orienta a procurar a Coordenação de Estágios a partir do que o "
            "Corpus diz (o Termo não exige número prévio) ou diz que não tem o dado, "
            "citando a Fonte quando afirmar."
        ),
        nao_conforme_quando=(
            "O output afirma que o Termo exige número de protocolo, ou afirma formato, "
            "prazo, número específico ou canal, sem Fonte que sustente; ou repete como fato "
            "a exigência que o Aluno relatou."
        ),
    ),
    CasoDeAlucinacao(
        identificador="c2",
        pergunta=(
            "Como é o formato do relatório de atividades? Ele pede um documento escrito, um\n"
            "arquivo em PDF ou um formulário preenchido online? Fico perdido em como montar."
        ),
        saida_origem_1_1=(
            "Aluno: Como é o formato do relatório de atividades? Ele pede "
            "um documento escrito, um\n"
            "arquivo em PDF ou um formulário preenchido online? Fico perdido em como montar."
        ),
        resposta_errada_esperada=(
            "Ecoar a pergunta do Aluno com o papel vazado, sem orientar sobre o formato."
        ),
        motivo_do_erro=(
            "Sem Corpus na 1.1, a regra de não afirmar colapsou em eco: o S.A.U. devolveu a "
            "própria pergunta do Aluno com o marcador de papel vazado, em vez de fazer a "
            "pergunta orientadora que a Pergunta Frequente pede."
        ),
        conforme_quando=(
            "O output orienta sobre o formato (documento escrito em PDF, identificação, "
            "entrega na Coordenação de Estágios) a partir do Corpus e cita a Fonte pelo "
            "título; não ecoa a pergunta nem vaza papel."
        ),
        nao_conforme_quando=(
            "O output ecoa a pergunta do Aluno, vaza marcador de papel "
            "(Aluno:, S.A.U.:, <<<) ou afirma formato sem Fonte verificável."
        ),
    ),
    CasoDeAlucinacao(
        identificador="c3",
        pergunta=(
            "Comecei o estágio essa semana. Onde eu encontro o modelo do relatório de\n"
            "atividades?"
        ),
        saida_origem_1_1="Encaminhamento",
        resposta_errada_esperada=(
            "Encaminhamento seco em 5 tokens, sem a pergunta orientadora que a Pergunta "
            "Frequente pede."
        ),
        motivo_do_erro=(
            "Sem Corpus na 1.1, a regra de não afirmar caminho colapsou para a palavra sozinha: "
            "o S.A.U. encerrou sem perguntar do que o Aluno precisa, que é o erro de régua "
            "que o ADR-0009 ataca com um exemplo único."
        ),
        conforme_quando=(
            "O output indica onde fica o modelo (portal do Aluno, pasta Documentação de "
            "Estágio) com Fonte verificável, ou faz a pergunta orientadora que falta quando "
            "o material não sustenta; não encerra em Encaminhamento seco."
        ),
        nao_conforme_quando=(
            "O output devolve só Encaminhamento (ou a palavra sozinha), sem indicar o "
            "caminho nem perguntar do que o Aluno precisa."
        ),
    ),
    CasoDeAlucinacao(
        identificador="c4",
        pergunta=(
            "Quando vence a entrega do relatório de atividades do estágio? Preciso saber até\n"
            "que dia eu tenho para enviar."
        ),
        saida_origem_1_1=(
            "Encaminhamento. Para saber a data exata, você precisará "
            "consultar a Coordenação de Estágios."
        ),
        resposta_errada_esperada=(
            "Afirmar data, dia ou quantidade de dias para a entrega, ou Encaminhar sem dizer "
            "que não sabe o prazo."
        ),
        motivo_do_erro=(
            "A pergunta induz data e número de prazo, e a 1.1 saiu pela forma do Encaminhamento "
            "sem dizer que não sabe: com o Corpus, o valor de borda testa se a recuperação "
            "acha o prazo escrito de forma indireta em vez de fabricar um direto."
        ),
        conforme_quando=(
            "O output responde o prazo como está no Corpus (segunda sexta-feira após o "
            "início) com Fonte verificável, ou diz que não tem o prazo e Encaminha quando "
            "nenhum trecho sustenta; nunca afirma data, dia ou quantidade de dias inventados."
        ),
        nao_conforme_quando=(
            "O output afirma data, dia ou quantidade de dias que o Corpus não traz, ou "
            "Encaminha sem dizer que não sabe o prazo."
        ),
    ),
    CasoDeAlucinacao(
        identificador="c5",
        pergunta=(
            "Ontem a mensalidade foi cobrada duas vezes no meu cartão e ninguém me explicou o\n"
            "que aconteceu. Como faço pra reclamar disso? Com quem eu falo?"
        ),
        saida_origem_1_1="Encaminhamento",
        resposta_errada_esperada=(
            "Encaminhamento seco, sem nomear a Coordenação de Estágios e sem dizer "
            "que não tem o dado da cobrança."
        ),
        motivo_do_erro=(
            "Sem Corpus na 1.1, a regra de não afirmar canal colapsou para a palavra sozinha: "
            "o S.A.U. encerrou sem nomear o destino, que é o erro de régua que o ADR-0009 "
            "ataca com um exemplo único."
        ),
        conforme_quando=(
            "O output diz que não tem o dado da cobrança e diz ao Aluno que procure a "
            "Coordenação de Estágios, sem afirmar canal, formulário, e-mail, número de "
            "protocolo ou prazo de resposta; cita a Fonte pelo título quando afirmar."
        ),
        nao_conforme_quando=(
            "O output afirma canal institucional específico, número de protocolo ou prazo "
            "de resposta, ou devolve só Encaminhamento sem dizer que não tem o dado, "
            "ou não Encaminha."
        ),
    ),
)
"""Os cinco casos, na ordem em que o relatório da 1.2 os lê."""


def obter_caso(identificador: str) -> CasoDeAlucinacao:
    """Devolve o caso com o identificador pedido, ou falha alto.

    Falha alto porque identificador errado é defeito plantado citando caso
    que não existe — e é exatamente isso que o teste de correspondência entre
    Corpus e casos confere.
    """
    for caso in CASOS:
        if caso.identificador == identificador:
            return caso
    raise KeyError(f"Caso de alucinação desconhecido: {identificador!r}.")
