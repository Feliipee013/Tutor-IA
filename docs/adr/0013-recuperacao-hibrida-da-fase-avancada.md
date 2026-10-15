# ADR-0013: Recuperação híbrida da fase avançada

**Status:** Aceito
**Data:** 2026-10-14
**Contexto:** Issue #39 — Recuperação híbrida da fase avançada (spec #34; bloqueadores #36 e #40 já fechados).

## Decisão

Adotar recuperação híbrida para `buscar_no_manual`: somar à via vetorial (Chroma, cosseno) uma via lexical (BM25 em memória, Python puro, sem dependência nova), fundir por **ranque recíproco (RRF)**, e **reordenar pelo cosseno vetorial** na entrega final.

- A `pontuacao` exposta continua sendo o cosseno (`1 - distância`).
- O `limiar` continua aplicado sobre o cosseno (contrato preservado).
- A via lexical só amplia o conjunto de candidatos; o cosseno vetorial manda.
- O índice lexical é montado **em memória a cada busca** a partir do próprio Chroma (`colecao.get(...)`), sem segundo artefato persistido.
- A tokenização remove diacríticos (NFKD + remoção de marcas combinantes) para casar "estagio" com "estágio".
- `buscar_no_indice` permanece disponível como via vetorial pura (base de medição).
- O híbrido torna-se o comportamento padrão de `buscar_no_manual`; **não** há flag de configuração.

## Motivação

As perguntas cruzadas da bateria (`perguntas-teste/bateria-manual.md`, x1–x5) exigem recuperar trechos distintos e, em alguns casos, a correspondência exata de termos é decisiva. O híbrido visa aumentar o recall nas cruzadas sem introduzir um segundo modelo, mantendo o contrato e o formato de log da fase básica.

## Consequências

- **Positivas:** maior robustez a ruídos de grafia/diacríticos; possibilidade de resgatar trechos raros com termo exato; recall mensurável sobre as cinco cruzadas.
- **Negativas:** custo leve (tokenização + BM25 + RRF) por busca; fusão exige escolher bem a pool para não diluir o sinal vetorial. Mantemos o cosseno como ordenação final para mitigar esse risco.
- **Técnicas:** BM25 implementado em `sau/manual/hibrido.py` (Python puro); `sau/manual/indice.py` ganha `buscar_hibrida_no_indice`; `sau/manual/tool.py` passa a usar a variante híbrida; log, contrato e limiar intactos.
- **Medição:** o recall das cruzadas x1–x5 pelos dois caminhos é medido por `docs/medicao-hibrido/medir.py` e registrado com as condições em `docs/medicao-hibrido/resultado.md`; os números dependem do PDF e do ambiente, e não são fixados aqui.

## Alternativas descartadas

- **Reranker externo.** Adicionaria dependência, complexidade e custo; não necessário para o objetivo de curto prazo.
- **BM25 puro.** Perderia o sinal semântico que já existe e foi validado; o híbrido preserva o cosseno como `pontuacao` e critério de ordenação.
- **Corte anterior de BM25 no sprint 1.2.** Adiado para não conflitar com a estabilização já feita; retomado agora com medição explícita.
- **Flag de ativação.** Complica configuração sem ganho para o comportamento desejado.
