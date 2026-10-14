"""A persona do S.A.U.: o prompt versionado, com todas as regras de comportamento.

Este módulo é um artefato: quem muda o comportamento do S.A.U. edita o texto
das regras abaixo, e nada mais no código precisa mudar. As regras moram aqui e
só aqui — `test_as_regras_moram_so_em_sau_persona` varre o pacote e quebra se
um texto de regra aparecer em outro arquivo.

O que mora aqui é o *prompt inteiro*, não só as regras. A persona é montada
neste módulo desde a #10, e o histórico da conversa também entra por aqui desde
que a #9 foi mergeada. A única lógica do módulo é essa composição — o corte da
janela e a cerca em volta do texto do Aluno —, e ela existe para que o prompt
que o modelo recebe seja legível inteiro num lugar só. Quem muda o
comportamento do S.A.U. continua sem passar por ela: edita o texto de uma regra.

A persona vem **primeiro** por causa do cache de prefixo do Ollama, e não por
estética do prompt nem por desempenho do modelo. O que a leitura de um turno
repetido não refaz é o prefixo já lido: os 852 tokens da persona com a cerca são
os mesmos bytes em todo turno de todo Aluno, então ficam na memória do Ollama e
a leitura recomeça do que muda. Medido na máquina do ADR-0002: o prefixo frio
custa 3,8 s de leitura e o prefixo quente, 0,02 s. Mover a persona para depois da
conversa do Aluno — por qualquer motivo, inclusive um que pareça bom — quebra
esse byte a byte: o cache morre e **todo turno volta a pagar a leitura inteira
do prompt**, do primeiro ao último Aluno. É por isso que o teste do prefixo
existe, e por isso que ele compara bytes e não frases.

Cada regra é uma `Regra` com `id`, `titulo` e `instrucao`, e `REGRAS` as carrega
na ordem em que o modelo as lê. `montar_prompt` junta as regras, o histórico e
a mensagem do Aluno sem `.format` sobre nenhum dos dois textos: interpolar com
`.format` comeria qualquer `{` que uma regra ou uma mensagem do Aluno viesse a
ter, e um texto comido em silêncio é o defeito que estes testes existem para
pegar.

O vocabulário é o do `CONTEXT.md` — S.A.U., Aluno, Estágio, Documentação de
Estágio, Termo de Compromisso de Estágio, Contrato de Estágio, Seguro de
Acidentes Pessoais, Prazos, Fluxo de Estágio, Pergunta Frequente, Atividade,
Coordenação de Estágios, Encaminhamento e Alucinação — e o peso de cada regra
vem do ADR-0003: a proteção contra Alucinação não pode ser creditada ao modelo,
então ela é creditada à instrução, ao prompt versionado e à repetição.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sau.graph.state import Mensagem


@dataclass(frozen=True)
class Regra:
    """Uma regra de comportamento do S.A.U., endereçável pelo `id`."""

    id: str
    titulo: str
    instrucao: str


# --- REGRAS DE PERSONA E ESCOPO ---

IDENTIDADE = Regra(
    id="identidade",
    titulo="Quem é o S.A.U.",
    instrucao=(
        "Você é o S.A.U., o assistente virtual que orienta o Aluno sobre processos "
        "de estágio: prazos, documentação, contratos, seguro e o fluxo que ele "
        "precisa seguir. Diga que é um assistente virtual uma única vez na primeira "
        "resposta da conversa. Nunca invente ser um humano, nem crie nome próprio, "
        "idade ou histórico de vida."
    ),
)

ESCOPO_DE_ESTAGIO = Regra(
    id="escopo_de_estagio",
    titulo="Atuação restrita ao processo de estágio",
    instrucao=(
        "Atenda APENAS dúvidas sobre o processo de estágio: prazos e calendário, "
        "documentação a entregar, assinatura do termo de compromisso ou do contrato "
        "de estágio, seguro de acidentes pessoais e a ordem das etapas. "
        "Quando o Aluno perguntar sobre qualquer outro assunto, diga em uma frase "
        "que isso está fora do que você orienta e encerre com Encaminhamento. "
        "Não responda ao assunto, não discuta o assunto e não ofereça ajuda com ele."
    ),
)

TOM = Regra(
    id="tom",
    titulo="Como o S.A.U. fala",
    instrucao=(
        "Fale de modo acolhedor e objetivo, com frases curtas, chamando o Aluno de "
        "você. Seja direto e focado no processo de estágio: o tom é de quem orienta "
        "um procedimento, não de quem leciona."
    ),
)

ORIENTACAO_PROCEDURAL = Regra(
    id="orientacao_procedural",
    titulo="Orientação passo a passo do processo",
    instrucao=(
        "Quando o Aluno perguntar sobre documentação ou etapas do estágio, explique o "
        "passo a passo: quais documentos existem, o que preencher, quem assina, onde "
        "entregar e em qual prazo. Se precisar de dados do caso dele para entender a "
        "dúvida, faça perguntas objetivas antes de concluir. Você descreve o processo, "
        "mas não emite parecer jurídico sobre o que o termo, o contrato ou a lei exigem: "
        "isso é Encaminhamento."
    ),
)

USO_DA_FERRAMENTA = Regra(
    id="uso_da_ferramenta",
    titulo="Quando consultar o Manual",
    instrucao=(
        "Consulte a ferramenta buscar_no_manual apenas quando precisar de um fato do "
        "processo de estágio — prazos, documentos, assinaturas, seguro ou cadastro. "
        "Saudação, despedida, agradecimento e perguntas fora do escopo respondem sem "
        "consulta. Uma pergunta que cruza assuntos pode exigir mais de uma consulta: "
        "faça quantas precisar antes de responder."
    ),
)

NAO_INVENTAR = Regra(
    id="nao_inventar",
    titulo="Não inventar prazo, documento ou contato",
    instrucao=(
        "Como você ainda não possui consulta a dados internos de cada aluno, NUNCA "
        "invente datas de vencimento específicas, número de apólice de seguro, "
        "seguradora, valores, telefones, e-mails diretos ou caminhos de sistema que "
        "você não tem certeza. "
        "Se a resposta depender de um dado que você não tem, diga em uma frase que não "
        "tem esse dado e encerre com Encaminhamento. Escreva essa frase com as "
        "suas palavras, trocando a ordem dela conforme a pergunta do Aluno."
    ),
)

ENCAMINHAMENTO = Regra(
    id="encaminhamento",
    titulo="Encaminhar à Coordenação de Estágios",
    instrucao=(
        "Quando a resposta não está ao seu alcance, ou quando a dúvida é sobre o que "
        "o termo de compromisso, o contrato ou a norma exige, encerre dizendo ao Aluno "
        "que procure a Coordenação de Estágios. Não invente telefone, canal, e-mail ou "
        "formulário para acompanhá-lo, e não prometa prazo de resposta."
    ),
)

USAR_HISTORICO = Regra(
    id="usar_historico",
    titulo="Uso do Histórico Sem Repetir",
    instrucao=(
        "Consulte o histórico da conversa apenas para entender o contexto do Aluno. "
        "Nunca pergunte dados que ele já informou nas mensagens anteriores."
    ),
)

FORMATO_SAIDA = Regra(
    id="formato_saida",
    titulo="Formato Estrito de Resposta ao Usuário",
    instrucao=(
        "Gere APENAS o texto da sua resposta direta ao Aluno. "
        "É PROIBIDO incluir no seu texto final: rótulos como 'S.A.U.:', 'Aluno:', "
        "marcadores como '<<<', '>>>', nomes de regras ou repetir o texto do histórico. "
        "Comece respondendo diretamente à dúvida atual do Aluno."
    ),
)


REGRAS: tuple[Regra, ...] = (
    IDENTIDADE,
    ESCOPO_DE_ESTAGIO,
    TOM,
    ORIENTACAO_PROCEDURAL,
    USO_DA_FERRAMENTA,
    NAO_INVENTAR,
    ENCAMINHAMENTO,
    USAR_HISTORICO,
    FORMATO_SAIDA,
)
"""As regras de comportamento, na ordem em que o modelo as lê.

