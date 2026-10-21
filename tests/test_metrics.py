"""Indicadores calculados sobre dados carregados, com populações de referência explícitas."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from conftest import cpf, linha_cadastro, tabela

from src import importacao, metrics, painel
from src.loaders import CABECALHOS_MOODLE_TEXTO


def _carregar(repo, pseudo, cabecalhos, cadastro, contas=None):
    importacao.confirmar(repo, importacao.preparar_cadastro(
        [tabela("cad.xlsx", cabecalhos, cadastro)], pseudo, hoje=date(2026, 10, 20)), "teste")
    if contas is not None:
        referencia = datetime(2026, 10, 20, 12, 0, tzinfo=ZoneInfo("America/Sao_Paulo"))
        importacao.confirmar(repo, importacao.preparar_atividade(
            [tabela("p.txt", CABECALHOS_MOODLE_TEXTO, contas)], pseudo, referencia, "America/Sao_Paulo",
            ["Estudante"]), "teste")
    return painel.montar_base(repo)


def test_pessoas_e_registros_nao_se_confundem(repo, pseudo, cabecalhos_cadastro):
    mesma = cpf(3)
    base = _carregar(repo, pseudo, cabecalhos_cadastro, [
        linha_cadastro("ANA SOUZA", email="ana@correio.example", cpf_valor=mesma),
        linha_cadastro("ANA SOUZA", email="ana@correio.example", cpf_valor=mesma, escola="OUTRA"),
        linha_cadastro("BRUNO LIMA", email="bruno@correio.example", inep=None),
    ])
    r = metrics.calcular(base.cursistas, base.contas, base, base.parametros)
    assert r["pessoas_cadastradas"].valor == 2
    assert r["registros_inscricao"].valor == 3
    assert (r["pct_inep_valido"].numerador, r["pct_inep_valido"].denominador) == (2, 3)
    # Sem base de atividade, os indicadores de plataforma ficam indisponíveis (e não zerados)
    assert not r["pct_contas_encontradas"].disponivel
    assert metrics.valor_formatado(r["pct_contas_encontradas"]) == "—"


def test_indicadores_de_plataforma(repo, pseudo, cabecalhos_cadastro):
    base = _carregar(repo, pseudo, cabecalhos_cadastro, [
        linha_cadastro("ANA SOUZA", email="ana@correio.example"),
        linha_cadastro("BRUNO LIMA", email="bruno@correio.example"),
        linha_cadastro("CARLA DIAS", email="carla@correio.example"),
        linha_cadastro("DANIEL REIS", email="daniel@correio.example"),
        linha_cadastro("ELISA MOTA", email="elisa@correio.example"),
    ], contas=[
        ["ANA SOUZA", "ana@correio.example", "Estudante", "Para 1", "2 dias 3 horas", "Ativo"],
        ["BRUNO LIMA", "bruno@correio.example", "Estudante", "Para 1", "20 dias 1 hora", "Ativo"],
        ["CARLA DIAS", "carla@correio.example", "Estudante", "Para 2", "Nunca", "Ativo"],
        ["DANIEL REIS", "daniel@correio.example", "Estudante", "Para 2", "1 dia", "Suspenso"],
        ["ELISA MOTA", "elisa.nova@correio.example", "Estudante", "Para 2", "1 hora 2 minutos", "Ativo"],
        ["TUTORA X", "tutora@formacao.example", "Formador (Tutor não editor)", "Para 1", "1 hora", "Ativo"],
    ])
    r = metrics.calcular(base.cursistas, base.contas, base, base.parametros)
    # Elisa tem outro e-mail na plataforma: fica pendente, fora do numerador
    assert (r["pct_contas_encontradas"].numerador, r["pct_contas_encontradas"].denominador) == (4, 5)
    assert (r["pct_contas_ativas"].numerador, r["pct_contas_ativas"].denominador) == (3, 4)
    assert (r["pct_acesso_recente"].numerador, r["pct_acesso_recente"].denominador) == (2, 4)  # Ana e Daniel (≤ 7 dias)
    # Acompanhamento: Bruno (20 dias > 14), Carla (nunca), Daniel (conta não ativa); Elisa pendente não entra
    assert r["pessoas_acompanhamento"].valor == 3
    assert r["registros_pendentes"].valor == 1
    assert r["contas_cursista"].valor == 5  # a tutora não conta como cursista
    motivos = dict(zip(*metrics.contagem_motivos(base.cursistas).values.T))
    assert motivos == {painel.MOTIVO_INATIVIDADE: 1, painel.MOTIVO_NUNCA: 1, painel.MOTIVO_CONTA_INATIVA: 1}
    faixas = dict(zip(base.cursistas["nome"], base.cursistas["faixa_acesso"]))
    assert faixas["ANA SOUZA"] == "1 a 7 dias"
    assert faixas["BRUNO LIMA"] == "Mais de 14 dias"
    assert faixas["ELISA MOTA"] == painel.FAIXA_SEM_CONTA


def test_parametros_alteram_classificacao(repo, pseudo, cabecalhos_cadastro):
    repo.salvar_parametros({"faixas_inatividade_dias": [1, 3, 5], "limite_acompanhamento_dias": 1}, "teste")
    base = _carregar(repo, pseudo, cabecalhos_cadastro, [linha_cadastro("ANA SOUZA", email="ana@correio.example")],
                     contas=[["ANA SOUZA", "ana@correio.example", "Estudante", "Para 1", "2 dias 3 horas", "Ativo"]])
    assert base.cursistas.loc[0, "faixa_acesso"] == "1 a 3 dias"
    assert base.cursistas.loc[0, "requer_acompanhamento"]


def test_filtros_globais(repo, pseudo, cabecalhos_cadastro):
    base = _carregar(repo, pseudo, cabecalhos_cadastro, [
        linha_cadastro("ANA SOUZA", email="ana@correio.example", uf="PA"),
        linha_cadastro("BRUNO LIMA", email="bruno@correio.example", uf="AM", inep=13012345, cod_ibge=1302603, ente="Manaus"),
    ], contas=[
        ["ANA SOUZA", "ana@correio.example", "Estudante", "Amazonas 1", "1 dia", "Ativo"],
        ["BRUNO LIMA", "bruno@correio.example", "Estudante", "Para 1", "1 dia", "Ativo"],
        ["SEM CADASTRO", "sc@correio.example", "Estudante", "Para 1", "1 dia", "Ativo"],
    ])
    cursistas, contas = painel.aplicar_filtros(base, {"uf": ["AM"]})
    assert cursistas["nome"].tolist() == ["BRUNO LIMA"] and contas["nome_completo"].tolist() == ["BRUNO LIMA"]
    cursistas, contas = painel.aplicar_filtros(base, {"grupo": ["Para 1"]})
    assert cursistas["nome"].tolist() == ["BRUNO LIMA"]
    assert sorted(contas["nome_completo"]) == ["BRUNO LIMA", "SEM CADASTRO"]  # só grupo: inclui contas sem vínculo
