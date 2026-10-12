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

## Emenda: PDF externo fora do git (decisão de equipe na #40)

O PDF do Manual é material institucional e não se sabe se pode ser exposto:
por isso nunca entra no git nem na imagem. O `.gitignore` cobre `corpus/*.pdf`,
o `Dockerfile` copia só `corpus/README.md` e `.gitkeep`, e o PDF chega ao
container por bind mount (`./corpus:/app/corpus:ro` no serviço `webhook`,
ver `corpus/README.md`).

Com isso o aceite “subir o container do zero indexa o manual sem passo manual”
vale **depois** do PDF colocado: com o arquivo no caminho de
`MANUAL_PDF_CAMINHO`, o boot indexa (ou reaproveita pelo `sha256`); sem ele,
o serviço sobe sem índice com o aviso `coloque o PDF em corpus/` e segue no ar.

## Emenda: exceção do contato da Coordenação de Estágios

Telefone e e-mail seguem mascarados por padrão, mas trecho normativo ou de
Encaminhamento que nomeia a Coordenação **e** indica contato (`contato`,
`fale conosco`, `canal`) preserva telefone e e-mail — regra de
`e_contato_da_coordenacao` em `sau/manual/mascara.py`, decidida por chunk em
`sau/manual/chunks.py` via `preservar_contato`.

O Manual 2026/2 não tem seção assim (só Encaminhamento via chamado no
ServiceNow, sem telefone nem e-mail), então na prática atual a máscara cobre
tudo. A exceção existe para o Manual futuro não perder o contato normativo,
sem inventar contato onde não há.
