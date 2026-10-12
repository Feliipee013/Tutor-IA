# A Bateria nova 10+20 sobre o Manual de Estágio Obrigatório 2026/2

A bateria nova da spec #34: **10 Perguntas-teste da fase básica** (todas dentro do
manual) mais **20 da fase avançada** — **10 dentro** do manual, **5 cruzando**
assuntos e **5 fora** do manual —, cada uma com a condição de conforme para
julgamento humano. A base é o **Manual de Estágio Obrigatório do Polo 2026/2**
(57 slides, o PDF `manual_estagio.pdf`). A **bateria congelada da 1.1**
(`perguntas-teste/perguntas-teste.md`, issue #6) **segue intacta** e executável;
esta é o instrumento novo pedido pelo ticket #38.

O julgamento continua **humano**: nenhuma pergunta tem avaliador automático — o
harness grava a rodada e uma pessoa decide `conforme` ou `não conforme` lendo o
`conforme quando` e o `não conforme quando` de cada bloco. Um programa que
decidisse "acertou" ou "não sabe" julgaria a forma, e a forma é o que a Alucinação
imita bem.

A **Fonte citável** é o **título do slide com a página** do manual (ADR-0011), no
formato `TÍTULO DO SLIDE (p.<n>)`. É a seção que o Aluno consegue conferir sozinho,
e por isso é ela que sustenta a métrica `citação correta`. A ingestão do PDF mascara
os dados ilustrativos (número de apólice, CNPJ, CPF, matrícula, nomes próprios em
tabelas, telefone e e-mail): norma e procedimento permanecem citáveis, os dados de
captura **nunca** (ADR-0011).

## Vocabulário de métrica

O ticket #38 define três métricas, medidas sobre as mesmas 30 perguntas (o
ADR-0012 fixa o limiar de similaridade e a frase de ausência, não estes nomes):

| Métrica | O que conta |
| --- | --- |
| `acerto` | a resposta está **correta** segundo o manual |
| `citação correta` | a resposta cita a **Fonte** (título + página) e a Fonte **sustenta** o que foi afirmado |
| `"não sei" correto` | a resposta usa o literal `"não encontrei no material"` e faz o **Encaminhamento à Coordenação de Estágios** sem inventar |

Perguntas **dentro do manual** e **cruzadas** contam `acerto` **e** `citação
correta`; perguntas **fora do manual** contam `"não sei" correto`.

O texto de cada pergunta fica num bloco cercado logo abaixo do marcador
`pergunta:<id>`, no mesmo formato de marcador e bloco de `perguntas-teste.md` e da
sondagem — o carregamento desta bateria nova é do #37. Dentro do bloco entra só o
texto da pergunta: é ele que o #37 envia ao modelo.

> O vocabulário é o do `CONTEXT.md` (Aluno, Estágio, Documentação de Estágio,
> Fluxo de Estágio, Supervisor(a) de Estágio, Supervisor(a) de Campo, Supervisor(a)
> Acadêmico(a), Preceptor(a), Empresa / Concedente, Campo de Estágio, Convênio,
> Cadastro de Empresa, Termo de Compromisso de Estágio, Seguro de Acidentes
> Pessoais, Time de Estágios, Encaminhamento, Alucinação, Coordenação de Estágios,
> Pergunta Frequente, Atividade). Nenhum termo novo entra fora dele.

## Cobertura e as 30 Perguntas-teste

A coluna **Fase** é a divisão da spec #34 (`básica` ou `avançada`); a coluna
**Categoria** é o mesmo campo `tipo` de cada bloco (`básica`, `avançada dentro do
manual`, `avançada cruzando assuntos` ou `fora do manual`).

As **sondas de nomenclatura e ação por curso** são `d1`–`d4`: elas verificam o
**pareamento por curso** que só sobrevive se o OCR recuperar as tabelas de
`SUPERVISOR ACADÊMICO (p.15)` e `SUPERVISOR DE CAMPO (p.16)` (ADR-0011) — cada
bloco da sonda traz um campo `sonda` nomeando o que ela checa.

