"""As personas do S.A.U.: os prompts versionados, com todas as regras de comportamento.

Este módulo é um artefato: quem muda o comportamento do S.A.U. edita o texto
das regras abaixo, e nada mais no código precisa mudar. As regras moram aqui e
só aqui — `test_as_regras_moram_so_em_sau_persona` varre o pacote e quebra se
um texto de regra aparecer em outro arquivo.

São **duas** personas versionadas, e a separação é da #36. O **redator**
(`PERSONA`) é quem escreve a resposta ao Aluno: leva as regras de comportamento
e a `ORIENTACAO_DE_FONTE`, e **não** declara `tools` — ele redige a partir do
material que o roteador trouxe. O **roteador** (`PERSONA_DE_ROTEAMENTO`) é um
prompt enxuto que só decide se consulta o Manual antes de responder; é ele que
recebe o schema de `buscar_no_manual` em `tools`. O modelo pequeno não sustenta
as duas coisas num prompt só: com a persona inteira ele não chamava a
ferramenta (medido 0/6), e com o prompt enxuto passou a chamar.

O que mora aqui é o *prompt inteiro*, não só as regras. A persona é montada
neste módulo desde a #10, e o histórico da conversa também entra por aqui desde
que a #9 foi mergeada. A única lógica do módulo é essa composição — o corte da
janela e o mapeamento de cada fala para o seu papel nativo do `/api/chat`
(`aluno` vira `user`, `sau` vira `assistant`) —, e ela existe para que as
mensagens que o modelo recebe sejam legíveis inteiras num lugar só. Quem muda o
comportamento do S.A.U. continua sem passar por ela: edita o texto de uma regra.

A persona vai em mensagem `system`, **primeiro** e estável, por causa do cache
de prefixo do Ollama, e não por estética do prompt nem por desempenho do modelo.
O que a leitura de um turno repetido não refaz é o prefixo já lido: a mensagem
`system` com a persona é a mesma lista de bytes em todo turno de todo Aluno,
então fica na memória do Ollama e a leitura recomeça do que muda. Medido na
máquina do ADR-0002: o prefixo frio custa 3,8 s de leitura e o prefixo quente,
0,02 s. Mover a persona para depois da conversa do Aluno — por qualquer motivo,
inclusive um que pareça bom — quebra esse byte a byte: o cache morre e
**todo turno volta a pagar a leitura inteira do prompt**, do primeiro ao último
Aluno. É por isso que o teste do prefixo existe, e por isso que ele compara
bytes e não frases.

A conversa nunca foi cercada por acaso: a cerca textual (`<<<`, `Aluno:`,
`S.A.U.:` ao fim) induzia o modelo a continuar gerando a partir do prefixo
`S.A.U.:`, e esse rótulo vazava para a resposta do Aluno. Com os papéis
nativos não há cerca nem indução de prefixo — a última mensagem é sempre a
dúvida atual do Aluno em `user` — e nenhum texto do prompt carrega `<<<`,
`Aluno:` ou `S.A.U.:`, para que o modelo não tenha rótulo algum para ecoar.

Cada regra é uma `Regra` com `id`, `titulo` e `instrucao`, e `REGRAS` as carrega
na ordem em que o modelo as lê. `montar_mensagens` junta a persona em `system`,
o histórico mapeado para `user`/`assistant` e a mensagem do Aluno em `user`, sem
`.format` sobre nenhum dos dois textos: interpolar com `.format` comeria
qualquer `{` que uma regra ou uma mensagem do Aluno viesse a ter, e um texto
comido em silêncio é o defeito que estes testes existem para pegar.

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
    titulo="Identidade e Tom",
    instrucao=(
        "Você é o S.A.U., assistente virtual do processo de Estágio Obrigatório. "
        "Fale de modo acolhedor, objetivo e direto com o Aluno (usando 'você'), sem lecionar. "
        "Diga que é um assistente virtual apenas na primeira resposta da conversa. "
        "Nunca invente ser humano, nome próprio ou histórico."
    ),
)

ESCOPO_E_CORTESIA = Regra(
    id="escopo_e_cortesia",
    titulo="Escopo e Interação Inicial",
    instrucao=(
        "1. Para saudações, despedidas ou agradecimentos isolados: responda com "
        "gentileza em uma frase, sem citar trechos e sem encaminhar.\n"
        "2. Para assuntos fora do processo de estágio: diga em uma frase que o "
        "assunto está fora do que você orienta e indique a Coordenação de Estágios.\n"
        "3. Para dúvidas sobre estágio: responda passo a passo (documentos, "
        "etapas, prazos e assinaturas)."
    ),
)

NAO_INVENTAR_E_ENCAMINHAR = Regra(
    id="nao_inventar_e_encaminhar",
    titulo="Limites de Informação e Encaminhamento",
    instrucao=(
        "Como você não possui dados pessoais dos alunos, NUNCA invente datas "
        "específicas, números de apólice, "
        "telefones, e-mails ou prazos não presentes no material.\n"
        "Quando a dúvida exigir parecer normativo ou dado ausente, oriente o Aluno "
        "a procurar a Coordenação de Estágios "
        "(sem inventar canais específicos, telefones ou prazos de resposta)."
    ),
)

USAR_HISTORICO_E_FORMATO = Regra(
    id="usar_historico_e_formato",
    titulo="Formato de Saída",
    instrucao=(
        "Consulte o histórico apenas para entender o contexto e não pergunte dados já informados. "
        "Responda diretamente à dúvida atual do Aluno, sem repetir mensagens do "
        "histórico e sem listar nomes de regras."
    ),
)

REGRAS: tuple[Regra, ...] = (
    IDENTIDADE,
    ESCOPO_E_CORTESIA,
    NAO_INVENTAR_E_ENCAMINHAR,
    USAR_HISTORICO_E_FORMATO,
)
"""As regras de comportamento, na ordem em que o modelo as lê.

