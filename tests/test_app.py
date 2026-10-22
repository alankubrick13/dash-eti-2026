"""Testes de interface com o AppTest do Streamlit, sobre uma cópia do banco real do painel (modo local).

A cópia fica numa pasta temporária: consultas de contato e outras ações auditadas não chegam ao banco
original. As verificações sobre dados pessoais usam ``confere``, que nunca mostra os valores.
"""

import shutil
from pathlib import Path

import pytest
from conftest import confere
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "app.py")

PAGINAS = [
    "paginas/1_visao_geral.py", "paginas/2_cursistas.py", "paginas/3_atividade.py", "paginas/4_escolas.py",
    "paginas/5_territorio.py", "paginas/6_qualidade_conciliacao.py", "paginas/7_administracao.py",
]
TERMOS_DE_DADOS_INVENTADOS = ("fictíci", "demonstração", "sintétic", "de exemplo")


@pytest.fixture
def app(monkeypatch, tmp_path, dir_dados_real):
    dados = tmp_path / "dados"
    shutil.copytree(dir_dados_real, dados)
    monkeypatch.setenv("ETI_AMBIENTE", "local")
    monkeypatch.setenv("ETI_DIRETORIO_DADOS", str(dados))
    monkeypatch.delenv("ETI_CHAVE_PSEUDONIMIZACAO", raising=False)
    teste = AppTest.from_file(APP, default_timeout=240)
    teste.run()
    confere(not teste.exception, "o painel não abriu com os dados reais")
    return teste


def _erros(teste):
    return [e.value for e in teste.exception] + [e.value for e in teste.error]


@pytest.mark.parametrize("pagina", PAGINAS)
def test_paginas_renderizam_com_os_dados_reais(app, pagina):
    app.switch_page(pagina)
    app.run()
    confere(not _erros(app), f"{pagina}: erro ao montar a página")
    texto = " ".join([m.value for m in app.markdown] + [h.proto.body for h in app.get("html")]).lower()
    confere(not any(t in texto for t in TERMOS_DE_DADOS_INVENTADOS), f"{pagina}: menção a dados inventados")
    confere("dados reais" in texto, f"{pagina}: selo de dados reais ausente")


def _cartoes(teste) -> list[str]:
    return [h.proto.body for h in teste.get("html") if h.proto.body.startswith('<div class="eti-cartao')]


def test_galeria_de_cursistas_nao_expoe_dados_pessoais(app):
    import re

    app.switch_page("paginas/2_cursistas.py")
    app.run()
    cartoes = _cartoes(app)
    confere(len(cartoes) == 24, "a primeira página da galeria deve ter 24 cartões")
    base = app.session_state["_contexto"].base
    html = " ".join(cartoes).lower()
    digitos = re.sub(r"\D", "", html)
    emails = [str(e).lower() for e in base.cursistas["email"].dropna()]
    telefones = [re.sub(r"\D", "", str(t)) for t in base.cursistas["telefone"].dropna()]
    vazados = sum(e in html for e in emails) + sum(len(t) >= 8 and t in digitos for t in telefones)
    confere("@" not in html and vazados == 0, f"{vazados} contato(s) real(is) nos cartões da galeria")


def test_grupos_e_mostrar_mais_da_galeria(app):
    app.switch_page("paginas/2_cursistas.py")
    app.run()
    pessoas = app.session_state["_contexto"].cursistas
    [nunca] = [b for b in app.button if b.label.startswith("Mostrar: Nunca acessaram")]
    nunca.click().run()
    assert not _erros(app)
    nomes = {b.label.removeprefix("Abrir a ficha de ") for b in app.button if b.label.startswith("Abrir a ficha de ")}
    from src.cartoes import nome_legivel

    esperados = {nome_legivel(n) for n in pessoas.loc[pessoas["acesso_tipo"] == "nunca", "nome"]}
    assert nomes and nomes <= esperados
    [mais] = [b for b in app.button if b.label.startswith("Mostrar mais pessoas")] or [None]
    if mais is not None:
        antes = len(_cartoes(app))
        mais.click().run()
        assert len(_cartoes(app)) > antes


