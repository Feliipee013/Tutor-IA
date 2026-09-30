"""Testes unitários para o módulo de configuração sau/config.py."""

from __future__ import annotations

import pytest

from sau.config import carregar_configuracao
from sau.inference.semaphore import K_PADRAO, TETO_PADRAO_DA_FILA


def test_configuracao_valores_padrao() -> None:
    config = carregar_configuracao({})
    assert config.ollama_base_url == "http://host.docker.internal:11434"
    assert config.ollama_model == "qwen2.5:3b"
    assert config.ollama_timeout == 30.0
    assert config.ollama_allow_cpu is False
    assert config.vram_total_bytes is None
    assert config.bot_port == 8000
    assert config.bot_env == "development"
    assert config.log_level == "INFO"
    assert config.telegram_bot_token is None
    assert config.telegram_webhook_secret_token is None


def test_configuracao_sobrescrita_via_ambiente() -> None:
    env = {
        "OLLAMA_BASE_URL": "http://localhost:11434",
        "OLLAMA_MODEL": "qwen2.5:3b",
        "OLLAMA_TIMEOUT": "45.5",
        "OLLAMA_ALLOW_CPU": "true",
        "VRAM_TOTAL_MIB": "4096",
        "BOT_PORT": "9000",
        "BOT_ENV": "production",
        "LOG_LEVEL": "DEBUG",
    }
    config = carregar_configuracao(env)
    assert config.ollama_base_url == "http://localhost:11434"
    assert config.ollama_model == "qwen2.5:3b"
    assert config.ollama_timeout == 45.5
    assert config.ollama_allow_cpu is True
    assert config.vram_total_bytes == 4096 * 1_048_576
    assert config.bot_port == 9000
    assert config.bot_env == "production"
    assert config.log_level == "DEBUG"


def test_configuracao_vram_ausente_ou_vazia() -> None:
    """Ausente de verdade e string vazia do compose são a mesma coisa."""
    assert carregar_configuracao({}).vram_total_bytes is None
    assert carregar_configuracao({"VRAM_TOTAL_MIB": ""}).vram_total_bytes is None
    assert carregar_configuracao({"VRAM_TOTAL_MIB": "   "}).vram_total_bytes is None


def test_configuracao_vram_aceita_espaco_em_branco() -> None:
    config = carregar_configuracao({"VRAM_TOTAL_MIB": " 4096 "})
    assert config.vram_total_bytes == 4096 * 1_048_576


@pytest.mark.parametrize("valor", ["invalido", "0", "-1", "-4096"])
def test_configuracao_vram_invalida(valor: str) -> None:
    with pytest.raises(ValueError, match="Valor inválido para VRAM_TOTAL_MIB"):
        carregar_configuracao({"VRAM_TOTAL_MIB": valor})


def test_configuracao_vram_de_multiplas_gpus_explica_a_causa() -> None:
    """O nvidia-smi imprime uma linha por GPU, e é essa a causa provável.

    Uma máquina com duas placas entrega "4096\n4096" para o export, que não é
    um inteiro. A mensagem precisa apontar o motivo, senão quem lê só vê
    "Esperado um inteiro positivo" e não descobre de onde veio a quebra.
    """
    with pytest.raises(ValueError) as exc_info:
        carregar_configuracao({"VRAM_TOTAL_MIB": "4096\n4096"})

    msg = str(exc_info.value)
    assert "UMA LINHA POR GPU" in msg
    assert "head -1" in msg
    # A causa original do int() fica preservada, para o log do container mostrar
    # a linha que o nvidia-smi entregou.
    assert isinstance(exc_info.value.__cause__, ValueError)


@pytest.mark.parametrize("valor,esperado", [
    ("1", True),
    ("True", True),
    ("TRUE", True),
    ("yes", True),
    ("sim", True),
    ("0", False),
    ("false", False),
    ("no", False),
    ("nao", False),
    ("", False),
])
def test_configuracao_boolean_allow_cpu(valor: str, esperado: bool) -> None:
    config = carregar_configuracao({"OLLAMA_ALLOW_CPU": valor})
    assert config.ollama_allow_cpu is esperado


def test_configuracao_timeout_invalido() -> None:
    with pytest.raises(ValueError, match="Valor inválido para OLLAMA_TIMEOUT"):
        carregar_configuracao({"OLLAMA_TIMEOUT": "invalido"})


def test_configuracao_porta_invalida() -> None:
    with pytest.raises(ValueError, match="Valor inválido para BOT_PORT"):
        carregar_configuracao({"BOT_PORT": "oito_mil"})


# --- Credenciais do Telegram ---


def test_configuracao_telegram_padroes_sem_credenciais() -> None:
    """Quem não conversa com o Telegram sobe sem elas.

    O serviço do bot não fala com o Telegram, então a ausência das credenciais
    não pode ser erro de parsing — a obrigatoriedade mora no webhook.
    """
    config = carregar_configuracao({})
    assert config.telegram_bot_token is None
    assert config.telegram_webhook_secret_token is None
    assert config.telegram_webhook_port == 8080
    assert config.telegram_api_base == "https://api.telegram.org"