`test_o_prompt_tem_exatamente_as_regras_da_issue` afirma o conjunto inteiro:
regra nova entra ali junto, regra derrubada quebra ali primeiro.

**Duas formas ditadas existem, e são declaradas.** A regra de frase fixa verbatim
saiu em `3400b32` porque virava atrator para o 3B, e a linha de base mostrou o
custo do outro lado: cinco Perguntas-teste respondendo a palavra
`Encaminhamento` e parando, em 5 tokens. O modelo sabia *quando* encerrar e
não conseguia *como*. Por isso a persona mostra a forma duas vezes: no
`EXEMPLO_DE_ENCAMINHAMENTO` abaixo — um turno completo de fora de escopo,
perguntado e respondido de ponta a ponta
([ADR-0009](../../docs/adr/0009-exemplo-de-encaminhamento-na-persona.md)) —
e no `EXEMPLO_PARCIAL`, o turno de resposta com só parte sustentada.
São as únicas vezes em que a persona mostra em vez de descrever: fora dos
exemplos declarados, nenhuma resposta é ditada, e a instrução continua mandando
escrever com as próprias palavras seguindo a pergunta.

A instrução descreve o que fazer e manda escrever com as próprias palavras
seguindo a pergunta. Quem quiser o mesmo texto para os dois casos precisa do
Encaminhamento determinístico do grafo, que mora em `sau/graph/graph.py` —
no prompt, texto fixo vira a resposta.
"""

ORIENTACAO_DE_FONTE = (
    "Você é o assistente virtual do processo de Estágio Obrigatório (S.A.U.).\n"
    "Sua função é responder à dúvida do Aluno baseando-se EXCLUSIVAMENTE "
    "nos trechos fornecidos do Manual.\n\n"
    "<diretrizes_de_resposta>\n"
    "1. RESPOSTA ANCORADA: Responda usando SOMENTE as informações contidas "
    "nos trechos do Manual recebidos.\n"
    "2. CITAÇÃO OBRIGATÓRIA: Para cada afirmação baseada no material, "
    "você DEVE citar a fonte exatamente no formato "
    "`[Título (p. X)]` ou conforme o campo `fonte` do trecho fornecido.\n"
    "3. QUANDO NÃO HOUVER EVIDÊNCIA (Sem trechos ou trechos irrelevantes):\n"
    "   - Comece a resposta exatamente com: \"não encontrei no material\"\n"
    "   - Oriente o Aluno a procurar a Coordenação de Estágios.\n"
    "   - NUNCA invente telefones, e-mails, links ou prazos que não estão no texto.\n"
    "4. RESPOSTAS PARCIAIS: Se o material responder apenas parte da dúvida, "
    "responda o que for sustentado citando a Fonte, "
    "e declare para o restante: \"Sobre [assunto não encontrado], não encontrei "
    "no material sobre esse ponto. Procure a Coordenação de Estágios.\"\n"
    "</diretrizes_de_resposta>"
)
"""A instrução de grounding: responder só do Manual, citar a Fonte, Encaminhar sem trecho.

