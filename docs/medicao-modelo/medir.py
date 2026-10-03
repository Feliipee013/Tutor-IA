#!/usr/bin/env python3
"""Mede os candidatos a modelo do Ollama para o ADR-0003.

O script mede três coisas por candidato: o **tamanho** dos pesos, vindo do
`ollama list` (nunca de estimativa de memória), o **tempo** de resposta, e a
**resposta literal** à pergunta que não tem resposta no material. A última é a
evidência que sustenta a eliminação de um candidato por Alucinação, e por isso
é guardada character a character, sem resumo.

Duas decisões vêm do ADR-0002 e estão no código, não só no README:

- **Falha alta em CPU.** Um Ollama servindo em CPU devolve tempo médio plausível,
  e é por isso que a nota da issue #3 chama a medição de velocidade de "o
  critério mais fácil de cumprir errado". Se `ollama ps` mostrar CPU, o script
  aborta. Um aviso seria engolido, o número entraria errado e ninguém perceberia.
  O modo local em CPU existe para medir qualidade, que é medida válida em
  qualquer máquina — então ele é opt-in por `--permitir-cpu`, e o padrão exige
  GPU.
- **A mesma medição para os três candidatos.** Material, pergunta,
  `temperature`, `seed`, `num_predict` e `num_ctx` são idênticos. A comparação é
  sobre o modelo, não sobre a amostragem.

As perguntas, o material sintético e a instrução neutra não estão neste arquivo:
eles são lidos de `sondagem.md`, com as marcas `<!-- ... -->`. Um único lugar
para o texto que o modelo recebe é o que impede a sondagem e o script de
divergirem — e, se as marcas sumirem ou sobrar, a medição falha alto em vez de
rodar um conjunto incompleto.

Só stdlib, de propósito: o `pyproject.toml` e o toolchain (`pytest`, `ruff`,
`mypy`) são da issue #4, e um script de medição que precisa de instalação não é
executável na máquina de quem vai rodar a medição. Os tipos estão anotados para
quando o `mypy` existir.

Uso:

    python docs/medicao-modelo/medir.py
    python docs/medicao-modelo/medir.py --permitir-cpu
    python docs/medicao-modelo/medir.py --candidatos llama3.2:3b --saida-json bruto.json
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import platform
import re
import shutil
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final, NoReturn

RAIZ: Final = Path(__file__).resolve().parent
ARQUIVO_SONDAGEM: Final = RAIZ / "sondagem.md"

URL_PADRAO: Final = "http://localhost:11434"
TEMPO_LIMITE_SEGUNDOS: Final = 900

CANDIDATOS_PADRAO: Final[tuple[str, ...]] = ("qwen2.5:3b", "llama3.2:3b", "gemma2:2b")
PERGUNTAS_ESPERADAS: Final[tuple[str, ...]] = (
    "frequente",
    "atividade",
    "encaminhamento",
    "sem-resposta",
)

TEMPERATURA: Final = 0.0
SEED: Final = 20260926
NUM_PREDICT: Final = 256
NUM_CTX: Final = 2048
REPETICOES_PADRAO: Final = 3

# Primeiro critério da regra de decisão do ADR-0003: os pesos precisam caber nos
# 4 GB de VRAM da máquina do ADR-0002 e deixar espaço para o modelo de embedding
# que a 1.2 vai pedir ao mesmo Ollama (1.2-rag.md §13).
#
# A unidade é **GB decimal**, a mesma em que o `ollama list` imprime e em que o
# limite está escrito no plano da issue. Confundir com GiB aqui mudaria o teto
# em 7%: 2,2 GB decimal são 2,05 GiB, e o filtro mudaria de resultado.
TETO_PESOS_GB: Final = 2.2

# Segunda condição do mesmo filtro: a regra do ADR-0003 pede "≤ 2,2 GB **em
# Q4_K_M**", e as duas condições falham por motivos diferentes. Um peso alto se
# resolve com um modelo menor; uma quantização errada se resolve trocando a tag
# — o `gemma2:2b-instruct-q4_K_M` (1,7 GB) é exatamente esse caso, e o próprio ADR
# o registra como ponto aberto. Por isso o filtro é conferido inteiro, e não
# só o peso.
QUANTIZACAO_EXIGIDA: Final = "Q4_K_M"

# Divisores para reproduzir a formatação do `ollama list`, que é o que entra no
# ADR. O CLI imprime em unidade decimal com uma casa: 1.9299e9 vira "1.9 GB".
DIVISOR_POR_UNIDADE: Final[tuple[tuple[str, float], ...]] = (
    ("TB", 1e12),
    ("GB", 1e9),
    ("MB", 1e6),
    ("KB", 1e3),
)

RE_TAMANHO: Final = re.compile(r"^([\d.]+)\s*([KMGT]?i?B)$", re.IGNORECASE)
RE_CPU_NO_PROCESSADOR: Final = re.compile(r"(\d+(?:\.\d+)?)\s*%\s*CPU", re.IGNORECASE)
RE_ANSI: Final = re.compile(r"\x1b(?:\[[0-9;?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)|[@-Z\\-_])")
RE_BLOCO_SONDAGEM: Final = re.compile(
    r"<!--\s*(?P<marca>[a-z]+:[a-z0-9_-]+)\s*-->\s*```[a-z]*\n(?P<corpo>.*?)```",
    re.DOTALL,
)


# --------------------------------------------------------------------------- #
# Falha alta
# --------------------------------------------------------------------------- #


def falhar(mensagem: str) -> NoReturn:
    """Aborta a medição.

    Existe porque o ADR-0002 descreve um defeito que se esconde justamente no
    caminho da média: um Ollama em CPU responde, o número sai plausível e o
    erro vira indistinguível de um resultado. Aqui nada é "só um aviso".
    """
    print(f"\nFALHA: {mensagem}", file=sys.stderr)
    raise SystemExit(2)


# --------------------------------------------------------------------------- #
# Leitura da sondagem
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Sondagem:
    """O texto que sai da nossa parte para o modelo, e nada além disso."""

    instrucao: str
    material: str
    perguntas: dict[str, str]


def carregar_sondagem() -> Sondagem:
    if not ARQUIVO_SONDAGEM.is_file():
        falhar(f"a sondagem não está em {ARQUIVO_SONDAGEM}")

    texto = ARQUIVO_SONDAGEM.read_text(encoding="utf-8")
    blocos = {m.group("marca"): m.group("corpo").strip() for m in RE_BLOCO_SONDAGEM.finditer(texto)}

    if "material:dev" not in blocos:
        falhar("sondagem.md não tem o bloco `<!-- material:dev -->`")
    if "instrucao:comum" not in blocos:
        falhar("sondagem.md não tem o bloco `<!-- instrucao:comum -->`")

    perguntas = {chave.split(":", 1)[1]: corpo for chave, corpo in blocos.items() if chave.startswith("pergunta:")}
    faltando = [p for p in PERGUNTAS_ESPERADAS if p not in perguntas]
    sobrando = [p for p in perguntas if p not in PERGUNTAS_ESPERADAS]
    if faltando or sobrando:
        falhar(
            "as perguntas do arquivo não batem com as esperadas — "
            f"faltando {faltando}, sobrando {sobrando}, esperadas {list(PERGUNTAS_ESPERADAS)}"
        )

    return Sondagem(
        instrucao=blocos["instrucao:comum"],
        material=blocos["material:dev"],
        perguntas={p: perguntas[p] for p in PERGUNTAS_ESPERADAS},
    )


def montar_prompt(sondagem: Sondagem, pergunta: str) -> str:
    """O prompt é instrução + material + pergunta, nesta ordem, sempre.

    A persona do S.A.U. é a issue #10 e **não** entra aqui, de propósito: ela
    traz a regra de recusa, a regra de Encaminhamento e o "não sei". Aplicada
    aqui, ela daria aos três candidatos a mesma rede de proteção e a comparação
    deixaria de separar os modelos. O número medido aqui é um piso.
    """
    return f"{sondagem.instrucao}\n\n{sondagem.material}\n\n{pergunta}"


# --------------------------------------------------------------------------- #
# Ollama: binário, HTTP e as duas tabelas
# --------------------------------------------------------------------------- #


def binario_ollama() -> str:
    """Acha o executável, e falha alto se não achar.

    O instalador do Windows não põe o `ollama` no PATH do shell já aberto, então
    o caminho padrão é testado também.
    """
    no_path = shutil.which("ollama")
    if no_path:
        return no_path

    padroes = [
        Path.home() / "AppData" / "Local" / "Programs" / "Ollama" / "ollama.exe",
        Path("/usr/local/bin/ollama"),
        Path("/usr/bin/ollama"),
    ]
    for caminho in padroes:
        if caminho.is_file():
            return str(caminho)

    falhar("o executável do Ollama não está no PATH nem nos caminhos padrão — instale o Ollama")


def limpar_ansi(texto: str) -> str:
    """Tira as sequências de controle que o CLI do Ollama emite.

    O `ollama pull` desenha uma barra de progresso com códigos ANSI. Num erro,
    a mensagem real vem no fim de centenas de bytes de `\x1b[1G` e `\x1b[K`, e
    uma falha alta que imprime lixo não informa nada — foi exatamente o que
    aconteceu na primeira vez que o download de um candidato cahou por erro de
    rede.
    """
    return RE_ANSI.sub("", texto)


def ultima_linha_util(texto: str) -> str:
    """A última linha com conteúdo, que é onde o CLI deixa a mensagem de erro."""
    for linha in reversed(limpar_ansi(texto).splitlines()):
        if linha.strip():
            return linha.strip()
    return ""


def rodar_ollama(executavel: str, *argumentos: str) -> str:
    processo = subprocess.run(
        [executavel, *argumentos],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    saida = limpar_ansi(processo.stdout)
    if processo.returncode != 0:
        # O `ollama pull` reprinta o nome e a porcentagem a cada linha, então a
        # mensagem de erro é a última linha útil, não a saída inteira.
        detalhe = ultima_linha_util(processo.stderr) or ultima_linha_util(processo.stdout)
        falhar(f"`ollama {' '.join(argumentos)}` falhou (código {processo.returncode}): {detalhe}")
    return saida


def pedir_json(url: str, caminho: str, corpo: dict[str, Any] | None = None) -> Any:
    """Chama a API do Ollama com urllib. Sem requests, sem httpx."""
    url_completa = f"{url}{caminho}"
    dados: bytes | None = None
    cabecalhos = {"Accept": "application/json"}
    if corpo is not None:
        dados = json.dumps(corpo).encode("utf-8")
        cabecalhos["Content-Type"] = "application/json"

    requisicao = urllib.request.Request(url_completa, data=dados, headers=cabecalhos)
    try:
        with urllib.request.urlopen(requisicao, timeout=TEMPO_LIMITE_SEGUNDOS) as resposta:
            return json.loads(resposta.read().decode("utf-8"))
    except urllib.error.HTTPError as erro:
        falhar(f"{caminho} respondeu {erro.code}: {erro.read().decode('utf-8', 'replace')[:400]}")
    except urllib.error.URLError as erro:
        falhar(f"não consegui falar com o Ollama em {url_completa}: {erro.reason}")
    except json.JSONDecodeError as erro:
        falhar(f"{caminho} devolveu algo que não é JSON: {erro}")


def confirmar_ollama_no_ar(url: str) -> str:
    versao = pedir_json(url, "/api/version")
    if not isinstance(versao, dict) or "version" not in versao:
        falhar(f"/api/version devolveu uma forma inesperada: {versao!r}")
    return str(versao["version"])


def linha_da_tabela(saida: str, modelo: str) -> str:
    """Acha a linha de um modelo numa das tabelas do CLI.

    `ollama list` e `ollama ps` imprimem a mesma forma de tabela, e a coluna que
    interessa está na posição 2 (SIZE) ou 3 (PROCESSOR). Retorna a linha
    inteira, para a evidência colar na documentação sem reparse.
    """
    alvos = {modelo, f"{modelo}:latest"}
    for bruta in saida.splitlines():
        campos = re.split(r"\s{2,}", bruta.strip())
        if campos and campos[0] in alvos and len(campos) > 1:
            return re.sub(r"\s{2,}", "  ", bruta.strip())
    return ""


def tamanho_em_gb(texto: str) -> float | None:
    """Extrai o número de "1.9 GB". O CLI já imprime em decimal, então o número
    sai como está, sem conversão — converter reintroduziria a unidade errada."""
    achado = RE_TAMANHO.match(texto.strip())
    if achado is None:
        return None
    return float(achado.group(1))


def formatar_como_cli(exatos: int) -> str:
    """Reproduz a formatação do `ollama list` a partir dos bytes exatos.

    Serve para conferir o tamanho, e a conferência é por string e não por
    diferença numérica: o CLI arredonda para uma casa **antes** de qualquer
    conversão, então comparar "1.9 GB"convertido contra 1.9299e9 acusa uma
    diferença de 1,6% que é só o arredondamento. Reformatando os bytes exatos
    e comparando o texto, a conferência continua valendo e o teto de 2,2 GB é
    aplicado sobre o mesmo número que o ADR vai mostrar.
    """
    for unidade, divisor in DIVISOR_POR_UNIDADE:
        if exatos >= divisor:
            return f"{exatos / divisor:.1f} {unidade}"
    return f"{exatos} B"


def puxar_tamanho(executavel: str, url: str, modelo: str) -> dict[str, Any]:
    """O tamanho vem do `ollama list`, e não de memória nem de estimativa.

    `/api/tags` devolve o tamanho exato em bytes e entra como conferência: a
    formatação do CLI é re-derivada dos bytes e tem de dar exatamente a string
    que o CLI imprimiu. Discordar é sinal de que a tabela que entra no ADR é
    outra coisa que a gente pensa que é.
    """
    saida_list = rodar_ollama(executavel, "list")
    linha = linha_da_tabela(saida_list, modelo)
    if not linha:
        falhar(f"`ollama list` não mostrou {modelo} depois do pull")

    campos = re.split(r"\s{2,}", linha)
    if len(campos) < 3:
        falhar(f"a linha do `ollama list` para {modelo} tem forma inesperada: {linha!r}")
    tamanho_texto = campos[2]

    exato: int | None = None
    quantizacao = "desconhecida"
    parametros = "desconhecido"
    tags = pedir_json(url, "/api/tags")
    for modelo_local in tags.get("models", []):
        nome = modelo_local.get("model") or modelo_local.get("name")
        if nome in {modelo, f"{modelo}:latest"}:
            exato = modelo_local.get("size")
            detalhes = modelo_local.get("details") or {}
            quantizacao = str(detalhes.get("quantization_level", "desconhecida"))
            parametros = str(detalhes.get("parameter_size", "desconhecido"))
            break

    if exato is not None:
        esperado = formatar_como_cli(exato)
        if esperado != tamanho_texto.strip():
            falhar(
                f"o tamanho de {modelo} não bate entre `ollama list` "
                f"({tamanho_texto}) e /api/tags ({exatos} bytes, que o CLI "
                f"formataria como {esperado})"
            )

    return {
        "linha_list": linha,
        "tamanho_texto": tamanho_texto,
        "tamanho_gb": tamanho_em_gb(tamanho_texto),
        "bytes": exato,
        "quantizacao": quantizacao,
        "parametros": parametros,
    }


def percentual_de_cpu(processador: str) -> float | None:
    """Quanto de CPU a coluna PROCESSOR do `ollama ps` mostra, ou `None`.

    `None` é o que "100% GPU" quer dizer: a coluna não menciona CPU. A coluna
    PROCESSOR é a autoridade do ADR-0002, e esta função é o **único** lugar do
    script que a interpreta — as duas comportas, abortar e tarjar, leem por aqui
    de propósito, porque quando elas liam cada uma do seu jeito uma perguntava
    à máquina e a outra perguntava ao serviço, e as duas discordavam.
    """
    achado = RE_CPU_NO_PROCESSADOR.search(processador)
    if achado is None:
        return None
    return float(achado.group(1))


def processador_esta_na_gpu(processador: str) -> bool:
    """A velocidade de um candidato só vale se a coluna PROCESSOR não mostrar CPU.

    Isso vale por candidato, e não por máquina: quem prova a placa é a coluna
    PROCESSOR, e não a presença do `nvidia-smi` nem o resultado de uma medição
    anterior. Uma máquina sem `nvidia-smi` pode tarjar um modelo que esteja de
    fato na GPU, e um candidato que caia parcialmente para CPU é tarjado mesmo
    com `--permitir-cpu` — que é a regra que o `resultado-gpu.md` já escreve.
    """
    percentual = percentual_de_cpu(processador)
    return percentual is None or percentual <= 0


def conferir_processador(executavel: str, modelo: str, permitir_cpu: bool) -> tuple[str, str]:
    """A checagem do ADR-0002, e ela aborta. Devolve `(processador, linha_do_ps)`.

    `ollama ps` só lista o que está carregado, então esta função só é chamada
    depois que o modelo respondeu ao menos uma vez. A coluna PROCESSOR é a
    autoridade — `CUDA_VISIBLE_DEVICES` não é, porque variável mal formatada é
    ignorada em silêncio e o Ollama cai para CPU do mesmo jeito.
    """
    saida_ps = rodar_ollama(executavel, "ps")
    linha = linha_da_tabela(saida_ps, modelo)
    if not linha:
        falhar(f"`ollama ps` não mostrou {modelo}, então não dá para provar em que processador ele roda")

    campos = re.split(r"\s{2,}", linha)
    if len(campos) < 4:
        falhar(f"a linha do `ollama ps` para {modelo} tem forma inesperada: {linha!r}")
    processador = campos[3]

    percentual = percentual_de_cpu(processador)
    if percentual is None or percentual <= 0:
        return processador, linha

    if permitir_cpu:
        print(
            f"  ! ATENÇÃO: {modelo} está em {processador}. Medindo em CPU porque "
            "--permitir-cpu foi passado. Estes TEMPOS não descrevem a máquina do "
            "ADR-0002 e não podem entrar na coluna de velocidade do ADR.",
            file=sys.stderr,
        )
        return processador, linha

    falhar(
        f"{modelo} está sendo servido em {processador}, e a medição de velocidade "
        "exige a GPU do host (ADR-0002). Um tempo médio em CPU é plausível e "
        "errado ao mesmo tempo, que é a pior combinação. Rode em uma máquina com "
        "GPU, ou passe --permitir-cpu se o objetivo é só medir qualidade — e "
        "aí o número de velocidade é de outra máquina."
    )


def aquecer(url: str, modelo: str) -> None:
    """Carrega o modelo com uma geração mínima, para o `ollama ps` ter o que mostrar.

    A geração mínima vem antes da checagem de processador de propósito: é o
    modelo carregar que faz o `ollama ps` listar alguma coisa, e a checagem só
    é confiável depois disso. Não é uma repetição desperdiçada — as 12
    respostas da medição vêm todas depois deste ponto, com o modelo já quente,
    e por isso o tempo delas não carrega o custo de carregar o modelo.
    """
    pedir_json(
        url,
        "/api/generate",
        {
            "model": modelo,
            "prompt": "ok",
            "stream": False,
            "options": {"num_predict": 1, "num_ctx": NUM_CTX},
        },
    )


def descarregar(url: str, modelo: str) -> None:
    """Descarrega o modelo. `keep_alive: 0` manda o Ollama soltar na hora.

    Com 15,3 GiB de RAM e 1,8 GiB livres, manter os três candidatos carregados
    não cabe. Um por vez, descarregando entre eles, é o que faz a medição
    caber nesta máquina.
    """
    pedir_json(url, "/api/generate", {"model": modelo, "prompt": "", "keep_alive": 0})


# --------------------------------------------------------------------------- #
# A medição
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Resposta:
    pergunta: str
    repeticao: int
    texto: str
    segundos_totais: float
    segundos_da_geracao: float
    carga_segundos: float
    primeiro_token_segundos: float
    """`load_duration + prompt_eval_duration`, em segundos.

    A soma é uma escolha, e vale explicitar: o primeiro token existe para o
    Aluno quando o modelo **já está carregado** *e* o prompt **já foi lido**.
    São dois tempos encadeados, e o que o Aluno percebe é a soma deles, não
    qualquer um dos dois. `prompt_eval_duration` sozinho mediria só a leitura do
    prompt, que num modelo já carregado é a fração pequena; `load_duration`
    sozinho mediria só a carga, que num modelo já quente é zero.

    É a régua de troca do [ADR-0003](../../adr/0003-modelo-do-ollama.md) — o
    tempo de primeiro token perceptível, não o tok/s. Por isso o campo existe:
    uma régua que o instrumento não mede é uma régua de Alucinação.
    """
    tokens_por_segundo: float | None
    tokens_gerados: int | None
    concluida: bool


@dataclass(frozen=True)
class Candidato:
    nome: str
    linha_list: str
    linha_ps: str
    processador: str
    tamanho_texto: str
    tamanho_gb: float | None
    bytes: int | None
    quantizacao: str
    parametros: str
    respostas: tuple[Resposta, ...]


def medir_resposta(
    url: str,
    modelo: str,
    pergunta_id: str,
    prompt: str,
    repeticao: int,
) -> Resposta:
    corpo: dict[str, Any] = {
        "model": modelo,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": TEMPERATURA,
            "seed": SEED,
            "num_predict": NUM_PREDICT,
            "num_ctx": NUM_CTX,
        },
    }
    inicio = time.perf_counter()
    bruto = pedir_json(url, "/api/generate", corpo)
    segundos = time.perf_counter() - inicio

    carga = float(bruto.get("load_duration", 0)) / 1e9
    avaliacao_prompt = float(bruto.get("prompt_eval_duration", 0)) / 1e9
    duracao = float(bruto.get("eval_duration", 0)) / 1e9
    tokens = bruto.get("eval_count")
    tokens_por_segundo: float | None = None
    if isinstance(tokens, int) and duracao > 0:
        tokens_por_segundo = tokens / duracao

    return Resposta(
        pergunta=pergunta_id,
        repeticao=repeticao,
        texto=str(bruto.get("response", "")),
        segundos_totais=segundos,
        # A carga do modelo entra no tempo de ponta e vira ruído se for
        # misturada na geração. O `ollama ps` já provou que está na GPU, então
        # a leitura da velocidade usa só a geração.
        segundos_da_geracao=max(segundos - carga, 0.0),
        carga_segundos=carga,
        # Ver o docstring do campo: carga e leitura do prompt são encadeadas, e o
        # Aluno espera as duas.
        primeiro_token_segundos=carga + avaliacao_prompt,
        tokens_por_segundo=tokens_por_segundo,
        tokens_gerados=tokens if isinstance(tokens, int) else None,
        concluida=bool(bruto.get("done", False)),
    )


def medir_candidato(
    executavel: str,
    url: str,
    modelo: str,
    sondagem: Sondagem,
    repeticoes: int,
    permitir_cpu: bool,
) -> Candidato:
    print(f"\n{'=' * 78}\nCANDIDATO {modelo}\n{'=' * 78}")

    # O `ollama pull` é verboso e polui a evidência; o que importa é o `list`
    # depois, que é a fonte do tamanho.
    rodar_ollama(executavel, "pull", modelo)

    tamanho = puxar_tamanho(executavel, url, modelo)
    print(f"ollama list: {tamanho['linha_list']}")

    aquecer(url, modelo)
    processador, linha_ps = conferir_processador(executavel, modelo, permitir_cpu)
    print(f"ollama ps:   {linha_ps}")

    respostas: list[Resposta] = []
    for pergunta_id in PERGUNTAS_ESPERADAS:
        prompt = montar_prompt(sondagem, sondagem.perguntas[pergunta_id])
        print(f"\n--- {pergunta_id} ---")
        print(f"prompt enviado:\n{prompt}\n")
        for numero in range(1, repeticoes + 1):
            resposta = medir_resposta(url, modelo, pergunta_id, prompt, numero)
            respostas.append(resposta)
            print(f"[{numero}/{repeticoes}] {resposta.segundos_totais:.2f}s (geração {resposta.segundos_da_geracao:.2f}s)")
            print(resposta.texto)
            print()

    return Candidato(
        nome=modelo,
        linha_list=str(tamanho["linha_list"]),
        linha_ps=linha_ps,
        processador=processador,
        tamanho_texto=str(tamanho["tamanho_texto"]),
        tamanho_gb=tamanho["tamanho_gb"],
        bytes=tamanho["bytes"],
        quantizacao=str(tamanho["quantizacao"]),
        parametros=str(tamanho["parametros"]),
        respostas=tuple(respostas),
    )


# --------------------------------------------------------------------------- #
# Hardware da máquina
# --------------------------------------------------------------------------- #


def memoria() -> dict[str, float]:
    """RAM total e livre, em GiB, sem `psutil`."""
    try:
        if sys.platform == "win32":

            class StatusMemoria(ctypes.Structure):
                _fields_ = [
                    ("tamanho", ctypes.c_ulong),
                    ("carga", ctypes.c_ulong),
                    ("total_fisico", ctypes.c_ulonglong),
                    ("disponivel_fisico", ctypes.c_ulonglong),
                    ("total_pagefile", ctypes.c_ulonglong),
                    ("disponivel_pagefile", ctypes.c_ulonglong),
                    ("total_virtual", ctypes.c_ulonglong),
                    ("disponivel_virtual", ctypes.c_ulonglong),
                    ("disponivel_virtual_estendido", ctypes.c_ulonglong),
                ]

            status = StatusMemoria()
            status.tamanho = ctypes.sizeof(StatusMemoria)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))  # type: ignore[attr-defined]
            return {
                "total_gib": status.total_fisico / 2**30,
                "livre_gib": status.disponivel_fisico / 2**30,
            }

        pagina = os.sysconf("SC_PAGE_SIZE")
        paginas = os.sysconf("SC_PHYS_PAGES")
        total = pagina * paginas / 2**30
        disponivel = pagina * os.sysconf("SC_AVPHYS_PAGES") / 2**30
        return {"total_gib": total, "livre_gib": disponivel}
    except (AttributeError, OSError, ValueError):
        return {}


def hardware() -> dict[str, Any]:
    """GPU, VRAM e RAM da máquina em que a medição saiu.

    Vai junto de todo resultado porque é o que separa "este número mede a
    máquina do ADR-0002" de "este número mede o meu notebook". A medição de
    velocidade em CPU é válida como número de CPU e inválida como número de
    produção, e a diferença aparece aqui, não em quem vai colar o número.
    """
    info: dict[str, Any] = {
        "sistema": f"{platform.system()} {platform.release()}",
        "processador": platform.processor() or platform.machine(),
    }
    info.update(memoria())

    nvidia = shutil.which("nvidia-smi")
    if nvidia is None:
        info["gpu"] = "nenhuma GPU NVIDIA detectada: nvidia-smi ausente nesta máquina"
        info["vram_gib"] = None
    else:
        processo = subprocess.run(
            [nvidia, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if processo.returncode != 0 or not processo.stdout.strip():
            info["gpu"] = "nvidia-smi presente, mas não devolveu placa nenhuma"
            info["vram_gib"] = None
        else:
            linhas = [linha.strip() for linha in processo.stdout.strip().splitlines() if linha.strip()]
            info["gpu"] = linhas[0].split(",")[0].strip()
            try:
                info["vram_gib"] = float(linhas[0].split(",")[1].strip()) / 1024
                info["vram_total_placas"] = len(linhas)
            except (IndexError, ValueError):
                info["vram_gib"] = None
    return info


# --------------------------------------------------------------------------- #
# Saída
# --------------------------------------------------------------------------- #


def primeira_linha_significativa(texto: str) -> str:
    for linha in texto.splitlines():
        if linha.strip():
            return linha.strip()
    return ""


def estatisticas(candidato: Candidato) -> dict[str, float]:
    tempos = [r.segundos_da_geracao for r in candidato.respostas]
    return {
        "media": statistics.fmean(tempos),
        "mediana": statistics.median(tempos),
        "minimo": min(tempos),
        "maximo": max(tempos),
    }


def tempos_de_primeiro_token(candidato: Candidato) -> dict[str, float]:
    """Separa o tempo de primeiro token em cold start e em modelo quente.

    A mediana sai das repetições 2 e 3; a repetição 1 é linha separada, porque
    ela não é uma atípica e sim outra coisa: o script usa `keep_alive: 0` entre
    candidatos, então a primeira repetição de cada pergunta paga a carga do
    modelo e as outras duas não. Misturar as três só destruiria o número que a
    régua do ADR-0003 quer — o atendimento é com o modelo quente.

    A repetição 1 continua visível, com o seu `carga_segundos`, para o cold start
    não ser escondido: quem espera o primeiro Aluno de um plantão noturno paga a
    carga, e isso é fato, não ruído.
    """
    quentes = [r.primeiro_token_segundos for r in candidato.respostas if r.repeticao > 1]
    frias = [r.primeiro_token_segundos for r in candidato.respostas if r.repeticao == 1]

    if not quentes:
        raise ValueError(
            f"{candidato.nome}: nenhuma repetição quente (repetição > 1) para mediar o "
            "primeiro token; a régua do ADR-0003 é do modelo carregado"
        )
    if not frias:
        raise ValueError(f"{candidato.nome}: nenhuma repetição 1 para o cold start")

    return {
        "mediana": statistics.median(quentes),
        "minimo": min(quentes),
        "maximo": max(quentes),
        "cold_start": statistics.median(frias),
    }


def avaliar_filtro_duro(candidato: Candidato) -> tuple[str, str, str]:
    """Aplica o filtro inteiro do ADR-0003: peso **e** quantização.

    A regra declarada é "pesos ≤ 2,2 GB em Q4_K_M" — duas condições, e as duas
    são conferidas aqui. Antes desta correção o script só olhava o peso, e o
    `gemma2:2b` (Q4_0, 1,6 GB) passava numa coluna que o ADR marcava como
    reprovada: mesma coluna, duas perguntas, respostas opostas.

    As duas condições saem em colunas separadas porque falham por motivos
    diferentes, e uma delas se resolve trocando a tag em vez de trocando o
    modelo. Devolve as células de peso, quantização e veredito.
    """
    if candidato.tamanho_gb is None:
        return ("n/d", "n/d", "n/d")

    dentro_do_peso: bool = candidato.tamanho_gb <= TETO_PESOS_GB
    eh_quantizacao_exigida: bool = candidato.quantizacao == QUANTIZACAO_EXIGIDA

    celula_peso = "sim" if dentro_do_peso else f"**não** — pesou {candidato.tamanho_texto}"
    celula_quant = (
        "sim" if eh_quantizacao_exigida else f"**não** — é {candidato.quantizacao}"
    )

    if dentro_do_peso and eh_quantizacao_exigida:
        celula_filtro = "passa"
    elif not dentro_do_peso and not eh_quantizacao_exigida:
        celula_filtro = (
            f"**não** — pesou {candidato.tamanho_texto} e é {candidato.quantizacao}"
        )
    elif not eh_quantizacao_exigida:
        celula_filtro = (
            f"**não** — não é {QUANTIZACAO_EXIGIDA}; trocar a tag resolve"
        )
    else:
        celula_filtro = f"**não** — pesou {candidato.tamanho_texto}"

    return celula_peso, celula_quant, celula_filtro


def tabela_markdown(candidatos: list[Candidato]) -> str:
    """A tabela pronta para colar no ADR, com a velocidade como pendência.

    A velocidade não sai daqui para o candidato cuja coluna PROCESSOR mostra CPU:
    sairia preenchida com um número que parece comparável e não é, e foi
    exatamente esse o erro que a nota da issue #3 aponta como o mais fácil de
    cometer.

    A tarja é **por candidato**, lida da coluna PROCESSOR. Antes ela era uma
    única decisão para a tabela inteira, tirada da mensagem de hardware da
    máquina — que descreve a máquina, não o serviço — e por isso errava em dois
    sentidos: uma máquina sem `nvidia-smi` tarjava um modelo que estivesse de
    fato na GPU, e um modelo que tivesse caído só parcialmente para CPU saía com
    número. Quem prova a placa é a coluna PROCESSOR, então é ela que decide, e
    cada candidato decide por si.
    """
    # As três colunas do filtro têm o mesmo nome e a mesma ordem das colunas do
    # ADR-0003, para as duas tabelas serem comparáveis linha a linha. "Peso" e
    # "Q4_K_M" são colunas separadas de propósito: são condições diferentes, e
    # uma delas se resolve trocando a tag.
    cabecalho = (
        "| Candidato | Pesos (`ollama list`) | Quant. | Parâm. | Peso ≤ 2,2 GB "
        f"| É {QUANTIZACAO_EXIGIDA} | Filtro duro (peso e {QUANTIZACAO_EXIGIDA}) "
        "| Processador | Primeiro token mediana (s) | Primeiro token cold start (s) "
        "| Geração média (s) | Mediana (s) | tok/s (secundário) "
        "| 1ª linha da resposta à pergunta sem resposta |"
    )
    # A divisoria sai do proprio cabecalho, e nao de um numero escrito a mao: se
    # uma coluna nova entrar no cabecalho e o numero nao acompanhar-la, a tabela
    # quebra em silencio, que e o jeito mais caro de errar.
    divisoria = "| --- " * (cabecalho.count("|") - 1) + "|"

    linhas = [cabecalho, divisoria]
    for candidato in candidatos:
        numero = estatisticas(candidato)
        primeiro_token = tempos_de_primeiro_token(candidato)
        celula_peso, celula_quant, celula_filtro = avaliar_filtro_duro(candidato)
        if processador_esta_na_gpu(candidato.processador):
            celula_ttft = f"{primeiro_token['mediana']:.2f}"
            celula_cold = f"{primeiro_token['cold_start']:.2f}"
            celula_media = f"{numero['media']:.2f}"
            celula_mediana = f"{numero['mediana']:.2f}"
        else:
            celula_ttft = celula_cold = celula_media = celula_mediana = "pendente"
        tok_por_s = [
            r.tokens_por_segundo for r in candidato.respostas if r.tokens_por_segundo is not None
        ]
        celula_tok = f"{statistics.fmean(tok_por_s):.1f}" if tok_por_s else "n/d"

        sem_resposta = [r for r in candidato.respostas if r.pergunta == "sem-resposta"]
        primeira = primeira_linha_significativa(sem_resposta[0].texto) if sem_resposta else ""
        if len(primeira) > 120:
            primeira = primeira[:117] + "..."

        linhas.append(
            f"| `{candidato.nome}` | {candidato.tamanho_texto} | {candidato.quantizacao} "
            f"| {candidato.parametros} | {celula_peso} | {celula_quant} | {celula_filtro} "
            f"| {candidato.processador} | {celula_ttft} | {celula_cold} "
            f"| {celula_media} | {celula_mediana} | {celula_tok} | {primeira} |"
        )

    reprovados: list[str] = []
    for candidato in candidatos:
        motivo = avaliar_filtro_duro(candidato)[2]
        if motivo != "passa":
            reprovados.append(f"`{candidato.nome}` ({motivo.replace('**', '')})")

    if reprovados:
        linhas.append("")
        linhas.append(
            "> **Filtro duro tem duas condições.** A regra do ADR-0003 é \"pesos "
            f"≤ 2,2 GB em {QUANTIZACAO_EXIGIDA}\", e `Peso ≤ 2,2 GB` e "
            f"`É {QUANTIZACAO_EXIGIDA}` são as duas metades, separadas de propósito: "
            "um peso alto se resolve com um modelo menor, uma quantização errada se "
            "resolve **trocando a tag** — `gemma2:2b-instruct-q4_K_M` (1,7 GB) é "
            "esse caso, e o ADR-0003 o registra como ponto aberto. Reprovaram no "
            "filtro inteiro: "
            + ", ".join(reprovados)
            + "."
        )

    tarjados = [c.nome for c in candidatos if not processador_esta_na_gpu(c.processador)]
    if tarjados:
        linhas.append("")
        linhas.append(
            "> **Velocidade: pendente de propósito para "
            + ", ".join(f"`{nome}`" for nome in tarjados)
            + ".** A coluna PROCESSOR do `ollama ps` mostra CPU, e um tempo de "
            "modelo rodando em CPU descreve outra máquina, não a do ADR-0002. A "
            "tarja é por candidato, então um candidato na GPU sai com número "
            "mesmo com outro tarjado ao lado. Ver "
            "[`resultado-gpu.md`](../medicao-modelo/resultado-gpu.md)."
        )

    linhas.append("")
    linhas.append(
        "> **Régua de troca: primeiro token, não tok/s.** O ADR-0003 desempata pelo "
        "tempo de primeiro token perceptível, e `Primeiro token mediana` é a "
        "medição dessa régua: a mediana das repetições 2 e 3, com o modelo "
        "carregado. `Primeiro token cold start` é a repetição 1, à parte, porque "
        "o script usa `keep_alive: 0` entre candidatos e a primeira repetição paga "
        "a carga do modelo — ela não é uma atípica, é o cold start. O `tok/s` "
        "fica como secundário, como o ADR diz que ele é."
    )
    return "\n".join(linhas)


def imprimir_resumo(candidatos: list[Candidato], maquina: dict[str, Any]) -> None:
    print(f"\n{'=' * 78}\nHARDWARE DESTA MÁQUINA\n{'=' * 78}")
    print(f"sistema:      {maquina.get('sistema')}")
    print(f"processador:  {maquina.get('processador')}")
    print(f"GPU:          {maquina.get('gpu')}")
    if maquina.get("vram_gib") is not None:
        print(f"VRAM:         {maquina['vram_gib']:.2f} GiB")
    else:
        print("VRAM:         não determinada")
    if "total_gib" in maquina:
        print(f"RAM:          {maquina['total_gib']:.2f} GiB totais, {maquina.get('livre_gib', 0.0):.2f} GiB livres")
    else:
        print("RAM:          não determinada")

    print(f"\n{'=' * 78}\nTABELA PARA O ADR\n{'=' * 78}")
    print(tabela_markdown(candidatos))

    for candidato in candidatos:
        print(f"\n{'=' * 78}")
        print(f"RESPOSTA LITERAL À PERGUNTA SEM RESPOSTA — {candidato.nome}")
        print(f"{'=' * 78}")
        sem_resposta = [r for r in candidato.respostas if r.pergunta == "sem-resposta"]
        for resposta in sem_resposta:
            print(f"\n[repetição {resposta.repeticao}] {resposta.segundos_totais:.2f}s")
            print(resposta.texto)


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #


def montar_argumentos() -> argparse.Namespace:
    analisador = argparse.ArgumentParser(
        description="Mede os candidatos a modelo do Ollama para o ADR-0003.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    analisador.add_argument(
        "--candidatos",
        nargs="+",
        default=list(CANDIDATOS_PADRAO),
        help="modelos a medir, na ordem em que aparecem",
    )
    analisador.add_argument(
        "--repeticoes",
        type=int,
        default=REPETICOES_PADRAO,
        help="repetições por pergunta (padrão: 3)",
    )
    analisador.add_argument(
        "--permitir-cpu",
        action="store_true",
        help=(
            "mede mesmo com CPU. O padrão é exigir GPU e abortar, conforme o "
            "ADR-0002. Com esta flag os tempos medidos são de CPU e não podem "
            "entrar na coluna de velocidade do ADR."
        ),
    )
    analisador.add_argument(
        "--manter-vivo",
        action="store_true",
        help="não descarrega o modelo entre candidatos (pode não caber na RAM)",
    )
    analisador.add_argument(
        "--url",
        default=URL_PADRAO,
        help=f"endereço do Ollama (padrão: {URL_PADRAO})",
    )
    analisador.add_argument(
        "--saida-json",
        type=Path,
        default=None,
        help="arquivo para gravar o JSON bruto (padrão: só imprime na saída)",
    )
    return analisador.parse_args()


def configurar_saida() -> None:
    """Força UTF-8 na saída padrão.

    Resposta de modelo pode conter emoji, e o console padrão do Windows é
    cp1252. Na primeira medição o `gemma2:2b` respondeu com um emoji, o `print`
    derrubou com `UnicodeEncodeError` e a medição das 36 respostas foi embora
    junto com o JSON — um problema de console destruindo a evidência. O
    `errors="replace"` garante que nenhum caractere volte a derrubar a medição.
    """
    for fluxo in (sys.stdout, sys.stderr):
        reconfigurar = getattr(fluxo, "reconfigure", None)
        if reconfigurar is not None:
            reconfigurar(encoding="utf-8", errors="replace")


def main() -> int:
    configurar_saida()
    argumentos = montar_argumentos()
    if argumentos.repeticoes < 1:
        falhar("--repeticoes precisa ser pelo menos 1")

    executavel = binario_ollama()
    versao = confirmar_ollama_no_ar(argumentos.url)
    sondagem = carregar_sondagem()
    maquina = hardware()

    print(f"Ollama {versao} em {executavel}")
    print(f"sondagem:   {ARQUIVO_SONDAGEM}")
    print(f"candidatos: {', '.join(argumentos.candidatos)}")
    print(f"condições:  temperature={TEMPERATURA} seed={SEED} "
          f"num_predict={NUM_PREDICT} num_ctx={NUM_CTX} repeticoes={argumentos.repeticoes}")

    resultados: list[Candidato] = []
    for indice, modelo in enumerate(argumentos.candidatos, start=1):
        print(f"\n>>> [{indice}/{len(argumentos.candidatos)}] {modelo}")
        resultados.append(
            medir_candidato(
                executavel,
                argumentos.url,
                modelo,
                sondagem,
                argumentos.repeticoes,
                argumentos.permitir_cpu,
            )
        )
        if not argumentos.manter_vivo:
            descarregar(argumentos.url, modelo)
            print(f"\n{modelo} descarregado (keep_alive: 0)")

    imprimir_resumo(resultados, maquina)

    bruto = {
        "ollama": {"versao": versao, "executavel": executavel, "url": argumentos.url},
        "condicoes": {
            "temperature": TEMPERATURA,
            "seed": SEED,
            "num_predict": NUM_PREDICT,
            "num_ctx": NUM_CTX,
            "repeticoes": argumentos.repeticoes,
            "permitir_cpu": argumentos.permitir_cpu,
        },
        "maquina": maquina,
        "sondagem": {
            "arquivo": str(ARQUIVO_SONDAGEM),
            "instrucao": sondagem.instrucao,
            "material": sondagem.material,
            "perguntas": sondagem.perguntas,
        },
        "candidatos": [asdict(candidato) for candidato in resultados],
    }
    json_bruto = json.dumps(bruto, ensure_ascii=False, indent=2)
    if argumentos.saida_json is not None:
        argumentos.saida_json.write_text(json_bruto, encoding="utf-8")
        print(f"\nJSON bruto gravado em {argumentos.saida_json}")
    else:
        print("\n\nJSON BRUTO\n" + "=" * 78)
        print(json_bruto)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