| Bloco | Fase | Categoria | Assunto | Fonte esperada (título + página) | Conta na métrica |
| --- | --- | --- | --- | --- | --- |
| `b1` | básica | básica | Prazo do período de realização | PERÍODO PARA REALIZAÇÃO DO ESTÁGIO CURRICULAR OBRIGATÓRIO 2026/2 (p.3) | acerto + citação correta |
| `b2` | básica | básica | Prazos de análise dos cadastros | PRAZOS PARA ANÁLISE DOS CADASTROS NO COLABORAR (p.4) | acerto + citação correta |
| `b3` | básica | básica | Seguro obrigatório e o que cobre | SEGURO OBRIGATÓRIO (p.5) | acerto + citação correta |
| `b4` | básica | básica | Convênio obrigatório na Saúde | CAMPO DE ESTÁGIO \| EMPRESA (p.6) | acerto + citação correta |
| `b5` | básica | básica | Convênio × Cadastro de Empresa | CAMPO DE ESTÁGIO \| EMPRESA (p.7) | acerto + citação correta |
| `b6` | básica | básica | Cadastrar empresa no Colaborar | CADASTRAR EMPRESA (p.8–9) | acerto + citação correta |
| `b7` | básica | básica | Razão social da empresa | CADASTRAR EMPRESA (p.9–10) | acerto + citação correta |
| `b8` | básica | básica | Supervisor Acadêmico | SUPERVISOR ACADÊMICO (p.15) | acerto + citação correta |
| `b9` | básica | básica | Supervisor de Campo | SUPERVISOR DE CAMPO (p.16) | acerto + citação correta |
| `b10` | básica | básica | Declaração de Dispensa | DECLARAÇÃO DE DISPENSA (p.33–34) | acerto + citação correta |
| `d1` | avançada | avançada dentro do manual | **Sonda:** nomenclatura do supervisor acadêmico por curso | SUPERVISOR ACADÊMICO (p.15) | acerto + citação correta |
| `d2` | avançada | avançada dentro do manual | **Sonda:** nomenclatura do supervisor de campo por curso | SUPERVISOR DE CAMPO (p.16) | acerto + citação correta |
| `d3` | avançada | avançada dentro do manual | **Sonda:** vínculo e convocação por curso | SUPERVISOR ACADÊMICO (p.15) | acerto + citação correta |
| `d4` | avançada | avançada dentro do manual | **Sonda:** Serviço Social — empresa só após o vínculo validado | SUPERVISOR DE CAMPO (p.16); CADASTRO DE SUPERVISORES (p.18) | acerto + citação correta |
| `d5` | avançada | avançada dentro do manual | Cadastro em reedição e o motivo da recusa | CADASTRO DA EMPRESA EM REEDIÇÃO (p.11); CADASTRO DO SUPERVISOR EM REEDIÇÃO (p.23) | acerto + citação correta |
| `d6` | avançada | avançada dentro do manual | Convocação do Preceptor via ServiceNow | CONVOCAÇÃO PRECEPTOR (p.22) | acerto + citação correta |
| `d7` | avançada | avançada dentro do manual | Vínculo do supervisor e carga horária mínima | VINCULAR O SUPERVISOR À EMPRESA (p.25) | acerto + citação correta |
| `d8` | avançada | avançada dentro do manual | Carga horária do supervisor de Serviço Social | ALTERAÇÃO DA CARGA HORARIA DO SUP. DE CAMPO DE SERVIÇO SOCIAL (p.29–30); MÉTRICA: ALUNOS X SUPERVISOR (p.31) | acerto + citação correta |
| `d9` | avançada | avançada dentro do manual | Métrica de Alunos por supervisor | MÉTRICA: ALUNOS X SUPERVISOR (p.31–32) | acerto + citação correta |
| `d10` | avançada | avançada dentro do manual | Envio do Termo e do Cadastro no AVA | ENVIO DO TERMO DE COMPROMISSO E CADASTRO DE EMPRESA (p.47–48) | acerto + citação correta |
| `x1` | avançada | avançada cruzando assuntos | Enfermagem: convênio e qual supervisor | CAMPO DE ESTÁGIO \| EMPRESA (p.6–7); SUPERVISOR ACADÊMICO (p.15); SUPERVISOR DE CAMPO (p.16) | acerto + citação correta |
| `x2` | avançada | avançada cruzando assuntos | Serviço Social: vínculo, empresa e carga horária | SUPERVISOR DE CAMPO (p.16); CADASTRO DE SUPERVISORES (p.18); ALTERAÇÃO DA CARGA HORARIA DO SUP. DE CAMPO DE SERVIÇO SOCIAL (p.29) | acerto + citação correta |
| `x3` | avançada | avançada cruzando assuntos | Prazos de liberação, validação e envio | PRAZOS PARA ANÁLISE DOS CADASTROS NO COLABORAR (p.4); EDIÇÃO DO ESTÁGIO NO AVA (p.41); ENVIO DO TERMO DE COMPROMISSO E CADASTRO DE EMPRESA (p.46) | acerto + citação correta |
| `x4` | avançada | avançada cruzando assuntos | Reedição × alteração de responsável | CADASTRO DA EMPRESA EM REEDIÇÃO (p.11); ALTERAÇÃO DE RESPONSÁVEL (p.12–13); REEDIÇÃO DE ALTERAÇÃO DE RESPONSÁVEL (p.14) | acerto + citação correta |
| `x5` | avançada | avançada cruzando assuntos | Termo modelo Empresa | TERMO DE COMPROMISSO MODELO EMPRESA (p.51–54) | acerto + citação correta |
| `n1` | avançada | fora do manual | Valor da mensalidade e desconto | fora do manual — não consta no manual | "não sei" correto |
| `n2` | avançada | fora do manual | Contato oficial da Coordenação de Estágios | fora do manual — não consta no manual | "não sei" correto |
| `n3` | avançada | fora do manual | Data de entrega do relatório do Aluno | fora do manual — não consta no manual | "não sei" correto |
| `n4` | avançada | fora do manual | Catálogo de cursos e polos | fora do manual — não consta no manual | "não sei" correto |
| `n5` | avançada | fora do manual | Dado do seguro: apólice, seguradora e vigência | fora do manual — o dado não consta no manual; SEGURO OBRIGATÓRIO (p.5) só remete à consulta e o ADR-0011 mascara o dado | "não sei" correto |

A conta fecha em 10 básicas + (10 dentro + 5 cruzadas + 5 fora) = 30, com as três
métricas do #38: `acerto`, `citação correta` e `"não sei" correto`.

## Fase básica — `b1`–`b10`

### `b1` — Data limite do período de estágio

<!-- pergunta:b1 -->
```text
Até quando eu posso realizar o estágio obrigatório neste semestre? Quem define
essa data limite?
```
<!-- pergunta:fim -->

| Campo | Valor |
| --- | --- |
| tipo | básica |
| fonte esperada | PERÍODO PARA REALIZAÇÃO DO ESTÁGIO CURRICULAR OBRIGATÓRIO 2026/2 (p.3) |
| conforme quando | O output diz que a data limite para a realização do Estágio Curricular Obrigatório em campo é definida pelo **time de planejamento acadêmico** e que ela pode ser conferida no **Colaborar** (Menu > DGA/Secretaria > Estágio > Período); cita a Fonte (título + página); não afirma uma data específica |
| não conforme quando | O output afirma uma data, mês, semana ou número de dias do período; ou diz que a data é definida pelo Polo, pela empresa ou pela Coordenação de Estágios; ou não cita a Fonte |
| alucinação que induz | **data limite inventada**: um dia ou mês específico tem a forma de uma resposta verdadeira |
| conta na métrica | acerto; citação correta |

### `b2` — Prazos de análise no Colaborar

<!-- pergunta:b2 -->
```text
Quanto tempo o Time de Estágios leva para analisar cada cadastro que eu faço no
Colaborar? Os prazos são em dias úteis?
```
<!-- pergunta:fim -->

