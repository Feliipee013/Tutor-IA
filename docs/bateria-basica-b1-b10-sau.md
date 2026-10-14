# Bateria básica b1–b10 passada no S.A.U. — pergunta, resposta e checagem no Manual

## Condições da rodada (para a leitura não variar depois)

- Perguntas: `perguntas-teste/bateria-manual.md`, blocos `b1`–`b10`, histórico vazio.
- Caminho real do turno: `sau.graph.graph.executar_turno` com `OpcoesDoManual`.
- Gerador: `qwen2.5:3b` no Ollama do host; `temperature 0`, `seed` 20260926,
  `num_predict 512`.
- Recuperação: índice Chroma `manual-estagio-obrigatorio` com **57 chunks**,
  embedding local `nomic-embed-text`, `k = 4`, limiar `0.72`.
- Data: 2026-10-14. Julgamento abaixo é de pessoa lendo o Manual em PDF
  (`corpus/`), não de script.

## Resumo honesto

| Id | Conteúdo tem base no Manual? | Cita a Fonte no texto? | Obs |
| --- | --- | --- | --- |
| b1 | Sim (p.3) | **Não** | Fonte p.1 veio junto e é irrelevante |
| b2 | Sim (p.4, os 7 prazos) | **Não** | — |
| b3 | Sim (p.5, MA + IPA) | **Não** | Não cita apólice/seguradora — correto (máscara) |
| b4 | Sim (p.6 + p.7) | **Não** | Prisma/GO vêm de p.7, que foi recuperada |
| b5 | Sim (p.7; extra de p.11 existe) | **Não** | Ecoa "Aluno:" no início (defeito de forma) |
| b6 | Sim (p.8–p.9 + p.7) | **Não** | Resposta completa |
| b7 | Sim (p.9–p.10, com o exemplo) | **Não** | — |
| b8 | **Não — inverteu a regra** | **Não** | Diz que nos 6 cursos o nome não consta; o Manual diz o oposto |
| b9 | Sim (p.16 + p.17 + p.18) | Parcial (cita "página 16", sem título) | Resposta completa |
| b10 | Sim no núcleo (p.33–p.34); extra de p.30 parcial | **Não** | Troca "Coordenação de Curso" por genérico |

Ponto central: o S.A.U. respondeu **ancorado** em 9/10, mas **não citou
título + página em nenhuma resposta de forma completa** — a
`ORIENTACAO_DE_FONTE` não virou citação visível ao Aluno nesta rodada.

## b1 — Data limite do período de estágio

**Pergunta do Aluno:** Até quando eu posso realizar o estágio obrigatório neste
semestre? Quem define essa data limite?

**Resposta do S.A.U. (literal):** Até quando você pode realizar o estágio
obrigatório neste semestre está definido pelo time de planejamento acadêmico e
está disponível ao Polo no sistema Colaborar em: Menu > DGA/Secretaria > Estágio > Período ou na base de conhecimento.

**Recuperação que ele trouxe:** consulta do roteador `data limite estágio
obrigatório` | pontuações `[0.7616, 0.7529, 0.7014, 0.6704]` | descartes pelo
limiar: 2 | fontes entregues: `ESTÁGIO OBRIGATÓRIO (p. 1)`, `PERÍODO PARA
REALIZAÇÃO DO ESTÁGIO (p. 3)`.

**Verificação:** **Tem no material.** Trecho de p.3: "A data limite para a
realização do Estágio Curricular Obrigatório em campo é definida pelo time de
planejamento acadêmico e está disponível ao Polo no sistema Colaborar em: Menu >
DGA/Secretaria > Estágio > Período ou na base de conhecimento." Não afirma data —
correto. A p.1 entregue junto ("ESTÁGIO OBRIGATÓRIO | 2026/2") é capa, não
sustenta nada. Faltou citar a Fonte no texto.

## b2 — Prazos de análise no Colaborar

**Pergunta do Aluno:** Quanto tempo o Time de Estágios leva para analisar cada
cadastro que eu faço no Colaborar? Os prazos são em dias úteis?

**Resposta do S.A.U. (literal):** Os prazos para análise dos cadastros no
Colaborar são em dias úteis: - Cadastro de empresa: 4 dias - Alteração do
responsável da empresa: 5 dias - Cadastro de Supervisor de Campo/ Supervisor
Acadêmico/Preceptor: 4 dias - Vínculo do Supervisor/Empresa: 4 dias - Análise
Declaração de Dispensa: 5 dias - Liberação do Termo de Compromisso e do Cadastro
da Empresa: 7 dias - Validação do Termo de Compromisso e do Cadastro da Empresa:
7 dias. Aluno, caso tenha mais dúvidas sobre esses prazos, procure a Coordenação
de Estágios.

