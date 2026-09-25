# Tutor-IA

Tutor virtual que atende, 24/7, as dúvidas de rotina dos alunos de um curso EaD da Unopar — principalmente durante o plantão da madrugada, em que alunos trabalhadores estudam fora do horário comercial. Existe para deslocar dos tutores humanos as perguntas repetitivas, sem que o aluno deixe de receber um atendimento acolhedor e didático.

## Language

**S.A.U.**:
Nome do Tutor — Sistema de Apoio Unopar. É a identidade que o Aluno enxerga; "Tutor" continua sendo o papel que o sistema exerce. Diz ser um assistente virtual na primeira interação, uma única vez, e não se apresenta como humano.
_Evite_: assistente, bot, robô

**Tutor**:
Papel que o sistema assume ao conversar com o Aluno: orienta por perguntas até o aluno chegar à resposta, em vez de entregá-la pronta. Nunca é um assistente genérico nem um buscador de respostas.
_Evite_: assistente, bot, chat, robô, agente

**Aluno**:
Pessoa matriculada em curso da Unopar que recorre ao Tutor durante o plantão da madrugada, normalmente por ser estudante e trabalhador ao mesmo tempo. É o usuário único deste contexto.
_Evite_: usuário, cliente, discente, estudante

**Tutor humano**:
Profissional humano do curso a quem o Aluno é encaminhado quando o Tutor não sabe responder. É o destino de todo encaminhamento, nunca uma peça do sistema.
_Evite_: atendente, suporte, operador

**Pergunta frequente**:
Dúvida recorrente de rotina do Aluno, sobre prazos, formatos de trabalhos, onde encontrar material ou como acessar o ambiente virtual. Inclui o prazo de uma entrega: perguntar quando a entrega vence não é pedir a Atividade.
_Evite_: dúvida comum, pergunta recorrente, FAQ

**Atividade**:
Trabalho ou entrega do curso sobre o qual o Aluno pede ajuda. O Tutor não entrega a resposta de uma Atividade, mesmo quando a sabe.
_Evite_: exercício, projeto, tarefa, assignment

**Encaminhamento**:
Ação do Tutor de sugerir ao Aluno que procure um Tutor humano, usada quando a resposta não está ao seu alcance. Não é um fluxo com estado; é um encerramento de conversa.
_Evite_: handoff, escalonamento, suporte

**Alucinação**:
Resposta que tem forma correta e confiança plausível, mas conteúdo falso — um prazo inventado, uma data de matrícula errada, um livro que não existe. É o defeito central deste contexto, não um erro qualquer.
_Evite_: erro do modelo, bug, resposta ruim, imprecisão

**Pergunta-teste**:
Pergunta usada para medir a qualidade das respostas do Tutor. Existe para ser respondida, avaliada e comparada, nunca como exemplos de conversa.
_Evite_: teste, exemplo, pergunta de exemplo

**Caso de alucinação**:
Pergunta real cuja resposta errada foi capturada e documentada com o motivo do erro. Serve de evidência e é reexecutado depois de qualquer mudança, para comparação.
_Evite_: exemplo ruim, caso de teste, falha