Entra em todo prompt do redator, junto das regras, e por isso entra no
`sha256_do_prompt`: é persona, não topologia. Desde o ADR-0010 o material não
acompanha o prompt — ele chega como mensagem `tool`, depois de o roteador chamar
a ferramenta —, e o literal "não encontrei no material" é pedido aqui e
garantido pela guarda determinística do grafo (`sau/graph/graph.py`), não só
pela obediência do modelo. O critério de resposta com material é a citação da
Fonte do trecho que sustenta a afirmação — o título do slide com a página, como
escrito na #36 e na spec #34. A decisão de consultar saiu do prompt do redator na
#36, e com ela a menção a `buscar_no_manual`.
"""

PERSONA_DE_ROTEAMENTO: str = (
    "Você é o roteador do sistema de Estágio Obrigatório.\n"
    "Sua ÚNICA tarefa é chamar a ferramenta `buscar_no_manual` quando o Aluno demonstrar interesse, dúvida ou intenção sobre processos de estágio.\n\n"
    "<diretrizes>\n"
    "1. QUANDO CHAMAR A FERRAMENTA:\n"
    "   - Se a mensagem contiver QUALQUER menção, intenção ou dúvida sobre tópicos de estágio (prazos, documentos, termo de compromisso, assinaturas, seguro, cadastro, entregas).\n"
    "   - Inclua intenções indiretas como: \"queria saber\", \"gostaria de ver\", \"me explica\", \"preciso de ajuda com\".\n"
    "   - Argumento da busca: extraia a dúvida do Aluno em linguagem natural, ignorando apenas saudações como \"oi\" ou \"olá\".\n"
    "   - Exemplo: \"Oi, queria saber mais sobre prazos\" -> Chame `buscar_no_manual(consulta=\"queria saber mais sobre prazos\")`.\n\n"
    "2. QUANDO NÃO CHAMAR A FERRAMENTA:\n"
    "   - Mensagens que sejam EXCLUSIVAMENTE saudações, agradecimentos ou conversas sem tema de estágio (ex: \"Oi\", \"Bom dia\", \"Obrigado\", \"Como vai?\").\n"
    "   - Se a mensagem NÃO for sobre estágio, responda apenas: sem busca\n"
    "</diretrizes>\n\n"
    "Se houver qualquer dúvida sobre o processo de estágio, Chame a ferramenta `buscar_no_manual`. Não gere explicações."
)
"""A persona do roteador: o prompt enxuto que decide se consulta o Manual.

É a primeira persona **separada** da de redação, e a separação é o que a #36
mede: com a persona inteira o `qwen2.5:3b` não chamava a ferramenta (0/6), e com
este prompt enxuto passou a chamar. Ele não leva as regras nem a
`ORIENTACAO_DE_FONTE` — o roteador não escreve a resposta, só decide se há
consulta a fazer —, e os textos de resposta ditados nele são o "sem busca" do
caminho sem ferramenta mais os três few-shots (`Oi` puro que dispensa a busca,
`Oi` com pergunta sobre o termo, `Oi` com apresentação e pergunta de prazo),
que o redator não lê. A consulta nunca é resumida para uma palavra só: o
roteador lê a mensagem inteira até o fim, remove só saudação, apresentação e
agradecimento, e repassa o trecho relevante da dúvida em linguagem natural,
com o verbo e o objeto como o Aluno escreveu. Quem declara o schema de
`buscar_no_manual` em `tools` é o nó do roteador
(`sau/graph/nodes.criar_no_roteador`), não este texto.

O "sem busca" pós-ferramenta é deliberadamente **só prompt, sem teto de
tokens**: um `num_predict` baixo no roteador poderia truncar um `tool_calls`
longo no meio e degradar o caminho bom, então o rascunho descartado se evita
pela instrução de responder curto, e não pelo corte.
"""

EXEMPLO_DE_ENCAMINHAMENTO = (
    "<exemplo_fora_de_escopo>\n"
    "Entrada: \"Como faço para me inscrever no curso de inglês nas férias?\"\n"
    "Contexto (Trechos): []\n"
    "Resposta: Isso está fora do que eu oriento — eu acompanho o processo "
    "de estágio. Procure a Coordenação de Estágios.\n"
    "</exemplo_fora_de_escopo>"
)
"""O turno completo de fora de escopo que mostra a forma do Encaminhamento.

