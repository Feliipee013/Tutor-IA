# CONTEXT.md Format

## Structure

```md
# {Context Name}

{One or two sentence description of what this context is and why it exists.}

## Language

**Aluno**:
{A one or two sentence description of the term}
_Evite_: usuário, cliente, discente, estudante

**Atividade**:
Trabalho ou entrega do curso sobre o qual o Aluno pede ajuda. O Tutor não
entrega a resposta de uma Atividade, mesmo quando a sabe.
_Evite_: exercício, projeto, tarefa, assignment

**Encaminhamento**:
Ação do Tutor de sugerir ao Aluno que procure um Tutor humano, usada quando a
resposta não está ao seu alcance. Não é um fluxo com estado; é um encerramento
de conversa.
_Evite_: handoff, escalonamento, suporte
```

## Rules

- **Be opinionated.** When multiple words exist for the same concept, pick the best one and list the others under `_Evite_`.
- **Keep definitions tight.** One or two sentences max. Define what it IS, not what it does.
- **Only include terms specific to this project's context.** General programming concepts (timeouts, error types, utility patterns) don't belong even if the project uses them extensively. Before adding a term, ask: is this a concept unique to this context, or a general programming concept? Only the former belongs.
- **Group terms under subheadings** when natural clusters emerge. If all terms belong to a single cohesive area, a flat list is fine.

## Single vs multi-context repos

**Single context (most repos):** One `CONTEXT.md` at the repo root.

**Multiple contexts:** A `CONTEXT-MAP.md` at the repo root lists the contexts, where they live, and how they relate to each other:

```md
# Context Map

## Contexts

- [Bot](./sau/CONTEXT.md) — classifies intent, retrieves from the corpus and answers the Aluno
- [Conteudo](./corpus/CONTEXT.md) — the team-authored corpus and the Perguntas-teste
- [Medicao](./harness/CONTEXT.md) — runs the Perguntas-teste and scores the rate of Alucinacao

## Relationships

- **Bot → Conteudo**: Bot queries the corpus by Pergunta Frequente; Conteudo answers with the section
- **Conteudo → Medicao**: Conteudo ships the Perguntas-teste; Medicao runs them against a model
- **Bot ↔ Medicao**: Shared vocabulary for Alucinação, the rate of non-answer and the rate of refusal of Atividade
```

The skill infers which structure applies:

- If `CONTEXT-MAP.md` exists, read it to find contexts
- If only a root `CONTEXT.md` exists, single context
- If neither exists, create a root `CONTEXT.md` lazily when the first term is resolved

When multiple contexts exist, infer which one the current topic relates to. If unclear, ask.
