# Limiar de similaridade com a frase de ausência

A recuperação por similaridade vetorial usa um limiar mínimo configurável. Trechos abaixo do limiar são descartados como evidência insuficiente. Quando não há evidência válida acima do limiar, a resposta utiliza o literal "não encontrei no material" e encerra com Encaminhamento à Coordenação de Estágios.

## Decisão

- **Limiar inicial**: 0,35 em similaridade de cosseno (configurável por ambiente).
- **Filtro por evidência**: a ferramenta (`buscar_no_manual`) filtra pelo limiar e devolve apenas trechos com pontuação >= limiar, incluindo trecho, Fonte, página e pontuação. Trechos abaixo do limiar são devolvidos como vazio com sinal de ausência de evidência.
- **Frase de ausência**: em ausência de evidência válida, a resposta usa exatamente o literal **"não encontrei no material"**, seguido de Encaminhamento à Coordenação de Estágios, sem inventar telefone, canal ou prazo.
- **Calibração**: o valor do limiar é calibrado pela bateria de testes (10 perguntas da fase básica + 20 da fase avançada, com gabarito humano), permitindo ajuste justificado com base em evidência comparável.
- **Auditoria**: toda chamada da ferramenta registra em log a consulta, as pontuações retornadas, os descartes pelo limiar e as Fontes efetivamente entregues.

## Consequências

- Reduz falsos positivos (trechos semanticamente distantes) que antes poderiam levar à alucinação.
- Torna explícita a ausência de evidência, forçando Encaminhamento quando o manual não sustenta o fato.
- Cria um ponto de ajuste mensurável (antes/depois com a mesma bateria) ao invés de um valor arbitrário não justificado.

## Emenda: implementação na #36

- **O literal também é garantido em código.** A guarda do grafo (`finalizar`)
  troca a resposta pelo texto de ausência quando a ferramenta foi chamada e nada
  passou pelo limiar, de modo que a frase não depende de o modelo obedecer ao
  prompt ([ADR-0010](./0010-aposentadoria-da-recuperacao-obrigatoria-em-todo-turno.md)).
- **O limiar e o `k` têm fonte única.** Os padrões vivem em `sau/config.py`
  (`MANUAL_LIMIAR_SIMILARIDADE=0.35`, `MANUAL_K_PADRAO=4`); a ferramenta
  `buscar_no_manual` recebe ambos por parâmetro, sem default próprio, para que a
  calibração tenha um lugar só.