**Recuperação que ele trouxe:** `prazos cadastro colaborar` | `[0.7673, 0.7118,
0.7026, 0.6759]` | descartes: 3 | fonte entregue: `PRAZOS PARA ANÁLISE DOS
CADASTROS (p. 4)`.

**Verificação:** **Tem no material.** Trecho de p.4: "Confira os prazos em dias
úteis: Cadastro de empresa: 4 dias; Alteração do responsável da empresa: 5 dias;
Cadastro de Supervisor de Campo / Supervisor Acadêmico / Preceptor: 4 dias;
Vínculo do Supervisor/Empresa: 4 dias; Análise Declaração de Dispensa: 5 dias;
Liberação do Termo de Compromisso e do Cadastro da Empresa: 7 dias; Validação do
Termo de Compromisso e do Cadastro da Empresa: 7 dias." Os 7 valores conferem.
Faltou citar a Fonte no texto.

## b3 — Seguro obrigatório e o que cobre

**Pergunta do Aluno:** O estágio obrigatório tem seguro? O que exatamente esse
seguro cobre — e o que ele NÃO cobre?

**Resposta do S.A.U. (literal):** O seguro obrigatório cobre duas coberturas
principais: MA - Morte acidental e IPA - Invalidez Permanente Parcial ou Total
por Acidente. Demais situações não estão contempladas.

**Recuperação que ele trouxe:** `seguro estágio obrigatório cobre o que e não
cobre` | `[0.7839, 0.7252, 0.7136, 0.7127]` | descartes: 2 | fontes:
`SEGURO OBRIGATÓRIO (p. 5)`, `ESTÁGIO OBRIGATÓRIO (p. 1)`.

**Verificação:** **Tem no material.** Trecho de p.5: "De acordo com a Lei
11.788/08 os alunos precisam possuir a cobertura do seguro estágio durante a
vigência da disciplina Estágio Curricular Obrigatório… a apólice vigente contempla
duas coberturas: MA - Morte acidental e IPA - Invalidez Permanente Parcial ou
Total por Acidente. Demais situações não estão contempladas." Não cita número de
apólice, seguradora nem vigência — correto, é dado mascarado pelo ADR-0011.
Faltou citar a Fonte e a Lei no texto.

## b4 — Convênio obrigatório na área da Saúde

**Pergunta do Aluno:** Sou de um curso da área da Saúde. Preciso de convênio
para fazer o estágio? O que acontece se não tiver convênio?

**Resposta do S.A.U. (literal):** O convênio é obrigatório para os cursos da
área da Saúde, como Biomedicina, Enfermagem, Farmácia, Fisioterapia, Nutrição e
Radiologia. Sem o convênio, os alunos desses cursos não podem iniciar o estágio.
Você precisa verificar se a empresa em que deseja realizar o estágio está listada
no portal Prisma. Em caso de dúvida, entre em contato com o GO responsável pelo
seu Polo/Unidade.

**Recuperação que ele trouxe:** `convênio estágio saúde` | `[0.7756, 0.7469,
0.6856, 0.6836]` | descartes: 2 | fontes: `CAMPO DE ESTÁGIO | EMPRESA (p. 6)`,
`CAMPO DE ESTÁGIO | EMPRESA (p. 7)`.

**Verificação:** **Tem no material.** Trecho de p.6: "Convênio: obrigatório
somente para os cursos da Área da Saúde (Biomedicina, Enfermagem, Farmácia,
Fisioterapia, Nutrição e Radiologia)… Sem o convênio, os alunos da Saúde não
podem iniciar o estágio!" Trecho de p.7: "A lista oficial de empresas conveniadas
está no portal Prisma. Em caso de dúvida, o Polo deve acionar o GO responsável
pelo seu Polo/Unidade." Prisma/GO vêm de p.7, que foi recuperada — não é invenção.
Faltou citar as Fontes no texto.

## b5 — Convênio × Cadastro de Empresa

**Pergunta do Aluno:** Qual é a diferença entre convênio e cadastro de empresa?
Quem faz cada um — eu, o Polo ou a faculdade?

