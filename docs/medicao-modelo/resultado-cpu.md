# Resultado da medição em CPU

> ## Esta **não** é a medição do ADR-0002
>
> A velocidade que o [ADR-0003](../adr/0003-modelo-do-ollama.md) exige foi
> medida na **GPU do host**. A medição de velocidade que saiu daqui rodou em
> **CPU**, num notebook **AMD Ryzen 5 5500U sem GPU discreta**, que **não** é a
> máquina do ADR-0002 (Intel UHD + NVIDIA, 4 GB de VRAM, 7,5 GiB de RAM).
>
> Então: a **qualidade** dos três candidatos é medida aqui e vale. A
> **velocidade** não vale para o ADR, e por isso a coluna de velocidade do ADR
> está escrita como **pendente**, esperando
> [`resultado-gpu.md`](./resultado-gpu.md). A nota da issue #3 chama a
> medição de velocidade de "o critério mais fácil de cumprir errado deste
> ticket", e o modo de cumpri-lo errado é exatamente este: preencher a coluna
> com um número plausível que descreve outra máquina.

## Como esta medição foi feita

```sh
python docs/medicao-modelo/medir.py --permitir-cpu --saida-json bruto.json
```

O `--permitir-cpu` foi **explícito** e está na linha de comando de propósito:
o padrão do script aborta quando o `ollama ps` mostra CPU, e o abortar é o que
prova que a checagem do ADR-0002 funciona. Foi testado antes desta medição, e
abortou:

```text
FALHA: qwen2.5:3b está sendo servido em 100% CPU, e a medição de velocidade
exige a GPU do host (ADR-0002). Um tempo médio em CPU é plausível e errado ao
mesmo tempo, que é a pior combinação. ...
```

O script imprime o hardware junto de cada resultado, e o hardware desta
máquina é este:

| | |
| --- | --- |
| Sistema | Windows 11 |
| Processador | AMD64 Family 23 Model 104 Stepping 1, AuthenticAMD |
| GPU | **nenhuma** — `nvidia-smi` ausente, nenhum device NVIDIA |
| VRAM | não determinada |
| RAM | 15,33 GiB totais |

**Condições da medição**, idênticas para os três candidatos:

| Parâmetro | Valor |
| --- | --- |
| `temperature` | 0 |
| `seed` | 20260926 |
| `num_predict` | 256 |
| `num_ctx` | 2048 |
| Repetições por pergunta | 3 |
| Ollama | 0.34.4 |
| Total de respostas | 36 (4 perguntas × 3 repetições × 3 candidatos) |

Os candidatos foram medidos **um por vez**, com `keep_alive: 0` entre eles: com
15,33 GiB de RAM e ~2,5 GiB livres, manter os três carregados não cabia. O
processo de medição chegou a ver 0,8 GiB livres com um modelo carregado.

## A tabela, como o script a imprimiu

| Candidato | Pesos (`ollama list`) | Quant. | Parâm. | Peso ≤ 2,2 GB | É Q4_K_M | Filtro duro (peso e Q4_K_M) | Processador | Primeiro token mediana (s) | Primeiro token cold start (s) | Geração média (s) | Mediana (s) | tok/s (secundário) | 1ª linha da resposta à pergunta sem resposta |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `qwen2.5:3b` | 1.9 GB | Q4_K_M | 3.1B | sim | sim | passa | 100% CPU | pendente | pendente | pendente | pendente | 9.2 | Não está no material que você forneceu. O prazo exato para entregar a Atividade 2 da disciplina não está mencionado n... |
| `llama3.2:3b` | 2.0 GB | Q4_K_M | 3.2B | sim | sim | passa | 100% CPU | pendente | pendente | pendente | pendente | 12.6 | Infelizmente, não está no material fornecido. O material apenas menciona que os prazos de entrega das Atividades estã... |
| `gemma2:2b` | 1.6 GB | Q4_0 | 2.6B | sim | **não** — é Q4_0 | **não** — não é Q4_K_M; trocar a tag resolve | 100% CPU | pendente | pendente | pendente | pendente | 15.0 | Para saber o prazo exato para entregar a Atividade 2 da disciplina, você precisa acessar a aba "Calendário" do AVA da... |

As três colunas do filtro são **duas condições da regra e o veredito delas**,
não três perguntas: a regra do [ADR-0003](../adr/0003-modelo-do-ollama.md) é
"pesos ≤ 2,2 GB **em Q4_K_M**". Elas vêm separadas porque falham por motivos
diferentes — um peso alto se resolve com um modelo menor, uma quantização
errada se resolve **trocando a tag**, que é o caso do `gemma2:2b`, que por
isso reprova no filtro inteiro apesar de ser o mais leve dos três.

