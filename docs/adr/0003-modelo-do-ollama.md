# Modelo do Ollama do S.A.U.: `qwen2.5:3b`

---
status: accepted
---

O S.A.U. é servido pelo **`qwen2.5:3b`** em quantização Q4_K_M: 1,9 GB de pesos,
3,1B de parâmetros. É o único dos três candidatos que **não mandou o Aluno atrás
de um arquivo que não existe** — e essa diferença é a que as duas máquinas em
que ele foi medido sustentam, o que faz dela o único motivo de escolha que
ambas apoiam. A escolha vem de medir, não de preferir: a regra de decisão foi
escrita **antes** de olhar qualquer resultado e está registrada abaixo, com a
mesma ordem que foi aplicada.

A velocidade foi medida na máquina do ADR-0002, com `100% GPU` nos três
candidatos, e está na coluna de velocidade de Considered Options. O número
**não reverteu** a escolha: os dois candidatos que passam no filtro duro
empatam em 0,02 s de primeiro token, e o critério que os separava é anterior ao
desempate.

> ## O que este ADR ainda não cumpre
>
> **Um item só, e ele é do tracker, não da medição.** A issue #3 ainda cita
> `OLLAMA_VISIBLE_DEVICES`, que não é a variável que o Ollama lê — a correta é
> `CUDA_VISIBLE_DEVICES`, com o UUID de `nvidia-smi -L`, e o repositório está
> corrigido no ADR-0002 e no SETUP.md. O **critério 4 da issue precisa de edição
> humana**.
>
> O critério de velocidade está fechado: medido na máquina do ADR-0002, com
> `100% GPU` nos três candidatos, em
> [`resultado-gpu.md`](../medicao-modelo/resultado-gpu.md).

## A regra de decisão, antes dos resultados

Os quatro critérios abaixo foram escritos antes da medição e **não** mudaram
depois. Registrados aqui para que a escolha não pareça retro-raciocínio. A
única coisa que esta seção perdeu desde a primeira redação foi a nota de que a
velocidade estava por medir, que saiu quando a medição foi feita.

1. **Filtro duro: pesos ≤ 2,2 GB em Q4_K_M.** Cabe nos 4 GB de VRAM da máquina
   do ADR-0002 e deixa espaço para o modelo de embedding que a 1.2 vai pedir ao
   **mesmo** Ollama ([`1.2-rag.md` §13](../sprints/1.2-rag.md)). Sem esse
   espaço, a 1.2 não roda.
2. **Alucinação, critério principal.** O candidato que responde à pergunta sem
   resposta com um fato plausível e falso é **eliminado**, independentemente do
   resto. É o defeito central do `CONTEXT.md`, não um critério entre outros.
3. **Secundário:** português nas perguntas com resposta, e se produz
   **Encaminhamento** no que está fora de escopo.
4. **Terciário:** velocidade, medida depois. Empate se resolve por velocidade.

A ordem não se inverte depois de ver os dados. Em particular: a velocidade é o
**último** critério, e por isso é a que confirma em vez de decidir — foi
medida depois, e o número de 0,02 s não precisou ser acionado como desempate.

## Considered Options

Todos os três candidatos cabem nos 4 GB de VRAM — a família 7B em Q4_K_M fica
em 4,4–4,7 GB só de pesos, e estoura, como o ADR-0002 registrou. Então a
escolha é entre três modelos da família 3B, medidos no mesmo conjunto de
sondagem ([`sondagem.md`](../medicao-modelo/sondagem.md)) com
`temperature: 0`, `seed` 20260926, `num_predict: 256`, `num_ctx: 2048` e 3
repetições por pergunta.

### A máquina da medição

A velocidade saiu da máquina do ADR-0002, e a VRAM **e** a RAM foram medidas
na hora, não supostas — é o que o critério de aceitação da issue #3 pede
registrar junto da medição.

| | |
| --- | --- |
| Sistema | Linux 7.1.1-76070101-generic |
| GPU | NVIDIA GeForce GTX 1650 |
| VRAM | **4,00 GiB** |
| RAM | **7,53 GiB** totais, 2,73 GiB livres no momento da medição |
| Ollama | 0.34.4 |