Um exemplo só, não dois ([ADR-0009](../../docs/adr/0009-exemplo-de-encaminhamento-na-persona.md)):
ele acolhe, diz que está fora do que o S.A.U. orienta e nomeia a Coordenação
de Estágios, sem inventar canal nem prometer prazo. A pergunta é sobre curso
de férias — fora do processo de Estágio por construção — para que nenhum
trecho do Corpus a sustente e nenhum teste confunda o exemplo com conversa.
"""

EXEMPLO_PARCIAL = (
    "<exemplo_resposta_parcial>\n"
    "Entrada: \"O que o termo precisa conter e qual o prazo final para enviar?\"\n"
    "Contexto (Trechos): [{\"titulo\": \"TERMO DE COMPROMISSO MODELO EMPRESA\", "
    "\"pagina\": 51, "
    "\"texto\": \"O modelo da Empresa precisa conter identificação do Aluno, "
    "local do estágio, supervisores e dados da Instituição.\", "
    "\"fonte\": \"TERMO DE COMPROMISSO MODELO EMPRESA (p. 51)\"}]\n"
    "Resposta: Pelo TERMO DE COMPROMISSO MODELO EMPRESA (p. 51), o modelo "
    "da Empresa precisa conter identificação do Aluno, "
    "local do estágio, supervisores e dados da Instituição. Sobre o prazo "
    "de envio, não encontrei no material sobre esse ponto. "
    "Procure a Coordenação de Estágios.\n"
    "</exemplo_resposta_parcial>"
)
"""O turno de resposta parcial: o que fazer quando só parte tem Fonte.

Mostra a forma — parte sustentada com citação de título e página, buraco com o
literal sobre o ponto específico mais Encaminhamento — sem ditar texto a
repetir. A pergunta cruza conteúdo do termo (dentro do Manual) com prazo de
envio (fora dele), que é o caso `x3`/`x5` da bateria.
"""

PERSONA: str = "\n\n".join(
    [f"{regra.titulo}\n{regra.instrucao}" for regra in REGRAS]
    + [ORIENTACAO_DE_FONTE, EXEMPLO_DE_ENCAMINHAMENTO, EXEMPLO_PARCIAL]
)

MENSAGENS_NO_PROMPT = 6


def _historico_para_papeis(historico: Sequence[Mensagem]) -> list[dict[str, str]]:
    """Mapeia o histórico para os papéis nativos do `/api/chat`.

    A fala do Aluno vira `user` e a resposta do S.A.U. vira `assistant`, na
    ordem da conversa e com o mesmo corte de janela de antes: só as
    `MENSAGENS_NO_PROMPT` mais recentes entram. É a única lógica deste módulo
    além da persona — e é o que aposenta a cerca textual e a
    `Mensagem.como_linha` no caminho do prompt: sem rótulo no texto, o modelo
    não tem prefixo a induzir nem a ecoar.
    """
    papeis: list[dict[str, str]] = []
    for falada in list(historico)[-MENSAGENS_NO_PROMPT:]:
        if falada.papel == "sau":
            papeis.append({"role": "assistant", "content": falada.texto})
        else:
            papeis.append({"role": "user", "content": falada.texto})
    return papeis


def montar_mensagens(
    mensagem: str,
    historico: Sequence[Mensagem] = (),
) -> list[dict[str, str]]:
    """Monta as mensagens do redator: persona em `system` mais a conversa em papéis.

    A primeira mensagem é sempre a `PERSONA` em `system`, estável byte a byte
    entre turnos para o cache de prefixo; em seguida o histórico mapeado, e por
    último a dúvida atual do Aluno em `user`. Sem prefill de `assistant` vazio:
    o modelo começa a gerar a partir da dúvida, e não de um rótulo.

    O material não entra por aqui: desde o ADR-0010 ele chega ao modelo como
    mensagem `tool`, anexada pelo redator depois destas. E desde a #36 quem traz
    esse material é o roteador — o redator não declara ferramenta nenhuma —, e o
    que estas mensagens carregam é a persona (com a `ORIENTACAO_DE_FONTE`) e a
    conversa em papéis nativos.
    """
    return [
        {"role": "system", "content": PERSONA},
        *_historico_para_papeis(historico),
        {"role": "user", "content": mensagem},
    ]


def montar_mensagens_de_roteamento(
    mensagem: str,
    historico: Sequence[Mensagem] = (),
) -> list[dict[str, str]]:
    """Monta as mensagens do roteador: persona enxuta em `system` mais a conversa.

    Reusa o mesmo mapeamento de papéis, o mesmo corte de janela e a mesma
    última mensagem `user` do `montar_mensagens` — a única diferença é a persona
    que abre as mensagens. O roteador decide o que fazer com a mensagem; ele
    não recebe as regras de redação nem a `ORIENTACAO_DE_FONTE`.
    """
    return [
        {"role": "system", "content": PERSONA_DE_ROTEAMENTO},
        *_historico_para_papeis(historico),
        {"role": "user", "content": mensagem},
    ]