**Resposta do S.A.U. (literal):** Aluno: Qual é a diferença entre convênio e
cadastro de empresa? Quem faz cada um — eu, o Polo ou a faculdade? Convênio é
obrigatório para a Saúde. O cadastro no sistema é feito pelo Time de Convênios
da IES (Regulação e Controle), e o Polo será informado via chamado. Portanto, o
Polo não deve realizar o cadastro sozinho. O cadastro de empresa é usado para
cursos fora da área da Saúde (como Licenciaturas e Engenharias) e é feito
diretamente pelo Polo no sistema Colaborar. Não é necessário realizar um novo
cadastro se a empresa já estiver cadastrada. Caso haja divergências nos dados,
como CNPJ incorreto, razão social incompleta ou nome de responsável divergente,
o Time de Estágios sinalizará o cadastro com o status "REEDIÇÃO/ALTERAÇÃO".

**Recuperação que ele trouxe:** consulta longa com a própria pergunta |
`[0.8291, 0.7883, 0.7833, 0.7687]` | descartes: 0 | fontes: `CAMPO DE ESTÁGIO |
EMPRESA (p. 7)`, `CADASTRAR EMPRESA (p. 10)`, `CADASTRO DA EMPRESA EM REEDIÇÃO
(p. 11)`, `CADASTRAR EMPRESA (p. 9)`.

**Verificação:** **Tem no material, com dois reparos de forma.** Trecho de p.7:
"Convênio: obrigatório para a Saúde: quem faz o cadastro no sistema é o Time de
Convênios da IES (Regulação e Controle), e o Polo será informado via chamado…
o Polo não deve realizar o cadastro sozinho… Cadastro de Empresa: usado para
cursos fora da área da Saúde (ex: Licenciaturas, Engenharias) e é feito
diretamente pelo Polo no sistema colaborar." O parágrafo de reedição existe em
p.11 (CNPJ incorreto, razão social incompleta, responsável divergente) — extra
correto, não inventado. Reparos: a resposta ecoa "Aluno:" + a pergunta no início
e não cita nenhuma Fonte no texto.

## b6 — Cadastrar empresa no Colaborar

**Pergunta do Aluno:** Como eu cadastro a empresa concedente no Colaborar? Qual
o caminho e o que eu preciso conferir antes?

**Resposta do S.A.U. (literal):** Para cadastrar a empresa concedente no sistema
Colaborar, você precisa seguir os seguintes passos: 1. Acesse o sistema Colaborar
através do menu: MENU > DGA/Secretaria > Estágio > Registro de Empresas. 2. Para
verificar se a empresa já está cadastrada no sistema, você pode usar as teclas
Ctrl + F para facilitar a busca com uma palavra-chave (ex: razão social da
empresa) ou pela barra de pesquisa "CNPJ". 3. Se a empresa não estiver
cadastrada, você deve clicar em "Novo Cadastro" e preencher todos os campos
obrigatórios, garantindo que todas as informações estejam corretas e bem
escritas. Evite abreviações ou nomes incompletos. 4. Certifique-se de preencher
corretamente a razão social da empresa, pois isso é essencial para que o cadastro
seja reconhecido. Se a razão social estiver incorreta, o sistema não reconhecerá
o vínculo com a razão social cadastrada na Receita Federal e o cadastro entrará
automaticamente em reedição. 5. Se a razão social estiver correta, mas o campo
de estágio não estiver liberado na associação, é importante cadastrar de forma
completa para que todas as informações estejam registradas no sistema. Para mais
detalhes, consulte a base de conhecimento ou participe da oficina de
conhecimento. Se tiver dúvidas, entre em contato com o GO responsável pelo seu
Polo/Unidade.

**Recuperação que ele trouxe:** `cadastro empresa concedente colaborar` |
`[0.7724, 0.7217, 0.7216, 0.6974]` | descartes: 1 | fontes: `CADASTRAR EMPRESA
(p. 8)`, `CADASTRAR EMPRESA (p. 9)`, `CAMPO DE ESTÁGIO | EMPRESA (p. 7)`.

**Verificação:** **Tem no material.** Trecho de p.8: "Para seguir com o cadastro
da empresa, acesse o sistema Colaborar em: MENU > DGA/Secretaria > Estágio >
Registro de Empresas e consulte pelo CNPJ… Pode ser utilizado as teclas Ctrl + F…
ou pela barra de pesquisa 'CNPJ'." Trecho de p.9: "Clique em 'Novo Cadastro';
Preencha todos os campos obrigatórios (identificados com um asterisco *)…
evitando abreviações ou nomes incompletos… Caso o Polo cadastre apenas o nome
fantasia… o cadastro entrará automaticamente em reedição… se cadastrado apenas o
nome conforme razão social da receita federal, o campo de estágio poderá não ser
liberado na associação. Importante cadastrar de forma completa." O fechamento
(base de conhecimento, oficina, GO) vem de p.7, que foi recuperada. Faltou citar
as Fontes no texto.

