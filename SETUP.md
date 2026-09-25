# Setup do Ambiente

Este arquivo é a referência de ambiente do **Tutor-IA**. Ele tem duas partes: a
ferramenta que o time já usa agora, que está pronta, e a execução do projeto,
que ainda vai ser preenchida conforme o código entrar.

> **Estado do repositório em 25/09/2026:** o projeto tem documentação, ADRs e
> plano de sprint, mas **nenhuma linha de código de aplicação ainda**. A §3 é o
> contrato do que vai existir; atualize-a junto com o primeiro `docker compose up`
> funcional (issue #4).

## 1. Mapa do repositório

O mapa completo, com o que cada pasta faz e qual ticket a cria, está em
[`docs/estrutura.md`](./docs/estrutura.md). As referências que um agente precisa
ler antes de mexer em qualquer coisa:

| Arquivo | Para que serve |
| --- | --- |
| [`CONTEXT.md`](./CONTEXT.md) | glossário do domínio. S.A.U., Aluno, Pergunta Frequente, Atividade, Encaminhamento, Alucinação, Pergunta-teste |
| [`AGENTS.md`](./AGENTS.md) | como o agente trabalha neste repo: skills, regras de organização, Context7 |
| [`docs/adr/`](./docs/adr/) | decisões de arquitetura já tomadas, com o que foi descartado e por quê |
| [`docs/sprints/1.1.md`](./docs/sprints/1.1.md) | o que a sprint 1.1 entrega e em que ordem |
| [`docs/sprints/1.2-rag.md`](./docs/sprints/1.2-rag.md) | o plano de RAG e as decisões de 1.2 ainda em aberto |
| [`docs/agents/`](./docs/agents/) | contratos de tracker, labels, domínio e formato de PR |

## 2. Ferramentas

### 2.1 GitHub CLI (`gh`)

Issues e specs vivem no GitHub Issues — todo o fluxo é via `gh` (ver
[`docs/agents/issue-tracker.md`](./docs/agents/issue-tracker.md)).

Instalação por sistema operacional: https://github.com/cli/cli#installation

```sh
gh --version
```

**Autenticação**

```sh
gh auth login
```

Selecione **GitHub.com**, o protocolo preferido (HTTPS ou SSH) e autorize o
`gh` a autenticar o Git — assim `git push`/`git pull` funcionam sem credential
manager à parte.

```sh
gh auth status
```

Neste projeto o `gh` está autenticado como `Kcronnos`, que tem **WRITE** no
repositório `Feliipee013/Tutor-IA` e é **colaborator** do quadro. Uma máquina
autenticada como outra conta pode não ter as duas permissões. Confira antes de
uma sessão que escreve.

**Uso neste repo**

```sh
gh issue list --state open          # listar issues abertas
gh issue view 5 --comments          # ler uma issue
gh issue create --title "..." --body "..."   # criar issue
gh pr list --state open             # listar PRs abertas
```

**Quadro**

O quadro é [Tutor IA - KANBAN](https://github.com/users/Feliipee013/projects/3),
dono `Feliipee013`. As colunas de `Status` são `Backlog`, `Sprint Atual`,
`Em Progresso`, `Em Revisão (Pull Request)` e `Concluído`, e existe um campo de
iterações `Sprints` com a iteração **Sprint 1.1 + 1.2** (21/09 a 01/10/2026).

```sh
gh project view 3 --owner Feliipee013
gh project item-list 3 --owner Feliipee013
```

> **Acesso ao quadro:** ele é privado, e privado em projeto de nível usuário
> significa que **só o dono e os colaboradores do próprio projeto veem**.
> Colaborator do repositório não basta. Para alguém do time ver o quadro, é
> preciso adicioná-la em **Project settings → People** no próprio projeto —
> além de ela ser collaborator do repositório para ver o código e as issues.

### 2.2 Context7 (MCP)

O Context7 injeta documentação atualizada de bibliotecas direto no contexto do
agente. O `opencode.json` da raiz já vem com o MCP configurado — basta criar a
conta, gerar uma API key e gravá-la no repo.

**Criar conta**

Acesse https://context7.com/dashboard e faça sign in. É gratuito, sem cartão
de crédito.

**Criar uma API key**

No dashboard, no card **API Keys**, clique em **Create API Key**, dê um nome
(ex.: "opencode") e copie a chave gerada (`ctx7sk-...`). Ela é exibida **uma
única vez** — se perdida, revogue e crie outra.

**Gravar a chave no repo**

A chave fica num arquivo na raiz do repositório, ignorado pelo git:

```sh
printf '%s' 'ctx7sk-...' > .context7-key
chmod 600 .context7-key
```

O `opencode.json` da raiz lê esse arquivo via `{file:./.context7-key}`, com o
caminho relativo ao diretório do próprio config. O `.gitignore` já cobre
`.context7-key`, então a chave não sobe para o GitHub.

**Verificar**

```sh
opencode mcp list
```

Ou, numa sessão, peça ao agente a documentação de uma biblioteca do projeto
(ex.: "use context7: assinatura do `getUpdates` do python-telegram-bot 21").

## 3. Executando o projeto

> **Ainda não existe.** Esta seção é o contrato do que vai existir, derivado dos
> tickets da sprint 1.1. Substitua cada bloco pelo comando real assim que a
> pasta existir.

**Previsto:** Python com `pytest`, `ruff` e `mypy`; o serviço do bot em
`docker compose` (issue #4) com o **Ollama rodando no host**, conforme
[ADR-0002](./docs/adr/0002-topologia-do-ollama.md); o bot recebendo o webhook
do Telegram (issue #5) e respondendo pelo grafo LangGraph (issue #8).

**A definir junto com o código, não antes:**

- o nome do pacote Python e o entrypoint do serviço do bot;
- a porta do webhook local;
- o arquivo de ambiente e quais variáveis ele carrega, entre elas a URL base
  do Ollama, que é `http://host.docker.internal:11434`;
- o `k` do semáforo de inferência, que [ADR-0001](docs/adr/0001-concorrencia-do-bot.md)
  exige que seja **medido na máquina alvo**, não assumido.

### Pré-requisitos de host: o Ollama

O compose **sobe só o bot**. O Ollama é um serviço do host, e essa é a
consequência de colocá-lo lá: nenhum container, nenhuma GPU dentro do Docker.
Em troca, a GPU da máquina é usada sem instalar driver de container algum.

**Instalar e verificar, nesta ordem:**

```sh
# 1. o driver NVIDIA responde?
nvidia-smi

# 2. o Ollama está no ar?
curl -s http://localhost:11434/api/version

# 3. está mesmo na GPU, e não em CPU?
ollama ps        # a coluna PROCESSOR diz "100% GPU" ou "100% CPU"
```

O passo 3 é o que não pode ser pulado. `nvidia-smi` responder e a porta 11434
devolver JSON **são compatíveis com o Ollama servindo em CPU** — e nesse estado
todo o stack sobe parecendo saudável, com o modelo absurdamente lento. É
exatamente o defeito que o ADR-0002 existe para fechar, e o motivo de a issue
#4 exigir falha alta na checagem de pré-requisito em vez de uma espera silenciosa.

**Dois detalhes de laptop híbrido.** A máquina da decisão tem Intel UHD e NVIDIA
integrada: ao medir, fixe `OLLAMA_VISIBLE_DEVICES` para a placa discrete, senão a
medição da issue #3 descreve a GPU errada. E o bot, por estar em container,
precisa do alias para o host, que no Linux não é automático:

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

**Teto de hardware conhecido:** 4 GB de VRAM e 7,5 GiB de RAM. A família 7B em
quantização 4 bits não cabe, então a 1.1 trabalha com a família 3B. A issue #3
registra esse teto junto da medição.

Enquanto isso, o agente de validação é o trio abaixo, e vale rodá-lo a cada
commit:

```sh
pytest        # suíte
ruff check .  # lint
mypy .        # tipos
```

## Referências

- [Instalar o gh](https://github.com/cli/cli#installation)
- [Dashboard do Context7](https://context7.com/dashboard)
- [MCP no OpenCode](https://opencode.ai/docs/mcp-servers)
- [Skills no OpenCode](https://opencode.ai/docs/skills)
- [Instalar o Ollama no Linux](https://docs.ollama.com/linux)
- [Ollama com GPU NVIDIA](https://docs.ollama.com/gpu)
