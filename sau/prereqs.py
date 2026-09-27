"""Módulo de checagem rigorosa de pré-requisitos do S.A.U.

Garante que o Ollama no host esteja ativo, com o modelo baixado e alocado
em GPU, impedindo a degradação silenciosa para CPU conforme o ADR-0002.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from sau.config import Configuracao

logger = logging.getLogger("sau.prereqs")


class PreRequisitoError(RuntimeError):
    """Exceção base para falhas de pré-requisitos do sistema."""


class OllamaIndisponivelError(PreRequisitoError):
    """Lançada quando a API do Ollama no host não responde."""


class ModeloNaoEncontradoError(PreRequisitoError):
    """Lançada quando o modelo configurado não foi baixado no host."""


class CpuNaoAutorizadaError(PreRequisitoError):
    """Lançada quando o modelo cai para CPU sem autorização explícita."""


def verificar_conectividade(
    base_url: str,
    timeout: float = 5.0,
    client: httpx.Client | None = None,
) -> str:
    """Verifica se o Ollama está respondendo no endpoint /api/version.

    Retorna a versão do Ollama em caso de sucesso.
    """
    url = f"{base_url.rstrip('/')}/api/version"
    try:
        if client is not None:
            resp = client.get(url, timeout=timeout)
        else:
            with httpx.Client() as c:
                resp = c.get(url, timeout=timeout)

        if resp.status_code != 200:
            raise OllamaIndisponivelError(
                f"FALHA CRÍTICA: Ollama em '{base_url}' respondeu com "
                f"código {resp.status_code}: {resp.text}"
            )

        dados = resp.json()
        versao = dados.get("version", "desconhecida")
        return str(versao)
    except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as err:
        raise OllamaIndisponivelError(
            f"FALHA CRÍTICA: Não foi possível conectar ao Ollama em '{base_url}'.\n"
            "Certifique-se de que o Ollama está rodando no host ('ollama serve') e acessível\n"
            "pelo container via host.docker.internal:11434 (conforme ADR-0002).\n"
            f"Detalhes do erro: {err}"
        ) from err
    except Exception as err:
        if isinstance(err, PreRequisitoError):
            raise
        raise OllamaIndisponivelError(
            f"FALHA CRÍTICA: Erro inesperado ao consultar Ollama em '{base_url}': {err}"
        ) from err


def verificar_modelo_disponivel(
    base_url: str,
    modelo: str,
    timeout: float = 10.0,
    client: httpx.Client | None = None,
) -> None:
    """Verifica se o modelo configurado está presente na lista de tags do Ollama."""
    url = f"{base_url.rstrip('/')}/api/tags"
    try:
        if client is not None:
            resp = client.get(url, timeout=timeout)
        else:
            with httpx.Client() as c:
                resp = c.get(url, timeout=timeout)

        if resp.status_code != 200:
            raise PreRequisitoError(
                f"FALHA CRÍTICA: Consulta de tags no Ollama falhou "
                f"(código {resp.status_code}): {resp.text}"
            )

        dados = resp.json()
        modelos_instalados: set[str] = set()
        for item in dados.get("models", []):
            if "name" in item:
                modelos_instalados.add(item["name"])
            if "model" in item:
                modelos_instalados.add(item["model"])

        # Aceita correspondência direta ou com sufixo :latest
        alvos = {modelo}
        if ":" not in modelo:
            alvos.add(f"{modelo}:latest")

        if not any(alvo in modelos_instalados for alvo in alvos):
            disponiveis = ", ".join(sorted(modelos_instalados)) if modelos_instalados else "nenhum"
            raise ModeloNaoEncontradoError(
                f"FALHA CRÍTICA: O modelo '{modelo}' não foi encontrado "
                f"no Ollama em '{base_url}'.\n"
                f"Execute 'ollama pull {modelo}' no host para baixá-lo "
                "(conforme SETUP.md e ADR-0002).\n"
                f"Modelos atualmente disponíveis no host: {disponiveis}."
            )
    except httpx.HTTPError as err:
        raise PreRequisitoError(
            f"FALHA CRÍTICA: Falha de comunicação ao verificar modelo no Ollama: {err}"
        ) from err


def aquecer_modelo(
    base_url: str,
    modelo: str,
    timeout: float = 30.0,
    client: httpx.Client | None = None,
) -> None:
    """Dispara uma geração mínima para que o Ollama carregue o modelo na memória."""
    url = f"{base_url.rstrip('/')}/api/generate"
    payload: dict[str, Any] = {
        "model": modelo,
        "prompt": "",
        "keep_alive": "5m",
        "options": {"num_predict": 1},
    }
    try:
        if client is not None:
            resp = client.post(url, json=payload, timeout=timeout)
        else:
            with httpx.Client() as c:
                resp = c.post(url, json=payload, timeout=timeout)

        if resp.status_code != 200:
            raise PreRequisitoError(
                f"FALHA CRÍTICA: Falha ao carregar modelo '{modelo}' no Ollama "
                f"(status {resp.status_code}): {resp.text}"
            )
    except httpx.HTTPError as err:
        raise PreRequisitoError(
            f"FALHA CRÍTICA: Erro de rede ao aquecer modelo '{modelo}' no Ollama: {err}"
        ) from err


def verificar_alocacao_gpu(
    base_url: str,
    modelo: str,
    permitir_cpu: bool = False,
    timeout: float = 30.0,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Verifica se o modelo está alocado em GPU via /api/ps.

    Caso o modelo não esteja em execução, realiza aquecimento prévio.
    Se o modelo estiver em CPU e permitir_cpu for False, falha alto.
    """
    url_ps = f"{base_url.rstrip('/')}/api/ps"

    def consultar_ps() -> list[dict[str, Any]]:
        if client is not None:
            resp = client.get(url_ps, timeout=timeout)
        else:
            with httpx.Client() as c:
                resp = c.get(url_ps, timeout=timeout)
        if resp.status_code != 200:
            raise PreRequisitoError(
                f"FALHA CRÍTICA: Consulta /api/ps falhou com código {resp.status_code}: {resp.text}"
            )
        data = resp.json()
        models = data.get("models", [])
        if isinstance(models, list):
            return [m for m in models if isinstance(m, dict)]
        return []

    modelos_ativos = consultar_ps()
    alvos = {modelo}
    if ":" not in modelo:
        alvos.add(f"{modelo}:latest")

    item_modelo = next(
        (m for m in modelos_ativos if m.get("name") in alvos or m.get("model") in alvos),
        None,
    )

    # Se ainda não estiver carregado, aquece e consulta novamente
    if item_modelo is None:
        logger.info("Modelo '%s' não está carregado na memória. Aquecendo...", modelo)
        aquecer_modelo(base_url, modelo, timeout=timeout, client=client)
        modelos_ativos = consultar_ps()
        item_modelo = next(
            (m for m in modelos_ativos if m.get("name") in alvos or m.get("model") in alvos),
            None,
        )

    if item_modelo is None:
        raise PreRequisitoError(
            f"FALHA CRÍTICA: Modelo '{modelo}' não apareceu em /api/ps após aquecimento."
        )

    size = int(item_modelo.get("size", 0))
    size_vram = int(item_modelo.get("size_vram", 0))

    if size > 0:
        percentual_vram = (size_vram / size) * 100.0
    else:
        percentual_vram = 100.0 if size_vram > 0 else 0.0

    percentual_cpu = max(0.0, 100.0 - percentual_vram)

    if size_vram == 0 or percentual_cpu > 0.0:
        if not permitir_cpu:
            raise CpuNaoAutorizadaError(
                f"FALHA CRÍTICA: O modelo '{modelo}' está alocado em CPU "
                f"(VRAM: {size_vram} bytes, total: {size} bytes, {percentual_cpu:.1f}% em CPU).\n"
                "Conforme ADR-0002, o Tutor-IA exige GPU para evitar degradação silenciosa.\n"
                "Inicie o Ollama com suporte a GPU no host ou defina OLLAMA_ALLOW_CPU=true "
                "explicitamente apenas para ambientes de teste e desenvolvimento sem GPU."
            )
        logger.warning(
            "ATENÇÃO: O modelo '%s' está alocado em CPU (VRAM: %d / %d bytes, %.1f%% CPU). "
            "Execução autorizada excepcionalmente via OLLAMA_ALLOW_CPU=true.",
            modelo,
            size_vram,
            size,
            percentual_cpu,
        )
    else:
        logger.info(
            "Alocação em GPU confirmada: 100%% VRAM (%d bytes) para o modelo '%s'.",
            size_vram,
            modelo,
        )

    return item_modelo


def executar_checagens(
    config: Configuracao,
    client: httpx.Client | None = None,
) -> None:
    """Executa todas as checagens de pré-requisito sequencialmente."""
    logger.info("Iniciando verificação de pré-requisitos do S.A.U....")
    logger.info("Alvo Ollama: %s | Modelo: %s", config.ollama_base_url, config.ollama_model)

    # 1. Conectividade
    versao = verificar_conectividade(
        config.ollama_base_url,
        timeout=config.ollama_timeout,
        client=client,
    )
    logger.info("Conexão com Ollama estabelecida com sucesso. Versão: %s", versao)

    # 2. Modelo baixado
    verificar_modelo_disponivel(
        config.ollama_base_url,
        config.ollama_model,
        timeout=config.ollama_timeout,
        client=client,
    )
    logger.info("Modelo '%s' encontrado no repositório local do host.", config.ollama_model)

    # 3. GPU / Ausência de CPU não autorizada
    verificar_alocacao_gpu(
        config.ollama_base_url,
        config.ollama_model,
        permitir_cpu=config.ollama_allow_cpu,
        timeout=config.ollama_timeout,
        client=client,
    )

    logger.info("Todos os pré-requisitos foram validados com sucesso.")