def test_ficha_individual_e_dados_de_contato_auditados(app):
    app.switch_page("paginas/2_cursistas.py")
    app.run()
    [cartao] = [b for b in app.button if b.label.startswith("Abrir a ficha de ")][:1]
    cartao.click().run()
    assert not _erros(app)
    textos = _textos(app)
    assert "Participação na formação" in textos and "#### Escola" in textos
    assert {e.label for e in app.expander} >= {"Inscrição e vínculo", "Origem dos dados", "Dados pessoais e de contato"}
    ctx = app.session_state["_contexto"]
    antes = len(ctx.repo.auditoria())
    botoes = [b for b in app.button if b.label == "Exibir dados de contato"]
    assert botoes, "o contato deve ficar oculto até uma ação explícita"
    botoes[0].click().run()
    assert not _erros(app)
    assert len(ctx.repo.auditoria()) == antes + 1
    assert ctx.repo.auditoria().iloc[0]["acao"] == "exibiu_dados_contato"


def test_administracao_so_aceita_arquivos_e_bases_oficiais(app):
    app.switch_page("paginas/7_administracao.py")
    app.run()
    confere(not _erros(app), "erro ao montar a Administração")
    origens = app.radio(key="escolas_modo").options
    assert origens == ["Baixar microdados oficiais do Inep", "Importar pacote de microdados já baixado (ZIP ou CSV)",
                       "Importar exportação do Catálogo de Escolas (XLSX ou CSV)"]
    confere(not [r for r in app.radio if (r.key or "").startswith("demo_")], "seletor de arquivos de exemplo na página")


def _textos(teste) -> str:
    return " ".join(m.value for m in teste.markdown)


def _escola_localizada(teste) -> str:
    from src import painel, school_data

    base = teste.session_state["_contexto"].base
    localizadas = base.cursistas[base.cursistas["situacao_inep"] == school_data.SITUACAO_INEP_LOCALIZADO]
    return painel.chave_escola(localizadas).value_counts().index[0]  # a escola com mais cursistas


def test_ficha_da_escola_traz_dados_do_inep_e_cursistas(app):
    from src import fichas

    app.switch_page("paginas/4_escolas.py")
    app.run()
    assert len(_cartoes(app)) == 24
    chave = _escola_localizada(app)
    app.session_state[fichas.ABERTA] = ("escola", chave, None)
    app.run()
    assert not _erros(app)
    textos = _textos(app)
    assert "Quem desta escola participa da formação" in textos and "#### Censo Escolar" in textos
    assert any("eti-infra" in h.proto.body for h in app.get("html"))

    # Da escola para um dos seus cursistas, e de volta
    [pessoa] = [b for b in app.button if b.label.startswith("Abrir a ficha de ")][:1]
    pessoa.click().run()
    assert not _erros(app)
    assert app.session_state[fichas.ABERTA][0] == "cursista" and "Participação na formação" in _textos(app)
    [voltar] = [b for b in app.button if b.label == "Voltar para a escola"]
    voltar.click().run()
    assert app.session_state[fichas.ABERTA][:2] == ("escola", chave)
    # Fechar a gaveta (X ou Esc) chama fichas.fechar, que limpa a ficha aberta
    app.session_state[fichas.ABERTA] = None
    app.run()
    assert "Quem desta escola participa da formação" not in _textos(app)


def test_municipio_do_mapa_leva_as_escolas(app):
    from src import fichas, mapas

    app.switch_page("paginas/5_territorio.py")
    app.run()
    resumo = mapas.resumo_por_municipio(app.session_state["_contexto"].cursistas)
    municipio = resumo.sort_values("pessoas", ascending=False)["codigo"].iloc[0]
    app.session_state["municipio_sel"] = municipio
    app.run()
    assert not _erros(app)
    assert "## Escolas de " in _textos(app)
    [escola] = [b for b in app.button if b.label.startswith("Abrir a ficha da escola")][:1]
    escola.click().run()
    assert not _erros(app)
    assert app.session_state[fichas.ABERTA][0] == "escola" and "Quem desta escola participa da formação" in _textos(app)
