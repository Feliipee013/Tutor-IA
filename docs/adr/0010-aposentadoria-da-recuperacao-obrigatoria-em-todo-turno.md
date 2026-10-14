# Aposentadoria da recuperação obrigatória em todo turno

A recuperação obrigatória em todo turno é aposentada. Em vez de ser executada em toda resposta, a recuperação passa a ser uma ferramenta opcional da LLM (`buscar_no_manual`), que decide chamá-la apenas quando precisa de fato do Manual de Estágio.

## Motivo

A decisão anterior de recuperar obrigatoriamente em todo turno gerava chamadas desnecessárias (saudações, agradecimentos, perguntas fora do escopo não precisam de busca), aumentava ruído e dificultava distinguir quando não havia evidência válida. A Spec #34 define que a LLM deve chamar a ferramenta somente quando precisa de fato do manual, podendo chamá-la mais de uma vez em perguntas que cruzam assuntos.

## Consequências

- A recuperação deixa de ser etapa obrigatória do turno e torna-se ferramenta opcional.
- Política de uso vive no prompt: chamar apenas quando precisar de fato do manual; saudações, despedida e agradecimento respondem direto.
- Quando não houver evidência válida acima do limiar, a resposta usa o literal "não encontrei no material" e encerra com Encaminhamento à Coordenação de Estágios, sem inventar.
- Toda chamada da ferramenta é registrada em log com consulta, pontuações, descartes pelo limiar e Fontes entregues.
- O comportamento é auditável e comparável pela bateria de testes.

## Emenda: implementação na #36

A #36 implementa a aposentadoria. O que a decisão deixou em aberto, e a
implementação fixou:

- **Tool-calling nativo, não parada de decisão no prompt.** O turno fala por
  `/api/chat` do Ollama, declarando o schema de `buscar_no_manual` em `tools`.
  Quem decide chamar é o modelo, e a decisão chega como `message.tool_calls`;
  não há nó classificador nem frase de parada no texto do prompt.
- **O grafo vira o ciclo do agente.** `START → agente → (cond.) → ferramentas →
  agente … → finalizar → END`. O `agente` chama o modelo; `ferramentas` executa
  cada `buscar_no_manual` pedida e devolve o resultado como mensagem `tool`;
  `finalizar` encerra. `LIMITE_DE_RODADAS = 4` trava o laço de um modelo que peça
  a ferramenta sem parar.
- **O literal de ausência é garantido em código, não só pedido no prompt.** A
  guarda do `finalizar` dispara quando `houve_ferramenta and not houve_evidencia`
  e troca a resposta pelo texto de ausência seguido do Encaminhamento. Uma persona
  que peça o literal sem a guarda dependeria de o modelo obedecer; a guarda não.
- **Sem Manual no turno, o modelo não declara `tools`.** `manual=None` roda o
  agente sem ferramenta — é o modo dos testes de persona, e o caminho de um S.A.U.
  sem Manual.
- **A recuperação por Corpus sai do turno e não é deletada.** `sau/rag/retrieve.py`
  e seus testes ficam de pé; o que saiu foi o nó que a chamava em todo turno. As
  opções do Manual (onde, quanto e com que corte) chegam de `sau/config.py` —
  `MANUAL_LIMIAR_SIMILARIDADE` (padrão 0,35) e `MANUAL_K_PADRAO` (padrão 4) —,
  fonte única também para o harness.
