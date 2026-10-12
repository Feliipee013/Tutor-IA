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
