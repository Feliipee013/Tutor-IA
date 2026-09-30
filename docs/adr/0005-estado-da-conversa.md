# O estado da conversa fica num arquivo, isolado por `chat_id`, e expira sozinho

---
status: accepted
---

O S.A.U. guarda o que cada Aluno perguntou e o que ele respondeu, num arquivo
SQLite no serviço `webhook`, com a chave sendo o **`chat_id`** e não o `from.id`.
A conversa ociosa é apagada depois de 30 minutos sem contato, por padrão. E as
mensagens de uma mesma conversa são respondidas **na ordem em que chegaram**,
enquanto conversas diferentes correm em paralelo sem se esperar.

Isto é a parte do [ADR-0001](./0001-concorrencia-do-bot.md) que troca
worker-por-Aluno por estado-por-conversa. O ADR-0001 decidiu *que* o estado é por
conversa, e este fixa as quatro decisões que isso cobra: onde o estado mora, como
expira, por qual chave ele é isolado e como a ordem é garantida.

## Por que a chave é o `chat_id`, e não o `from.id`

`chat_id` é a conversa; `from.id` é a pessoa. São a mesma coisa numa conversa
particular, e não são num grupo — duas pessoas no mesmo grupo compartilham o
`chat_id` e, com ele, o histórico.

Escolher `from.id` seria mais preciso no grupo e seria **um estado por Aluno**, que
é a escolha que o ADR-0001 já recusou: worker e memória por pessoa custam caro
para a maioria dos Alunos que fica ociosa a maior parte da noite, e o recurso que
precisa ser protegido é o da conversa, não o da pessoa. No plantão da madrugada,
que é conversa particular, a diferença não aparece; ela aparece no grupo, e é o
limite conhecido desta chave.

O que fica gravado é o texto que o Aluno mandou, e não o `from.id` junto. Num
grupo, o S.A.U. conversa com a turma e não com uma pessoa — que é o comportamento
esperado de um bot de apoio de turma, e é o que a chave dá de graça.

## Por que um arquivo, e não memória

A memória do processo morre no `docker compose down`, no `restart`, e num
deploy. Um Aluno que pergunta "e o prazo da outra?" e volta a perguntar amanhã
receberia do S.A.U. o mesmo tratamento de quem nunca falou com ele — e isso é o
defeito que a #9 existe para fechar, na forma mais visível para quem usa.

O que força o estado a sobreviver ao processo é o critério de aceitação da própria
issue: reinício não pode apagar a conversa. Nenhuma estrutura em memória passa
nisso, e por isso a escolha é `sqlite3` do stdlib — sem dependência nova, sem
serviço novo, e um arquivo que o Docker controla por volume nomeado.

O `sqlite3` do stdlib foi escolhido **sobre** um ORM e **sobre** um servidor de
banco porque não há nada a consultar: o registro é lido inteiro e gravado por
chave, num volume de uma máquina só, por um processo só. Um Postgres aqui seria
uma dependência para operar, um serviço para derrubar e um acesso de rede para
autenticar, em troca de nada.

## Por que o TTL, e por que trinta minutos

O histórico de um Aluno é **dado guardado por um bot de faculdade**. A pergunta
não é só se o arquivo cresce; é se o S.A.U. tem direito de lembrar para sempre o
que alguém perguntou às 3h da manhã. A resposta é que não, e o TTL é como isso se
vira código em vez de promessa.

Trinta minutos é a escala do produto: uma pausa de trinta minutos entre duas
perguntas é conversa nova, não a mesma conversa retomada. Passado o prazo, a
próxima mensagem do Aluno começa do zero, sem que ele perceba — e é o que o
`CONVERSA_TTL_MINUTOS` controla, para quem achar o prazo errado.

A limpeza é **oportunista**: acontece quando um turno chega, varrendo o que está
vencido, e não num cron. Duas razões. A primeira é o ADR-0001, que rejeita
mecanismo externo para o estado. A segunda é mais prática: varrer no caminho do
turno prende o custo da limpeza à taxa real de uso — um bot que ninguém usa não
gasta nada varrendo nada. O índice em `ultimo_turno` é o que faz a varredura
barata; a lista de `chat_id` vencidos sai em uma consulta só.

## Por que a ordem é por conversa, e não global

A ordem global foi descartada por ser pior que não ter ordem nenhuma: com o
recurso escasso do ADR-0001 (a inferência) e o plantão da madrugada, serializar
todos os Alunos faria a fila de um Aluno atrasar a de outro, e ninguém tem motivo
para esperar na fila de quem não é ele.

A garantia é só dentro da conversa, e ela sai de uma fila de **senha** com um
`threading.Condition` por `chat_id`. Um `Lock` serializa sem ordem — quem acorda
primeiro entra primeiro, o que não é FIFO. Um `Event` é pior aqui: ele acorda
*todos* os que estão esperando, e dois turnos do mesmo Aluno rodariam juntos, que
é exatamente o defeito que a issue fecha.

Três detalhes que só aparecem quando a fila é testada de verdade:

- **A contagem de quem espera desce antes de o turno começar.** Contar o turno em
  andamento faria o teto estourar com um Aluno só mandando mensagem seguida, e o
  teto é da fila de espera.
