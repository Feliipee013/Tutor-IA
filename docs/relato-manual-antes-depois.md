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
ao ADR-0003 (que proíbe execução única porque o modelo varia entre
repetições). Consequência: não há leitura de estabilidade (a coluna
"comportamento" sai trivialmente estável) e cada número registra uma das
respostas possíveis, não o comportamento típico.

**Temperatura do modelo, por decisão.** O depois roda com **temperatura 0.8**
(o padrão do modelo no Ollama), e não com o `temperature 0` do ADR-0003 —
decisão do usuário na #37, com exceção explícita ao ADR. Motivo: em produção
a temperatura é a do modelo e a seed é sorteada a cada chamada
(`sau/inference/ollama.py:9`); medir a 0.8 aproxima a bateria do que o Aluno
recebe. A seed segue fixa (20260926), então a rodada é reproduzível
chamada a chamada. Consequência: os números valem para amostragem 0.8, não
para geração gananciosa.

**Como ler os vereditos.** O julgamento do depois foi redigido pelo agente
(OpenCode) e aguarda ratificação de Leonardo Rodrigues (assignee da #37),
conforme a emenda do ADR-0006. A régua é aplicada à letra: todo bloco `b`/`x`
exige a citação da Fonte (título + página) no `conforme quando`, então
resposta sem citação é `não conforme` mesmo com o conteúdo correto. A análise
de cada caso separa as duas coisas — conteúdo ancorado de um lado, citação de
outro — como o antes já fazia (9/10 ancoradas, 0/10 com citação completa).

## Condições dos dois lados

| Condição | Antes (reuso, sem re-rodar) | Depois (rodada desta issue) |
| --- | --- | --- |
| Perguntas | b1–b10 de `perguntas-teste/bateria-manual.md` | b1–b10 + x1–x5 + n1–n5 (20) |
| Recuperação | sem híbrido (só vetorial), k=4, limiar 0.72 | híbrida padrão (`buscar_hibrida_no_indice`), k=4, limiar 0.55 |
| Gerador e travas | qwen2.5:3b, temperature 0, seed 20260926, num_predict 512, num_ctx 4096 | qwen2.5:3b, temperature 0.8 (padrão do modelo), seed 20260926, num_predict 512, num_ctx 4096 |
| Índice | Chroma `manual-estagio-obrigatorio`, 57 chunks | o mesmo (PDF sha256 `1832780d…be19ffefa9`, 57 chunks, `nomic-embed-text`) |
| Caminho | `executar_turno` real, histórico vazio | o mesmo (grafo por turno, histórico vazio) |
| Repetições | 1 por pergunta, julgamento humano lendo o PDF | 1 por pergunta (20 execuções) |
| Prompt | persona anterior | persona com prazos por situação + exemplo ancorado (main `ddbae1c`, sha256 `029d9696…fca2ec`, conferido: o da rodada é o do código) |
| Julgamento | pessoa lendo o Manual em PDF | agente redigiu, a ratificar por Leonardo Rodrigues |
| Data | 2026-10-14 | 2026-10-16 |
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
| Citação correta (b/x) | 2/15 = 0,13 | 2/15 perguntas = 0,13 |
| "Não sei" correto (n) | 1/5 = 0,20 | 1/5 perguntas = 0,20 |

A conferência mecânica marca 10 respostas como parciais (fragmento do título,
sem `(p. N)`), 2 como ausentes (b1, b7) e 3 como verificáveis (b3 com
`SEGURO OBRIGATÓRIO (p. 5)`, b9 com página sem título, x2 com
`VINCULAR O SUPERVISOR À EMPRESA (p. 25)`). O veredito humano confirma 2/15
em citação (b3, x2). E como a régua exige a citação também no acerto, o acerto
vai a 0/15 junto — incluindo a b2, cujos 7 prazos conferem integralmente.

**A leitura que o número sozinho esconde.** Pela letra da régua, o depois
zerou no acerto; pelo conteúdo, não. Núcleo correto em: b2 (os 7 prazos em
dias úteis, íntegros), b4, b6 (núcleo, com "Novo Cadastro"), b9 (papel +
cadastro prévio nos 6 cursos), b10 (6h/30h com a Lei, envio e formatos) e x5
(conteúdo + envio). Conteúdo errado no ponto que a régua cobra em: b1 (nega
data especificada e empurra ao Polo/Unidade — o antes ancorava), b3 (estende
a cobertura a "doenças profissionais"), b5 (põe o Polo para fazer o convênio
"junto com" o Time), b7 (omite o nome de fantasia), b8 (presume "o seu curso"
sem sabê-lo e inventa prazo da coordenação), x1 (Acadêmico contraditório),
x2 (inverte o teto para "máxima de 10h"), x3 (joga tudo no Polo/Unidade, sem
os 7+7 dias), x4 (reedição sem sentido). Nas `n`, só 1/5 confere (n3): as
demais respondem certo no conteúdo mas sem o literal "não encontrei no
material" que a régua exige — n1, n2, n4 e n5 caem por forma, não por
Alucinação.

**Antes × depois, só nas `b`:** o conteúdo segue ancorado na maioria dos
casos e a citação completa segue rara — o defeito que o antes apontava
("ORIENTACAO_DE_FONTE não virou citação visível") melhorou de 0/10 para 2/15
contando as cruzadas, mas segue aberto nas básicas (0/10). O que mudou de
verdade: b2 lista os 7 prazos que o antes listava (agora sem citar), b8 saiu
da inversão do antes para uma presunção sobre "o seu curso", e b9 troca a
citação parcial do antes por página sem título. As `x`/`n` são estreia, sem
delta.

## Caso a caso

Resposta literal da única repetição do depois, com a análise.

### b1 — Data limite do período de estágio

**Pergunta feita:** Até quando eu posso realizar o estágio obrigatório neste
semestre? Quem define essa data limite?

**Antes:** ancorada (p.3, time de planejamento + Colaborar), sem citação.

**Resposta obtida (depois):** "Baseado no material que encontrei, a data
limite [...] não foi especificada diretamente. [...] você deve realizar a
edição de sua vigência e carga horária no AVA após a associação [...] Para a
data limite, você precisará verificar as orientações específicas do seu
Polo/Unidade [...]."

**Análise:** erra no ponto central: nega data especificada e atribui a regra
ao Polo/Unidade, quando o Manual manda time de planejamento + Colaborar (a
p.3 estava recuperada em 1º — erro do redator). Sem citação. Vereditos:
`nao_conforme` nos dois.

### b2 — Prazos de análise no Colaborar

**Pergunta feita:** Quanto tempo o Time de Estágios leva para analisar cada
cadastro que eu faço no Colaborar? Os prazos são em dias úteis?

**Antes:** ancorada, os 7 valores conferindo, sem citação.

**Resposta obtida (depois):** "Os prazos [...] são em dias úteis, conforme o
seguinte: Cadastro de empresa: 4 dias úteis; Alteração do responsável: 5;
Cadastro de Supervisor de Campo/Acadêmico/Preceptor: 4; Vínculo
Supervisor/Empresa: 4; Declaração de Dispensa: 5; Liberação do Termo e do
Cadastro da Empresa: 7; Validação do Termo e do Cadastro da Empresa: 7."

**Análise:** os 7 valores conferem integralmente, em dias úteis — o melhor
acerto de conteúdo da bateria. Cai só na citação, que a régua exige também
no acerto. Vereditos: `nao_conforme` nos dois — só pela citação.

### b3 — Seguro obrigatório e o que cobre

**Pergunta feita:** O estágio obrigatório tem seguro? O que exatamente esse
seguro cobre — e o que ele NÃO cobre?

**Antes:** ancorada (p.5, MA + IPA), sem dado de apólice (correto, máscara),
sem citação.

**Resposta obtida (depois):** "Segundo a informação do SEGURO OBRIGATÓRIO
(p. 5), o seguro [...] inclui [...] MA - Morte Acidental e IPA - Invalidez
Permanente ou Total por Acidente: Essas coberturas cubrem [...] acidentes de
trabalho, doenças profissionais [...]."

**Análise:** núcleo MA/IPA certo, Lei 11.788/08 mencionada, sem apólice
(a máscara segurou) — mas estende a cobertura a "doenças profissionais", que
o `não conforme quando` proíbe. A citação `SEGURO OBRIGATÓRIO (p. 5)`
sustenta o núcleo. Vereditos: acerto `nao_conforme`, citação `conforme`.

### b4 — Convênio obrigatório na área da Saúde

**Pergunta feita:** Sou de um curso da área da Saúde. Preciso de convênio
para fazer o estágio? O que acontece se não tiver convênio?

**Antes:** ancorada (p.6 + p.7, Prisma/GO), sem citação.

**Resposta obtida (depois):** "Baseado nos trechos do material, para fazer um
estágio na área da Saúde, você precisa de um convênio. Sem convênio, os
alunos da Saúde não podem iniciar o estágio. O convênio é um documento formal
firmado entre a IES e a empresa, e geralmente precisa passar pela análise
jurídica. [...] entre em contato com a Coordenação de Estágios [...]."

**Análise:** núcleo certo (convênio obrigatório, sem ele não inicia) e
Encaminhamento sem sugerir Cadastro de Empresa para a Saúde; sem citação.
Vereditos: `nao_conforme` nos dois — só pela citação.

### b5 — Convênio × Cadastro de Empresa

**Pergunta feita:** Qual é a diferença entre convênio e cadastro de empresa?
Quem faz cada um — eu, o Polo ou a faculdade?

**Antes:** ancorada com extra correto de p.11, com eco "Aluno:" (defeito de
forma), sem citação.

**Resposta obtida (depois):** "Conforme o material do Manual, [...] Convênio
é necessário apenas para cursos da área da Saúde [...] documento formal [...]
análise jurídica em alguns casos [...]. Cadastro de Empresa é usado para
cursos fora da Saúde, feito pelo Polo no Colaborar. [...] o convênio é feito
pelo Polo junto com o Time de Convênios da IES (Regulação e Controle)."

**Análise:** distingue os dois e nomeia o Time de Convênios — mas põe o Polo
para fazer o convênio "junto com" o Time, quando a régua manda o Polo não
cadastrar sozinho (é informado via chamado). Sem citação. Vereditos:
`nao_conforme` nos dois.

### b6 — Cadastrar empresa no Colaborar

**Pergunta feita:** Como eu cadastro a empresa concedente no Colaborar? Qual
o caminho e o que eu preciso conferir antes?

**Antes:** ancorada (p.8 + p.9 + p.7), sem citação.

**Resposta obtida (depois):** "Para cadastrar a empresa no Colaborar: 1.
**Novo Cadastro** [...] preencher todos os campos obrigatórios [...]. 2.
**Verificar Dados** [...] razão social da Receita Federal [...] entrará em
reedição. [...] 4. **Upload de Documentos** [...] três folhas em um único
arquivo. [...] consulte o portal Prisma [...]."

**Análise:** traz "Novo Cadastro", reedição e Prisma — mas omite o caminho
Menu > DGA/Secretaria > Estágio > Registro de Empresas e a consulta por CNPJ
que a régua cobra. Sem citação. Vereditos: `nao_conforme` nos dois.

### b7 — Razão social da empresa

**Pergunta feita:** No cadastro da empresa, o que eu coloco no campo da razão
social? Tem um jeito certo de preencher?

**Antes:** ancorada, curta e fiel (p.10), sem citação.

**Resposta obtida (depois):** "O campo da razão social [...] deve ser
preenchido com a razão social da Receita Federal [...] Por exemplo, se a
escola João e Maria está registrada sob o CNPJ da prefeitura, você deve
informar a razão social da prefeitura. [...] qualquer divergência [...] o
cadastro entrará em reedição."

**Análise:** traz a razão da Receita, mas omite o nome de fantasia e o
formato razão + fantasia com o exemplo do slide que a régua cobra. Zero
menção a Fonte (a mecânica marca ausente). Vereditos: `nao_conforme` nos
dois.

### b8 — Supervisor Acadêmico

**Pergunta feita:** Quem é o Supervisor Acadêmico e quando eu preciso
cadastrar ele? Vale para o meu curso?

**Antes:** a única b com conteúdo não conforme — regra invertida (o "não
consta / não precisa" atribuído aos 6 cursos).

**Resposta obtida (depois):** "Para o seu curso, não é necessário cadastrar o
Supervisor Acadêmico, pois [...] ele não constará no termo de compromisso.
[...] em alguns cursos específicos como Biomedicina, Enfermagem, Farmácia,
Fisioterapia, Nutrição e Serviço Social, é necessário cadastrar o Supervisor
Acadêmico no sistema colaborar antes de associar o aluno [...]. Quanto ao
prazo para cadastrar [...], não há um prazo específico [...] definido pela
coordenação de estágios."

**Análise:** enuncia as duas regras no sentido certo (a inversão do antes
saiu) — mas presume "o seu curso" sem sabê-lo e inventa prazo "definido pela
coordenação" mais "regras variam entre instituições", que ninguém perguntou.
Sem citação. Vereditos: `nao_conforme` nos dois.

### b9 — Supervisor de Campo

**Pergunta feita:** Quem é o Supervisor de Campo e quando ele precisa ser
cadastrado no sistema?

**Antes:** ancorada (p.16 + p.17 + p.18), com citação parcial ("página 16").

**Resposta obtida (depois):** "Segundo o Manual, o Supervisor de Campo é o
profissional designado pela empresa [...] Antes de associar o aluno, o
supervisor de campo precisa ser cadastrado no sistema colaborar, conforme
[...] Biomedicina, Enfermagem, Farmácia, Fisioterapia, Nutrição e Serviço
Social. O cadastro [...] deve ser feito conforme indicado na página 9 do
Manual [...]."

**Análise:** papel + cadastro prévio nos 6 cursos certos; a citação é
parcial ("página 9", sem título e com página trocada). Vereditos:
`nao_conforme` nos dois — só pela citação.

### b10 — Limite de carga horária e Declaração de Dispensa

**Pergunta feita:** Qual é o limite de carga horária do estágio obrigatório?
E como eu envio a Declaração de Dispensa?

**Antes:** núcleo com base (6h/30h, envio, formatos), extra de p.30 parcial,
sem citação.

**Resposta obtida (depois):** "Conforme a Lei de Estágio nº 11.788/08, o
aluno não pode cumprir mais do que 6 horas diárias e 30 horas semanais [...]
O envio é realizado através do sistema Colaborar, em: menu > dga/secretaria >
estágio > solicitação de dispensa de estágio. [...] formato PDF, JPG, JPEG e
PNG [...] assinadas e legíveis. [...] alteração da carga horária do
supervisor de campo [...] código do supervisor, CRESS [...]."

**Análise:** núcleo 6h/30h com a Lei + envio e formatos certos; o menu sai
sem o "remunerado" do título esperado e o extra de Serviço Social não foi
pedido (veio dos chunks — procedimento, não invenção solta). Sem citação.
Vereditos: `nao_conforme` nos dois — só pela citação.

### x1 — Enfermagem: convênio e qual supervisor (estreia)

**Pergunta feita:** Sou de Enfermagem. A empresa precisa ter convênio com a
faculdade? E qual supervisor eu preciso cadastrar — o de campo e o acadêmico?

**Resposta obtida (depois):** "segundo o documento [CAMPO DE ESTÁGIO |
EMPRESA (p. 6)], os cursos da Área da Saúde, incluindo Enfermagem, precisam
ter convênio [...] conforme o documento [SUPERVISOR DE CAMPO (p. 16)], você
precisará cadastrar o Supervisor de Campo [...]. No entanto, [...] o
Supervisor Acadêmico não precisará ser vinculado à empresa [...]. No
entanto, [...] o Supervisor Acadêmico será necessário e precisará estar
vinculado à empresa."

**Análise:** convênio certo e Campo a cadastrar certo, com as duas páginas
citadas — mas o Acadêmico sai contraditório no mesmo parágrafo (ora dispensa
vínculo, ora exige) e sem a nomenclatura Preceptor/Enfermeiro que a régua
cobra, então as Fontes não sustentam a nomenclatura. Vereditos:
`nao_conforme` nos dois. As 3 Fontes certas foram recuperadas (p.6, p.15,
p.16) — o erro foi do redator.

### x2 — Serviço Social: vínculo, empresa e carga horária (estreia)

**Pergunta feita:** Sou de Serviço Social. O supervisor de campo precisa de
vínculo com a empresa? Por que a empresa não aparece para associar? E quantas
horas ele pode ter?

**Resposta obtida (depois):** "o Supervisor de Campo precisa ter vínculo com
a empresa, e a empresa só se torna visível para associação após o vínculo
[...] realizado e validado pelo Time de Estágios. [...] conforme a Resolução
533/08, o Assistente Social pode supervisionar 1 aluno por 10 horas [...] a
carga horária máxima [...] é de 10 horas semanais. [...] siga as etapas
[...] em [VINCULAR O SUPERVISOR À EMPRESA (p. 25)]."

**Análise:** vínculo + empresa-visível-após-validado + 1 aluno/10h certos,
com a página do procedimento citada — mas inverte o teto ("máxima de 10h"
em vez de não ultrapassar 30h). Vereditos: acerto `nao_conforme`,
citação `conforme`.

### x3 — Prazos de liberação, validação e envio (estreia)

**Pergunta feita:** Quanto tempo o time leva para liberar o Termo de
Compromisso e quanto para validar depois que eu envio? E existe um prazo para
eu enviar a documentação?

**Resposta obtida (depois):** "O prazo para a liberação do Termo de
Compromisso e sua validação é de responsabilidade do seu Polo/Unidade [...] Não
foi informado exatamente quanto tempo esse processo leva [...]. A
documentação [...] precisa ser enviada pelo aluno através do AVA. Não foi
fornecido um prazo específico para esse envio [...]."

**Análise:** acerta só o envio pelo Aluno no AVA; joga liberação, validação
e prazo de envio no "Polo/Unidade" sem os 7 + 7 dias úteis da p.4 — que de
novo não estava entre as Fontes recuperadas (p.46/51/48/44). É o caso que
mais mostra o custo de recuperação incompleta em pergunta cruzada. Sem
citação. Vereditos: `nao_conforme` nos dois.

### x4 — Reedição × alteração de responsável (estreia)

**Pergunta feita:** Quando eu mexo no cadastro da empresa, qual a diferença
entre colocar em "reedição" e fazer "alteração de responsável"? Qual eu uso
em cada caso?

**Resposta obtida (depois):** "você deve usar a opção de ALTERAÇÃO DE
RESPONSÁVEL quando [...] alterar o nome do responsável [...]. Neste caso, não
é necessário colocar o cadastro do aluno em reedição. Já a opção de REEDIÇÃO
DE ALTERAÇÃO DE deve ser usada quando ocorrer uma revisão ou correção [...]
mas precisam ser atualizadas."

**Análise:** a alteração sai certa (sem pôr o Aluno em reedição), mas a
reedição sai sem sentido — não é o status que o Time marca ante divergência,
com correção e salvamento pelo Polo, que a régua pede. Sem citação válida.
Vereditos: `nao_conforme` nos dois.

### x5 — Termo modelo Empresa (estreia)

**Pergunta feita:** A empresa quer usar o modelo de Termo de Compromisso
dela. O que ele precisa conter, como eu envio e quem assina?

**Resposta obtida (depois):** "o modelo de Termo de Compromisso da empresa
precisa conter: Identificação do aluno (Nome completo, RA, CPF); Local do
estágio; Nome dos supervisores e do conselho; Dados da IES e representante
legal. Antes de assinar [...] enviá-lo por chamado para validação, com as
assinaturas [...] aluno, empresa e IES."

**Análise:** conteúdo e envio certos no essencial; faltam as cláusulas
conforme a Lei 11.788, vigência/horário, atividades e o WORD ou PDF. Sem
citação. Vereditos: `nao_conforme` nos dois — por detalhe + citação.

### n1 — Valor da mensalidade e desconto (estreia)

**Pergunta feita:** Quanto é a mensalidade do meu curso e tem desconto para
quem faz estágio?

**Resposta obtida (depois):** "As informações sobre a mensalidade do seu
curso e se há desconto para quem faz estágio não estão presentes nos trechos
que eu possuo. Procure a Coordenação de Estágios para obter essa informação."

**Análise:** não afirma valor e Encaminha — mas sem o literal "não
encontrei no material" que a régua exige. Veredito: `nao_conforme` (por
forma, não por Alucinação).