## b7 — Razão social da empresa

**Pergunta do Aluno:** No cadastro da empresa, o que eu coloco no campo da razão
social? Tem um jeito certo de preencher?

**Resposta do S.A.U. (literal):** Para preencher o campo da razão social no
cadastro da empresa, você deve informar a razão social da Receita Federal,
seguida pelo nome da fantasia. Exemplo: Prefeitura Municipal de São Paulo /
Escola João e Maria – Ensino Fundamental.

**Recuperação que ele trouxe:** `razão social cadastro empresa` | `[0.7876,
0.7638, 0.7355, 0.7276]` | descartes: 0 | fontes: `CADASTRAR EMPRESA (p. 9)`,
`CADASTRAR EMPRESA (p. 8)`, `CADASTRO DA EMPRESA EM REEDIÇÃO (p. 11)`,
`CADASTRAR EMPRESA (p. 10)`.

**Verificação:** **Tem no material.** Trecho de p.10: "Informe a razão social da
Receita Federal + o nome da fantasia: Prefeitura Municipal de São Paulo / Escola
João e Maria – Ensino Fundamental." Trecho de p.9: só o nome fantasia leva à
reedição; só a razão social pode não liberar o campo de estágio. Resposta curta
e fiel. Faltou citar a Fonte no texto.

## b8 — Supervisor Acadêmico ⚠️ RESPOSTA COM REGRA INVERTIDA

**Pergunta do Aluno:** Quem é o Supervisor Acadêmico e quando eu preciso
cadastrar ele? Vale para o meu curso?

**Resposta do S.A.U. (literal):** O Supervisor Acadêmico é o representante da
Instituição de Ensino Superior (IES) que acompanha o estágio. Para os alunos de
alguns cursos, como Biomedicina, Enfermagem, Farmácia, Fisioterapia, Nutrição e
Serviço Social, o nome do Supervisor Acadêmico não constará no termo de
compromisso e, portanto, não é necessário informar no momento da associação.
Para esses cursos, antes de associar o aluno, é necessário cadastrar o Supervisor
Acadêmico no sistema colaborar e, em alguns casos, vinculá-lo à empresa.

**Recuperação que ele trouxe:** `Supervisor Acadêmico, quando cadastrar
Supervisor Acadêmico` | `[0.8029, 0.7841, 0.7821, 0.7744]` | descartes: 0 |
fontes: `CADASTRO DE SUPERVISORES (p. 17)`, `SUPERVISOR ACADÊMICO (p. 15)`,
`SUPERVISOR DE CAMPO (p. 16)`, `CADASTRO DO SUPERVISOR EM REEDIÇÃO (p. 24)`.

**Verificação:** **NÃO tem no material como escrito — a regra saiu invertida.**
Trecho de p.15: "Para os alunos de 'demais cursos' o nome do supervisor
acadêmico não constará no termo de compromisso e, portanto, não é necessário
informar no momento da associação. Já nos cursos de Biomedicina, Enfermagem,
Farmácia, Fisioterapia, Nutrição e Serviço Social… antes de associar ao aluno,
primeiramente será necessário cadastrar o supervisor acadêmico no sistema
colaborar e, em alguns casos, vinculá-lo à empresa." A resposta trocou o sujeito:
atribuiu o "não consta / não precisa" aos 6 cursos, quando o Manual o atribui
aos "demais cursos". A recuperação trouxe a página certa (p.15) — o erro foi do
redator, não da busca. É a única b com conteúdo não conforme, e também sem
citação de Fonte.

## b9 — Supervisor de Campo

**Pergunta do Aluno:** Quem é o Supervisor de Campo e quando ele precisa ser
cadastrado no sistema?

