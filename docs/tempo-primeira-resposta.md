# Tempo de primeira resposta do `qwen2.5:3b`

O que o primeiro Aluno da madrugada espera, medido com o stack no ar.

> **Este número é o número da máquina do ADR-0002.** Medido numa GTX 1650 com
> 4 GB de VRAM, por CUDA — a máquina que o ADR-0002 assume. Placa diferente é
> outro tempo: os números antigos desta página saíram de uma RX 7600 (Vulkan)
> e estão na nota ao fim.
>
> **Este número não é o número de produção.** A medição saiu de uma pergunta
> curta, com o modelo sem a persona do S.A.U. (que é a #10) e sem nenhum
> material de contexto (que é o RAG da 1.2). Um turno de conversa de verdade lê
> mais prompt, e a leitura do prompt é parte do tempo do primeiro token. O
> número real da produção vai ser maior que este.

## A máquina

| | |
| --- | --- |
| Sistema | Pop!_OS 22.04 LTS |
| Placa | NVIDIA GeForce GTX 1650 |
| VRAM | 4.294.967.296 bytes = **4096 MiB** |
| RAM | 7,5 GiB |
| Ollama | 0.34.4, `ollama serve` com `OLLAMA_HOST=0.0.0.0:11434` |
| Backend | **CUDA**, com `100% GPU` no `ollama ps` |

A VRAM saiu do `nvidia-smi` — por isso o `scripts/preparar-host.sh` a descobre
sozinho nesta máquina, sem o caminho do `/sys/class/drm` (que é para placas
que não são NVIDIA). Ver o
[ADR-0004](adr/0004-vram-por-maquina.md).

Antes de medir, o modelo foi descarregado com `keep_alive: 0`: o aquecimento
das checagens é a primeira coisa a tocar no modelo depois da subida. O
`OLLAMA_KEEP_ALIVE` desta máquina é o default de 5 minutos — passou disso, o
próximo Aluno paga a carga de novo.

## O que está no host

```
$ ollama list
NAME          ID              SIZE      MODIFIED
qwen2.5:3b    357c53fb659c    1.9 GB    20 hours ago

$ ollama ps
NAME          ID              SIZE      PROCESSOR    CONTEXT    UNTIL
qwen2.5:3b    357c53fb659c    2.1 GB    100% GPU     2048       4 minutes from now
```

A coluna `PROCESSOR` é a que vale. `100% GPU` é o que o ADR-0002 exige — e o
`CONTEXT` 2048 é a prova de que não houve recarga (ver abaixo).

## As condições

- Medido **de dentro do container**, com o stack no ar:
  `VRAM_TOTAL_MIB=4096 docker compose run --rm bot python -m sau.inference.fumaca --repeticoes 4`.
- Pergunta: `Em uma frase, o que você faz por um aluno?` — a pergunta padrão da
  fumaça, que é sintética e **não** é uma Pergunta-teste.
- O cliente não manda `temperature` nem `seed`. Quem mede é quem passa as
  condições dele, e por isso estes números não são comparáveis com a tabela do
  [ADR-0003](adr/0003-modelo-do-ollama.md), que foi medida com `temperature 0`
  e `seed 20260926`.
- `num_ctx` 2048 na checagem e na geração. O aquecimento usa o `NUM_CTX_PADRAO`
  do cliente, então a 1ª geração encontra o modelo já carregado na janela
  certa: **não há recarga**.
- 1 geração primeira e 3 com o modelo já respondendo.

## O tempo

O tempo de primeira resposta é `load_duration + prompt_eval_duration`, a mesma
conta e o mesmo nome de `docs/medicao-modelo/medir.py`. A soma é o que o Aluno
espera: o primeiro token só existe depois que o modelo carregou **e** o prompt
foi lido.

A carga fria — o que o aquecimento das checagens paga com o modelo
descarregado, medido direto na API com `num_ctx` 2048, três amostras:

| Amostra | Carga |
| --- | --- |
| 1 | 5,079 s |
| 2 | 4,587 s |
| 3 | 4,633 s |

A fumaça, com o modelo descarregado antes:

| Rodada | Primeiro token | Carga | Prompt | Total | tok/s | Tokens |
| --- | --- | --- | --- | --- | --- | --- |
| 1 — primeira depois do aquecimento | **0,297 s** | 0,002 s | 0,296 s | 0,673 s | 52,4 | 19 |
| 2 — modelo respondendo | **0,019 s** | 0,001 s | 0,018 s | 0,566 s | 54,1 | 29 |
| 3 — modelo respondendo | **0,020 s** | 0,001 s | 0,019 s | 0,547 s | 54,2 | 28 |
| 4 — modelo respondendo | **0,019 s** | 0,001 s | 0,018 s | 0,702 s | 53,6 | 36 |

Resumo, como a fumaça imprime:

```
========================================================================
TEMPO DE PRIMEIRA RESPOSTA (ttft)
  1ª geração, com a carga do modelo:  0.297 s
  demais gerações, modelo carregado: 0.019 s (média de 3)
========================================================================
```

**O que os dois números significam.** A carga (~4,8 s) é paga uma vez, no
aquecimento das checagens — em produção, na subida do serviço, antes do
primeiro Aluno chegar. O primeiro Aluno espera 0,3 s: quase tudo disso é a
primeira leitura do prompt (0,296 s contra 0,018 s das seguintes). Os Alunos
seguintes esperam 0,019 s. São coisas diferentes: misturá-los num número só
descreve um Aluno que não existe.

## A saída, como ela saiu no log

O log vem do cliente de inferência, em INFO, com o prefixo `[SAU]` do
serviço. O texto do modelo vai inteiro, sem resumo e sem aspas:

```
2026-09-29 00:05:43 [SAU] [INFO] sau.inference.ollama: Resposta do modelo 'qwen2.5:3b' | primeiro token 0.297s (carga 0.002s + prompt 0.296s) | total 0.673s | 52.4 tok/s | 19 tokens | parada: stop
Eu ajudo alunos a compreender e dominar o conteúdo que estão estudando.
```

E com uma Pergunta-teste de verdade, o `p1` ("quando vence a entrega"), que é o
quinto critério da #7. O texto foi copiado de
`perguntas-teste/perguntas-teste.md` para um arquivo fora do repo e mandado com
`--de-arquivo` (o container não enxerga o `/tmp` do host, então o arquivo entra
por `-v`); o arquivo congelado não é lido pela fumaça:

```
2026-09-29 00:07:41 [SAU] [INFO] sau.inference.ollama: Resposta do modelo 'qwen2.5:3b' | primeiro token 0.263s (carga 0.002s + prompt 0.261s) | total 2.813s | 52.0 tok/s | 132 tokens | parada: stop
Peço desculpas, mas não tenho informações específicas sobre a data de entrega da Atividade 2 para uma determinada disciplina. Isso geralmente depende do professor ou instrutor responsável pela disciplina e do seu calendário acadêmico.

Você pode encontrar essa informação:

1. No material de estudo fornecido pelo professor.
2. Em um calendário acadêmico específico da disciplina.
3. Perguntando diretamente ao seu professor ou instrutor.

Por favor, verifique essas fontes para obter a data exata e a hora limite de entrega da sua atividade.
```

O `p1` é a Pergunta-teste que mais convida a Alucinação: a resposta certa seria
dizer que não sabe o prazo. O modelo não inventou data nenhuma, e apontou o
Aluno para o professor e para o material. O que ele ainda não tem é a identidade
do S.A.U. e a regra de Encaminhamento — o que a persona da #10 vai resolver.
Este é o primeiro teste de que o modelo responde; a avaliação das respostas é
o trabalho da #12, e ela ainda não aconteceu.

## Para repetir

```sh
# Descarrega e roda a fumaça: aquecimento + 1 primeira + 3 respondendo, de dentro do container
curl -s http://localhost:11434/api/generate \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen2.5:3b","keep_alive":0}'

VRAM_TOTAL_MIB=4096 docker compose run --rm bot python -m sau.inference.fumaca --repeticoes 4
```

O `VRAM_TOTAL_MIB` tem de ser o da sua máquina, e não este 4096. O
`scripts/preparar-host.sh` descobre e imprime o valor certo.

## Números anteriores (RX 7600, código com recarga)

Medidos numa Radeon RX 7600 (Vulkan) antes de o aquecimento usar o `num_ctx`
da geração: 1ª geração 2,254 s (carga 2,180 s — uma recarga de 4096 para
2048), modelo carregado 0,011 s, frio de verdade 1,938 s. Não são comparáveis
com os de cima: placa diferente e código diferente. Ficam aqui pela linhagem
do número.
