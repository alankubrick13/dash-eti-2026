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


def _com_conta(base):
    pessoas = painel.pessoas_de(base.cursistas)
    return pessoas[pessoas["status_conciliacao"] == rc.CORRESPONDENTE]


def test_ja_acessaram_confere_com_as_faixas(base_real):
    if not base_real.tem_atividade:
        pytest.skip("base de atividade não importada")
    r = metrics.calcular(base_real.cursistas, base_real.contas, base_real, base_real.parametros)["pct_ja_acessaram"]
    com_conta = _com_conta(base_real)
    faixas_de_tempo = set(painel.rotulos_faixas(base_real.parametros["faixas_inatividade_dias"]))
    assert (r.numerador, r.denominador) == (int(com_conta["faixa_acesso"].isin(faixas_de_tempo).sum()), len(com_conta))


def test_histograma_soma_quem_tem_acesso(base_real):
    if not base_real.tem_atividade:
        pytest.skip("base de atividade não importada")
    parametros = base_real.parametros
    janela, limite = parametros["janela_acesso_recente_dias"], parametros["limite_acompanhamento_dias"]
    com_conta = _com_conta(base_real)
    classes = painel.classes_de_dias(com_conta["dias_sem_acesso"], parametros["faixas_inatividade_dias"], (janela, limite))
    assert classes["contagem"].sum() == int(com_conta["dias_sem_acesso"].notna().sum())
    # Cada classe fica numa única faixa: a soma por faixa é a contagem das faixas
    por_faixa = classes.groupby("faixa")["contagem"].sum()
    contagem = com_conta.loc[com_conta["dias_sem_acesso"].notna(), "faixa_acesso"].value_counts()
    assert por_faixa[por_faixa > 0].sort_index().to_dict() == contagem.sort_index().to_dict()
    assert {janela, limite} <= set(classes["inicio"])  # as marcas do gráfico são bordas de classe
    confere(classes["contagem"].iloc[-1] > 0, "classes vazias depois do maior tempo sem acesso")


def test_destaques_batem_com_os_indicadores(base_real):
    if not base_real.tem_atividade:
        pytest.skip("base de atividade não importada")
    parametros = base_real.parametros
    janela, limite = parametros["janela_acesso_recente_dias"], parametros["limite_acompanhamento_dias"]
    r = metrics.calcular(base_real.cursistas, base_real.contas, base_real, parametros)
    itens = metrics.destaques(base_real.cursistas, base_real.contas, parametros)
    com_conta = _com_conta(base_real)
    assert itens[0].valor == metrics.valor_formatado(r["pct_ja_acessaram"])
    assert itens[1].valor == metrics.numero(r["pct_acesso_recente"].numerador)
    assert itens[2].valor == metrics.numero(int((com_conta["acesso_tipo"] == "nunca").sum()))
    turmas = painel.resumo_turmas(base_real.contas, janela, limite)
    turmas = turmas[turmas["estudantes"] >= 10]
    if not turmas.empty:
        menor = turmas["taxa_acesso"].min()
        assert itens[3].valor == metrics.percentual(menor, 0)
        empatadas = turmas[(turmas["taxa_acesso"] - menor).abs() < 1e-9]["rotulo"]
        assert all(rotulo in itens[3].texto for rotulo in empatadas)  # empates: todas as turmas são citadas
    grupos = {painel.GRUPO_NUNCA, painel.grupo_recentes(janela), painel.grupo_inativos(limite)}
    for item in itens:
        if item.acao and item.acao[0] == "pagina" and item.acao[2]:
            assert item.acao[2] in grupos, item.titulo


def test_turmas_cobrem_todos_os_estudantes(base_real):
    if not base_real.tem_atividade:
        pytest.skip("base de atividade não importada")
    parametros = base_real.parametros
    turmas = painel.resumo_turmas(base_real.contas, parametros["janela_acesso_recente_dias"],
                                  parametros["limite_acompanhamento_dias"])
    estudantes = base_real.contas[base_real.contas["eh_cursista"] == 1]
    assert turmas["estudantes"].sum() == sum(len(grupos) for grupos in estudantes["lista_grupos"])
    assert ((turmas["acessaram"] + turmas["nunca"]) <= turmas["estudantes"]).all()
    assert all(len(faixas) == n for faixas, n in zip(turmas["faixas"], turmas["estudantes"]))
    assert ((turmas["inativos"] + turmas["nunca"]) <= turmas["atencao"]).all()


def test_perfil_e_escola_das_contas_vem_do_cadastro(base_real):
    """Cargo, origem, escolaridade, semana da inscrição e dados da escola de cada conta: os da pessoa associada."""
    import pandas as pd

    if base_real.associacoes.empty:
        pytest.skip("nenhuma associação entre cadastro e plataforma")
    cadastro = base_real.cursistas.set_index("id_registro")
    contas = base_real.contas.set_index("id_conta")
    divergentes = 0
    for id_registro, id_conta in base_real.associacoes.drop_duplicates("id_conta")[["id_registro", "id_conta"]].itertuples(index=False):
        for coluna in painel.COLUNAS_PERFIL:
            a, b = cadastro.at[id_registro, coluna], contas.at[id_conta, coluna]
            divergentes += not ((pd.isna(a) and pd.isna(b)) or a == b)
    confere(divergentes == 0, f"{divergentes} valor(es) de perfil das contas diferentes do cadastro")
    semanas = pd.to_datetime(base_real.cursistas["semana_inscricao"])
    respostas = pd.to_datetime(base_real.cursistas["data_resposta"])
    validas = respostas.notna()
    assert (semanas[validas].dt.weekday == 0).all()  # semana começa na segunda-feira
    assert (respostas[validas] - semanas[validas]).dt.days.between(0, 6).all()
    if not base_real.atributos_escolas.empty:
        internet = base_real.atributos_escolas.set_index("co_entidade")["IN_INTERNET"]
        com_dado = base_real.cursistas.dropna(subset=["internet_escola"])
        esperado = com_dado["inep"].map(internet).map({"1": "Com internet", "0": "Sem internet"})
        assert (com_dado["internet_escola"] == esperado).all()