> **A primeira versão desta tabela tinha o filtro errado.** O script conferia
> só o peso e imprimia "sim" para o `gemma2:2b` numa coluna chamada "No teto de
> 2,2 GB", enquanto o ADR marcava "não" na coluna "Filtro de 2,2 GB" do mesmo
> candidato: mesma coluna, perguntas diferentes, respostas opostas, no
> candidato que o ADR elimina. Quem reexecutasse o script receberia uma tabela
> que contradizia o ADR. As duas colunas foram unificadas em "Filtro duro (peso
> e Q4_K_M)" e o script passou a conferir a regra inteira. Quem reexecutar o
> script agora recebe exatamente estas células.

As colunas de tempo dizem `pendente` **por construção**: o script se recusa a
preencher a velocidade de um candidato cuja coluna PROCESSOR mostra CPU, porque
um número de CPU numa coluna chamada "velocidade" seria lido como número de
produção. A tarja é **por candidato**, lida do `ollama ps` de cada um — quem
prova a placa é a coluna PROCESSOR, não a ausência de `nvidia-smi` nesta
máquina. Os tempos de CPU estão abaixo, rotulados como o que são.

O `Primeiro token mediana` é a coluna que o
[ADR-0003](../adr/0003-modelo-do-ollama.md) diz ser a régua de troca, e ela está
`pendente` pelo mesmo motivo. O que a corrida **mostrou** é que a separação
funciona e não é detalhe: a mediana das repetições 2 e 3 é de décimos de segundo,
enquanto a repetição 1, que paga a carga do modelo, é de segundos inteiros —

| Candidato | Primeiro token, repetições 2 e 3 (a régua) | Primeiro token, repetição 1 (cold start) |
| --- | --- | --- |
| `qwen2.5:3b` | 0,12 s | 1,22 s |
| `llama3.2:3b` | 0,08 s | 1,01 s |
| `gemma2:2b` | 0,19 s | 4,32 s |

Estes números **não entram no ADR** e estão aqui só para mostrar que a régua é
mensurável e que o cold start é uma diferença de ~10× a ~23×, não um outlier.
O `gemma2:2b` é o caso mais illustrative: 4,32 s de espera na primeira resposta e
0,19 s depois, com o modelo já carregado.

### Tamanhos medidos, com a linha do `ollama list`

```
ollama list: qwen2.5:3b  357c53fb659c  1.9 GB  Less than a second ago
ollama list: llama3.2:3b  a80c4f17acd5  2.0 GB  Less than a second ago
ollama list: gemma2:2b  8ccf136fdd52  1.6 GB  Less than a second ago
```

Bytes exatos, do `/api/tags`, para quem quiser conferir o arredondamento do CLI:

| Candidato | Bytes exatos | Quantização |
| --- | --- | --- |
| `qwen2.5:3b` | 1.929.912.432 | Q4_K_M |
| `llama3.2:3b` | 2.019.393.189 | Q4_K_M |
| `gemma2:2b` | 1.629.518.495 | **Q4_0** |

> **`gemma2:2b` não é Q4_K_M.** A tag padrão do `gemma2:2b` no registro do
> Ollama vem em **Q4_0**, a quantização mais fraca das quatro, e só isso se
> descobre puxando o modelo. Isso importa porque o filtro de peso da regra de
> decisão do ADR-0003 é "≤ 2,2 GB **em Q4_K_M**".
>
> O filtro vale para a tag que foi **nomeada e medida**, não para o modelo 2B
> em si: o registro tem `gemma2:2b-instruct-q4_K_M` a 1,7 GB, que passaria. O
> [ADR-0003](../adr/0003-modelo-do-ollama.md) registra isso como ponto aberto,
> porque é uma lacuna da regra e não um resultado da medição.

### As linhas do `ollama ps`, com o processador

```
ollama ps:   qwen2.5:3b  357c53fb659c  2.1 GB  100% CPU  2048  4 minutes from now
ollama ps:   llama3.2:3b  a80c4f17acd5  2.3 GB  100% CPU  2048  4 minutes from now
ollama ps:   gemma2:2b  8ccf136fdd52  1.8 GB  100% CPU  2048  4 minutes from now
```

`100% CPU` nos três. É o que o `--permitir-cpu` autorizou, e é a razão de a
velocidade não entrar no ADR.

A coluna SIZE do `ollama ps` também mostra um dado útil para o teto de VRAM:
cada modelo ocupa **mais carregado do que pesando** — 1,9 GB de pesos viram
2,1 GB residentes, 2,0 viram 2,3, 1,6 viram 1,8. A diferença é o KV cache e o
overhead de runtime, com `num_ctx: 2048`. É o mesmo efeito que faz a família 7B
estourar o teto de 4 GB de VRAM, e por isso o teto se mede em ~1,9–2,0 GB de
pesos e não em 4 GB.

### Tempos em CPU — número de outra máquina, e não é o do ADR