### n2 — Contato oficial da Coordenação de Estágios (estreia)

**Pergunta feita:** Qual é o telefone e o e-mail da Coordenação de Estágios?
Preciso falar com alguém de lá.

**Resposta obtida (depois):** "Os dados da Coordenação de Estágios não estão
disponíveis neste material. Procure a Coordenação de Estágios para obter as
informações que você precisa."

**Análise:** não inventa canal e Encaminha — mas sem o literal. Veredito:
`nao_conforme` (por forma).

### n3 — Data de entrega do relatório do Aluno (estreia)

**Pergunta feita:** Qual é a data exata de entrega do meu relatório de
atividades? Meu professor falou que tem um dia certo.

**Resposta obtida (depois):** "Com base no material fornecido, não encontrei
no material a data exata de entrega do seu relatório de atividades. Procure a
Coordenação de Estágios para obter essa informação."

**Análise:** literal + Encaminhamento, sem data. Veredito: `conforme`.

### n4 — Catálogo de cursos e polos (estreia)

**Pergunta feita:** Quais cursos a faculdade oferece no meu polo? Tem o curso
que eu quero?

**Resposta obtida (depois):** "Pelo material que você consultou, não foi
possível encontrar quais cursos a faculdade oferece no seu polo específico.
Para obter essa informação, é melhor você procurar a Coordenação de
Estágios."

