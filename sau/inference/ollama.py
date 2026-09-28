"""Cliente de inferência que fala com o Ollama do host.

O modelo roda fora do container, conforme o ADR-0002, e este cliente é o meio do
S.A.U. até ele. Ele faz uma coisa só: manda um prompt e devolve a resposta do
modelo junto com os tempos que a geração custou.

Três decisões estão no código e não só na conversa:

- **Nenhuma amostragem travada.** O ADR-0003 fixou `temperature 0` e uma `seed`
  porque aquilo era medição, e medir exige comparar. Em produção a
  temperatura é a do modelo e a seed é sorteada a cada chamada — travar a seed
  aqui daria a todo Aluno exatamente a mesma resposta, o que é o oposto de
  atender alguém. Quem mede passa as condições dele em `opcoes`.
- **`num_ctx` sempre vai.** É o tamanho da janela de contexto e é o que segura
  o consumo de memória da placa; o resto quem decide é quem chama.
- **O tempo de primeira resposta é a régua do ADR-0003**, e a régua tem um nome
  só. `primeiro_token_segundos` é `load_duration + prompt_eval_duration`, as
  mesmas duas medidas e a mesma soma de `docs/medicao-modelo/medir.py`. Número
  de duas réguas diferentes não se compara, mesmo quando as duas medições são
  do mesmo modelo.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger("sau.inference.ollama")

NUM_CTX_PADRAO = 2048
"""Janela de contexto padrão, o mesmo valor da medição do ADR-0003.

2048 é o que a #3 usou, e o que cabe nas placas de 4 GB que a decisão do
ADR-0002 assume. Uma janela maior cabe em placas maiores, mas muda o consumo de
memória: quem subir este valor precisa conferir a VRAM da máquina de novo.
"""

TIMEOUT_PADRAO = 60.0
"""Tempo de espera da geração, em segundos.

