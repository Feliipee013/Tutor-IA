# Pipeline de OCR com máscara de dados ilustrativos

O Manual de Estágio Obrigatório do Polo (PDF) é ingerido com pipeline que combina texto nativo do PDF e OCR por imagem, aplicando máscara de dados ilustrativos antes da indexação para proteger dados sensíveis, preservando ao mesmo tempo o conteúdo normativo e procedimental.

## O que descreve

- **Extração híbrida**: combina texto extraído do PDF com OCR por imagem (idioma português). Imagens pequenas recebem ampliação prévia para melhorar a legibilidade da extração.
- **Máscara de dados ilustrativos**: antes da indexação, são substituídos por marcadores neutros: número de apólice, CNPJ, CPF, matrícula, nomes próprios em tabelas, telefone e e-mail. Dados ilustrativos nunca viram fato citável.
- **O que permanece indexável**: norma, procedimento, passos, prazos definidos no manual, estrutura, títulos, seções e texto descritivo que não contenha dados sensíveis ilustrativos.
- **Rastreamento de origem**: o texto proveniente de imagem é marcado como tal no chunk.
- **Chunking**: um slide por chunk (título + corpo + texto das imagens, na ordem de leitura), sem sobreposição.
- **Fonte citável**: título do slide com a página correspondente, permitindo ao Aluno conferir a afirmação no material.
- **Persistência**: banco vetorial embarcado em modo persistente (volume nomeado), coleção dedicada ao manual, com carga inicial idempotente no boot (re-ingere somente quando o conteúdo do PDF muda).

## Consequências

- Garante que números e nomes de captura não sejam citados como fato, mesmo com Fonte.
- Preserva a capacidade de responder com trechos procedimentais e normativos extraídos de imagens.
- Mantém a rastreabilidade (Fonte + página) para toda afirmação baseada no manual.