**Análise:** não afirma catálogo e Encaminha — mas sem o literal. Veredito:
`nao_conforme` (por forma).

### n5 — Dado do seguro: apólice, seguradora e vigência (estreia)

**Pergunta feita:** Qual é o número da apólice do seguro de estágio? E qual é
a seguradora, e até quando a apólice vale?

**Resposta obtida (depois):** "Infelizmente, o material que você solicitou
não contém informações sobre o número da apólice do seguro de estágio, a
seguradora ou até quando a apólice vale. Procure a Coordenação de Estágios
para obter essa informação."

**Análise:** não cita dado mascarado e Encaminha — a máscara antes de
indexar segue funcionando de ponta a ponta — mas sem o literal. Veredito:
`nao_conforme` (por forma).

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
estilo: `num_ctx` é 4096 e não é tocado, e cada trecho custa contexto que a
conversa não tem. O híbrido resgata o que o
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
sagrada. A ausência de citação completa (0/10 nas básicas do depois) é o
próximo defeito a fechar, não uma qualidade do índice. A amostra é única e a
temperatura é a do modelo: cada número registra uma das respostas possíveis,
não o comportamento típico. A b8 do antes saiu com a regra invertida; o
depois a enuncia no sentido certo — inversão fechada nesta amostra única.

## Ressalva sobre d1–d10 (fora do escopo)

