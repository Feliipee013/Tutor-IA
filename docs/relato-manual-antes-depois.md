# Relato: antes sem híbrido × depois no híbrido (bateria do Manual)

O comparativo do lado "antes" já documentado (b1–b10 sem busca híbrida) com o
lado "depois" rodado no pipeline atual (busca híbrida padrão), no recorte de
20 Perguntas-teste (b1–b10 + x1–x5 + n1–n5), com pergunta feita + resposta
obtida + análise por caso — e a página de uma folha justificando chunking e
armazenamento, com limitações declaradas. Issue #37, spec #34.

**Divergência declarada do aceite original.** O aceite pedia "os mesmos 20
casos nos dois pipelines". O comparativo real é outro: o antes cobre só as 10
básicas (b1–b10, sem híbrido, limiar 0.72) e o depois cobre as 10 básicas mais
10 novas (x1–x5 e n1–n5, com híbrido, limiar 0.55). Só as `b` são comparáveis
pergunta a pergunta; as `x`/`n` entram como estreia do híbrido. Os limiares
também diferem (0.72 no antes, 0.55 no depois). Isto é uma evolução observada,
não um experimento controlado — e é como deve ser lido.

**Amostra única, por decisão.** O depois roda **1 repetição por pergunta** (20
execuções), como no antes — decisão do usuário na #37, com exceção explícita
ao ADR-0003 (que proíbe execução única porque o `qwen2.5:3b` varia entre
repetições). Consequência: não há leitura de estabilidade (a coluna
"comportamento" sai trivialmente estável) e cada número registra uma das
respostas possíveis, não o comportamento típico.

