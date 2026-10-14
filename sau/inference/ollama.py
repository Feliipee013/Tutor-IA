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

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from sau.rag.embed import MODELO_EMBEDDING_PADRAO, ClienteEmbedding

logger = logging.getLogger("sau.inference.ollama")

NUM_CTX_PADRAO = 4096
"""Janela de contexto padrão: o dobro do que a medição do ADR-0003 usou.

2048 é o que a #3 usou, e o que cabe nas placas de 4 GB que a decisão do
ADR-0002 assume — justificativa que continua valendo e que nenhuma medição
derrubou. O que a medição do tempo de primeira resposta mostrou foi que esse
teto é curto demais para o prompt de um turno real: persona (870 tokens com a
cerca, 3.008 caracteres na mesma base de 3,46 do doc), a pergunta do Aluno no
teto do Telegram (4.096 caracteres, 1.138 tokens) e seis falas de histórico
(386 tokens) somam 2.394 tokens, e a 2048 o modelo leu **1.026** deles — menos
da metade, sem erro e com `done: true`. O que se perde é o fim do prompt, e o
fim é onde está a pergunta do Aluno. Um prompt de 3.031 tokens a 2048 lia 1.026
também; o mesmo, a 4096, lia os 3.031.

O que custa: **+72 MiB** de KV cache, de 72 para 144. A VRAM não aperta —
`ollama ps` marca 2,4 GB do modelo com janela de 8.192 numa placa de 4.096 MiB.
E a leitura do prompt **não piora** com a janela maior: mesmo prompt de 740
tokens, 3,778 s a 2048, 3,776 s a 4096, 3,693 s a 6144 e 3,694 s a 8192, porque
o KV cache é pré-alocado e a janela não é alocada na leitura.

O fato operacional é o que vale e é o que o teste sustenta: o prompt precisa
caber no `num_ctx`. Por que o corte a 2048 caiu sempre em 1.026 tokens, em três
casos independentes, não está explicado — e um número sem explicação não vira
regra.
"""

TIMEOUT_PADRAO = 60.0
"""Tempo de espera da geração quando ninguém informa outro, em segundos.

É o default do construtor, e não o número que roda em serviço: a fumaça e as
checagens passam `config.ollama_timeout` (30.0 por padrão), então geração e
checagem usam o mesmo relógio. Sessenta segundos aqui é a rede de segurança
para quem chama o cliente na mão.
"""

MOTIVO_NAO_INFORMADO = "(o Ollama não informou)"
"""O que se escreve quando a geração não diz por que parou.

O campo volta vazio em parte dos Responses do Ollama, e um campo vazio na linha
do log é um número sem nome. A frase é uma só porque a fumaça escreve a mesma
linha: duas frases para o mesmo vazio só faz a divergência aparecer quando
alguém compara os dois logs.
"""

