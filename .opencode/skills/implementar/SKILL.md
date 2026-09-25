---
name: implementar
description: Planeja a implementação de uma issue ou spec e, após aprovação explícita, delega a execução ao subagente executor. Use quando um ticket do GitHub Issues precisa virar código, antes de editar qualquer arquivo.
---

# Implementação em duas fases

Use esta skill para transformar uma issue, spec ou ticket em uma mudança
executável. O plano fica somente no contexto da sessão e é enviado diretamente
ao subagente executor após a aprovação humana.

**Esta skill não edita código.** A fase 1 produz um plano e a fase 2 apenas
delega esse plano. Se você está lendo isto com intenção de já alterar arquivos,
pare: a implementação é do subagente `executor`, e só depois de uma aprovação
humana explícita do plano completo.

## Fase 1: planejar

1. Leia a issue, a spec, os ADRs, o `CONTEXT.md` e o `AGENTS.md`.
2. Consulte `docs/estrutura.md` para saber onde a mudança vai morar e qual
   ticket já criou cada pasta. Se a pasta ainda não existir, o plano a cria.
3. Explore o repositório para confirmar o estado atual e os pontos de impacto.
4. Valide bloqueios, critérios de aceitação e comandos de validação. As
   validações deste projeto são `pytest`, `ruff` e `mypy`.
5. Verifique no quadro se os bloqueadores da issue estão fechados antes de
   planejar: um ticket só entra na fronteira de trabalho quando seus
   bloqueadores fecham.
6. Não edite código, não crie branches e não execute operações Git mutáveis.
7. Apresente exatamente um `Plano de Implementação` com esta estrutura:

```markdown
# Plano de Implementação

**Status:** aguardando aprovação

## Issue
- Principal: #123 Título da issue
- Relacionadas: nenhuma

## Objetivo

## Escopo
- Incluído:
- Fora do escopo:

## Decisões e Limites

## Estado Atual
- Arquivos e módulos relevantes:
- Comportamento existente:

## Execução
1. Passo concreto.
2. Passo concreto.

## Verificação
- Critério de aceitação:
- Comando ou teste:
- Evidência esperada:

## Riscos e Bloqueios

## Critérios de Conclusão
```

8. Pergunte de forma inequívoca: `Aprova este plano para execução?`
9. Se faltar uma decisão essencial, pare e pergunte antes de pedir aprovação.

## Fase 2: executar

Só entre nesta fase depois de uma aprovação explícita do plano completo.

1. Use o `task` para iniciar exatamente um subagente `executor`.
2. Envie no prompt o plano completo, a confirmação da aprovação e o diretório
   de trabalho atual. Não envie um caminho para arquivo intermediário.
3. O agente principal não implementa a mudança depois da delegação; aguarda o
   relatório do executor.
4. Se o executor encontrar uma contradição ou bloqueio, interrompa a execução e
   devolva a pergunta ao usuário sem reinterpretar o escopo.
5. Ao concluir, apresente o relatório recebido com branch, commit, validações,
   code-review e limitações. A criação da PR continua pertencendo ao `criar-pr`.

## Regras

- Não use `.scratch/` para transportar o plano.
- Uma alteração no plano depois da aprovação exige novo plano e nova aprovação.
- O plano deve referenciar artefatos existentes, sem copiar specs inteiras.
- Pendências de escopo, comportamento, contrato ou arquitetura bloqueiam a
  delegação.
- O vocabulário do domínio vem de `CONTEXT.md`. Escreva o plano, os comentários
  e os testes em português, usando os termos do glossário.
