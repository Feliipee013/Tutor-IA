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
- **Gráficos híbridos exigem atenção na medição.** A máquina da decisão tem Intel UHD e NVIDIA. Com CUDA presente o Ollama deveria pegar a NVIDIA, mas para garantir que a #3 meça a placa certa e não a integrada, a medição fixa `OLLAMA_VISIBLE_DEVICES`.
- **As medidas que os ADRs pressupõem passam a ser possíveis.** A velocidade comparada entre candidatos na #3 e o `k` do semáforo do ADR-0001 exigem inferência em GPU para ter significado; medidos em CPU os dois números saem sem utilidade. Com o Ollama no host, medir exige apenas lembrar de medir na máquina certa.
- **O teto de hardware é conhecido e entra no escopo da 1.1.** A máquina da decisão tem 4 GB de VRAM e 7,5 GiB de RAM. Isso exclui a família 7B em quantização 4 bits e amarra a escolha da #3 à família 3B. A #3 registra esse teto junto com a medição, para que a restrição de hardware não apareça depois como surpresa.
- **O compose para de ter o Ollama como serviço, então o healthcheck entre eles muda de natureza:** passa a ser o bot verificando um host, e não um serviço esperando outro no mesmo `depends_on`.
