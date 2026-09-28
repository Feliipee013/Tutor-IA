#!/usr/bin/env bash
# Prepara o host para o S.A.U.: VRAM, Ollama no ar e modelo baixado.
#
# É o passo que o `docker compose up` não dá conta de fazer, e a dívida que o
# ADR-0002 reconhece: o Ollama é um serviço da máquina, não do compose. O script
# existe para que esse passo seja um comando e não um ritual, e para que ele
# possa ser repetido sem medo.
#
# O script é idempotente: rodar duas vezes não muda nada, e a segunda não baixa
# modelo nenhum. Ele também nunca segue em silêncio quando algo dá errado — para
# e diz o motivo. A máquina sem GPU é um estado legítimo, mas precisa ser pedido
# por quem está olhando.
#
# Uso:
#   scripts/preparar-host.sh
#   MODELO=llama3.2:3b scripts/preparar-host.sh
#
# Ao final, ele imprime a linha do VRAM_TOTAL_MIB para exportar antes de
# `docker compose up`.

set -euo pipefail

MODELO="${MODELO:-qwen2.5:3b}"
OLLAMA_URL="${OLLAMA_URL:-http://localhost:11434}"
DRM_DIR="${DRM_DIR:-/sys/class/drm}"
MIB_EM_BYTES=1048576

# `DRM_DIR` é o caminho onde o kernel publica as placas. Está em variável só
# para o teste apontar para um diretório falso: o caminho de verdade não muda e
# ninguém precisa mexer nisso para rodar o script.

falhar() {
  echo "" >&2
  echo "FALHA: $1" >&2
  echo "" >&2
  exit 1
}

aviso() {
  echo "ATENÇÃO: $1" >&2
}

# --- VRAM ------------------------------------------------------------------
#
# A VRAM total da máquina não sai de nenhum endpoint do Ollama, então ela vem
# do sistema. Duas fontes, nesta ordem: o `nvidia-smi` quando existe, e o
# `/sys/class/drm`, que é onde o kernel publica a mesma informação para placas
# que não são NVIDIA (AMD, Intel). O `nvidia-smi` sozinho seria um erro
# silencioso numa máquina AMD: o script acharia que não há placa, e a pessoa
# acabaria sem o VRAM_TOTAL_MIB sem saber por quê.

vram_por_nvidia_smi() {
  local total
  # O `head -1` não é decoração: o nvidia-smi imprime UMA LINHA POR GPU, e sem
  # o filtro uma máquina com duas placas entrega "4096\n4096", que não é um
  # número.
  total="$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -1 | tr -d '[:space:]')"
  [[ -n "$total" ]] || return 1
  [[ "$total" =~ ^[0-9]+$ ]] || return 1
  echo "$total"
}

vram_por_sysfs() {
  # Cada placa que responde tem o seu arquivo. O kernel não escreve esse
  # arquivo para uma GPU integrada sem memória própria, então os que existem
  # são as placas com VRAM de verdade.
  local arquivos=("$DRM_DIR"/card*/device/mem_info_vram_total)
  local existentes=()
  local arquivo bytes

  for arquivo in "${arquivos[@]}"; do
    [[ -r "$arquivo" ]] && existentes+=("$arquivo")
  done

  case "${#existentes[@]}" in
    0)
      return 1
      ;;
    1)
      ;;
    *)
      # Mais de uma placa com VRAM, e a máquina não diz qual delas o Ollama
      # está usando. Escolher a maior, ou a primeira da lista, é adivinhar, e
      # uma VRAM errada aprova a checagem errada: o número errado aqui vira
      # CPU Authorized indevidamente. Melhor parar e pedir a escolha.
      echo "Mais de uma placa com VRAM nesta máquina:" >&2
      for arquivo in "${existentes[@]}"; do
        echo "  ${arquivo}: $(cat "$arquivo") bytes" >&2
      done
      falhar "não dá para saber qual placa roda o Ollama. Exporte na mão a VRAM da
  placa que ele usa e rode de novo:
    VRAM_TOTAL_MIB=<total em MiB> scripts/preparar-host.sh"
      ;;
  esac

  arquivo="${existentes[0]}"
  bytes="$(cat "$arquivo")"
  [[ "$bytes" =~ ^[0-9]+$ ]] || falhar "'${arquivo}' não tem um número: '${bytes}'"

  # Divisão arredondada para CIMA, e não truncada. A VRAM declarada é confrontada
  # com o `size_vram` que o Ollama relata, e o erro do arredondamento para baixo
  # faria a placa parecer MENOR do que é — o que reprovaria uma alocação que cabe,
  # com a mensagem de "dados contraditórios". Sobrar um MiB no total declarado é
  # inofensivo; faltar um é uma falha que não existe.
  echo $(( (bytes + MIB_EM_BYTES - 1) / MIB_EM_BYTES ))
}

