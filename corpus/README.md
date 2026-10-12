# Manual de Estágio Obrigatório do Polo (issue #40)

Este diretório guarda o **Manual de Estágio Obrigatório do Polo 2026/2 em PDF**,
que é a base do S.A.U.: no boot do serviço `webhook` o Manual é indexado
automaticamente (texto nativo mais OCR das imagens, com máscara de dados
ilustrativos — ver ADR-0011) num banco vetorial persistente.

## Qual arquivo colocar aqui

```
corpus/manual-estagio-obrigatorio-polo-2026-2.pdf
```

Exatamente esse nome. O serviço procura esse caminho (ou o que a variável
`MANUAL_PDF_CAMINHO` apontar) e calcula o `sha256` do conteúdo: se o índice
guardado já é desse conteúdo, o boot reaproveita; se o PDF mudou, o próximo
boot re-ingere sozinho.

## O PDF nunca entra no git

O `.gitignore` cobre `corpus/*.pdf` de propósito: o Manual é material
institucional, e o repositório versiona só este README e o `.gitkeep`. O PDF
chega ao container por bind mount (`./corpus:/app/corpus:ro` no serviço
`webhook`).

## Comportamento sem o PDF

Sem o arquivo, o serviço **sobe normalmente** e registra no log:

> coloque o PDF em `corpus/` — ver `corpus/README.md`

…e segue sem índice até o PDF aparecer. Nada precisa de passo manual além de
colocar o arquivo e (re)subir o serviço.

## Limitação conhecida

O Manual 2026/2 não tem seção de contato da Coordenação de Estágios com
telefone ou e-mail (só Encaminhamento via chamado no ServiceNow). Por isso a
máscara cobre telefone e e-mail em todos os trechos por padrão
(`sau/manual/mascara.py`): se um Manual futuro trouxer contato da Coordenação
em trecho normativo, a regra de exceção preserva — sem inventar contato onde
não há.
