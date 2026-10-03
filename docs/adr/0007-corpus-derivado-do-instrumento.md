# O Corpus é derivado do instrumento, não do escopo

---
status: proposed
---

O Corpus tem **três** documentos, um por aglomerado que as Perguntas-teste de fato
cobrem: Prazos do calendário de Estágio, Documentação de Estágio (formato e caminho) e
Termo de Compromisso e Contrato de Estágio (protocolo). Seguro de Acidentes Pessoais
**fica de fora**, mesmo estando no escopo do [`CONTEXT.md`](../../CONTEXT.md), porque
nenhuma das dez perguntas o alcança — e uma contradição plantada sem caso que a
alcance é ruído, e ruído que ninguém vai explicar depois.

O critério é o instrumento, não o glossário. Derivar do instrumento é o que garante
que cada defeito plantado tenha caso: `p1` pergunta prazo, `p2` e `p3` perguntam
formato e caminho, `p4` pergunta protocolo, e as quatro seções do Corpus existem
porque essas quatro perguntas existem.

## Considered Options

- **Quatro documentos, um por categoria do escopo.** Cobre o glossário inteiro, e
  transforma o capítulo de Seguro em duas páginas que nenhum caso mede.
- **Um corpus espelhando a sondagem.** A sondagem ([`sondagem.md`](../medicao-modelo/sondagem.md))
  é escrita em vocabulário de curso EaD e é anterior ao realinhamento de domínio; as
  dez Perguntas-teste já foram reescritas para o processo de Estágio. Derivar de um
  documento desatualizado produz um Corpus que não responde às perguntas do próprio
  projeto.

## Consequences

- **A base de comparação da 1.2 fica Viável.** O "depois" da §9 de
  [`1.2-rag.md`](../sprints/1.2-rag.md) compara os mesmos casos do "antes", e um caso
  só é medido se existe trecho que o sustente.
- **A limitação fica declarada, não escondida.** Não cobrir Seguro é uma escolha de
  bancada, e o relatório da 1.2 diz que o Corpus cobre três dos quatro blocos do
  processo.
- **Esta decisão é do P1, não da 1.2 inteira.** Se a visita técnica trouxer material
  real, o Corpus cresce e a decisão é revista — o que é barato, porque nada no código
  depende de quantos documentos existem.

## Referências

- [`CONTEXT.md`](../../CONTEXT.md) — o escopo que este Corpus deliberadamente não
  cobre inteiro
- [`1.2-rag.md`](../sprints/1.2-rag.md) §4 — o porquê de cada defeito plantado
  carregar o caso que o ataca
- [`perguntas-teste/perguntas-teste.md`](../../perguntas-teste/perguntas-teste.md)
  — as dez perguntas que definem as quatro seções