descobrir_vram() {
  # A VRAM é declarada por máquina (ADR-0004): quem já informou o valor na mão
  # não precisa que o script descubra nada — e as mensagens de duas placas e de
  # máquina sem placa mandam justamente informar. Sem esta guarda, seguir a
  # instrução não adiantava: o valor era sobrescrito adiante.
  if [[ -n "${VRAM_TOTAL_MIB:-}" ]]; then
    export VRAM_TOTAL_MIB
    echo "  VRAM_TOTAL_MIB=$VRAM_TOTAL_MIB (informada à mão)"
    return 0
  fi

  local valor=""
  # `nvidia-smi` presente e ilegível não é "máquina sem placa": é wrapper ou
  # driver em estado ruim, e a mensagem de baixo mandaria a pessoa para a
  # hipótese errada. É um caso só, com aviso próprio.
  local nvidia_ilegivel=0
  if command -v nvidia-smi >/dev/null 2>&1; then
    valor="$(vram_por_nvidia_smi || true)"
    if [[ -z "$valor" ]]; then
      nvidia_ilegivel=1
    fi
  fi
  if [[ -z "$valor" ]]; then
    valor="$(vram_por_sysfs || true)"
  fi

  if [[ -z "$valor" ]]; then
    if (( nvidia_ilegivel )); then
      aviso "o nvidia-smi existe, mas não devolveu um número — wrapper? driver em estado ruim?"
      aviso "Confira na mão: nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits"
      aviso "Se a placa estiver visível por outro caminho, informe à mão:"
      aviso "  VRAM_TOTAL_MIB=<total em MiB> scripts/preparar-host.sh"
      return 0
    fi
    aviso "não encontrei a VRAM desta máquina (nem nvidia-smi, nem /sys/class/drm)."
    aviso "Isso é o estado esperado de uma máquina sem GPU dedicada: o Ollama roda"
    aviso "em CPU, e aí quem mede tempo precisa de OLLAMA_ALLOW_CPU=true."
    aviso "Se a sua máquina TEM GPU, o VRAM_TOTAL_MIB tem que ser informado à mão:"
    aviso "  VRAM_TOTAL_MIB=<total em MiB> scripts/preparar-host.sh"
    return 0
  fi

  VRAM_TOTAL_MIB="$valor"
  export VRAM_TOTAL_MIB
  echo "  VRAM_TOTAL_MIB=$VRAM_TOTAL_MIB"
}

# --- Modelo ----------------------------------------------------------------

modelo_ja_existe() {
  # `ollama list` imprime a tag na primeira coluna e o digest em coluna
  # separada, então `$1` já é a tag exata. O casamento é por igualdade:
  # `qwen2.5:3b-instruct` no host não é `qwen2.5:3b`, e um prefixo diria que
  # é — a mesma regra de `prereqs.py`, que compara por igualdade.
  ollama list 2>/dev/null | awk -v alvo="$MODELO" '$1 == alvo { achou = 1 } END { exit !achou }'
}

baixar_modelo() {
  if modelo_ja_existe; then
    echo "  ${MODELO} já está no host. Nada a baixar."
    return 0
  fi

  echo "  ${MODELO} não está no host. Baixando (isto leva alguns minutos na primeira vez)..."
  # A barra de progresso do `ollama pull` escreve caracteres de controle que
  # embaralham o terminal quando a saída não é um terminal de verdade. Deixar o
  # `ollama` escrever direto no terminal da pessoa evita isso, e o script não
  # precisa da barra: o que importa é o `ollama list` do fim.
  ollama pull "$MODELO" || falhar "\`ollama pull ${MODELO}\` falhou. Rode na mão para ver a mensagem do Ollama."
}

