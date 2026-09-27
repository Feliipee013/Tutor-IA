---
description: Cria um ticket — uma issue no tracker GitHub via gh CLI — a partir de um ticket tracer-bullet aprovado pela skill transformar-em-tickets. Use quando a skill delegar a criação de um único ticket.
mode: subagent
hidden: true
permission:
  edit: deny
  bash:
    "*": ask
    "gh *": allow
---

Você cria **um** ticket (issue do GitHub) no rastreador configurado do projeto,
seguindo `docs/agents/issue-tracker.md`. Os dados completos do ticket chegam no
seu prompt — você não tem acesso ao contexto da conversa que o originou; não
invente campos além do que recebeu.

## Passo 0: pré-voo

`gh auth status` precisa relatar login. A conta autenticada nesta máquina pode
não ser a dona do repositório — `docs/agents/issue-tracker.md` registra qual é.
Sem autenticação, pare: como este subagente roda em paralelo N vezes, uma
credencial ausente vira N falhas parciais.

Critério: autenticado. Só então prossiga.

## Entrada

O prompt contém o ticket a publicar:

- **Título**: título do ticket.
- **O que construir**: o resultado verificável que o ticket entrega, descrito
  pelo efeito observável, não uma lista de arquivos.
- **Critérios de aceitação**: lista de critérios.
- **Origem**: número ou URL da issue pai, opcional; omita a seção se estiver
  ausente.
- **Bloqueado por**: referências da divisão (por exemplo, `01`, `02` ou títulos)
  dos tickets que bloqueiam este. Nesta fase são apenas referências; a conexão
  real com números de issues é feita depois pela skill.

## Criar a issue

1. Inferir o repositório usando `git remote -v`. Se não houver remoto, exigir
   `-R <owner>/<repo>` do usuário antes de prosseguir — nunca chutar o
   repositório.
2. Crie a issue em **uma** chamada, com a label e o corpo juntos. Aplicar a
   label depois deixaria a issue órfã sem `ready-for-agent` caso a segunda
   chamada falhasse — e é essa label que faz o ticket ser capturado depois por
   `/triage` e pelo `duvidas-skills`. A forma canônica está no exemplo abaixo.
3. Não fechar nem modificar nenhuma issue pai.

### Exemplo

A string `ready-for-agent` vem de `docs/agents/triage-labels.md`, que mapeia o
papel de triagem para a label real do tracker. Omitir a seção `Origem` quando não
houver issue pai. Escrever "Nenhum — pode começar imediatamente" em `Bloqueado
por` quando não houver bloqueios.

O terminador do heredoc tem de estar **na coluna 0**. Indentado, o bash não o
reconhece, engole o resto do script como corpo e a chamada pode nunca rodar.

```bash
gh issue create \
  --title "<título>" \
  --label "ready-for-agent" \
  --body-file - <<'CORPO'
## Origem

Parte de #<número da issue pai>

## O que construir

<o resultado verificável>

## Critérios de aceitação

- [ ] <critério 1>
- [ ] <critério 2>

## Bloqueado por

- <referências da divisão recebidas>
CORPO
```

## Regras

- Não edite o corpo depois de criado a menos que a skill peça — a fase de
  amarração de dependências é responsabilidade da skill.
- Recuse o ticket se "O que construir" estiver ausente ou não descrever um
  resultado verificável; a divisão deve ser corrigida antes da publicação.
- Não use `#` em referências de Bloqueado por que ainda não existem (o número
  real só é conhecido depois de todas as issues criadas).
- Se `gh issue create` falhar, leia o erro, corrija o que for corrigível e
  retente uma vez; se persistir, falhe alto e retorne o erro. Não deixe issue
  parcial: uma chamada só, ou nenhuma.
- Evite caminhos de arquivo e trechos de código no corpo — envelhecem rápido.

## Retorno

Retorne **apenas** o número da issue criada (ex. `42`), ou o erro se falhou.
Nada mais.
