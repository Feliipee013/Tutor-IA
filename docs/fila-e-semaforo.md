# Fila e semáforo de inferência

O `k` da máquina do [ADR-0002](./adr/0002-topologia-do-ollama.md), o roteiro para
medir, e o que o Aluno lê quando o S.A.U. está ocupado.

> **O `k` desta página ainda não foi medido.** O campo está em branco, e o número
> que roda hoje é o padrão declarado do código (`K_PADRAO = 2`), não um número
> verificado nesta máquina. O [ADR-0001](./adr/0001-concorrencia-do-bot.md) exige
> medição, e a medição é o procedimento da seção "Medir o `k`" abaixo. Até ela
> acontecer, qualquer afirmação sobre "quantos Alunos ao mesmo tempo" é hipótese.
>
> **Os dois testes de campo também não rodaram.** As duas contas do Telegram e os
> números que elas produziram estão em branco, pelo mesmo motivo: precisam de
> duas contas reais e de uma máquina com GPU, e o roteiro é o que está escrito.

## A máquina

A mesma do ADR-0002 e do
[tempo de primeira resposta](./tempo-primeira-resposta.md), porque é a máquina que
o `k` medido teria de valer.

| | |
| --- | --- |
| Sistema | Pop!_OS 22.04 LTS |
| Placa | NVIDIA GeForce GTX 1650 |
| VRAM | 4.294.967.296 bytes = **4096 MiB** |
| Ollama | 0.34.4, `OLLAMA_HOST=0.0.0.0:11434` |

## O `k` medido

| | |
| --- | --- |
| Gerações simultâneas que a VRAM aceita | **(a preencher)** |
| Gerações simultâneas que o S.A.U. usa (`INFERENCIA_K`) | **(a preencher)** |
| Tempo por geração, com o `k` acima | **(a preencher)** |
| Data e quem mediu | **(a preencher)** |

O padrão do código é `2`, e ele vem do ADR-0001: *"na prática aceita uma ou duas
gerações simultâneas porque a VRAM limita qualquer paralelismo maior"*. É ponto de
partida declarado, e não é o número desta máquina.

O teto da fila (`INFERENCIA_FILA_TETO`, padrão `10`) não aparece nesta tabela
porque não é medido: ele é um número escolhido, como o `TETO_DE_TURNOS_ESPERANDO`
da #9, e a razão do arbitrário está no próprio módulo.

## Medir o `k`

O critério é o que o ADR-0001 nomeia: quantas gerações simultâneas a VRAM desta
máquina aceita **sem o modelo cair para CPU**. Não é "quantas cabem" — caber
memória não é o mesmo que o Ollama continuar na GPU, e é para isso que a medição
existe.

1. **Suba o stack** e confirme o modelo na GPU antes de qualquer coisa:
   `ollama ps` precisa mostrar `100% GPU`. Medir com o modelo em CPU produz um
   número que não serve para nada, e o ADR-0002 já avisa disso: *"as medidas que os
   ADRs pressupõem passam a ser possíveis"*.
2. **Gere a carga.** Com o S.A.U. no ar, mande mensagens de duas contas
   diferentes ao mesmo tempo. Acompanhe com `ollama ps` — ele mostra quantas
   generations estão em `PROCESSING` ao mesmo tempo.
3. **Suba o `k` de um em um** (`INFERENCIA_K=3`, `4`, …) até `ollama ps` mostrar
   o modelo em CPU, ou até o tempo por geração piorar a ponto de o Aluno notar.
   O `k` é **um a menos** que o ponto em que isso acontece.
4. **Grave o tempo por geração** com o `k` final e com duas contas mandando
   juntas. É o número que a estimativa de espera vai usar em campo, e é o que
   substitui o piso declarado de 10 s.
5. **Preencha a tabela acima** e ponha o resultado no `.env` do seu ambiente.

O passo 3 é o que o ADR-0001 chama de "no escuro" e o que o `2` evita: sem ele,
quem escreve o `.env` escolhe o número por intuição, e a intuição erra para os dois
lados — `k=8` numa placa de 4 GB joga o modelo para CPU e derruba o tempo de todo
mundo, e `k=1` numa máquina folgada desperdiça a placa e faz o Aluno esperar na
fila sem necessidade.

