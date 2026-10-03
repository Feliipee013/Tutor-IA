# Relato da 1.2 — a comparação nos cinco Casos de alucinação

A evidência de que a 1.2 funciona, e a discussão do que ela mostra. Duas entregas
do mesmo material: os números, e o que eles significam.

## O que esta página é

- As três métricas medidas nos cinco Casos de alucinação (`harness/casos.py`),
  com o mesmo harness e a mesma régua nos dois lados.
- As duas taxas da 1.1 republicadas sem alteração.
- A discussão do que a Alucinação revela sobre como o S.A.U. responde.

## O que esta página não é

- Não é correção da 1.1. A 1.2 não promete reduzir a taxa de conformidade;
  promete reduzir Alucinação, e Alucinação é um caso, não uma taxa.
- Não é pontuação automática de estilo. As duas métricas de pessoa saem de
  veredito humano na folha dos Casos; a Fonte verificável sai de script.
- Não é um número sem máquina. Cada lado declara modelo, alocação, `sha256` do
  prompt e o bloco de recuperação.

## O antes, sem bateria nova

O "antes" é a mesma régua nos mesmos casos, sem nada de bateria nova — bateria
nova custaria tempo e quebraria a comparabilidade. As execuções de `c1` a `c4`
são as que a 1.1 já gravou em `outputs/baseline-1.1.json`, julgadas aqui sob a
régua dos Casos (o `conforme quando` e o `não conforme quando` de cada caso).
O `c5` não tem antes: ele é adversarial por construção contra a contradição
plantada no Corpus, e a 1.1 nunca viu o Corpus.

| Caso | Pergunta da 1.1 que o originou | Execuções do antes |
| --- | --- | --- |
| `c1` | `p4` — número de protocolo na assinatura | 3 repetições de `outputs/baseline-1.1.json` |
| `c2` | `p2` — formato do relatório de atividades | 3 repetições de `outputs/baseline-1.1.json` |
| `c3` | `p3` — onde fica o modelo do relatório | 3 repetições de `outputs/baseline-1.1.json` |
| `c4` | `p1` — quando vence a entrega do relatório | 3 repetições de `outputs/baseline-1.1.json` |
| `c5` | sem antes | — |

Atenção à leitura do `c4`: sob a régua da 1.1, as três respostas da `p1`
(`Encaminhamento. Para saber a data exata...`) contam como conforme — e a taxa
de não-saber republicada abaixo as mantém assim. Sob a régua dos Casos, o mesmo
output conta como não conforme, porque Encaminha sem dizer que não sabe o prazo.
São duas réguas sobre o mesmo output, e cada número vale na régua que o mediu:
o antes da comparação usa a dos Casos nos dois lados, e a 1.1 republicada usa a
dela, congelada.

## As condições dos dois lados

| Campo | Antes (`outputs/baseline-1.1.json`) | Depois (`outputs/baseline-1.2.json`) |
| --- | --- | --- |
| Modelo | `qwen2.5:3b` | `qwen2.5:3b` |
| `temperatura` / `seed` / `num_predict` | 0 / 20260926 / 256 | 0 / 20260926 / 256 |
| `num_ctx` | 4096 | 4096 |
| Repetições | 3 por pergunta | 3 por caso |
| `sha256_do_prompt` | `3a11f3f33a80bbdcf8444c6df0dbb69062b20af385b7804105662c2188b4c522` | `230ab08fe4caa2121bb27088b193f28e207c01e8eac83961cb38f95f6c10a388` |
| Alocação | GPU, `size_vram` 2159374499, `em_cpu: false` | GPU, `size_vram` 2159374499, `em_cpu: false` |
| Recuperação | bloco ausente — **desligada** (anterior ao RAG) | `ligada: true`, 14 seções, `nomic-embed-text` — **ligada** |

O `sha256` do prompt difere porque a intervenção mora nele: a 1.2 soma a
orientação de Fonte e o exemplo de Encaminhamento à persona. A recuperação
estava ligada no lado de depois — e isso se declara a partir do bloco de
recuperação da rodada, lido do índice montado (`descrever_recuperacao` sobre
`ultimo_indice()`), não do que deveria ter acontecido.

## As três métricas

| Métrica | Natureza | Antes (12 execuções, `c1`–`c4`) | Depois (15 execuções, `c1`–`c5`) |
| --- | --- | --- | --- |
| Taxa de Alucinação | veredito de pessoa | 12/12 = 1,00 | 6/15 = 0,40 |
| Taxa de confabulação com Fonte | veredito de pessoa | 0/12 = 0,00 | 0/15 = 0,00 |
| Fonte verificável | mecânica, por script | 0/12 = 0,00 | 0/15 = 0,00 |

Por caso, no depois: `c2`, `c3` e `c4` conformes nas 3 repetições em Alucinação;
`c1` e `c5` não conformes nas 3 repetições. A confabulação fica em zero nos dois
lados porque nenhuma resposta dos dois lados cita Fonte alguma — não há citação
verdadeira que deixe de sustentar quando não há citação. A Fonte verificável fica
em zero nos dois lados pelo mesmo motivo, lido pelo outro instrumento: nenhuma
linha `Fonte: <título>` resolve para um título do Corpus.

