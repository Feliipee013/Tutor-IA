"""Testes do harness das Perguntas-teste, harness/run.py.

O que se prova aqui é o instrumento da #12: o parser lê as 10
Perguntas-teste com o comportamento esperado junto, a bateria roda 3
repetições por pergunta e grava output bruto com o motivo de parada, a
condição da rodada vai no JSON, a falha de um turno não aborta a bateria, e
a checagem de pré-requisito falha antes de gravar qualquer coisa.

O turno real (`executar_turno` contra o Ollama do host) não roda aqui: o
`turno` é uma função injetada, e a bateria prova o isolamento contra ela.
Nenhum teste deste arquivo fala com o Ollama de verdade — o `ClienteMedido`
é testado contra um `httpx.MockTransport`, como `tests/test_prereqs.py`.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from harness.run import (
    IDS_DA_CADEIA,
    IDS_ESPERADOS,
    ORDEM_DA_BATERIA,
    ORDEM_DA_CADEIA,
    SEED_PADRAO,
    TEMPERATURA_PADRAO,
    AlocacaoDoModelo,
    ClienteMedido,
    CondicoesDaRodada,
    PerguntaTeste,
    RegistroDoPassoDaCadeia,
    carregar_cadeia,
    carregar_perguntas_teste,
    descrever_alocacao,
    executar_bateria,
    executar_cadeia,
    gravar_rodada,
    main,
    montar_argumentos,
    sha256_do_prompt,
)
from sau.graph.state import Mensagem
from sau.inference.ollama import ClienteOllama, ErroDeInferencia, Resposta
from sau.prereqs import CpuNaoAutorizadaError, OllamaIndisponivelError

RAIZ = Path(__file__).resolve().parent.parent
ARQUIVO_PERGUNTAS = RAIZ / "perguntas-teste" / "perguntas-teste.md"


def _pergunta_falsa(id_pergunta: str = "a1") -> PerguntaTeste:
    return PerguntaTeste(
        id=id_pergunta,
        texto=f"texto da Pergunta-teste {id_pergunta}",
        conforme_quando=f"conforme quando {id_pergunta}",
        nao_conforme_quando=f"não conforme quando {id_pergunta}",
    )


def _resposta_falsa(texto: str, *, motivo_de_parada: str = "stop") -> Resposta:
    """A `Resposta` que o Ollama devolveria, com os tempos preenchidos."""
    return Resposta(
        texto=texto,
        primeiro_token_segundos=0.4,
        carga_segundos=0.2,
        avaliacao_prompt_segundos=0.2,
        segundos_totais=1.5,
        tokens_por_segundo=18.0,
        tokens_gerados=27,
        concluida=True,
        motivo_de_parada=motivo_de_parada,
    )


def _condicoes_falsas(**mudancas: Any) -> CondicoesDaRodada:
    base: dict[str, Any] = {
        "modelo": "qwen2.5:3b",
        "url": "http://localhost:11434",
        "repeticoes": 3,
        "temperatura": TEMPERATURA_PADRAO,
        "seed": SEED_PADRAO,
        "num_predict": 256,
        "num_ctx": 4096,
        "sha256_do_prompt": "abc123",
        "alocacao": AlocacaoDoModelo(size=1_900_000_000, size_vram=1_900_000_000, em_cpu=False),
        "inicio": "2026-09-30T12:00:00+00:00",
        "fim": "2026-09-30T12:05:00+00:00",
    }
    return CondicoesDaRodada(**{**base, **mudancas})


# --- Parser: as 10 Perguntas-teste com o esperado junto ---


def test_parser_le_as_10_perguntas_teste_em_ordem() -> None:
    perguntas = carregar_perguntas_teste(ARQUIVO_PERGUNTAS)

    assert [p.id for p in perguntas] == list(ORDEM_DA_BATERIA)
    assert set(IDS_ESPERADOS) == {f"a{i}" for i in (1, 2, 3)} | {f"f{i}" for i in (1, 2, 3)} | {
        f"p{i}" for i in (1, 2, 3, 4)
    }
    assert len(perguntas) == 10


def test_parser_traz_texto_e_comportamento_esperado_de_cada_caso() -> None:
    perguntas = carregar_perguntas_teste(ARQUIVO_PERGUNTAS)

    for pergunta in perguntas:
        assert pergunta.texto, f"a Pergunta-teste {pergunta.id} veio sem texto"
        assert "```" not in pergunta.texto
        assert pergunta.conforme_quando, f"{pergunta.id} sem o conforme quando"
        assert pergunta.nao_conforme_quando, f"{pergunta.id} sem o não conforme quando"


def test_parser_falha_alto_se_um_id_faltar(tmp_path: Path) -> None:
    arquivo = tmp_path / "perguntas-teste.md"
    arquivo.write_text(
        "<!-- pergunta:a1 -->\n```text\nOi\n```\n"
        "| Campo | Valor |\n"
        "| conforme quando | algo |\n"
        "| não conforme quando | outra |\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="faltando"):
        carregar_perguntas_teste(arquivo)


def test_parser_falha_alto_se_faltar_o_conforme(tmp_path: Path) -> None:
    blocos: list[str] = []
    for id_pergunta in ORDEM_DA_BATERIA:
        bloco = f"<!-- pergunta:{id_pergunta} -->\n```text\ntexto {id_pergunta}\n```\n"
        bloco += "| Campo | Valor |\n| tipo | Atividade |\n"
        bloco += "| conforme quando | algo |\n| não conforme quando | outra |\n"
        if id_pergunta == "a1":
            bloco = bloco.replace("| conforme quando | algo |\n", "")
        blocos.append(bloco)
    arquivo = tmp_path / "perguntas-teste.md"
    arquivo.write_text("\n".join(blocos), encoding="utf-8")

    with pytest.raises(ValueError, match="conforme quando"):
        carregar_perguntas_teste(arquivo)


# --- Bateria: repetições, output bruto, motivo de parada, falha isolada ---


def test_bateria_roda_tres_repeticoes_por_pergunta() -> None:
    """O n=3 do ADR-0003 é o padrão, não um detalhe de quem chama."""
    perguntas = [_pergunta_falsa("a1"), _pergunta_falsa("f1")]

    registros = executar_bateria(perguntas, lambda texto: _resposta_falsa("bruto"))

    assert len(registros) == 6
    assert [registro.repeticao for registro in registros] == [1, 2, 3, 1, 2, 3]


def test_bateria_agrupa_as_repeticoes_de_uma_mesma_pergunta() -> None:
    """Pergunta-maior: as repetições da a1 vêm seguidas, para ler lado a lado."""
    perguntas = [_pergunta_falsa("a1"), _pergunta_falsa("a2")]

    registros = executar_bateria(perguntas, lambda texto: _resposta_falsa("bruto"))

    assert [(registro.id, registro.repeticao) for registro in registros] == [
        ("a1", 1),
        ("a1", 2),
        ("a1", 3),
        ("a2", 1),
        ("a2", 2),
        ("a2", 3),
    ]


def test_bateria_grava_output_bruto_com_esperado_e_timestamp() -> None:
    perguntas = [_pergunta_falsa("a1"), _pergunta_falsa("f1")]

    registros = executar_bateria(
        perguntas, lambda texto: _resposta_falsa(f"S.A.U. respondeu: {texto}"), repeticoes=1
    )

    assert len(registros) == 2
    for pergunta, registro in zip(perguntas, registros, strict=True):
        assert registro.id == pergunta.id
        assert registro.repeticao == 1
        assert registro.pergunta == pergunta.texto
        assert registro.conforme_quando == pergunta.conforme_quando
        assert registro.nao_conforme_quando == pergunta.nao_conforme_quando
        assert registro.resposta_bruta == f"S.A.U. respondeu: {pergunta.texto}"
        assert registro.erro is None
        datetime.fromisoformat(registro.timestamp)
        assert registro.duracao_segundos >= 0


def test_bateria_grava_o_motivo_de_parada_e_os_numeros_da_resposta() -> None:
    """Resposta cortada sai com cara de resposta: o registro precisa dizer o motivo da parada."""
    perguntas = [_pergunta_falsa("a1")]

    registros = executar_bateria(
        perguntas,
        lambda texto: _resposta_falsa("Começou e não", motivo_de_parada="length"),
        repeticoes=1,
    )

    assert registros[0].motivo_de_parada == "length"
    assert registros[0].tokens_gerados == 27
    assert registros[0].primeiro_token_segundos == 0.4


def test_falha_de_um_turno_nao_aborta_a_bateria() -> None:
    perguntas = [_pergunta_falsa("a1"), _pergunta_falsa("a2"), _pergunta_falsa("a3")]

    def turno(texto: str) -> Resposta:
        if "a2" in texto:
            raise ErroDeInferencia("FALHA CRÍTICA: Ollama fora do ar")
        return _resposta_falsa("output bruto do S.A.U.")

    registros = executar_bateria(perguntas, turno, repeticoes=1)

    assert len(registros) == 3
    assert registros[0].resposta_bruta == "output bruto do S.A.U."
    assert registros[0].erro is None
    assert registros[1].resposta_bruta is None
    assert registros[1].erro is not None
    assert "ErroDeInferencia" in registros[1].erro
    assert registros[1].motivo_de_parada is None
    assert registros[2].resposta_bruta == "output bruto do S.A.U."
    assert registros[2].erro is None


def test_timeout_tambem_vira_erro_do_caso_e_segue(tmp_path: Path) -> None:
    perguntas = [_pergunta_falsa("p1"), _pergunta_falsa("p2")]

    def turno(texto: str) -> Resposta:
        if "p1" in texto:
            raise TimeoutError("tempo esgotado")
        return _resposta_falsa("resposta")

    registros = executar_bateria(perguntas, turno, repeticoes=1)
    destino = tmp_path / "rodada.json"
    gravar_rodada(registros, _condicoes_falsas(), destino)

    assert registros[0].erro is not None
    assert "TimeoutError" in (registros[0].erro or "")
    assert registros[1].erro is None
    assert destino.is_file()


# --- Gravação: as condições e a máquina junto das execuções ---


def test_gravacao_traz_modelo_url_uma_execucao_por_registro(tmp_path: Path) -> None:
    perguntas = [_pergunta_falsa("a1")]
    registros = executar_bateria(perguntas, lambda texto: _resposta_falsa("bruto"), repeticoes=1)

    destino = tmp_path / "rodada.json"
    gravar_rodada(registros, _condicoes_falsas(), destino)

    rodada = json.loads(destino.read_text(encoding="utf-8"))
    assert rodada["modelo"] == "qwen2.5:3b"
    assert rodada["url"] == "http://localhost:11434"
    assert rodada["inicio"]
    assert rodada["fim"]
    assert len(rodada["execucoes"]) == 1
    execucao = rodada["execucoes"][0]
    assert execucao["id"] == "a1"
    assert execucao["resposta_bruta"] == "bruto"
    assert execucao["conforme_quando"]
    assert execucao["timestamp"]


def test_gravacao_declara_as_condicoes_da_medicao(tmp_path: Path) -> None:
    """Linha de base sem as condições não é comparável com nada."""
    registros = executar_bateria(
        [_pergunta_falsa("a1")], lambda texto: _resposta_falsa("bruto"), repeticoes=1
    )

    destino = tmp_path / "rodada.json"
    gravar_rodada(registros, _condicoes_falsas(), destino)

    condicoes = json.loads(destino.read_text(encoding="utf-8"))["condicoes"]
    assert condicoes["repeticoes"] == 3
    assert condicoes["temperatura"] == 0.0
    assert condicoes["seed"] == SEED_PADRAO
    assert condicoes["num_predict"] == 256
    assert condicoes["num_ctx"] == 4096
    assert condicoes["sha256_do_prompt"]


def test_gravacao_declara_a_alocacao_do_modelo(tmp_path: Path) -> None:
    """Uma rodada de CPU precisa ficar visivelmente uma rodada de CPU."""
    alocacao = AlocacaoDoModelo(size=1_900_000_000, size_vram=0, em_cpu=True)
    registros = executar_bateria(
        [_pergunta_falsa("a1")], lambda texto: _resposta_falsa("bruto"), repeticoes=1
    )

    destino = tmp_path / "rodada.json"
    gravar_rodada(registros, _condicoes_falsas(alocacao=alocacao), destino)

    rodada = json.loads(destino.read_text(encoding="utf-8"))
    assert rodada["alocacao"]["em_cpu"] is True
    assert rodada["alocacao"]["size_vram"] == 0


def test_sha256_do_prompt_tem_64_digitos_hexadecimal() -> None:
    """O hash amarra a rodada ao prompt versionado, então precisa ser um sha256 de verdade."""
    digest = sha256_do_prompt()

    assert len(digest) == 64
    assert all(caractere in "0123456789abcdef" for caractere in digest)


def test_descrever_alocacao_le_o_item_do_api_ps() -> None:
    alocacao = descrever_alocacao({"name": "qwen2.5:3b", "size": 2_000, "size_vram": 2_000})

    assert alocacao.size == 2_000
    assert alocacao.size_vram == 2_000
    assert alocacao.em_cpu is False


def test_descrever_alocacao_marca_queda_para_cpu() -> None:
    alocacao = descrever_alocacao({"name": "qwen2.5:3b", "size": 2_000, "size_vram": 0})

    assert alocacao.em_cpu is True
    assert alocacao.size_vram == 0


def test_descrever_alocacao_marca_size_vram_ausente() -> None:
    """Campo ausente não é o mesmo campo que vale zero: um não confirma, o outro é queda."""
    alocacao = descrever_alocacao({"name": "qwen2.5:3b", "size": 2_000})

    assert alocacao.size_vram is None
    assert alocacao.em_cpu is True


# --- ClienteMedido: as travas da medição sem passar pelo grafo ---


def _handler_de_geracao(enviados: list[dict[str, Any]]) -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        enviados.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "response": "resposta do modelo",
                "done": True,
                "done_reason": "stop",
                "eval_count": 12,
                "eval_duration": 500_000_000,
                "load_duration": 100_000_000,
                "prompt_eval_duration": 200_000_000,
            },
            request=request,
        )

    return handler


def _cliente_medido_falso() -> tuple[ClienteMedido, list[dict[str, Any]]]:
    """Um `ClienteMedido` com respostas simuladas e a lista do que foi enviado."""
    enviados: list[dict[str, Any]] = []
    cliente = ClienteMedido(
        "http://localhost:11434",
        "qwen2.5:3b",
        opcoes={"temperature": 0.0, "seed": SEED_PADRAO, "num_predict": 256},
        client=httpx.Client(transport=httpx.MockTransport(_handler_de_geracao(enviados))),
    )
    return cliente, enviados


def test_cliente_medido_injeta_as_condicoes_da_medicao() -> None:
    cliente, enviados = _cliente_medido_falso()

    cliente.responder("Oi")

    opcoes = enviados[0]["options"]
    assert opcoes["temperature"] == 0.0
    assert opcoes["seed"] == SEED_PADRAO
    assert opcoes["num_predict"] == 256
    assert opcoes["num_ctx"] == 4096


def test_cliente_medido_guarda_a_resposta_do_turno() -> None:
    cliente, _ = _cliente_medido_falso()

    resposta = cliente.responder("Oi")

    assert resposta.texto == "resposta do modelo"
    assert resposta.motivo_de_parada == "stop"
    assert resposta.tokens_gerados == 12
    assert cliente.ultima is resposta
    assert cliente.ultima is not None
    assert cliente.ultima.tokens_gerados == 12


def test_cliente_medido_nao_altera_a_amostragem_do_caminho_quente() -> None:
    """O cliente de produção segue sem trava: travar a seed daria a todo Aluno a mesma resposta."""
    enviados_producao: list[dict[str, Any]] = []
    cliente_producao = ClienteOllama(
        "http://x:11434",
        "qwen2.5:3b",
        client=httpx.Client(transport=httpx.MockTransport(_handler_de_geracao(enviados_producao))),
    )
    cliente_medido, enviados_medido = _cliente_medido_falso()

    cliente_producao.responder("Oi")
    cliente_medido.responder("Oi")

    producao = enviados_producao[0]["options"]
    medido = enviados_medido[0]["options"]
    assert "temperature" not in producao
    assert "seed" not in producao
    assert medido["temperature"] == 0.0
    assert medido["seed"] == SEED_PADRAO


# --- CLI: flags que sobrescrevem o .env, e o pré-requisito que falha alto ---


def test_flags_do_harness_sobrescrevem_o_env() -> None:
    opcoes = montar_argumentos(
        ["--modelo", "outro:7b", "--url", "http://x:11434", "--timeout", "12", "--saida", "r.json"]
    )

    assert opcoes.modelo == "outro:7b"
    assert opcoes.url == "http://x:11434"
    assert opcoes.timeout == 12.0
    assert opcoes.saida == Path("r.json")


def test_default_do_cli_preserva_as_condicoes_do_adr() -> None:
    opcoes = montar_argumentos([])

    assert opcoes.repeticoes == 3
    assert opcoes.temperatura == 0.0
    assert opcoes.seed == SEED_PADRAO
    assert opcoes.num_predict == 256


def test_main_recusa_rodar_com_zero_repeticao(tmp_path: Path) -> None:
    """Uma execução só não é evidência de comportamento: o ADR-0003 mediu que muda o resultado."""
    assert main(["--repeticoes", "0", "--saida", str(tmp_path / "r.json")]) == 2
    assert not (tmp_path / "r.json").exists()


def test_main_falha_alto_quando_o_ollama_nao_responde(tmp_path: Path, monkeypatch: Any) -> None:
    """Ollama fora do ar é falha do instrumento: nenhum JSON pode ser gravado."""
    import harness.run

    def _cair(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise OllamaIndisponivelError("FALHA CRÍTICA: Não foi possível conectar ao Ollama.")

    monkeypatch.setattr(harness.run, "_checar_pre_requisitos", _cair)
    destino = tmp_path / "rodada.json"

    codigo = main(["--saida", str(destino)])

    assert codigo == 3
    assert not destino.exists()


def test_main_falha_alto_quando_a_cpu_nao_foi_autorizada(
    tmp_path: Path, monkeypatch: Any
) -> None:
    import harness.run

    def _cair(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise CpuNaoAutorizadaError("FALHA CRÍTICA: Queda silenciosa para CPU.")

    monkeypatch.setattr(harness.run, "_checar_pre_requisitos", _cair)
    destino = tmp_path / "rodada.json"

    codigo = main(["--saida", str(destino)])

    assert codigo == 3
    assert not destino.exists()


def test_main_devolve_1_quando_nenhuma_execucao_responde(
    tmp_path: Path, monkeypatch: Any
) -> None:
    import harness.run

    alocacao_falsa = AlocacaoDoModelo(size=2_000, size_vram=2_000, em_cpu=False)
    monkeypatch.setattr(harness.run, "_checar_pre_requisitos", lambda *_a, **_k: alocacao_falsa)

    def _executar_turno(cliente: Any, _texto: str, _historico: Any) -> str:
        cliente.ultima = None
        raise ErroDeInferencia("FALHA CRÍTICA: o modelo não respondeu")

    monkeypatch.setattr(harness.run, "executar_turno", _executar_turno)
    destino = tmp_path / "rodada.json"

    codigo = main(["--saida", str(destino), "--repeticoes", "1"])

    assert codigo == 1
    assert destino.is_file()
    rodada = json.loads(destino.read_text(encoding="utf-8"))
    assert len(rodada["execucoes"]) == 10
    assert all(execucao["erro"] is not None for execucao in rodada["execucoes"])


def test_main_devolve_0_quando_alguma_execucao_responde(tmp_path: Path, monkeypatch: Any) -> None:
    """Falha parcial é dado, não motivo de reprovar a rodada."""
    import harness.run

    alocacao_falsa = AlocacaoDoModelo(size=2_000, size_vram=2_000, em_cpu=False)
    monkeypatch.setattr(harness.run, "_checar_pre_requisitos", lambda *_a, **_k: alocacao_falsa)

    chamadas: list[str] = []

    def _turno(cliente: Any, texto: str, _historico: Any) -> str:
        """O `main` lê a `Resposta` do cliente depois que o turno roda: é aqui que ela nasce."""
        chamadas.append(texto)
        if len(chamadas) == 1:
            cliente.ultima = None
            raise ErroDeInferencia("FALHA CRÍTICA: o modelo não respondeu")
        cliente.ultima = _resposta_falsa("resposta")
        return "resposta"

    monkeypatch.setattr(harness.run, "executar_turno", _turno)
    destino = tmp_path / "rodada.json"

    codigo = main(["--saida", str(destino), "--repeticoes", "1"])

    assert codigo == 0
    rodada = json.loads(destino.read_text(encoding="utf-8"))
    respostas = [execucao for execucao in rodada["execucoes"] if execucao["resposta_bruta"]]
    assert len(respostas) == 9


def test_main_usa_a_url_do_host_e_nao_o_padrao_do_container(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """O padrão de `OLLAMA_BASE_URL` aponta para o container; o harness roda no host."""
    import harness.run

    vistas: list[str] = []
    alocacao_falsa = AlocacaoDoModelo(size=2_000, size_vram=2_000, em_cpu=False)

    def _checar(url: str, _modelo: str, _timeout: float) -> AlocacaoDoModelo:
        vistas.append(url)
        return alocacao_falsa

    monkeypatch.setattr(harness.run, "_checar_pre_requisitos", _checar)
    monkeypatch.setattr(harness.run, "executar_turno", lambda *_a, **_k: "resposta")
    monkeypatch.setattr(
        ClienteMedido,
        "responder",
        lambda _self, _prompt, opcoes=None: _resposta_falsa("resposta"),
    )

    main(["--saida", str(tmp_path / "r.json"), "--repeticoes", "1", "--url", "http://localhost"])

    assert vistas == ["http://localhost"]


# --- Cadeia especial s1–s5: com histórico, 3 repetições da cadeia ---


def _passos_falsos() -> list[PerguntaTeste]:
    return [_pergunta_falsa(id_passo) for id_passo in ORDEM_DA_CADEIA]


def test_parser_aceita_as_10_mais_a_cadeia() -> None:
    """O arquivo real traz a bateria isolada mais os 5 passos encadeados."""
    bateria = carregar_perguntas_teste(ARQUIVO_PERGUNTAS)
    cadeia = carregar_cadeia(ARQUIVO_PERGUNTAS)

    assert [p.id for p in bateria] == list(ORDEM_DA_BATERIA)
    assert len(bateria) == 10
    assert [p.id for p in cadeia] == list(ORDEM_DA_CADEIA)
    assert set(IDS_DA_CADEIA) == {"s1", "s2", "s3", "s4", "s5"}
    assert len(cadeia) == 5
    for passo in cadeia:
        assert passo.texto, f"o passo {passo.id} veio sem texto"
        assert passo.conforme_quando
        assert passo.nao_conforme_quando


def test_cadeia_acumula_historico_na_ordem() -> None:
    """Cada passo recebe o acumulado dos anteriores, s1→s5, e a repetição recomeça."""
    vistos: list[tuple[str, tuple[Mensagem, ...]]] = []

    def turno_com_historico(
        texto: str, historico: tuple[Mensagem, ...] | list[Mensagem]
    ) -> Resposta:
        vistos.append((texto, tuple(historico)))
        return _resposta_falsa(f"resposta a {texto}")

    registros = executar_cadeia(_passos_falsos(), turno_com_historico, repeticoes=1)

    assert [(r.id, r.repeticao) for r in registros] == [(f"s{i}", 1) for i in (1, 2, 3, 4, 5)]
    assert vistos[0][1] == ()
    assert [m.texto for m in vistos[1][1]] == [
        "texto da Pergunta-teste s1",
        "resposta a texto da Pergunta-teste s1",
    ]
    assert vistos[1][1][0].papel == "aluno"
    assert vistos[1][1][1].papel == "sau"
    assert len(vistos[4][1]) == 8
    for registro in registros:
        assert isinstance(registro, RegistroDoPassoDaCadeia)
        assert registro.historico_usado == vistos[registros.index(registro)][1]
        assert registro.erro is None


def test_cadeia_repete_a_conversa_inteira_tres_vezes() -> None:
    registros = executar_cadeia(
        _passos_falsos(), lambda texto, historico: _resposta_falsa("bruto"), repeticoes=3
    )

    assert len(registros) == 15
    assert [r.repeticao for r in registros] == [1] * 5 + [2] * 5 + [3] * 5
    assert [r.id for r in registros[:5]] == list(ORDEM_DA_CADEIA)
    # Cada repetição recomeça com histórico vazio em s1.
    assert registros[0].historico_usado == ()
    assert registros[5].historico_usado == ()
    assert registros[10].historico_usado == ()


def test_falha_de_um_passo_nao_aborta_a_cadeia() -> None:
    def turno_com_historico(texto: str, historico: object) -> Resposta:
        if "s3" in texto:
            raise ErroDeInferencia("FALHA CRÍTICA: Ollama fora do ar")
        return _resposta_falsa("output bruto do S.A.U.")

    registros = executar_cadeia(_passos_falsos(), turno_com_historico, repeticoes=1)

    assert len(registros) == 5
    assert registros[2].resposta_bruta is None
    assert registros[2].erro is not None
    assert "ErroDeInferencia" in (registros[2].erro or "")
    assert registros[3].resposta_bruta == "output bruto do S.A.U."
    assert registros[3].erro is None
    # O passo que falhou entra no histórico só com a fala do Aluno.
    papeis_s4 = [(m.papel, m.texto) for m in registros[3].historico_usado]
    assert ("aluno", "texto da Pergunta-teste s3") in papeis_s4


def test_gravacao_traz_bloco_da_cadeia_separado(tmp_path: Path) -> None:
    bateria = executar_bateria(
        [_pergunta_falsa("a1")], lambda texto: _resposta_falsa("bruto"), repeticoes=1
    )
    cadeia = executar_cadeia(
        [_pergunta_falsa("s1")],
        lambda texto, historico: _resposta_falsa("bruto"),
        repeticoes=1,
    )

    destino = tmp_path / "rodada.json"
    gravar_rodada(bateria, _condicoes_falsas(), destino, cadeia)

    rodada = json.loads(destino.read_text(encoding="utf-8"))
    assert len(rodada["execucoes"]) == 1
    assert len(rodada["cadeia"]) == 1
    passo = rodada["cadeia"][0]
    assert passo["id"] == "s1"
    assert passo["resposta_bruta"] == "bruto"
    assert "historico_usado" in passo
    assert passo["conforme_quando"]


def test_gravacao_sem_cadeia_grava_bloco_vazio(tmp_path: Path) -> None:
    """A assinatura nova não quebra a chamada antiga: sem cadeia, o bloco é vazio."""
    bateria = executar_bateria(
        [_pergunta_falsa("a1")], lambda texto: _resposta_falsa("bruto"), repeticoes=1
    )

    destino = tmp_path / "rodada.json"
    gravar_rodada(bateria, _condicoes_falsas(), destino)

    rodada = json.loads(destino.read_text(encoding="utf-8"))
    assert rodada["cadeia"] == []
