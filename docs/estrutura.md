# Estrutura de pastas

Mapa de onde cada coisa mora no Tutor-IA e qual ticket a cria. Serve para um
agente Implementar localizar o ponto de impacto sem varrer o repositório inteiro.

> **Nenhuma das pastas de código existe ainda.** Este mapa é derivado dos
> tickets da sprint 1.1 e do plano da 1.2, e é uma **proposta de layout**, não uma
> decisão fechada. Atualize a coluna `Existe` e ajuste o caminho quando a pasta
> for realmente criada — sobretudo o nome do pacote, que precisa ser decidido
> junto com a issue #4.

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
| `opencode.json` | MCP do Context7 e permissões de `bash` por agente | sim |
| `docs/` | documentação versionada (abaixo) | sim |
| `.opencode/agents/` | subagentes `criar-pr` e `executor` | sim |
| `.opencode/skills/` | a skill `implementar` | sim |
| `.agents/skills/` | skills de terceiros, hoje só a `code-review` (em inglês) | sim |

## `docs/`

| Caminho | O que é | Existe |
| --- | --- | --- |
| `docs/estrutura.md` | este arquivo | sim |
| `docs/agents/` | contratos de tracker, labels, domínio e formato de PR | sim |
| `docs/adr/` | decisões de arquitetura, com o que foi descartado e por quê | sim |
| `docs/sprints/` | plano legível da 1.1 e da 1.2 | sim |
| `docs/limitacoes.md` | documento de limitações do modelo — **issue #14** | não |

## `sau/` — o pacote do bot

Nome do pacote é uma proposta. O grafo é a espinha do projeto: classificação da
intenção, e a 1.2 entra como rota nova **dentro** desse mesmo grafo, não como
serviço à parte.

| Caminho | O que faz | Ticket | Existe |
| --- | --- | --- | --- |
| `sau/config.py` | lê o ambiente: modelo, temperatura, `k` do semáforo, webhook e a URL base do Ollama no host | #4 | não |
| `sau/persona.py` | o prompt versionado do S.A.U., com todas as regras de comportamento | #10 | não |
| `sau/telegram/webhook.py` | handler do webhook, com acuse de recibo antes da inferência | #5 | não |
| `sau/inference/ollama.py` | cliente do Ollama, que roda **no host** e é alcançado por `host.docker.internal:11434` ([ADR-0002](./adr/0002-topologia-do-ollama.md)) | #3, #7 | não |
| `sau/inference/semaphore.py` | fila com teto e semáforo em frente à inferência | #11 | não |
| `sau/graph/state.py` | estado da conversa, isolado por Aluno | #9 | não |
| `sau/graph/graph.py` | monta o grafo LangGraph do turno | #8 | não |
| `sau/graph/nodes.py` | classificar intenção, recuperar, responder, encaminhar | #8, P5 | não |
| `sau/rag/embed.py` | embeddings locais via Ollama e indexação do corpus | P3 | não |
| `sau/rag/retrieve.py` | busca os `k` chunks mais próximos, com a Fonte | P4 | não |

## Conteúdo do time

| Caminho | O que é | Ticket | Existe |
| --- | --- | --- | --- |
| `perguntas-teste/` | as 10 Perguntas-teste, com o comportamento esperado de cada uma | #6 | não |
| `corpus/` | os quatro documentos autorados, um por categoria, com as contradições plantadas | P1 | não |
| `outputs/` | saída bruta do harness, ignorada pelo git | #12 | não |
| `tests/` | suíte `pytest` | — | não |

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
