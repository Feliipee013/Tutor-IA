# Tutor-IA (S.A.U. - Sistema de Apoio Unopar)

Tutor virtual 24/7 para atendimento a dúvidas de rotina dos alunos de cursos EaD da Unopar, com foco no plantão da madrugada.

## Arquitetura e Topologia

Conforme definido no [ADR-0002](docs/adr/0002-topologia-do-ollama.md), adotamos uma arquitetura híbrida de execução:

- **Ollama no Host:** Executa nativamente no sistema operacional da máquina servidora para utilizar diretamente os drivers NVIDIA e a GPU sem complexidade de container runtime passthrough.
- **Bot no Container Docker:** O serviço do bot S.A.U. é executado via Docker Compose e comunica-se com a API do Ollama no host através de `http://host.docker.internal:11434` (viabilizado pelo mapeamento `extra_hosts: ["host.docker.internal:host-gateway"]` no Linux).
- **Falha Alta (Fail-fast):** O serviço do bot verifica rigorosamente na inicialização a conectividade com o Ollama, a disponibilidade do modelo e a alocação em GPU (VRAM). O serviço falha imediatamente se o modelo cair silenciosamente para CPU, protegendo a experiência do Aluno contra lentidão excessiva.

## Pré-requisitos no Host

Antes de subir os containers, prepare o host seguindo estes passos:

### 1. Verificar Driver NVIDIA e GPU

```sh
nvidia-smi
```

Certifique-se de que a GPU é reconhecida e o driver está operante.

### 2. Iniciar o Ollama no Host

Instale o Ollama se ainda não o tiver ([instruções oficiais](https://docs.ollama.com/linux)) e inicie o serviço:

```sh
ollama serve
```

Verifique a resposta da API:

```sh
curl -s http://localhost:11434/api/version
```

### 3. Baixar o Modelo Selecionado

Conforme o [ADR-0003](docs/adr/0003-modelo-do-ollama.md), o modelo padrão é o `llama3.2:3b`:

```sh
ollama pull llama3.2:3b
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

Para construir a imagem e iniciar o serviço do bot:

```sh
docker compose up --build
```

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

As seguintes variáveis podem ser configuradas no arquivo `.env` ou passadas diretamente ao compose:

| Variável | Padrão | Descrição |
| --- | --- | --- |
| `OLLAMA_BASE_URL` | `http://host.docker.internal:11434` | URL da API do Ollama acessível a partir do container |
| `OLLAMA_MODEL` | `llama3.2:3b` | Nome do modelo de linguagem a ser utilizado |
| `OLLAMA_ALLOW_CPU` | `false` | Se `false`, o serviço falha alto se o modelo for alocado em CPU. Se `true`, autoriza CPU (apenas para testes/dev sem GPU) |
| `OLLAMA_TIMEOUT` | `30` | Timeout em segundos para requisições ao Ollama |
| `BOT_PORT` | `8000` | Porta HTTP exposta pelo container |
| `LOG_LEVEL` | `INFO` | Nível de detalhamento dos logs (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |

### Execução em máquinas sem GPU (Ambiente de Testes / CI)

Caso esteja desenvolvendo em máquina sem GPU dedicada, autorize explicitamente a execução em CPU:

```sh
OLLAMA_ALLOW_CPU=true docker compose up --build
```

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