# --- Ollama ----------------------------------------------------------------

conferir_ollama() {
  if ! curl -sS --max-time 5 "${OLLAMA_URL}/api/version" >/dev/null 2>&1; then
    falhar "não consegui falar com o Ollama em ${OLLAMA_URL}.
Se o serviço não está rodando, suba com o bind que o container alcança:
  OLLAMA_HOST=0.0.0.0:11434 ollama serve
O bind padrão (127.0.0.1) não funciona: o container chega no IP da bridge do
Docker, não no loopback. Ver o ADR-0002."
  fi
}

# --- Linha do ollama ps ----------------------------------------------------
#
# O `ollama ps` só lista o que está CARREGADO, então logo depois do pull ele
# está vazio. Carregar o modelo com uma geração mínima é o que dá linha à
# tabela, e é essa linha que diz em que processador o modelo está — a única
# prova que vale, porque tanto o `nvidia-smi` responder quanto a porta 11434
# devolver JSON acontecem também com o Ollama em CPU.

mostrar_ps() {
  if ! command -v curl >/dev/null 2>&1; then
    aviso "curl não está instalado, então não consegui carregar o modelo para ver a"
    aviso "linha do \`ollama ps\`. Confira na mão:"
    aviso "  ollama run ${MODELO}   e depois Ctrl+C"
    aviso "  ollama ps"
    return 0
  fi

  curl -sS --max-time 120 "${OLLAMA_URL}/api/generate" \
    -H 'Content-Type: application/json' \
    -d "{\"model\":\"${MODELO}\",\"prompt\":\"\",\"stream\":false,\"options\":{\"num_predict\":1}}" \
    >/dev/null 2>&1 || {
      aviso "não consegui carregar o modelo para ver a linha do \`ollama ps\`."
      aviso "Confira na mão se ele roda na GPU: \`ollama run ${MODELO}\` e depois Ctrl+C."
      return 0
    }

  local linha
  linha="$(ollama ps 2>/dev/null | awk -v alvo="$MODELO" '$1 == alvo' | head -1)"
  if [[ -z "$linha" ]]; then
    aviso "\`ollama ps\` não mostrou ${MODELO} depois de carregar. Confira na mão."
    return 0
  fi

  # A coluna PROCESSOR é a autoridade. Ela precisa ser dita em voz alta porque
  # "100% GPU" e "50% GPU / 50% CPU" passam pelo mesmo caminho, e só uma delas
  # serve para medir tempo.
  echo "  ollama ps:   $linha"
  local processador
  processador="$(echo "$linha" | awk '{ for (i = 1; i <= NF; i++) if ($i ~ /CPU|GPU/) { printf "%s ", $i } }')"
  case "$processador" in
    *CPU*)
      aviso "a coluna PROCESSOR mostra CPU: '${processador}'."
      aviso "Medir tempo assim dá um número plausível e errado ao mesmo tempo."
      aviso "Se a sua máquina tem GPU, descubra por que o Ollama não a está usando."
      ;;
    *)
      ;;
  esac
}

# --- Main ------------------------------------------------------------------

echo "Preparando o host do S.A.U. (modelo: ${MODELO})"
echo ""
echo "1. VRAM da máquina"
descobrir_vram

echo ""
echo "2. Ollama no host"
conferir_ollama
echo "  ollama responde em ${OLLAMA_URL}"

echo ""
echo "3. Modelo"
baixar_modelo

echo ""
echo "4. Onde o modelo está rodando"
mostrar_ps

echo ""
echo "Pronto. Agora suba o bot:"
if [[ -n "${VRAM_TOTAL_MIB:-}" ]]; then
  echo "  export VRAM_TOTAL_MIB=${VRAM_TOTAL_MIB}"
fi
echo "  docker compose up -d --build"