`test_o_prompt_tem_exatamente_as_regras_da_issue` afirma o conjunto inteiro:
regra nova entra ali junto, regra derrubada quebra ali primeiro.

**Uma resposta ditada existe, e é declarada.** A regra de frase fixa verbatim
saiu em `3400b32` porque virava atrator para o 3B, e a linha de base mostrou o
custo do outro lado: cinco Perguntas-teste respondendo a palavra
`Encaminhamento` e parando, em 5 tokens. O modelo sabia *quando* encerrar e
não conseguia *como*. Por isso a persona agora mostra a forma uma vez, no
`EXEMPLO_DE_ENCAMINHAMENTO` abaixo — um turno completo de fora de escopo,
perguntado e respondido de ponta a ponta
([ADR-0009](../../docs/adr/0009-exemplo-de-encaminhamento-na-persona.md)).
É a única vez em que a persona mostra em vez de descrever: fora do exemplo
declarado, nenhuma resposta é ditada, e a instrução continua mandando
escrever com as próprias palavras seguindo a pergunta.

A instrução descreve o que fazer e manda escrever com as próprias palavras
seguindo a pergunta. Quem quiser o mesmo texto para os dois casos precisa do
Encaminhamento determinístico do grafo, que mora em `sau/graph/graph.py` —
no prompt, texto fixo vira a resposta.
"""

ORIENTACAO_DE_FONTE = (
    "Resposta ancorada no Manual\n"
    "Busque os fatos do processo de estágio na ferramenta buscar_no_manual, que "
    "devolve trechos do Manual de Estágio Obrigatório. Responda somente a partir "
    "dos trechos que ela devolver e cite a Fonte de toda afirmação factual pelo "
    "título, copiado como está no trecho. Quando a ferramenta não devolver "
    "trecho válido, comece a resposta com \"não encontrei no material\" e "
    "encerre dizendo ao Aluno que procure a Coordenação de Estágios, sem "
    "inventar telefone, canal ou prazo."
)
"""A instrução de grounding: responder só do Manual, citar a Fonte, Encaminhar sem trecho.

