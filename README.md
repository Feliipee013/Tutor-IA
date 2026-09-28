# Tutor-IA (S.A.U. - Sistema de Apoio Unopar)

Tutor virtual 24/7 para atendimento a dúvidas de rotina dos alunos de cursos EaD da Unopar, com foco no plantão da madrugada.

## Arquitetura e Topologia

Conforme definido no [ADR-0002](docs/adr/0002-topologia-do-ollama.md), adotamos uma arquitetura híbrida de execução:

- **Ollama no Host:** Executa nativamente no sistema operacional da máquina servidora para utilizar diretamente os drivers NVIDIA e a GPU sem complexidade de container runtime passthrough.
- **Bot no Container Docker:** O serviço do bot S.A.U. é executado via Docker Compose e comunica-se com a API do Ollama no host através de `http://host.docker.internal:11434` (viabilizado pelo mapeamento `extra_hosts: ["host.docker.internal:host-gateway"]` no Linux).
- **Falha Alta (Fail-fast):** O serviço do bot verifica rigorosamente na inicialização a conectividade com o Ollama, a disponibilidade do modelo e a alocação em GPU (VRAM). O confronto é entre o `size_vram` que o Ollama relata e a VRAM total que a máquina declara, porque nenhum dos dois lados sozinho prova GPU. O serviço falha imediatamente se o modelo cair silenciosamente para CPU, protegendo a experiência do Aluno contra lentidão excessiva.

## Pré-requisitos no Host

Antes de subir os containers, prepare o host seguindo estes passos:

### 1. Verificar Driver NVIDIA e GPU

```sh
nvidia-smi
```

Certifique-se de que a GPU é reconhecida e o driver está operante.

Anote também a VRAM total da placa, que é o número que o serviço confronta com o
que o Ollama relata:

```sh
nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits
```

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

O modelo fica persistido no diretório padrão do host (`~/.ollama`), sobrevivendo a `docker compose down` e `docker compose up`.

### 4. Confirmar Alocação em GPU

```sh
ollama ps
```

Verifique a coluna `PROCESSOR`. Ela deve indicar `100% GPU`.

---

## Executando o Serviço

### Subir o Bot via Docker Compose

O `.env` é **opcional**. Há dois caminhos, e o Compose dá precedência ao
ambiente do shell sobre o `.env` — quem já exportou a variável no shell não
precisa criar arquivo nenhum.

```sh
# Caminho rápido (recomendado) - não cria .env
export OLLAMA_HOST=0.0.0.0:11434      # só no host, antes do ollama serve
export VRAM_TOTAL_MIB=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | head -1)
docker compose up --build

# Caminho com .env - para fixar valores e sobrescrever
cp .env.example .env
$EDITOR .env
docker compose up --build
```

Note que `OLLAMA_HOST` não entra no `.env`: ele é consumido pelo `ollama serve`,
que roda no host, e não pelo container.

Para executar em segundo plano:

```sh
docker compose up -d --build
```

Para visualizar os logs estruturados com o identificador `[SAU-BOT]`:

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

---

## Variáveis de Ambiente

Copie [`.env.example`](.env.example) para `.env` e ajuste o que precisar, ou passe
as variáveis direto ao `docker compose up`. O `.env` é lido **pelo Compose**:
rodar `python -m sau.main` direto no host **ignora** o `.env`, porque o Python
não lê `.env` sozinho.

| Variável | Padrão | Obrigatória | Descrição |
| --- | --- | --- | --- |
| `OLLAMA_BASE_URL` | `http://host.docker.internal:11434` | Não | URL da API do Ollama acessível a partir do container |
| `OLLAMA_MODEL` | `qwen2.5:3b` | Não | Nome do modelo de linguagem a ser utilizado |
| `OLLAMA_ALLOW_CPU` | `false` | Não | Se `false`, o serviço falha alto se o modelo for alocado em CPU. Se `true`, autoriza CPU (apenas para testes/dev sem GPU) |
| `OLLAMA_TIMEOUT` | `30` | Não | Timeout em segundos para requisições ao Ollama |
| `VRAM_TOTAL_MIB` | — (ausente) | **Sim** | VRAM total da máquina em MiB, exatamente como o `nvidia-smi` imprime. Sem ela a checagem do ADR-0002 não tem contra o que comparar o `size_vram` do Ollama, e o serviço falha alto |
| `BOT_PORT` | `8000` | Não | Porta HTTP exposta pelo container |
| `LOG_LEVEL` | `INFO` | Não | Nível de detalhamento dos logs (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |

A VRAM total não é exposta por nenhum endpoint do Ollama — o `/api/ps` só
relata o `size_vram` de cada modelo — então ela tem de vir do host:

```sh
export VRAM_TOTAL_MIB=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | head -1)
```

O `head -1` não é decoração: o `nvidia-smi` imprime **uma linha por GPU**, e sem
o filtro uma máquina com duas placas entrega `"4096\n4096"`, que não é um inteiro.
Com mais de uma placa, preencha à mão o total da que roda o Ollama.

### Execução em máquinas sem GPU (Ambiente de Testes / CI)

Caso esteja desenvolvendo em máquina sem GPU dedicada, autorize explicitamente a execução em CPU:

```sh
OLLAMA_ALLOW_CPU=true docker compose up --build
```

Com `OLLAMA_ALLOW_CPU=true`, a `VRAM_TOTAL_MIB` deixa de ser obrigatória: a
checagem de VRAM passa a registrar warning e a execução segue, porque em máquina
sem GPU não há VRAM para conferir.

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