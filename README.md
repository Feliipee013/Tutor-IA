# Tutor-IA (S.A.U. - Sistema de Apoio Unopar)

Tutor virtual 24/7 para atendimento a dúvidas de rotina dos alunos de cursos EaD da Unopar, com foco no plantão da madrugada.

## Arquitetura e Topologia

Conforme definido no [ADR-0002](docs/adr/0002-topologia-do-ollama.md), adotamos uma arquitetura híbrida de execução:

- **Ollama no Host:** Executa nativamente no sistema operacional da máquina servidora para utilizar diretamente os drivers NVIDIA e a GPU sem complexidade de container runtime passthrough.
- **Bot no Container Docker:** O serviço do bot S.A.U. é executado via Docker Compose e comunica-se com a API do Ollama no host através de `http://host.docker.internal:11434` (viabilizado pelo mapeamento `extra_hosts: ["host.docker.internal:host-gateway"]` no Linux). O serviço `webhook` usa o mesmo caminho desde a #8, porque é ele que roda o turno de resposta.
- **Falha Alta (Fail-fast):** O serviço do bot verifica rigorosamente na inicialização a conectividade com o Ollama, a disponibilidade do modelo e a alocação em GPU (VRAM). O confronto é entre o `size_vram` que o Ollama relata e a VRAM total que a máquina declara, porque nenhum dos dois lados sozinho prova GPU. O serviço falha imediatamente se o modelo cair silenciosamente para CPU, protegendo a experiência do Aluno contra lentidão excessiva.
- **O `webhook` não falha alto, e é de propósito:** ele é o canal do Telegram, e precisa continuar no ar para acusejar o Aluno mesmo com o modelo fora. Ollama indisponível vira uma mensagem amigável ao Aluno, não um serviço fora do ar.

## Pré-requisitos no Host

O passo inteiro cabe em um comando, e ele pode ser repetido à vontade — não
baixa o modelo duas vezes:

```sh
scripts/preparar-host.sh
```

O script descobre a VRAM da sua placa, confere que o Ollama responde, baixa o
modelo se ele ainda não estiver no host, e imprime no final a linha
`export VRAM_TOTAL_MIB=...` para você usar no `docker compose up`. Se algo
estiver errado, ele para e diz o quê.

Abaixo está o mesmo passo escrito à mão, para quando algo der errado e você
precisar entender o que o script fez.

### 1. Verificar a GPU e anotar a VRAM

O número que o serviço confronta é a **VRAM total da placa**, em MiB. Ele não
vem de nenhum endpoint do Ollama — o `/api/ps` só diz o quanto cada modelo
ocupou — então sai do sistema:

**Placa NVIDIA:**

```sh
nvidia-smi
nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | head -1
```

**Placa de qualquer outra marca** (AMD, Intel): o `nvidia-smi` não existe, e o
kernel publica a mesma informação em `/sys/class/drm`:

```sh
cat /sys/class/drm/card*/device/mem_info_vram_total
```

Esse número vem em **bytes**. Divida por 1048576 para ter MiB, arredondando
**para cima** — é assim que o script faz. Uma GPU integrada costuma não ter esse
arquivo, e tudo bem: ela não tem VRAM para declarar.

Se a máquina tem mais de uma placa, o `head -1` no comando do `nvidia-smi` é o
que evita que o script receba duas linhas e não saiba qual usar. Com o
`/sys/class/drm`, o script para e mostra as duas em vez de escolher por você.
Detalhes e o resto das receitas, no
[ADR-0004](docs/adr/0004-vram-por-maquina.md).