Os 4 GB de VRAM batem com o teto do ADR-0002, e os 7,53 GiB de RAM batem com
os 7,5 GiB que aquele ADR registra. A checagem que vale não é esta
correspondência, é a coluna PROCESSOR do `ollama ps`, e ela mostrou `100% GPU`
nos três candidatos — o que prova que a medição rodou na GPU do host e não
caiu para a CPU em silêncio.

### Os três candidatos

| Candidato | Pesos (`ollama list`) | Bytes | Quant. | Parâm. | Peso ≤ 2,2 GB | É Q4_K_M | Filtro duro (peso e Q4_K_M) | Velocidade (1º token mediana · cold start) | Resposta à pergunta sem resposta |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **`qwen2.5:3b`** | **1,9 GB** | 1.929.912.432 | Q4_K_M | 3.1B | sim | sim | **passa** | 0,02 s · 0,21 s — **100% GPU** | "Desculpe, mas o material que você forneceu não contém informações específicas sobre o prazo exato... verifique o calendário do AVA" — **sem data inventada** |
| `llama3.2:3b` | 2,0 GB | 2.019.393.189 | Q4_K_M | 3.2B | sim | sim | **passa** | 0,02 s · 0,22 s — **100% GPU** | "Infelizmente, não está no material fornecido. O material apenas menciona que os prazos de entrega das Atividades estão no calendário da disciplina..." — **sem data inventada** |
| `gemma2:2b` | 1,6 GB | 1.629.518.495 | **Q4_0** | 2.6B | sim | **não** — é Q4_0 | **não** — não é Q4_K_M; trocar a tag resolve | 0,05 s · **1,05 s** — **100% GPU** | "Para saber o prazo exato para entregar a Atividade 2, você precisa acessar a aba 'Calendário' do AVA da disciplina" — **sem data inventada** |

A coluna de velocidade e a coluna de resposta são as duas medidas na **máquina
do ADR-0002**, a mesma corrida. A máquina de CPU, que é outra, deu tempos e
textos diferentes para os mesmos três modelos, e
[`resultado-cpu.md`](../medicao-modelo/resultado-cpu.md) traz os dela com o
mesmo cuidado. As duas leituras estão no repositório de propósito: um número de
velocidade sem a máquina junto é número que se cita errado depois.

O filtro tem **duas condições** e elas estão em colunas separadas, com o
veredito na terceira, pelo mesmo motivo e com os mesmos nomes que a tabela do
script em [`resultado-cpu.md`](../medicao-modelo/resultado-cpu.md): as duas
condições falham por motivos diferentes. `Peso ≤ 2,2 GB` é a pergunta do peso;
`É Q4_K_M` é a pergunta da quantização; `Filtro duro` é a regra inteira, e é a
única das três que elimina. Isso não é preciosismo de coluna — o `gemma2:2b`
é o caso que prova a diferença, porque ele **passa** na primeira e **reprova**
na terceira, e a reprovação se resolve trocando a tag, não trocando o modelo.

### De onde veio o número, e por que o outro também vale

Os tempos de primeira token e de cold start da tabela acima saíram de
[`resultado-gpu.md`](../medicao-modelo/resultado-gpu.md), na máquina do
ADR-0002, com `100% GPU` nos três candidatos e as mesmas condições da corrida
de CPU: `seed` 20260926, `temperature` 0, `num_predict` 256, `num_ctx` 2048,
3 repetições. A corrida rodou **sem** `--permitir-cpu` e **sem** `--manter-vivo`
— sem a primeira, o script aborta se o `ollama ps` mostrar CPU, e sem a segunda
a regra de cold start do próprio script não é quebrada em silêncio. O número é
de produção, e por isso ele é a coluna de velocidade deste ADR.

