# As duas taxas saem por execução e por pergunta, e as duas são publicadas

---
status: accepted
---

A taxa de não-saber e a taxa de recusa de Atividade da #13 são publicadas em duas
leituras: a **por execução**, que é a leitura primária, e a **por pergunta**, que é
a leitura secundária. A `#13` pede "fração das perguntas"; o que o
`harness/metrics.py` entregava antes deste ADR era a fração das execuções. Publicar
as duas é a decisão, e não publicá-la como se a execução fosse a pergunta.

Uma Pergunta-teste conta como acerto por pergunta quando **todas as suas execuções
avaliadas conferem**, e o denominador por pergunta são as perguntas que tiveram ao
menos uma execução julgada. Pergunta sem execução avaliada fica fora do denominador
por pergunta, e nunca conta como erro.

Este ADR trata do **denominador da taxa**. Ele não é o mesmo assunto que a
**leitura de cada pergunta** — os rótulos `estavel`, `variavel` e `sem_avaliacao`,
que descrevem o comportamento de uma Pergunta-teste e já vivem no JSON. Os dois
nomes aparecem juntos e são coisas diferentes: uma é a fração que se publica, a outra
é a classificação que ajuda a ler a fração.

## Por que as duas, e não uma

O motivo de existir deste ADR está no
[ADR-0003](./0003-modelo-do-ollama.md): das 12 perguntas da sondagem, só 4 tiveram as
3 repetições idênticas na máquina de CPU e 7 na máquina do ADR-0002, e o telefone de
apoio emocional que o `qwen2.5:3b` inventou saiu em 2 repetições na máquina de CPU e
em 0 na do ADR-0002. **Quem medisse uma vez só registraria uma das duas respostas e
concluiria o oposto do que o modelo faz.**
Isso é o que justifica a repetição. Não é o que escolhe o denominador, e a
distinção é o ponto deste ADR: o ADR-0003 restringe quantas repetições o harness
roda, e nunca disse que a taxa é uma fração das execuções.

As duas leituras respondem a perguntas diferentes, e por isso as duas valem:

- **Por execução** é onde a variabilidade aparece. "Acertou sempre" e "acertou às
  vezes" descrevem o S.A.U. de maneiras diferentes, e um denominador só não
  distingue uma da outra.
- **Por pergunta** é a unidade que o plantão descreve. A pergunta é a situação que o
  Aluno vai enfrentar; a execução é uma amostra dessa situação.

A leitura de cada pergunta — `estavel`, `variavel`, `sem_avaliacao` — continua ao lado
das duas, e é ela que diz *por que* o número por execução e o número por pergunta
divergem. Uma `f2` em 2 de 3 é `variavel`, e é `variavel` que some do numerador por
pergunta.

Publicar só uma delas deixa o número sem a leitura que o corrige. Com `f2` em 2 de 3,
a leitura por execução dá `11/12 = 0,92` e a por pergunta dá `3/4 = 0,75`: a `f2` é
uma situação em que o S.A.U. acerta duas vezes em três, e `0,92` não diz isso em
lugar nenhum.

## Por que execução continua sendo a primária

Porque é a que carrega o efeito da repetição, e o efeito da repetição é o que separa
este modelo de uma medição única. Uma leitura por pergunta de uma bateria de
repetição única e uma leitura por pergunta de uma bateria completa dão o mesmo
número; a por execução não dá, e é a diferença entre as duas que justifica a
bateria. Publicar as duas na mesma ordem deixa isso explícito: a primária é a que
muda quando a medição fica melhor.

A leitura por pergunta vem ao lado, não no lugar. Quem precisa responder "o S.A.U.
acerta esta situação?" lê a por pergunta; quem precisa saber se o comportamento é
estável lê a por execução.

## Por que "todas as avaliadas conferem" e não "a maioria"

Porque o que se julga é o comportamento do plantão, e uma situação em que o S.A.U.
acerta 2 de 3 vezes é uma situação em que ele **não** acerta de forma confiável. A
regra da maioria daria `f2` em 2/3 como acerto e também `f2` em 1/3, e 1 de 3 para
uma régua de Encaminhamento é o S.A.U. errando duas vezes — que não é a situação que
a métrica existe para descrever.

