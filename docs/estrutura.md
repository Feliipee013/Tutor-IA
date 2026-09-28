# Estrutura de pastas

Mapa de onde cada coisa mora no Tutor-IA e qual ticket a cria. Serve para um
agente Implementar localizar o ponto de impacto sem varrer o repositório inteiro.

> **O layout já está em execução para o serviço do bot.** A issue #4 entregou
> o pacote `sau`, o compose e a suíte de testes, e o nome do pacote foi decidido
> junto com ela. Este mapa continua sendo derivado dos tickets das sprints 1.1 e
> 1.2: a coluna `Existe` diz o que já existe, e as pastas marcadas `não` ainda
> não foram criadas. Ajuste o caminho quando a pasta for realmente criada.

## Como usar este mapa

1. Leia a issue e identifique de qual linha da tabela ela é responsável.
2. Vá até a pasta indicada. Se a coluna `Existe` disser `não`, a pasta é criada
   por este ticket.
3. Antes de criar uma pasta nova, confira se o ticket já tem um dono — dois
   tickets concorrentes criando a mesma pasta é o modo mais comum de conflito
   neste projeto.
4. Ao criar a pasta, atualize este arquivo e a issue.

## Raiz

| Caminho | O que é | Existe |
| --- | --- | --- |
| `CONTEXT.md` | glossário do domínio. A fonte do vocabulário de todo o código | sim |
| `AGENTS.md` | como o agente trabalha aqui: skills, regras, Context7 | sim |
| `SETUP.md` | ambiente: `gh`, Context7, e como executar o projeto | sim |
| `Dockerfile` | imagem do serviço do bot, `python -m sau.main` — **issue #4** | sim |
| `docker-compose.yml` | sobe o serviço `bot` (com o Ollama no host, ADR-0002) e o serviço `webhook`, independentes entre si — **issues #4 e #5** | sim |
| `pyproject.toml` | pacote `sau`, dependências e config de pytest, ruff e mypy — **issue #4** | sim |
| `.env.example` | modelo das variáveis de ambiente do compose, com o que é obrigatório — **issues #4 e #5** | sim |
| `scripts/preparar-host.sh` | o passo que o compose não dá conta de fazer: acha a VRAM, confere o Ollama e baixa o modelo se faltar. Idempotente — **issue #7** | sim |
| `opencode.json` | MCP do Context7 e permissões de `bash` por agente | sim |
| `docs/` | documentação versionada (abaixo) | sim |
| `.opencode/agents/` | subagentes `criar-pr`, `criar-ticket` e `executor` | sim |
| `.opencode/skills/` | as skills do projeto: `implementar`, `duvidas-skills`, `entrevistar-com-docs`, `grilling`, `domain-modeling`, `transformar-em-spec`, `transformar-em-tickets` e `contribuir-pr` | sim |
| `.agents/skills/` | skills de terceiros em inglês. Em uso: `code-review`, `triage`, `setup-matt-pocock-skills`, `wayfinder` e `writing-for-agents` — o resto veio do set upstream e não tem par em português | sim |

## `docs/`

| Caminho | O que é | Existe |
| --- | --- | --- |
| `docs/estrutura.md` | este arquivo | sim |
| `docs/agents/` | contratos de tracker, labels, domínio e formato de PR | sim |
| `docs/adr/` | decisões de arquitetura, com o que foi descartado e por quê | sim |
| `docs/adr/0004-vram-por-maquina.md` | a VRAM é declarada por máquina: o contrato, como descobrir o valor e o que fazer sem GPU dedicada — **issue #7** | sim |
| `docs/sprints/` | plano legível da 1.1 e da 1.2 | sim |
| `docs/medicao-modelo/` | a sondagem, o script de medição e a saída de cada máquina — **issue #3** | sim |
| `docs/tempo-primeira-resposta.md` | o tempo de primeira resposta nesta máquina, com as condições e o aviso de que não é a do ADR-0002 — **issue #7** | sim |
| `docs/limitacoes.md` | documento de limitações do modelo — **issue #14** | não |

## `docs/medicao-modelo/` — a evidência da escolha do modelo

O que sustenta o [ADR-0003](./adr/0003-modelo-do-ollama.md). Fica versionado
porque a escolha de modelo é a decisão mais fácil de rever sem evidência: o
número de velocidade só vale para a máquina em que saiu, e por isso cada máquina
tem o seu próprio arquivo.

| Caminho | O que faz | Ticket | Existe |
| --- | --- | --- | --- |
| `docs/medicao-modelo/sondagem.md` | as 4 perguntas de sondagem, com o comportamento esperado de cada uma | #3 | sim |
| `docs/medicao-modelo/medir.py` | mede tamanho, tempo e a resposta à pergunta sem resposta; só stdlib | #3 | sim |
| `docs/medicao-modelo/resultado-cpu.md` | a saída medida em CPU, nesta máquina, que **não** é a máquina do ADR-0002 | #3 | sim |
| `docs/medicao-modelo/resultado-gpu.md` | o passo a passo para quem tem a máquina NVIDIA colar o número de velocidade | #3 | sim |