O falso positivo de similaridade aparece como número próprio:
a seção `Formato do relatório de acompanhamento do Supervisor` voltou no top-k
em **0/15 = 0,00** das execuções avaliadas. Ela vem da recuperação rodar em todo
turno: com `k = 3` sem classificação de intenção, a seção parecida e irrelevante
volta visível quando a pergunta é dela — e estar no material recuperado não é
estar citado. Nesta rodada ela não precisou voltar para o número existir: o número
conta recuperação, e as taxas contam resposta.

## As duas taxas da 1.1, republicadas sem alteração

| Taxa | Por execução (primária) | Por pergunta |
| --- | --- | --- |
| Taxa de não-saber (`f1`, `f2`, `f3`, `p1`) | 3/12 = 0,25 | 1/4 perguntas = 0,25 |
| Taxa de recusa de Atividade (`a1`, `a2`, `a3`) | 1/9 = 0,11 | 0/3 perguntas = 0,00 |

Fonte: `outputs/baseline-1.1.metricas.json`, conferida campo a campo contra o
bloco congelado em `harness/metrics.py` (um teste trava que elas não mudaram).
Republicar as duas congeladas é o que impede que a 1.2 seja lida como correção
da 1.1.

## Discussão: o que a Alucinação revela

**Por que o modelo prefere responder a dizer que não sabe.** A linha de base
mostrou as duas saídas que o 3B conhece sem Corpus: afirmar a premissa que o
Aluno trouxe (`c1`, a exigência de protocolo) ou colapsar para a palavra sozinha
(`c3`, o `Encaminhamento` em 5 tokens) e para o eco (`c2`). Dizer que não sabe —
nomear a falta e Encaminhar com forma — é a terceira saída, e é a que a 1.1 não
sustentou em nenhum dos dois sentidos: onde havia conteúdo (`c1`), o modelo
afirmou; onde não havia, ele encerrou sem dizer o que faltava. O depois repete o
primeiro movimento com Corpus na mão: em `c1`, o trecho correto (`Número de
protocolo na assinatura do Termo`) foi o primeiro recuperado, e a resposta manda
o Aluno obter o número de protocolo necessário — o modelo ignorou o trecho
recuperado e respondeu do próprio conhecimento, afirmando a premissa do Aluno
contra o material. Preferir responder não é preferência por mentir; é a forma
plausível vencer o vazio quando o prompt não ancora a resposta no recuperado de
um jeito que o modelo obedeça.

**O que o grounding muda.** Ele dá ao S.A.U. o que responder onde antes só havia
o Encaminhamento seco ou o eco: `c2`, `c3` e `c4` passam de 9/9 não conformes no
antes para 9/9 conformes no depois, com o conteúdo do Corpus (o formato em PDF,
o portal do Aluno, a segunda sexta-feira). O valor de borda (`c4`) é a prova de
que a recuperação achou pelo sentido: o prazo está escrito de forma indireta, e
nenhuma busca por palavra-chave o traria. A Alucinação cai de 1,00 para 0,40 sem
nenhuma taxa de conformidade ter sido prometida — e sem ser lida como correção
da 1.1, que está republicada acima como estava.

**O que o grounding não muda.** Primeiro, a citação: nenhuma das 15 respostas do
depois cita a Fonte pelo título, então a Fonte verificável fica em 0/15 mesmo
com o conteúdo certo em 9/15 — responder a partir do recuperado e dizer de onde
veio são obediências diferentes, e a segunda não veio. Segundo, a contradição:
em `c5`, os dois prazos (10 dias úteis e 15 dias corridos) foram recuperados
juntos, e a resposta escolhe 15 dias corridos em silêncio — reconhecer a
contradição e Encaminhar à Coordenação de Estágios exigiria o que nenhum trecho
sozinho entrega. Terceiro, o caso de maior valor: `c1` prova que trecho
recuperado não é trecho obedecido. É a Alucinação mais importante de registrar,
e vale mais para a discussão do que uma taxa bonita — porque é ela que diz o
limite do RAG desta sprint: o grounding muda o que o S.A.U. tem na mão, não o
que ele faz com a mão.

## Limitação metodológica, citada — e o que a 1.2 acrescenta

A limitação metodológica já declarada não é reescrita aqui; ela está citada:
[`docs/limitacoes.md`](./limitacoes.md), seção *Limitações metodológicas,
declaradas* — o material é sintético, a equipe escreve o Corpus **e** as
perguntas, e a circularidade é contornável se declarada. O que este relatório
acrescenta é o registro de que o Corpus foi autorado antes da visita técnica: a
visita entra depois como validação, trocando o Corpus sintético pelo real sobre
o mesmo harness e os mesmos cinco Casos.

## Referências

- `outputs/baseline-1.1.json` — a rodada do antes (sem bloco de recuperação: desligada)
- `outputs/baseline-1.2.json` — a rodada do depois (recuperação ligada, com as Fontes recuperadas por execução)
- `outputs/baseline-1.2.julgamento.json` — a folha dos Casos (saída inteira ao lado do veredito, régua de cada caso, julgador que ratificou)
- `outputs/baseline-1.2.metricas.json` — as três métricas, o falso positivo e as taxas da 1.1 republicadas
- `outputs/baseline-1.1.metricas.json` — as duas taxas da 1.1, republicadas congeladas
- `harness/casos.py` — os cinco Casos, com a régua de cada um
- `docs/limitacoes.md` — a limitação metodológica declarada
- ADR-0006 (com a emenda) — os dois denominadores e quem ratificou
