"""Cartões das galerias e peças das fichas (dados fictícios)."""

from collections import namedtuple

from src import cartoes, graficos, painel

CORES = graficos.cores_faixas(painel.ordem_faixas([1, 7, 14]))
Pessoa = namedtuple("Pessoa", [
    "id_registro", "nome", "cargo_funcao", "escola", "escola_oficial", "municipio_escola", "ente", "uf",
    "lista_grupos", "faixa_acesso", "acesso_tipo", "acesso_segundos", "status_conciliacao", "motivos",
    "requer_acompanhamento", "email", "telefone",
])


def _pessoa(**mudancas):
    dados = dict(id_registro="C1", nome="MARIA DA SILVA", cargo_funcao="Diretor Escolar", escola="EMEF TESTE",
                 escola_oficial="ESCOLA MUNICIPAL DE ENSINO FUNDAMENTAL JOÃO XXIII", municipio_escola="Belém",
                 ente="Belém", uf="PA", lista_grupos=["Para 3"], faixa_acesso="1 a 7 dias", acesso_tipo="relativo",
                 acesso_segundos=3 * 86400 + 3600, status_conciliacao="Correspondente", motivos=[],
                 requer_acompanhamento=False, email="maria.silva@correio.example", telefone="91988887777")
    dados.update(mudancas)
    return Pessoa(**dados)


def test_nomes_em_caixa_alta_ficam_legiveis():
    assert cartoes.nome_legivel("MARIA DA SILVA") == "Maria da Silva"
    assert cartoes.nome_legivel("EMEF JOÃO XXIII") == "EMEF João XXIII"
    assert cartoes.nome_legivel("ESCOLA ESTADUAL DOM PEDRO II") == "Escola Estadual Dom Pedro II"
    assert cartoes.nome_legivel("E.E.F. SANTA-RITA DE CÁSSIA") == "E.E.F. Santa-Rita de Cássia"
    assert cartoes.nome_legivel("Maria da Silva") == "Maria da Silva"  # caixa mista: como veio
    assert cartoes.nome_legivel(None) == "—"
    assert cartoes.iniciais("MARIA DA SILVA") == "MS" and cartoes.iniciais("ANA") == "A" and cartoes.iniciais("") == "?"


def test_tempo_desde_o_ultimo_acesso():
    assert cartoes.tempo_desde(1800) == "há menos de 1 hora"
    assert cartoes.tempo_desde(5 * 3600) == "há 5 horas"
    assert cartoes.tempo_desde(86400 + 10) == "há 1 dia"
    assert cartoes.tempo_desde(20 * 86400) == "há 20 dias"
    assert cartoes.tempo_desde(float("nan")) is None


def test_situacao_da_pessoa_e_da_escola():
    assert cartoes.situacao(_pessoa(), CORES) == ("Último acesso há 3 dias", CORES["1 a 7 dias"])
    assert cartoes.situacao(_pessoa(acesso_tipo="nunca", faixa_acesso=painel.FAIXA_NUNCA), CORES)[0] == "Nunca acessou"
    sem_conta = _pessoa(acesso_tipo=None, faixa_acesso=painel.FAIXA_SEM_CONTA, status_conciliacao="Sem correspondência")
    assert cartoes.situacao(sem_conta, CORES)[0] == "Sem conta na plataforma"
    assert cartoes.situacao(sem_conta._replace(status_conciliacao="Pendente"), CORES)[0] == "Conta em conciliação"
    assert [cartoes.situacao_escola(c, a) for c, a in ((3, 3), (3, 1), (3, 0), (0, 0))] == list(cartoes.SITUACOES_ESCOLA)


def test_cartao_de_pessoa_sem_contato_e_com_html_escapado():
    html = cartoes.cartao_pessoa(_pessoa(nome="ANA <SCRIPT>", requer_acompanhamento=True,
                                         motivos=[painel.MOTIVO_INATIVIDADE]), CORES)
    assert "correio.example" not in html and "91988887777" not in html
    assert "<SCRIPT>" not in html and "&lt;" in html
    assert "Pará · T3" in html and "EMEF João XXIII" in html  # nome curto da escola no cartão
    assert "Acompanhar" in html and painel.MOTIVO_INATIVIDADE in html  # marca, com o motivo na dica


def test_pontos_da_escola():
    pequena = cartoes.pontos([painel.FAIXA_NUNCA, "Até 24 horas", "1 a 7 dias"], CORES)
    assert pequena.count("<i ") == 3  # um ponto por pessoa
    assert pequena.index(CORES["Até 24 horas"]) < pequena.index(CORES[painel.FAIXA_NUNCA])  # mais recentes primeiro
    # Escola grande: pontos proporcionais, sem esconder quem nunca acessou
    grande = cartoes.pontos([painel.FAIXA_NUNCA, "Até 24 horas"] + ["1 a 7 dias"] * 40, CORES, limite=28)
    assert grande.count("<i ") == 28 and CORES[painel.FAIXA_NUNCA] in grande and "1 ponto ≈ 1,5 pessoas" in grande