O que ficou em
[`resultado-cpu.md`](../medicao-modelo/resultado-cpu.md) continua válido, e
vale para uma coisa só: **a qualidade dos três candidatos**. Qualidade se mede
em qualquer máquina, porque as 36 respostas não dependem da placa — é este ADR
que separa as duas coisas, e a nota da issue #3 avisa que a velocidade é "o
critério mais fácil de cumprir errado". Aquele arquivo guardou os tempos que
mediu, rotulados como número de outra máquina, e foi a decisão certa na época:
a máquina onde a qualidade saiu não tem GPU. O que ele **não** tem é autoridade
sobre a velocidade, e por isso nenhum dos tempos dele entra na tabela acima.

- **`gemma2:2b` — descartado no filtro duro.** A tag padrão do `gemma2:2b` no
  registro do Ollama vem em **Q4_0**, não em Q4_K_M, e isso só aparece depois
  do pull. O filtro de peso é "≤ 2,2 GB **em Q4_K_M**" e o `gemma2:2b`, como foi
  nomeado e medido, não é Q4_K_M. Ele é o mais leve dos três (1,6 GB) e o mais
  rápido em CPU, e é exatamente por isso que ele é um candidato de verdade: ele
  é a prova de que o critério de VRAM importa **duplamente** aqui, porque a 1.2
  vai querer a VRAM que ele deixaria sobrando. Como o filtro é declarado **em
  Q4_K_M**, ele sai antes de qualquer comparação de qualidade. Registrar a tag
  padrão de um candidato não é detalhe de catálogo: é o que separa "cabe na
  VRAM" de "cabe na VRAM com a quantização que a regra exige".

  > **Ponto aberto, e ele é do humano, não meu.** A exclusão vale para a tag
  > `gemma2:2b` **como nomeada e medida**. O mesmo modelo 2B **existe em
  > Q4_K_M** no registro, como `gemma2:2b-instruct-q4_K_M` (1,7 GB), que
  > **passaria** o filtro. A regra diz em Q4_K_M, e a regra não diz o que fazer
  > quando a tag nomeada falha e uma tag irmã do mesmo modelo passa. Escolhi
  > aplicar a regra à tag que a issue nomeia, e registrar a outra em vez de
  > trocar o candidato silenciosamente — mas isso é uma lacuna da regra, não um
  > fato medido, e está aqui para ser corrigida se alguém discordar.
  >
  > **O que a medição de produção já diz sobre essa tag.** A tag
  > Q4_K_M **não foi medida** — o que segue é o `gemma2:2b` em Q4_0, o mesmo
  > modelo-base com outra quantização, e é a melhor evidência disponível sem
  > puxar a tag irmã. Na máquina do ADR-0002 ele é o **melhor em `tok/s`**
  > (56,3 contra 51,3) e o **pior na régua**: 0,05 s de primeiro token contra
  > 0,02 s dos dois que passam, e 1,05 s na primeira repetição de cada pergunta
  > contra 0,21 s do `qwen2.5:3b` — **cinco vezes mais espera**. Como o ADR
  > desempata pelo primeiro token e declara o `tok/s` secundário, a métrica em
  > que o `gemma2` ganha é justamente a que não decide. Medir a tag Q4_K_M
  > continua valendo a pena, e agora por um motivo diferente do que estava
  > escrito aqui: para **fechar a lacuna da regra**, não para abrir a
  > possibilidade de o `gemma2` entrar por velocidade.
