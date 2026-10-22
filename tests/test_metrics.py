"""Indicadores calculados sobre os dados reais do painel (cópia do banco), conferidos contra contagens diretas."""

import pytest
from conftest import confere

from src import importacao, metrics, painel
from src import reconciliation as rc
from src.persistence import Repositorio


def test_indicadores_de_cadastro(base_real):
    r = metrics.calcular(base_real.cursistas, base_real.contas, base_real, base_real.parametros)
    cursistas = base_real.cursistas
    assert r["pessoas_cadastradas"].valor == cursistas["chave_pessoa"].nunique()
    assert r["registros_inscricao"].valor == len(cursistas)
    assert r["escolas_identificadas"].valor == cursistas.loc[cursistas["inep_status"] == "valido", "inep"].nunique()
    assert (r["pct_inep_valido"].numerador, r["pct_inep_valido"].denominador) == (
        int((cursistas["inep_status"] == "valido").sum()), len(cursistas))


def test_indicadores_de_plataforma(base_real):
    if not base_real.tem_atividade:
        pytest.skip("base de atividade não importada")
    r = metrics.calcular(base_real.cursistas, base_real.contas, base_real, base_real.parametros)
    pessoas = painel.pessoas_de(base_real.cursistas)
    com_conta = pessoas[pessoas["status_conciliacao"] == rc.CORRESPONDENTE]
    assert (r["pct_contas_encontradas"].numerador, r["pct_contas_encontradas"].denominador) == (len(com_conta), len(pessoas))
    janela = base_real.parametros["janela_acesso_recente_dias"]
    assert r["pct_acesso_recente"].numerador == int((com_conta["dias_sem_acesso"].fillna(10**9) <= janela).sum())
    assert r["pessoas_acompanhamento"].valor == int(pessoas["requer_acompanhamento"].sum())
    assert r["contas_cursista"].valor == int((base_real.contas["eh_cursista"] == 1).sum())
    for resultado in r.values():
        if resultado.disponivel and resultado.denominador is not None:
            parte = resultado.numerador if resultado.numerador is not None else resultado.valor
            assert 0 <= parte <= resultado.denominador, resultado.indicador.id


def test_motivos_de_acompanhamento(base_real):
    pessoas = painel.pessoas_de(base_real.cursistas)
    motivos = metrics.contagem_motivos(base_real.cursistas)
    for motivo, n in zip(motivos["motivo"], motivos["pessoas"]):
        assert n == int(pessoas["motivos"].map(lambda m, alvo=motivo: alvo in m).sum()), motivo
    confere((pessoas.loc[pessoas["requer_acompanhamento"], "motivos"].map(len) > 0).all(),
            "pessoa em acompanhamento sem motivo registrado")


def test_faixas_de_acesso_coerentes_com_o_tempo(base_real):
    limites = base_real.parametros["faixas_inatividade_dias"]
    contas = base_real.contas
    esperado = [painel.classificar_faixa(t, s, limites) for t, s in zip(contas["acesso_tipo"], contas["acesso_segundos"])]
    confere(contas["faixa_acesso"].tolist() == esperado, "faixa de acesso incoerente com o tempo sem acesso")


def test_parametros_alteram_a_classificacao(dir_dados_real, tmp_path):
    copia = tmp_path / "eti.sqlite3"
    copia.write_bytes((dir_dados_real / "eti.sqlite3").read_bytes())
    repo = Repositorio(copia)
    repo.salvar_parametros({"faixas_inatividade_dias": [1, 3, 5], "limite_acompanhamento_dias": 5}, "teste")
    base = painel.montar_base(repo)
    rotulos = painel.rotulos_faixas([1, 3, 5])
    relativas = base.contas[base.contas["acesso_tipo"] == "relativo"]
    confere(set(relativas["faixa_acesso"]) <= set(rotulos), "faixas não seguiram os novos parâmetros")
    dias = relativas["acesso_segundos"] / 86400
    confere(((dias > 5) == (relativas["faixa_acesso"] == rotulos[-1])).all(), "limite superior das faixas não aplicado")


def test_sem_base_de_atividade_os_indicadores_ficam_indisponiveis(repo, previa_cadastro):
    importacao.confirmar(repo, previa_cadastro, "teste")
    base = painel.montar_base(repo)
    r = metrics.calcular(base.cursistas, base.contas, base, base.parametros)
    assert r["pessoas_cadastradas"].disponivel
    assert not r["pct_contas_encontradas"].disponivel and metrics.valor_formatado(r["pct_contas_encontradas"]) == "—"


def test_filtros_globais(base_real):
    uf = base_real.cursistas["uf"].dropna().value_counts().index[0]
    cursistas, contas = painel.aplicar_filtros(base_real, {"uf": [uf]})
    assert len(cursistas) == int((base_real.cursistas["uf"] == uf).sum())
    assert set(cursistas["uf"]) == {uf}
    vinculadas = set(cursistas["id_conta"].dropna())
    confere(set(contas["id_conta"]) <= vinculadas | set(base_real.contas.loc[base_real.contas["uf"] == uf, "id_conta"]),
            "filtro de UF deixou passar contas de outra UF")
