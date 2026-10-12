# Setup do Ambiente

Este arquivo é a referência de ambiente do **Tutor-IA**. Ele tem duas partes: a
ferramenta que o time já usa agora, que está pronta, e a execução do projeto,
que ainda vai ser preenchida conforme o código entrar.

> **Estado do repositório:** a §3 já não é contrato — é o que está rodando. A
> issue #4 entregou o serviço do bot como container, e a §3 descreve o
> `docker compose up` que o sobe. A issue #5 entregou o canal do Telegram: o
> serviço `webhook` recebe o update e manda um acuse de recibo fixo. A issue #8
> entregou o **primeiro turno ponta a ponta**: o mesmo serviço `webhook` roda o
> grafo LangGraph e responde o Aluno com o texto do modelo, logo depois do acuse.
> O que ainda falta é a persona (#10), o histórico por conversa (#9) e a fila
> (#11). O mapa do que falta está em
> [`docs/estrutura.md`](./docs/estrutura.md).

## 1. Mapa do repositório

O mapa completo, com o que cada pasta faz e qual ticket a cria, está em
[`docs/estrutura.md`](./docs/estrutura.md). As referências que um agente precisa
ler antes de mexer em qualquer coisa:

| Arquivo | Para que serve |
| --- | --- |
| [`CONTEXT.md`](./CONTEXT.md) | glossário do domínio. S.A.U., Aluno, Estágio, Documentação de Estágio, Prazos / Calendário de Estágio, Fluxo de Estágio, Pergunta Frequente, Atividade, Coordenação de Estágios, Encaminhamento, Alucinação, Pergunta-teste |
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
  - `TELEGRAM_API_BASE`: padrão `https://api.telegram.org`. Existe para apontar
    para uma Bot API local em desenvolvimento, e para isso só. O compose **não**
    a expõe, porque o canal conversa com a API do Telegram
- **Variáveis da conversa (issue #9), opcionais — o `webhook` só:**
  - `CONVERSA_TTL_MINUTOS`: padrão `30` (minutos sem contato antes de a conversa
    ser apagada). Precisa ser inteiro positivo
  - `CONVERSA_CAMINHO`: o compose **não repassa** esta variável. Ele fixa o caminho
    dentro do container, em `/var/lib/sau/conversas.db`, e monta o volume nomeado
    `conversas` nesse caminho — é esse volume que faz o histórico sobreviver ao
    `docker compose down`. A variável vale para quem roda o `webhook` direto no
    host, e ali o padrão é `conversas.db` no diretório de trabalho. Ver
    [A conversa](#a-conversa-issue-9)
- **Variável do host, fora do container:** `OLLAMA_HOST=0.0.0.0:11434`, consumida
  pelo `ollama serve` e não pelo serviço. Ver o passo 2 logo abaixo.
- **Logs estruturados:** formato padronizado com prefixo `[SAU]` no stdout.

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

> **Sem argumentos, o compose sobe os dois serviços**, `bot` e `webhook` (issue
> #5), porque é o que o comando sem nome significa. O `webhook` **falha alto na
> subida** se as duas credenciais do Telegram não estiverem no `.env`, com uma
> mensagem explicando o que é cada uma — o `bot` sobe sem elas, porque não
> conversa com o Telegram. Para subir só o bot, e só o webhook, nomeie o serviço:
> ver [Canal do Telegram](#canal-do-telegram-issue-5).

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
URL pública, então a porta local precisa de um túnel HTTPS. Em dev o túnel é o
serviço `ngrok` do `docker-compose.dev.yml` — ele exige conta gratuita, com o
token que `dashboard.ngrok.com` entrega:

```sh
# .env (ignorado pelo git, nunca entra em commit ou log)
NGROK_AUTHTOKEN=<o token do dashboard.ngrok.com>
```

Daí em diante, um comando só sobe o canal com o túnel e registra sozinho a URL
pública no Telegram, antes de atender o Aluno:

```sh
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

Ou exporte o `COMPOSE_FILE` uma vez e use o `up` normal:

```sh
export COMPOSE_FILE=docker-compose.yml:docker-compose.dev.yml
docker compose up --build
```

O `docker compose up` puro (sem `-f`) nunca inclui o ngrok: a prod continua sem
dependência externa. Confira com `docker compose config` — sem `-f` ele não
lista o `ngrok`.

Como funciona: o `webhook` descobre a URL pelo `/api/tunnels` do serviço
`ngrok` (com retry curto para absorver o boot) e faz o `setWebhook` com
`url=<url-pública>/webhook` mais o `secret_token`. Se a `TELEGRAM_PUBLIC_URL`
estiver preenchida no `.env`, ela vence a descoberta — é o caminho de quem abre
o túnel na mão, fora do compose dev. Sem as duas, nenhum HTTP extra acontece e
o serviço sobe sem registrar, como em prod. O registro nunca derruba o canal:
se falhar, vira só um warning no log e o Aluno continua sendo acusejado.

**O `.env` é lido pelo Compose, não pelo seu shell.** O `curl` abaixo usa
`${TELEGRAM_BOT_TOKEN}`, então exporte as variáveis antes, senão a URL vira
`api.telegram.org/bot/setWebhook` e a resposta é um `404` sem outra pista. O
mesmo cuidado vale para rodar `python -m sau.telegram` direto na máquina. O
`curl` é o caminho manual, para quando o registro automático não se aplica
(compose puro, sem o override de dev):

```sh
# 1. suba o serviço (compose puro)
docker compose up --build webhook

# 2. em outro terminal, abra o túnel para a porta 8080
ngrok http 8080
# ele imprime algo como: https://aleatorio-1234.ngrok-free.app

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
Telegram enviou, e `Mensagem enviada ao Aluno <id>` confirma cada texto que saiu
— o acuse primeiro, a resposta do modelo depois:

```sh
docker compose logs -f webhook
```

O turno aparece com `Entrada do grafo: mensagem do Aluno`, o
`Resposta do modelo '<modelo>'` com os tempos e o `Saída do grafo: resposta ao
Aluno`. Se o Ollama estiver fora, o que aparece é `O turno do Aluno <id> falhou:`
com o motivo inteiro, e o Aluno recebe a mensagem amigável em vez da resposta.

**O tempo do turno.** `Turno do Aluno <id> entregue em <s>s (<desfecho>)` é o
número do critério "a resposta chega em tempo aceitável para alguém acordado às
2h da manhã", e ele é do turno inteiro — do começo à entrega —, não só da
geração. O desfecho entre parênteses diz o que aconteceu (`resposta do modelo`,
`falha do modelo`, `erro inesperado`, `resposta vazia`), e é o que separa "levou
30s e respondeu" de "levou 30s e pediu desculpa". O `total` do
`Resposta do modelo` é só a geração, e ele fica dentro do turno.

Esse tempo depende da máquina, e o número medido da máquina do ADR-0002 está em
[`docs/tempo-primeira-resposta.md`](./docs/tempo-primeira-resposta.md). O log do
`webhook` é o número do turno a turno; a medição é a da máquina, com as
condições e os limites dela.

O acuse e a resposta continuam sendo **duas mensagens separadas**, e é assim que
o `webhook` garante o que o ADR-0001 pede: o Aluno leva o primeiro retorno antes
de qualquer inferência. O turno é executado em uma thread, fora do request — o
semáforo e a fila com backpressure são da #11.

O `webhook` **não responde a pergunta do Aluno com a persona do S.A.U.** ainda: o
prompt do turno é a mensagem com a instrução mínima de respondê-la, e é a #10 que
troca esse texto.

### A conversa (issue #9)

O `webhook` é o dono do estado da conversa. O que o Aluno perguntou e o que o
S.A.U. respondeu ficam num arquivo SQLite, isolados por `chat_id`, e as últimas
mensagens da conversa entram no prompt do turno seguinte. Nada disso precisa ser
configurado: o serviço sobe, cria o arquivo no volume nomeado e guarda trinta
minutos de conversa ociosa.

Para conferir o que está guardado:

```sh
docker compose exec -T webhook ls -l /var/lib/sau
```

O caminho `/var/lib/sau` é o volume nomeado `conversas`, e ele é do `webhook` e
não do `bot` porque o `bot` não roda turno — ele não tem conversa para guardar.
`docker compose down` **não** apaga esse volume; `docker compose down -v` apaga,
e com ele todo o histórico. É o comportamento esperado de `down -v` em qualquer
compose, e vale saber antes de rodar o comando com `-v` por engano.

Ajustar o TTL é mexer em `CONVERSA_TTL_MINUTOS` no `.env` e subir de novo:

```sh
CONVERSA_TTL_MINUTOS=120 docker compose up -d --build webhook
```

Passado o TTL, a próxima mensagem do Aluno começa uma conversa nova, do zero. O
motivo está no [ADR-0005](./docs/adr/0005-estado-da-conversa.md): o histórico de
um Aluno é dado guardado por um bot de faculdade, e não há por que guardar para
sempre o que ele perguntou às 3h da manhã.

**Rodando o `webhook` no host, sem container.** Aí o caminho não é o volume, e
sim o `CONVERSA_CAMINHO` — cujo padrão é `conversas.db`, relativo a onde você
está. O `.gitignore` cobre `*.db`, então o arquivo não sobe para o Git por
acidente, mas ele fica ali e some com ele o histórico.

### O Manual de Estágio (issue #40)

O `webhook` indexa o Manual de Estágio Obrigatório do Polo no boot, sozinho:
subir do zero indexa, subir de novo reaproveita, trocar o PDF re-ingere no
próximo boot. O arquivo esperado é
`corpus/manual-estagio-obrigatorio-polo-2026-2.pdf` — como colocar, o que
acontece sem ele e a limitação conhecida estão em
[`corpus/README.md`](./corpus/README.md). O PDF nunca entra no git, e o índice
Chroma vive no volume nomeado `manual-chroma`.

### Pré-requisitos de host: o Ollama

O compose **não sobe o Ollama**. Ele sobe dois serviços, `bot` e `webhook` (issue
#5), e o Ollama é um serviço do host: nenhum container, nenhuma GPU dentro do
Docker. Em troca, a GPU da máquina é usada sem instalar driver de container
algum.

**O passo inteiro cabe em um comando**, e ele pode ser repetido sem medo — na
segunda vez ele não baixa o modelo:

```sh
scripts/preparar-host.sh
```

Ele descobre a VRAM, confere que o Ollama responde, baixa o modelo se faltar, e
imprime a linha `export VRAM_TOTAL_MIB=...` pronta para o `docker compose up`.
O mesmo passo, escrito à mão:

```sh
# 1. quanto de VRAM a placa tem? (o número que alimenta o VRAM_TOTAL_MIB)
#    placa NVIDIA:
nvidia-smi
nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | head -1
#    qualquer outra placa (AMD, Intel) — o valor vem em bytes:
cat /sys/class/drm/card*/device/mem_info_vram_total

# 2. o Ollama está no ar, escutando em todas as interfaces?
OLLAMA_HOST=0.0.0.0:11434 ollama serve   # em um terminal
curl -s http://localhost:11434/api/version   # em outro

# 3. o modelo está baixado?
ollama pull qwen2.5:3b

# 4. está mesmo na GPU, e não em CPU?
ollama run qwen2.5:3b   # e interrompa com Ctrl+C, para o modelo ficar carregado
ollama ps        # a coluna PROCESSOR diz "100% GPU" ou "100% CPU"
```

O número do passo 1 é **obrigatório** por padrão: nenhum endpoint do Ollama
reporta a VRAM total da máquina, então sem ele a checagem do ADR-0002 não tem
contra o que comparar o `size_vram` que o Ollama relata, e o serviço falha alto.
Quem está em dev ou CI sem GPU não precisa dele, porque
`OLLAMA_ALLOW_CPU=true` transforma a falha em aviso.

Duas coisas sobre esse número:

- **Ele não tem nada de NVIDIA.** `VRAM_TOTAL_MIB` é um inteiro em MiB, e a
  checagem só o compara com o `size_vram` em bytes. O `/sys/class/drm` é o
  caminho para quem não tem `nvidia-smi`, e a conversão de bytes para MiB
  arredonda para cima — arredondar para baixo faria a placa parecer menor do que
  é e reprovaria uma alocação que cabe.
- **Ele precisa ser o da sua máquina.** Um total errado aprova a checagem errada
  e não aparece como erro. Confira na primeira vez. Com mais de uma placa, o
  script para e mostra as duas em vez de escolher por você.

O [ADR-0004](./docs/adr/0004-vram-por-maquina.md) tem o resto das receitas, e
o caso "sem GPU dedicada" inteiro.

**O passo 2 é o que o compose não consegue fazer por você.** O bind padrão do
Ollama é `127.0.0.1`, e o container do bot chega no IP da bridge do Docker, não
no loopback do host: com o bind padrão a conexão é recusada na hora, com
`Errno 111: Connection refused`, antes de qualquer checagem de pré-requisito. Por
isso o `OLLAMA_HOST` precisa ser `0.0.0.0:11434`.

Esse bind vale para os **dois** serviços desde a #8: o `bot` na checagem e na
fumaça, o `webhook` no turno. A diferença é o que acontece quando ele falta. No
`bot` a falha é alta, na subida. No `webhook` o serviço sobe normalmente, o Aluno
recebe o acuse e uma segunda mensagem dizendo que houve um problema — porque o
canal do Telegram não pode sair do ar por causa do modelo.

**Onde essa variável mora depende de quem sobe o Ollama.** São dois casos, e
confundir os dois é o jeito mais comum de o passo 2 não funcionar:

- **Ollama de serviço do systemd** (pelo pacote do Arch, do Ubuntu ou pelo
  instalador oficial). A variável vai no serviço, com um arquivo de override:

  ```sh
  sudo tee /etc/systemd/system/ollama.service.d/host.conf >/dev/null <<'EOF'
  [Service]
  Environment="OLLAMA_HOST=0.0.0.0:11434"
  EOF
  sudo systemctl daemon-reload
  sudo systemctl restart ollama
  ```

  Confira com `systemctl show ollama --property=Environment` (tem que aparecer
  `OLLAMA_HOST=0.0.0.0:11434`) e com `ss -ltn | grep 11434` (tem que dar
  `*:11434`). O primeiro comando diz o que o serviço recebeu, o segundo diz onde
  ele está escutando. Se o primeiro estiver certo e o segundo mostrar
  `127.0.0.1:11434`, outro processo está na frente da porta e o `ollama` do seu
  PATH pode estar falando com ele.

- **Ollama que você mesmo sobe**, no seu terminal, com
  `OLLAMA_HOST=0.0.0.0:11434 ollama serve`. Aqui a variável no shell basta. Ela
  não sobrevive ao fechamento do terminal, e o comando `ollama` do seu PATH
  precisa apontar para o mesmo binário do serviço — senão você mede um Ollama e
  o compose fala com outro.

A contrapartida é de segurança nos dois casos: `0.0.0.0` expõe a porta 11434 em
todas as interfaces da rede, não só na localhost. Em rede confiável, com a
máquina de inference atrás de firewall, é o preço do bind; em rede não
confiável, restrinja o bind a uma interface que só a bridge alcance, ou coloque
um proxy com autenticação na frente.

O passo 4 é o que não pode ser pulado. `nvidia-smi` responder e a porta 11434
devolver JSON **são compatíveis com o Ollama servindo em CPU** — e nesse estado
todo o stack sobe parecendo saudável, com o modelo absurdamente lento. É
exatamente o defeito que o ADR-0002 existe para fechar, e o motivo de a issue
#4 exigir falha alta na checagem de pré-requisito em vez de uma espera silenciosa.

### Medindo o tempo de primeira resposta

Depois do stack no ar, dá para medir o que o primeiro Aluno da madrugada espera:

```sh
VRAM_TOTAL_MIB=<o da sua máquina> docker compose run --rm bot python -m sau.inference.fumaca
```

Com `--repeticoes 4`, a primeira rodada sai com o modelo descarregado e as três
seguintes com ele carregado — que é a diferença entre o primeiro Aluno e os
outros. Para mandar outra pergunta:

```sh
python -m sau.inference.fumaca --pergunta "sua pergunta aqui"
python -m sau.inference.fumaca --de-arquivo pergunta.txt
```

O resultado desta máquina está em
[`docs/tempo-primeira-resposta.md`](./docs/tempo-primeira-resposta.md) — e ele
é o número da máquina do ADR-0002, a GTX 1650 de 4 GB. O seu não vai ser igual:
placa diferente é outro tempo, e a pergunta e a persona mudam o número também.

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

### Harness das Perguntas-teste (issue #12)

O harness envia as 10 Perguntas-teste ao S.A.U. pelo caminho real do turno
(o mesmo grafo do `webhook`, com histórico vazio, sem Telegram e sem banco
de respostas gravado) e grava o output bruto de cada uma, com o comportamento
esperado lado a lado. O julgamento de conforme/não-conforme é humano: o
script grava, não avalia. A saída vai para `outputs/`, um JSON por rodada.

Rode no **host**, não no container. O `OLLAMA_BASE_URL` do `.env` aponta para
`host.docker.internal`, que é o endereço do host visto de dentro do container e
não resolve a partir do host — sem exportar a URL abaixo, a bateria inteira
falha.

```sh
# 1. a URL do Ollama como o host enxerga
export OLLAMA_BASE_URL=http://localhost:11434

# 2. a VRAM da placa, que o /api/ps não informa e a checagem precisa
export VRAM_TOTAL_MIB=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | head -1)

# 3. a bateria
python -m harness.run --help
python -m harness.run
python -m harness.run --saida outputs/baseline-1.1.json
```

As flags `--modelo`, `--url` e `--timeout` sobrescrevem o `.env`; `--saida`
escolhe o arquivo da rodada (o padrão é `outputs/harness-<data-hora>.json`).
A falha ou o timeout de um turno grava `erro` na execução e a bateria segue.

Cada pergunta roda **3 repetições**, com `temperature 0`, `seed 20260926` e
`num_predict 256` — as condições do ADR-0003. O número não é detalhe: o ADR
mediu que das 12 perguntas da sondagem só 4 tiveram as 3 repetições idênticas na
máquina de CPU, e 7 na máquina do ADR-0002 — o número depende da máquina, e é
por isso que ele é qualificado em vez de solto. Uma execução só registra uma das
respostas possíveis, então a taxa da #13 sai de uma amostra que não representa o
comportamento. As flags `--repeticoes`,
`--temperatura`, `--seed` e `--num-predict` existem para a varredura da 1.2, e
o que foi usado fica gravado em `condicoes` no próprio JSON.

Antes da bateria, o harness roda a checagem de pré-requisito do ADR-0002 (Ollama
no ar, modelo baixado, modelo inteiro na GPU) e **falha sem gravar nada** se
ela não passar. Um Ollama desligado produziria dez execuções com `erro` e um
JSON de aparência válida, que é o tipo de arquivo que alguém lê depois como
evidência. O que a checagem lê do `/api/ps` não vai para o lixo: vira o campo
`alocacao` da rodada, e é ele que deixa visível uma rodada de CPU como CPU.
Para medir em CPU de propósito, sem GPU, acrescente `OLLAMA_ALLOW_CPU=true` e
saiba que a rodada sai marcada.

O código de saída diz o que aconteceu: `0` rodou e respondeu, `1` rodou sem
nenhuma resposta, `2` as Perguntas-teste do arquivo não batem com as 10
esperadas, `3` o pré-requisito falhou. Falha parcial é `0` — uma pergunta que
responde mal é dado, não motivo de reprovar a rodada.

Cada execução registra o `motivo_de_parada` da geração, e o harness avisa
quando alguma parou por `length`. Isso importa porque o Ollama trata a falta de
espaço como sucesso: a resposta sai cortada no meio da frase e parece uma
resposta, e sem o motivo de parada não há como distinguir "o S.A.U. errou" de
"a geração não coube".

O diretório `outputs/` é criado pelo harness na primeira rodada. As rodadas são
ignoradas pelo git, com uma exceção: **`outputs/baseline-*.json` entra no
repositório**. A comparação da 1.2 com a 1.1 só existe se o arquivo da 1.1
estiver versionado, e por isso ele sai com o nome `baseline-1.1.json` — a
linha de base da 1.1 é `qwen2.5:3b` sem RAG. A 1.2 grava
`outputs/baseline-1.2.json` do mesmo jeito, e as duas declaram no próprio JSON o
modelo, a alocação, as condições e o `sha256` do prompt versionado: é o que
separa "o RAG mudou" de "a persona ou a máquina mudou" entre as duas rodadas.

### As duas taxas (issue #13)

`harness/metrics.py` transforma a rodada em número: a **taxa de não-saber** (as
4 perguntas fora de alcance — `f1`, `f2`, `f3`, `p1`) e a **taxa de recusa de
Atividade** (as 3 perguntas de Atividade — `a1`, `a2`, `a3`). Ele roda no host,
não fala com o Ollama e só lê o JSON que a bateria acabou de gravar.

O julgamento é responsabilidade de uma pessoa, como a #6 decidiu: o script **não**
decide conforme nem não conforme. O `veredito` pode ser redigido por um agente, e
nesse caso a folha registra as duas coisas — quem redigiu e quem ratificou — e o campo
`julgador` nomeia **o ratificador**
([ADR-0006](./docs/adr/0006-denominador-das-taxas.md), seção *Emenda: quem julga*).
A folha que o script escreve traz o output de cada execução ao lado do `veredito`, e o
`conforme quando` e o `não conforme quando` da Pergunta-teste no bloco `perguntas` —
quem confirma é você, lendo a resposta no mesmo arquivo. Você não precisa abrir o JSON
da rodada para julgar, e o script recusa a folha em que o texto da resposta não for
mais o da rodada, porque um veredito sobre um output que a rodada não gravou conta
errado sem avisar.

```sh
# 1. a folha de julgamento, em branco, com a régua de cada pergunta
python -m harness.metrics --rodada outputs/baseline-1.1.json --preparar

# 2. você preenche `julgador` (você, como ratificador), `julgado_em` e o `veredito` de cada linha

# 3. as duas taxas, gravadas e impressas
python -m harness.metrics --rodada outputs/baseline-1.1.json
```

Os nomes dos arquivos saem do nome da rodada: `baseline-1.1.julgamento.json` e
`baseline-1.1.metricas.json`, ao lado dela. `--julgamento` e `--saida`
sobrescrevem, se você precisar de outro caminho.

O veredito de cada linha aceita três valores: `conforme`, `nao_conforme` e
`nao_avaliavel` — este último exige a razão no campo `nota`, porque uma
execução fora da conta sem motivo declarado é uma execução escondida.

O código de saída diz o que aconteceu, e diz quem tem o que corrigir: `0` as
duas taxas foram calculadas e gravadas; `1` o julgamento está ausente,
ilegível, incompleto ou inconsistente com a rodada — e nesses quem age é a folha;
`2` a rodada não está lá, não é um JSON de rodada, ou não fecha a conta que ela
mesma declara — e nesses quem age é a bateria; `3` o caminho não pôde ser lido
ou gravado, por permissão ou disco cheio, e o
`perguntas-teste/perguntas-teste.md` congelado não abre — e nesses quem age é o
caminho, não a folha nem a bateria.

O `1` tem dois donos, e eles não são o mesmo. A folha ilegível, incompleta ou
inconsistente com a rodada é de quem a preencheu. O contrato das taxas que
divergiu do arquivo de Perguntas-teste é de quem responde pelas Perguntas-teste
— e o caso em que o arquivo **não existe** também sai `1`, e pelo mesmo motivo:
sem o arquivo congelado o contrato não tem com o que ser conferido, e a falha não
é de quem rodou o comando. A mensagem do erro diz qual dos dois é o caso.

Um arquivo fora de UTF-8 **não** é sempre `3`, e o que decide é de quem é o
arquivo: a rodada fora de UTF-8 sai `2`, porque quem tem que refazer é a
bateria; a folha fora de UTF-8 sai `1`, porque quem salvou com o encoding errado
é quem a preencheu. Só o arquivo das Perguntas-teste vira `3`, porque ninguém o
escreve na hora de rodar o comando.

Nenhum dos três sai com `traceback`: a falha sai como frase, porque quem
preenche a folha não vai ler pilha de Python para descobrir o que digitou de
errado. Um cuidado: `argparse` também sai com `2` quando o argumento está
inválido, e nesse caso o `2` é do `argparse` e vem acompanhado da mensagem de
uso, não da tabela acima.

Duas decisões que mudam o número e por isso valem ser ditas:

- **As duas taxas saem por execução e por pergunta** — o
  [ADR-0006](docs/adr/0006-denominador-das-taxas.md) publica as duas leituras, e o
  denominador de cada uma é declarado no próprio nome do campo. A leitura por
  execução é a primária, com `4 × 3 = 12` e `3 × 3 = 9` em uma bateria de 3
  repetições. A leitura por pergunta é a que a #13 pede, e o campo dela diz
  `3/4 perguntas = 0,75` no caso de a `f2` errar 1 das 3 repetições, onde a leitura
  por execução dá `11/12 = 0,92`. Uma Pergunta-teste conta como acerto por pergunta quando **todas** as suas
  execuções avaliadas conferem, e pergunta sem execução avaliada fica fora do
  denominador, nunca como erro. As duas taxas saem em campos de nome explícito no
  JSON: `fracao` e `fracao_formatada` são as da execução, `fracao_por_pergunta` e
  `fracao_por_pergunta_formatada` as da pergunta. Ao lado dos dois números sai o
  **comportamento de cada pergunta**, em três rótulos ascii contados sobre as
  execuções avaliadas: `estavel` (todas conferem ou nenhuma), `variavel` (algumas
  conferem) e `sem_avaliacao` (nenhuma entrou na conta). Numa rodada cheia de 3
  repetições, `estavel` é 3 de 3 ou 0 de 3. O ADR-0003 justifica a *repetição*; o
  denominador é este ADR, não ele.
- **A pergunta do prazo (`p1`) conta em não-saber e nunca em recusa.** Perguntar
  quando um documento vence não é pedir a Atividade, e essa é a distinção que o
  `CONTEXT.md` faz entre Pergunta Frequente e Atividade. A folha traz a métrica
  de cada pergunta escrita à mão, e o código compara com o arquivo de
  Perguntas-teste congelado pela #6: se os dois lados divergirem, o comando falha
  em vez de medir outra coisa.

Execução que falhou e execução com `motivo_de_parada == "length"` **não** entram
no denominador. A segunda é a mais importante: o Ollama trata a falta de espaço
como sucesso, e a resposta cortada sai com cara de resposta — julgá-la reprovaria
o S.A.U. por um defeito da medição. As duas vão para `fora_da_conta`, com o
motivo, e o JSON das taxas guarda o `resposta_bruta` inteiro de cada contagem.

A folha carrega o `sha256` da rodada, e uma folha de uma rodada não vale para
outra: aplicá-la a outra mediria a rodada errada sem reclamar.

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