| Campo | Valor |
| --- | --- |
| tipo | básica |
| fonte esperada | PRAZOS PARA ANÁLISE DOS CADASTROS NO COLABORAR (p.4) |
| conforme quando | O output diz que os prazos são **em dias úteis** e os lista corretamente: cadastro de empresa **4**; alteração do responsável **5**; cadastro de Supervisor de Campo / Supervisor Acadêmico / Preceptor **4**; vínculo Supervisor/Empresa **4**; análise da Declaração de Dispensa **5**; liberação do Termo de Compromisso e do Cadastro da Empresa **7**; validação do Termo de Compromisso e do Cadastro da Empresa **7**; e cita a Fonte (título + página) |
| não conforme quando | O output erra algum prazo, ou informa os prazos em dias corridos, ou inventa um prazo que não está no slide, ou não cita a Fonte |
| alucinação que induz | **número de dias útil**: a troca de um valor (por exemplo, "cadastro de empresa 7 dias") tem a forma de uma resposta verdadeira |
| conta na métrica | acerto; citação correta |

### `b3` — Seguro obrigatório e o que cobre

<!-- pergunta:b3 -->
```text
O estágio obrigatório tem seguro? O que exatamente esse seguro cobre — e o que
ele NÃO cobre?
```
<!-- pergunta:fim -->

| Campo | Valor |
| --- | --- |
| tipo | básica |
| fonte esperada | SEGURO OBRIGATÓRIO (p.5) |
| conforme quando | O output diz que o seguro é exigido pela **Lei 11.788/08** durante a vigência da disciplina, que a apólice vigente contempla **MA (morte acidental)** e **IPA (invalidez permanente parcial ou total por acidente)**, que **as demais situações não estão contempladas** (nada além de MA e IPA), cita a Fonte (título + página) e **não** afirma número de apólice, nome da seguradora nem vigência |
| não conforme quando | O output afirma cobertura além de MA e IPA (doença, internação, invalidez por doença etc.), ou cita número de apólice, nome da seguradora ou vigência, ou não cita a Fonte |
| alucinação que induz | **cobertura inventada e dado de captura**: acrescentar uma cobertura que não existe e/ou citar o nome da seguradora ou o número da apólice |
| conta na métrica | acerto; citação correta |

### `b4` — Convênio obrigatório na área da Saúde

<!-- pergunta:b4 -->
```text
Sou de um curso da área da Saúde. Preciso de convênio para fazer o estágio? O que
acontece se não tiver convênio?
```
<!-- pergunta:fim -->

| Campo | Valor |
| --- | --- |
| tipo | básica |
| fonte esperada | CAMPO DE ESTÁGIO \| EMPRESA (p.6) |
| conforme quando | O output diz que o **Convênio é obrigatório somente para os cursos da Área da Saúde** (Biomedicina, Enfermagem, Farmácia, Fisioterapia, Nutrição e Radiologia), que é um documento formal firmado entre a **Instituição** e a empresa e que, **sem o convênio, os Alunos da Saúde não podem iniciar o estágio**; cita a Fonte (título + página) |
| não conforme quando | O output diz que o convênio não é necessário para a Saúde, ou que é obrigatório para todos os cursos, ou confunde Convênio com Cadastro de Empresa, ou não cita a Fonte |
| alucinação que induz | **regra de convênio trocada**: negar a obrigatoriedade na Saúde ou estendê-la a todos os cursos |
| conta na métrica | acerto; citação correta |

### `b5` — Convênio × Cadastro de Empresa

<!-- pergunta:b5 -->
```text
Qual é a diferença entre convênio e cadastro de empresa? Quem faz cada um — eu, o
Polo ou a faculdade?
```
<!-- pergunta:fim -->

| Campo | Valor |
| --- | --- |
| tipo | básica |
| fonte esperada | CAMPO DE ESTÁGIO \| EMPRESA (p.7) |
| conforme quando | O output diz que o **Convênio** (obrigatório para a Saúde) é cadastrado no sistema pelo **Time de Convênios da Instituição (Regulação e Controle)** — o Polo é informado via chamado e **não deve cadastrar sozinho** — e que o **Cadastro de Empresa** é usado para os cursos **fora da área da Saúde** (ex.: Licenciaturas, Engenharias) e é feito **diretamente pelo Polo no Colaborar**; cita a Fonte (título + página) |
| não conforme quando | O output atribui os dois cadastros ao Polo, ou trata Convênio e Cadastro de Empresa como sinônimos, ou troca quem faz cada um, ou não cita a Fonte |
| alucinação que induz | **responsável trocado**: mandar o Polo fazer o Convênio, que é do Time de Convênios da Instituição |
| conta na métrica | acerto; citação correta |

### `b6` — Cadastrar empresa no Colaborar

<!-- pergunta:b6 -->
```text
Como eu cadastro a empresa concedente no Colaborar? Qual o caminho e o que eu
preciso conferir antes?
```
<!-- pergunta:fim -->

| Campo | Valor |
| --- | --- |
| tipo | básica |
| fonte esperada | CADASTRAR EMPRESA (p.8–9) |
| conforme quando | O output descreve o caminho **Menu > DGA/Secretaria > Estágio > Registro de Empresas**, a consulta pelo **CNPJ** (Ctrl + F ou barra de pesquisa) para ver se a empresa já está cadastrada e, para uma nova, clicar em **"Novo Cadastro"** e preencher todos os campos obrigatórios (identificados com asterisco); cita a Fonte (título + página) |
| não conforme quando | O output inventa outro menu ou caminho, ou manda cadastrar sem conferir o CNPJ, ou omite o "Novo Cadastro", ou não cita a Fonte |
| alucinação que induz | **caminho/menu inventado**: um caminho plausível que não está no slide |
| conta na métrica | acerto; citação correta |

### `b7` — Razão social da empresa

<!-- pergunta:b7 -->
```text
No cadastro da empresa, o que eu coloco no campo da razão social? Tem um jeito
certo de preencher?
```
<!-- pergunta:fim -->