A sondagem **não** é o conjunto de Perguntas-teste: as 10 Perguntas-teste são da
#6 e moram em `perguntas-teste/`. A sondagem existe para escolher o modelo, e uma
Pergunta-teste medida contra modelo nenhum não compara nada.

## `sau/` — o pacote do bot

Nome do pacote é decisão fechada junto com a #4. O grafo é a espinha do projeto:
classificação da intenção, e a 1.2 entra como rota nova **dentro** desse mesmo
grafo, não como serviço à parte.

| Caminho | O que faz | Ticket | Existe |
| `sau/config.py` | lê do ambiente o que a #4 precisa: modelo, timeout, porta, a URL base do Ollama no host e a VRAM total da máquina; e o que a #5 precisa: as duas credenciais do Telegram, a porta do webhook e a URL da API. Temperatura e `k` do semáforo ainda não são lidos — chegam nos tickets que vão escrevê-los, e a linha cresce aqui quando eles existirem | #4, #5 | sim |
| `sau/prereqs.py` | checagem rigorosa de pré-requisitos (conectividade, modelo e GPU no host) | #4 | sim |
| `sau/main.py` | entrypoint do serviço com logs estruturados e health server. O prefixo da linha é `[SAU]`, do S.A.U.; o serviço que emitiu a linha é identificado pelo nome do módulo nela mesma (`sau.main` contra `sau.telegram.webhook`), e não pelo prefixo | #4 | sim |
| `sau/persona.py` | o prompt versionado do S.A.U., com todas as regras de comportamento | #10 | não |
| `sau/telegram/webhook.py` | handler do webhook, com acuse de recibo fixo ao Aluno antes de qualquer inferência, registro do update bruto e conferência do `secret_token` | #5 | sim |
| `sau/telegram/__main__.py` | entrypoint do serviço `webhook`, para o log sair com o nome do módulo e não `__main__` | #5 | sim |
| `sau/inference/ollama.py` | cliente do Ollama, que roda **no host** e é alcançado por `host.docker.internal:11434` ([ADR-0002](./adr/0002-topologia-do-ollama.md)) | #7 | sim |
| `sau/inference/fumaca.py` | prova de fumaça: roda as checagens, pede uma geração e mostra o tempo de cada etapa | #7 | sim |
| `sau/inference/semaphore.py` | fila com teto e semáforo em frente à inferência | #11 | não |
| `sau/graph/state.py` | estado da conversa, isolado por Aluno | #9 | não |
| `sau/graph/graph.py` | monta o grafo LangGraph do turno | #8 | não |
| `sau/graph/nodes.py` | classificar intenção, recuperar, responder, encaminhar | #8, P5 | não |
| `sau/rag/embed.py` | embeddings locais via Ollama e indexação do corpus | P3 | não |
| `sau/rag/retrieve.py` | busca os `k` chunks mais próximos, com a Fonte | P4 | não |

## Conteúdo do time

| Caminho | O que é | Ticket | Existe |
| --- | --- | --- | --- |
| `perguntas-teste/` | as 10 Perguntas-teste, com o comportamento esperado de cada uma | #6 | sim |
| `corpus/` | os quatro documentos autorados, um por categoria, com as contradições plantadas | P1 | não |
| `outputs/` | saída bruta do harness, ignorada pelo git | #12 | não |
| `tests/` | suíte `pytest`, com `test_config.py` e `test_prereqs.py` da #4, `test_webhook.py` da #5 e `test_ollama.py` e `test_fumaca.py` da #7 | #4, #5, #7 | sim |

O `corpus/` é quebrado em unidades de recuperação pela própria equipe: cada
`##` dentro de um documento responde a uma Pergunta Frequente, então **o chunk é
a seção** e o chunking vira uma escolha da equipe, não uma heurística.

## `harness/`

| Caminho | O que faz | Ticket | Existe |
| --- | --- | --- | --- |
| `harness/run.py` | roda as 10 Perguntas-teste e grava os outputs brutos | #12 | não |
| `harness/metrics.py` | taxa de não-saber e taxa de recusa de Atividade | #13 | não |
| `harness/casos.py` | os cinco casos de alucinação, com o motivo do erro de cada um | P2 | não |

O harness é a régua das duas sprints: a 1.2 roda **o mesmo** harness sobre
**os mesmos** casos, e é por isso que ele precisa ser reexecutável sem refazer
a implementação.

## Onde as coisas entram

| Assunto | Onde |
| --- | --- |
| Decisão de arquitetura e o que foi descartado | `docs/adr/` |
| Vocabulário do domínio | `CONTEXT.md` |
| Plano da sprint e ordem de entrega | `docs/sprints/` |
| Formato da PR, título e corpo | `docs/agents/pull-request.md` |
| Ambiente e execução | `SETUP.md` |
| Estado das sprints no quadro | [Tutor IA - KANBAN](https://github.com/users/Feliipee013/projects/3) |
