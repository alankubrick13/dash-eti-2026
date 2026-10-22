"""Cartões das galerias e peças das fichas, gerados para todas as pessoas e escolas reais do painel."""

import re

import pytest
from conftest import confere

from src import cartoes, graficos, painel
from src.normalization import eh_vazio


@pytest.fixture(scope="module")
def pessoas(base_real):
    return painel.pessoas_de(base_real.cursistas)


@pytest.fixture(scope="module")
def cores(base_real):
    return graficos.cores_faixas(painel.ordem_faixas(base_real.parametros["faixas_inatividade_dias"]))


def _letras(texto: str) -> str:
    return " ".join(str(texto).split()).casefold()


def test_nomes_reais_so_mudam_de_caixa(base_real):
    nomes = [n for n in base_real.cursistas["nome"] if not eh_vazio(n)]
    escolas = [e for e in base_real.cursistas["escola_oficial"].dropna().unique()]
    alterados = sum(_letras(cartoes.nome_legivel(n)) != _letras(n) for n in [*nomes, *escolas])
    confere(alterados == 0, f"{alterados} nome(s) real(is) com letras alteradas (além da caixa)")
    instaveis = sum(cartoes.nome_legivel(cartoes.nome_legivel(n)) != cartoes.nome_legivel(n) for n in nomes)
    confere(instaveis == 0, "formatação de nomes instável")


def test_iniciais_dos_nomes_reais(base_real):
    erradas = 0
    for nome in base_real.cursistas["nome"].dropna():
        sigla = cartoes.iniciais(nome)
        palavras = [p for p in str(nome).split() if p.lower() not in cartoes.PARTICULAS and p[:1].isalpha()]
        erradas += not (1 <= len(sigla) <= 2 and sigla.isupper() and palavras and sigla[0] == palavras[0][0].upper())
    confere(erradas == 0, f"{erradas} inicial(is) incoerente(s) com o nome")


def test_situacao_das_pessoas_reais(pessoas, cores):
    incoerentes = 0
    for pessoa in pessoas.itertuples(index=False):
        texto, cor = cartoes.situacao(pessoa, cores)
        if pessoa.acesso_tipo in ("relativo", "absoluto"):
            incoerentes += not texto.startswith("Último acesso há")
        elif pessoa.acesso_tipo == "nunca":
            incoerentes += texto != "Nunca acessou"
        incoerentes += cor != cores.get(pessoa.faixa_acesso, graficos.CINZA_SEM_CONTA)
    confere(incoerentes == 0, f"{incoerentes} situação(ões) incoerente(s) nos cartões")


def test_cartoes_reais_nao_mostram_contatos(base_real, pessoas, cores):
    """Para todas as pessoas reais: cartão e linha da ficha da escola sem e-mail, telefone ou WhatsApp."""
    vazados = 0
    for pessoa in pessoas.itertuples(index=False):
        html = (cartoes.cartao_pessoa(pessoa, cores) + cartoes.linha_pessoa(pessoa, cores)).lower()
        digitos = re.sub(r"\D", "", html)
        if not eh_vazio(pessoa.email):
            vazados += str(pessoa.email).lower() in html
        for telefone in (pessoa.telefone, pessoa.whatsapp):
            numero = re.sub(r"\D", "", str(telefone)) if not eh_vazio(telefone) else ""
            vazados += len(numero) >= 8 and numero in digitos
    confere(vazados == 0, f"{vazados} contato(s) real(is) dentro dos cartões")
    confere(len(pessoas) == base_real.cursistas["chave_pessoa"].nunique(), "galeria sem um cartão por pessoa")


def test_html_dos_cartoes_escapado(pessoas, cores):
    pessoa = next(pessoas.itertuples(index=False))
    html = cartoes.cartao_pessoa(pessoa._replace(nome=f"{pessoa.nome} <b>"), cores)
    assert "<b>" not in html and "&lt;" in html


def test_cartoes_das_escolas_reais(base_real, cores):
    resumo = painel.resumo_escolas(base_real.cursistas)
    dados = base_real.cursistas.assign(_chave=painel.chave_escola(base_real.cursistas)).drop_duplicates(
        ["_chave", "chave_pessoa"])
    faixas = dados.groupby("_chave")["faixa_acesso"].agg(list).to_dict()
    incoerentes = 0
    for escola in resumo.itertuples(index=False):
        lista = faixas.get(escola.chave_escola, [])
        html = cartoes.cartao_escola(escola, lista, cores)
        incoerentes += len(lista) != escola.pessoas
        incoerentes += html.count("<i style=") != min(len(lista), 28)
        incoerentes += cartoes.situacao_escola(escola.com_conta, escola.acessaram) not in cartoes.SITUACOES_ESCOLA
        # o nome oficial aparece inteiro (só a caixa muda)
        incoerentes += _letras(cartoes.nome_legivel(escola.escola)) not in _letras(re.sub(r"<[^>]+>", " ", html))
    confere(len(resumo) > 0 and incoerentes == 0, f"{incoerentes} incoerência(s) nos cartões de escola")


def test_tempo_desde_o_ultimo_acesso(base_real):
    duracoes = base_real.contas.loc[base_real.contas["acesso_tipo"] == "relativo", "acesso_segundos"]
    confere(len(duracoes) > 0 and all(cartoes.tempo_desde(s).startswith("há ") for s in duracoes),
            "tempo desde o acesso mal formatado")
    # Especificação de formato
    assert [cartoes.tempo_desde(s) for s in (1800, 5 * 3600, 86400 + 10, 20 * 86400)] == [
        "há menos de 1 hora", "há 5 horas", "há 1 dia", "há 20 dias"]
    assert cartoes.tempo_desde(float("nan")) is None
