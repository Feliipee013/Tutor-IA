# Medição de velocidade na máquina com GPU

> ## Medido em 26/09/2026, e o número é válido
>
> A coluna de velocidade do
> [ADR-0003](../adr/0003-modelo-do-ollama.md) está preenchida, e saiu desta
> máquina — que **é** a do ADR-0002. O `ollama ps` mostrou **`100% GPU` nos
> três candidatos**, que é a autoridade: é ela, e não a ausência de CPU na
> coluna, que prova em que processador cada um rodou.
>
> | | |
> | --- | --- |
> | Sistema | Linux 7.1.1-76070101-generic |
> | GPU | NVIDIA GeForce GTX 1650 |
> | VRAM | 4,00 GiB |
> | RAM | 7,53 GiB totais, 2,73 GiB livres no momento da medição |
> | Ollama | 0.34.4 |
>
> As condições são as mesmas da corrida em CPU: `seed` 20260926,
> `temperature` 0, `num_predict` 256, `num_ctx` 2048, 3 repetições, 36
> respostas. A medição rodou **sem** `--permitir-cpu` e **sem** `--manter-vivo`,
> e é por isso que o cold start desta tabela é o cold start de verdade: o
> defeito conhecido da flag `--manter-vivo`, que quebra a régua de cold start
> em silêncio, não entrou aqui.
>
> **O número não reverteu a escolha.** `qwen2.5:3b` e `llama3.2:3b` empatam
> em 0,02 s de primeiro token, e o critério 3 da regra — que separa os dois —
> já tinha decidido antes deste número existir. O que a segunda máquina mudou
> foi a **prosa**: três afirmações qualitativas do ADR-0003 que descreviam a
> máquina de CPU não se sustentam aqui, e o ADR agora diz o nome da máquina ao
> lado de cada uma.
>
> As seções de método abaixo — procedure, checagens, regra do número — foram
> mantidas de propósito. Elas descrevem **como** a medição foi feita e
> **como** o número deve ser lido, e continuam valendo para quem medir em
> outra máquina.

## Para quem é

