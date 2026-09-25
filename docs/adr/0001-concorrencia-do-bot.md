# Concorrência do bot: webhook, estado por conversa e semáforo de inferência

---
status: accepted
---

O S.A.U. atende vários Alunos ao mesmo tempo, mas o recurso escasso é único: a inferência local no Ollama, que na prática aceita uma ou duas gerações simultâneas porque a VRAM limita qualquer paralelismo maior. Em vez de um worker dedicado por Aluno, a decisão é: **um worker por conversa** (criado na primeira mensagem, destruído por timeout de inatividade), com estado conversacional isolado por Aluno, e um **semáforo limitado em frente à chamada ao Ollama**, com fila de espera com teto e backpressure. O consumo do Telegram vem por **webhook**, não por long polling.

## Considered Options

- **Um worker dedicado por Aluno** (Celery/RQ). Descartado: a maioria dos Alunos está ociosa a maior parte da noite, então o custo é linear em Alunos registrados para isolar um estado que é por *conversa*, não por pessoa. Além disso, worker dedicado é padrão para trabalho CPU-bound em lote; aqui só a chamada ao modelo é cara, todo o resto é I/O.
- **Long polling do Telegram com vários workers.** Descartado: workers concorrentes precisam coordenar o `offset` do `getUpdates` para não processar o mesmo update duas vezes. Com webhook cada request é independente. É a decisão mais cara de voltar atrás — trocar depois implica reprocessar histórico de updates.
- **Broker externo (Redis, RabbitMQ) para a fila.** Descartado por ora: o gargalo é um semáforo em um processo, e um broker só se justifica com múltiplas réplicas do bot. Reavaliar se o bot rodar em mais de uma instância.

## Consequences

- O número de Alunos atendidos simultaneamente é limitado por `k` (o semáforo), não por CPU ou memória da aplicação. `k` precisa ser medido na máquina alvo, não assumido.
- Ordem de mensagens é preservada **por conversa**, não globalmente: um Aluno nunca vê o histórico de outro, e as mensagens dele não embaralham.
- A fila com teto exige mensagem de posição e prazo para o Aluno. Um Aluno às 2h da manhã esperando sem saber o que está acontecendo destrói a promessa do produto — o backpressure precisa ser comunicado, não escondido.
- Confirmar o recebimento imediatamente, ainda antes da inferência, é requisito, não polimento.