**Sem GPU dedicada?** Tudo acima não se aplica, e o serviço sobe assim mesmo —
com `OLLAMA_ALLOW_CPU=true`. Ele roda em CPU, e nesse caso **não mede tempo**: um
número de CPU é plausível e errado ao mesmo tempo. Ver
[Execução em máquinas sem GPU](#execução-em-máquinas-sem-gpu-ambiente-de-testes--ci)
abaixo.

### 2. Iniciar o Ollama no Host

Instale o Ollama se ainda não o tiver ([instruções oficiais](https://docs.ollama.com/linux)) e inicie o serviço com o `OLLAMA_HOST` apontando para todas as interfaces:

```sh
OLLAMA_HOST=0.0.0.0:11434 ollama serve
```

**Por que o `OLLAMA_HOST` é obrigatório:** o bind padrão do Ollama é
`127.0.0.1:11434`, e o container do bot chega no IP da bridge do Docker — não no
loopback do host. Sem esta variável, a conexão é recusada na hora
(`Errno 111: Connection refused`) e o serviço nem chega à checagem de
pré-requisito.

**Se o seu Ollama é um serviço do systemd** — é o que sobra depois de instalar
pelo pacote do Arch, do Ubuntu ou pelo instalador oficial — o comando acima não
resolve. Ele sobe um Ollama a mais, no seu terminal, e some quando você fecha o
terminal; o serviço do sistema, que é o que o `docker compose` encontra, continua
no `127.0.0.1`. Nesse caso a variável vai no serviço:

```sh
sudo tee /etc/systemd/system/ollama.service.d/host.conf >/dev/null <<'EOF'
[Service]
Environment="OLLAMA_HOST=0.0.0.0:11434"
EOF
sudo systemctl daemon-reload
sudo systemctl restart ollama
```

São três comandos, e o último reinicia o Ollama: some com o que já estava
carregado. Dá para conferir se pegou com estes dois:

```sh
systemctl show ollama --property=Environment   # tem que aparecer OLLAMA_HOST=0.0.0.0:11434
ss -ltn | grep 11434                           # tem que dar *:11434, e não 127.0.0.1:11434
```

O primeiro diz o que o serviço recebeu; o segundo diz em que endereço ele está
escutando de verdade. Se o primeiro tiver a variável e o segundo mostrar
`127.0.0.1:11434`, o que está na frente da porta é outro processo — e o comando
`ollama` do seu PATH pode estar apontando para o outro, o que faz a alteração
parecer funcionar sem ter funcionado.

O `export OLLAMA_HOST=0.0.0.0:11434` no seu shell só vale se **você** for subir o
Ollama com `ollama serve`. Com serviço do systemd, quem precisa da variável é o
serviço.

> **Ressalva de segurança:** `0.0.0.0` expõe a porta 11434 em **todas** as
> interfaces da rede, não só na localhost. Em rede confiável, com a máquina de
> inference atrás de firewall, isso é o preço do bind. Se a máquina estiver em
> rede não confiável, restrinja o bind a uma interface que só a bridge do Docker
> alcance, ou coloque um proxy com autenticação na frente.

Verifique a resposta da API:

```sh
curl -s http://localhost:11434/api/version
```

### 3. Baixar o Modelo Selecionado

Conforme o [ADR-0003](docs/adr/0003-modelo-do-ollama.md), o modelo padrão é o `qwen2.5:3b`:

```sh
ollama pull qwen2.5:3b
```

O modelo fica no diretório que o `OLLAMA_MODELS` apontar, e **não
necessariamente em `~/.ollama`**. O `OLLAMA_MODELS` do serviço é quem decide, e o
padrão dele muda de instalação para instalação. Numa máquina com pouco espaço na
home, é comum apontar para um disco maior:

```sh
# no serviço do Ollama, antes de subir
OLLAMA_MODELS=/mnt/data/ollama/models
```

Para ver onde os modelos estão nesta máquina:

```sh
systemctl show ollama --property=Environment | grep OLLAMA_MODELS
```

O modelo sobrevive a `docker compose down` e `docker compose up` porque vive no
host, não em volume do compose.

### 4. Confirmar Alocação em GPU

```sh
ollama ps
```

Verifique a coluna `PROCESSOR`. Ela deve indicar `100% GPU`.

O `ollama ps` só lista o que está **carregado**. Se a tabela estiver vazia, rode
`ollama run qwen2.5:3b` e interrompa com Ctrl+C, e olhe de novo. O
`scripts/preparar-host.sh` faz essa carga por você.

---

## Executando o Serviço

### Subir o Bot via Docker Compose

O `.env` é **opcional**. Há dois caminhos, e o Compose dá precedência ao
ambiente do shell sobre o `.env` — quem já exportou a variável no shell não
precisa criar arquivo nenhum.

```sh
# Caminho rápido (recomendado) - não cria .env
scripts/preparar-host.sh
# ele imprime a linha "export VRAM_TOTAL_MIB=..." — copie e rode ela
docker compose up --build

# Caminho com .env - para fixar valores e sobrescrever
cp .env.example .env
$EDITOR .env
docker compose up --build
```

Note que `OLLAMA_HOST` não entra no `.env`: ele é consumido pelo `ollama serve`,
que roda no host, e não pelo container.

Para medir o tempo de primeira resposta, ou só para conferir que o modelo
responde de dentro do container:

```sh
VRAM_TOTAL_MIB=<o da sua máquina> docker compose run --rm bot python -m sau.inference.fumaca
```

Para executar em segundo plano:

```sh
docker compose up -d --build
```

Para visualizar os logs estruturados com o identificador `[SAU]`:

```sh
docker compose logs -f bot
```

Para parar o serviço:

```sh
docker compose down
```

### Verificação de Saúde (Health Check)

O container expõe a porta `8000` (configurável via `BOT_PORT`):

```sh
curl -s http://localhost:8000/health
```

Resposta esperada:
```json
{"status": "healthy", "servico": "sau-bot", "identidade": "S.A.U. - Sistema de Apoio Unopar"}
```

### Canal do Telegram (Webhook)

O serviço `webhook` recebe as mensagens do Aluno e responde. São **duas**
mensagens, nesta ordem: um **acuse de recibo fixo**, imediato, e a **resposta do
modelo**, logo depois. O turno roda no próprio `webhook` (o grafo LangGraph está
em [`sau/graph/`](sau/graph/)), que é o que a [emenda da #8 ao ADR-0002](docs/adr/0002-topologia-do-ollama.md)
registra.

```sh
# as duas credenciais são obrigatórias para o serviço `webhook`
docker compose up --build webhook
docker compose logs -f webhook
```

O Telegram entrega updates por POST numa URL pública, então a porta local
precisa de um túnel HTTPS, e a URL precisa ser registrada com `setWebhook`. O
passo a passo completo, com `cloudflared`, está em
[`SETUP.md` §3](./SETUP.md#canal-do-telegram-issue-5).

O `webhook` não roda a checagem de pré-requisito do `bot`, e isso é de propósito:
se o Ollama estiver fora, o serviço continua no ar, o Aluno recebe o acuse e uma
segunda mensagem dizendo que houve um problema — nunca um stack trace, e nunca um
5xx que faria o Telegram reentregar o update. O motivo da falha fica inteiro no
log do serviço.

> **O que ainda não existe.** O prompt do turno ainda não tem a persona do S.A.U.:
> ele é a mensagem do Aluno com a instrução mínima de respondê-la, e é isso que a
> #10 substitui. A posição na fila e o semáforo são da #11, que também substitui
> a thread por turno — até lá, duas mensagens seguidas do mesmo Aluno podem ser
> respondidas fora de ordem. O histórico por conversa e o isolamento entre Alunos
> são da #9.

---

## Variáveis de Ambiente

Copie [`.env.example`](.env.example) para `.env` e ajuste o que precisar, ou passe
as variáveis direto ao `docker compose up`. O `.env` é lido **pelo Compose**:
rodar `python -m sau.main` direto no host **ignora** o `.env`, porque o Python
não lê `.env` sozinho.

| Variável | Padrão | Obrigatória | Descrição |
| --- | --- | --- | --- |
| `OLLAMA_BASE_URL` | `http://host.docker.internal:11434` | Não | URL da API do Ollama acessível a partir do container. Vale para o `bot` e para o `webhook` desde a #8 |
| `OLLAMA_MODEL` | `qwen2.5:3b` | Não | Nome do modelo de linguagem a ser utilizado |
| `OLLAMA_ALLOW_CPU` | `false` | Não | Se `false`, o serviço falha alto se o modelo for alocado em CPU. Se `true`, autoriza CPU (apenas para testes/dev sem GPU) |
| `OLLAMA_TIMEOUT` | `30` | Não | Timeout em segundos para requisições ao Ollama |
| `VRAM_TOTAL_MIB` | — (ausente) | **Sim** | VRAM total da máquina em MiB, exatamente como o `nvidia-smi` imprime. Sem ela a checagem do ADR-0002 não tem contra o que comparar o `size_vram` do Ollama, e o serviço falha alto |
| `BOT_PORT` | `8000` | Não | Porta HTTP exposta pelo container do serviço `bot` |
| `LOG_LEVEL` | `INFO` | Não | Nível de detalhamento dos logs (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `TELEGRAM_BOT_TOKEN` | — (ausente) | **Sim** (só para `webhook`) | Token que o `@BotFather` entrega. É o que faz o Aluno achar o S.A.U. pelo `@username`. Sem ele o serviço `webhook` falha alto na subida; o `bot` sobe sem ele |
| `TELEGRAM_WEBHOOK_SECRET_TOKEN` | — (ausente) | **Sim** (só para `webhook`) | Chave que o Telegram devolve no header `X-Telegram-Bot-Api-Secret-Token` e que fecha a porta do endpoint. Gere com `openssl rand -hex 16` |
| `TELEGRAM_WEBHOOK_PORT` | `8080` | Não | Porta do webhook no host. O container escuta sempre em 8080 |
| `TELEGRAM_API_BASE` | `https://api.telegram.org` | Não | URL base da Bot API do Telegram. Existe para apontar para uma Bot API local em desenvolvimento; o compose não a expõe, porque o canal conversa com a do Telegram |

A VRAM total não é exposta por nenhum endpoint do Ollama — o `/api/ps` só
relata o `size_vram` de cada modelo — então ela tem de vir do host:

```sh
# placa NVIDIA
export VRAM_TOTAL_MIB=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | head -1)

# qualquer outra placa: o valor vem em bytes, divida por 1048576 arredondando para cima
export VRAM_TOTAL_MIB=$(( ($(cat /sys/class/drm/card*/device/mem_info_vram_total | head -1) + 1048575) / 1048576 ))
```

Ou, mais simples, deixe o `scripts/preparar-host.sh` fazer isso e imprimir a
linha pronta.

O `head -1` não é decoração: o `nvidia-smi` imprime **uma linha por GPU**, e sem
o filtro uma máquina com duas placas entrega `"4096\n4096"`, que não é um inteiro.
Com mais de uma placa, preencha à mão o total da que roda o Ollama. E confira o
valor na primeira vez de cada máquina: um total errado aprova a checagem errada,
e isso não aparece como erro. O [ADR-0004](docs/adr/0004-vram-por-maquina.md)
tem o resto das receitas.

### Execução em máquinas sem GPU (Ambiente de Testes / CI)

Caso esteja desenvolvendo em máquina sem GPU dedicada, autorize explicitamente a execução em CPU:

```sh
OLLAMA_ALLOW_CPU=true docker compose up --build
```

Com `OLLAMA_ALLOW_CPU=true`, a `VRAM_TOTAL_MIB` deixa de ser obrigatória: a
checagem de VRAM passa a registrar warning e a execução segue, porque em máquina
sem GPU não há VRAM para conferir.

**Rodar em CPU não é medir em CPU.** O serviço sobe e atende, e o número de
tempo que sair daí descreve o processador da sua máquina, não a placa de
produção. Para medir tempo, é preciso GPU dedicada. A fumaça e o
[`medir.py`](docs/medicao-modelo/medir.py) param com erro antes de gerar
qualquer tempo quando o modelo está em CPU, a não ser que a CPU esteja
autorizada — pela flag `--permitir-cpu` ou pelo `OLLAMA_ALLOW_CPU=true` que o
compose repassa para o container. Nas duas o número sai marcado como número de
CPU, e o aviso diz qual das duas portas foi aberta.

---

## Desenvolvimento e Validação

Para rodar a suíte de testes e os linters localmente:

```sh
# Ativar o ambiente virtual
source .venv/bin/activate

# Executar testes unitários
pytest

# Verificar padrões e estilo de código
ruff check .

# Verificar checagem estática de tipos
mypy .
```

Consulte também:
- [`CONTEXT.md`](CONTEXT.md) para o vocabulário e regras de domínio.
- [`SETUP.md`](SETUP.md) para detalhes de configuração do ambiente e ferramentas.
- [`docs/estrutura.md`](docs/estrutura.md) para o mapa de pastas e responsabilidades.