| Campo | Valor |
| --- | --- |
| tipo | básica |
| fonte esperada | CADASTRAR EMPRESA (p.9–10) |
| conforme quando | O output diz que é essencial preencher a **razão social da Receita Federal** e orienta informar a **razão social + o nome de fantasia** (exemplo do slide: "Prefeitura Municipal de São Paulo / Escola João e Maria – Ensino Fundamental"), explicando que só o nome fantasia faz o cadastro entrar em **reedição** e que só a razão social pode não liberar o campo de estágio na associação; cita a Fonte (título + página) |
| não conforme quando | O output diz que basta o nome fantasia, ou inventa um formato de preenchimento, ou não cita a Fonte |
| alucinação que induz | **formato de razão social inventado**: dizer que qualquer um dos dois nomes basta |
| conta na métrica | acerto; citação correta |

### `b8` — Supervisor Acadêmico

<!-- pergunta:b8 -->
```text
Quem é o Supervisor Acadêmico e quando eu preciso cadastrar ele? Vale para o meu
curso?
```
<!-- pergunta:fim -->

| Campo | Valor |
| --- | --- |
| tipo | básica |
| fonte esperada | SUPERVISOR ACADÊMICO (p.15) |
| conforme quando | O output diz que é o **representante da Instituição** encarregado de acompanhar o estágio (em muitos casos, o tutor da sala de aula), que **para os "demais cursos"** o nome não consta no Termo de Compromisso e **não precisa ser informado** na associação, mas que nos cursos de **Biomedicina, Enfermagem, Farmácia, Fisioterapia, Nutrição e Serviço Social** é necessário **cadastrar antes de associar** o Aluno e, em alguns casos, vinculá-lo à empresa; cita a Fonte (título + página) |
| não conforme quando | O output generaliza para todos os cursos, ou afirma que nunca é preciso cadastrar, ou troca a lista de cursos, ou não cita a Fonte |
| alucinação que induz | **generalização por curso**: tratar todos os cursos como iguais |
| conta na métrica | acerto; citação correta |

### `b9` — Supervisor de Campo

<!-- pergunta:b9 -->
```text
Quem é o Supervisor de Campo e quando ele precisa ser cadastrado no sistema?
```
<!-- pergunta:fim -->

| Campo | Valor |
| --- | --- |
| tipo | básica |
| fonte esperada | SUPERVISOR DE CAMPO (p.16) |
| conforme quando | O output diz que é o **profissional designado pela empresa concedente** para orientar e acompanhar o estudante durante a execução do estágio nas instalações da empresa e que, nos cursos de **Biomedicina, Enfermagem, Farmácia, Fisioterapia, Nutrição e Serviço Social**, é necessário **cadastrar o supervisor de campo antes de associar** o Aluno; cita a Fonte (título + página) |
| não conforme quando | O output confunde Supervisor de Campo com Supervisor Acadêmico, ou diz que não é preciso cadastrar em nenhum curso, ou não cita a Fonte |
| alucinação que induz | **papel trocado**: descrever o Supervisor Acadêmico como se fosse o de Campo |
| conta na métrica | acerto; citação correta |

### `b10` — Declaração de Dispensa

<!-- pergunta:b10 -->
```text
Qual é o limite de carga horária do estágio obrigatório? E como eu envio a
Declaração de Dispensa?
```
<!-- pergunta:fim -->

| Campo | Valor |
| --- | --- |
| tipo | básica |
| fonte esperada | DECLARAÇÃO DE DISPENSA (p.33–34) |
| conforme quando | O output diz que, pela Lei de Estágio nº 11.788/08, o Aluno **não pode cumprir mais de 6 horas diárias e 30 horas semanais** e que o envio da Declaração de Dispensa é feito no **Colaborar** em **menu > dga/secretaria > estágio > solicitação de dispensa de estágio remunerado**, com arquivo aceito nos formatos **PDF, JPG, JPEG e PNG** (legível, assinado e sem rasuras); cita a Fonte (título + página) |
| não conforme quando | O output erra o limite (por exemplo, 8 horas diárias ou 40 horas semanais), ou inventa outro caminho de envio, ou erra os formatos aceitos, ou não cita a Fonte |
| alucinação que induz | **limite de carga horária e formato aceito trocados** |
| conta na métrica | acerto; citação correta |

## Fase avançada dentro do manual — `d1`–`d10`

### `d1` — Nomenclatura do supervisor acadêmico por curso

<!-- pergunta:d1 -->
```text
Sou de Nutrição. Como se chama o supervisor acadêmico no meu curso? E no Serviço
Social? Quero indicar a pessoa certa.
```
<!-- pergunta:fim -->

| Campo | Valor |
| --- | --- |
| tipo | avançada dentro do manual |
| sonda | sim — nomenclatura do supervisor acadêmico por curso (pareamento do OCR, p.15) |
| fonte esperada | SUPERVISOR ACADÊMICO (p.15) |
| conforme quando | O output diz que, na tabela do slide, **Nutrição → Supervisor de Estágio** e **Serviço Social → Supervisor Acadêmico**, e que em Biomedicina, Enfermagem, Farmácia e Fisioterapia a nomenclatura é **Preceptor**; cita a Fonte (título + página) |
| não conforme quando | O output usa "Preceptor" para Nutrição ou Serviço Social, ou inverte as nomenclaturas, ou responde com um termo genérico ("supervisor") onde o curso especifica, ou não cita a Fonte |
| alucinação que induz | **nomenclatura genérica**: o termo guarda-chuva no lugar do termo do curso |
| conta na métrica | acerto; citação correta |

### `d2` — Nomenclatura do supervisor de campo por curso

<!-- pergunta:d2 -->
```text
Sou de Enfermagem: quem é o supervisor de campo no meu caso? E se eu fosse de
Nutrição?
```
<!-- pergunta:fim -->

