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

## Emenda: cobertura além do instrumento

O Corpus mínimo cumpriu o papel de bancada, e agora limita a utilidade do
S.A.U.: o Aluno pergunta por blocos reais do processo — carga horária,
autorização da Empresa pela Instituição, rescisão e aditivo, relatório parcial
vs. final, quem assina, Seguro de Acidentes Pessoais — e a resposta "não
tenho esse dado" para tudo que está fora das quatro seções do instrumento
deixa de ser medida e passa a ser falta de cobertura.

Por isso o Corpus passa de **três** para **quatro** documentos, com o
`seguro-de-acidentes-pessoais.md` cobrindo o Seguro, e com seções novas de
cobertura nos três documentos originais. A regra original continua valendo
para os defeitos: seção nova de cobertura não leva marcador `<!-- caso -->`
— defeito plantado sem caso que o alcance continua sendo ruído, e os cinco
marcadores existentes (`c1`, `c2`, `c4`, `c5`, `c5`) ficam como estão. O que
muda é só a cobertura: o relatório da 1.2 passa a dizer que o Corpus cobre
os blocos do processo, e a visita técnica vira ampliação, não fundação.

## Emenda: Corpus `.md` aposentado na #40 (base passa a ser o PDF)

Decisão de equipe na #40: os quatro `.md` sintéticos saem do `corpus/` e o
Manual de Estágio Obrigatório do Polo em PDF vira a base (ADR-0011). O
`corpus/` passa a guardar só o PDF externo (fora do git), o `README.md` e o
`.gitkeep`.

O caminho antigo (`sau/rag/retrieve.py` lendo `*.md` via
`DIRETORIO_CORPUS_PADRAO`) segue existindo até a #36 religar o turno no Chroma,
mas o `README.md` nunca é material: `carregar_corpus` o ignora, então produção
degrada para recuperação desligada (Encaminhamento determinístico) em vez de
citar o README. Fixtures de `.md` em `tests/` provam só a mecânica, não o
material.

## Emenda: o caminho `.md` sai do turno na #36

A #36 religa o turno na ferramenta `buscar_no_manual` sobre o índice do PDF
([ADR-0010](./0010-aposentadoria-da-recuperacao-obrigatoria-em-todo-turno.md)):
o caminho antigo deixa de ser chamado em todo turno. `sau/rag/retrieve.py` e os
seus testes continuam no repositório, mas o nó que lia o Corpus a cada turno
(`criar_no_recuperar`, e o `DIRETORIO_CORPUS_PADRAO` de `sau/graph/nodes.py`) foi
removido. `DIRETORIO_CORPUS_PADRAO` continua existindo em `harness/metrics.py`,
que o usa nas métricas da bateria.

## Referências

- [`CONTEXT.md`](../../CONTEXT.md) — o escopo que este Corpus deliberadamente não
  cobre inteiro
- [`1.2-rag.md`](../sprints/1.2-rag.md) §4 — o porquê de cada defeito plantado
  carregar o caso que o ataca
- [`perguntas-teste/perguntas-teste.md`](../../perguntas-teste/perguntas-teste.md)
  — as dez perguntas que definem as quatro seções