- **`llama3.2:3b` — descartado no secundário.** Passa o filtro de peso e passa
  no critério de Alucinação. Na pergunta da **Atividade** as três repetições
  abriram com "Claro, posso ajudar!" e mandaram o Aluno, na aba
  "Material didático", "procurar pelo arquivo da Atividade 2" — firmando que
  esse arquivo está em PDF. A promessa é a mesma nas três; só muda a forma da
  frase, porque duas repetições escrevem "procure pelo arquivo da Atividade 2
  em PDF" e a terceira a quebra no mesmo parágrafo ("procure pelo arquivo da
  Atividade 2. Ele deve estar em PDF"). **Esse arquivo não existe**: o
  material diz que os PDFs são um por unidade e nem menciona a Atividade 2. O
  modelo inventou o artefato e ainda se ofereceu para fazer a Atividade em vez
  de recusar. **As duas máquinas concordam aqui**: as 3 repetições na máquina
  de CPU e as 3 na máquina do ADR-0002 fabricaram o mesmo arquivo inexistente.
  Para o produto é o pior resultado dos três: o Aluno, às três da madrugada, é
  mandado procurar um arquivo que não existe. O critério 3 é "português nas
  perguntas com resposta, e Encaminhamento no que está fora de escopo" — e a
  resposta à Atividade não está no registro do S.A.U.

  > **O Encaminhamento dele mudou de máquina para máquina, e nenhuma das duas
  > leituras é razão para escolhê-lo.** Na máquina de CPU ele era o **melhor**
  > dos três na pergunta de Encaminhamento: declarava "eu sou um modelo de
  > linguagem e não um profissional de saúde", se oferecia para ouvir e sugeria
  > ajuda qualificada, sem inventar canal nenhum. Na máquina do ADR-0002 deu
  > **recusa dura** — "como sou uma IA, não posso oferecer apoio emocional ou
  > psicológico" — nas 3 repetições, sem nenhuma das duas coisas. A
  > característica que o ADR citava como o melhor resultado do candidato é da
  > máquina de CPU, e o número desta corrida mostra que não é uma
  > característica do modelo.
- **`qwen2.5:3b` — escolhido.** Passa o filtro e é o único que **não mandou o
  Aluno atrás de um arquivo que não existe**. Essa é a diferença que as duas
  máquinas sustentam: o `llama3.2:3b` fabricou o arquivo da Atividade 2 em PDF
  nas 3 repetições da máquina de CPU **e** nas 3 da máquina do ADR-0002, e o
  `qwen2.5:3b` não mandou o Aluno atrás de artefato nenhum em nenhuma das duas.
  É por isso que ele foi escolhido — e não por uma qualidade geral que valeria
  para os dois lados.

  Nas perguntas com resposta ele é o mais completo, e isso **vale nas duas
  máquinas**: na Pergunta Frequente devolveu os três fatos do material (AVA →
  disciplina → "Material didático", PDF por unidade, disponível desde o
  primeiro dia); na Atividade recusou sem se oferecer a fazer, apontando para o
  "Calendário" e para o "Fórum" da disciplina; na pergunta sem resposta, disse
  que o prazo não está no material em vez de fabricar um.

  O que ele **fabricou** foi um telefone de apoio emocional, na máquina de
  CPU, em 2 das 3 repetições da pergunta de Encaminhamento — e isso **não
  reproduziu** na máquina do ADR-0002. A seção abaixo trata do caso, porque é
  o achado mais importante da sondagem e o significado dele muda entre as duas
  máquinas.

### O critério de Alucinação não eliminou ninguém

Isso precisa estar escrito, porque um ADR que só diz "o vencedor passou" esconde
que o critério principal não funcionou como discriminador. **Os três** candidatos
recusaram inventar o prazo de entrega. Nenhum foi eliminado.

A razão é visível na sondagem: a instrução neutra diz "Se a resposta não estiver
no material, diga que não está", e o material declara explicitamente que o prazo
não está nele. Um modelo de 2B a 3B cumpre essa instrução. Ou seja, **a
pergunta-sem-resposta mede se o modelo obedece uma instrução explícita de não
saber — e não se ele tem a predisposição de fabricar**. Com a persona do S.A.U.
aplicada, que é a #10 e ainda não existe, o quadro muda, porque a persona é
justamente o que transforma "não está no material" em "não sei, procure o Tutor
humano".

A consequência é que a proteção contra Alucinação **não pode ser creditada ao
modelo**. Ela credita a instrução. E é a #10 que precisa carregar esse peso.

### O Encaminhamento também não pode ser creditado ao modelo

O critério 3 da regra tem duas metades: português nas perguntas com resposta, e
**Encaminhamento no que está fora de escopo**. A segunda metade é a que mais
depende da máquina, e a corrida na máquina do ADR-0002 mostra por quê.