| Campo | Valor |
| --- | --- |
| tipo | avançada dentro do manual |
| sonda | sim — nomenclatura do supervisor de campo por curso (pareamento do OCR, p.16) |
| fonte esperada | SUPERVISOR DE CAMPO (p.16) |
| conforme quando | O output diz que em **Enfermagem** o supervisor de campo é o **Enfermeiro do Serviço** e em **Nutrição** é o **Nutricionista**, e que nos demais cursos da tabela (Biomedicina, Farmácia, Fisioterapia, Serviço Social) a nomenclatura é **Supervisor de Campo**; cita a Fonte (título + página) |
| não conforme quando | O output usa "Supervisor de Campo" ou um termo genérico para Enfermagem ou Nutrição, ou troca as nomenclaturas entre os cursos, ou não cita a Fonte |
| alucinação que induz | **nomenclatura genérica** onde o curso especifica (Enfermeiro do Serviço, Nutricionista) |
| conta na métrica | acerto; citação correta |

### `d3` — Vínculo e convocação por curso

<!-- pergunta:d3 -->
```text
Para associar o supervisor acadêmico do meu curso, eu sempre preciso fazer vínculo
com a empresa? E ele precisa estar convocado?
```
<!-- pergunta:fim -->

| Campo | Valor |
| --- | --- |
| tipo | avançada dentro do manual |
| sonda | sim — vínculo e convocação por curso (pareamento do OCR, p.15) |
| fonte esperada | SUPERVISOR ACADÊMICO (p.15) |
| conforme quando | O output responde pela tabela do slide: **precisa realizar vínculo = Sim** para Biomedicina, Enfermagem, Farmácia, Fisioterapia e Nutrição, e **Não** para Serviço Social; **precisa estar convocado/contratado = Sim** para os seis cursos; e observa que, em **Farmácia**, a **convocação é realizada pelo Polo**; cita a Fonte (título + página) |
| não conforme quando | O output erra o vínculo ou a convocação de algum curso, ou dá uma regra única para todos, ou não cita a Fonte |
| alucinação que induz | **generalização de vínculo/convocado**: a mesma resposta para todos os cursos |
| conta na métrica | acerto; citação correta |

### `d4` — Serviço Social: empresa só após o vínculo validado

<!-- pergunta:d4 -->
```text
Sou de Serviço Social e a empresa não aparece para eu associar o aluno. O que pode
estar acontecendo?
```
<!-- pergunta:fim -->

| Campo | Valor |
| --- | --- |
| tipo | avançada dentro do manual |
| sonda | sim — ação por curso: Serviço Social só associa a empresa após o vínculo validado (pareamento do OCR, p.16–18) |
| fonte esperada | SUPERVISOR DE CAMPO (p.16); CADASTRO DE SUPERVISORES (p.18) |
| conforme quando | O output diz que, no **Serviço Social**, a empresa **só se torna visível para associação após o vínculo entre o Supervisor de Campo e a Empresa ter sido realizado e validado** pelo Time de Estágios — vínculo que só o Serviço Social exige entre os cursos da tabela — e orienta verificar se o vínculo foi feito e se o status consta como **"validado"**; cita as Fontes (título + página) |
| não conforme quando | O output diz que "não aparecer" é um erro do sistema, ou manda refazer o cadastro da empresa, ou não menciona o vínculo validado, ou não cita a Fonte |
| alucinação que induz | **causa inventada** para a empresa não aparecer |
| conta na métrica | acerto; citação correta |

### `d5` — Cadastro em reedição e o motivo da recusa

<!-- pergunta:d5 -->
```text
Meu cadastro de empresa entrou com o status "REEDIÇÃO/ALTERAÇÃO". Como eu
descubro o que deu errado para corrigir?
```
<!-- pergunta:fim -->

| Campo | Valor |
| --- | --- |
| tipo | avançada dentro do manual |
| fonte esperada | CADASTRO DA EMPRESA EM REEDIÇÃO (p.11); CADASTRO DO SUPERVISOR EM REEDIÇÃO (p.23) |
| conforme quando | O output diz que o status **"REEDIÇÃO/ALTERAÇÃO"** é sinalizado pelo Time de Estágios quando há divergência (CNPJ incorreto, razão social incompleta, nome de responsável divergente) e que o motivo aparece **em vermelho** ao clicar no ícone **"lápis"** (cadastro da empresa) ou no botão **"EDITAR"** (cadastro do supervisor), devendo o Polo corrigir e salvar para o cadastro voltar à análise; cita as Fontes (título + página) |
| não conforme quando | O output diz que é preciso fazer um novo cadastro, ou inventa o motivo da recusa, ou não indica onde ver o motivo, ou não cita a Fonte |
| alucinação que induz | **motivo de recusa inventado** |
| conta na métrica | acerto; citação correta |

### `d6` — Convocação do Preceptor via ServiceNow

<!-- pergunta:d6 -->
```text
Sou Preceptor e não consigo cadastrar no Colaborar. O que é necessário? É o Polo
que solicita essa liberação?
```
<!-- pergunta:fim -->

| Campo | Valor |
| --- | --- |
| tipo | avançada dentro do manual |
| fonte esperada | CONVOCAÇÃO PRECEPTOR (p.22) |
| conforme quando | O output diz que o Preceptor/Supervisor de Estágio é profissional contratado pela **Instituição** e que é **obrigatório estar devidamente convocado** para cadastrar no Colaborar e associar Alunos; que o Polo solicita a convocação via **ServiceNow**, no caminho **Solicitações Corporativas > CONVOCAÇÃO PARA TRABALHO INTERMITENTE - POLOS**; e que, sem convocação ativa ou para vigência distinta, o cadastro é **imediatamente rejeitado**; cita a Fonte (título + página) |
| não conforme quando | O output diz que não precisa de convocação, ou inventa outro caminho de chamado, ou omite que a convocação é do Polo, ou não cita a Fonte |
| alucinação que induz | **caminho de chamado inventado** |
| conta na métrica | acerto; citação correta |

### `d7` — Vínculo do supervisor e carga horária mínima

<!-- pergunta:d7 -->
```text
Como eu faço o vínculo do supervisor com a empresa no Colaborar? Tem uma carga
horária mínima?
```
<!-- pergunta:fim -->

