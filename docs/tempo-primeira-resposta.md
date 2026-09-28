# Tempo de primeira resposta do `qwen2.5:3b`

O que o primeiro Aluno da madrugada espera, medido com o stack no ar.

> **Este número não é o número da máquina do ADR-0002.** A máquina do ADR-0002
> tem uma GTX 1650 com 4 GB de VRAM. A máquina aqui tem uma Radeon RX 7600 com
> 8 GB, e o Ollama fala com ela por Vulkan, não por CUDA. Placa diferente é
> outro tempo, e o número de uma não vale para a outra. Se você está na máquina
> do ADR-0002, meça de novo aí antes de usar qualquer valor desta página.
>
> **Este número também não é o número de produção.** A medição saiu de uma
> pergunta curta, com o modelo sem a persona do S.A.U. (que é a #10) e sem
> nenhum material de contexto (que é o RAG da 1.2). Um turno de conversa de
> verdade lê mais prompt, e a leitura do prompt é parte do tempo do primeiro
> token. O número real da produção vai ser maior que este.

## A máquina

| | |
| --- | --- |
| Sistema | Arch Linux |
| Placa | AMD Radeon RX 7600 (Navi 33) |
| VRAM | 8.573.157.376 bytes = **8176 MiB** |
| RAM | 15 GiB |
| Ollama | 0.34.4, serviço do sistema, escutando em `0.0.0.0:11434` |
| Modelos em | `/mnt/data/ollama/models` (o `OLLAMA_MODELS` do serviço) |
| Backend | **Vulkan**, com `37/37 layers to GPU` no `journalctl` |

A placa é AMD, e não NVIDIA. O `nvidia-smi` não existe nesta máquina — por isso
o `scripts/preparar-host.sh` também procura a VRAM em
`/sys/class/drm/card*/device/mem_info_vram_total`, que é onde o kernel publica
a mesma informação para placas que não são NVIDIA. Ver o
[ADR-0004](adr/0004-vram-por-maquina.md).

Antes de medir, o `llama3.1:8b` (4,9 GB) estava carregado no servidor, e o
`OLLAMA_KEEP_ALIVE` é de 30 minutos. Com o `qwen2.5:3b` (2,2 GB) somando, os
dois não cabiam nos 8 GB da placa e o `ollama ps` chegou a mostrar
`32%/68% CPU/GPU` para o 3B — o modelo escorregando para a CPU. Ele foi solto
antes de qualquer medição, com `keep_alive: 0`. A somar um modelo grande com o
nosso, a VRAM é deles dois, e o número sai errado sem nenhuma mensagem de erro.

## O que está no host

```
$ ollama list
NAME                ID              SIZE      MODIFIED
qwen2.5:3b          357c53fb659c    1.9 GB    12 minutes ago
llama3.1:8b         46e0c10c039e    4.9 GB    2 days ago
qwen2.5-coder:7b    dae161e27b0e    4.7 GB    3 days ago
(…)

$ ollama ps
NAME          ID              SIZE      PROCESSOR    CONTEXT    UNTIL
qwen2.5:3b    357c53fb659c    2.1 GB    100% GPU     2048       29 minutes from now
```

A coluna `PROCESSOR` é a que vale. `100% GPU` é o que o ADR-0002 exige.

## As condições

- Medido **de dentro do container**, com o stack no ar:
  `VRAM_TOTAL_MIB=8176 docker compose up -d` e depois
  `VRAM_TOTAL_MIB=8176 docker compose run --rm bot python -m sau.inference.fumaca`.
- Pergunta: `Em uma frase, o que você faz por um aluno?` — a pergunta padrão da
  fumaça, que é sintética e **não** é uma Pergunta-teste.
- O cliente não manda `temperature` nem `seed`. Quem mede é quem passa as
  condições dele, e por isso estes números não são comparáveis com a tabela do
  [ADR-0003](adr/0003-modelo-do-ollama.md), que foi medida com `temperature 0`
  e `seed 20260926`.
- `num_ctx` 2048. É o padrão do cliente.
- 1 geração que paga a carga do modelo, e 3 com ele já carregado.

**A carga da 1ª geração é uma recarga, não um modelo frio.** A checagem de
pré-requisito aquece o modelo com o `num_ctx` padrão do servidor, que nesta
máquina é 4096. A fumaça pede 2048, e o Ollama recarrega o modelo quando o
tamanho da janela muda: no `journalctl` são dois `llama-server` seguidos, um com
`-c 4096` e outro com `-c 2048`. O número do primeiro Aluno é o mesmo dos dois
jeitos — ele paga a carga uma vez —, mas o motivo não é só "o modelo estava
descarregado". O número do modelo frio de verdade está na seção
[O modelo frio de verdade](#o-modelo-frio-de-verdade).

## O tempo

O tempo de primeira resposta é `load_duration + prompt_eval_duration`, a mesma
conta e o mesmo nome de `docs/medicao-modelo/medir.py`. A soma é o que o Aluno
espera: o primeiro token só existe depois que o modelo carregou **e** o prompt
foi lido.

| Rodada | Primeiro token | Carga | Prompt | Total | tok/s | Tokens |
| --- | --- | --- | --- | --- | --- | --- |
| 1 — com a carga do modelo | **2,254 s** | 2,180 s | 0,074 s | 2,589 s | 100,7 | 33 |
| 2 — modelo carregado | **0,011 s** | 0,001 s | 0,010 s | 0,325 s | 104,7 | 32 |
| 3 — modelo carregado | **0,011 s** | 0,001 s | 0,010 s | 0,435 s | 103,5 | 43 |
| 4 — modelo carregado | **0,011 s** | 0,001 s | 0,010 s | 0,233 s | 106,1 | 22 |

Resumo, como a fumaça imprime:

```
========================================================================
TEMPO DE PRIMEIRA RESPOSTA (ttft)
  1ª geração, com a carga do modelo:  2.254 s
  demais gerações, modelo carregado: 0.011 s (média de 3)
========================================================================
```

**O que os dois números significam.** O primeiro Aluno da madrugada paga os
2,254 s: quase tudo disso é a carga do modelo, 2,180 s. Os Alunos seguintes
esperam 0,011 s, porque o modelo já está na VRAM e o prompt é curto. Os dois
números são do mesmo modelo na mesma máquina, e são coisas diferentes: misturá-los
num número só descreve um Aluno que não existe.

Enquanto o modelo está carregado, ele fica na VRAM por `OLLAMA_KEEP_ALIVE`,
que nesta máquina é 30 minutos. Passou disso, o próximo Aluno paga a carga de
novo. Uma madrugada inteira de plantão cabe folgada nesses 30 minutos, mas
atender dois Alunos com 40 minutos de intervalo custa a carga outra vez.

## O modelo frio de verdade

A tabela acima mede pela porta da fumaça, e por isso a 1ª geração paga uma
recarga. O modelo frio de verdade se mede com o Ollama descarregado e uma
geração só, direto na API:

| Primeiro token | Carga | Prompt | Total | tok/s | Tokens |
| --- | --- | --- | --- | --- | --- |
| **1,938 s** | 1,860 s | 0,078 s | 2,246 s | 97,8 | 30 |

É a mesma máquina, o mesmo modelo, o mesmo prompt e o mesmo `num_ctx` 2048, com
as condições do ADR-0003 (`temperature 0` e `seed 20260926`) — muda só a porta,
e a fumaça não manda `temperature` nem `seed`.

Os dois números ficam a uns 0,3 s um do outro, e a diferença vem do caminho: a
fumaça carrega o modelo duas vezes, uma na checagem com 4096 e outra na
geração com 2048, e a segunda carga vem depois da primeira. Quem pergunta
"quanto tempo leva a primeira resposta?" leva 1,94 s nesta máquina; quem mede
pela fumaça vê 2,25 s. Os dois são honestos, e nenhum dos dois é o número de
produção.

## A saída, como ela saiu no log

O log vem do cliente de inferência, em INFO, com o prefixo `[SAU-BOT]` do
serviço. O texto do modelo vai inteiro, sem resumo e sem aspas:

```
2026-09-28 09:06:27 [SAU-BOT] [INFO] sau.inference.ollama: Resposta do modelo 'qwen2.5:3b' | primeiro token 2.254s (carga 2.180s + prompt 0.074s) | total 2.589s | 100.7 tok/s | 33 tokens | parada: stop
Eu fico à disposição para ajudar um aluno a compreender novos conceitos e resolver problemas de maneira clara e eficaz.
```

E com uma Pergunta-teste de verdade, o `p1` ("quando vence a entrega"), que é o
quinto critério da #7. O texto foi copiado de
`perguntas-teste/perguntas-teste.md` para um arquivo e mandado com
`--de-arquivo`; o arquivo congelado não é lido pela fumaça:

```
2026-09-28 09:06:39 [SAU-BOT] [INFO] sau.inference.ollama: Resposta do modelo 'qwen2.5:3b' | primeiro token 0.051s (carga 0.001s + prompt 0.050s) | total 1.327s | 101.5 tok/s | 128 tokens | parada: stop
Desculpe pela confusão, mas como eu souo uma inteligência artificial criada pela Alibaba Cloud, eu não tenho informações específicas sobre as datas de entrega de atividades de disciplinas em suas respectivas universidades ou instituições de ensino.

A data limite para a entrega de atividades é geralmente uma informação fornecida pelo professor da disciplina ou pela própria instituição. Você deveria verificar com o professor que coordena a disciplina ou o departamento de estudos para obter a informação mais precisa e atual sobre quando a entrega da Atividade 2 deve ser realizada.
```

O `p1` é a Pergunta-teste que mais convida a Alucinação: a resposta certa seria
dizer que não sabe o prazo. O modelo não inventou data nenhuma, e apontou o
Aluno para o professor. O que ele ainda não tem é a identidade do S.A.U. e a
regra de Encaminhamento — "sou uma inteligência artificial criada pela Alibaba
Cloud" e "verifique com o professor" são justamente o que a persona da #10 vai
resolver. Este é o primeiro teste de que o modelo responde; a avaliação das
respostas é o trabalho da #12, e ela ainda não aconteceu.

## Para repetir

```sh
# 1. Modelo frio de verdade: descarrega, e manda uma geração só
curl -s -X POST http://localhost:11434/api/generate \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen2.5:3b","keep_alive":0}'

curl -s http://localhost:11434/api/generate \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen2.5:3b","prompt":"Em uma frase, o que você faz por um aluno?","keep_alive":"30m","options":{"temperature":0,"seed":20260926,"num_predict":256,"num_ctx":2048}}'

# 2. Descarga de novo e roda a fumaça: 1 com recarga + 3 quentes, de dentro do container
curl -s -X POST http://localhost:11434/api/generate \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen2.5:3b","keep_alive":0}'

VRAM_TOTAL_MIB=8176 docker compose run --rm bot python -m sau.inference.fumaca --repeticoes 4
```

O `VRAM_TOTAL_MIB` tem de ser o da sua máquina, e não este 8176. O
`scripts/preparar-host.sh` descobre e imprime o valor certo.