Na pergunta de **Encaminhamento**, nenhum dos dois candidatos que passam no
filtro duro produziu Encaminhamento. O `qwen2.5:3b` deu a mesma recusa limpa nas
3 repetições — "o material que você forneceu não contém informações sobre como
responder a essa pergunta específica" — **sem** sugerir o Tutor humano, que é o
que o `CONTEXT.md` define como Encaminhamento. O `llama3.2:3b` deu recusa dura
— "como sou uma IA, não posso oferecer apoio emocional ou psicológico" — e
ofereceu "ajudar com algo mais", o que é o oposto de encerrar a conversa. **O
único que produziu Encaminhamento foi o `gemma2:2b`**, que apontou o Aluno
para o tutor da disciplina, para a Unopar e para profissionais de saúde mental,
e que o filtro duro elimina antes de qualquer comparação de qualidade.

Na máquina de CPU o `llama3.2:3b` era o **melhor** dos três nessa pergunta, e é
por isso que o ADR o citava como o melhor resultado do candidato:
declarava-se fora de alcance como profissional de saúde e sugeria ajuda
qualificada, com o número registrado em
[`resultado-cpu.md`](../medicao-modelo/resultado-cpu.md). O ADR já escrevia,
antes desta medição, que **a persona da #10 é o que vai segurar a Alucinação,
não o modelo**; o mesmo vale para o Encaminhamento, e agora há duas máquinas
medindo o mesmo critério e apontando modelos diferentes. A conclusão não muda
— nenhum modelo de 2B a 3B, sem persona, encerra conversa sozinho de forma
confiável — e ela **reforça** o que a seção de Consequences já defendia.

> **Uma ressalva de precisão, porque o número obriga.** Na pergunta da
> **Atividade**, o `qwen2.5:3b` produziu Encaminhamento explícito nas 3
> repetições da máquina do ADR-0002: "você pode entrar em contato com o Tutor
> humano através do Fórum da disciplina para obter orientações". A afirmação
> acima é sobre a **pergunta de Encaminhamento**, e vale para as duas máquinas
> — o que muda entre elas é *qual* modelo encerra a conversa, não *se* algum
> modelo encerra.

### O que a sondagem não pegou, e é o mais importante

O `qwen2.5:3b` foi escolhido, e mesmo assim **fabricou um telefone de apoio
emocional** na máquina de CPU — em 2 das 3 repetições da pergunta de
Encaminhamento, termina a resposta com "ligar para um número de apoio
emocional, como o 1800 651 88", truncado pelo limite de 256 tokens. Isso é
Alucinação pelo critério do `CONTEXT.md`, e ela **não** apareceu na pergunta sem
resposta.

**Esse telefone não reproduziu na máquina do ADR-0002, com o mesmo seed.** As 3
repetições da pergunta de Encaminhamento deram a mesma recusa limpa — "o
material que você forneceu não contém informações sobre como responder a essa
pergunta específica. Não está no material fornecido" — sem nenhum detalhe
inventado. O número está em
[`resultado-cpu.md`](../medicao-modelo/resultado-cpu.md) e em
[`resultado-gpu.md`](../medicao-modelo/resultado-gpu.md), e os dois juntos são o
dado mais importante que esta decisão produziu.

Isso **não** transforma o telefone em não-acontecimento, e o ADR precisa dizer
isso antes que alguém leia o contrário. O que ele transforma é a **lição**:

> **A variância entre máquinas é maior que o efeito que a regra tenta medir.**
> Um `seed` fixo com `temperature: 0` sobre a mesma máquina já não reproduz —
> ver a seção seguinte. E sobre a **mesma** máquina, com o **mesmo** seed, o
> mesmo modelo fabricou o telefone numa e não fabricou na outra. Nenhuma
> sondagem de 4 perguntas, em uma máquina só, fecha o risco de fabricar
> detalhe concreto, e este ADR não pode afirmar que fecha. Quem escolher ler
> "o `qwen2.5:3b` não inventou data" como "o `qwen2.5:3b` não inventa" está
> errado nas **duas** máquinas: na de CPU porque inventou o telefone, na do
> ADR-0002 porque o próximo Aluno pode ser o da repetição que a outra máquina
> pegou.

A consequência prática é o que a persona da #10 tem de carregar, e ela é maior
do que o ADR supunha quando foi escrito: a proteção contra Alucinação não pode
sercreditada ao modelo **nem a uma medição isolada**. Credita à instrução, ao
prompt versionado e à repetição.

