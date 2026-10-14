# Medição da recuperação híbrida (fase avançada)

**Objetivo:** comparar vetorial puro vs híbrido (BM25 + RRF) nas perguntas cruzadas x1–x5 da bateria do Manual.

## Condições

- PDF: manual_estagio.pdf
- sha256 do PDF: d1bbcb7c15aa9954ee05d338fddb521f049804938febdd51d58d08cb16742042
- sha256 indexado: d1bbcb7c15aa9954ee05d338fddb521f049804938febdd51d58d08cb16742042
- Índice: manual-chroma
- Coleção: manual-estagio-obrigatorio
- Modelo de embedding: nomic-embed-text
- Ollama: http://localhost:11434
- k: 4
- limiar (registrado): 0.72
- chunks no índice: 57
- OCR (tesseract) disponível: não

## Resultados por pergunta (recall por Fonte esperada)

| id | vetorial (Fontes presentes/esperadas) | híbrido (Fontes presentes/esperadas) | delta |
| --- | --- | --- | --- |
| x1 | 2/3 | 3/3 | +1 |
| x2 | 1/3 | 2/3 | +1 |
| x3 | 1/3 | 1/3 | +0 |
| x4 | 3/3 | 3/3 | +0 |
| x5 | 1/1 | 1/1 | +0 |

## Agregado

- Recall vetorial: 8/13
- Recall híbrido: 10/13
- Delta: +2

## Veredito

O híbrido mostra ganho de recall nas cruzadas x1–x5.

## Limitações

- O PDF do Manual é material institucional e não entra no git (ver corpus/README.md).
- A medição exige o Ollama no host com o modelo de embedding.
- Sem tesseract no host, os slides em imagem entraram sem OCR: só o texto nativo foi indexado. Isso reduz o recall absoluto das perguntas cujo conteúdo mora em figura, e vale para os dois caminhos.