- **O teto é alarme, não válvula.** Passar dele não recusa nada e vai para o log
  com quantos estão esperando. Recusar aqui seria pior do que esperar: o acuse
  já saiu no request, e o Aluno leria "recebi sua mensagem" e não veria resposta
  nenhuma. Quem recusa e quem comunica a posição é a #11, com o semáforo.
- **Conversa expirada e registro fechado acordam quem espera.** Sem isso, um turno
  já na fila ficaria esperando uma senha que ninguém vai mais servir, e essa
  espera não tem teto de tempo — um `docker compose down` com turno na fila
  deixaria a thread presa para sempre.

## O grafo não faz I/O

O `registrar` é chamado pelo `webhook`, nunca pelo grafo. Quem sabe qual é a
conversa é o `chat_id` do update, e o `EstadoTurno` sabe do histórico apenas o que
o `webhook` já entregou a ele.

Essa separação é o que mantém a troca da persona (#10) como troca de texto: o
grafo recebe o histórico pronto e devolve a resposta, sem saber de onde veio. Um
grafo que gravasse por conta própria puxaria para dentro de si a chave do
`chat_id`, que é do canal.

A mensagem do Aluno é gravada **antes** do grafo rodar, e a resposta — inclusive
a de falha — **depois**. A conversa não pode divergir do que o Aluno viu: se a
falha ficasse de fora, o turno seguinte mostraria ao modelo uma conversa que
saltou da pergunta do Aluno direto para uma resposta sem pergunta nenhuma, que é
a forma mais barata de fabricar Alucinação.

## Considered Options

- **Estado em memória, sem arquivo.** Rejeitado: morre no `docker compose down`,
  e o critério "reinício não apaga a conversa" é da própria issue. É a opção mais
  simples de implementar e a que entrega menos.
- **Estado por `from.id`.** Rejeitado: é estado por pessoa, que é a escolha que o
  ADR-0001 já recusou, e em grupo faria a conversa de um Aluno desaparecer do meio
  do histórico de outro. Ver a seção acima.
- **Ordem global, uma fila para todos os Alunos.** Rejeitado: faria a fila de um
  Aluno atrasar a de outro por causa de um terceiro. O ADR-0001 já diz que a ordem
  é preservada por conversa, não globalmente.
- **Uma fila só, com `Event`.** Rejeitado: `Event` acorda todos os que estão
  esperando, e dois turnos do mesmo Aluno rodariam juntos. É a variante que
  parece certa e produz exatamente o defeito que a issue fecha.
- **Um `Lock` por `chat_id`, sem ordem.** Rejeitado: serializa, mas não garante
  FIFO — quem acorda primeiro entra primeiro.
- **Redis, para o estado e para a fila.** Rejeitado por ora: o ADR-0001 já
  descarta broker externo enquanto o bot roda em uma instância só, e o gargalo é o
  semáforo da #11, não o armazenamento. Reavaliar se o bot rodar em mais de uma
  instância — e aí não é só trocar o banco: a fila em memória também precisa
  atravessar processos.
- **Cron de limpeza do TTL.** Rejeitado: prende a limpeza a um relógio que roda
  mesmo com o bot parado, e o ADR-0001 recusa mecanismo externo para o estado.
  Varrer no caminho do turno prende o custo à taxa real de uso.
- **Apagar as mensagens antigas a cada insert, em vez de recortar na leitura.**
  Rejeitado: seria uma escrita extra por turno, e o que o teto de mensagens quer é
  que a *leitura* nunca carregue conversa demais. O arquivo guarda tudo até o TTL,
  que é quem apaga de verdade.

## Consequences

- **O histórico é dado pessoal, e o TTL é obrigação, não otimização.** Quem
  escreve neste arquivo herda a obrigação: a conversa de um Aluno não é conteúdo
  do S.A.U., e o prazo de 30 minutos é o prazo que o produto se compromete a
  respeitar. Apagar o arquivo é legítimo e esperado; guardá-lo é que precisa de
  justificativa.
- **`docker compose down` não apaga a conversa; `down -v` apaga.** É o
  comportamento de volume nomeado, e ele é desejado: o reinício é justamente o
  caso que a issue pede para sobreviver.
- **O teto de 40 mensagens é do arquivo, e não do prompt.** O prompt recebe um
  recorte bem menor, porque a janela do cliente é apertada: a persona, a pergunta
  do Aluno e o histórico disputam o mesmo `num_ctx`. Dois tetos porque são duas
  perguntas: quanto o arquivo guarda sem crescer, e quanto cabe na janela do
  modelo.
- **A ordem é garantida dentro do processo, e não entre instâncias.** Quem
  replicar o `webhook` precisa de um estado compartilhado, e a fila em memória
  deixa de valer junto. Isso é o ponto de reavaliação do ADR-0001, e ele não muda
  com esta decisão: só fica mais perto.
- **O registro é uma costura, não um casamento.** São quatro métodos
  (`conversa`, `historico`, `registrar`, `expirar`), e é o `webhook` que os chama,
  nunca o grafo. Se o arquivo virar PostgreSQL, reescreve-se `RegistroDeConversas`
  e nada acima dela muda.
- **A varredura do TTL acontece quando alguém escreve.** Num bot parado, um
  registro sem uso não gasta nada — e também não expira ninguém, porque não há
  ninguém esperando que expire.
