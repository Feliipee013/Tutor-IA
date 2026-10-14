"""Configurações do serviço do S.A.U.

Lê variáveis de ambiente com defaults seguros e tipados. A VRAM total da
máquina entra por `VRAM_TOTAL_MIB` porque nenhum endpoint do Ollama a expõe, e
a checagem de pré-requisito do ADR-0002 não consegue confrontar o `size_vram`
que o Ollama relata sem ela.

O `INFERENCIA_K` e o `INFERENCIA_FILA_TETO` são a #11, e a validação deles é a
mesma do TTL, com o mesmo motivo: quem escreve o número no `.env` não tem como
perceber que zero é diferente de um.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

from sau.inference.semaphore import K_PADRAO, TETO_PADRAO_DA_FILA


@dataclass(frozen=True)
class Configuracao:
    """Configurações operacionais do bot S.A.U."""

    ollama_base_url: str
    ollama_model: str
    ollama_timeout: float
    ollama_allow_cpu: bool
    vram_total_bytes: int | None
    bot_port: int
    bot_env: str
    log_level: str
    telegram_bot_token: str | None
    telegram_webhook_secret_token: str | None
    telegram_webhook_port: int
    telegram_api_base: str
    conversa_caminho: str
    conversa_ttl_minutos: int
    inferencia_k: int
    inferencia_fila_teto: int
    manual_pdf_caminho: str = "corpus/manual-estagio-obrigatorio-polo-2026-2.pdf"
    manual_chroma_caminho: str = "manual-chroma"
    manual_colecao: str = "manual-estagio-obrigatorio"
    manual_limiar_similaridade: float = 0.72
    manual_k_padrao: int = 4
    telegram_public_url: str | None = None
    ngrok_api_url: str | None = None


_MIB_EM_BYTES = 1_048_576
"""Quantos bytes tem 1 MiB, a unidade em que a VRAM é declarada."""


def _parse_bool(valor: str | None, default: bool = False) -> bool:
    if valor is None:
        return default
    return valor.strip().lower() in ("true", "1", "yes", "t", "sim")


def carregar_configuracao(origem: Mapping[str, str] | None = None) -> Configuracao:
    """Carrega as configurações a partir do ambiente ou de um dicionário fornecido."""
    env = os.environ if origem is None else origem

    ollama_base_url = env.get("OLLAMA_BASE_URL", "http://host.docker.internal:11434").strip()
    ollama_model = env.get("OLLAMA_MODEL", "qwen2.5:3b").strip()

    timeout_raw = env.get("OLLAMA_TIMEOUT", "30.0")
    try:
        ollama_timeout = float(timeout_raw)
    except ValueError as err:
        raise ValueError(
            f"Valor inválido para OLLAMA_TIMEOUT: '{timeout_raw}'. Esperado número."
        ) from err

    ollama_allow_cpu = _parse_bool(env.get("OLLAMA_ALLOW_CPU"), default=False)

    # A VRAM total da máquina não é exposta por nenhum endpoint do Ollama: o
    # /api/ps só diz o size_vram de cada modelo. Como o container não tem GPU
    # por desenho do ADR-0002, o total precisa vir do host, em MiB, exatamente
    # como o nvidia-smi imprime. Ausente é None; string vazia também, porque o
    # compose injeta '${VRAM_TOTAL_MIB:-}'.
    vram_mib_bruto = env.get("VRAM_TOTAL_MIB")
    vram_total_bytes: int | None = None
    vram_mib_texto = (vram_mib_bruto or "").strip()
    if vram_mib_texto:
        erro_vram = (
            f"Valor inválido para VRAM_TOTAL_MIB: '{vram_mib_bruto}'. "
            "Esperado um inteiro positivo em MiB.\n"
            "A causa quase sempre é o nvidia-smi: ele imprime UMA LINHA POR GPU, "
            "então em uma máquina com mais de uma placa o comando precisa ser "
            "filtrado para entregar um valor só:\n"
            "  export VRAM_TOTAL_MIB=$(nvidia-smi --query-gpu=memory.total "
            "--format=csv,noheader,nounits | head -1)\n"
            "Se a sua máquina tem mais de uma placa, o head -1 pega a primeira: "
            "informe na mão o total da placa que roda o Ollama."
        )
        try:
            vram_mib = int(vram_mib_texto)
        except ValueError as err:
            raise ValueError(erro_vram) from err
        if vram_mib <= 0:
            raise ValueError(erro_vram)
        vram_total_bytes = vram_mib * _MIB_EM_BYTES

    port_raw = env.get("BOT_PORT", "8000")
    try:
        bot_port = int(port_raw)
    except ValueError as err:
        raise ValueError(f"Valor inválido para BOT_PORT: '{port_raw}'. Esperado inteiro.") from err

    bot_env = env.get("BOT_ENV", "development").strip()
    log_level = env.get("LOG_LEVEL", "INFO").strip().upper()

    # Credenciais do Telegram. Nenhuma das duas tem valor padrão, e nenhuma é
    # exigida aqui: quem não conversa com o Telegram é o serviço do bot, que
    # não precisa delas. A obrigatoriedade mora no `sau/telegram/webhook.py`,
    # que falha alto se subir sem elas — no mesmo estilo da checagem de
    # pré-requisito do ADR-0002, e não num `ValueError` que derrubaria também
    # quem não usa o canal. Ausente é None; string vazia também, porque o
    # compose injeta '${TELEGRAM_BOT_TOKEN:-}'.
    telegram_bot_token = (env.get("TELEGRAM_BOT_TOKEN") or "").strip() or None
    telegram_webhook_secret_token = (env.get("TELEGRAM_WEBHOOK_SECRET_TOKEN") or "").strip() or None
    telegram_api_base = env.get("TELEGRAM_API_BASE", "https://api.telegram.org").strip()

    # URL pública do túnel de desenvolvimento. Ausente é None; string vazia
    # também, porque o compose dev injeta '${TELEGRAM_PUBLIC_URL:-}'. Quando
    # presente, ela vence a descoberta via API do ngrok: é o caminho manual
    # para quem abre o túnel na mão, fora do compose dev.
    telegram_public_url = (env.get("TELEGRAM_PUBLIC_URL") or "").strip() or None
    # Base da API local do ngrok (o /api/tunnels). Ausente é None pelo mesmo
    # motivo acima. Sem ela e sem TELEGRAM_PUBLIC_URL nenhum HTTP extra
    # acontece: o canal sobe sem registrar, como em prod.
    ngrok_api_url = (env.get("NGROK_API_URL") or "").strip() or None

    webhook_port_raw = env.get("TELEGRAM_WEBHOOK_PORT", "8080")
    try:
        telegram_webhook_port = int(webhook_port_raw)
    except ValueError as err:
        raise ValueError(
            f"Valor inválido para TELEGRAM_WEBHOOK_PORT: '{webhook_port_raw}'. Esperado inteiro."
        ) from err

    # O arquivo de conversas. O padrão é relativo ao diretório de trabalho, e é
    # de propósito: o `python -m sau.telegram` no host cria o arquivo onde a pessoa
    # está, sem configuração nenhuma. Quem sobe em container aponta o caminho para
    # o volume nomeado do compose, e é o que faz o histórico sobreviver ao
    # `docker compose down`.
    conversa_caminho = env.get("CONVERSA_CAMINHO", "conversas.db").strip()

    ttl_raw = env.get("CONVERSA_TTL_MINUTOS", "30")
    try:
        conversa_ttl_minutos = int(ttl_raw)
    except ValueError as err:
        raise ValueError(
            f"Valor inválido para CONVERSA_TTL_MINUTOS: '{ttl_raw}'. Esperado inteiro."
        ) from err
    if conversa_ttl_minutos <= 0:
        raise ValueError(
            f"Valor inválido para CONVERSA_TTL_MINUTOS: '{ttl_raw}'. "
            "Esperado inteiro positivo: com zero o histórico de toda conversa "
            "seria apagado antes de o turno seguinte chegar."
        )

    # O semáforo de inferência: quantos turnos entram no modelo ao mesmo tempo e
    # quantos podem esperar uma vaga. As duas variáveis nascem aqui na #11, e o
    # `INFERENCIA_K` é o número que o ADR-0001 exige medir na máquina alvo em vez
    # de assumir — o valor padrão é o ponto de partida declarado, e o procedimento
    # de medição está em `docs/fila-e-semaforo.md`.
    #
    # Zero é recusado nos dois, e não por formalidade: com `k=0` nenhuma vaga
    # existiria e todo turno ficaria esperando para sempre, e com teto `0` o
    # primeiro turno fora de vaga seria recusado antes de a fila chegar a existir.
    # A validação é a mesma do TTL acima, e vale a mesma razão: quem escreve o
    # número no `.env` não tem como perceber que zero é diferente de um.
    k_raw = env.get("INFERENCIA_K", str(K_PADRAO))
    try:
        inferencia_k = int(k_raw)
    except ValueError as err:
        raise ValueError(
            f"Valor inválido para INFERENCIA_K: '{k_raw}'. Esperado inteiro."
        ) from err
    if inferencia_k <= 0:
        raise ValueError(
            f"Valor inválido para INFERENCIA_K: '{k_raw}'. Esperado inteiro "
            f"positivo: com zero nenhuma vaga de inferência existiria e todo turno "
            "ficaria esperando para sempre, sem que ninguém percebesse. O valor "
            "medido na máquina alvo está em docs/fila-e-semaforo.md."
        )

    teto_raw = env.get("INFERENCIA_FILA_TETO", str(TETO_PADRAO_DA_FILA))
    try:
        inferencia_fila_teto = int(teto_raw)
    except ValueError as err:
        raise ValueError(
            f"Valor inválido para INFERENCIA_FILA_TETO: '{teto_raw}'. Esperado inteiro."
        ) from err
    if inferencia_fila_teto <= 0:
        raise ValueError(
            f"Valor inválido para INFERENCIA_FILA_TETO: '{teto_raw}'. Esperado inteiro "
            "positivo: com zero o primeiro turno fora de vaga seria recusado antes de "
            "a fila de espera existir."
        )

    # O Manual de Estágio Obrigatório do Polo (issue #40, ADR-0011). O PDF fica
    # em `corpus/` fora do git (ver `corpus/README.md`), e o índice Chroma
    # vive no volume nomeado em container ou no diretório local no host.
    # String vazia do compose cai no padrão, pelo mesmo motivo da VRAM acima.
    manual_pdf_caminho = (
        env.get("MANUAL_PDF_CAMINHO", "corpus/manual-estagio-obrigatorio-polo-2026-2.pdf")
        or "corpus/manual-estagio-obrigatorio-polo-2026-2.pdf"
    ).strip() or "corpus/manual-estagio-obrigatorio-polo-2026-2.pdf"
    manual_chroma_caminho = (
        env.get("MANUAL_CHROMA_CAMINHO", "manual-chroma") or "manual-chroma"
    ).strip() or "manual-chroma"
    manual_colecao = (
        env.get("MANUAL_COLECAO", "manual-estagio-obrigatorio") or "manual-estagio-obrigatorio"
    ).strip() or "manual-estagio-obrigatorio"

    # Limiar mínimo de similaridade de cosseno e quantidade padrão de trechos (issue #36, ADR-0012).
    # Sem o `or "0.72"` que a string faria cair no padrão: variável numérica vazia
    # é valor inválido, e não ausência — a mesma régua do `INFERENCIA_K` acima.
    limiar_raw = env.get("MANUAL_LIMIAR_SIMILARIDADE", "0.72")
    try:
        manual_limiar_similaridade = float(limiar_raw)
    except ValueError as err:
        raise ValueError(
            f"Valor inválido para MANUAL_LIMIAR_SIMILARIDADE: '{limiar_raw}'. "
            "Esperado número de ponto flutuante (ex: 0.72)."
        ) from err
    if not 0.0 <= manual_limiar_similaridade <= 1.0:
        raise ValueError(
            f"Valor inválido para MANUAL_LIMIAR_SIMILARIDADE: '{limiar_raw}'. "
            "Esperado valor entre 0.0 e 1.0."
        )

    k_raw = env.get("MANUAL_K_PADRAO", "4")
    try:
        manual_k_padrao = int(k_raw)
    except ValueError as err:
        raise ValueError(
            f"Valor inválido para MANUAL_K_PADRAO: '{k_raw}'. "
            "Esperado número inteiro positivo (ex: 4)."
        ) from err
    if manual_k_padrao <= 0:
        raise ValueError(
            f"Valor inválido para MANUAL_K_PADRAO: '{k_raw}'. "
            "Esperado número inteiro positivo (k >= 1)."
        )

    return Configuracao(
        ollama_base_url=ollama_base_url,
        ollama_model=ollama_model,
        ollama_timeout=ollama_timeout,
        ollama_allow_cpu=ollama_allow_cpu,
        vram_total_bytes=vram_total_bytes,
        bot_port=bot_port,
        bot_env=bot_env,
        log_level=log_level,
        telegram_bot_token=telegram_bot_token,
        telegram_webhook_secret_token=telegram_webhook_secret_token,
        telegram_webhook_port=telegram_webhook_port,
        telegram_api_base=telegram_api_base,
        conversa_caminho=conversa_caminho,
        conversa_ttl_minutos=conversa_ttl_minutos,
        inferencia_k=inferencia_k,
        inferencia_fila_teto=inferencia_fila_teto,
        manual_pdf_caminho=manual_pdf_caminho,
        manual_chroma_caminho=manual_chroma_caminho,
        manual_colecao=manual_colecao,
        manual_limiar_similaridade=manual_limiar_similaridade,
        manual_k_padrao=manual_k_padrao,
        telegram_public_url=telegram_public_url,
        ngrok_api_url=ngrok_api_url,
    )