Os blocos d1–d10 seguem no arquivo, intactos, e fora desta rodada por decisão
registrada no plano (o usuário ressalvou que os blocos `d` possivelmente estão
errados e merecem revisão em issue futura). Nada deles foi deletado nem
reescrito aqui. Em particular, as sondas de nomenclatura e ação por curso
(d1–d4) dependem do pareamento do OCR das tabelas de p.15–p.16 — e o depois
mostra que esse pareamento ainda falha no redator (x1) mesmo com
as páginas recuperadas. A revisão dos `d` deve cobrir o `conforme quando` de
cada um contra o Manual antes de qualquer rodada que os inclua.

## Referências e artefatos

- `perguntas-teste/bateria-manual.md` — os 30 blocos e o `conforme quando` de cada um
- `corpus/manual-estagio-obrigatorio-polo-2026-2.pdf` — o Manual (local, fora do git; sha256 `1832780d…be19ffefa9`)
- `outputs/baseline-manual-hibrido.json` — a rodada do depois (20 execuções, evidência bruta + Fontes recuperadas)
- `outputs/baseline-manual-hibrido.julgamento.json` — a folha (35 vereditos, redigida pelo agente, a ratificar por Leonardo Rodrigues em 2026-10-16)
- `outputs/baseline-manual-hibrido.metricas.json` — as taxas (acerto 0/15, citação 2/15, "não sei" 1/5, por execução e por pergunta, fora_da_conta vazio, Fonte mecânica por execução)
- `docs/bateria-basica-b1-b10-sau.md` — o antes, reusado sem re-rodar
- `harness/run_manual.py`, `harness/metrics_manual.py` — o instrumento desta issue
- ADR-0010 — ferramenta opcional, busca de segurança, literal garantido em código
- ADR-0011 — pipeline de OCR, máscara, chunk por slide, Fonte título + página, Chroma persistente
- ADR-0012 — limiar e frase de ausência
- ADR-0013 — recuperação híbrida (BM25 + RRF, re-rank pelo cosseno)
- `docs/medicao-hibrido/resultado.md` — recall vetorial 8/13 × híbrido 10/13 nas x1–x5