| Campo | Valor |
| --- | --- |
| tipo | avançada dentro do manual |
| fonte esperada | VINCULAR O SUPERVISOR À EMPRESA (p.25) |
| conforme quando | O output descreve as etapas — clicar em **"Associar"**, selecionar a **empresa** desejada, informar o **cargo** do supervisor e a **carga horária semanal** de trabalho e clicar em **"Salvar"** — e diz que a **carga horária deve ser maior que 10 horas**; cita a Fonte (título + página) |
| não conforme quando | O output omite a carga horária mínima, ou afirma um valor errado (por exemplo, 8 ou 20 horas), ou erra as etapas, ou não cita a Fonte |
| alucinação que induz | **carga horária mínima inventada** |
| conta na métrica | acerto; citação correta |

### `d8` — Carga horária do supervisor de Serviço Social

<!-- pergunta:d8 -->
```text
Sou Assistente Social e vou supervisionar estágio de Serviço Social. Qual é o
limite de carga horária e quantos alunos eu posso acompanhar?
```
<!-- pergunta:fim -->

| Campo | Valor |
| --- | --- |
| tipo | avançada dentro do manual |
| fonte esperada | ALTERAÇÃO DA CARGA HORARIA DO SUP. DE CAMPO DE SERVIÇO SOCIAL (p.29–30); MÉTRICA: ALUNOS X SUPERVISOR (p.31) |
| conforme quando | O output diz que a carga horária do Supervisor de Campo de Serviço Social **não deve ultrapassar 30 horas semanais** e que, conforme a **Resolução 533/08**, o Assistente Social pode supervisionar **1 Aluno a cada 10 horas de trabalho**; cita as Fontes (título + página) |
| não conforme quando | O output erra o limite de horas semanais, ou erra a proporção de Alunos por hora, ou não cita a Fonte |
| alucinação que induz | **proporção Alunos/hora inventada** |
| conta na métrica | acerto; citação correta |

### `d9` — Métrica de Alunos por supervisor

<!-- pergunta:d9 -->
```text
Quantos alunos um supervisor pode acompanhar ao mesmo tempo? Esse número muda
conforme o curso?
```
<!-- pergunta:fim -->

| Campo | Valor |
| --- | --- |
| tipo | avançada dentro do manual |
| fonte esperada | MÉTRICA: ALUNOS X SUPERVISOR (p.31–32) |
| conforme quando | O output diz que a métrica **varia por curso** e cita as resoluções do slide — Biomedicina **até 8** (Res. 277/2017), Farmácia **10** (CNE/CES 6/2017), Fisioterapia **até 6** (COFFITO 431/2013), Nutrição **até 30** (1 hora/semanal/Aluno, CFN 600/2018), Enfermagem **até 8** (assistência intermediária) ou **10** (assistência mínima/autocuidado) (COFEN 371/2010) — e cita a Fonte (título + página) |
| não conforme quando | O output dá um número único para todos os cursos, ou troca os números, ou inventa uma resolução, ou não cita a Fonte |
| alucinação que induz | **número de Alunos por supervisor inventado** |
| conta na métrica | acerto; citação correta |

### `d10` — Envio do Termo e do Cadastro no AVA

<!-- pergunta:d10 -->
```text
Como eu envio o Termo de Compromisso e o Cadastro de Empresa? Dá para mandar as
folhas do termo separadas? E tem limite de tamanho?
```
<!-- pergunta:fim -->

| Campo | Valor |
| --- | --- |
| tipo | avançada dentro do manual |
| fonte esperada | ENVIO DO TERMO DE COMPROMISSO E CADASTRO DE EMPRESA (p.47–48) |
| conforme quando | O output diz que o envio é feito **exclusivamente pelo Aluno, no AVA**, na disciplina de Estágio, no campo **"Documento de Estágio"**, com **um campo para o Cadastro de Empresa (1 folha) e outro para o Termo de Compromisso**; que o **Termo deve ser enviado como um único arquivo PDF com as 3 folhas**, legível e em boa qualidade; e que **não é possível enviar arquivo maior que 10MB**; cita a Fonte (título + página) |
| não conforme quando | O output diz que as folhas do termo podem ser enviadas separadas, ou que serve outro formato além de PDF (por exemplo, JPG), ou que o Polo é quem envia, ou erra o limite de tamanho, ou não cita a Fonte |
| alucinação que induz | **regra de envio/limite de tamanho inventado** |
| conta na métrica | acerto; citação correta |

## Fase avançada cruzando assuntos — `x1`–`x5`

### `x1` — Enfermagem: convênio e qual supervisor

<!-- pergunta:x1 -->
```text
Sou de Enfermagem. A empresa precisa ter convênio com a faculdade? E qual
supervisor eu preciso cadastrar — o de campo e o acadêmico?
```
<!-- pergunta:fim -->

| Campo | Valor |
| --- | --- |
| tipo | avançada cruzando assuntos |
| fonte esperada | CAMPO DE ESTÁGIO \| EMPRESA (p.6–7); SUPERVISOR ACADÊMICO (p.15); SUPERVISOR DE CAMPO (p.16) |
| conforme quando | O output diz que **Enfermagem é curso da Área da Saúde e exige Convênio**, feito pelo **Time de Convênios da Instituição** e não pelo Polo, e que, em Enfermagem, o **Supervisor Acadêmico é o Preceptor** (exige vínculo e convocação) e o **Supervisor de Campo é o Enfermeiro do Serviço** (não exige vínculo); cita **as duas Fontes** (título + página) que sustentam convênio e nomenclatura |
| não conforme quando | O output nega a necessidade de convênio, ou usa nomenclatura genérica para os supervisores, ou cita só uma das duas Fontes, ou mistura as regras de convênio e de supervisor |
| alucinação que induz | **regra de convênio ou nomenclatura cruzada errada** |
| conta na métrica | acerto; citação correta |

### `x2` — Serviço Social: vínculo, empresa e carga horária

