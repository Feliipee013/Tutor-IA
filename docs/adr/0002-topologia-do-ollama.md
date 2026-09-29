# Topologia do Ollama: serviço no host, bot em container

---
status: accepted
---

O Ollama roda **nativo no host**, fora do Docker, com o driver e a GPU da máquina diretamente disponíveis. Só o serviço do bot vai em container. O bot alcança a API do Ollama em `http://host.docker.internal:11434`; no Linux isso exige `extra_hosts: ["host.docker.internal:host-gateway"]` no serviço do bot, porque o alias não é automático fora do Docker Desktop. O compose deixa de publicar a porta 11434, que não é mais um serviço dele. O modelo vive em `~/.ollama` no host, não em volume.

A razão é o comportamento de falha. Em container, a GPU depende do NVIDIA Container Toolkit instalado na máquina, e quando ele falta o Ollama **não falha**: ele serve o mesmo modelo em CPU, o compose sobe normal e todo critério de aceite passa. O defeito fica invisível até alguém medir a velocidade e desconfiar do número. No host esse modo de falha não existe: ou o Ollama está rodando e usando a GPU, ou não está rodando.

## Considered Options

- **Ollama em container com GPU passthrough.** Descartado: exige NVIDIA Container Toolkit em cada máquina do time, e a ausência dele degrada para CPU sem erro, transforming um pré-requisito invisível em armadilha. Verificado nesta máquina durante a decisão: driver presente e funcionando (`nvidia-smi` responde), `nvidia-ctk` ausente, sem `/etc/docker/daemon.json` — ou seja, hoje nenhum container alcançaria a GPU, e o stack subiria parecendo saudável.
- **Compose com override de GPU** (`docker-compose.yml` sobe o Ollama sempre; `docker-compose.override.yml` adiciona o device). Descartado por ora: resolve o caso do time misto, teammates com e sem NVIDIA, mas adiciona um arquivo e um conceito a mais. A escolha do host já é portátil sem nenhuma configuração condicional — quem não tem NVIDIA instala o Ollama no host e ele roda em CPU, sem mudar nada no compose. Reavaliar se aparecer a demanda por um `docker compose up` único como pré-requisito de fluxo do time.
- **Inferência em serviço remoto.** Descartado: contraria a restrição do projeto de não depender de serviço externo para inferência, e a 1.2 assume o mesmo Ollama servindo o modelo de embedding.

## Consequences

- **A GPU do host passa a estar disponível sem configuração de container.** A verificação é `nvidia-smi` no host, antes de qualquer coisa do compose.
- **`docker compose up` deixa de bastar sozinho.** O Ollama precisa estar rodando no host antes. Isso **reintroduz um passo manual** que a issue #4 existia para eliminar, e é a dívida real desta decisão: o ticket passa a ter duas metades, o que ele faz e a documentação do passo que sobrou. O que impede que isso vire um segundo modo de falha silencioso é a checagem de pré-requisito do serviço do bot, que precisa **falhar alto**.
- **A checagem de pré-requisito tem que olhar a VRAM, não só a resposta.** Um `GET /api/version` bem-sucedido não prova GPU: prova que algo responde em 11434, e uma queda para CPU satisfaz isso. A verificação precisa confrontar o que o Ollama reporta com o que a máquina tem, ou o defeito que este ADR existe para fechar reabre pela porta dos fundos.
- **O modelo não precisa de volume.** "Sobreviver a um down e up" deixa de ser critério de persistência e passa a ser consequência natural de `~/.ollama` no host.
- **Gráficos híbridos exigem atenção na medição.** A máquina da decisão tem Intel UHD e NVIDIA. Com CUDA presente o Ollama deveria pegar a NVIDIA, mas para garantir que a #3 meça a placa certa e não a integrada, a medição fixa `CUDA_VISIBLE_DEVICES` — que é o nome real da variável no Ollama (`envconfig/config.go`), corrigido aqui porque este ADR citava `OLLAMA_VISIBLE_DEVICES`, que não existe. O valor recomendado é o **UUID** da placa, que `nvidia-smi -L` imprime, e não o índice numérico, porque a ordem dos devices pode variar. A variável **não é a verificação**: ela só restringe o que o Ollama pode enxergar, e uma variável mal formatada é ignorada em silêncio. O que prova a placa em uso é `ollama ps`, na coluna PROCESSOR.
- **As medidas que os ADRs pressupõem passam a ser possíveis.** A velocidade comparada entre candidatos na #3 e o `k` do semáforo do ADR-0001 exigem inferência em GPU para ter significado; medidos em CPU os dois números saem sem utilidade. Com o Ollama no host, medir exige apenas lembrar de medir na máquina certa.
- **O teto de hardware é conhecido e entra no escopo da 1.1.** A máquina da decisão tem 4 GB de VRAM e 7,5 GiB de RAM. Isso exclui a família 7B em quantização 4 bits e amarra a escolha da #3 à família 3B. A #3 registra esse teto junto com a medição, para que a restrição de hardware não apareça depois como surpresa.
- **O compose para de ter o Ollama como serviço, então o healthcheck entre eles muda de natureza:** passa a ser o bot verificando um host, e não um serviço esperando outro no mesmo `depends_on`.
- **Consequência que só apareceu na implementação: o `OLLAMA_HOST` precisa ser `0.0.0.0`.** O bind padrão do Ollama é `127.0.0.1:11434`, e o container chega no IP da bridge do Docker, que não é o loopback do host. Um serviço que escuta só no loopback é inalcançável de fora do host, então o passo manual que este ADR já reconhecia como dívida tem uma condição a mais: sem `OLLAMA_HOST=0.0.0.0:11434` o bot nem chega à checagem de pré-requisito, morre com `Errno 111: Connection refused`. O preço é o oposto do desejado: a porta 11434 passa a responder em todas as interfaces da rede, não só na localhost. A alternativa seria bind restrito e um caminho que não passe por rede, o que o Compose só oferece com `network_mode: host` — que abriria mão do isolamento que o container dá. A escolha é documentar a exposição e tratá-la como decisão de rede da máquina, não do bot.

