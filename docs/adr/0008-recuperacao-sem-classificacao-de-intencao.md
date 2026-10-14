# A recuperação entra como nó único, sem classificação de intenção

---
status: superseded by ADR-0010
---

> **Substituído pelo
> [ADR-0010](./0010-aposentadoria-da-recuperacao-obrigatoria-em-todo-turno.md).**
> A recuperação obrigatória em todo turno, com nó único e sem aresta condicional,
> foi aposentada: ela passou a ser a ferramenta opcional `buscar_no_manual`, que o
> modelo chama quando precisa de um fato do Manual. O que este ADR cortou (a
> classificação de intenção) continua cortado; o que ele fixou (o nó em todo turno
> e a ausência de condicional) é que mudou.

A recuperação entra no grafo existente (`sau/graph/`) como **um nó só, que roda em
todo turno**, entre a mensagem do Aluno e o `responder`. **Não há classificação de
intenção e não há roteamento** — a topologia de três rotas (Atividade, Pergunta
Frequente, fora de escopo) que a §7 do plano anterior desenhava foi cortada.

O motivo é que a recuperação entrega, por outra via, o que a classificação entregaria.
Num turno de Pergunta Frequente, o trecho recuperado dá ao modelo algo a dizer. Num
turno de Atividade ou fora de escopo, a busca devolve o que estiver mais próximo — em
geral nada que sustente uma resposta — e a instrução de dizer que não sabe sem
grounding produz o Encaminhamento. O comportamento observável é o mesmo; o número de
nós, e o risco de o classificador errar a rota e devolver canned para o turno errado,
desaparecem.

Uma classificação de intenção foi desenhada antes, como sprint própria (a 1.1.2),
e foi abandonada: ela disputava com o Corpus e a recuperação o mesmo tempo de uma
pessoa só, e a recuperação é o que a situação-problema 1.2 pede.

## Consequences

- **O grafo ganha um nó e nenhuma aresta condicional.** `tests/test_graph.py` trava
  hoje `sorted(visao.nodes) == ["__end__", "__start__", "responder"]` e o par de
  arestas exato; o P4 da 1.2 reescreve essas asserções no mesmo ticket em que soma o
  nó.
- **`EstadoTurno` ganha campos, e o teste da linha 205 quebra junto.** Ele compara o
  estado de entrada e saída com um dicionário literal, então qualquer chave nova
  (`contexto`, `fontes`) exige a reescrita no mesmo ticket.
- **`ClienteMedido.ultima` sobrevive.** `harness/run.py` marca esse ponto para rever
  "quando a 1.2 somar nós que também geram". A recuperação não gera, então o ponto
  continua válido — e é por isso que a classificação ter sido cortada importa para o
  harness, e não só para o grafo.
- **O `sha256_do_prompt` volta a ser o campo que diz o que mudou.** O texto do
  Encaminhamento determinístico mora no grafo, não na persona, para que o hash
  continue reportando a persona e não a topologia. Ver o
  [ADR-0009](./0009-exemplo-de-encaminhamento-na-persona.md) para o outro lado dessa
  mesma separação.
- **Os docstrings de `sau/graph/graph.py` e `sau/graph/nodes.py` foram corrigidos**,
  porque ambos prometiam classificação e arestas que não vão existir. Se outro lugar
  do repositório ainda mencionar roteamento, é herança do plano anterior, não
  arquitetura.

## Referências

- [`1.2-rag.md`](../sprints/1.2-rag.md) §7 — a topologia de nó único que este ADR
  fixa
- [`docs/estrutura.md`](../estrutura.md) — onde `sau/rag/` entra e quem é o dono
- [`outputs/baseline-1.1.metricas.json`](../../outputs/baseline-1.1.metricas.json) — a
  linha de base que o "antes" mede