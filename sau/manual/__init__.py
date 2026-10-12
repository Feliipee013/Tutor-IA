"""Base do Manual de Estágio Obrigatório do Polo (issue #40, ADR-0011).

O Manual chega em PDF (`corpus/`, fora do git) e vira índice vetorial
persistente no boot do `webhook`: `extrair` lê texto nativo mais OCR,
`mascara` cobre os dados ilustrativos, `chunks` quebra um slide por chunk e
`indice` guarda no Chroma com carga idempotente pelo `sha256` do PDF.
"""
