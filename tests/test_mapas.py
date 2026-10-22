"""Mapas com as malhas oficiais do IBGE e os dados reais do painel (cópia do banco)."""

import pandas as pd
import pytest
from conftest import confere

from src import config, mapas
from src.importacao import carregar_municipios


@pytest.fixture(scope="module")
def resumo(base_real):
    return mapas.resumo_por_municipio(base_real.cursistas)


@pytest.fixture(scope="module")
def malhas(base_real, resumo):
    municipios, contornos, faltando = mapas.carregar_malhas(set(mapas.ufs_do_mapa(base_real.cursistas, resumo)),
                                                            baixar=False)
    if faltando:
        pytest.skip(f"malhas do IBGE ausentes para {', '.join(faltando)}")
    return municipios, contornos


def _poligonos(geojson):
    for feicao in geojson["features"]:
        geo = feicao["geometry"]
        yield from ([geo["coordinates"]] if geo["type"] == "Polygon" else geo["coordinates"])


def test_malhas_oficiais_orientadas_para_o_plotly(malhas):
    municipios, contornos = malhas
    errados = 0
    for poligono in [*_poligonos(municipios), *_poligonos(contornos)]:
        errados += mapas._area(poligono[0]) >= 0  # anel externo no sentido horário
        errados += sum(mapas._area(furo) <= 0 for furo in poligono[1:])  # furos no anti-horário
    assert errados == 0


def test_municipios_das_malhas_conferem_com_a_lista_oficial(malhas):
    municipios, _ = malhas
    lista = carregar_municipios()
    codigos = [f["properties"]["codarea"] for f in municipios["features"]]
    assert len(codigos) == len(set(codigos)) and set(codigos) <= set(lista)
    lon0, lon1, lat0, lat1 = mapas.limites(municipios)
    assert -75 < lon0 < lon1 < -28 and -35 < lat0 < lat1 < 6  # dentro do território brasileiro


def test_resumo_por_municipio_real(base_real, resumo):
    from src import painel

    pessoas = painel.pessoas_de(base_real.cursistas)
    com_municipio = painel.municipio_do_registro(pessoas).notna()
    assert int(resumo["pessoas"].sum()) == int(com_municipio.sum())
    assert set(resumo["codigo"]) <= set(carregar_municipios())
    confere((resumo["acessaram"] <= resumo["com_conta"]).all() and (resumo["com_conta"] <= resumo["pessoas"]).all(),
            "contagens por município incoerentes")
    sem_conta = resumo["com_conta"] == 0
    assert resumo.loc[sem_conta, "taxa_acesso"].isna().all()  # sem ninguém com conta: taxa indefinida, nunca 0%
    assert resumo.loc[~sem_conta, "taxa_acesso"].between(0, 1).all()


def test_ufs_do_mapa(base_real, resumo):
    esperado = set(base_real.cursistas["uf"].dropna()) | {config.UFS[c[:2]][0] for c in resumo["codigo"]}
    assert mapas.ufs_do_mapa(base_real.cursistas, resumo) == frozenset(esperado)


def test_malha_ausente_e_informada(tmp_path, monkeypatch, base_real):
    monkeypatch.setattr(mapas, "DIR_MALHAS", tmp_path)
    uf = base_real.cursistas["uf"].dropna().iloc[0]
    _, _, faltando = mapas.carregar_malhas({uf}, baixar=False)
    assert faltando == [uf]


def test_figura_com_os_dados_reais(resumo, malhas):
    municipios, contornos = malhas
    com_taxa = resumo.dropna(subset=["taxa_acesso"])
    selecionado = com_taxa.sort_values("pessoas", ascending=False)["codigo"].iloc[0]
    fig = mapas.figura(resumo, municipios, contornos, "Acessaram o curso", selecionado)
    vazios, dados, ufs = fig.data
    todos = {f["properties"]["codarea"] for f in municipios["features"]}
    assert set(vazios.locations) == todos - set(com_taxa["codigo"])
    assert list(dados.locations) == com_taxa["codigo"].tolist() and (dados.zmin, dados.zmax) == (0.0, 1.0)
    i = list(dados.locations).index(selecionado)
    assert dados.marker.line.width[i] > 2 and ufs.hoverinfo == "skip"
    nome, uf = carregar_municipios()[selecionado]
    assert f"{nome} ({uf})" in dados.text[i]
    assert mapas.figura(resumo, municipios, contornos, "Nunca acessaram").data[1].colorscale[-1][1] == mapas.ALERTA_MAX
    contagem = mapas.figura(resumo, municipios, contornos, "Cursistas").data[1]
    assert contagem.zmax == float(resumo["pessoas"].max())
    assert isinstance(fig.layout.geo.lonaxis.range, tuple) and len(pd.Series(fig.layout.geo.lataxis.range)) == 2
