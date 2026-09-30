"""Módulo de checagem rigorosa de pré-requisitos do S.A.U.

Garante que o Ollama no host esteja ativo, com o modelo baixado e alocado
em GPU, impedindo a degradação silenciosa para CPU conforme o ADR-0002. A
alocação é conferida contra a VRAM que a máquina declarou, porque nem a
porta respondendo nem o `size_vram` isolado provam GPU.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from sau.config import Configuracao
from sau.inference.ollama import NUM_CTX_PADRAO

logger = logging.getLogger("sau.prereqs")


class PreRequisitoError(RuntimeError):
    """Exceção base para falhas de pré-requisitos do sistema."""


class OllamaIndisponivelError(PreRequisitoError):
    """Lançada quando a API do Ollama no host não responde."""


class ModeloNaoEncontradoError(PreRequisitoError):
    """Lançada quando o modelo configurado não foi baixado no host."""


class CpuNaoAutorizadaError(PreRequisitoError):
    """Lançada quando o modelo cai para CPU sem autorização explícita."""


class VramNaoInformadaError(PreRequisitoError):
    """Lançada quando o host não declarou a VRAM total que a checagem confronta."""


def modelo_servido_em_cpu(item_ps: dict[str, Any]) -> bool:
    """O `/api/ps` diz que este modelo foi servido sem residência na VRAM?

    `size_vram` zerado é a queda silenciosa que o ADR-0002 nomeia: o Ollama
    aceitou a requisição e serviu o modelo inteiro em CPU. O campo ausente é o
    mesmo veredito para quem precisa decidir se marca um número — não deu para
    confirmar a GPU, e número não confirmado não é número de GPU.

    A regra mora aqui e não no consumidor porque `_diagnosticar_alocacao` já a
    aplica: quem pergunta se o modelo está na GPU e quem decide se o tempo sai
    marcado como CPU precisam responder a mesma pergunta, com a mesma resposta.
    """
    return not int(item_ps.get("size_vram") or 0)


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
    """Dispara uma geração mínima para que o Ollama carregue o modelo na memória.

    O `num_ctx` é o mesmo da geração (`NUM_CTX_PADRAO` do cliente), e é por isso
    que ele é enviado: sem ele o Ollama carrega com o default do servidor, que na
    máquina medida por acaso é o mesmo número. Acaso não é garantia — no dia em
    que a janela da geração mudar, o modelo recarrega, e o primeiro Aluno paga a
    carga duas vezes. Mandar o número trava a igualdade.
    """
    url = f"{base_url.rstrip('/')}/api/generate"
    payload: dict[str, Any] = {
        "model": modelo,
        "prompt": "",
        "keep_alive": "5m",
        "options": {"num_predict": 1, "num_ctx": NUM_CTX_PADRAO},
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


def _diagnosticar_alocacao(
    modelo: str,
    size: int,
    size_vram: int | None,
    vram_total_bytes: int | None,
) -> tuple[type[PreRequisitoError], str] | None:
    """Confere a alocação do modelo contra a VRAM que a máquina declarou.

    Devolve o par (exceção, mensagem) quando a alocação não é aceitável, ou
    None quando o modelo está inteiro na GPU. Cada situação tem mensagem
    própria, porque "não deu para conferir" e "caiu para CPU" pedem ações
    diferentes de quem lê o log, e o diagnóstico que os dois casos tinham em
    comum — "100.0% em CPU" — não separava a queda silenciosa de um payload
    incompleto.
    """
    if vram_total_bytes is None or vram_total_bytes <= 0:
        return VramNaoInformadaError, (
            f"Não foi possível conferir a VRAM do modelo '{modelo}': "
            "a VRAM total da máquina não foi informada.\n"
            "Nenhum endpoint do Ollama reporta o total da placa, então ele tem de "
            "vir do host:\n"
            "  export VRAM_TOTAL_MIB=$(nvidia-smi --query-gpu=memory.total "
            "--format=csv,noheader,nounits | head -1)\n"
            "O head -1 evita que uma máquina com várias placas entregue várias "
            "linhas. Sem esse número a checagem do ADR-0002 não tem contra o que "
            "comparar o size_vram que o Ollama relata."
        )

    if size_vram is None:
        return PreRequisitoError, (
            f"O Ollama não informou o campo 'size_vram' do modelo "
            f"'{modelo}' em /api/ps. O payload veio incompleto, o que é diferente de "
            f"VRAM zerada, e a checagem para aqui em vez de assumir que o modelo está "
            f"na GPU.\n"
            f"O que veio: size={size} bytes, com a máquina declarando "
            f"{vram_total_bytes} bytes de VRAM."
        )

    if size_vram > vram_total_bytes:
        return PreRequisitoError, (
            f"Dados contraditórios para o modelo '{modelo}'. O Ollama "
            f"relata {size_vram} bytes na VRAM, acima dos {vram_total_bytes} bytes "
            f"declarados para a máquina. Um dos dois números está errado, então o "
            f"veredito é impossível: ou o modelo não cabe em {vram_total_bytes} bytes, "
            f"ou VRAM_TOTAL_MIB não descreve a placa em uso."
        )

    if size > vram_total_bytes:
        return PreRequisitoError, (
            f"O modelo '{modelo}' não cabe na placa. O Ollama relata "
            f"{size} bytes para o modelo e a máquina declarou {vram_total_bytes} bytes "
            f"de VRAM.\n"
            "Baixe um modelo menor no host, ou corrija VRAM_TOTAL_MIB se o valor não "
            "for o da placa em uso."
        )

    if size == 0:
        # O payload de /api/ps trouxe zero bytes no total do modelo. Não dá para
        # calcular a fração de CPU: a divisão seria 0/0, e o 0.0% que sai dela é
        # a mesma coisa que dizer que o modelo inteiro está na GPU — que é
        # justamente o que este código existe para não afirmar.
        if size_vram > 0:
            leitura = (
                f"e size_vram={size_vram}, o que é autocontraditório: não se pode "
                "ocupar mais VRAM do que o tamanho do modelo."
            )
        else:
            leitura = "e size_vram=0, ou seja, o modelo não tem residência no Ollama."
        return PreRequisitoError, (
            f"O /api/ps relata size={size} para o modelo '{modelo}', {leitura}\n"
            f"A máquina declarou {vram_total_bytes} bytes de VRAM, que é o que "
            "tornaria a checagem possível se houvesse o que conferir.\n"
            "Aqueça o modelo no host para que ele ocupe memória "
            f"('ollama run {modelo}' e interrompa com Ctrl+C), e confira o que "
            "o Ollama passou a relatar:\n"
            "  ollama ps"
        )

    percentual_cpu = (size - size_vram) / size * 100.0

    if size_vram == 0:
        return CpuNaoAutorizadaError, (
            f"Queda silenciosa para CPU. A máquina tem "
            f"{vram_total_bytes} bytes de VRAM declarados, mas o Ollama relata "
            f"size_vram=0 para o modelo '{modelo}' ({size} bytes, "
            f"{percentual_cpu:.1f}% em CPU).\n"
            "Conforme ADR-0002, o Tutor-IA exige GPU para evitar degradação silenciosa.\n"
            "Inicie o Ollama no host com suporte a GPU, ou defina OLLAMA_ALLOW_CPU=true "
            "explicitamente apenas para ambientes de teste e desenvolvimento sem GPU."
        )

    if size_vram < size:
        return CpuNaoAutorizadaError, (
            f"Spill parcial para CPU. O modelo '{modelo}' tem {size} "
            f"bytes, dos quais {size_vram} estão na VRAM e os {size - size_vram} "
            f"restantes em CPU ({percentual_cpu:.1f}% em CPU).\n"
            "Conforme ADR-0002, o Tutor-IA exige o modelo inteiro na GPU para evitar "
            "degradação silenciosa.\n"
            "Baixe um modelo menor no host, ou defina OLLAMA_ALLOW_CPU=true "
            "explicitamente apenas para ambientes de teste e desenvolvimento sem GPU."
        )

    return None


def verificar_alocacao_gpu(
    base_url: str,
    modelo: str,
    permitir_cpu: bool = False,
    vram_total_bytes: int | None = None,
    timeout: float = 30.0,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Verifica se o modelo está alocado em GPU via /api/ps.

    Caso o modelo não esteja em execução, realiza aquecimento prévio.

    O confronto é entre o que o Ollama relata e a VRAM que a máquina declarou,
    porque nenhum dos dois lados basta sozinho: porta respondendo não prova
    GPU, e size_vram sem o total da placa não diz se o modelo coube. Sem
    permitir_cpu, qualquer uma das situações que não fecha é falha alta; com
    permitir_cpu, todas viram warning e a execução segue — é o que fecha o
    caminho de dev e de CI sem GPU.
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
        dados = resp.json()
        modelos = dados.get("models", [])
        if isinstance(modelos, list):
            return [m for m in modelos if isinstance(m, dict)]
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
    # Campo ausente e campo zerado são defeitos diferentes: o primeiro impede o
    # diagnóstico, o segundo é a queda silenciosa que o ADR-0002 existe para
    # fechar. Tratar os dois como zero apagaria a diferença entre "não deu para
    # conferir" e "caiu para CPU".
    vram_relatada = item_modelo.get("size_vram")
    size_vram = int(vram_relatada) if vram_relatada is not None else None

    diagnostico = _diagnosticar_alocacao(modelo, size, size_vram, vram_total_bytes)
    if diagnostico is not None:
        erro, mensagem = diagnostico
        if not permitir_cpu:
            # O "FALHA CRÍTICA" fica no ponto em que a falha é uma falha, e não
            # dentro da mensagem: autorizada, a mesma mensagem sai como warning,
            # e a palavra se contradiria com o "ATENÇÃO" do log.
            raise erro(f"FALHA CRÍTICA: {mensagem}")
        logger.warning(
            "ATENÇÃO: %s\nA execução segue por autorização explícita em "
            "OLLAMA_ALLOW_CPU=true.",
            mensagem,
        )
        return item_modelo

    logger.info(
        "Alocação em GPU confirmada: %d bytes na VRAM para o modelo '%s', contra %d "
        "bytes declarados para a máquina.",
        size_vram,
        modelo,
        vram_total_bytes,
    )
    return item_modelo


def executar_checagens(
    config: Configuracao,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Executa todas as checagens de pré-requisito sequencialmente.

    Devolve o item do `/api/ps` que a checagem de alocação leu. Quem só quer o
    veredito — o serviço, na subida — ignora o retorno; quem vai medir precisa
    da evidência, e a evidência já estava na mão: as checagens leram o
    processador do modelo para decidir se passam, e essa leitura não ia para
    lugar nenhum. `modelo_servido_em_cpu` é o veredito sobre esse item.
    """
    logger.info("Iniciando verificação de pré-requisitos do S.A.U....")
    vram_declarada = (
        f"{config.vram_total_bytes} bytes" if config.vram_total_bytes else "não declarada"
    )
    logger.info(
        "Alvo Ollama: %s | Modelo: %s | VRAM da máquina: %s",
        config.ollama_base_url,
        config.ollama_model,
        vram_declarada,
    )

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
    alocacao = verificar_alocacao_gpu(
        config.ollama_base_url,
        config.ollama_model,
        permitir_cpu=config.ollama_allow_cpu,
        vram_total_bytes=config.vram_total_bytes,
        timeout=config.ollama_timeout,
        client=client,
    )

    logger.info("Todos os pré-requisitos foram validados com sucesso.")
    return alocacao