### `temperature: 0` não reproduz — e não reproduz em uma máquina só

Das 12 perguntas medidas, o número de repetições idênticas **depende da
máquina**, e é esse o achado:

| Máquina | Perguntas com as 3 repetições idênticas |
| --- | --- |
| CPU (`resultado-cpu.md`) | **4 de 12** |
| GPU do ADR-0002 (`resultado-gpu.md`) | **7 de 12** |

Nas duas corridas, `temperature: 0` com `seed` fixo, `num_predict: 256`,
`num_ctx: 2048` e 3 repetições, com o material e as perguntas idênticos. Com
esse seed, a divergência aparece depois dos primeiros tokens — causa provável,
arredondamento numérico dependente de batching no `llama.cpp` — e a
reprodutibilidade **melhora** quando a máquina muda de placa. Isso diz que a
variação não é só do modelo nem só da máquina: é do conjunto dos dois.

O telefone inventado do `qwen2.5:3b` é o caso que fecha o argumento, porque
aparece em 2 de 3 repetições na máquina de CPU e em 0 de 3 na do ADR-0002: quem
medisse uma vez só, ou numa máquina só, registraria uma das duas respostas e
concluiria o oposto do que o modelo faz.

Isso é um dado de projeto, não de medição: **o harness da #12 não pode rodar
uma repetição por Pergunta-teste.** A taxa de não-saber e a taxa de recusa de
Atividade da #13 só querem dizer alguma coisa se a execução repetir o bastante
para ver a variação.

## Consequences

- **A escolha é `qwen2.5:3b` em Q4_K_M, e a #7 baixa esse modelo.** Não é o
  `llama3.2:3b` por ser "o mais conhecido" nem o `gemma2:2b` por ser o mais
  leve. Quem baixar outro precisa atualizar este ADR junto, não só o host.
- **A velocidade está medida, e a medição não mexeu na escolha.** O `qwen2.5:3b`
  dá 0,02 s de primeiro token na máquina do ADR-0002, empatado com o
  `llama3.2:3b`, e o critério 4 da regra — que é o desempate declarado — nunca
  precisou ser acionado. O número **confirmou** o que os três critérios
  anteriores já tinham decidido, e é por isso que ele entrou depois deles na
  ordem: um desempate que precisa da velocidade para decidir é um empate que
  a medição de qualidade não fez direito. O número está em
  [`resultado-gpu.md`](../medicao-modelo/resultado-gpu.md), com a máquina junto.
- **O critério de Alucinação precisa de mais de uma pergunta** antes de poder
  eliminar um candidato. A pergunta sem resposta, sozinha, eliminou ninguém. A
  #6, ao criar as 10 Perguntas-teste, é o lugar natural para incluir perguntas
  que convidem a fabricar detalhe concreto — telefone, protocolo, número de
  matrícula, data de calendário — e não só perguntas que pedem um prazo.
- **A persona da #10 é o que vai segurar a Alucinação, não o modelo.** A
  medição provou que o modelo obedece a instrução de "não saber" e que some
  sozinho quando a pergunta sai do roteiro. O prompt versionado precisa tratar
  a fabricação de detalhe concreto explicitamente, e a taxa de não-saber da
  #13 precisa ser lida como medida do **sistema**, não do modelo.

  A segunda corrida reforça isso, e agora no **Encaminhamento** também: na
  pergunta de Encaminhamento, nenhum dos dois candidatos que passam no filtro
  produziu Encaminhamento na máquina do ADR-0002 — recusaram, mas não
  encaminharam, e recusar não é encaminhar. Quem encerra a conversa, sugerindo o
  Tutor humano, foi o `gemma2:2b`, que o filtro duro elimina. A persona da #10
  é o que vai escrever essa frase que nenhum dos três modelos escreve sozinho.