**Resposta do S.A.U. (literal):** O Supervisor de Campo é o profissional
designado pela empresa para orientar e acompanhar o estudante durante a execução
do estágio nas instalações da empresa. Para cadastrar um Supervisor de Campo no
sistema, você deve seguir os seguintes passos: 1. Clique em "Novo Cadastro" no
menu do sistema. 2. Preencha os campos necessários, incluindo o nome, formação
acadêmica, número de conselho, e outros dados relevantes. 3. Selecione o curso
para o qual o Supervisor de Campo está sendo cadastrado. 4. Clique em "Salvar"
para finalizar o cadastro. Para os alunos dos cursos de Biomedicina, Enfermagem,
Farmácia, Fisioterapia, Nutrição e Serviço Social, é necessário cadastrar o
Supervisor de Campo no sistema colaborar antes de associar o aluno. Para os
demais cursos, o Supervisor de Campo é indicado durante o processo de associação.
Se você ainda não tem o Supervisor de Campo cadastrado, você deve seguir os
passos acima para realizar o cadastro. Se a empresa não aparecer no momento da
associação, verifique se o vínculo entre o Supervisor de Campo e a Empresa já foi
realizado e se o status consta como "validado" no sistema. Para mais
informações, consulte a página 16 do manual de estágio.

**Recuperação que ele trouxe:** `Supervisor de Campo, cadastrado no sistema` |
`[0.836, 0.8313, 0.7714, 0.7688]` | descartes: 0 | fontes: `SUPERVISOR DE CAMPO
(p. 16)`, `CADASTRO DE SUPERVISORES (p. 17)`, `CADASTRAR EMPRESA (p. 9)`,
`Para os alunos de "demais cursos", o supervisor de (p. 18)`.

**Verificação:** **Tem no material.** Trecho de p.16: "É o profissional
designado pela empresa concedente para orientar e acompanhar o estudante durante
a execução do estágio nas instalações da empresa… Nos cursos de Biomedicina,
Enfermagem, Farmácia, Fisioterapia, Nutrição e Serviço Social, antes de associar
o aluno, primeiramente será necessário cadastrar o supervisor de campo no sistema
colaborar." Trecho de p.17: "Para cadastrar novo(a) supervisor(a), no colaborar,
acesse: MENU > DGA/Secretaria > Estágio > Supervisor de Estágio > Novo Cadastro…
informar… Nome, Formação Acadêmica, Número de Conselho etc… selecione o curso…
clique em 'salvar'." Trecho de p.18: "Para os alunos de 'demais cursos', o
supervisor de campo é indicado durante o processo de associação… Para o curso de
Serviço Social, a empresa só se tornará visível para associação após o vínculo
entre o Supervisor de Campo e a Empresa ter sido realizado e validado." O passo
a passo que parecia suspeito confere com p.17, e o fecho sobre vínculo validado
confere com p.18. A menção final à "página 16" aponta para a página certa, mas
sem o título da Fonte — citação parcial.

## b10 — Limite de carga horária e Declaração de Dispensa

**Pergunta do Aluno:** Qual é o limite de carga horária do estágio obrigatório?
E como eu envio a Declaração de Dispensa?

**Resposta do S.A.U. (literal):** O limite de carga horária do estágio
obrigatório é de 6 horas diárias e 30 horas semanais. Para a Declaração de
Dispensa, você deve acessar o sistema Colaborar, seguir os passos descritos no
modelo de declaração disponível no menu > dga/secretaria > estágio > solicitação
de dispensa de estágio. Os arquivos devem ser enviados no formato PDF, JPG, JPEG
ou PNG, e devem conter todas as informações, devidamente assinadas e legíveis.
Para alterar a carga horária do supervisor de campo, você deve abrir um chamado
em Graduação EAD > Solicitações Acadêmicas > Estágio > Estágio Obrigatório >
Avaliação > Supervisor de Estágio e anexe as declarações de todas as empresas. A
aprovação da Coordenação é necessária para realizar a adequação e atualização da
carga horária no sistema. Para mais informações, encaminhe sua dúvida para a
Coordenação de Estágios.

**Recuperação que ele trouxe:** `limite de carga horária estágio obrigatório
declaração de dispensa` | `[0.8478, 0.8014, 0.7666, 0.7381]` | descartes: 0 |
fontes: `DECLARAÇÃO DE DISPENSA (p. 33)`, `DECLARAÇÃO DE DISPENSA (p. 34)`,
`DECLARAÇÃO DE DISPENSA (p. 35)`, `ALTERAÇÃO DA CARGA HORARIA DO SUP. DE (p. 30)`.

