# Tutor-IA

## Agent skills

### Issue tracker

Issues e specs vivem no GitHub Issues de `Feliipee013/Tutor-IA`, operados via CLI `gh`. Ver `docs/agents/issue-tracker.md`.

### Triage labels

Vocabulário canônico de cinco papéis (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). Ver `docs/agents/triage-labels.md`.

### Domain docs

Layout single-context: `CONTEXT.md` na raiz e `docs/adr/`. Ver `docs/agents/domain.md`.

### Code review

`/code-review` revisa a mudança em dois eixos paralelos: **Standards** (segue as convenções deste repo?) e **Spec** (implementa a issue e o ADR?). A skill vive em `.agents/skills/code-review` e está em inglês. Use a merge base entre a branch e a base como ponto fixo.

### Implementar

`/implementar` é o caminho para transformar um ticket em código, em duas fases: monta um `Plano de Implementação` na conversa e, **só depois de aprovação humana explícita**, delega a execução ao subagente `executor`. Ela não edita código. Ver `.opencode/skills/implementar/SKILL.md`.

### Criar PR

`criar-pr` é um subagente, não uma skill. Ele monta um preview sem nenhuma mutação e só publica depois que uma pessoa aprovar o preview completo. Ver `.opencode/agents/criar-pr.md` e o formato em `docs/agents/pull-request.md`.

### Dúvidas de skill

`/duvidas-skills` é o roteador do fluxo. Ele não inventa fluxo: se uma skill
apontar para outra, é porque as duas existem. Ver `.opencode/skills/duvidas-skills/SKILL.md`.

### Da ideia ao ticket

Quatro skills encadeadas, todas com `disable-model-invocation` — só entram por
comando explícito, e o contexto de uma alimenta a seguinte:

1. `/entrevistar-com-docs` — afia a ideia por entrevista e resolve o vocabulário
   e os ADRs no caminho (delega para `/grilling` e `/domain-modeling`).
2. `/transformar-em-spec` — sintetiza a conversa numa spec e publica no tracker
   com `ready-for-agent`.
3. `/transformar-em-tickets` — quebra a spec em tickets tracer-bullet por
   entrega, cada um com suas arestas de bloqueio. A publicação de cada ticket
   é delegada ao subagente `criar-ticket`.
4. `/implementar` — planeja e delega ao `executor`.

`/transformar-em-spec` e `/transformar-em-tickets` não acrescentam decisão: elas
sintetizam o que já foi discutido. `/entrevistar-com-docs` e `/implementar` têm
gate de aprovação humana explícita.

### Criar ticket

`criar-ticket` é um subagente, não uma skill, e é `hidden`. Ele recebe o ticket
completo no prompt, cria a issue em uma única chamada `gh issue create` já com
`ready-for-agent`, e devolve só o número. Este projeto não tem divisão por área
nos tickets, e o subagente não cria nem aplica label além dessa. Ver
`.opencode/agents/criar-ticket.md`.

### Contribuir numa PR de outro dev

`/contribuir-pr` assume uma PR parada com *request changes* enquanto o autor não
pode responder: pega a branch dele, implementa o bloqueante, devolve os commits à
PR original com trailer de assinatura, e tem dois gates de aprovação antes de
qualquer mutação no GitHub. Ver `.opencode/skills/contribuir-pr/SKILL.md`.

### Mapa de pastas

Antes de planejar uma implementação, leia `docs/estrutura.md`. Ele diz onde cada coisa mora e qual ticket cria cada pasta — evita varrer o repositório e evita que dois tickets criem a mesma pasta.

### Docs atuais via Context7

Quando o código depender de uma API de dependência que sua memória pode ter defasada — assinatura exata, config, comportamento que muda entre versões — consulte as docs oficiais no MCP `context7` (informando a lib e a versão) antes de escrever. Dispara em: Ollama, LangGraph, LangChain, python-telegram-bot, Docker/Compose. Consulta pontual: o alvo é a lib, não Python básico. O MCP já está configurado em `opencode.json`; ver `SETUP.md` para gerar a chave.

## Regras de organização

- **Um ticket, uma branch, uma PR.** Cada ticket tem branch própria e code-review antes do merge.
- **Bloqueios reais.** Um ticket só entra na fronteira de trabalho quando os bloqueadores declarados estão fechados. Não crie tickets improvisados para contornar dependência.
- **TDD não é obrigatório.** A referência é o ticket, os ADRs e o comportamento observável.
- **Aprovação humana antes de codar.** O plano da `/implementar` só vira código depois de uma aprovação explícita, e a PR só existe depois da aprovação do preview.
- **O vocabulário é do `CONTEXT.md`.** S.A.U., Aluno, Estágio, Empresa / Concedente, Supervisor(a) de Estágio, Termo de Compromisso de Estágio, Contrato de Estágio, Seguro de Acidentes Pessoais, Documentação de Estágio, Prazos / Calendário de Estágio, Fluxo de Estágio, Pergunta Frequente, Atividade, Instituição, Coordenação de Estágios, Encaminhamento, Alucinação, Pergunta-teste. Escreva código, comentários, testes e mensagens em português usando esses termos.
