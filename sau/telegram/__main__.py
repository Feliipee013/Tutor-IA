"""Entrypoint do serviço do webhook do Telegram.

Existe para o módulo ser importado pelo nome dele. Rodar
`python -m sau.telegram.webhook` carrega o arquivo como `__main__`, e aí todo
log do handler sai marcado `__main__` em vez de `sau.telegram.webhook` — o que
tira do operador a forma de filtrar o log do canal do Telegram.
"""

from sau.telegram.webhook import main

main()
