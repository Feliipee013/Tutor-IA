"""Canal do Telegram do S.A.U.

Handler do webhook: recebe o update do Telegram, registra o update bruto para
depuração e entrega ao Aluno o acuse de recibo fixo, sem depender do modelo.
O turno com inferência é do ticket #8.
"""
