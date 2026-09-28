"""Testes da prova de fumaça `sau/inference/fumaca.py` e do script de host.

O `scripts/preparar-host.sh` entra aqui porque ele é a outra metade da fumaça:
um é o lado de dentro do container, o outro é o lado de fora, na máquina. O
script é testado chamando-o de verdade, com o `PATH` apontado para um diretório
temporário que tem `ollama`, `nvidia-smi` e `curl` falsos — assim o teste não
depende da máquina em que roda, não baixa nada e não fala com o Ollama real.
"""

from __future__ import annotations

import ast
import os
import re
import stat
import subprocess
from pathlib import Path
from typing import Any

import httpx
import pytest

from sau.config import Configuracao
from sau.inference import fumaca
from sau.inference.ollama import ClienteOllama
from sau.prereqs import executar_checagens

_MODELO = "qwen2.5:3b"
_VRAM_8GIB = 8176 * 1_048_576
_RAIZ = Path(__file__).resolve().parent.parent
_SCRIPT = _RAIZ / "scripts" / "preparar-host.sh"


# --------------------------------------------------------------------------- #
# Ollama falso para a fumaça
# --------------------------------------------------------------------------- #


def _config_de_teste(**mudancas: Any) -> Configuracao:
    base: dict[str, Any] = {
        "ollama_base_url": "http://host.docker.internal:11434",
        "ollama_model": _MODELO,
        "ollama_timeout": 10.0,
        "ollama_allow_cpu": False,
        "vram_total_bytes": _VRAM_8GIB,
        "bot_port": 8000,
        "bot_env": "test",
        "log_level": "INFO",
    }
    base.update(mudancas)
    return Configuracao(**base)


def _geracao(texto: str = "O prazo eu não sei.", **extra: Any) -> dict[str, Any]:
    return {
        "model": _MODELO,
        "response": texto,
        "done": True,
        "done_reason": "stop",
        "load_duration": 400_000_000,
        "prompt_eval_duration": 100_000_000,
        "eval_duration": 1_000_000_000,
        "eval_count": 50,
        **extra,
    }


def _item_ps(size_vram: int) -> dict[str, Any]:
    return {"name": _MODELO, "size": 2_000_000_000, "size_vram": size_vram}


def _ollama_falso(
    *,
    size_vram: int = 2_000_000_000,
    geracao: dict[str, Any] | None = None,
    status_geracao: int = 200,
) -> httpx.Client:
    """Ollama que responde às três consultas de pré-requisito e à geração."""

    def handler(request: httpx.Request) -> httpx.Response:
        caminho = request.url.path
        if caminho == "/api/version":
            return httpx.Response(200, json={"version": "0.34.4"}, request=request)
        if caminho == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": _MODELO}]}, request=request)
        if caminho == "/api/ps":
            return httpx.Response(200, json={"models": [_item_ps(size_vram)]}, request=request)
        if caminho == "/api/generate":
            if status_geracao != 200:
                return httpx.Response(
                    status_geracao, text="model runner exited", request=request
                )
            return httpx.Response(200, json=geracao or _geracao(), request=request)
        return httpx.Response(404, request=request)

    return httpx.Client(transport=httpx.MockTransport(handler))


def _ligar_ollama_falso(monkeypatch: pytest.MonkeyPatch, cliente: httpx.Client) -> None:
    """Faz a fumaça falar com o Ollama falso em vez do host.

    As checagens de pré-requisito também recebem o cliente falso, e não são
    substituídas: a fumaça precisa passar por elas de verdade, porque é a
    queda para CPU delas que este teste está provando.
    """

    def fabrica(base_url: str, modelo: str, timeout: float = 60.0, **kwargs: Any) -> Any:
        return ClienteOllama(base_url, modelo, timeout=timeout, client=cliente)

    def checagens(config: Configuracao) -> None:
        executar_checagens(config, client=cliente)

    monkeypatch.setattr(fumaca, "ClienteOllama", fabrica)
    monkeypatch.setattr(fumaca, "executar_checagens", checagens)
    # A configuração vem do ambiente, e o ambiente da pessoa que roda o teste
    # não tem VRAM_TOTAL_MIB. Sem isto a checagem do ADR-0002 reprovaria antes
    # de a fumaça chegar à geração — o que é certo, mas não é o que se quer
    # testar aqui.
    monkeypatch.setattr(fumaca, "carregar_configuracao", _config_de_teste)