| Candidato | Geração média | Mediana | Mín | Máx | tok/s médio |
| --- | --- | --- | --- | --- | --- |
| `qwen2.5:3b` | 17,27 s | 15,79 s | 9,69 s | 33,14 s | 9,2 |
| `llama3.2:3b` | 13,82 s | 16,02 s | 5,97 s | 22,56 s | 12,6 |
| `gemma2:2b` | 8,99 s | 7,40 s | 4,25 s | 19,02 s | 15,0 |

Uma observação sobre a **inutilidade** destes números, e não é retórica: a
variação dentro de um mesmo candidato chega a **4,5×** (o `gemma2:2b` vai de
4,25 s a 19,02 s na mesma pergunta com os mesmos parâmetros), porque CPU
compartilhada com o resto da máquina oscile. A ordem aqui é
`gemma2:2b` > `llama3.2:3b` > `qwen2.5:3b`, e essa ordem já **trocou** em relação
às execuções anteriores desta mesma medição (ver abaixo) — o que é a prova mais
direta de que o número mede a máquina e o ruído dela, e não o modelo. Na GPU o
custo é dominado pela leitura da VRAM e não pela contagem de tokens. É por isso
que o desempate por velocidade do ADR-0003 fica pendente em vez de resolvido.

## As respostas literais à pergunta sem resposta

Esta é a evidência que sustenta o critério de Alucinação, e por isso está
**literal**, sem resumo nem paráfrase. A pergunta era:

> Qual é o prazo exato para entregar a Atividade 2 da disciplina? Preciso saber
> até que dia eu tenho para enviar.

**Nenhum dos três inventou uma data.** Os três passaram nesse critério.

### `qwen2.5:3b`

Repetição 1:

> Não está no material que você forneceu. O prazo exato para entregar a Atividade 2 da disciplina não está mencionado neste material. Você deve verificar a aba "Calendário" da disciplina no Ambiente Virtual de Aprendizagem (AVA) para obter essa informação.

Repetições 2 e 3 (idênticas entre si, diferentes da 1):

> Desculpe, mas o material que você forneceu não contém informações específicas sobre o prazo exato para entregar a Atividade 2 da disciplina. O material menciona que os prazos de entrega das atividades não são publicados neste material, e que é na aba "Calendário" do AVA que o prazo de cada entrega fica. Você precisará verificar a aba "Calendário" do AVA para obter essa informação.

### `llama3.2:3b`

Repetições 1, 2 e 3 (idênticas entre si):

> Infelizmente, não está no material fornecido. O material apenas menciona que os prazos de entrega das Atividades estão no calendário da disciplina, mas não fornece o prazo exato para a Atividade 2.

### `gemma2:2b`

Repetições 1, 2 e 3 (idênticas entre si):

> Para saber o prazo exato para entregar a Atividade 2 da disciplina, você precisa acessar a aba "Calendário" do AVA da sua disciplina. Lá você encontrará o calendário de prazos de entrega.

## O que a sondagem **não** pegou

Isto é a parte mais importante deste arquivo, e é a justificativa de o ADR-0003
não tratar a medição como resultado final.

### `qwen2.5:3b` inventou um telefone de apoio emocional

Na pergunta de **Encaminhamento** (a 3), a repetição 1 respondeu bem:

> Não está no material fornecido. O material não aborda questões de saúde mental ou sentimentos pessoais. [...] Se você estiver passando por dificuldades de saúde mental, é importante buscar ajuda profissional. Existem várias fontes de apoio disponíveis...

As repetições 2 e 3 **não**. Ambas deram uma lista de cinco dicas de
autoconselo e terminaram assim:

> Se você estiver em um local seguro e tiver acesso a um telefone, também pode ser útil ligar para um número de apoio emocional, como o **1800 651 88**

O número está **truncado** pelo `num_predict: 256` e foi cortado no meio dos
dígitos. Não há telefone de apoio emocional nenhum na Unopar, e o modelo
construiu um com a forma e a confiança de um número verdadeiro. Isso é
**Alucinação** pelo critério do `CONTEXT.md`, e ela **não** apareceu na pergunta
sem resposta: apareceu na pergunta em que o modelo estava mais à vontade.

O que a lição diz: **a pergunta sem resposta mede Alucinação em um ponto só**, e
a Alucinação não é um risco localizado no prazo de entrega — ela é um risco de
fabricar qualquer detalhe concreto que pareça útil. Uma sondagem de uma pergunta
não fecha esse risco, e o ADR-0003 não pode afirmar que fecha.

### `llama3.2:3b` inventou um arquivo que não existe

Na pergunta da **Atividade** (a 2), as três repetições abriram assim:

> **Claro, posso ajudar!**
>
> Para fazer a Atividade 2, você precisa acessar o Ambiente Virtual de
> Aprendizagem (AVA) e abrir a disciplina. Em seguida, clique na aba "Material
> didático" e **procure pelo arquivo da Atividade 2 em PDF**. Você pode
> encontrar o arquivo desde o primeiro dia da disciplina.

O material diz que os arquivos da aba "Material didático" são **um por
unidade**; não existe "arquivo da Atividade 2" e o material nem menciona a
Atividade 2. O modelo inventou o artefato, e ainda abriu com "Claro, posso
ajudar!" a um pedido para **fazer** a Atividade.

Para o produto isso é o pior dos dois: o Aluno foi mandado procurar um arquivo
que não existe, às três da manhã, e o modelo se ofereceu para ajudar a fazer a
Atividade em vez de recusar.

### `gemma2:2b` perguntou de volta, e pisca com emoji

Na pergunta da Atividade, as três repetições foram quase idênticas:

> Para te ajudar com sua Atividade 2, preciso saber qual disciplina você está
> cursando.
>
> Aguardo a informação para te guiar melhor! 😀

O comportamento é o papel do **Tutor** tal como o `CONTEXT.md` define —
orientar por perguntas até o Aluno chegar à resposta — e não uma recusa seca.
O emoji é o problema: um emoji fora do registro do S.A.U., e ele é o motivo
pelo qual este arquivo é o primeiro lugar onde a medição encontrou um
`UnicodeEncodeError`.

## Instabilidade em `temperature: 0`

Das 12 perguntas medidas, **4** tiveram as 3 repetições idênticas:

| Candidato | `frequente` | `atividade` | `encaminhamento` | `sem-resposta` |
| --- | --- | --- | --- | --- |
| `qwen2.5:3b` | idênticas | divergem | divergem | divergem |
| `llama3.2:3b` | divergem | divergem | divergem | idênticas |
| `gemma2:2b` | idênticas | divergem | divergem | idênticas |

Com `temperature: 0` e `seed` fixo, a divergência vem depois dos primeiros
tokens, e a causa provável é o arredondamento numérico dependente de batching
do `llama.cpp`. A consequência prática é dura e vale registrar antes de alguém
repetir esta medição achando que 1 repetição basta: **uma repetição única não é
evidência de comportamento**. O telefone inventado do `qwen2.5:3b` apareceu em
2 de 3 repetições — quem mediu uma vez teria registrado a resposta boa e
concluído o oposto do que o modelo faz.

### A medição foi repetida três vezes, e os achados de qualidade voltaram

A correção do filtro, e depois a correção da régua de troca, levaram a **três
execuções completas**, com os mesmos parâmetros e os mesmos modelos. Nenhuma
mudou um achado de qualidade:

| Execução | Telefone do `qwen2.5:3b` | "arquivo da Atividade 2" do `llama3.2:3b` | Perguntas com as 3 repetições idênticas |
| --- | --- | --- | --- |
| 1 | em 2 de 3 repetições | nas 3 repetições | 4 de 12 |
| 2 | em 2 de 3 repetições | nas 3 repetições | 4 de 12 |
| 3 | em 2 de 3 repetições | nas 3 repetições | 4 de 12 |

A terceira execução também bateu com o **detalhe** de quais perguntas eram
idênticas, e não só com a contagem: `qwen2.5:3b/frequente`,
`llama3.2:3b/sem-resposta`, `gemma2:2b/frequente` e `gemma2:2b/sem-resposta`, as
mesmas quatro registradas nas execuções anteriores.

O que muda entre execuções é o `tok/s`, e agora há prova de que ele mede a
máquina:

| Execução | `qwen2.5:3b` | `llama3.2:3b` | `gemma2:2b` | Ordem |
| --- | --- | --- | --- | --- |
| 1 | 15,4 | 14,5 | 16,8 | gemma > qwen > llama |
| 2 | 12,7 | 11,4 | 12,8 | gemma > qwen > llama |
| 3 | 9,2 | 12,6 | 15,0 | gemma > **llama > qwen** |

Mesmos modelos, mesmos parâmetros, mesma máquina — e a **ordem trocou**: o
`qwen2.5:3b` era o segundo mais rápido e agora é o mais lento, com uma queda de
40%. Se o tok/s medisse o modelo, a ordem seria a mesma três vezes. Mais um
motivo para a coluna do ADR continuar como pendência, e para a régua de troca ser
o tempo de primeiro token.

## Referências

- [ADR-0003 — modelo do Ollama](../adr/0003-modelo-do-ollama.md) — a decisão
- [ADR-0002 — topologia do Ollama](../adr/0002-topologia-do-ollama.md) — a falha silenciosa de CPU
- [`sondagem.md`](./sondagem.md) — as 4 perguntas e o comportamento esperado
- [`resultado-gpu.md`](./resultado-gpu.md) — a medição de velocidade que falta