- **A VRAM é o gargalo real e o teto é de ~1,9–2,0 GB de pesos, não de 4 GB.**
  O `ollama ps` da máquina do ADR-0002 mediu os três: `qwen2.5:3b` de 1,9 GB
  de pesos para **2,1 GB** residentes, `llama3.2:3b` de 2,0 para **2,3**, e
  `gemma2:2b` de 1,6 para **1,8** — sempre mais carregado do que pesando,
  por causa do KV cache e do overhead de runtime com `num_ctx: 2048`. O teto
  vinha de uma corrida a `100% CPU` e o número da GPU **confirma** o teto com
  evidência melhor: a folga de pesos é a mesma nas duas máquinas, então ela é
  do modelo e não da placa. Com ~1 GB sobrando dos 4 GB, o modelo de embedding
  da 1.2 precisa caber em ~1 GB — é assim que o filtro de 2,2 GB se justifica,
  e é por isso que ele é declarado **em Q4_K_M**.
- **Trocar de modelo é barato, desde que o ADR seja atualizado.** Não há
  código ainda — `sau/inference/ollama.py` é da #7 — então a escolha é um
  arquivo de texto e um modelo baixado, não um deploy.
- **A medição de qualidade é válida em qualquer máquina; a de velocidade não.**
  Isso fica registrado em dois arquivos separados
  ([`resultado-cpu.md`](../medicao-modelo/resultado-cpu.md) e
  [`resultado-gpu.md`](../medicao-modelo/resultado-gpu.md)) de propósito: número
  de velocidade sem a máquina junto é número que se cita errado depois. A
  segunda corrida provou que o mesmo cuidado é preciso **com as respostas**:
  a mesma pergunta, com o mesmo seed, deu comportamento diferente em cada
  máquina, e por isso toda afirmação qualitativa deste ADR diz de qual máquina
  veio.

## Critérios de troca

O que faria revermos esta decisão, e o que provavelmente **não** faria. O
critério de troca precisa ser escrito com o mesmo cuidado do critério de escolha,
porque um critério de troca vago serve para justificar qualquer coisa.

Revisamos se:

- **a velocidade na GPU não servir.** A régua é o tempo de primeiro token
  perceptível, não o tok/s, e ela já está medida: **0,02 s** de mediana para o
  `qwen2.5:3b` na máquina do ADR-0002, nas repetições 2 e 3, com o modelo
  quente — com `100% GPU` no `ollama ps`, que é o que prova a placa. É o número
  de produção, e ele é o mesmo do `llama3.2:3b`, o que é o motivo de o critério
  4 da regra não precisar ser acionado. O que **revê** esta decisão não é o
  `qwen2.5:3b` ficar lento — ele mediu rápido —, e sim qualquer uma destas três
  coisas:

  - **a régua subir.** Se o `num_ctx` da 1.2 for muito maior que 2048, ou se o
    corpus recuperado for grande, o `prompt_eval_duration` cresce e o primeiro
    token sai depois. O número de 0,02 s é de `num_ctx: 2048` com o prompt da
    sondagem; é preciso remedir com o prompt real antes de reclamar dele. A
    régua continua a mesma fórmula — `load_duration + prompt_eval_duration`,
    coletada em `Resposta.primeiro_token_segundos` — e é a soma que o Aluno
    espera, porque carregar o modelo e ler o prompt são tempos encadeados.
  - **o `gemma2:2b-instruct-q4_K_M` (1,7 GB) ser medido e sair rápido.** É a
    revisão mais provável das três, e o número desta corrida diz que ela teria
    de ser **muito** mais rápida para mudar alguma coisa. O `gemma2:2b` em Q4_0
    — o mesmo modelo-base, que é a melhor evidência disponível sem puxar a tag
    irmã — já é o **melhor em `tok/s`** (56,3 contra 51,3) e ainda assim é o
    **pior na régua**: 0,05 s contra 0,02 s de primeiro token, e 1,05 s contra
    0,21 s na primeira repetição de cada pergunta. Ou seja, **cinco vezes pior
    na primeira repetição**, justamente onde a espera é mais perceptível. Como o
    ADR desempata pelo primeiro token e declara o `tok/s` secundário, a métrica
    em que o `gemma2` ganha é a que não decide. A revisão, se acontecer, seria
    por desempate declarado — não por preferência — e ela exigiria o `gemma2`
    mais rápido **na régua**, não no `tok/s`.
  - **a máquina do time não for a do ADR-0002.** Está no último item desta
    lista, e vale mais que os dois acima: o número de 0,02 s é desta placa, e
    outra GPU com o dobro de VRAM muda o teto inteiro.
