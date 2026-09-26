# Medição de velocidade na máquina com GPU

> **PENDENTE — a coluna de velocidade do
> [ADR-0003](../adr/0003-modelo-do-ollama.md) está esperando este arquivo.**
>
> A qualidade dos três candidatos já foi medida e está em
> [`resultado-cpu.md`](./resultado-cpu.md). A **velocidade não foi**: a máquina
> onde a medição de qualidade saiu é um notebook AMD sem GPU discreta, e o
> ADR-0002 exige que a velocidade seja medida na máquina alvo. Os tempos em CPU
> que existem em `resultado-cpu.md` **não** podem substituir esta medição — eles
> descrevem outra máquina, e a nota da issue #3 chama exatamente isso de "o
> critério mais fácil de cumprir errado".

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

## O que colar aqui

Substitua o bloco de pendência abaixo pelos números da sua máquina. São **três
números por candidato**, e eles são os que faltam no ADR.

| Candidato | Pesos (`ollama list`) | Processador (do `ollama ps`) | Geração média (s) | Mediana (s) | tok/s |
| --- | --- | --- | --- | --- | --- |
| `qwen2.5:3b` | _a medir_ | _a medir_ | _a medir_ | _a medir_ | _a medir_ |
| `llama3.2:3b` | _a medir_ | _a medir_ | _a medir_ | _a medir_ | _a medir_ |
| `gemma2:2b` | _a medir_ | _a medir_ | _a medir_ | _a medir_ | _a medir_ |

E cole também, para a evidência:

```
ollama list: <a linha de cada modelo>
ollama ps:   <a linha de cada modelo, com o PROCESSOR>
```

Se a coluna PROCESSOR mostrar **100% GPU**, a medição é válida. Se mostrar
qualquer porcentagem de CPU, a medição **não** é válida, mesmo que os tempos
pareçam bons — e nesse caso o número não entra no ADR.

## Como o número volta para o ADR

1. Preencher a tabela acima e o bloco de pendência.
2. Trocar, no [ADR-0003](../adr/0003-modelo-do-ollama.md), a coluna de velocidade
   de `pendente` pelos números, e **tirar** o aviso de que a velocidade está
   pendente.
3. Conferir que a máquina registrada no ADR é a do ADR-0002 (4 GB de VRAM,
   7,5 GiB de RAM) e que o `ollama ps` de cada candidato mostrou GPU.
4. Se a velocidade **mudar o vencedor**, isso é um resultado, não um problema:
   a regra de decisão do ADR-0003 põe a velocidade em último lugar e desempata
   por ela, então o texto da escolha precisa ser revisto junto com o número.

## Referências

- [ADR-0002 — topologia do Ollama](../adr/0002-topologia-do-ollama.md) — a falha silenciosa de CPU, e o teto de hardware
- [ADR-0003 — modelo do Ollama](../adr/0003-modelo-do-ollama.md) — a regra de decisão e a escolha
- [`sondagem.md`](./sondagem.md) — as 4 perguntas e o comportamento esperado de cada uma
- [`resultado-cpu.md`](./resultado-cpu.md) — a medição de qualidade, que **não** substitui esta
- [Ollama com GPU NVIDIA](https://docs.ollama.com/gpu)
