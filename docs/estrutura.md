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
| `docker-compose.yml` | sobe o serviço `bot` (com o Ollama no host, ADR-0002) e o serviço `webhook`, independentes entre si e ambos alcançando o Ollama do host. Desde a #9 o `webhook` monta o volume nomeado que guarda o arquivo de conversas — **issues #4, #5, #8 e #9** | sim |
| `docker-compose.dev.yml` | override de dev: o serviço `ngrok` (túnel para o `webhook:8080`) e o `webhook` apontado para a API dele (`NGROK_API_URL`) com `TELEGRAM_PUBLIC_URL` opcional. O compose puro nunca inclui o ngrok | sim |
| `pyproject.toml` | pacote `sau`, dependências (o `langgraph` entrou com a #8) e config de pytest, ruff e mypy — **issues #4 e #8** | sim |
| `.env.example` | modelo das variáveis de ambiente do compose, com o que é obrigatório — **issues #4, #5, #8 e #9** | sim |
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
| `docs/adr/0005-estado-da-conversa.md` | o estado da conversa vive num arquivo, isolado por `chat_id`, com TTL e ordem FIFO por conversa — **issue #9** | sim |
| `docs/adr/0006-denominador-das-taxas.md` | as duas taxas da 1.1 saem por execução e por pergunta, e as duas são publicadas: o denominador de cada uma, e quando uma Pergunta-teste conta como acerto. Emenda: o veredito é responsabilidade de uma pessoa, pode ser redigido por um agente, e a folha nomeia **quem ratificou** — **issue #13** | sim |
| `docs/adr/0007-corpus-derivado-do-instrumento.md` | o Corpus tem quatro documentos (três do instrumento + Seguro por emenda), com cobertura de blocos reais do processo. Seguro de Acidentes Pessoais é coberto no documento próprio | sim |
| `docs/adr/0008-recuperacao-sem-classificacao-de-intencao.md` | a recuperação entra como **nó único, em todo turno**, sem classificação de intenção nem roteamento; a topologia de três rotas que a 1.1.2 desenhava foi abandonada | sim |
| `docs/adr/0009-exemplo-de-encaminhamento-na-persona.md` | a persona ganha **um** exemplo de Encaminhamento completo, porque a linha de base mostra o modelo encerrando em 5 tokens. Reverte `10d9c56` e `3400b32` | sim |
| `docs/sprints/` | plano legível da 1.1 e da 1.2 | sim |
| `docs/medicao-modelo/` | a sondagem, o script de medição e a saída de cada máquina — **issue #3** | sim |
| `docs/tempo-primeira-resposta.md` | o tempo de primeira resposta na GTX 1650 do ADR-0002, com as condições e a nota dos números antigos da RX 7600 — **issue #7** | sim |
| `docs/fila-e-semaforo.md` | a máquina do `k` do semáforo, o roteiro para medi-lo e as duas contas do teste de campo, com os campos em branco que a medição vai preencher — **issue #11** | sim |
| `docs/relato-1.1.md` | a página de relato da 1.1: a régua declarada, as duas taxas, a leitura de tom e acolhimento e as limitações. Os números dependem da bateria rodada — **issue #13** | sim |
| `docs/relato-1.2.md` | a página de relato da 1.2: as três métricas nos cinco Casos, as taxas da 1.1 republicadas e a discussão do que a Alucinação revela — **issue #28** | sim |
| `docs/limitacoes.md` | documento de limitações do modelo — **issue #14** | sim |

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

Nome do pacote é decisão fechada junto com a #4. O grafo é a espinha do projeto: a
recuperação da 1.2 entra como **um nó a mais dentro** desse mesmo grafo, sem
classificação de intenção e sem aresta condicional
([ADR-0008](./adr/0008-recuperacao-sem-classificacao-de-intencao.md)).

| Caminho | O que faz | Ticket | Existe |
| `sau/config.py` | lê do ambiente o que a #4 precisa: modelo, timeout, porta, a URL base do Ollama no host e a VRAM total da máquina; o que a #5 precisa: as duas credenciais do Telegram, a porta do webhook e a URL da API; e o que a #9 precisa: o caminho do arquivo de conversas e o TTL em minutos. A #8 não acrescenta campo novo — o `webhook` passa a ler o mesmo `OLLAMA_*` que o `bot` já lia. Desde a #11 também o `INFERENCIA_K` e o `INFERENCIA_FILA_TETO`, o `k` do semáforo e o teto da fila, com a mesma validação de inteiro positivo do TTL. A temperatura ainda não é lida — chega no ticket que for escrevê-la, e a linha cresce aqui quando ele existir | #4, #5, #8, #9, #11 | sim |
| `sau/prereqs.py` | checagem rigorosa de pré-requisitos (conectividade, modelo e GPU no host) | #4 | sim |
| `sau/main.py` | entrypoint do serviço com logs estruturados e health server. O prefixo da linha é `[SAU]`, do S.A.U.; o serviço que emitiu a linha é identificado pelo nome do módulo nela mesma (`sau.main` contra `sau.telegram.webhook`), e não pelo prefixo | #4 | sim |
| `sau/persona.py` | o prompt versionado do S.A.U., com todas as regras de comportamento, e a composição do prompt do turno: desde a #10 é quem monta as regras com a mensagem do Aluno, e desde a #9 é quem junta o histórico da conversa e cerca o texto do Aluno entre marcadores. A 1.2 soma **um** exemplo de Encaminhamento completo ([ADR-0009](./adr/0009-exemplo-de-encaminhamento-na-persona.md)), e `tests/test_persona.py:503` muda de critério junto | #9, #10, P6 | sim |
| `sau/telegram/webhook.py` | handler do webhook: registro do update bruto, conferência do `secret_token` e acuse de recibo fixo ao Aluno antes de qualquer inferência. Desde a #8 é também quem dispara o turno (em thread, fora do request) e quem vira a falha do modelo em mensagem amigável. Desde a #9 é quem monta o registro de conversas e quem roda o turno dentro da fila FIFO da conversa do Aluno. Desde a #11 é quem adquire o semáforo **dentro** dessa fila — o que torna "um Aluno nunca tem dois turnos" estrutural — e quem escreve as três mensagens do turno: acuse, posição na fila com a estimativa, e a recusa educada quando a fila passa do teto | #5, #8, #9, #11 | sim |
| `sau/telegram/__main__.py` | entrypoint do serviço `webhook`, para o log sair com o nome do módulo e não `__main__` | #5 | sim |
| `sau/inference/ollama.py` | cliente do Ollama, que roda **no host** e é alcançado por `host.docker.internal:11434` ([ADR-0002](./adr/0002-topologia-do-ollama.md)). Desde a #8 é usado pelos dois serviços: o `bot` na checagem e na fumaça, o `webhook` no turno | #7, #8 | sim |
| `sau/inference/fumaca.py` | prova de fumaça: roda as checagens, pede uma geração e mostra o tempo de cada etapa | #7 | sim |
| `sau/inference/semaphore.py` | a fila de senha e o `k` de vagas em frente à inferência: entrega a `PosicaoNaFila` por callback e levanta `FilaCheiaError` acima do teto. Não conhece o Telegram — quem escreve para o Aluno é o `webhook`. O `relogio` é injetável para a estimativa poder ser testada sem esperar | #11 | sim |
| `sau/graph/state.py` | o estado da conversa, isolado por Aluno: o registro em arquivo, o TTL que apaga a conversa ociosa e a fila FIFO por `chat_id` | #9 | sim |
| `sau/graph/graph.py` | monta o grafo LangGraph do turno. Nasceu com um caminho só (`START → responder → END`) e a recuperação da 1.2 entra aqui como o **único** nó novo, sem aresta condicional. Desde a #9 `executar_turno` recebe o histórico da conversa do Aluno. O texto do Encaminhamento determinístico mora **aqui**, e não na persona, para que o `sha256_do_prompt` continue reportando a persona e não a topologia | #8, #9, P4 | sim |
| `sau/graph/nodes.py` | os nós do grafo. A #8 criou o `responder` e o `montar_prompt`, a costura onde a #10 injeta a persona; a recuperação é o único nó que a 1.2 soma, e o índice dela vive no cache do módulo por (diretório, modelo de embedding) — e não no fecho do nó, que morreria com o grafo remontado a cada turno. Desde a #9 o `montar_prompt` recebe as últimas mensagens do Aluno para que ele não precise repetir a pergunta a cada turno, e desde a #10 ele é o `montar_prompt` de `sau/persona.py`, reexportado aqui: quem monta o prompt mora no módulo da persona, e este só entrega o estado do turno a ele | #8, #9, #10, P4 | sim |
| `sau/rag/embed.py` | embeddings locais via Ollama e indexação do Corpus. O modelo de embedding é **medido** aqui, com `ollama ps`, contra o orçamento de VRAM do ADR-0003 — não é escolhido antes | #29 | sim |
| `sau/rag/retrieve.py` | busca os `k` trechos mais próximos, com a Fonte (`buscar`), a matriz de similaridade inspecionável (`similaridades`) e a resolução da Fonte por correspondência exata (`resolver_fonte`). `k` é 3 porque `num_ctx` é 4096 e não é tocado: três trechos curtos é o que cabe antes de a conversa perder contexto. A #29 entregou o mínimo do índice (montar das seções em memória, guardar e expor); a #30 soma a busca | #29, #30 | sim |

## Conteúdo do time

| Caminho | O que é | Ticket | Existe |
| --- | --- | --- | --- |
| `perguntas-teste/` | as 10 Perguntas-teste, com o comportamento esperado de cada uma | #6 | sim |
| `corpus/` | os **quatro** documentos autorados — os três do instrumento mais o de Seguro, por emenda do ADR-0007 — com os defeitos plantados cada um nomeando o caso que ataca — [ADR-0007](./adr/0007-corpus-derivado-do-instrumento.md) | #29 | sim |
| `outputs/` | evidência bruta do harness: as rodadas são rascunho ignorado, as linhas de base entram no repositório. Desde a #13 a mesma exceção preserva os três artefatos da linha de base juntos: a rodada, o julgamento e o JSON das taxas | #12, #13 | sim |
| `tests/` | suíte `pytest`, com `test_config.py` e `test_prereqs.py` da #4, `test_webhook.py` da #5 (o caminho do turno da #8, o isolamento por Aluno da #9, a sentinela que afasta a persona da conversa, que ele precisa desde que a persona entra em todo prompt na #10, e a fila e o semáforo da #11), `test_graph.py` da #8, `test_state.py` e `test_semaphore.py` da #9 e da #11, `test_ollama.py` e `test_fumaca.py` da #7, `test_persona.py` da #10, `test_harness.py` da #12 e `test_metrics.py` da #13 | #4, #5, #7, #8, #9, #10, #11, #12, #13 | sim |

O `corpus/` é quebrado em unidades de recuperação pela própria equipe: cada
`##` dentro de um documento responde a uma Pergunta Frequente, então **o trecho
recuperado é a seção** e o chunking vira uma escolha da equipe, não uma heurística.
As seções são **curtas de propósito**: `num_ctx` é 4096 e não é tocado
(`sau/inference/ollama.py:34`, `scripts/preparar-host.sh:40`,
`tests/test_fumaca.py:1029`), e com uma persona de 852 tokens cada trecho
recuperado custa contexto que a conversa não tem.

## `harness/`

| Caminho | O que faz | Ticket | Existe |
| --- | --- | --- | --- |
| `harness/run.py` | roda as 10 Perguntas-teste, 3 repetições cada, e grava os outputs brutos com as condições da medição | #12 | sim |
| `harness/metrics.py` | taxa de não-saber e taxa de recusa de Atividade, com a folha de julgamento humano e a evidência de cada contagem. Os dois nomes são do instrumento, amarrados às linhas `conta na métrica do #13` de `perguntas-teste/perguntas-teste.md`. Desde a #28, também as três métricas dos Casos (Alucinação e confabulação por pessoa, Fonte verificável por script), o falso positivo e a republicação congelada da 1.1 | #13 | sim |
| `harness/casos.py` | os cinco Casos de alucinação, com o motivo do erro de cada um e o output real que cada um origina. É onde o caminho B mora: a 1.2 mede sobre estes cinco casos, e não sobre a bateria de 30 execuções | #29 | sim |
| `harness/run_casos.py` | roda os cinco Casos no S.A.U. pelo caminho real do turno, com as mesmas travas da bateria, e grava a rodada com as Fontes recuperadas por execução | #28 | sim |

O harness é a régua das duas sprints: a 1.2 roda **o mesmo** harness sobre
**os mesmos** casos, e é por isso que ele precisa ser reexecutável sem refazer
a implementação.

A evidência que ele grava vai para `outputs/`. As rodadas são ignoradas pelo
git porque são resultado descartável, com uma exceção — `outputs/baseline-*.json`
entra, e é o que permite comparar a 1.2 com a 1.1 em vez de afirmar que a
comparação foi feita. Desde a #13 a exceção cobre os três artefatos da linha de
base de uma vez, e pela mesma razão: a rodada sem o julgamento é output cru, e o
julgamento sem as taxas é opinião. O que a comparação mede só é conferível
depois, lendo do próprio arquivo o modelo, a alocação e o `sha256` do prompt: são
esses campos que separam "o RAG mudou" de "a persona ou a máquina mudou".

O `harness/metrics.py` é a metade do harness que **não** mede o modelo: ele
transforma o julgamento da folha em número com evidência, e por isso não fala com
o Ollama nem importa nada de `sau/`. O veredito é **responsabilidade de uma
pessoa** (decisão da #6) e pode ser redigido por um agente — nesse caso o campo
`julgador` nomeia **quem ratificou**, e é isso que amarra a folha a uma pessoa em
vez de a um processo ([emenda do
ADR-0006](./adr/0006-denominador-das-taxas.md)). `metrics.py` escreve a folha com
o output de cada execução na linha a julgar e o `conforme quando` de cada
Pergunta-teste no bloco `perguntas`, e quem decide é quem lê.

O `harness/run.py` também é o único lugar do repositório que **mede**: ele trava
`temperature 0`, uma `seed` fixa e `num_predict 256`, e registra o que usou.
`sau/inference/ollama.py` segue sem amostragem travada de propósito — travar a
seed ali daria a todo Aluno exatamente a mesma resposta, que é o oposto de
atender alguém.

## Onde as coisas entram

| Assunto | Onde |
| --- | --- |
| Decisão de arquitetura e o que foi descartado | `docs/adr/` |
| Vocabulário do domínio | `CONTEXT.md` |
| Plano da sprint e ordem de entrega | `docs/sprints/` |
| Formato da PR, título e corpo | `docs/agents/pull-request.md` |
| Ambiente e execução | `SETUP.md` |
| Estado das sprints no quadro | [Tutor IA - KANBAN](https://github.com/users/Feliipee013/projects/3) |