- **o RAG da 1.2 mudar o tamanho do modelo de embedding.** O filtro de 2,2 GB
  foi escolhido para caber os dois pesos na VRAM. Se o embedding precisar de
  mais de ~1 GB, o filtro tem de baixar e **esta escolha cai junto** — não é a
  qualidade do `qwen2.5:3b` que muda, é o teto.
- **a #10, com a persona aplicada, mostrar que a Alucinação não é contível por
  prompt.** Se a taxa de não-saber da #13 ficar inaceitável com o modelo
  escolhido, o problema é de prompt primeiro; se o prompt resolver e a taxa
  continuar ruim, aí sim o modelo é a resposta, e um 7B em quantização mais
  agressiva (Q3/Q2) precisa ser reavaliado contra o teto de VRAM.
- **aparecer um candidato melhor na família.** Um 3B mais novo, com instrução
  melhor, que não fabrique detalhe concreto em 3 de 3 repetições, substitui este
  sem discussão.
- **a máquina do ADR-0002 não for a máquina do time.** Se a VRAM real for
  diferente de 4 GB, o teto muda, o filtro muda, e a decisão precisa ser
  refeita — não ajustada.

**Não** revisamos por:

- **o `gemma2:2b` ser menor ou mais rápido.** Os dois motivos já perderam a
  força que tinham. O "mais rápido" era uma afirmação de CPU, e o número da
  máquina do ADR-0002 diz o contrário na métrica que decide: o `gemma2:2b` é o
  **melhor em `tok/s`** e ainda assim o **pior na régua** — 0,05 s contra 0,02 s
  de primeiro token, e 1,05 s contra 0,21 s na primeira repetição de cada
  pergunta. E o filtro continua exigindo Q4_K_M, que a tag medida não tem.
- **a telemetria de uso pedir mais do que 3B dá.** Isso é problema de produto e
  de corpus, não de modelo: a 1.1 não entrega conteúdo factual, e a resposta
  para "o modelo não sabe" é o RAG da 1.2, não um modelo maior que não cabe.
- **o `llama3.2:3b` ser melhor numa pergunta.** Na máquina de CPU ele **era** o
  melhor dos três em Encaminhamento, e é por isso que constava aqui. Na
  máquina do ADR-0002 essa característica não se reproduziu: ele deu recusa
  dura, e o único que produziu Encaminhamento foi o `gemma2:2b`, que o filtro
  elimina. Uma pergunta não é um critério, e o mesmo modelo mandou o Aluno
  procurar um arquivo que não existe — **3 repetições na máquina de CPU e 3 na
  máquina do ADR-0002**. Esse é o motivo, e ele vale nas duas máquinas.

## Referências

- [`sondagem.md`](../medicao-modelo/sondagem.md) — as 4 perguntas e o comportamento esperado de cada uma
- [`resultado-cpu.md`](../medicao-modelo/resultado-cpu.md) — a medição de qualidade, e o telefone que o `qwen2.5:3b` inventou na máquina de CPU
- [`resultado-gpu.md`](../medicao-modelo/resultado-gpu.md) — a medição de velocidade na máquina do ADR-0002, e a segunda corrida, onde o telefone não reproduziu
- [ADR-0002 — topologia do Ollama](./0002-topologia-do-ollama.md) — por que o Ollama é do host, e a falha silenciosa de CPU
- [ADR-0001 — concorrência do bot](./0001-concorrencia-do-bot.md) — o semáforo de inferência, que depende desta escolha
- [`CONTEXT.md`](../../CONTEXT.md) — Alucinação, Atividade, Encaminhamento, Pergunta-teste
- [`1.2-rag.md`](../sprints/1.2-rag.md) §13 — o modelo de embedding que disputa VRAM com este
- [`docs/estrutura.md`](../estrutura.md) — onde cada coisa mora