@pytest.fixture
def ollama_preso(monkeypatch: pytest.MonkeyPatch) -> httpx.Client:
    """Ollama de mentira, em GPU, respondendo o que a fumaça pergunta."""
    cliente = _ollama_falso()
    _ligar_ollama_falso(monkeypatch, cliente)
    return cliente


# --------------------------------------------------------------------------- #
# A fumaça imprime o que promete
# --------------------------------------------------------------------------- #


def test_fumaca_imprime_o_bloco_de_tempos(
    ollama_preso: httpx.Client, capsys: pytest.CaptureFixture[str]
) -> None:
    assert fumaca.main(["--repeticoes", "1"]) == 0

    saida = capsys.readouterr().out
    assert "FUMAÇA DA INFERÊNCIA DO S.A.U." in saida
    assert "TEMPOS DA GERAÇÃO" in saida
    # Os sete campos que o plano da #7 pede no bloco.
    assert "primeiro token (ttft):  0.500 s" in saida
    assert "carga do modelo:         0.400 s" in saida
    assert "leitura do prompt:      0.100 s" in saida
    assert re.search(r"total:\s+\d+\.\d{3} s", saida)
    assert "50.0 tok/s" in saida
    assert "tokens gerados:         50" in saida
    assert "parou porque:           stop" in saida


def test_fumaca_escreve_a_resposta_do_modelo_no_log(
    ollama_preso: httpx.Client, capsys: pytest.CaptureFixture[str]
) -> None:
    """O quinto critério da #7: a saída do modelo fica em log, para ser lida.

    O teste olha o log no stdout, e não o objeto de log do Python, porque é o
    stdout que a pessoa lê no `docker compose logs`. E o prefixo `[SAU-BOT]` vem
    do mesmo `configurar_logging` do serviço: a evidência é a mesma coisa nos
    dois lugares, e não duas com nomes diferentes.
    """
    assert fumaca.main([]) == 0

    saida = capsys.readouterr().out
    linha_do_log = next(
        linha for linha in saida.splitlines() if "sau.inference.ollama" in linha
    )
    assert "[SAU-BOT]" in linha_do_log
    assert "[INFO]" in linha_do_log
    # O texto do modelo vai na linha seguinte à do registro, inteiro.
    assert "O prazo eu não sei." in saida


def test_fumaca_repeticoes_separam_a_primeira_das_demais(
    ollama_preso: httpx.Client, capsys: pytest.CaptureFixture[str]
) -> None:
    """A primeira geração paga a carga do modelo; as outras, não.

    A média das duas coisas seria um número que nenhum Aluno pagou, e é por isso
    que a fumaça separa as duas leituras em vez de jogar tudo numa média só.
    """
    assert fumaca.main(["--repeticoes", "3"]) == 0

    saida = capsys.readouterr().out
    assert "1ª geração, com a carga do modelo:  0.500 s" in saida
    assert "demais gerações, modelo carregado: 0.500 s (média de 2)" in saida
    assert "--- geração 2/3 ---" in saida
    assert "--- geração 3/3 ---" in saida


