"""Mapas por município: orientação das malhas, agregação por município e figura (dados fictícios)."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from conftest import linha_cadastro, tabela

from src import importacao, mapas, painel
from src.loaders import CABECALHOS_MOODLE_TEXTO

BELEM, ABAETETUBA, PALMAS = "1501402", "1500107", "1721000"


def _quadrado(sentido_horario: bool, x0: float = 0.0, tamanho: float = 1.0) -> list:
    anel = [[x0, x0], [x0 + tamanho, x0], [x0 + tamanho, x0 + tamanho], [x0, x0 + tamanho], [x0, x0]]
    return list(reversed(anel)) if sentido_horario else anel


def test_aneis_orientados_como_o_plotly_espera():
    # Anel externo anti-horário e furo horário (convenção do GeoJSON/RFC 7946): o d3-geo pede o contrário
    geo = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"codarea": "1"},
         "geometry": {"type": "Polygon", "coordinates": [_quadrado(False, 0, 4), _quadrado(True, 1, 1)]}},
        {"type": "Feature", "properties": {"codarea": "2"},
         "geometry": {"type": "MultiPolygon", "coordinates": [[_quadrado(False, 10, 2)], [_quadrado(True, 20, 2)]]}},
    ]}
    resultado = mapas.orientar_para_plotly(geo)
    externo, furo = resultado["features"][0]["geometry"]["coordinates"]
    assert mapas._area(externo) < 0 < mapas._area(furo)
    assert all(mapas._area(p[0]) < 0 for p in resultado["features"][1]["geometry"]["coordinates"])


def _base(repo, pseudo, cabecalhos):
    importacao.confirmar(repo, importacao.preparar_cadastro([tabela("cad.xlsx", cabecalhos, [
        linha_cadastro("ANA SOUZA", email="ana@correio.example", cod_ibge=int(BELEM)),
        linha_cadastro("BRUNO LIMA", email="bruno@correio.example", cod_ibge=int(BELEM), inep=15000001),
        linha_cadastro("CARLA DIAS", email="carla@correio.example", cod_ibge=int(ABAETETUBA), ente="Abaetetuba",
                       inep=15000002),
        # Ente estadual (código de 2 dígitos) e escola sem base oficial: sem município, fora do mapa
        linha_cadastro("DIEGO REIS", email="diego@correio.example", cod_ibge=15, ente="Pará", inep=15000003),
    ])], pseudo, hoje=date(2026, 10, 20)), "teste")
    referencia = datetime(2026, 10, 20, 12, 0, tzinfo=ZoneInfo("America/Sao_Paulo"))
    importacao.confirmar(repo, importacao.preparar_atividade([tabela("p.txt", CABECALHOS_MOODLE_TEXTO, [
        ["ANA SOUZA", "ana@correio.example", "Estudante", "Para 1", "2 dias", "Ativo"],
        ["BRUNO LIMA", "bruno@correio.example", "Estudante", "Para 1", "Nunca", "Ativo"],
    ])], pseudo, referencia, "America/Sao_Paulo", ["Estudante"]), "teste")
    return painel.montar_base(repo)


def test_resumo_por_municipio(repo, pseudo, cabecalhos_cadastro):
    base = _base(repo, pseudo, cabecalhos_cadastro)
    resumo = mapas.resumo_por_municipio(base.cursistas).set_index("codigo")
    assert set(resumo.index) == {BELEM, ABAETETUBA}  # Diego (ente estadual, escola não localizada) fica de fora
    belem = resumo.loc[BELEM]
    assert (belem["pessoas"], belem["escolas"], belem["com_conta"], belem["acessaram"], belem["nunca"]) == (2, 2, 2, 1, 1)
    assert belem["taxa_acesso"] == pytest.approx(0.5)
    # Sem ninguém com conta, a taxa fica indefinida (nunca 0%)
    assert resumo.loc[ABAETETUBA, "com_conta"] == 0 and pd.isna(resumo.loc[ABAETETUBA, "taxa_acesso"])
    assert mapas.resumo_por_municipio(base.cursistas.iloc[0:0]).empty


def test_ufs_do_mapa_incluem_a_uf_do_municipio_da_escola():
    cursistas = pd.DataFrame({"uf": ["PA", None]})
    resumo = pd.DataFrame({"codigo": [BELEM, PALMAS]})
    assert mapas.ufs_do_mapa(cursistas, resumo) == frozenset({"PA", "TO"})


def test_malhas_locais_e_ausentes(tmp_path, monkeypatch):
    municipios, contornos, faltando = mapas.carregar_malhas({"PA"}, baixar=False)
    codigos = {f["properties"]["codarea"] for f in municipios["features"]}
    assert BELEM in codigos and len(codigos) == 144 and not faltando  # 144 municípios no Pará
    assert [f["properties"]["codarea"] for f in contornos["features"]] == ["15"]
    monkeypatch.setattr(mapas, "DIR_MALHAS", tmp_path)
    _, _, faltando = mapas.carregar_malhas({"PA"}, baixar=False)
    assert faltando == ["PA"]


def _geo(*codigos):
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"codarea": c},
         "geometry": {"type": "Polygon", "coordinates": [_quadrado(True, i * 2, 1)]}} for i, c in enumerate(codigos)]}


def test_figura_destaca_municipio_e_separa_os_sem_cursistas():
    resumo = pd.DataFrame([{"codigo": BELEM, "pessoas": 3, "escolas": 2, "com_conta": 2, "acessaram": 1, "nunca": 1,
                            "acompanhamento": 1, "taxa_acesso": 0.5, "taxa_nunca": 0.5, "taxa_acompanhamento": 1 / 3}])
    fig = mapas.figura(resumo, _geo(BELEM, ABAETETUBA), _geo("15"), "Acessaram o curso", selecionado=BELEM)
    vazios, dados, contornos = fig.data
    assert list(vazios.locations) == [ABAETETUBA] and "Sem cursistas" in vazios.hovertemplate
    assert list(dados.locations) == [BELEM] and (dados.zmin, dados.zmax) == (0.0, 1.0)
    assert "Belém (PA)" in dados.text[0] and "1 de 2 com conta" in dados.text[0]
    assert dados.marker.line.width[0] > 2  # município selecionado com contorno reforçado
    assert contornos.hoverinfo == "skip"
    # Métricas de alerta usam outra escala de cor; contagens usam o máximo observado
    alerta = mapas.figura(resumo, _geo(BELEM), _geo("15"), "Nunca acessaram")
    assert alerta.data[0].colorscale[-1][1] == mapas.ALERTA_MAX
    assert mapas.figura(resumo, _geo(BELEM), _geo("15"), "Cursistas").data[0].zmax == 3