def test_configuracao_telegram_credenciais_lidas_do_ambiente() -> None:
    config = carregar_configuracao({
        "TELEGRAM_BOT_TOKEN": "  7123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw  ",
        "TELEGRAM_WEBHOOK_SECRET_TOKEN": " chave-de-desenvolvimento ",
        "TELEGRAM_WEBHOOK_PORT": "9001",
        "TELEGRAM_API_BASE": "https://api.exemplo.invalid",
    })
    assert config.telegram_bot_token == "7123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw"
    assert config.telegram_webhook_secret_token == "chave-de-desenvolvimento"
    assert config.telegram_webhook_port == 9001
    assert config.telegram_api_base == "https://api.exemplo.invalid"


@pytest.mark.parametrize("variavel", ["TELEGRAM_BOT_TOKEN", "TELEGRAM_WEBHOOK_SECRET_TOKEN"])
@pytest.mark.parametrize("bruto", ["", "   "])
def test_configuracao_telegram_credencial_vazia_vira_ausente(
    variavel: str, bruto: str
) -> None:
    """Ausente de verdade e string vazia do compose são a mesma coisa."""
    config = carregar_configuracao({variavel: bruto})
    valor = (
        config.telegram_bot_token
        if variavel == "TELEGRAM_BOT_TOKEN"
        else config.telegram_webhook_secret_token
    )
    assert valor is None


def test_configuracao_telegram_porta_invalida() -> None:
    with pytest.raises(ValueError, match="Valor inválido para TELEGRAM_WEBHOOK_PORT"):
        carregar_configuracao({"TELEGRAM_WEBHOOK_PORT": "oito_mil"})


# --- O semáforo de inferência (a #11) ---


def test_configuracao_semaforo_tem_padrao() -> None:
    """Sem variável no ambiente, o semáforo nasce com os números declarados.

    O `2` é o ponto de partida do ADR-0001, e o `10` é o teto arbitrário declarado
    no mesmo espírito do `TETO_DE_TURNOS_ESPERANDO` da #9. Os dois existem como
    padrão para que o serviço suba sem configuração nenhuma, e nenhum dos dois é
    o número medido: o `k` medido na máquina alvo é o procedimento de
    `docs/fila-e-semaforo.md`, cujo campo está em branco até a medição acontecer.
    """
    config = carregar_configuracao({})
    assert config.inferencia_k == K_PADRAO
    assert config.inferencia_fila_teto == TETO_PADRAO_DA_FILA


def test_configuracao_semaforo_lido_do_ambiente() -> None:
    config = carregar_configuracao({"INFERENCIA_K": "3", "INFERENCIA_FILA_TETO": "25"})
    assert config.inferencia_k == 3
    assert config.inferencia_fila_teto == 25


@pytest.mark.parametrize("bruto", ["0", "-1", "abc", "2.5", ""])
def test_configuracao_k_invalido(bruto: str) -> None:
    """`k` tem de ser inteiro positivo, e a recusa é na leitura.

    Zero é o caso que dói: com `k=0` nenhuma vaga existiria e todo turno ficaria
    esperando para sempre, sem que ninguém percebesse. O `.env` não denuncia zero,
    e é por isso que a falha tem que ser na partida do serviço.
    """
    with pytest.raises(ValueError, match="Valor inválido para INFERENCIA_K"):
        carregar_configuracao({"INFERENCIA_K": bruto})


@pytest.mark.parametrize("bruto", ["0", "-1", "abc", ""])
def test_configuracao_teto_da_fila_invalido(bruto: str) -> None:
    """O teto tem a mesma exigência, e pelo mesmo motivo do `k`.

    Com teto `0` o primeiro turno fora de vaga seria recusado antes de a fila de
    espera chegar a existir — o serviço pareceria quebrado para todo mundo, o
    tempo todo, sem nenhuma fila para olhar.
    """
    with pytest.raises(ValueError, match="Valor inválido para INFERENCIA_FILA_TETO"):
        carregar_configuracao({"INFERENCIA_FILA_TETO": bruto})


def test_configuracao_k_invalido_aponta_onde_medir() -> None:
    """A mensagem do `k` precisa dizer que o número é medido, não escolhido.

    O ADR-0001 exige que o `k` venha de medição na máquina alvo, e alguém que
    escrever `INFERENCIA_K=8` por palpite precisa encontrar na falha o caminho
    para a medição — não só a informação de que 8 não é aceito.
    """
    with pytest.raises(ValueError) as exc_info:
        carregar_configuracao({"INFERENCIA_K": "0"})

    assert "docs/fila-e-semaforo.md" in str(exc_info.value)


def test_configuracao_semaforo_aceita_espaco_em_branco() -> None:
    """O mesmo trimming que o resto da configuração aceita."""
    config = carregar_configuracao({"INFERENCIA_K": " 3 ", "INFERENCIA_FILA_TETO": " 25 "})
    assert config.inferencia_k == 3
    assert config.inferencia_fila_teto == 25