Maior que o timeout das checagens de pré-requisito porque aqui a resposta
inteira tem de caber no relógio, e não só a mão do servidor. A checagem pergunta
"você está aí?"; a geração pergunta "quanto tempo o Aluno espera?".
"""

NANOSEGUNDOS_POR_SEGUNDO = 1e9
"""O Ollama reporta durações em nanossegundos, e a pessoa que lê o log pensa em segundos."""


class ErroDeInferencia(RuntimeError):
    """Falha ao pedir uma resposta ao modelo."""


class TempoEsgotadoError(ErroDeInferencia):
    """O modelo não respondeu a tempo.

    Existe separada porque timeout é o defeito mais provável de um turno de
    conversa: a máquina carregada, o modelo sobrecarregado e o Aluno esperando.
    Tratar como erro genérico esconde o motivo que a pessoa precisa.
    """


@dataclass(frozen=True)
class Resposta:
    """A resposta do modelo e o que a geração custou.

    Os tempos vêm do próprio Ollama, não de relógio na parede: o que interessa
    é o tempo que o modelo gastou, e medir por fora inclui a fila e a rede, que
    são outras coisas. A exceção é `segundos_totais`, que é de ponta a ponta e
    existe para comparar com o que a pessoa sente.
    """

    texto: str
    primeiro_token_segundos: float
    """`load_duration + prompt_eval_duration`, em segundos.

    A régua de troca do ADR-0003, e a soma é uma escolha: o primeiro token
    existe para o Aluno quando o modelo **já está carregado** *e* o prompt
    **já foi lido**. São dois tempos em sequência, e o que o Aluno espera é a
    soma. `load_duration` sozinho é zero com o modelo quente, e
    `prompt_eval_duration` sozinho mede só a leitura do prompt.
    """
    carga_segundos: float
    """Quanto tempo o Ollama levou para carregar o modelo.

    O primeiro Aluno da madrugada paga isso. Os seguintes não.
    """
    avaliacao_prompt_segundos: float
    """Quanto tempo o modelo levou para ler o prompt."""
    segundos_totais: float
    """Da partida da requisição até a resposta inteira, medido no cliente."""
    tokens_por_segundo: float | None
    tokens_gerados: int | None
    concluida: bool
    motivo_de_parada: str
    """Por que o modelo parou, como o `stop` que o Ollama relata.

    Entrou no relatório porque `length` — parou por falta de espaço — é um
    defeito silencioso: a resposta sai cortada no meio de uma frase e parece
    uma resposta.
    """


class ClienteOllama:
    """Fala com o modelo no host e devolve a resposta com os tempos.

    `client` existe para os testes, que montam um `httpx.MockTransport` no
    mesmo formato de `tests/test_prereqs.py`. Sem ele, cada geração abre e fecha
    uma conexão; com a 1.2 e o semáforo na frente, quem quiser reaproveitar a
    conexão passa a instanciar com uma.
    """

    def __init__(
        self,
        base_url: str,
        modelo: str,
        timeout: float = TIMEOUT_PADRAO,
        num_ctx: int = NUM_CTX_PADRAO,
        client: httpx.Client | None = None,
    ) -> None:
        self._url = f"{base_url.rstrip('/')}/api/generate"
        self._modelo = modelo
        self._timeout = timeout
        self._num_ctx = num_ctx
        self._client = client

    def responder(self, prompt: str, *, opcoes: dict[str, Any] | None = None) -> Resposta:
        """Manda o prompt ao modelo e devolve a resposta com os tempos.

        `opcoes` vai direto para o campo `options` do Ollama e é o caminho de
        quem precisa de uma condição específica — a medição do ADR-0003, por
        exemplo, passa aqui a `temperature`, a `seed` e o `num_predict` que
        ela usa. O que vem em `opcoes` ganha do padrão; o que não vem fica no
        `num_ctx` do cliente.
        """
        payload: dict[str, Any] = {
            "model": self._modelo,
            "prompt": prompt,
            # `stream: false` é o que faz a resposta vir inteira, com os
            # tempos, em um JSON só. Com streaming, os tempos chegam em
            # pedaços e o primeiro token deixa de ser um número: vira o
            # instante do primeiro pedaço, medido pelo relógio do cliente.
            "stream": False,
            "options": {"num_ctx": self._num_ctx, **(opcoes or {})},
        }

        inicio = time.perf_counter()
        bruto = self._pedir(payload)
        segundos_totais = time.perf_counter() - inicio

        carga = float(bruto.get("load_duration", 0)) / NANOSEGUNDOS_POR_SEGUNDO
        avaliacao = float(bruto.get("prompt_eval_duration", 0)) / NANOSEGUNDOS_POR_SEGUNDO
        duracao = float(bruto.get("eval_duration", 0)) / NANOSEGUNDOS_POR_SEGUNDO

        tokens = bruto.get("eval_count")
        tokens_gerados = tokens if isinstance(tokens, int) else None
        tokens_por_segundo = (
            tokens_gerados / duracao if tokens_gerados is not None and duracao > 0 else None
        )

        resposta = Resposta(
            texto=str(bruto.get("response", "")),
            primeiro_token_segundos=carga + avaliacao,
            carga_segundos=carga,
            avaliacao_prompt_segundos=avaliacao,
            segundos_totais=segundos_totais,
            tokens_por_segundo=tokens_por_segundo,
            tokens_gerados=tokens_gerados,
            concluida=bool(bruto.get("done", False)),
            motivo_de_parada=str(bruto.get("done_reason", "")),
        )
        self._registrar(resposta)
        return resposta

    def _pedir(self, payload: dict[str, Any]) -> dict[str, Any]:
        """POST em `/api/generate` e devolve o JSON do Ollama."""
        try:
            if self._client is not None:
                resp = self._client.post(self._url, json=payload, timeout=self._timeout)
            else:
                with httpx.Client() as c:
                    resp = c.post(self._url, json=payload, timeout=self._timeout)
        except httpx.TimeoutException as err:
            raise TempoEsgotadoError(
                f"FALHA CRÍTICA: o modelo '{self._modelo}' não respondeu em "
                f"{self._timeout:.0f}s. O Aluno teria ficado esperando esse tempo "
                "todo antes de qualquer erro, então a espera é o defeito e não a "
                "ausência de resposta."
            ) from err
        except httpx.HTTPError as err:
            raise ErroDeInferencia(
                f"FALHA CRÍTICA: não consegui falar com o Ollama em {self._url}: {err}. "
                "Confira se o serviço está rodando no host e se o container alcança "
                "a porta 11434 (ver ADR-0002)."
            ) from err

        if resp.status_code != 200:
            raise ErroDeInferencia(
                f"FALHA CRÍTICA: o Ollama respondeu {resp.status_code} ao pedir uma "
                f"geração do modelo '{self._modelo}': {resp.text}"
            )

        try:
            dados = resp.json()
        except ValueError as err:
            raise ErroDeInferencia(
                f"FALHA CRÍTICA: o Ollama devolveu algo que não é JSON ao pedir uma "
                f"geração do modelo '{self._modelo}'."
            ) from err

        if not isinstance(dados, dict):
            raise ErroDeInferencia(
                f"FALHA CRÍTICA: o Ollama devolveu {type(dados).__name__} no lugar de um "
                f"objeto JSON ao pedir uma geração do modelo '{self._modelo}'."
            )

        # Sem o campo `response`, não há resposta para dar ao Aluno. Tratar
        # isso como texto vazio entregaria um Aluno uma tela em branco sem
        # nenhum sinal de que algo deu errado.
        if "response" not in dados:
            raise ErroDeInferencia(
                f"FALHA CRÍTICA: o Ollama não devolveu o campo 'response' na geração do "
                f"modelo '{self._modelo}'. O que veio: {sorted(dados)}."
            )

        return dados

    def _registrar(self, resposta: Resposta) -> None:
        """Escreve a resposta do modelo no log, sem mexer nela.

        A saída vai inteira, como o modelo escreveu. A #7 pede que a resposta do
        modelo esteja em log para as Perguntas-teste poderem ser lidas, e um
        resumo, uma aspas ou uma truncagem no meio da frase não serve para
        isso. Os tempos vão no mesmo registro para que o número e a resposta
        fiquem juntos: um tempo sem a resposta que ele mediu é um tempo de
        ninguém.
        """
        logger.info(
            "Resposta do modelo '%s' | primeiro token %.3fs (carga %.3fs + prompt %.3fs) "
            "| total %.3fs | %s tok/s | %s tokens | parada: %s\n%s",
            self._modelo,
            resposta.primeiro_token_segundos,
            resposta.carga_segundos,
            resposta.avaliacao_prompt_segundos,
            resposta.segundos_totais,
            _numero(resposta.tokens_por_segundo),
            _numero(resposta.tokens_gerados),
            resposta.motivo_de_parada or "(o Ollama não informou)",
            resposta.texto,
        )


def _numero(valor: float | int | None) -> str:
    """Formata um número que pode não existir, sem estourar o log.

    O `tok/s` é `None` quando a geração não reportou duração, e imprimir
    "None" no log é ruído que esconde o resto. O campo continua aparecendo
    como "n/d", que é a forma que o ADR-0003 já usa.
    """
    if valor is None:
        return "n/d"
    if isinstance(valor, float):
        return f"{valor:.1f}"
    return str(valor)
