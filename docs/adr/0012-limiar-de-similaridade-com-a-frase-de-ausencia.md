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
