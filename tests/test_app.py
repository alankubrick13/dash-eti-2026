"""Testes de interface com o AppTest do Streamlit (modo demonstração, dados fictícios)."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "app.py")

PAGINAS = [
    "paginas/1_visao_geral.py", "paginas/2_cursistas.py", "paginas/3_atividade.py", "paginas/4_escolas.py",
    "paginas/5_territorio.py", "paginas/6_qualidade_conciliacao.py", "paginas/7_administracao.py",
]
COLUNAS_PROIBIDAS = {"CPF", "E-mail", "Telefone", "WhatsApp", "Data Nascimento", "Raça/Cor", "Gênero"}


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("ETI_AMBIENTE", "demonstracao")
    teste = AppTest.from_file(APP, default_timeout=240)
    teste.run()
    assert not teste.exception, [e.value for e in teste.exception]
    return teste


def _erros(teste):
    return [e.value for e in teste.exception] + [e.value for e in teste.error]


@pytest.mark.parametrize("pagina", PAGINAS)
def test_paginas_renderizam_sem_erros(app, pagina):
    app.switch_page(pagina)
    app.run()
    assert not _erros(app)


def _cartoes(teste) -> list[str]:
    return [h.proto.body for h in teste.get("html") if h.proto.body.startswith('<div class="eti-cartao')]


def test_galeria_de_cursistas_nao_expoe_dados_pessoais(app):
    app.switch_page("paginas/2_cursistas.py")
    app.run()
    cartoes = _cartoes(app)
    assert len(cartoes) == 24  # primeira página da galeria
    base = app.session_state["_contexto"].base
    emails = set(base.cursistas["email"].dropna())
    telefones = set(base.cursistas["telefone"].dropna().astype(str))
    for cartao in cartoes:
        assert "@" not in cartao and not any(t in cartao for t in telefones if len(t) >= 8)
    assert not any(e in "".join(cartoes) for e in emails)


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


def test_importacao_bloqueia_erro_estrutural_e_confirma_arquivo_valido(app):
    app.switch_page("paginas/7_administracao.py")
    app.run()
    radio = app.radio(key="demo_cadastro")
    radio.set_value("Cadastro sem a coluna de e-mail (erro estrutural, fictício)").run()
    app.button(key="validar_cadastro").click().run()
    assert any("E-mail" in e.value for e in app.error)
    assert app.button(key="confirmar_cadastro").disabled

    app.radio(key="demo_cadastro").set_value("Cadastro atualizado, com entradas e saídas (fictício)").run()
    app.button(key="validar_cadastro").click().run()
    assert not app.button(key="confirmar_cadastro").disabled
    app.button(key="confirmar_cadastro").click().run()
    assert any("confirmada" in s.value for s in app.success)
    assert not _erros(app)


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
