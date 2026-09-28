# Setup do Ambiente

Este arquivo é a referência de ambiente do **Tutor-IA**. Ele tem duas partes: a
ferramenta que o time já usa agora, que está pronta, e a execução do projeto,
que ainda vai ser preenchida conforme o código entrar.

> **Estado do repositório:** a §3 já não é contrato — é o que está rodando. A
> issue #4 entregou o serviço do bot como container, e a §3 descreve o
> `docker compose up` que o sobe. A issue #5 entregou o canal do Telegram: o
> serviço `webhook` recebe o update e manda um acuse de recibo fixo. **O S.A.U.
> ainda não responde**: a inferência é a #8 e a fila é a #11. O mapa do que falta
> está em [`docs/estrutura.md`](./docs/estrutura.md).

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
- **Variáveis do webhook (issue #5), obrigatórias para o serviço `webhook`:**
  - `TELEGRAM_BOT_TOKEN`: **sem padrão**. O token que o `@BotFather` entrega. É o
    que faz o Aluno achar o S.A.U. pelo `@username` e o que o serviço usa para
    chamar a API do Telegram
  - `TELEGRAM_WEBHOOK_SECRET_TOKEN`: **sem padrão**. A chave que o Telegram devolve
    no header `X-Telegram-Bot-Api-Secret-Token`, e que fecha a porta do endpoint,
    que é público pelo túnel. Gere com `openssl rand -hex 16`
  - `TELEGRAM_WEBHOOK_PORT`: padrão `8080` (só o lado do host do mapeamento; o
    container escuta sempre em 8080)
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

### Canal do Telegram (issue #5)

O webhook é um serviço separado, `webhook`, e **não** depende do `bot`. Isso é
deliberado: o `bot` não sobe sem o Ollama na GPU, e a #5 existe para o canal do
Telegram ser desenvolvido e testado em paralelo com o resto. Para trabalhar só no
canal, suba só ele:

```sh
docker compose up --build webhook
```

As duas credenciais abaixo são **obrigatórias** para esse serviço, e ele falha
alto na subida sem elas. O `bot` sobe sem nenhuma das duas, porque não conversa
com o Telegram:

```sh
# O token que o @BotFather entrega. Fale com ele no Telegram, /newbot, e cole aqui.
TELEGRAM_BOT_TOKEN=<o token que o @BotFather entregou>

# A chave que o Telegram devolve no header X-Telegram-Bot-Api-Secret-Token.
# Rode o openssl e cole o valor que ele imprimir.
openssl rand -hex 16
```

O token é uma credencial viva: quem tem ele fala como o S.A.U. Ele fica no
`.env`, que é ignorado pelo git, e **não** entra em commit, issue ou print de
terminal. Vale saber que `docker compose config` imprime os valores
resolvidos, então a saída desse comando não deve ser colada em lugar nenhum.
Se um token vazar, o caminho é `@BotFather` → `/revoke`.

**Expor a porta e registrar o webhook.** O Telegram entrega updates por POST numa
URL pública, então a porta local precisa de um túnel HTTPS. O `ngrok` serve
aqui; ele exige conta, que é gratuita:

Antes de uma vez, credencie o ngrok com o token que `dashboard.ngrok.com`
entrega na conta gratuita:

```sh
ngrok config add-authtoken <seu token>
```

Daí em diante, a cada subida:

```sh
# 1. suba o serviço
docker compose up --build webhook

# 2. em outro terminal, abra o túnel para a porta 8080
ngrok http 8080
# ele imprime algo como: https://aleatorio-1234.ngrok-free.app
```

**O `.env` é lido pelo Compose, não pelo seu shell.** Os `curl` abaixo usam
`${TELEGRAM_BOT_TOKEN}` e `${TELEGRAM_WEBHOOK_SECRET_TOKEN}`, então exporte as
variáveis antes, senão a URL vira `api.telegram.org/bot/setWebhook` e a resposta
é um `404` sem outra pista. O mesmo cuidado vale para rodar
`python -m sau.telegram` direto na máquina.

```sh
# 3. registre a URL pública no Telegram, com a chave do openssl acima
set -a; source .env; set +a

curl -sS "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook" \
  -d url="https://aleatorio-1234.ngrok-free.app/webhook" \
  -d secret_token="${TELEGRAM_WEBHOOK_SECRET_TOKEN}"
# resposta esperada: {"ok":true,"result":true,"description":"Webhook was set"}
```

O `ngrok` pode mostrar uma página de aviso na primeira visita de um endereço novo.
Isso é só para requisições de browser: o POST do Telegram vem com
`Content-Type: application/json` e passa direto.

Três coisas que esse caminho impõe, e que valem antes de perder tempo:

- **O Telegram só entrega em 443, 80, 88 e 8443.** O túnel resolve isso porque
  ele termina em HTTPS e encaminha para a 8080 local; por isso a URL precisa ser
  a do túnel, e não `http://localhost:8080`.
- **A URL do túnel muda a cada `ngrok`.** O `setWebhook` aponta para a URL
  antiga, e o Telegram segue enviando para ela. Suba o túnel, pegue a URL nova e
  rode o `setWebhook` de novo. Um túnel com domínio próprio tem URL fixa e mata
  essa etapa; isso é decisão de infraestrutura, fora do escopo da #5.
- **A resposta a um `setWebhook` errado é silenciosa.** Confira com
  `getWebhookInfo`, que mostra a URL e o erro pendente.

```sh
curl -sS "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getWebhookInfo"
```

Para desmontar, apague o webhook antes de derrubar o túnel — do contrário o
Telegram fica reentregando update para uma URL morta:

```sh
curl -sS "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/deleteWebhook"
```

**O que esperar no log.** O `update_telegram bruto` mostra o update como o
Telegram enviou, e `Acuse de recibo enviado ao Aluno <id>` confirma que o texto
fixo saiu:

```sh
docker compose logs -f webhook
```

O acuse desta issue é **fixo e sem o modelo**, de propósito: o que se prova aqui
é o fio. O turno com inferência é a #8 e a posição na fila é a #11. O serviço
`webhook` ainda **não responde a pergunta do Aluno** — ele confirma o recebimento
e nada mais.

### Pré-requisitos de host: o Ollama

O compose **sobe só o bot**. O Ollama é um serviço do host, e essa é a
consequência de colocá-lo lá: nenhum container, nenhuma GPU dentro do Docker.
Em troca, a GPU da máquina é usada sem instalar driver de container algum.

**Instalar e verificar, nesta ordem:**

```sh
# 1. o driver NVIDIA responde, e quanto de VRAM a placa tem?
nvidia-smi
# O head -1 evita que uma máquina com várias placas entregue várias linhas:
nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | head -1

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