## Emenda (issue #5, 2026-09-28): o `webhook` também vai em container

A issue #5 adicionou um segundo serviço em container, o `webhook`, e a frase "só
o serviço do bot vai em container" do texto acima deixou de ser verdade. A emenda
é **aditiva**: a decisão deste ADR continua `accepted` e continua valendo sem
alteração. O que muda é o número de serviços em container, de um para dois — `bot`
e `webhook`, independentes entre si.

Isso **não é um conflito de decisão**, e a distinção importa. O que este ADR
decidiu foi onde o Ollama roda, e ele continua no host, pelos mesmos motivos: a
GPU, o modo de falha silencioso em CPU e o `OLLAMA_HOST=0.0.0.0` valem igual. O
serviço `webhook` não toca na GPU nem no Ollama — ele existe para provar o fio do
canal (webhook, serialização, roteamento de chat, acuse de recibo) sem depender
do modelo, e é justamente por não depender dele que ele sobe numa máquina sem
GPU. Colocá-lo no host junto com o Ollama o acoplaria ao passo manual que as
"Consequences" já registram como dívida.

O efeito colateral de projeto é o que a emenda deixa registrado: `docker compose
up` sem argumentos sobe dois serviços, e o `webhook` falha alto sem as duas
credenciais do Telegram. Quem subir o compose esperando um serviço só vai ver o
`webhook` morrer na largada — e a mensagem de falha é explícita sobre o motivo,
que é o comportamento que o serviço promete.

Quando a #7 criar o cliente do Ollama, ele vai no serviço `bot` e alcança
`http://host.docker.internal:11434` como este ADR descreve. Se algum dia ele for
posto no `webhook`, isso reabre a decisão e não é uma conveniência de
implementação.

## Emenda (issue #8, 2026-09-29): o turno roda no serviço `webhook`

A #8 põe o turno no serviço `webhook` — o grafo LangGraph e a chamada ao modelo
saem de lá, e não do `bot`. Isso é o que a emenda anterior previu como "reabre a
decisão", e a emenda é o registro de que ela foi reaberta e resolvida.

A emenda continua **aditiva**: o status deste ADR segue `accepted` e a decisão de
onde o Ollama roda não muda. O modelo continua **nativo no host**, com a GPU da
máquina e o `OLLAMA_HOST=0.0.0.0:11434` que a decisão original exige. O que muda é
**qual serviço o alcança**: o `webhook` passou a alcançar
`http://host.docker.internal:11434` pelo mesmo `extra_hosts` do `bot`, e a frase
"só o serviço do bot vai em container" do texto original deixa de valer para o
acesso ao modelo.

A frase que a emenda da #5 deixou como condição — "se algum dia ele for posto no
`webhook`, isso reabre a decisão" — é lida aqui como o que era: uma advertência,
não um veto. O que a decisão original protege é a **GPU**: que o modelo não caia
para CPU em silêncio, e que ninguém confundisse o `bot` inferindo em container com
o modelo rodando em container. Nenhum dos dois se altera por um container a mais
alcançar o host.

**O que não muda:** Ollama nativo no host; GPU da máquina; `OLLAMA_HOST=0.0.0.0`;
o modelo em `~/.ollama` e não em volume; a porta 11434 fora do compose.

**O que muda, e é a consequência que importa:**

- **O `webhook` continua subindo sem o Ollama, e é o turno que passa a depender
  dele.** A emenda da #5 dizia que o serviço "sobe numa máquina sem GPU" por não
  tocar no modelo, e isso segue verdade: ele não roda a checagem de pré-requisito,
  não checa VRAM e não falha alto quando o Ollama está fora — é o que permite
  acusejar Aluno com o modelo caído, devolvendo a mensagem amigável em vez de um
  5xx. O que muda é o **turno**: ele passa a depender do Ollama do mesmo jeito
  que a geração do `bot` depende. Subir é barato; responder não é.
- **A `OLLAMA_ALLOW_CPU` e a `VRAM_TOTAL_MIB` continuam fora do `webhook`.** São
  variáveis da checagem de pré-requisito, e a checagem é do `bot`. A degradação
  silenciosa para CPU que este ADR existe para fechar é um problema do serviço
  que **mede**; o `webhook` não mede tempo, e quem mede é `docs/medicao-modelo`.
  A alternativa seria estender a checagem ao `webhook`, e aí o canal do Telegram
  passaria a exigir GPU para acusejar Aluno — o oposto do que a #5 comprou ao
  separá-lo do `bot`.
- **A thread por turno é dívida assumida.** O `webhook` dispara uma thread por
  turno para que o acuse não espere o modelo. A fila e o semáforo são da #11, e é
  a #11 que substitui a thread. Até lá, dois turnos simultâneos para o mesmo
  Aluno rodam em paralelo, sem ordem entre eles.

O serviço `bot` segue dono da checagem de pré-requisito e do health server, e a
divisão entre os dois serviços é a mesma que a emenda da #5%: o `bot` é o serviço
de inferência e medição, o `webhook` é o canal do Telegram. O que a #8 acrescenta é
que o canal também fala com o modelo.
