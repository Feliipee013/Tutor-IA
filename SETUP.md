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

O serviço do bot é empacotado no container via `docker-compose.yml`,
consumindo o **Ollama rodando nativamente no host**, conforme
[ADR-0002](./docs/adr/0002-topologia-do-ollama.md).

**Definições consolidadas (issue #4):**
- **Pacote Python e entrypoint:** pacote `sau`, entrypoint `python -m sau.main`
- **Porta padrão do serviço:** `8000` (com endpoint de saúde `/health`)
- **Variáveis de ambiente (`.env` opcional):**
  - `OLLAMA_BASE_URL`: padrão `http://host.docker.internal:11434`
  - `OLLAMA_MODEL`: padrão `qwen2.5:3b` (o escolhido no [ADR-0003](./docs/adr/0003-modelo-do-ollama.md))
  - `OLLAMA_ALLOW_CPU`: padrão `false` (exige GPU e falha alto se cair em CPU; use `true` apenas em dev/CI sem GPU)
  - `OLLAMA_TIMEOUT`: padrão `30` (segundos)
  - `VRAM_TOTAL_MIB`: sem padrão, **obrigatória** (VRAM total da máquina em MiB, como o `nvidia-smi` imprime; exigida pelo confronto de VRAM do ADR-0002, dispensada com `OLLAMA_ALLOW_CPU=true`)
  - `BOT_PORT`: padrão `8000`
  - `LOG_LEVEL`: padrão `INFO`
- **Variável do host, fora do container:** `OLLAMA_HOST=0.0.0.0:11434`, consumida
  pelo `ollama serve` e não pelo serviço. Ver o passo 2 logo abaixo.
- **Logs estruturados:** formato padronizado com prefixo `[SAU-BOT]` no stdout.

### Subindo o bot via Docker Compose

```sh
# 1. Certifique-se de que o Ollama está rodando no host e o modelo está baixado
OLLAMA_HOST=0.0.0.0:11434 ollama serve
ollama pull qwen2.5:3b

# 2. Suba o serviço do bot
docker compose up --build

# Para subir em background
docker compose up -d --build

# Para visualizar os logs
docker compose logs -f bot
```

### Pré-requisitos de host: o Ollama

O compose **sobe só o bot**. O Ollama é um serviço do host, e essa é a
consequência de colocá-lo lá: nenhum container, nenhuma GPU dentro do Docker.
Em troca, a GPU da máquina é usada sem instalar driver de container algum.

**Instalar e verificar, nesta ordem:**

```sh
# 1. o driver NVIDIA responde, e quanto de VRAM a placa tem?
nvidia-smi
nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits

# 2. o Ollama está no ar, escutando em todas as interfaces?
OLLAMA_HOST=0.0.0.0:11434 ollama serve   # em um terminal
curl -s http://localhost:11434/api/version   # em outro

# 3. está mesmo na GPU, e não em CPU?
ollama ps        # a coluna PROCESSOR diz "100% GPU" ou "100% CPU"
```

**O passo 2 é o que o compose não consegue fazer por você.** O bind padrão do
Ollama é `127.0.0.1`, e o container do bot chega no IP da bridge do Docker, não
no loopback do host: com o bind padrão a conexão é recusada na hora, com
`Errno 111: Connection refused`, antes de qualquer checagem de pré-requisito. Por
isso o `OLLAMA_HOST` precisa ser `0.0.0.0:11434` no shell **antes** de subir o
Ollama. A contrapartida é de segurança: `0.0.0.0` expõe a porta 11434 em todas
as interfaces da rede, não só na localhost. Em rede confiável, com a máquina de
inference atrás de firewall, é o preço do bind; em rede não confiável, restrinja
o bind a uma interface que só a bridge alcance, ou coloque um proxy com
autenticação na frente.

O número do `nvidia-smi --query-gpu=memory.total` é o que alimenta a
`VRAM_TOTAL_MIB`, e ele é **obrigatório**: nenhum endpoint do Ollama reporta a
VRAM total da máquina, então sem ele a checagem do ADR-0002 não tem contra o que
comparar o `size_vram` que o Ollama relata, e o serviço falha alto. Quem está em
dev ou CI sem GPU não precisa dele, porque `OLLAMA_ALLOW_CPU=true` transforma a
falha em warning.

O passo 3 é o que não pode ser pulado. `nvidia-smi` responder e a porta 11434
devolver JSON **são compatíveis com o Ollama servindo em CPU** — e nesse estado
todo o stack sobe parecendo saudável, com o modelo absurdamente lento. É
exatamente o defeito que o ADR-0002 existe para fechar, e o motivo de a issue
#4 exigir falha alta na checagem de pré-requisito em vez de uma espera silenciosa.

**Dois detalhes de laptop híbrido.** A máquina da decisão tem Intel UHD e NVIDIA
integrada: ao medir, fixe `CUDA_VISIBLE_DEVICES` para a placa discreta, senão a
medição da issue #3 descreve a GPU errada. É esse o nome da variável no Ollama —
`OLLAMA_VISIBLE_DEVICES` não existe e é ignorado em silêncio. Use o UUID que
`nvidia-smi -L` imprime, e não o índice numérico, porque a ordem dos devices pode
variar. A variável não substitui o passo 3: quem prova a placa em uso é o
`ollama ps`. E o bot, por estar em container, precisa do alias para o host, que no
Linux não é automático:

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