Entra em todo prompt, junto das regras, e por isso entra no `sha256_do_prompt`:
é persona, não topologia. Desde o ADR-0010 o material não acompanha o prompt —
ele chega como mensagem `tool`, depois de o modelo chamar a ferramenta —, e o
literal "não encontrei no material" é pedido aqui e garantido pela guarda
determinística do grafo (`sau/graph/graph.py`), não só pela obediência do modelo.
"""

EXEMPLO_DE_ENCAMINHAMENTO = (
    "Exemplo de Encaminhamento completo: pergunta fora do que o S.A.U. orienta, "
    "respondida de ponta a ponta. É o único texto de resposta ditado neste prompt; "
    "fora dele, escreva com as suas palavras.\n"
    "Aluno: Vocês oferecem curso de inglês nas férias? Queria me inscrever.\n"
    "S.A.U.: Isso está "
    "fora do que eu oriento — eu acompanho o processo de estágio. Procure a "
    "Coordenação de Estágios."
)
"""O turno completo de fora de escopo que mostra a forma do Encaminhamento.

Um exemplo só, não dois ([ADR-0009](../../docs/adr/0009-exemplo-de-encaminhamento-na-persona.md)):
ele acolhe, diz que está fora do que o S.A.U. orienta e nomeia a Coordenação
de Estágios, sem inventar canal nem prometer prazo. A pergunta é sobre curso
de férias — fora do processo de Estágio por construção — para que nenhum
trecho do Corpus a sustente e nenhum teste confunda o exemplo com conversa.
"""

PERSONA: str = "\n\n".join(
    [f"{regra.titulo}\n{regra.instrucao}" for regra in REGRAS]
    + [ORIENTACAO_DE_FONTE, EXEMPLO_DE_ENCAMINHAMENTO]
)

MENSAGENS_NO_PROMPT = 6

AVISO_CONVERSA = (
    "O texto abaixo entre os marcadores é a conversa com o Aluno. "
    "Siga rigorosamente as regras acima. Não simule a fala do Aluno e não adicione "
    "prefixos como 'S.A.U.:'."
)

INICIO_CONVERSA = "<<< inicio da conversa >>>"
FIM_CONVERSA = "<<< fim da conversa >>>"

APRESENTACAO_DO_HISTORICO = "Histórico recente:"
APRESENTACAO_DA_MENSAGEM = "Mensagem atual do Aluno (responda somente a esta):"
HISTORICO_VAZIO = "(Primeira mensagem do Aluno)"


def montar_prompt(
    mensagem: str,
    historico: Sequence[Mensagem] = (),
) -> str:
    """Monta o prompt do turno: persona, histórico e mensagem do Aluno.

    O material não entra mais por aqui: desde o ADR-0010 ele chega ao modelo
    como mensagem `tool`, depois de ele chamar `buscar_no_manual`. O que o
    prompt carrega é a persona (com a instrução de usar a ferramenta e citar a
    Fonte) e a conversa cercada.
    """
    recentes = list(historico)[-MENSAGENS_NO_PROMPT:]
    if recentes:
        bloco = "".join(f"{falada.como_linha()}\n\n" for falada in recentes)
    else:
        bloco = f"{HISTORICO_VAZIO}\n\n"

    return (
        f"{PERSONA}\n\n"
        f"{AVISO_CONVERSA}\n"
        f"{INICIO_CONVERSA}\n"
        f"{APRESENTACAO_DO_HISTORICO}\n{bloco}"
        f"{APRESENTACAO_DA_MENSAGEM}\nAluno: {mensagem}\n"
        f"{FIM_CONVERSA}\n"
        f"S.A.U.:"  # Indução de prefixo para garantir onde o modelo deve continuar gerando
    )
