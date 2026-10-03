# Um exemplo de Encaminhamento completo na persona

---
status: proposed
---

A persona ganha **um** exemplo de Encaminhamento completo: um turno de fora de escopo,
perguntado e respondido de ponta a ponta. A regra `encaminhamento` continua dizendo
**quando** encerrar e **o que não inventar**, e o exemplo é a única vez em que a
persona mostra a forma do encerramento em vez de descrevê-la.

Isto volta atrás de duas decisões deliberadas. `10d9c56` ("as regras descrevem o
comportamento, e não ditam a resposta") removeu a frase ditada, e `3400b32` ("remove
frase fixa verbatim de sem-info que virava atrator") removeu a segunda. O motivo era
justo: uma frase verbatim vira atrator e o modelo a repete onde ela não serve. O
efeito colateral não foi medido na época, e é o que este ADR corrige.

## O que a linha de base mostra

Nos outputs de `outputs/baseline-1.1.json`, **cinco das dez Perguntas-teste** — `a3`,
`f1`, `f2`, `f3` e `p3` — respondem a palavra `Encaminhamento` e param, em **5
tokens**, idênticas nas três repetições. A única que acerta é `p1`, que acrescenta
"Para saber a data exata, você precisará consultar a Coordenação de Estágios", e a
melhor da bateria é `p4`, que nomeia o destino e não inventa o número de protocolo.

Ou seja: o modelo sabe **que** tem de encerrar e não consegue **como**. A causa
provável é visível na persona: a regra `encaminhamento` (`sau/persona.py`) descreve a
condição e as proibições, e não oferece nenhuma forma para imitar. Com 852 tokens, 8
regras e um `qwen2.5:3b` a 4096 de contexto, sobra pouco espaço para o modelo montar a
frase. `p1` e `p4` provam que a forma existe quando o modelo a encontra.

## Consequences

- **`tests/test_persona.py` precisa mudar.** `test_nenhuma_regra_dita_a_resposta_do_aluno`
  (linha 503) falha com um exemplo de turno, porque um exemplo é resposta ditada por
  definição. A regra do teste muda de "nenhuma resposta ditada" para "nenhuma resposta
  ditada **fora do exemplo declarado**", e o exemplo passa a ser o ponto que o teste
  verifica. Isso é uma alteração de critério de um teste que existe para proteger uma
  decisão, e por isso é uma alteração declarada aqui.
- **O exemplo entra no `sha256_do_prompt`.** A linha de base da 1.1 carrega
  `3a11f3f3…`; o hash muda, e é isso que permite dizer depois que a persona mudou e o
  Corpus também. Um exemplo a mais ou a menos precisa aparecer na folha de julgamento
  como o que é.
- **Um exemplo só, e não dois.** Dois textos de Encaminhamento — dor/saúde e
  reclamação institucional — foram descartados junto com a classificação de intenção
  (ver [ADR-0008](./0008-recuperacao-sem-classificacao-de-intencao.md)). `f1` é
  sofrimento e `f3` é reclamação, e o veredito de `f1` exige reconhecer o sofrimento
  antes de nomear a Coordenação; com um exemplo só, `f1` continua sendo o caso que
  falha, e isso é declarado em vez de escondido.
- **O exemplo não é template.** Ele não pode ser a resposta a ser completada nem uma
  frase para trocar o destinatário. É um turno, e a regra continua valendo quando
  nenhum turno se pareça com ele.

## Referências

- [`sau/persona.py`](../../sau/persona.py) — a regra `encaminhamento`, que descreve e
  não mostra
- [`outputs/baseline-1.1.json`](../../outputs/baseline-1.1.json) — os outputs de 5
  tokens que motivam o exemplo
- [`perguntas-teste/perguntas-teste.md`](../../perguntas-teste/perguntas-teste.md) — o
  `conforme quando` de `f1`, que exige reconhecer o sofrimento
- [`docs/relato-1.1.md`](../relato-1.1.md) — a régua declarada que o exemplo serve