Para quem estiver na máquina do **ADR-0002**: Intel UHD **e** NVIDIA, **4 GB de
VRAM** e **7,5 GiB de RAM**. Se a máquina não tiver os 4 GB de VRAM, pare e leia
[Antes de começar](#antes-de-começar) — o teto de hardware é parte da decisão e
mudá-lo invalida a escolha do modelo, não só a velocidade.

Tempo estimado: 15 a 40 minutos, dos quais a maior parte é o download dos três
modelos e a geração em CPU… em GPU. Se a máquina não tiver rede rápida, o
download domina.

## Antes de começar

Três checagens. As três são pré-requisito, e cada uma delas tem um modo de
falhar que é **silencioso** — é o defeito que o ADR-0002 existe para fechar.

### 1. A placa responde?

```sh
nvidia-smi
```

Tem de responder. Sem isso, pare: o resto da medição vai rodar em CPU e produzir
um número plausível e errado.

### 2. A VRAM é a do ADR-0002?

```sh
nvidia-smi --query-gpu=name,memory.total --format=csv
```

Precisa mostrar **4096 MiB** (ou 4 GB) na placa **discreta**. Se mostrar mais, a
máquina não é a do ADR-0002: **pare e avise quem vai revisar a PR**, porque o
teto de 2,2 GB por modelo muda junto e o ADR precisa ser revisto antes de
publicar o número.

### 3. A medição vai cair na placa certa?

```sh
nvidia-smi -L
```

A máquina tem Intel UHD **e** NVIDIA. Para garantir que a medição use a
discreta e não a integrada, fixe `CUDA_VISIBLE_DEVICES` com o **UUID** que o
comando acima imprime, não com índice numérico — a ordem dos devices pode
variar entre máquinas e entre boots.

```sh
export CUDA_VISIBLE_DEVICES=GPU-<uuid-que-nvidia-smi-L-imprimiu>
```

> **`CUDA_VISIBLE_DEVICES` é o nome certo.** O ADR-0002 e a issue #3 diziam
> `OLLAMA_VISIBLE_DEVICES`, que não existe no Ollama e é ignorado em silêncio.
> A correção está no ADR-0002 e no SETUP.md; a **issue #3 ainda não foi
> corrigida** e alguém precisa editar o critério 4 dela.
>
> E o mais importante: **esta variável não é a verificação.** Ela só restringe o
> que o Ollama pode enxergar, e uma variável mal formatada é ignorada sem erro.
> Quem prova a placa em uso é o `ollama ps`, e o `medir.py` aborta se ele
> mostrar CPU.

## O Ollama

O compose **sobe só o bot**; o Ollama é um serviço do host (ADR-0002). Ele
precisa estar rodando **antes** de qualquer coisa:

```sh
ollama --version
curl -s http://localhost:11434/api/version
```

Se a porta 11434 estiver fechada, suba o serviço. No Linux com systemd:

```sh
sudo systemctl start ollama
```

No Windows, o Ollama é instalado pelo instalador oficial
(https://ollama.com/download) ou por `winget install Ollama.Ollama`.

## Rodar a medição

Da raiz do repositório:

```sh
python docs/medicao-modelo/medir.py --saida-json bruto-gpu.json
```

**Sem `--permitir-cpu`.** O padrão do script é exigir GPU e abortar, e é
justamente esse abortar que prova que a checagem está valendo. Se você passar
`--permitir-cpu` nesta máquina, o número sai errado e o aviso passa em branco.

O script faz, sozinho:

- baixa os três candidatos;
- tira o tamanho de cada um do `ollama list`;
- carrega o modelo, roda `ollama ps` e **aborta se mostrar CPU**;
- roda as 4 perguntas da [`sondagem.md`](./sondagem.md) 3 vezes cada, com
  `temperature: 0`, `seed` fixo, `num_predict: 256` e `num_ctx: 2048`;
- descarrega cada modelo antes do próximo (`keep_alive: 0`), porque 7,5 GiB de
  RAM não segura os três carregados;
- imprime a tabela em markdown e o JSON bruto.

Se der erro de RAM ao baixar o segundo modelo, é falta de memória de disco ou de
banda, não do modelo: rode um candidato por vez com
`--candidatos llama3.2:3b` e cole as tabelas na mesma ordem.

## O número medido

A tabela abaixo está preenchida com o número desta máquina, que é a do ADR-0002.
Quem medir em outra máquina substitui as células pelas suas — e o número do
[ADR-0003](../adr/0003-modelo-do-ollama.md) é o que entra na coluna de
velocidade, nunca outro.

| Candidato | Pesos (`ollama list`) | Processador (do `ollama ps`) | Primeiro token mediana (s) | Primeiro token cold start (s) | Geração média (s) | Mediana (s) | tok/s (secundário) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `qwen2.5:3b` | 1.9 GB | **100% GPU** | **0,02 s** | **0,21 s** | 2,67 s | 1,67 s | 51,3 |
| `llama3.2:3b` | 2.0 GB | **100% GPU** | **0,02 s** | **0,22 s** | 2,25 s | 1,98 s | 53,2 |
| `gemma2:2b` | 1.6 GB | **100% GPU** | **0,05 s** | **1,05 s** | 2,70 s | 1,90 s | 56,3 |

`100% GPU` nos três, então **nenhum candidato foi tarjado** e todos os três
saíram com número. A diferença entre eles na régua é pequena: o
`qwen2.5:3b` e o `llama3.2:3b` empatam em 0,02 s, e o `gemma2:2b` está a
0,03 s dos dois. Na régua, os três são praticamente o mesmo modelo — e o que
separa os dois que passam no filtro é o critério 3, que vem **antes** da
velocidade na ordem da regra.

O que **não** é empate é a primeira repetição de cada pergunta, a linha que o
ADR separa como cold start: 1,05 s do `gemma2:2b` contra 0,21 s do
`qwen2.5:3b` é **cinco vezes** mais espera. E é exatamente na métrica que a
tabela do ADR trata como secundária, o `tok/s`, onde o `gemma2:2b` lidera
(56,3 contra 51,3) — a ordem se inverte entre as duas últimas colunas, e é a
régua que decide.

> **O que essa linha é, e o que ela não é.** É a mediana das 4 repetições 1 dos
> 4 candidatos, e por isso não é uma atípica nem ruído: o mesmo padrão se
> repete nos três, com `gemma2:2b` cerca de 5× acima dos outros dois. O que
> ela **não** é é tempo de carregar pesos: o `carga_segundos` que o `medir.py`
> grava é de **~0,001 s nas 12 respostas**, repetição 1 incluída — o modelo
> já está aquecido quando as 12 respostas começam, e a diferença da repetição 1
> é quase toda a leitura do prompt (`prompt_eval_duration`), não a carga. A
> docstring do campo diz que a repetição 1 "paga a carga do modelo", e o número
> desta corrida não confirma essa leitura. O ADR-0003 mantém a coluna e o
> significado dela porque a regra de troca é a mesma; o que muda é a causa, e
> ela está registrada aqui em vez de ser afirmada em silêncio.

## A evidência

As linhas que o `medir.py` imprimiu, com o PROCESSOR de cada candidato:

```
ollama list: qwen2.5:3b  357c53fb659c  1.9 GB  Less than a second ago
ollama list: llama3.2:3b  a80c4f17acd5  2.0 GB  Less than a second ago
ollama list: gemma2:2b  8ccf136fdd52  1.6 GB  Less than a second ago

ollama ps:   qwen2.5:3b  357c53fb659c  2.1 GB  100% GPU  2048  4 minutes from now
ollama ps:   llama3.2:3b  a80c4f17acd5  2.3 GB  100% GPU  2048  4 minutes from now
ollama ps:   gemma2:2b  8ccf136fdd52  1.8 GB  100% GPU  2048  4 minutes from now
```

Os pesos dos dois blocos batem coluna a coluna com a tabela acima, e o SIZE do
`ollama ps` é sempre **maior** que o peso no `ollama list` — 1,9 vira 2,1, 2,0
vira 2,3, 1,6 vira 1,8. É o KV cache e o overhead de runtime com
`num_ctx: 2048`, medidos na GPU, e é o que sustenta o teto de ~1,9–2,0 GB de
pesos do ADR-0003. Em CPU a diferença é a mesma, e é por isso que o número do
teto não dependia da máquina.

A regra de leitura desta tabela continua valendo, e é a que impediu um número
errado de entrar: se a coluna PROCESSOR mostrar qualquer porcentagem de CPU, a
medição **não** é válida, mesmo que os tempos pareçam bons — e nesse caso o
número não entra no ADR. A regra vale por candidato: um que caia só
parcialmente para CPU já é tarjado, e um que esteja de fato na GPU sai com
número mesmo numa máquina sem `nvidia-smi`. Quem prova a placa é a coluna
PROCESSOR. Nos três daqui, `100% GPU`.

## Qual número decide

O [ADR-0003](../adr/0003-modelo-do-ollama.md) desempata pelo **tempo de
primeiro token perceptível**, não pelo tok/s. As duas medidas estão na tabela,
mas não têm o mesmo peso:

- **`Primeiro token mediana` é a régua.** É o que o Aluno espera, e o ADR
  desempata por ela. Vem do campo `Resposta.primeiro_token_segundos` do
  [`medir.py`](./medir.py), calculado como `load_duration + prompt_eval_duration`:
  o modelo carregar e o prompt ser lido são dois tempos encadeados, e o
  primeiro token só existe quando os dois acabaram.
- **`Primeiro token cold start` é a repetição 1, e não é uma atípica.** O script
  usa `keep_alive: 0` entre candidatos, então a primeira repetição de cada
  pergunta paga a carga do modelo e as outras duas não. A mediana sai das
  repetições 2 e 3 porque o plantão é com o modelo quente. **Não** trate a
  repetição fria como outlier nem jogue fora a linha: quem espera o primeiro
  Aluno de uma madrugada paga a carga, e isso é fato.
- **`tok/s` é secundário.** O ADR diz que é, e por isso ele vem marcado como tal
  na coluna. Ele mede a vazão da geração, não a espera — um modelo que despeja
  tokens rápido depois de esperar 5 s continua sendo um modelo que o Aluno
  espera 5 s.

## Como o número voltou para o ADR

O que foi feito com esta medição, e o que ela decidiu:

1. **A coluna de velocidade do
   [ADR-0003](../adr/0003-modelo-do-ollama.md) foi preenchida** com os números
   desta tabela e com o `100% GPU` dos três, e o aviso de que a velocidade
   estava por medir saiu do ADR.
2. **A máquina foi registrada junto do número**: VRAM de 4,00 GiB e RAM de
   7,53 GiB, que é o teto do ADR-0002 conferido contra o `ollama ps`, e não
   assumido.
3. **A escolha não mudou.** `qwen2.5:3b` continua o escolhido, e o desempate
   declarado nunca precisou ser acionado: os dois candidatos que passam no
   filtro duro estão empatados em 0,02 s, e o critério 3 — Alucinação e
   comportamento no secundário — já os tinha separado. A velocidade confirmou
   o que os outros três critérios disseram, que é o melhor jeito de ela
   confirmar.
4. **A prosa do ADR mudou, e isso é o resultado que importa.** A máquina de CPU
   e esta máquina discordam em três afirmações qualitativas que o ADR
   escrevia sem dizer de qual máquina vinham. Nenhuma delas muda o vencedor, e
   as três mudam o que o ADR afirma saber:
   | Afirmação que estava no ADR | Na máquina de CPU | Na máquina do ADR-0002 |
   | --- | --- | --- |
   | Telefone de apoio emocional do `qwen2.5:3b` | fabricou `1800 651 88` em 2 das 3 repetições de Encaminhamento | **não reproduziu** — 3 de 3 deram a mesma recusa limpa, sem detalhe inventado |
   | Arquivo da Atividade 2 do `llama3.2:3b` | fabricou nas 3 repetições | **fabricou nas 3 de novo**, e é a diferença que as duas máquinas sustentam |
   | Encaminhamento do `llama3.2:3b` | "declaro ser um modelo de linguagem, ofereço ouvir, sugiro ajuda qualificada" | recusa dura: "como sou uma IA, não posso oferecer apoio emocional ou psicológico" |

5. **O `gemma2:2b` ganhou a métrica secundária e perdeu a régua.** 56,3 tok/s
   contra 51,3 do `qwen2.5:3b` — e 1,05 s de cold start contra 0,21 s. Se o
   ADR desempatasse pelo `tok/s`, a escolha seria outra; como desempata pelo
   primeiro token, o `gemma2:2b` fica fora pelo filtro duro e a escolha não se
   move. É a regra de troca funcionando como foi escrita.
6. **`temperature: 0` com seed fixo não reproduziu aqui também** — e não era
   para reproduzir. Das 12 perguntas, **7** tiveram as 3 repetições idênticas,
   contra 4 de 12 na máquina de CPU. A variância **entre máquinas** é maior
   que a variância dentro de uma delas, e o ADR-0003 passou a citar as duas.

## Referências

- [ADR-0002 — topologia do Ollama](../adr/0002-topologia-do-ollama.md) — a falha silenciosa de CPU, e o teto de hardware
- [ADR-0003 — modelo do Ollama](../adr/0003-modelo-do-ollama.md) — a regra de decisão e a escolha
- [`sondagem.md`](./sondagem.md) — as 4 perguntas e o comportamento esperado de cada uma
- [`resultado-cpu.md`](./resultado-cpu.md) — a medição de qualidade, em outra máquina, que **não** substitui esta
- [Ollama com GPU NVIDIA](https://docs.ollama.com/gpu)