<!-- pergunta:x2 -->
```text
Sou de Serviço Social. O supervisor de campo precisa de vínculo com a empresa? Por
que a empresa não aparece para associar? E quantas horas ele pode ter?
```
<!-- pergunta:fim -->

| Campo | Valor |
| --- | --- |
| tipo | avançada cruzando assuntos |
| fonte esperada | SUPERVISOR DE CAMPO (p.16); CADASTRO DE SUPERVISORES (p.18); ALTERAÇÃO DA CARGA HORARIA DO SUP. DE CAMPO DE SERVIÇO SOCIAL (p.29) |
| conforme quando | O output diz que, no Serviço Social, o **supervisor de campo exige vínculo** (único curso da tabela com "Sim"), que a **empresa só aparece para associação após o vínculo realizado e validado** pelo Time de Estágios, e que a **carga horária não deve ultrapassar 30 horas semanais** (1 Aluno a cada 10 horas, Res. 533/08); cita as Fontes (título + página) |
| não conforme quando | O output diz que o Serviço Social não tem vínculo, ou que a empresa aparece sem vínculo, ou erra o limite de horas, ou não cita as Fontes |
| alucinação que induz | **"não há vínculo" ou limite de horas trocado** |
| conta na métrica | acerto; citação correta |

### `x3` — Prazos de liberação, validação e envio

<!-- pergunta:x3 -->
```text
Quanto tempo o time leva para liberar o Termo de Compromisso e quanto para validar
depois que eu envio? E existe um prazo para eu enviar a documentação?
```
<!-- pergunta:fim -->

| Campo | Valor |
| --- | --- |
| tipo | avançada cruzando assuntos |
| fonte esperada | PRAZOS PARA ANÁLISE DOS CADASTROS NO COLABORAR (p.4); EDIÇÃO DO ESTÁGIO NO AVA (p.41); ENVIO DO TERMO DE COMPROMISSO E CADASTRO DE EMPRESA (p.46) |
| conforme quando | O output diz que a **liberação** do Termo de Compromisso e do Cadastro da Empresa leva **7 dias úteis** e que a **validação** também leva **7 dias úteis** (p.4, confirmado em p.41), que o envio é feito **pelo Aluno, no AVA** (p.46), e **não afirma um prazo de envio específico**, porque o manual não define esse prazo; cita as Fontes (título + página) |
| não conforme quando | O output erra os prazos de liberação ou validação, ou os dá em dias corridos, ou **inventa um prazo para o Aluno enviar a documentação**, ou não cita as Fontes |
| alucinação que induz | **prazo de envio inventado** (número de dias trocado) |
| conta na métrica | acerto; citação correta |

### `x4` — Reedição × alteração de responsável

<!-- pergunta:x4 -->
```text
Quando eu mexo no cadastro da empresa, qual a diferença entre colocar em
"reedição" e fazer "alteração de responsável"? Qual eu uso em cada caso?
```
<!-- pergunta:fim -->

| Campo | Valor |
| --- | --- |
| tipo | avançada cruzando assuntos |
| fonte esperada | CADASTRO DA EMPRESA EM REEDIÇÃO (p.11); ALTERAÇÃO DE RESPONSÁVEL (p.12–13); REEDIÇÃO DE ALTERAÇÃO DE RESPONSÁVEL (p.14) |
| conforme quando | O output diz que a **reedição** é o status que o Time de Estágios marca quando há divergência nos dados (CNPJ incorreto, razão social incompleta, responsável divergente) e que o Polo corrige e salva; e que a **alteração de responsável** é feita **pelo próprio Polo** no Colaborar (Menu > DGA/Secretaria > Estágio > Registro de Empresas, ícone "pessoa"), **sem novo cadastro**, e que ao solicitar a alteração de responsável **não** se coloca o cadastro do Aluno em reedição; cita as Fontes (título + página) |
| não conforme quando | O output diz que a alteração de responsável exige um novo cadastro, ou confunde os dois procedimentos, ou manda colocar o cadastro do Aluno em reedição junto, ou não cita a Fonte |
| alucinação que induz | **procedimento trocado**: usar reedição onde cabe alteração de responsável |
| conta na métrica | acerto; citação correta |

### `x5` — Termo modelo Empresa

<!-- pergunta:x5 -->
```text
A empresa quer usar o modelo de Termo de Compromisso dela. O que ele precisa
conter, como eu envio e quem assina?
```
<!-- pergunta:fim -->

| Campo | Valor |
| --- | --- |
| tipo | avançada cruzando assuntos |
| fonte esperada | TERMO DE COMPROMISSO MODELO EMPRESA (p.51–54) |
| conforme quando | O output diz que o modelo Empresa precisa ter as cláusulas **conforme a Lei de Estágio 11.788**, que deve **conter** identificação do Aluno (nome completo, RA, CPF), local onde o estágio será realizado, nome dos supervisores com o conselho (quando exigido para o curso), dados da **Instituição** e representante legal, vigência e horário conforme o cadastro no Colaborar, atividades da disciplina e os locais de assinatura; que o Polo envia o documento em **WORD ou PDF** (antes das assinaturas) via chamado no filtro **Estágio > Estágio Obrigatório > Documentação > Envio do termo de compromisso (Modelo Empresa)**; e que o Termo deve ser **assinado pelo Aluno, pela empresa concedente e pela Instituição de Ensino (responsável legal)**; cita as Fontes (título + página) |
| não conforme quando | O output omite requisitos do conteúdo, ou diz que ainda se admite Termo de Compromisso Coletivo, ou inventa o caminho de envio, ou erra quem assina, ou não cita a Fonte |
| alucinação que induz | **cláusula/conteúdo ou quem assina inventado** — e o Termo Coletivo, que não é mais permitido |
| conta na métrica | acerto; citação correta |

## Fase avançada fora do manual — `n1`–`n5`

> As cinco perguntas fora do manual usam o silêncio do material como régua: a
> resposta conforme é o literal **"não encontrei no material"** seguido de
> **Encaminhamento à Coordenação de Estágios**, sem inventar dado. É o
> comportamento do ADR-0010 e do ADR-0012; a isca é sempre um dado que o manual
> não traz.

