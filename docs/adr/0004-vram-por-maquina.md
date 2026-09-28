# A VRAM é declarada por máquina, e a checagem não é só da NVIDIA

---
status: accepted
---

O serviço recebe a VRAM total da máquina por `VRAM_TOTAL_MIB`, em MiB, e
confronta esse número com o `size_vram` que o Ollama relata. Este ADR fixa três
coisas: que o contrato é um inteiro em MiB e não tem nada de NVIDIA, como
descobrir o valor em cada tipo de placa, e o que fazer numa máquina sem GPU
dedicada.

O motivo de existir é o do time. Somos 7 pessoas em 3 máquinas, e duas delas não
têm placa NVIDIA. Um contrato que só a NVIDIA preenche deixa a variável em branco
na máquina de quem não tem nvidia-smi, e a checagem do ADR-0002 reprova com
"VRAM não informada" — que parece defeito do código e é só falta do número.

## O contrato não é NVIDIA

`VRAM_TOTAL_MIB` é um inteiro positivo em MiB, e ponto. A checagem do ADR-0002
só faz uma coisa com ele: compara com o `size_vram`, em bytes, que o Ollama
relata no `/api/ps`. Não há nome de placa, não há driver, não há marca ali dentro.
O nome da variável é `VRAM_TOTAL_MIB` e não `NVIDIA_VRAM_MIB` porque a
distinção não existe para quem usa.

Quem escolheu o nome do `nvidia-smi` e o `head -1` como receita única estava
escrevendo o caminho da máquina que ele tinha na mão, e não o contrato. A
`prereqs.py` e o `config.py` nunca exigiram NVIDIA; a documentação é que se
achava mais estreita do que o código.

## Como descobrir o valor

Em ordem, pegando a primeira que responder:

```sh
# NVIDIA
nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | head -1

# Qualquer placa que o kernel conhece, NVIDIA ou não
cat /sys/class/drm/card*/device/mem_info_vram_total
```

O `head -1` não é decoração: o `nvidia-smi` imprime uma linha por placa, e sem o
filtro uma máquina com duas placas entrega "4096\n4096", que não é um inteiro.

O `/sys/class/drm` é o caminho geral. O kernel escreve
`mem_info_vram_total` só para as placas que têm memória de vídeo própria — uma
GPU integrada costuma não ter o arquivo. Quando existe, ele vem em bytes, e a
conversão para MiB arredonda **para cima**. Isso é escolha, não detalhe: a VRAM
declarada é o contra o que o `size_vram` é comparado, e arredondar para baixo
faria a placa parecer menor do que é, reprovando com "dados contraditórios" uma
alocação que cabe. Sobrar um MiB no total não machuca; faltar um é uma falha
que não existe.

Com mais de uma placa com VRAM, o script **para** e mostra as duas em vez de
escolher uma. Ele não sabe qual placa o Ollama está usando, e adivinhar seria
pior que não saber: uma VRAM declarada grande demais aprova a checagem de uma
alocação que talvez nem caiba, e o defeito reaparece pelo lado do verde.

O `scripts/preparar-host.sh` faz essa busca e imprime o
`export VRAM_TOTAL_MIB=...` pronto. Em máquina sem GPU, ele avisa em vez de
falhar — ver a próxima seção.

## Sem GPU dedicada: roda, mas não mede

Uma máquina sem GPU dedicada não está quebrada, e o time não espera que esteja.
O que não pode é medir tempo de produção nela: um Ollama em CPU devolve um
número plausível e errado ao mesmo tempo, que é a pior combinação possível — o
erro se parece com o acerto.

Então são dois estados, e eles não se confundem:

| Estado | O que acontece | Como pedir |
| --- | --- | --- |
| Com GPU dedicada | `VRAM_TOTAL_MIB` é obrigatória e a checagem falha se faltar | `export VRAM_TOTAL_MIB=$(nvidia-smi … \| head -1)` |
| Sem GPU dedicada | O Ollama roda em CPU, a checagem vira aviso, e o serviço sobe | `OLLAMA_ALLOW_CPU=true` |

Roda em CPU é para desenvolver, para CI e para medir a **qualidade** das
respostas, que é medida válida em qualquer máquina. Tempo em CPU não é
produção, e a fumaça e o `medir.py` param com erro antes de gerar qualquer tempo
a não ser que alguém passe `--permitir-cpu` na mão.

O aviso importa tanto quanto o caminho. Uma pessoa que roda em CPU e não sabe
que está rodando em CPU vai colar um número de CPU num documento de produção, e
ninguém vai perceber — que é exatamente o defeito que o ADR-0002 existe para
fechar. Por isso o "sem GPU" é sempre dito: no script, na fumaça, no README.

## Considered Options

- **Descobrir a VRAM por dentro do Ollama.** Não existe. O `/api/ps` diz o
  quanto um modelo ocupou, e o `/api/version` não diz nada de placa. A checagem
  do ADR-0002 não teria contra o que comparar.
- **Um número só, no `.env`, escrito à mão.** É o que tinha, e é o que deixa a
  variável em branco justamente na máquina de quem não tem `nvidia-smi`. O
  `.env` continua valendo, e o script imprime a linha para ele.
- **Pedir o valor em MiB já convertido, para todo mundo.** Obligaria quem tem
  placa não-NVIDIA a fazer a conta de bytes para MiB à mão, e um erro de fator
  1024 ali reprova a checagem sem mensagem que ajude.
- **Substituir a checagem por uma leitura do `ollama ps`.** A coluna `PROCESSOR`
  não é informação de API, é texto de tabela, e o texto muda entre versões.

## Consequences

- **`VRAM_TOTAL_MIB` continua obrigatória por padrão.** Não virou opcional
  "quando der". O ADR-0002 continua valendo: a checagem falha alto, e quem
  autoriza CPU diz isso na mão, com `OLLAMA_ALLOW_CPU=true`.
- **O `nvidia-smi` sai do caminho obrigatório.** Ele vira uma das duas formas de
  achar o número, e a outra cobre quem não tem NVIDIA.
- **Nenhum número de tempo é transferível entre máquinas.** A máquina do
  ADR-0002 é a GTX 1650 de 4 GB; a da medição do
  [tempo de primeira resposta](./../tempo-primeira-resposta.md) é uma Radeon
  RX 7600 de 8 GB com backend Vulkan. O
  [ADR-0003](./0003-modelo-do-ollama.md) mediu na primeira, e o número da
  segunda não substitui o da primeira. Cada máquina tem a sua página.
- **`nvidia-smi` responder não prova que há GPU em uso.** Ele prova que há driver
  NVIDIA na máquina. Quem prova é o `ollama ps`, na coluna `PROCESSOR`, e é por
  isso que o script imprime essa linha.
- **Um número de VRAM errado não se denuncia.** Ele aprova a checagem errada em
  silêncio, e o único jeito de perceber é conferir `nvidia-smi` (ou
  `/sys/class/drm`) com o que foi exportado. Vale conferir na primeira vez de
  cada máquina.