def test_fumaca_avisa_geracao_nao_concluida(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`done: false` com `length` é texto pela metade, e o Aluno receberia assim."""
    _ligar_ollama_falso(
        monkeypatch,
        _ollama_falso(geracao=_geracao(done=False, done_reason="length")),
    )

    assert fumaca.main([]) == 0

    saida = capsys.readouterr().out
    assert "geração NÃO terminou" in saida
    assert "parou porque:           length" in saida


# --------------------------------------------------------------------------- #
# De onde vem a pergunta
# --------------------------------------------------------------------------- #


def test_fumaca_usa_a_pergunta_padrao_sem_flag() -> None:
    assert fumaca.ler_pergunta(fumaca.Opcoes.de_argumentos([])) == fumaca.PERGUNTA_PADRAO


def test_fumaca_usa_a_pergunta_da_flag() -> None:
    args = fumaca.Opcoes.de_argumentos(["--pergunta", "  Oi, tudo bem?  "])
    assert fumaca.ler_pergunta(args) == "Oi, tudo bem?"


def test_fumaca_usa_a_pergunta_do_arquivo_preservando_as_linhas(tmp_path: Path) -> None:
    """Uma Pergunta-teste tem várias linhas, e quebrada não é a mesma pergunta."""
    arquivo = tmp_path / "pergunta.txt"
    arquivo.write_text("Quando vence a entrega?\nEm que dia?\n", encoding="utf-8")

    args = fumaca.Opcoes.de_argumentos(["--de-arquivo", str(arquivo)])

    assert fumaca.ler_pergunta(args) == "Quando vence a entrega?\nEm que dia?"


def test_fumaca_para_com_pergunta_vazia() -> None:
    with pytest.raises(SystemExit) as exc_info:
        fumaca.ler_pergunta(fumaca.Opcoes.de_argumentos(["--pergunta", "   "]))
    assert exc_info.value.code != 0


def test_fumaca_para_com_arquivo_vazio(tmp_path: Path) -> None:
    arquivo = tmp_path / "vazio.txt"
    arquivo.write_text("\n\n", encoding="utf-8")

    with pytest.raises(SystemExit) as exc_info:
        fumaca.ler_pergunta(fumaca.Opcoes.de_argumentos(["--de-arquivo", str(arquivo)]))

    assert exc_info.value.code != 0


def test_fumaca_para_com_arquivo_inexistente(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc_info:
        fumaca.ler_pergunta(
            fumaca.Opcoes.de_argumentos(["--de-arquivo", str(tmp_path / "nao-existe.txt")])
        )

    assert exc_info.value.code != 0


def test_fumaca_recusa_pergunta_e_arquivo_juntos() -> None:
    with pytest.raises(SystemExit) as exc_info:
        fumaca.Opcoes.de_argumentos(["--pergunta", "a", "--de-arquivo", "b"])
    assert exc_info.value.code != 0


def test_fumaca_nao_le_o_arquivo_de_perguntas_teste() -> None:
    """As 10 Perguntas-teste são a régua da #12, e a fumaça não mexe nelas.

    A pergunta padrão é sintética e está no próprio módulo. Se a fumaça passasse a
    ler `perguntas-teste/`, ela traria uma medição sem `temperature` nem `seed`
    para dentro da comparação da #12, e o número apareceria ao lado dos outros
    como se fosse da mesma régua.
    """
    assert fumaca.PERGUNTA_PADRAO

    texto_do_p1 = _texto_da_pergunta_teste("p1")
    if texto_do_p1 is not None:
        assert fumaca.PERGUNTA_PADRAO != texto_do_p1

    # E o módulo não tem nem o caminho do arquivo entre o código: o único lugar
    # em que o nome aparece é a docstring, que explica por que ele não é usado.
    for constante in _constantes_de_codigo(fumaca):
        assert "perguntas-teste" not in constante


def _constantes_de_codigo(modulo: Any) -> list[str]:
    """As strings do módulo que o código executa, sem as docstrings.

    A docstring da fumaça cita `perguntas-teste/` para dizer que não lê o
    arquivo, e é o código — não o texto sobre o código — que a garantia
    precisa olhar.
    """
    arvore = ast.parse(Path(modulo.__file__).read_text(encoding="utf-8"))
    docstrings = {
        id(corpo.value)
        for no in ast.walk(arvore)
        if isinstance(no, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
        for corpo in no.body[:1]
        if isinstance(corpo, ast.Expr) and isinstance(corpo.value, ast.Constant)
    }
    return [
        no.value
        for no in ast.walk(arvore)
        if isinstance(no, ast.Constant)
        and isinstance(no.value, str)
        and id(no) not in docstrings
    ]


def _texto_da_pergunta_teste(identificador: str) -> str | None:
    """Lê o texto de uma Pergunta-teste, ou None se o arquivo não estiver lá."""
    arquivo = _RAIZ / "perguntas-teste" / "perguntas-teste.md"
    if not arquivo.is_file():
        return None
    achado = re.search(
        rf"<!--\s*pergunta:{identificador}\s*-->\s*```[a-z]*\n(.*?)```",
        arquivo.read_text(encoding="utf-8"),
        re.DOTALL,
    )
    return achado.group(1).strip() if achado else None


# --------------------------------------------------------------------------- #
# Falha alta
# --------------------------------------------------------------------------- #


def test_fumaca_para_quando_o_modelo_esta_em_cpu(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """O padrão exige a GPU do host, como o `medir.py` e o ADR-0002 exigem.

    Sem esta comporta, o tempo desta máquina entraria no documento como se fosse
    o tempo de produção — e um tempo em CPU é plausível e errado ao mesmo tempo.
    """
    _ligar_ollama_falso(monkeypatch, _ollama_falso(size_vram=0))

    with pytest.raises(SystemExit) as exc_info:
        fumaca.main([])

    assert exc_info.value.code != 0
    capturado = capsys.readouterr()
    erro = capturado.err
    assert "FALHA" in erro
    assert "Queda silenciosa para CPU" in erro
    assert "checagem de pré-requisito" in erro
    # E nada foi gerado: com a checagem reprovada, não há o que medir.
    assert "TEMPOS DA GERAÇÃO" not in capturado.out


def test_fumaca_com_permitir_cpu_roda_e_avisa_que_o_numero_e_de_cpu(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Com `--permitir-cpu` a fumaça roda, e diz que o número é de CPU.

    Autorizar não pode ser silêncio: um tempo de CPU que entra no documento sem
    aviso é exatamente o defeito que o ADR-0002 existe para fechar.
    """
    _ligar_ollama_falso(monkeypatch, _ollama_falso(size_vram=0))

    assert fumaca.main(["--permitir-cpu", "--repeticoes", "2"]) == 0

    saida = capsys.readouterr().out
    assert "TEMPOS DA GERAÇÃO" in saida
    assert "medido com --permitir-cpu" in saida
    assert "não descreve a máquina do ADR-0002" in saida


def test_fumaca_sem_permitir_cpu_nao_avisa_que_rodou_em_cpu(
    ollama_preso: httpx.Client, capsys: pytest.CaptureFixture[str]
) -> None:
    """O aviso é sobre CPU medida, e não sai quando a GPU está em uso."""
    assert fumaca.main([]) == 0
    assert "medido com --permitir-cpu" not in capsys.readouterr().out


def test_fumaca_para_quando_a_vram_da_maquina_nao_e_declarada(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Sem VRAM declarada a checagem do ADR-0002 não tem contra o que comparar."""
    _ligar_ollama_falso(monkeypatch, _ollama_falso())
    monkeypatch.setattr(fumaca, "carregar_configuracao", lambda: _config_de_teste(
        vram_total_bytes=None
    ))

    with pytest.raises(SystemExit) as exc_info:
        fumaca.main([])

    assert exc_info.value.code != 0
    assert "VRAM" in capsys.readouterr().err


def test_fumaca_para_quando_a_geracao_falha(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Pré-requisito bom e geração ruim é falha, e sai com código de erro."""
    _ligar_ollama_falso(monkeypatch, _ollama_falso(status_geracao=500))

    with pytest.raises(SystemExit) as exc_info:
        fumaca.main([])

    assert exc_info.value.code != 0
    erro = capsys.readouterr().err
    assert "o modelo não respondeu" in erro
    assert "model runner exited" in erro


def test_fumaca_para_quando_a_configuracao_e_invalida(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Uma variável de ambiente inválida para antes de falar com o modelo."""

    def carregar() -> Configuracao:
        raise ValueError("Valor inválido para VRAM_TOTAL_MIB: 'quatro mil'.")

    monkeypatch.setattr(fumaca, "carregar_configuracao", carregar)

    with pytest.raises(SystemExit) as exc_info:
        fumaca.main([])

    assert exc_info.value.code != 0
    assert "VRAM_TOTAL_MIB" in capsys.readouterr().err


def test_fumaca_rejeita_repeticoes_zero() -> None:
    with pytest.raises(SystemExit) as exc_info:
        fumaca.main(["--repeticoes", "0"])
    assert exc_info.value.code != 0


# --------------------------------------------------------------------------- #
# scripts/preparar-host.sh
# --------------------------------------------------------------------------- #


def _exec(caminho: Path, corpo: str) -> None:
    caminho.write_text(f"#!/usr/bin/env bash\n{corpo}\n", encoding="utf-8")
    caminho.chmod(caminho.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _linha_ps(processador: str) -> str:
    return f"{_MODELO}    357c53fb659c    2.2 GB    {processador}     4096    29 minutes from now"


# O `ollama` falso cobre `list` (o modelo já está ou não), `pull` (marca um
# arquivo, para um pull indevido quebrar o teste) e `ps` (a linha do processador).
_OLLAMA_MODELO_PRESENTE = f"""
if [ "$1" = "list" ]; then
  echo "NAME                ID              SIZE      MODIFIED"
  echo "{_MODELO}    357c53fb659c    1.9 GB    now"
fi
if [ "$1" = "pull" ]; then
  echo "pull" >> "$PULL_REGISTRADO"
  exit 1
fi
if [ "$1" = "ps" ]; then
  echo "{_linha_ps('100% GPU')}"
fi
"""

_OLLAMA_MODELO_AUSENTE = f"""
if [ "$1" = "list" ]; then
  echo "NAME                ID              SIZE      MODIFIED"
  echo "llama3.2:3b         abc123          1.9 GB    now"
fi
if [ "$1" = "pull" ]; then
  echo "$2" > "$PULL_REGISTRADO"
fi
if [ "$1" = "ps" ]; then
  echo "{_linha_ps('100% GPU')}"
fi
"""


def _montar_maquina(
    pasta: Path,
    *,
    nvidia_smi: str | None = None,
    ollama: str = _OLLAMA_MODELO_PRESENTE,
    pull_registrado: Path,
    processador: str = "100% GPU",
) -> Path:
    """Monta o `PATH` falso da máquina de teste e devolve o diretório dele.

    O `/sys/class/drm` falso fica em `pasta / "drm"`, que os testes montam
    separado — ele é por placa, e cada teste tem o seu caso.
    """
    ferramentas = pasta / "bin"
    ferramentas.mkdir(parents=True, exist_ok=True)

    if nvidia_smi is not None:
        _exec(ferramentas / "nvidia-smi", f'echo "{nvidia_smi}"')

    ollama_com_ps = ollama.replace("100% GPU", processador)
    _exec(ferramentas / "ollama", ollama_com_ps)

    # O `curl` também é falso: a máquina de teste não tem Ollama, e o script
    # precisa falar com algo para conferir que o serviço está no ar e carregar o
    # modelo. Sem isto o teste dependeria do Ollama real desta máquina.
    # `CURL_FALHO` derruba toda chamada; `CURL_GERAR_FALHO` derruba só a carga do
    # modelo, o que é o caminho de "conferi que está no ar, mas não consegui
    # carregar" — um estado que precisa de aviso próprio.
    _exec(
        ferramentas / "curl",
        'if [ -n "$CURL_FALHO" ]; then echo "curl: (7) Failed to connect" >&2; exit 7; fi\n'
        'case "$*" in\n'
        '  *api/generate*)\n'
        '    if [ -n "$CURL_GERAR_FALHO" ]; then\n'
        '      echo "curl: (28) Operation timed out" >&2\n'
        '      exit 28\n'
        '    fi\n'
        '    ;;\n'
        'esac\n'
        'exit 0',
    )

    (pasta / "drm").mkdir(parents=True, exist_ok=True)
    return ferramentas


def _criar_cartao(drm: Path, nome: str, bytes_total: int) -> None:
    device = drm / nome / "device"
    device.mkdir(parents=True, exist_ok=True)
    (device / "mem_info_vram_total").write_text(f"{bytes_total}\n", encoding="utf-8")


def _rodar_script(
    pasta: Path,
    ferramentas: Path,
    pull_registrado: Path,
    env_extra: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    # Só o PATH é trocado, e o `DRM_DIR` aponta para o `/sys/class/drm` falso.
    # O resto do sistema fica, para o bash, o awk e o cat continuarem funcionando.
    env["PATH"] = f"{ferramentas}:{env['PATH']}"
    env["DRM_DIR"] = str(pasta / "drm")
    env["PULL_REGISTRADO"] = str(pull_registrado)
    if env_extra:
        env.update(env_extra)

    return subprocess.run(
        ["bash", str(_SCRIPT)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        check=False,
    )


def test_script_descobre_a_vram_pelo_nvidia_smi(tmp_path: Path) -> None:
    """O caminho de quem tem placa NVIDIA, que é o da máquina do ADR-0002."""
    registro = tmp_path / "pulls.txt"
    ferramentas = _montar_maquina(tmp_path, nvidia_smi="8176", pull_registrado=registro)

    resultado = _rodar_script(tmp_path, ferramentas, registro)

    assert resultado.returncode == 0, resultado.stderr
    assert "VRAM_TOTAL_MIB=8176" in resultado.stdout
    assert "export VRAM_TOTAL_MIB=8176" in resultado.stdout


def test_script_usa_a_primeira_linha_do_nvidia_smi(tmp_path: Path) -> None:
    """O `nvidia-smi` imprime uma linha por GPU, e duas linhas não são número."""
    registro = tmp_path / "pulls.txt"
    ferramentas = tmp_path / "bin"
    ferramentas.mkdir()
    _exec(ferramentas / "nvidia-smi", 'echo "8176"\necho "4096"')
    _exec(ferramentas / "ollama", _OLLAMA_MODELO_PRESENTE)
    _exec(ferramentas / "curl", "exit 0")
    (tmp_path / "drm").mkdir()

    resultado = _rodar_script(tmp_path, ferramentas, registro)

    assert resultado.returncode == 0, resultado.stderr
    assert "VRAM_TOTAL_MIB=8176" in resultado.stdout


def test_script_descobre_a_vram_pelo_sysfs_quando_nao_ha_nvidia_smi(tmp_path: Path) -> None:
    """A placa desta máquina é AMD, e o `nvidia-smi` não existe.

    Buscar a VRAM só pelo `nvidia-smi` acharia que a máquina não tem placa, e a
    pessoa ficaria sem o `VRAM_TOTAL_MIB` sem saber por quê.
    """
    registro = tmp_path / "pulls.txt"
    ferramentas = _montar_maquina(tmp_path, nvidia_smi=None, pull_registrado=registro)
    _criar_cartao(tmp_path / "drm", "card1", 8_573_157_376)

    resultado = _rodar_script(tmp_path, ferramentas, registro)

    assert resultado.returncode == 0, resultado.stderr
    assert "VRAM_TOTAL_MIB=8176" in resultado.stdout


def test_script_arredonda_a_vram_do_sysfs_para_cima(tmp_path: Path) -> None:
    """A VRAM declarada é confrontada com o `size_vram` do Ollama.

    Arredondar para baixo faria a placa parecer MENOR do que é, e aí uma
    alocação que cabe seria reprovada com "dados contraditórios". Sobrar um MiB
    no total declarado é inofensivo; faltar um é uma falha que não existe.
    """
    registro = tmp_path / "pulls.txt"
    ferramentas = _montar_maquina(tmp_path, nvidia_smi=None, pull_registrado=registro)
    # 4 GB + 1 byte: não cabe em 4096 MiB exatos.
    _criar_cartao(tmp_path / "drm", "card1", 4 * 1_073_741_824 + 1)

    resultado = _rodar_script(tmp_path, ferramentas, registro)

    assert resultado.returncode == 0, resultado.stderr
    assert "VRAM_TOTAL_MIB=4097" in resultado.stdout


def test_script_avisa_quando_nao_encontra_nenhuma_placa(tmp_path: Path) -> None:
    """Máquina sem GPU dedicada é um estado legítimo, mas precisa ser dito."""
    registro = tmp_path / "pulls.txt"
    ferramentas = _montar_maquina(tmp_path, nvidia_smi=None, pull_registrado=registro)

    resultado = _rodar_script(tmp_path, ferramentas, registro)

    assert resultado.returncode == 0, resultado.stderr
    assert "VRAM_TOTAL_MIB=" not in resultado.stdout
    assert "não encontrei a VRAM" in resultado.stderr
    assert "sem GPU dedicada" in resultado.stderr
    assert "OLLAMA_ALLOW_CPU=true" in resultado.stderr
    # E segue sem a linha do `export`, porque não há número para exportar.
    assert "export VRAM_TOTAL_MIB" not in resultado.stdout


def test_script_para_quando_a_maquina_tem_duas_placas_com_vram(tmp_path: Path) -> None:
    """Com duas placas o número é ambíguo, e adivinhar seria pior que parar.

    Uma VRAM errada aprova a checagem errada: o total declarado é o contra o que
    o `size_vram` do Ollama é comparado, e um total grande demais libera CPU sem
    ninguém perceber.
    """
    registro = tmp_path / "pulls.txt"
    ferramentas = _montar_maquina(tmp_path, nvidia_smi=None, pull_registrado=registro)
    _criar_cartao(tmp_path / "drm", "card0", 512 * 1_048_576)
    _criar_cartao(tmp_path / "drm", "card1", 8_573_157_376)

    resultado = _rodar_script(tmp_path, ferramentas, registro)

    assert resultado.returncode != 0
    assert "Mais de uma placa com VRAM" in resultado.stderr
    assert "card0" in resultado.stderr
    assert "card1" in resultado.stderr
    assert "VRAM_TOTAL_MIB=<total em MiB>" in resultado.stderr
    assert "VRAM_TOTAL_MIB=" not in resultado.stdout


def test_script_ignora_cartao_sem_vram_propria(tmp_path: Path) -> None:
    """GPU integrada costuma não ter o arquivo, e ela não pode ser contada."""
    registro = tmp_path / "pulls.txt"
    ferramentas = _montar_maquina(tmp_path, nvidia_smi=None, pull_registrado=registro)
    (tmp_path / "drm" / "card0").mkdir(parents=True)  # integrada: sem o arquivo
    _criar_cartao(tmp_path / "drm", "card1", 8_573_157_376)

    resultado = _rodar_script(tmp_path, ferramentas, registro)

    assert resultado.returncode == 0, resultado.stderr
    assert "VRAM_TOTAL_MIB=8176" in resultado.stdout


def test_script_falha_alto_quando_o_ollama_nao_responde(tmp_path: Path) -> None:
    """Sem Ollama no ar o script para e diz como subir, em vez de seguir calado."""
    registro = tmp_path / "pulls.txt"
    ferramentas = _montar_maquina(tmp_path, nvidia_smi="8176", pull_registrado=registro)

    resultado = _rodar_script(tmp_path, ferramentas, registro, {"CURL_FALHO": "1"})

    assert resultado.returncode != 0
    assert "FALHA" in resultado.stderr
    assert "OLLAMA_HOST=0.0.0.0:11434" in resultado.stderr
    assert "ADR-0002" in resultado.stderr
    assert not registro.exists()


def test_script_avisa_quando_a_placa_caiu_para_cpu(tmp_path: Path) -> None:
    """A coluna PROCESSOR é a autoridade, e CPU tem de aparecer dita."""
    registro = tmp_path / "pulls.txt"
    ferramentas = _montar_maquina(
        tmp_path, nvidia_smi="8176", pull_registrado=registro, processador="100% CPU"
    )

    resultado = _rodar_script(tmp_path, ferramentas, registro)

    assert resultado.returncode == 0, resultado.stderr
    assert "100% CPU" in resultado.stdout
    assert "coluna PROCESSOR mostra CPU" in resultado.stderr
    assert "plausível e errado ao mesmo tempo" in resultado.stderr


def test_script_avisa_quando_a_marcao_passa_da_integracao(tmp_path: Path) -> None:
    """`50% CPU/GPU` serve para atender e não serve para medir."""
    registro = tmp_path / "pulls.txt"
    ferramentas = _montar_maquina(
        tmp_path, nvidia_smi="8176", pull_registrado=registro, processador="50% CPU/GPU"
    )

    resultado = _rodar_script(tmp_path, ferramentas, registro)

    assert "50% CPU/GPU" in resultado.stdout
    assert "coluna PROCESSOR mostra CPU" in resultado.stderr


def test_script_imprime_a_linha_do_ollama_ps(tmp_path: Path) -> None:
    """O `ollama ps` é a evidência de onde o modelo está rodando."""
    registro = tmp_path / "pulls.txt"
    ferramentas = _montar_maquina(tmp_path, nvidia_smi="8176", pull_registrado=registro)

    resultado = _rodar_script(tmp_path, ferramentas, registro)

    assert resultado.returncode == 0, resultado.stderr
    assert "ollama ps:" in resultado.stdout
    assert "100% GPU" in resultado.stdout


def test_script_avisa_quando_nao_consegue_carregar_o_modelo(tmp_path: Path) -> None:
    """Ollama no ar, mas o modelo não carregou: o script avisa, e não confirma nada."""
    registro = tmp_path / "pulls.txt"
    ferramentas = _montar_maquina(tmp_path, nvidia_smi="8176", pull_registrado=registro)

    resultado = _rodar_script(tmp_path, ferramentas, registro, {"CURL_GERAR_FALHO": "1"})

    assert resultado.returncode == 0, resultado.stderr
    assert "não consegui carregar o modelo" in resultado.stderr
    assert "ollama run" in resultado.stderr
    assert "ollama ps:" not in resultado.stdout


def test_script_nao_baixa_de_novo_quando_o_modelo_ja_existe(tmp_path: Path) -> None:
    """O primeiro critério da #7: a segunda execução não baixa nada."""
    registro = tmp_path / "pulls.txt"
    ferramentas = _montar_maquina(tmp_path, nvidia_smi="8176", pull_registrado=registro)

    resultado = _rodar_script(tmp_path, ferramentas, registro)

    assert resultado.returncode == 0, resultado.stderr
    assert "já está no host" in resultado.stdout
    assert "Nada a baixar" in resultado.stdout
    # O `ollama` falso sai com erro no `pull`, então um pull indevido quebraria
    # o script — e o arquivo de registro diria o que aconteceu.
    assert not registro.exists()


def test_script_baixa_o_modelo_quando_a_tag_falta(tmp_path: Path) -> None:
    registro = tmp_path / "pulls.txt"
    ferramentas = _montar_maquina(
        tmp_path, nvidia_smi="8176", pull_registrado=registro, ollama=_OLLAMA_MODELO_AUSENTE
    )

    resultado = _rodar_script(tmp_path, ferramentas, registro)

    assert resultado.returncode == 0, resultado.stderr
    assert "Baixando" in resultado.stdout
    assert registro.read_text(encoding="utf-8").strip() == _MODELO


def test_script_rodar_duas_vezes_nao_muda_nada(tmp_path: Path) -> None:
    """Idempotência: o segundo passo é tão seguro quanto o primeiro."""
    registro = tmp_path / "pulls.txt"
    ferramentas = _montar_maquina(tmp_path, nvidia_smi="8176", pull_registrado=registro)

    primeiro = _rodar_script(tmp_path, ferramentas, registro)
    segundo = _rodar_script(tmp_path, ferramentas, registro)

    assert primeiro.returncode == 0, primeiro.stderr
    assert segundo.returncode == 0, segundo.stderr
    assert primeiro.stdout == segundo.stdout
    assert not registro.exists()


def test_script_aceita_outro_modelo(tmp_path: Path) -> None:
    """`MODELO=` troca o modelo, para quem estiver testando outro candidato."""
    registro = tmp_path / "pulls.txt"
    ferramentas = _montar_maquina(
        tmp_path,
        nvidia_smi="8176",
        pull_registrado=registro,
        ollama=_OLLAMA_MODELO_AUSENTE,
    )

    # A lista do falso tem `llama3.2:3b`, então pedir `llama3.1:8b` tem de
    # resultar em `ollama pull llama3.1:8b`.
    resultado = _rodar_script(
        tmp_path, ferramentas, registro, {"MODELO": "llama3.1:8b"}
    )

    assert resultado.returncode == 0, resultado.stderr
    assert "llama3.1:8b" in resultado.stdout
    assert registro.read_text(encoding="utf-8").strip() == "llama3.1:8b"