**Como ler os vereditos.** O julgamento do depois foi redigido pelo agente
executor e ratificado por Leonardo Rodrigues (assignee da #37), conforme a
emenda do ADR-0006. A régua é aplicada à letra: todo bloco `b`/`x` exige a
citação da Fonte (título + página) no `conforme quando`, então resposta sem
citação é `não conforme` mesmo com o conteúdo correto. A análise de cada caso
separa as duas coisas — conteúdo ancorado de um lado, citação de outro — como
o antes já fazia (9/10 ancoradas, 0/10 com citação completa).

## Condições dos dois lados

| Condição | Antes (reuso, sem re-rodar) | Depois (rodada desta issue) |
| --- | --- | --- |
| Perguntas | b1–b10 de `perguntas-teste/bateria-manual.md` | b1–b10 + x1–x5 + n1–n5 (20) |
| Recuperação | sem híbrido (só vetorial), k=4, limiar 0.72 | híbrida padrão (`buscar_hibrida_no_indice`), k=4, limiar 0.55 |
| Gerador e travas | qwen2.5:3b, temperature 0, seed 20260926, num_predict 512, num_ctx 4096 | os mesmos |
| Índice | Chroma `manual-estagio-obrigatorio`, 57 chunks | o mesmo (PDF sha256 `1832780d…be19ffefa9`, 57 chunks, `nomic-embed-text`) |
| Caminho | `executar_turno` real, histórico vazio | o mesmo (grafo por turno, histórico vazio) |
| Repetições | 1 por pergunta, julgamento humano lendo o PDF | 1 por pergunta (20 execuções) |
| Prompt | persona anterior | persona atual (sha256 `9d68c6dc…f69b1`, conferido: o da rodada é o do código) |
| Julgamento | pessoa lendo o Manual em PDF | agente redigiu, Leonardo Rodrigues ratificou |
| Data | 2026-10-14 | 2026-10-15 |
| Máquina | GPU (ver `docs/bateria-basica-b1-b10-sau.md`) | GPU, `size_vram` 2159374499, `em_cpu: false` |

O antes vive em `docs/bateria-basica-b1-b10-sau.md`. O depois vive em
`outputs/baseline-manual-hibrido.json` (rodada),
`outputs/baseline-manual-hibrido.julgamento.json` (folha, 35 vereditos) e
`outputs/baseline-manual-hibrido.metricas.json` (taxas).

## Agregado

**Antes (b1–b10, 1 execução cada):** 9/10 respostas ancoradas no Manual, 0/10
com citação título+página completa (só b9 cita "página 16", sem título). A
única com conteúdo não conforme é a b8, com a regra invertida (atribui o "não
consta / não precisa" aos 6 cursos, quando o Manual o atribui aos demais
cursos).

**Depois (20 perguntas × 1 repetição = 20 execuções, 0 erros, 0 cortadas):**

| Métrica | Por execução | Por pergunta |
| --- | --- | --- |
| Acerto (b/x) | 0/15 = 0,00 | 0/15 perguntas = 0,00 |
| Citação correta (b/x) | 0/15 = 0,00 | 0/15 perguntas = 0,00 |
| "Não sei" correto (n) | 4/5 = 0,80 | 4/5 perguntas = 0,80 |

Nenhuma das 15 respostas de `b`/`x` traz a Fonte título+página: a conferência
mecânica marca 14 como parciais (fragmento do título, sem `(p. N)`) e 1 como
ausente (b7). O veredito humano confirma: citação 0/15. E como a régua
exige a citação também no acerto, o acerto vai a 0/15 junto.

**A leitura que o número sozinho esconde.** Pela letra da régua, o depois
zerou; pelo conteúdo, não. Núcleo correto em: b1, b3 (sem dado de captura),
b4, b6 (núcleo), b7, b8 (a regra saiu **no sentido certo** — a inversão do
antes foi corrigida), b10 (núcleo, nomeando a Lei) e x5 (conteúdo + envio).
Conteúdo errado ou incompleto no ponto que a régua cobra em: b2 (generaliza
"até 7 dias úteis" — o antes listava os 7 valores certos), b5 (resume "IES
(faculdade)" e perde o Time de Convênios), b8 no extra (acrescenta passos de
cadastro não pedidos), b9 (omite a regra de cadastro prévio), x1 (nega o
Acadêmico em Enfermagem), x2 (omite o vínculo validado, teto de horas errado),
x3 (omite os 7+7 dias — a p.4 nem foi recuperada), x4 (confunde reedição com
alteração). Nas `n`, 4/5 conferem; a n4 responde sem o literal que a régua
exige.

**Antes × depois, só nas `b`:** o conteúdo continua ancorado na maioria dos
casos e a citação continua ausente em todos — o defeito que o antes apontava
("ORIENTACAO_DE_FONTE não virou citação visível") segue aberto no depois. O
que mudou de verdade: b8 acertou a regra que o antes invertia, e b2
piorou (o antes acertava os 7 prazos) e b9 piorou (o antes ancorava com
citação parcial; o depois desvia para um "prazo" não perguntado). As `x`/`n`
são estreia, sem delta.

## Caso a caso

Resposta literal da única repetição do depois, com a análise.

### b1 — Data limite do período de estágio

**Pergunta feita:** Até quando eu posso realizar o estágio obrigatório neste
semestre? Quem define essa data limite?

**Antes:** ancorada (p.3, time de planejamento + Colaborar), sem citação.

**Resposta obtida (depois):** "O período para realização do estágio
obrigatório neste semestre é definido pelo time de planejamento acadêmico e
está disponível no sistema Colaborar em: Menu > DGA/Secretaria > Estágio >
Período. Para obter a data final, você deve acessar esse menu e verificar a
informação."

**Análise:** conteúdo correto e sem data inventada, como no antes; sem
citação da Fonte. Vereditos: acerto `nao_conforme`, citação `nao_conforme` —
pela ausência da citação que a régua exige. Recuperação trouxe a p.3 em 1º.

### b2 — Prazos de análise no Colaborar

**Pergunta feita:** Quanto tempo o Time de Estágios leva para analisar cada
cadastro que eu faço no Colaborar? Os prazos são em dias úteis?

**Antes:** ancorada, os 7 valores conferindo, sem citação.

**Resposta obtida (depois):** "De acordo com os prazos fornecidos no
material, o Time de Estágios leva até 7 dias úteis para analisar cada cadastro
que você faz no Colaborar. Por favor, observe que esses prazos podem variar
dependendo da situação específica do cadastro, como alterações ou
inconsistências que possam ser necessárias."

**Análise:** regressão contra o antes. O depois generaliza "até 7 dias
úteis" para todo cadastro e omite a tabela (4/5/4/4/5/7/7) — erra prazos por
generalização, que o `não conforme quando` proíbe. Sem citação. Vereditos:
`nao_conforme` nos dois. A p.4 foi recuperada em 1º — o erro foi do
redator, não da busca.

### b3 — Seguro obrigatório e o que cobre

**Pergunta feita:** O estágio obrigatório tem seguro? O que exatamente esse
seguro cobre — e o que ele NÃO cobre?

**Antes:** ancorada (p.5, MA + IPA), sem dado de apólice (correto, máscara),
sem citação.

**Resposta obtida (depois):** "O seguro obrigatório para o estágio oferecido
pela sua instituição cobre duas coberturas principais: 1. **MA - Morte
acidental e IPA - Invalidez Permanente Parcial ou Total por Acidente** [...]
2. **Demais situações não estão contempladas** [...]. Para mais informações
ou dúvidas, recomendo que você entre em contato com a Coordenação de
Estágios."

**Análise:** núcleo MA/IPA + demais-não correto, sem número de
apólice/seguradora/vigência (a máscara segurou); omite a Lei 11.788/08 e não
cita a Fonte. Vereditos: `nao_conforme` nos dois. Os exemplos de
situações não cobertas ("doenças graves", "violência doméstica") são
elaboração do modelo sobre o "demais não contempladas" — não contradizem o
Manual, mas também não vêm dele.

### b4 — Convênio obrigatório na área da Saúde

**Pergunta feita:** Sou de um curso da área da Saúde. Preciso de convênio
para fazer o estágio? O que acontece se não tiver convênio?

**Antes:** ancorada (p.6 + p.7, Prisma/GO), sem citação.

**Resposta obtida (depois):** "Para realizar um estágio na área da Saúde, é
necessário um convênio entre a Instituição de Ensino Superior (IES) e a
empresa. Sem o convênio, os alunos da área da Saúde não podem iniciar o
estágio. [...] Se não tiver convênio, você precisará entrar em contato com a
Coordenação de Estágios para obter mais informações."

**Análise:** núcleo certo (convênio obrigatório, sem ele não inicia) e
Encaminhamento sem sugerir Cadastro de Empresa para a Saúde; sem citação.
Vereditos: `nao_conforme` nos dois — só pela citação.

### b5 — Convênio × Cadastro de Empresa

**Pergunta feita:** Qual é a diferença entre convênio e cadastro de empresa?
Quem faz cada um — eu, o Polo ou a faculdade?

**Antes:** ancorada com extra correto de p.11, com eco "Aluno:" (defeito de
forma), sem citação.

**Resposta obtida (depois):** distingue Convênio (Saúde, IES) de Cadastro de
Empresa (fora da Saúde, Polo no Colaborar); resume quem faz como "o Polo faz
o cadastro de empresa [...] enquanto a IES (faculdade) faz o cadastro do
convênio".

**Análise:** perde o Time de Convênios (Regulação e Controle) + via chamado
+ não-fazer-sozinho, que a régua cobra; o eco "Aluno:" sumiu. Sem citação.
Vereditos: `nao_conforme` nos dois.

### b6 — Cadastrar empresa no Colaborar

**Pergunta feita:** Como eu cadastro a empresa concedente no Colaborar? Qual
o caminho e o que eu preciso conferir antes?

**Antes:** ancorada (p.8 + p.9 + p.7), sem citação.

**Resposta obtida (depois):** caminho Menu > DGA/Secretaria > Estágio >
Registro de Empresas, consulta por Ctrl + F / "CNPJ", reedição com os
motivos, Prisma/GO no fecho — e "siga os passos descritos na página 8 do
manual".

**Análise:** núcleo correto, com o extra de reedição; falta o
"Novo Cadastro" explícito que a régua cobra, e "página 8 do manual"
é citação parcial (página sem título — a mecânica marca parcial). Vereditos:
`nao_conforme` nos dois.

### b7 — Razão social da empresa

**Pergunta feita:** No cadastro da empresa, o que eu coloco no campo da razão
social? Tem um jeito certo de preencher?

**Antes:** ancorada, curta e fiel (p.10), sem citação.

**Resposta obtida (depois):** "você deve informar a razão social da Receita
Federal, seguida pelo nome da fantasia da empresa. Por exemplo, se o estágio
for realizado na Escola João e Maria (Ensino Fundamental) [...]" + reedição
+ CNPJ.

**Análise:** conteúdo correto e completo; zero menção a Fonte
(a mecânica marca ausente). Vereditos: `nao_conforme` nos dois — só pela
citação.

### b8 — Supervisor Acadêmico

**Pergunta feita:** Quem é o Supervisor Acadêmico e quando eu preciso
cadastrar ele? Vale para o meu curso?

**Antes:** a única b com conteúdo não conforme — regra invertida (o "não
consta / não precisa" atribuído aos 6 cursos).

**Resposta obtida (depois):** "O Supervisor Acadêmico é o representante
da Instituição de Ensino Superior (IES) responsável por acompanhar o estágio.
Para os alunos de "demais cursos", o nome do Supervisor Acadêmico não
constará no termo de compromisso e, portanto, não é necessário informar no
momento da associação. Para os cursos de Biomedicina, Enfermagem, Farmácia,
Fisioterapia, Nutrição e Serviço Social, antes de associar o aluno, é
necessário cadastrar o Supervisor Acadêmico no sistema colaborar. Em alguns
casos, é necessário vinculá-lo à empresa." + passos de cadastro.

**Análise:** a inversão do antes foi corrigida — a regra saiu no sentido do
Manual. Sem citação. Vereditos: `nao_conforme` nos dois — só pela citação. A
p.15 foi recuperada em 1º.

### b9 — Supervisor de Campo

**Pergunta feita:** Quem é o Supervisor de Campo e quando ele precisa ser
cadastrado no sistema?

**Antes:** ancorada (p.16 + p.17 + p.18), com citação parcial ("página 16").

**Resposta obtida (depois):** define o papel ("profissional designado pela
empresa..."), dá conselho genérico de cadastro — e encerra: "Quanto ao prazo
para cadastrar o Supervisor de Campo, não encontrei no material sobre esse
ponto. Procure a Coordenação de Estágios."

**Análise:** omite a regra central que a régua cobra (cadastrar antes de
associar nos 6 cursos) e desvia para um "prazo" que ninguém perguntou,
respondendo com o literal de ausência fora de lugar. Sem citação. Vereditos:
`nao_conforme` nos dois — pior que o antes neste caso.

### b10 — Limite de carga horária e Declaração de Dispensa

**Pergunta feita:** Qual é o limite de carga horária do estágio obrigatório?
E como eu envio a Declaração de Dispensa?

**Antes:** núcleo com base (6h/30h, envio, formatos), extra de p.30 parcial,
sem citação.

**Resposta obtida (depois):** "O limite de carga horária do estágio
obrigatório é de 6 horas diárias e 30 horas semanais, conforme estabelecido
pela Lei de Estágio nº 11.788/08." + envio no Colaborar (menu, formatos
PDF/JPG/JPEG/PNG, assinado e legível) + extras de consulta a declarações,
ServiceNow e status.

**Análise:** núcleo correto (a única b a nomear a Lei); o menu sai sem
o "remunerado" do título esperado, e os extras vêm dos chunks recuperados —
procedimento, não invenção solta. Sem citação. Vereditos: `nao_conforme`
nos dois — só pela citação.

### x1 — Enfermagem: convênio e qual supervisor (estreia)

**Pergunta feita:** Sou de Enfermagem. A empresa precisa ter convênio com a
faculdade? E qual supervisor eu preciso cadastrar — o de campo e o acadêmico?

**Resposta obtida (depois):** convênio obrigatório para a Saúde (certo) +
"Não é necessário cadastrar o Supervisor Acadêmico, pois, para os cursos
de Enfermagem, o nome do supervisor acadêmico não constará no termo de
compromisso".

**Análise:** repete a inversão do antes-b8 em Enfermagem (a régua
exige: Acadêmico = Preceptor, com vínculo e convocação; Campo = Enfermeiro
do Serviço, sem vínculo). Sem citação. Vereditos: `nao_conforme` nos dois.
As 3 Fontes certas foram recuperadas (p.6, p.15, p.16) — o erro foi do
redator.

### x2 — Serviço Social: vínculo, empresa e carga horária (estreia)

**Pergunta feita:** Sou de Serviço Social. O supervisor de campo precisa de
vínculo com a empresa? Por que a empresa não aparece para associar? E quantas
horas ele pode ter?

**Resposta obtida (depois):** vínculo necessário (certo) + "A carga
horária deve ser maior que 10 horas" + "1 aluno a cada 10 horas" (Res.
533/08), sem o ponto da empresa invisível sem vínculo validado.

**Análise:** omite o ponto central ("empresa só aparece após o vínculo
realizado e validado") e erra o teto (o certo é **não ultrapassar 30h
semanais**; "maior que 10" é o mínimo do vínculo genérico). Sem citação.
Vereditos: `nao_conforme` nos dois.

### x3 — Prazos de liberação, validação e envio (estreia)

**Pergunta feita:** Quanto tempo o time leva para liberar o Termo de
Compromisso e quanto para validar depois que eu envio? E existe um prazo para
eu enviar a documentação?

**Resposta obtida (depois):** envio pelo Aluno no AVA, 3 folhas em PDF único,
10MB (certo) + "O prazo para enviar a documentação não está especificado no
material" (certo — não inventa) + declara ausência sobre liberação e
validação, com Encaminhamento.

**Análise:** meio certo, meio omisso: acerta o envio e não inventa prazo,
mas declara ausência onde há resposta (liberação 7 + validação 7 dias úteis,
p.4) — e a p.4 de fato não estava entre as Fontes recuperadas. É o caso que
mais mostra o custo de recuperação incompleta em pergunta cruzada. Sem
citação. Vereditos: `nao_conforme` nos dois.

### x4 — Reedição × alteração de responsável (estreia)

**Pergunta feita:** Quando eu mexo no cadastro da empresa, qual a diferença
entre colocar em "reedição" e fazer "alteração de responsável"? Qual eu uso
em cada caso?

**Resposta obtida (depois):** "você não precisa colocar o cadastro do aluno
em reedição" na alteração (certo) + "Já para a reedição [...] você precisa
colocar o cadastro do aluno em reedição, conforme [...] a página 42 do
manual".

**Análise:** usa o título da p.14 ("REEDIÇÃO DE ALTERAÇÃO DE") como se
fosse a reedição de empresa da p.11 e manda o Aluno à reedição — o oposto do
que a régua pede para a alteração; citação parcial ("página 42", sem
título). Vereditos: `nao_conforme` nos dois.

### x5 — Termo modelo Empresa (estreia)

**Pergunta feita:** A empresa quer usar o modelo de Termo de Compromisso
dela. O que ele precisa conter, como eu envio e quem assina?

**Resposta obtida (depois):** conteúdo (Aluno RA/CPF, local,
supervisores + conselho, IES + representante) + assinaturas (Aluno, empresa,
Instituição) certos; envio "por chamado" genérico, após trâmites no sistema
da IES.

**Análise:** o melhor conteúdo das cruzadas; faltam a menção às
cláusulas conforme a Lei 11.788 e os detalhes (vigência/horário, atividades,
locais de assinatura, filtro do chamado). Sem citação. Vereditos:
`nao_conforme` nos dois — por detalhe + citação.

### n1 — Valor da mensalidade e desconto (estreia)

**Pergunta feita:** Quanto é a mensalidade do meu curso e tem desconto para
quem faz estágio?

**Resposta obtida (depois):** "Não encontrei no material informações
específicas sobre a mensalidade do seu curso ou descontos para quem faz
estágio. Procure a Coordenação de Estágios."

**Análise:** literal (com maiúscula de início de frase) + Encaminhamento,
sem valor. Veredito: `conforme`.

### n2 — Contato oficial da Coordenação de Estágios (estreia)

**Pergunta feita:** Qual é o telefone e o e-mail da Coordenação de Estágios?
Preciso falar com alguém de lá.

**Resposta obtida (depois):** "Não encontrei no material informações sobre o
telefone e o e-mail da Coordenação de Estágios. Procure a Coordenação de
Estágios."

**Análise:** literal + Encaminhamento, sem inventar canal — o caso que a
máscara do ADR-0011 existe para proteger. Veredito: `conforme`.

### n3 — Data de entrega do relatório do Aluno (estreia)

**Pergunta feita:** Qual é a data exata de entrega do meu relatório de
atividades? Meu professor falou que tem um dia certo.

**Resposta obtida (depois):** "Não encontrei no material a data exata de
entrega do seu relatório de atividades. Procure a Coordenação de Estágios."

**Análise:** literal + Encaminhamento, sem data. Veredito: `conforme`.

### n4 — Catálogo de cursos e polos (estreia)

**Pergunta feita:** Quais cursos a faculdade oferece no meu polo? Tem o curso
que eu quero?

**Resposta obtida (depois):** "Para responder sua dúvida, preciso que você
forneça mais detalhes sobre o seu polo e o curso [...]. No manual, não há
informações específicas sobre quais cursos a faculdade oferece em cada polo.
Para isso, você deve consultar a Coordenação de Estágios."

**Análise:** não afirma catálogo e Encaminha — mas sem o literal "não
encontrei no material" que a régua exige, e pedindo dado que não resolveria
(a resposta seguiria inexistente). Veredito: `nao_conforme`. É o único
"não sei" que falhou, por forma e não por Alucinação.

### n5 — Dado do seguro: apólice, seguradora e vigência (estreia)

**Pergunta feita:** Qual é o número da apólice do seguro de estágio? E qual é
a seguradora, e até quando a apólice vale?

**Resposta obtida (depois):** "não encontrei no material informações sobre o
número da apólice do seguro de estágio, a seguradora ou até quando a apólice
vale. Procure a Coordenação de Estágios."

**Análise:** literal em caixa baixa + Encaminhamento, sem citar dado
mascarado — a prova de que a máscara antes de indexar funciona de ponta a
ponta (o chunk p.5 recuperado em 1º já vem mascarado). Veredito: `conforme`.

## Página de justificativa: chunking e armazenamento (1 folha)

**Decisão.** Chunking: **1 slide = 1 chunk**, sem sobreposição — título + corpo
nativo + blocos de imagem na ordem de leitura, com a marca `[texto de imagem]`
(`sau/manual/chunks.py:77`, `montar_chunks`). Fonte citável: **título do slide
+ página** (`ChunkManual.fonte`), o que o Aluno confere sozinho no PDF.
Armazenamento: **Chroma persistente, coleção dedicada**
(`manual-estagio-obrigatorio`), carga idempotente pelo `sha256` do PDF no boot
(re-ingere só se o conteúdo mudou), volume nomeado no container
(`sau/manual/indice.py`, `sau/config.py`). Embeddings: `nomic-embed-text`
local via Ollama, vetores L2-normalizados, espaço cosseno. Recuperação:
ferramenta opcional `buscar_no_manual` sobre a **busca híbrida** (BM25 em
memória + RRF para escolher os candidatos, cosseno vetorial para ordenar e
pontuar — ADR-0013), `k = 4`, limiar `0.55`, com busca de segurança
determinística e guarda que troca resposta sem evidência pelo literal "não
encontrei no material" + Encaminhamento (ADR-0010, ADR-0012).

**Por que assim.** O Manual é uma apresentação: cada slide já é uma unidade de
sentido com título próprio, então o limite do chunk é do autor, não heurística
nossa — e a Fonte herda esse limite de graça. Chunks curtos são orçamento, não
estilo: `num_ctx` é 4096 e não é tocado, a persona tem 852 tokens, e cada
trecho custa contexto que a conversa não tem. O híbrido resgata o que o
vetorial puro deixava de fora nas cruzadas (medição `docs/medicao-hibrido/`:
recall 8/13 → 10/13 em x1–x5). Persistência existe para o boot indexar
sozinho e reaproveitar quando o PDF é o mesmo; idempotência por hash impede
duplicar o índice a cada restart. Máscara antes de indexar (apólice, CNPJ,
CPF, matrícula, nomes em tabelas, telefone, e-mail) garante que dado
ilustrativo nunca vire fato citável — b3 e n5 provam o porquê, dos dois lados.

**Descartadas.** Janela fixa de N caracteres com overlap: quebraria slides no
meio e geraria Fontes "página X, pedaço 2", que o Aluno não confere. Índice só
em memória: perderia tudo a cada restart e o boot pagaria embedding sempre.
Vetor externo (pgvector/serviço próprio): infra nova para 57 chunks — custo
sem ganho medido. Trocar embedding ou gerador: sem evidência da bateria; o
`nomic-embed-text` (274 MB) cabe no orçamento de ~1 GB ao lado do gerador
(ADR-0003). OCR com visão ou reranker externo: só entram se a bateria provar
necessidade (spec #34). Recuperação obrigatória todo turno: aposentada —
gerava chamada em saudação e escondia a ausência de evidência (ADR-0010).

**Limites declarados.** Sem tesseract no host, slides em imagem entraram sem
OCR: só o texto nativo foi indexado — reduz o recall absoluto onde o conteúdo
mora em figura, e vale igual para todas as execuções do depois. Tabelas de
p.15–p.16 dependem desse OCR; capturas mascaradas não voltam como fato.
Limiar 0.55 é ponto de partida calibrável pela bateria, não constante
sagrada. A ausência de citação visível (0/15 no depois, como 0/10 no antes) é
o próximo defeito a fechar, não uma qualidade do índice — e há um complicador
medido: no Telegram (temperatura do modelo, seed sorteada a cada chamada) o
redator cita a Fonte, enquanto no harness (`temperature 0`, seed fixa) ele a
omite sistematicamente, com o mesmo código e a mesma persona (`sha256`
conferido). A obediência à `ORIENTACAO_DE_FONTE` é sensível à amostragem, e a
régua do harness mede o pior caso. A b8 do antes saiu com a regra invertida;
o depois a corrigiu — inversão fechada nesta amostra única.

## Ressalva sobre d1–d10 (fora do escopo)

Os blocos d1–d10 seguem no arquivo, intactos, e fora desta rodada por decisão
registrada no plano (o usuário ressalvou que os blocos `d` possivelmente estão
errados e merecem revisão em issue futura). Nada deles foi deletado nem
reescrito aqui. Em particular, as sondas de nomenclatura e ação por curso
(d1–d4) dependem do pareamento do OCR das tabelas de p.15–p.16 — e o depois
mostra que esse pareamento ainda falha no redator (x1, b9) mesmo com
as páginas recuperadas. A revisão dos `d` deve cobrir o `conforme quando` de
cada um contra o Manual antes de qualquer rodada que os inclua.

## Referências e artefatos

- `perguntas-teste/bateria-manual.md` — os 30 blocos e o `conforme quando` de cada um
- `corpus/manual-estagio-obrigatorio-polo-2026-2.pdf` — o Manual (local, fora do git; sha256 `1832780d…be19ffefa9`)
- `outputs/baseline-manual-hibrido.json` — a rodada do depois (20 execuções, evidência bruta + Fontes recuperadas)
- `outputs/baseline-manual-hibrido.julgamento.json` — a folha (35 vereditos, redigida pelo agente, ratificada por Leonardo Rodrigues em 2026-10-15)
- `outputs/baseline-manual-hibrido.metricas.json` — as taxas (acerto 0/15, citação 0/15, "não sei" 4/5, por execução e por pergunta, fora_da_conta vazio, Fonte mecânica por execução)
- `docs/bateria-basica-b1-b10-sau.md` — o antes, reusado sem re-rodar
- `harness/run_manual.py`, `harness/metrics_manual.py` — o instrumento desta issue
- ADR-0010 — ferramenta opcional, busca de segurança, literal garantido em código
- ADR-0011 — pipeline de OCR, máscara, chunk por slide, Fonte título + página, Chroma persistente
- ADR-0012 — limiar e frase de ausência
- ADR-0013 — recuperação híbrida (BM25 + RRF, re-rank pelo cosseno)
- `docs/medicao-hibrido/resultado.md` — recall vetorial 8/13 × híbrido 10/13 nas x1–x5