**Verificação:** **Núcleo tem base; extra parcial.** Trecho de p.33: "o aluno
não pode cumprir mais do que 6 (seis) horas diárias e 30 (trinta) horas semanais
em Estágio Curricular Obrigatório ou Não Obrigatório." Trecho de p.34: "O envio
é realizado através do sistema Colaborar em: menu > dga/secretaria > estágio >
solicitação de dispensa de estágio remunerado… somente… PDF, JPG, JPEG e PNG…
devidamente assinado e legível (sem rasuras)." O parágrafo do supervisor (p.30)
existe — "Abra um chamado em Graduação EAD > Solicitações Acadêmicas > Estágio >
Estágio Obrigatório > Avaliação > Supervisor de Estágio… Após a aprovação da
Coordenação…" — mas o Manual diz "Coordenação de Curso" e exige declaração de
*cada* local quando há 2+ empresas, detalhe que a resposta resumiu para
"Coordenação" genérica. Não foi pedido na pergunta; é extra recuperado (p.30
estava entre as fontes). Faltou citar as Fontes.

---

## Página de justificativa: chunking e armazenamento (1 folha)

**Decisão.** Chunking: **1 slide = 1 chunk**, sem sobreposição — título + corpo
nativo + blocos de imagem na ordem de leitura, com a marca `[texto de imagem]`
(`sau/manual/chunks.py`). Fonte citável: **título do slide + página**
(`ChunkManual.fonte`), o que o Aluno confere sozinho no PDF. Armazenamento:
**Chroma persistente, coleção dedicada** (`manual-estagio-obrigatorio`), carga
idempotente pelo `sha256` do PDF no boot (re-ingere só se o conteúdo mudou),
volume nomeado no container (`sau/manual/indice.py`, `sau/config.py`).
Embeddings: `nomic-embed-text` local via Ollama, vetores L2-normalizados,
espaço cosseno — o mesmo cosseno que a busca em memória calculava. Recuperação:
ferramenta opcional `buscar_no_manual` (`k = 4`, limiar `0.72`), com busca de
segurança determinística e guarda que troca resposta sem evidência pelo literal
"não encontrei no material" + Encaminhamento (ADR-0010, ADR-0012).

**Por que assim.** O Manual é uma apresentação: cada slide já é uma unidade de
sentido com título próprio, então o limite do chunk é do autor, não heurística
nossa — e a Fonte herda esse limite de graça. Chunks curtos são orçamento, não
estilo: `num_ctx` é 4096 e não é tocado, a persona tem 852 tokens, e cada trecho
custa contexto que a conversa não tem. Persistência existe para o boot indexar
sozinho e reaproveitar quando o PDF é o mesmo; idempotência por hash impede
duplicar o índice a cada restart. Máscara antes de indexar (apólice, CNPJ, CPF,
matrícula, nomes em tabelas, telefone, e-mail) garante que dado ilustrativo
nunca vire fato citável — b3 prova o porquê.

**Descartadas.** Janela fixa de N caracteres com overlap: quebraria slides no
meio e geraria Fontes "página X, pedaço 2", que o Aluno não confere. Índice só
em memória: perderia tudo a cada restart e o boot pagaria embedding sempre.
Vetor externo (pgvector/serviço próprio): infra nova para 57 chunks — custo sem
ganho medido. Trocar embedding ou gerador: sem evidência da bateria; o
`nomic-embed-text` (274 MB) cabe no orçamento de ~1 GB ao lado do gerador
(ADR-0003). OCR com visão ou reranker externo: só entram se a bateria provar
necessidade (spec #34). Recuperação obrigatória todo turno: aposentada — gerava
chamada em saudação e escondia a ausência de evidência (ADR-0010).

**Limites declarados.** Tabelas de p.15–p.16 dependem do OCR das imagens;
capturas mascaradas não voltam como fato. Limiar 0.72 é ponto de partida
calibrável pela bateria, não constante sagrada — e a ausência de citação visível
nesta rodada é o próximo defeito a fechar, não uma qualidade do índice.

## Referências

- `perguntas-teste/bateria-manual.md` — os 30 blocos e o `conforme quando` de cada um
- `corpus/manual-estagio-obrigatorio-polo-2026-2.pdf` — o Manual (local, fora do git)
- ADR-0011 — pipeline de OCR, máscara, chunk por slide, Fonte título + página, Chroma persistente
- ADR-0010 — ferramenta opcional, busca de segurança, literal garantido em código
- ADR-0012 — limiar e frase de ausência
- `sau/manual/chunks.py`, `sau/manual/indice.py`, `sau/manual/tool.py`, `sau/graph/nodes.py`, `sau/graph/graph.py`
