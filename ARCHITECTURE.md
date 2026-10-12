# Arquitetura do Tutor-IA (S.A.U.)

> Visão geral de longo prazo. Só muda quando algo estrutural ocorre.

## Visão geral

O S.A.U. (Sistema de Apoio Unopar) atende, pelo Telegram,
as dúvidas recorrentes do Aluno sobre o processo de Estágio:
prazos, documentação, Termo de Compromisso e Contrato,
Seguro de Acidentes Pessoais e a ordem das etapas.
Orienta o processo, não o conteúdo: descreve qual documento existe,
quem assina e em que etapa, mas não emite parecer autoritativo nem substitui a Coordenação de Estágios.
Quando não tem a informação, diz que não sabe e encaminha, nunca inventa.

O Aluno conversa pelo Telegram.
O S.A.U. confirma o recebimento de cada mensagem antes de qualquer inferência.
Para responder, ele monta o prompt — persona, histórico da conversa e a mensagem —,
busca no material autorado os trechos que sustentam a resposta e consulta o modelo local.
Toda afirmação factual cita a Fonte;
quando nada a sustenta, o S.A.U. não responde: diz que não encontrou e encaminha.

Três forças explicam o desenho:

1. Fidelidade ao processo. A resposta vem de um material autorado, com Fonte conferível.
   O defeito central é a Alucinação, e a mitigação é _grounding_, não confiança no modelo.
2. Escassez de inferência. O modelo roda local em GPU de pouca VRAM e atende poucas gerações ao mesmo tempo.
   O atendimento é 24/7 e confirma o recebimento antes de qualquer inferência.
3. Orientação, não parecer. Onde a decisão depende da coordenação, a resposta é o Encaminhamento,
   um encerramento de conversa, não um fluxo com estado.

## Mapa do código

### Serviços

O `compose` sobe dois serviços com a mesma imagem, independentes:

- `bot` (`sau/main.py`): checagem de pré-requisitos e _health server_.
  Roda a checagem na subida e falha alto se o Ollama ou a GPU não estiverem prontos.
- `webhook` (`sau/telegram/webhook.py`): canal do Telegram.
  Recebe o _update_, confere o `secret_token`,
  manda um aviso de recebimento fixo e dispara o turno em segundo plano.

**Invariantes:** o `bot` falha alto quando a alocação não confere;
o `webhook` não roda essa checagem de propósito —
ele precisa avisar o Aluno mesmo com o modelo fora,
e vira a falha em mensagem amigável, nunca um 5xx que faria o Telegram reentregar o _update_.

### O turno

O turno roda num grafo LangGraph (`sau/graph/`).
`sau/persona.py` é o prompt versionado: regras de comportamento e a montagem do prompt do turno.
`sau/graph/state.py` guarda a conversa: histórico isolado por `chat_id`,
com expiração por inatividade e ordem das mensagens dentro da conversa.

**Invariantes:** quem lê e grava a conversa é o canal, e o grafo recebe o histórico pronto.
As regras de comportamento moram só em `sau/persona.py`.
O hash do prompt descreve a persona e não o grafo,
então o Encaminhamento determinístico do grafo fica fora da persona.
A persona abre o prompt, sempre com o mesmo texto,
para que o Ollama reaproveite o cache do início do prompt entre chamadas.

### Conhecimento

O material de referência é autorado e versionado, e quebrado em unidades recuperáveis.
A recuperação (`sau/rag/`) transforma as unidades e a pergunta em vetores, com o Ollama,
e devolve os trechos mais próximos, com a Fonte do trecho.

**Invariantes:** a resposta factual se ancora no material recuperado, nunca no conhecimento do modelo.
Toda afirmação factual cita a Fonte, e a Fonte aponta para uma unidade que existe no material.
Sem trecho que sustente, o S.A.U. não responde: diz que não encontrou e encaminha.

### Inferência e concorrência

`sau/inference/ollama.py` é o cliente do modelo; `sau/inference/semaphore.py` é a fila de vagas em frente à inferência,
com teto e posição comunicada ao Aluno.
`sau/prereqs.py` confere conectividade, modelo e alocação em GPU.

**Invariantes:** o cliente de produção não trava amostragem — só o _test harness_ mede com condições fixas.
O semáforo é adquirido dentro da fila da conversa, o que torna
"um Aluno nunca tem dois turnos processados ao mesmo tempo" estrutural;
a ordem dos travamentos é sempre conversa → semáforo, e é por isso que não há _deadlock_.

### Configuração

`sau/config.py` lê tudo do ambiente para um _dataclass_ `Configuracao`.
O `.env` é lido pelo `compose`, não pelo Python.

### Régua

`harness/` roda as Perguntas-teste (`perguntas-teste/`) e os Casos de alucinação pelo caminho real do turno,
e grava o output bruto com as condições da medição em `outputs/`.

**Invariantes:** o julgamento é humano; o código só conta.
A régua não importa nada de `sau/`, porque régua que conhece o pacote deixa de ser régua.
Toda afirmação numérica carrega as condições (modelo, alocação, hash do prompt) no próprio artefato.

### Governança

`docs/adr/` são as decisões, com o que foi descartado;
`docs/estrutura.md` é o mapa de pastas; `docs/agents/` fixa os contratos de tracker, labels, domínio e PR.
Os agentes e skills do fluxo vivem em `.opencode/` e `.agents/`.

**Invariantes:** um ticket, uma branch, uma PR, com code-review antes do merge.
Nenhuma implementação vira código sem aprovação do plano.

## Fora de escopo

- Parecer autoritativo sobre o que o termo, o contrato ou a lei exigem.
  Isso é Encaminhamento.
- Substituir a Coordenação de Estágios como quem dá a orientação final.
- Inferência em serviço remoto.

## Ver também

- `CONTEXT.md` para o glossário e as regras de domínio.
- `docs/estrutura.md` para o mapa de pastas.
- `docs/adr/` para as decisões e as alternativas descartadas.
- `README.md` e `SETUP.md` para execução, variáveis de ambiente e pré-requisitos.
