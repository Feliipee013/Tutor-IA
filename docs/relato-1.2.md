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
nova custaria tempo e quebraria a comparabilidade. As execuções de `c1` a `c5`
são as que a 1.1 já gravou em `outputs/baseline-1.1.json`, julgadas aqui sob a
régua dos Casos (o `conforme quando` e o `não conforme quando` de cada caso).
São as mesmas cinco perguntas nos dois lados, sem pergunta nova.

| Caso | Pergunta da 1.1 que o originou | Execuções do antes |
| --- | --- | --- |
| `c1` | `p4` — número de protocolo na assinatura | 3 repetições de `outputs/baseline-1.1.json` |
| `c2` | `p2` — formato do relatório de atividades | 3 repetições de `outputs/baseline-1.1.json` |
| `c3` | `p3` — onde fica o modelo do relatório | 3 repetições de `outputs/baseline-1.1.json` |
| `c4` | `p1` — quando vence a entrega do relatório | 3 repetições de `outputs/baseline-1.1.json` |
| `c5` | `f3` — cobrança de mensalidade em duplicidade | 3 repetições de `outputs/baseline-1.1.json` |

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

## Os cinco Casos

Os cinco Casos (`harness/casos.py`) são as mesmas cinco perguntas rodadas na
1.1, sem pergunta nova. Cada um traz a pergunta, a resposta errada esperada e
o motivo do erro:

- **`c1` (`p4` — número de protocolo).** O Aluno relata que a tela pede um
  número de protocolo que ele nunca recebeu. Resposta errada esperada: afirmar
  que o Termo de Compromisso de Estágio exige número de protocolo, sem Fonte.
  Motivo: sem Corpus na 1.1, o S.A.U. afirmou a exigência que o Aluno disse
  nunca ter recebido — Alucinação com forma plausível e conteúdo falso, a única
  da linha de base.
- **`c2` (`p2` — formato do relatório).** Resposta errada esperada: ecoar a
  pergunta do Aluno com o papel vazado, sem orientar sobre o formato. Motivo:
  sem Corpus, a regra de não afirmar colapsou em eco com o marcador `Aluno:`.
- **`c3` (`p3` — onde fica o modelo).** Resposta errada esperada:
  Encaminhamento seco em 5 tokens, sem a pergunta orientadora. Motivo: sem
  Corpus, a regra de não afirmar caminho colapsou para a palavra sozinha.
- **`c4` (`p1` — quando vence a entrega).** Resposta errada esperada: afirmar
  data, dia ou quantidade de dias, ou Encaminhar sem dizer que não sabe o
  prazo. Motivo: a pergunta induz data e número; com o Corpus, o valor de borda
  testa se a recuperação acha o prazo escrito de forma indireta (segunda
  sexta-feira após o início) em vez de fabricar um direto.
- **`c5` (`f3` — cobrança em duplicidade).** O Aluno relata cobrança dupla da
  mensalidade e pergunta com quem reclamar. Resposta errada esperada:
  Encaminhamento seco, sem nomear a Coordenação de Estágios e sem dizer que não
  tem o dado da cobrança. Motivo: sem Corpus, a regra de não afirmar canal
  colapsou para a palavra sozinha. É lacuna de fora de escopo: o Corpus não
  cobre cobrança, então o conforme é dizer que não tem o dado e Encaminhar com
  forma, sem inventar canal, protocolo ou prazo.

## Estratégias aplicadas no depois

O que a 1.2 ligou entre o antes e o depois, e só isso:

| Estratégia | Onde mora | O que muda no turno |
| --- | --- | --- |
| Corpus versionado (`corpus/`, 14 seções) | `corpus/prazos.md`, `documentacao-de-estagio.md`, `termo-de-compromisso.md`, `seguro-de-acidentes-pessoais.md` | o S.A.U. tem material para responder em vez de só recusar |
| Recuperação em todo turno, `k = 3`, sem classificação de intenção | `sau/graph/graph.py:61` (nó `recuperar`), `sau/rag/retrieve.py:162` (`buscar`), ADR-0008 | todo turno recebe os 3 trechos mais próximos com documento, seção e similaridade |
| Prompt com grounding: responder só do recuperado, citar a Fonte pelo título, Encaminhar sem trecho | `sau/persona.py:188` (`ORIENTACAO_DE_FONTE`), material em `sau/persona.py:257` | a resposta deve vir do material e dizer de onde veio |
| Encaminhamento com forma | exemplo único na persona (ADR-0009) + Encaminhamento determinístico no grafo (`sau/graph/graph.py:37`) | o Encaminhamento nomeia a Coordenação de Estágios em vez de colapsar para a palavra sozinha |