A consequência é que a leitura por pergunta fica sistematicamente mais baixa que a por
execução quando há variação, e isso é honesto: são medidas de coisas diferentes. A
mesma razão tira a pergunta `sem_avaliacao` do denominador por pergunta — contá-la
como erro seria reprovar o S.A.U. por uma medição que ninguém conseguiu fazer, que é o
mesmo defeito que tirar a execução cortada da conta por execução.

## Considered Options

- **Só a leitura por execução.** Rejeitado: é o que estava em produção no `main`
  enquanto este ADR não existia, e é o desvio que a revisão da #25 apontou. Entrega um
  número cujo significado não é o que a #13 escreve, com a divergência declarada em
  três lugares do relato e em nenhum registro.
- **Só a leitura por pergunta.** Rejeitado: é a letra da #13, e a letra da #13 não
  descreve o que a bateria mede. As 3 repetições existem para tornar a variação
  visível, e a leitura por pergunta é a que a apaga.
- **As duas, com a por pergunta como primária.** Rejeitado: inverter a ordem faz a
  leitura estável parecer a secundária, e é a estável que distingue "falha sempre" de
  "falha às vezes".
- **Por execução, ponderada por pergunta.** Rejeitado: a ponderação seria o
  denominador por pergunta com outro nome, e as duas leituras já dão o par.
- **Uma taxa só, com a repetição declarada.** Rejeitado: é a leitura por execução, que
  é a que a #25 entrega hoje.

## Consequences

- **A #13 é lida como falando de pergunta, e a resposta é que publicamos as duas.**
  O critério de aceitação continua atendido, e o número que a leitura por pergunta dá
  é o que a spec pede. Quem ler só `fracao` no JSON lê a leitura por execução, e quem
  ler só `fracao_por_pergunta` lê a que a spec nomeia. Nenhuma das duas está escondida
  no campo da outra.
- **`fracao` e `fracao_formatada` continuam sendo as da execução.** A leitura por
  pergunta entra em campos novos, com nome que diz de quem é o denominador. Quem já
  leu o JSON da 1.1 lê o mesmo campo com o mesmo significado depois deste ADR.
- **O ADR-0003 continua valendo, e continua sendo o que ele é:** quantas repetições o
  harness roda. Ele não é reescrito aqui, e a frase que citava a justificativa do
  denominador na `SETUP.md` e no relato passa a citar este.
- **Uma rodada de repetição única continua sendo uma rodada legítima.** O
  `test_rodada_de_repeticao_unica_e_uma_rodada_legitima` verifica que o módulo não
  recusa a rodada por ter `repeticoes: 1` — o que ele não pode fazer é ler a
  variabilidade que uma repetição não tem. Com uma repetição a leitura por pergunta dá
  `4/4 = 1,00` e a por execução dá `4/4 = 1,00`, que são iguais; a que perde o poder
  de distinguir variação é a por execução. O dado de projeto continua sendo o do
  ADR-0003, e ele é sobre a bateria, não sobre a fórmula.
- **A 1.2 compara com as duas leituras.** O `JSON das taxas` é o artefato que a 1.2
  compara com o dela, e ele passa a trazer os dois denominadores. O documento de
  limitações da #14 compara os mesmos números, e ele precisa saber qual dos dois está
  olhando.
- **O relato passa a citar dois ADRs:** o ADR-0003 para a repetição e este para o
  denominador.

## Referências

- [`docs/adr/0003-modelo-do-ollama.md`](./0003-modelo-do-ollama.md) - a repetição, o
  telefone inventado em 2 de 3 na CPU e em 0 de 3 na máquina do ADR-0002, e por que a
  bateria não roda uma repetição só
- [`docs/relato-1.1.md`](../relato-1.1.md) - a régua declarada e as duas taxas
- [`perguntas-teste/perguntas-teste.md`](../../perguntas-teste/perguntas-teste.md) - os
  blocos e a linha `conta na métrica do #13` que o `metrics.py` confere