MOTIVO_PARADA_NO_LIMITE = "length"
"""O `done_reason` que o Ollama dá quando a geração parou por falta de espaço.

O Ollama trata a parada como o fim bem-sucedido da geração: `done` é verdadeiro
e o motivo é este, o mesmo `done` de uma resposta que chegou ao fim do limite.
A geração não falhou — ela acabou, e o que ela deixou é texto pela metade.

Por isso o valor é uma constante aqui e não uma string espalhada pelo pacote: quem
lê o registro de um turno precisa comparar a parada contra um nome declarado, e
não lembrar de um literal. O nome `length` sozinho não diz nada disso — é
`length` de "tamanho", e quem não conhece o vocabulário do modelo lê um motivo
que parece o de qualquer outra parada.
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
class ChamadaDeFerramenta:
    """Uma ferramenta que o modelo decidiu chamar, com os argumentos que ele mandou.

    É o que o `/api/chat` devolve em `message.tool_calls`: o turno executa a
    ferramenta e devolve o resultado ao modelo, que decide continuar. O nome é
    o da ferramenta declarada (`buscar_no_manual`), e `argumentos` é o objeto
    já decodificado — o Ollama entrega um objeto, e não a string JSON que a
    API da OpenAI entrega por compatibilidade.
    """

    nome: str
    argumentos: dict[str, Any] = field(default_factory=dict)


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
    chamadas: tuple[ChamadaDeFerramenta, ...] = ()
    """As ferramentas que o modelo pediu para chamar, em ordem.

    Vazio na geração por `/api/generate`, que não tem tool calling, e na
    resposta final do turno. Preenchido só quando o modelo decide consultar o
    manual antes de responder; `texto` vem vazio junto, porque a resposta é a
    chamada.
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
        modelo_embedding: str = MODELO_EMBEDDING_PADRAO,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._url = f"{self._base_url}/api/generate"
        self._url_chat = f"{self._base_url}/api/chat"
        self._modelo = modelo
        self._timeout = timeout
        self._num_ctx = num_ctx
        self._client = client
        self._modelo_embedding = modelo_embedding

    @property
    def modelo_embedding(self) -> str:
        """O modelo que produz os vetores da recuperação, para a rodada declarar o que usou.

        É parâmetro com padrão — e não argumento obrigatório — pelo mesmo motivo
        que o `historico` do turno: quem chama sem ele continua funcionando com
        o modelo medido no ADR-0003 em vez de quebrando.
        """
        return self._modelo_embedding

    def embutir(self, textos: list[str]) -> list[list[float]]:
        """Embute a lista de textos no `/api/embed` e devolve um vetor por texto.

        É o que permite ao nó `ferramentas` embutir a consulta do modelo sem
        parâmetro novo no grafo: o cliente do turno carrega o embedding junto da
        geração, e a ferramenta `buscar_no_manual` o usa para consultar o índice
        do Manual. A conversa com o Ollama é a do `ClienteEmbedding`, com o mesmo
        transporte falso nos testes.
        """
        return ClienteEmbedding(
            self._base_url,
            self._modelo_embedding,
            timeout=self._timeout,
            client=self._client,
        ).embutir(textos)

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
        bruto = self._pedir(payload, url=self._url, chave="response")
        segundos_totais = time.perf_counter() - inicio

        return self._montar_resposta(
            bruto, texto=str(bruto.get("response", "")), segundos_totais=segundos_totais
        )

    def conversar(
        self,
        mensagens: list[dict[str, Any]],
        *,
        ferramentas: list[dict[str, Any]] | None = None,
        opcoes: dict[str, Any] | None = None,
    ) -> Resposta:
        """Conversa por `/api/chat`, com tool calling opcional.

        É o caminho do turno com ferramenta: o modelo pode responder direto
        (`texto`) ou pedir para chamar uma ferramenta (`chamadas`), e o turno
        executa e volta com o resultado no histórico de mensagens. `ferramentas`
        é o schema no formato `tools` do Ollama; sem ele, a conversa é uma
        geração comum por chat.
        """
        payload: dict[str, Any] = {
            "model": self._modelo,
            "messages": mensagens,
            "stream": False,
            "options": {"num_ctx": self._num_ctx, **(opcoes or {})},
        }
        if ferramentas is not None:
            payload["tools"] = ferramentas

        inicio = time.perf_counter()
        bruto = self._pedir(payload, url=self._url_chat, chave="message")
        segundos_totais = time.perf_counter() - inicio

        mensagem = bruto.get("message")
        # `_pedir` já garantiu que `message` é um objeto; o `isinstance` é só
        # para o mypy, que não segue a garantia de um campo verificado lá.
        if not isinstance(mensagem, dict):
            mensagem = {}
        return self._montar_resposta(
            bruto,
            texto=str(mensagem.get("content", "")),
            segundos_totais=segundos_totais,
            chamadas=_ler_chamadas(mensagem.get("tool_calls")),
        )

    def _montar_resposta(
        self,
        bruto: dict[str, Any],
        *,
        texto: str,
        segundos_totais: float,
        chamadas: tuple[ChamadaDeFerramenta, ...] = (),
    ) -> Resposta:
        """Monta a `Resposta` a partir do JSON do Ollama e a registra no log.

        Os tempos são os mesmos em `/api/generate` e `/api/chat`, e por isso a
        montagem é uma só: o que muda entre as duas rotas é de onde vem o texto
        (o `response` ou o `message.content`) e se há chamadas de ferramenta.
        """
        carga = float(bruto.get("load_duration", 0)) / NANOSEGUNDOS_POR_SEGUNDO
        avaliacao = float(bruto.get("prompt_eval_duration", 0)) / NANOSEGUNDOS_POR_SEGUNDO
        duracao = float(bruto.get("eval_duration", 0)) / NANOSEGUNDOS_POR_SEGUNDO

        tokens = bruto.get("eval_count")
        tokens_gerados = tokens if isinstance(tokens, int) else None
        tokens_por_segundo = (
            tokens_gerados / duracao if tokens_gerados is not None and duracao > 0 else None
        )

        resposta = Resposta(
            texto=texto,
            primeiro_token_segundos=carga + avaliacao,
            carga_segundos=carga,
            avaliacao_prompt_segundos=avaliacao,
            segundos_totais=segundos_totais,
            tokens_por_segundo=tokens_por_segundo,
            tokens_gerados=tokens_gerados,
            concluida=bool(bruto.get("done", False)),
            motivo_de_parada=str(bruto.get("done_reason", "")),
            chamadas=chamadas,
        )
        self._registrar(resposta)
        return resposta

    def _pedir(self, payload: dict[str, Any], *, url: str, chave: str) -> dict[str, Any]:
        """POST em `url` e devolve o JSON do Ollama.

        `chave` é o campo que a rota precisa devolver (`response` na geração,
        `message` no chat): sem ele, não há resposta para dar ao Aluno.
        """
        try:
            if self._client is not None:
                resp = self._client.post(url, json=payload, timeout=self._timeout)
            else:
                with httpx.Client() as c:
                    resp = c.post(url, json=payload, timeout=self._timeout)
        except httpx.TimeoutException as err:
            raise TempoEsgotadoError(
                f"FALHA CRÍTICA: o modelo '{self._modelo}' não respondeu em "
                f"{self._timeout:.0f}s. O Aluno teria ficado esperando esse tempo "
                "todo antes de qualquer erro, então a espera é o defeito e não a "
                "ausência de resposta."
            ) from err
        except httpx.HTTPError as err:
            raise ErroDeInferencia(
                f"FALHA CRÍTICA: não consegui falar com o Ollama em {url}: {err}. "
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

        # Sem o campo que a rota promete (`response` na geração, `message` no
        # chat), não há resposta para dar ao Aluno. Tratar isso como texto
        # vazio entregaria ao Aluno uma tela em branco sem nenhum sinal de que
        # algo deu errado.
        if chave not in dados:
            raise ErroDeInferencia(
                f"FALHA CRÍTICA: o Ollama não devolveu o campo '{chave}' na geração do "
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
        detalhe = resposta.texto
        if resposta.chamadas:
            # Uma resposta de ferramenta vem sem texto: o que o modelo "disse"
            # foi a chamada, e é ela que precisa ficar no log para o critério
            # de auditoria da #36 (consulta registrada) ser verdadeiro.
            detalhe = "[tool_calls] " + "; ".join(
                f"{chamada.nome}({json.dumps(chamada.argumentos, ensure_ascii=False)})"
                for chamada in resposta.chamadas
            )
        logger.info(
            "Resposta do modelo '%s' | primeiro token %.3fs (carga %.3fs + prompt %.3fs) "
            "| total %.3fs | %s tok/s | %s tokens | parada: %s\n%s",
            self._modelo,
            resposta.primeiro_token_segundos,
            resposta.carga_segundos,
            resposta.avaliacao_prompt_segundos,
            resposta.segundos_totais,
            formatar_numero(resposta.tokens_por_segundo),
            formatar_numero(resposta.tokens_gerados),
            resposta.motivo_de_parada or MOTIVO_NAO_INFORMADO,
            detalhe,
        )


def _ler_chamadas(bruto: Any) -> tuple[ChamadaDeFerramenta, ...]:
    """Lê o `message.tool_calls` do `/api/chat`, ignorando o que não serve.

    O Ollama entrega `arguments` como objeto, e a compatibilidade com a API da
    OpenAI aceita que venha como string JSON; as duas formas são aceitas. Uma
    chamada sem nome de função é descartada em vez de virar uma ferramenta
    fantasma: sem saber o que executar, não há o que executar.
    """
    if not isinstance(bruto, list):
        return ()

    chamadas: list[ChamadaDeFerramenta] = []
    for item in bruto:
        if not isinstance(item, dict):
            continue
        funcao = item.get("function")
        if not isinstance(funcao, dict):
            continue
        nome = funcao.get("name")
        if not isinstance(nome, str) or not nome:
            continue
        chamadas.append(
            ChamadaDeFerramenta(nome=nome, argumentos=_ler_argumentos(funcao.get("arguments")))
        )
    return tuple(chamadas)


def _ler_argumentos(bruto: Any) -> dict[str, Any]:
    """Os argumentos de uma chamada, objeto ou string JSON, sempre como dicionário."""
    if isinstance(bruto, dict):
        return bruto
    if isinstance(bruto, str):
        try:
            decodificado = json.loads(bruto)
        except ValueError:
            return {}
        if isinstance(decodificado, dict):
            return decodificado
    return {}


def formatar_numero(valor: float | int | None) -> str:
    """Formata um número que pode não existir, sem estourar o log.

    O `tok/s` é `None` quando a geração não reportou duração, e imprimir
    "None" no log é ruído que esconde o resto. O campo continua aparecendo
    como "n/d", que é a forma que o ADR-0003 já usa.

    É pública porque a fumaça escreve os mesmos campos na mesma régua do
    ADR-0003: quem formata é o mesmo, e um `_` importado de fora acopla o
    formato do log dos dois arquivos sem nenhum dos dois declarar isso.
    """
    if valor is None:
        return "n/d"
    if isinstance(valor, float):
        return f"{valor:.1f}"
    return str(valor)