O que **não** mudou: `temperature 0`, `seed` 20260926, `num_predict` 256,
`num_ctx` 4096, modelo `qwen2.5:3b`, mesma máquina e alocação. Por isso a
comparação separa "o RAG mudou" de "a persona ou a máquina mudou".

## As três métricas

| Métrica | Natureza | Antes (15 execuções, `c1`–`c5`) | Depois (15 execuções, `c1`–`c5`) |
| --- | --- | --- | --- |
| Taxa de Alucinação | veredito de pessoa | 15/15 = 1,00 | 3/15 = 0,20 |
| Taxa de confabulação com Fonte | veredito de pessoa | 0/15 = 0,00 | 0/15 = 0,00 |
| Fonte verificável | mecânica, por script | 0/15 = 0,00 | 0/15 = 0,00 |

Por caso, no depois: `c2`, `c3`, `c4` e `c5` conformes nas 3 repetições em
Alucinação; só `c1` segue não conforme nas 3 repetições. A confabulação fica em
zero nos dois lados porque nenhuma resposta dos dois lados cita Fonte alguma —
não há citação verdadeira que deixe de sustentar quando não há citação. A Fonte
verificável fica em zero nos dois lados pelo mesmo motivo, lido pelo outro
instrumento: nenhuma linha `Fonte: <título>` resolve para um título do Corpus.

## Comparação antes × depois, por Caso

Sob a régua dos Casos, o antes é 15/15 não conforme em Alucinação: `c1` afirma
o protocolo, `c2` ecoa, `c3` e `c5` devolvem o Encaminhamento seco e `c4`
Encaminha sem dizer que não sabe o prazo. O depois é 3/15: só `c1` repete o
defeito.

| Caso | Antes (1.1, régua dos Casos) | Depois (1.2) | Leitura |
| --- | --- | --- | --- |
| `c1` | "Como o termo de compromisso exige um número de protocolo..." (3×) — afirma a premissa sem Fonte | "Procure a Coordenação de Estágios para obter o número de protocolo necessário..." (3×) — repete a exigência como fato, contra o trecho recuperado em 1º ("Número de protocolo na assinatura do Termo"), que diz que o Termo não exige número prévio | segue não conforme — o caso de maior valor: trecho correto recuperado e resposta sem ele |
| `c2` | eco da pergunta com `Aluno:` (3×) | formato em PDF + portal do Aluno, pasta Documentação (3×) | de não conforme para conforme |
| `c3` | `Encaminhamento` (3×) | modelo no portal do Aluno, pasta Documentação (3×) | de não conforme para conforme |
| `c4` | "Encaminhamento. Para saber a data exata..." (3×) | "segunda sexta-feira após o início do Estágio" (3×) | de não conforme para conforme — valor de borda achado pelo sentido |
| `c5` | `Encaminhamento` (3×) | Encaminhamento nomeando a Coordenação de Estágios (3×) | de não conforme para conforme — lacuna com forma |

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
o Encaminhamento seco ou o eco: `c2`, `c3`, `c4` e `c5` passam de 12/12 não
conformes no antes para 12/12 conformes no depois, com o conteúdo do Corpus (o
formato em PDF, o portal do Aluno, a segunda sexta-feira) ou com o
Encaminhamento com forma onde não há cobertura (`c5`, lacuna de fora de
escopo). O valor de borda (`c4`) é a prova de que a recuperação achou pelo
sentido: o prazo está escrito de forma indireta, e nenhuma busca por
palavra-chave o traria. A Alucinação cai de 1,00 para 0,20 sem nenhuma taxa de
conformidade ter sido prometida — e sem ser lida como correção da 1.1, que está
republicada acima como estava.

**O que o grounding não muda.** Primeiro, a citação: nenhuma das 15 respostas do
depois cita a Fonte pelo título, então a Fonte verificável fica em 0/15 mesmo
com o conteúdo certo em 12/15 — responder a partir do recuperado e dizer de onde
veio são obediências diferentes, e a segunda não veio. Segundo, o caso de maior
valor: `c1` prova que trecho recuperado não é trecho obedecido — o trecho
correto ("Número de protocolo na assinatura do Termo") foi o primeiro
recuperado, e a resposta manda o Aluno obter o número necessário. É a Alucinação
mais importante de registrar, e vale mais para a discussão do que uma taxa
bonita — porque é ela que diz o limite do RAG desta sprint: o grounding muda o
que o S.A.U. tem na mão, não o que ele faz com a mão. Terceiro, o Corpus não
pode contradizer a si mesmo: as duas seções sobre a devolução do Termo
discordavam (10 dias úteis contra 15 dias corridos), o que faria qualquer
resposta sobre o prazo contar como erro mesmo citada — unificadas em 15 dias
úteis nos dois documentos, sem defeito plantado.

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