## O que o Aluno lê

Três mensagens possíveis num turno, e elas não se substituem:

| Momento | Mensagem | Sai de |
| --- | --- | --- |
| O update chega | o acuse de recibo | do request, antes de qualquer inferência |
| A vaga está ocupada | a posição na fila e a estimativa | da thread do turno, antes de esperar |
| A vaga aparece | a resposta do modelo | da thread do turno |
| A fila passou do teto | a recusa educada | da thread do turno, sem chamar o modelo |

A posição e a estimativa **não entram no histórico**: elas são sobre a espera, e
não sobre a conversa, e um modelo lendo "você está na posição 3" como se fosse uma
fala do S.A.U. entenderia mal a conversa. A recusa entra, pelo mesmo motivo da
`TEXTO_FALHA` — o Aluno leu, e o histórico não pode divergir do que ele leu.

A estimativa é uma média móvel da duração observada das vagas, vezes o número de
voltas que a posição implica, e ela é declarada como estimativa. Antes da primeira
medição ela sai de um piso declarado de 10 s, que é o caso frio de
[`tempo-primeira-resposta.md`](./tempo-primeira-resposta.md) arredondado para
cima. O `k` medido é o que substitui esse piso na prática, mas por outro caminho:
o piso é o valor de partida da estimativa e o `k` é o valor de partida do limite.

## Testar com as duas contas

O critério que a suíte não cobre é o do Aluno real: a mensagem de posição tem de
fazer sentido para quem está esperando, e não apenas existir.

| | |
| --- | --- |
| Conta 1 (`chat_id`) | **(a preencher)** |
| Conta 2 (`chat_id`) | **(a preencher)** |
| `INFERENCIA_K` usado no teste | **(a preencher)** |
| O que a conta 2 leu, palavra por palavra | **(a preencher)** |
| O tempo real de espera da conta 2 | **(a preencher)** |
| A estimativa comparada com o tempo real | **(a preencher)** |

O roteiro:

1. `INFERENCIA_K=1` e duas contas, uma por vez, para confirmar que uma por vez
   funciona e que nenhuma das duas recebe mensagem de fila.
2. As duas contas mandando mensagem **quase ao mesmo tempo**. A segunda deve ler
   acuse, depois posição, depois a resposta — nessa ordem.
3. Anote o que a segunda leu, palavra por palavra, e o tempo entre o acuse e a
   resposta.
4. Compare a estimativa com o tempo real. Ela **vai** errar: a média móvel ainda
   está aprendendo, e a primeira vaga da noite é a pior. O que não pode é errar de
   um fator de dois para mais, porque aí o Aluno desiste antes de a estimativa
   melhorar.
5. Suba `INFERENCIA_K` para o valor medido e repita o passo 2. Agora as duas devem
   entrar juntas e nenhuma deve ler posição.

## Para repetir

- **As três validações** do repositório, depois de mexer no módulo ou no
  `webhook`:
  ```bash
  .venv/bin/python -m pytest
  .venv/bin/python -m ruff check .
  .venv/bin/python -m mypy .
  ```
- **A suíte do semáforo sozinha**, que é a parte que depende de concorrência:
  ```bash
  .venv/bin/python -m pytest tests/test_semaphore.py -q
  ```
  Rode mais de uma vez se mexeu em trava. Um teste de concorrência que passa uma
  vez prova pouco, e o que falha é a ordem de despertar, que é justamente o
  defeito que a fila de senha existe para não ter.
- **O `k` de novo**: a medição é da máquina, e a máquina muda de placa, de
  Ollama e de modelo. Quem muda um dos três refaz a tabela do topo.

## O que esta página ainda não tem

- **O `k` medido.** A seção é o procedimento; o número está em branco.
- **As duas contas.** O roteiro está escrito; os números estão em branco.
- **A comparação entre a estimativa e a espera real.** Sai da mesma conta de
  campo, e depende dela.

Nada aqui é bloqueio para o serviço: o semáforo funciona com o `k` declarado, e
`tests/test_semaphore.py` prova o mecanismo sem máquina nenhuma. O que falta é a
medição — e medições que ninguém fez não se escrevem no lugar delas.