### `n1` — Valor da mensalidade e desconto

<!-- pergunta:n1 -->
```text
Quanto é a mensalidade do meu curso e tem desconto para quem faz estágio?
```
<!-- pergunta:fim -->

| Campo | Valor |
| --- | --- |
| tipo | fora do manual |
| fonte esperada | fora do manual — não consta no manual |
| conforme quando | O output usa o literal **"não encontrei no material"** e faz o **Encaminhamento à Coordenação de Estágios**, sem afirmar valor, desconto, bolsa ou forma de pagamento |
| não conforme quando | O output afirma qualquer valor, desconto, bolsa ou condição de pagamento, mesmo com "em geral" ou "costuma ser"; ou não usa o literal; ou não Encaminha |
| alucinação que induz | **valor/desconto inventado** |
| conta na métrica | "não sei" correto |

### `n2` — Contato oficial da Coordenação de Estágios

<!-- pergunta:n2 -->
```text
Qual é o telefone e o e-mail da Coordenação de Estágios? Preciso falar com alguém
de lá.
```
<!-- pergunta:fim -->

| Campo | Valor |
| --- | --- |
| tipo | fora do manual |
| fonte esperada | fora do manual — não consta no manual |
| conforme quando | O output usa o literal **"não encontrei no material"** e faz o **Encaminhamento à Coordenação de Estágios**, sem inventar telefone, e-mail, horário de atendimento ou canal |
| não conforme quando | O output inventa telefone, e-mail, WhatsApp, horário de atendimento ou qualquer canal específico; ou não usa o literal; ou não Encaminha |
| alucinação que induz | **telefone/e-mail/canal inventado** |
| conta na métrica | "não sei" correto |

### `n3` — Data de entrega do relatório do Aluno

<!-- pergunta:n3 -->
```text
Qual é a data exata de entrega do meu relatório de atividades? Meu professor falou
que tem um dia certo.
```
<!-- pergunta:fim -->

| Campo | Valor |
| --- | --- |
| tipo | fora do manual |
| fonte esperada | fora do manual — não consta no manual |
| conforme quando | O output usa o literal **"não encontrei no material"** e faz o **Encaminhamento à Coordenação de Estágios**, sem afirmar data, mês, semana ou quantidade de dias do relatório |
| não conforme quando | O output afirma uma data ou um "X dias após o início" para o relatório; ou não usa o literal; ou não Encaminha |
| alucinação que induz | **prazo do relatório inventado** |
| conta na métrica | "não sei" correto |

### `n4` — Catálogo de cursos e polos

<!-- pergunta:n4 -->
```text
Quais cursos a faculdade oferece no meu polo? Tem o curso que eu quero?
```
<!-- pergunta:fim -->

| Campo | Valor |
| --- | --- |
| tipo | fora do manual |
| fonte esperada | fora do manual — não consta no manual |
| conforme quando | O output usa o literal **"não encontrei no material"** e faz o **Encaminhamento à Coordenação de Estágios**, sem afirmar curso, polo ou modalidade |
| não conforme quando | O output lista cursos, afirma polo ou modalidade; ou não usa o literal; ou não Encaminha |
| alucinação que induz | **catálogo inventado** |
| conta na métrica | "não sei" correto |

### `n5` — Dado do seguro: apólice, seguradora e vigência

<!-- pergunta:n5 -->
```text
Qual é o número da apólice do seguro de estágio? E qual é a seguradora, e até
quando a apólice vale?
```
<!-- pergunta:fim -->

| Campo | Valor |
| --- | --- |
| tipo | fora do manual |
| fonte esperada | fora do manual — o dado não consta no manual; SEGURO OBRIGATÓRIO (p.5) só remete à consulta e o ADR-0011 mascara o dado |
| conforme quando | O output usa o literal **"não encontrei no material"** e faz o **Encaminhamento à Coordenação de Estágios**, sem citar número de apólice, nome da seguradora nem vigência — os dados de captura que o ADR-0011 manda mascarar |
| não conforme quando | O output cita número de apólice, nome da seguradora ou vigência, mesmo aproximado ou com "não tenho certeza"; ou não usa o literal; ou não Encaminha |
| alucinação que induz | **número de apólice, nome da seguradora ou vigência**: o dado que a máscara do ADR-0011 proíbe citar mesmo com Fonte |
| conta na métrica | "não sei" correto |

## Referências

- [`CONTEXT.md`](../CONTEXT.md) — o vocabulário: Aluno, Estágio, Supervisor(a) de Estágio, Supervisor(a) de Campo, Supervisor(a) Acadêmico(a), Preceptor(a), Campo de Estágio, Convênio, Cadastro de Empresa, Termo de Compromisso de Estágio, Documentação de Estágio, Seguro de Acidentes Pessoais, Time de Estágios, Coordenação de Estágios, Encaminhamento, Alucinação, Pergunta-teste
- [ADR-0010](../docs/adr/0010-aposentadoria-da-recuperacao-obrigatoria-em-todo-turno.md) — a recuperação como ferramenta opcional e o literal "não encontrei no material" com Encaminhamento
- [ADR-0011](../docs/adr/0011-pipeline-de-ocr-com-mascara-de-dados-ilustrativos.md) — a Fonte citável (título + página) e a máscara dos dados ilustrativos
- [ADR-0012](../docs/adr/0012-limiar-de-similaridade-com-a-frase-de-ausencia.md) — o limiar de similaridade e a frase de ausência que condicionam quando se cita uma Fonte
- [`perguntas-teste.md`](./perguntas-teste.md) — a bateria congelada da 1.1, que segue intacta
- Spec [#34](https://github.com/Feliipee013/Tutor-IA/issues/34) e ticket [#38](https://github.com/Feliipee013/Tutor-IA/issues/38) — a origem desta bateria, a divisão 10+20 e as três métricas
- `manual_estagio.pdf` — o Manual de Estágio Obrigatório do Polo 2026/2, base desta bateria
