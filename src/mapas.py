"""Mapas por município com as malhas territoriais oficiais do IBGE.

As escolas não têm coordenadas nos microdados do Censo Escolar; por isso os mapas
mostram municípios (onde ficam as escolas dos cursistas, segundo o Inep), nunca
pontos em posições aproximadas. As malhas vêm da API de malhas do IBGE
(qualidade mínima) e ficam guardadas em ``data/referencias/malhas/``.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import pandas as pd

from . import config, graficos
from .painel import municipio_do_registro, pessoas_de

DIR_MALHAS = config.DIR_REFERENCIAS / "malhas"
URL_MALHA = "https://servicodados.ibge.gov.br/api/v3/malhas/estados/{uf}?formato=application/vnd.geo+json&qualidade=minima{extra}"

METRICAS = {
    "Acessaram o curso": ("taxa_acesso", "percentual", "Proporção das pessoas com conta que já acessaram o curso"),
    "Nunca acessaram": ("taxa_nunca", "percentual_alerta", "Proporção das pessoas com conta que nunca acessaram"),
    "Requerem acompanhamento": ("taxa_acompanhamento", "percentual_alerta", "Proporção das pessoas que requerem acompanhamento"),
    "Cursistas": ("pessoas", "contagem", "Pessoas cadastradas cuja escola fica no município"),
    "Escolas": ("escolas", "contagem", "Escolas distintas com cursistas no município"),
}
ALERTA_MIN = "#F7EEE6"
ALERTA_MAX = "#A8461F"
SEM_DADOS = "#EEF0F2"


# ---------------------------------------------------------------- malhas


def _area(anel: list) -> float:
    return sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(anel, anel[1:] + anel[:1])) / 2


def _orientar(poligono: list) -> list:
    """Anel externo no sentido horário e furos no anti-horário (convenção do d3-geo, usado pelo Plotly)."""
    resultado = []
    for i, anel in enumerate(poligono):
        horario = _area(anel) < 0
        quer_horario = i == 0
        resultado.append(anel if horario == quer_horario else list(reversed(anel)))
    return resultado


def orientar_para_plotly(geojson: dict) -> dict:
    for feicao in geojson.get("features", []):
        geo = feicao["geometry"]
        if geo["type"] == "Polygon":
            geo["coordinates"] = _orientar(geo["coordinates"])
        elif geo["type"] == "MultiPolygon":
            geo["coordinates"] = [_orientar(p) for p in geo["coordinates"]]
    return geojson


def _arquivo(nivel: str, codigo_uf: str) -> Path:
    return DIR_MALHAS / f"{nivel}_{codigo_uf}.geojson"


def baixar_malha(nivel: str, codigo_uf: str) -> dict:
    """Baixa do IBGE a malha da UF (nivel "municipios" ou "uf") e guarda cópia local."""
    import requests

    extra = "&intrarregiao=municipio" if nivel == "municipios" else ""
    resposta = requests.get(URL_MALHA.format(uf=codigo_uf, extra=extra), timeout=60,
                            headers={"User-Agent": "painel-acompanhamento-eti/1.0"})
    resposta.raise_for_status()
    dados = resposta.json()
    DIR_MALHAS.mkdir(parents=True, exist_ok=True)
    _arquivo(nivel, codigo_uf).write_text(json.dumps(dados, separators=(",", ":")), encoding="utf-8")
    return dados


@lru_cache(maxsize=8)
def malhas_das_ufs(siglas: frozenset[str]) -> tuple[dict, dict, tuple[str, ...]]:
    """Versão com cache (as malhas não mudam durante a execução)."""
    municipios, contornos, faltando = carregar_malhas(set(siglas))
    return municipios, contornos, tuple(faltando)


def carregar_malhas(siglas: set[str], baixar: bool = True) -> tuple[dict, dict, list[str]]:
    """Retorna (municípios, contornos das UFs, UFs sem malha disponível) em GeoJSON pronto para o Plotly."""
    municipios = {"type": "FeatureCollection", "features": []}
    contornos = {"type": "FeatureCollection", "features": []}
    faltando = []
    for sigla in sorted(siglas):
        codigo = config.CODIGO_DA_SIGLA.get(sigla)
        if not codigo:
            continue
        for nivel, destino in (("municipios", municipios), ("uf", contornos)):
            arquivo = _arquivo(nivel, codigo)
            try:
                dados = (json.loads(arquivo.read_text(encoding="utf-8")) if arquivo.exists()
                         else baixar_malha(nivel, codigo) if baixar else None)
            except Exception:
                dados = None
            if dados is None:
                faltando.append(sigla)
                continue
            destino["features"].extend(dados.get("features", []))
    return orientar_para_plotly(municipios), orientar_para_plotly(contornos), sorted(set(faltando))


# ---------------------------------------------------------------- dados por município


def resumo_por_municipio(cursistas: pd.DataFrame) -> pd.DataFrame:
    if cursistas.empty:
        return pd.DataFrame(columns=["codigo", "pessoas", "escolas", "com_conta", "acessaram", "nunca",
                                     "acompanhamento", "taxa_acesso", "taxa_nunca", "taxa_acompanhamento"])
    pessoas = pessoas_de(cursistas).assign(codigo=lambda d: municipio_do_registro(d))
    pessoas = pessoas.dropna(subset=["codigo"])
    com_conta = pessoas["id_conta"].notna()
    acessou = pessoas["acesso_tipo"].isin(["relativo", "absoluto"])
    resumo = pessoas.assign(
        _conta=com_conta, _acessou=com_conta & acessou, _nunca=com_conta & (pessoas["acesso_tipo"] == "nunca"),
        _acomp=pessoas["requer_acompanhamento"].astype(bool),
    ).groupby("codigo").agg(
        pessoas=("chave_pessoa", "nunique"),
        escolas=("inep", lambda s: s.dropna().nunique()),
        com_conta=("_conta", "sum"),
        acessaram=("_acessou", "sum"),
        nunca=("_nunca", "sum"),
        acompanhamento=("_acomp", "sum"),
    ).reset_index()
    base = resumo["com_conta"].where(resumo["com_conta"] > 0)
    resumo["taxa_acesso"] = resumo["acessaram"] / base
    resumo["taxa_nunca"] = resumo["nunca"] / base
    resumo["taxa_acompanhamento"] = resumo["acompanhamento"] / resumo["pessoas"]
    return resumo


def ufs_do_mapa(cursistas: pd.DataFrame, resumo: pd.DataFrame) -> frozenset[str]:
    """UFs do cadastro e UFs dos municípios das escolas (podem diferir em escolas de divisa)."""
    siglas = set(cursistas["uf"].dropna()) if not cursistas.empty else set()
    siglas |= {config.UFS[c[:2]][0] for c in resumo["codigo"] if c[:2] in config.UFS}
    return frozenset(siglas)


def nomes_municipios() -> dict[str, tuple[str, str]]:
    from .importacao import carregar_municipios

    return carregar_municipios() or {}


# ---------------------------------------------------------------- figura


def limites(geojson: dict) -> tuple[float, float, float, float] | None:
    """(lon mín., lon máx., lat mín., lat máx.) de todas as feições."""
    xs, ys = [], []

    def coletar(coordenadas):
        if coordenadas and isinstance(coordenadas[0], (int, float)):
            xs.append(coordenadas[0])
            ys.append(coordenadas[1])
        else:
            for c in coordenadas:
                coletar(c)

    for feicao in geojson.get("features", []):
        coletar(feicao["geometry"]["coordinates"])
    return (min(xs), max(xs), min(ys), max(ys)) if xs else None


def _formatar(valor, tipo: str) -> str:
    if valor is None or pd.isna(valor):
        return "—"
    if tipo.startswith("percentual"):
        return f"{valor * 100:.0f}%".replace(".", ",")
    return f"{int(valor):,}".replace(",", ".")


def _janela(municipios_geo: dict, contornos_geo: dict) -> tuple[float, float, float, float] | None:
    """Limites do enquadramento (com 1,5% de folga), em graus: (lon mín., lon máx., lat mín., lat máx.)."""
    caixa = limites(contornos_geo) or limites(municipios_geo)
    if not caixa:
        return None
    lon0, lon1, lat0, lat1 = caixa
    folga_lon, folga_lat = (lon1 - lon0) * 0.015, (lat1 - lat0) * 0.015
    return lon0 - folga_lon, lon1 + folga_lon, lat0 - folga_lat, lat1 + folga_lat


def proporcao(municipios_geo: dict, contornos_geo: dict) -> float:
    """Largura ÷ altura do enquadramento na projeção de Mercator: o contêiner do mapa usa essa proporção,
    para que o mapa ocupe a área toda em qualquer largura de tela (sem faixas vazias em cima e embaixo)."""
    import math

    janela = _janela(municipios_geo, contornos_geo)
    if not janela:
        return 1.45
    lon0, lon1, lat0, lat1 = janela
    y = lambda lat: math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))  # noqa: E731
    altura = y(lat1) - y(lat0)
    return math.radians(lon1 - lon0) / altura if altura > 0 else 1.45


def legenda_html(resumo: pd.DataFrame, metrica: str) -> str:
    """Legenda do mapa em HTML (gradiente da métrica e a cor dos municípios sem cursistas)."""
    import html

    coluna, tipo, _ = METRICAS[metrica]
    inicio, fim = ((ALERTA_MIN, ALERTA_MAX) if tipo == "percentual_alerta" else (graficos.CALOR_MIN, graficos.CALOR_MAX))
    if tipo.startswith("percentual"):
        marcas = ["0%", "50%", "100%"]
    else:
        maximo = int(resumo[coluna].max()) if not resumo.empty and resumo[coluna].notna().any() else 0
        marcas = ["0", f"{maximo:,}".replace(",", ".")]
    rotulos = "".join(f"<span>{m}</span>" for m in marcas)
    return (f'<div class="eti-legenda-mapa"><div class="eti-legenda-mapa-escala"><b>{html.escape(metrica)}</b>'
            f'<i style="background:linear-gradient(90deg, {inicio}, {fim})"></i><div>{rotulos}</div></div>'
            f'<span class="eti-legenda-mapa-vazio"><i style="background:{SEM_DADOS}"></i>Sem cursistas</span></div>')


def figura(resumo: pd.DataFrame, municipios_geo: dict, contornos_geo: dict, metrica: str,
           selecionado: str | None = None, altura: int | None = 560, escala: bool = True):
    """Mapa coroplético dos municípios: cor pela métrica escolhida; municípios sem cursistas em cinza claro.

    ``altura=None`` deixa o tamanho por conta do contêiner (``st.plotly_chart(height="stretch")``);
    ``escala=False`` tira a barra de cores do gráfico (a legenda vem de ``legenda_html``).
    """
    import plotly.graph_objects as go

    coluna, tipo, _ = METRICAS[metrica]
    nomes = nomes_municipios()
    todos = [f["properties"]["codarea"] for f in municipios_geo["features"]]
    com_dados = resumo.dropna(subset=[coluna]) if not resumo.empty else resumo
    codigos_dados = set(com_dados["codigo"]) if not com_dados.empty else set()
    vazios = [c for c in todos if c not in codigos_dados]
    fig = go.Figure()
    if vazios:
        fig.add_trace(go.Choropleth(
            geojson=municipios_geo, featureidkey="properties.codarea", locations=vazios, z=[0] * len(vazios),
            colorscale=[[0, SEM_DADOS], [1, SEM_DADOS]], showscale=False, marker_line_color="#FFFFFF",
            marker_line_width=0.5, hovertemplate="%{customdata}<br>Sem cursistas<extra></extra>",
            customdata=[f"{nomes.get(c, (c, ''))[0]} ({nomes.get(c, ('', ''))[1]})" for c in vazios],
            name="sem_dados",
        ))
    if not com_dados.empty:
        minimo, maximo = (0.0, 1.0) if tipo.startswith("percentual") else (0, float(com_dados[coluna].max() or 1))
        cores = ([[0, ALERTA_MIN], [1, ALERTA_MAX]] if tipo == "percentual_alerta"
                 else [[0, graficos.CALOR_MIN], [1, graficos.CALOR_MAX]])
        textos = []
        for linha in com_dados.itertuples(index=False):
            nome, uf = nomes.get(linha.codigo, (linha.codigo, ""))
            textos.append(
                f"<b>{nome} ({uf})</b><br>Cursistas: {_formatar(linha.pessoas, 'contagem')} · "
                f"Escolas: {_formatar(linha.escolas, 'contagem')}<br>"
                f"Acessaram o curso: {_formatar(linha.taxa_acesso, 'percentual')} "
                f"({int(linha.acessaram)} de {int(linha.com_conta)} com conta)<br>"
                f"Nunca acessaram: {_formatar(linha.taxa_nunca, 'percentual')} · "
                f"Requerem acompanhamento: {_formatar(linha.taxa_acompanhamento, 'percentual')}"
            )
        fig.add_trace(go.Choropleth(
            geojson=municipios_geo, featureidkey="properties.codarea", locations=com_dados["codigo"].tolist(),
            z=com_dados[coluna].astype(float).tolist(), zmin=minimo, zmax=maximo, colorscale=cores, showscale=escala,
            marker_line_color=["#1F2933" if c == selecionado else "#FFFFFF" for c in com_dados["codigo"]],
            marker_line_width=[2.2 if c == selecionado else 0.5 for c in com_dados["codigo"]],
            text=textos, hovertemplate="%{text}<extra></extra>", name="municipios",
            colorbar={"title": {"text": metrica, "side": "top", "font": {"size": 12, "color": graficos.TINTA_SUAVE}},
                      "orientation": "h", "x": 0.0, "xanchor": "left", "y": -0.02, "yanchor": "top",
                      "len": 0.45, "thickness": 10, "outlinewidth": 0,
                      "tickformat": ".0%" if tipo.startswith("percentual") else ",d",
                      "tickfont": {"size": 11, "color": graficos.TINTA_SUAVE}},
        ))
    if contornos_geo["features"]:
        ufs = [f["properties"]["codarea"] for f in contornos_geo["features"]]
        fig.add_trace(go.Choropleth(
            geojson=contornos_geo, featureidkey="properties.codarea", locations=ufs, z=[0] * len(ufs),
            colorscale=[[0, "rgba(0,0,0,0)"], [1, "rgba(0,0,0,0)"]], showscale=False,
            marker_line_color="#5B6670", marker_line_width=1.1, hoverinfo="skip", name="ufs",
        ))
    fig.update_geos(visible=False, projection_type="mercator", bgcolor="#FFFFFF")
    # Enquadramento pelos limites da região: com fitbounds o Plotly mantém o quadro (quadrado) do
    # mapa-múndi e a região fica pequena no meio dele.
    janela = _janela(municipios_geo, contornos_geo)
    if janela:
        lon0, lon1, lat0, lat1 = janela
        fig.update_geos(lonaxis_range=[lon0, lon1], lataxis_range=[lat0, lat1])
    if altura:
        fig.update_layout(height=altura)
    fig.update_layout(margin={"l": 0, "r": 0, "t": 0, "b": 40 if escala else 0}, paper_bgcolor="#FFFFFF",
                      font={"family": "Inter, system-ui, sans-serif", "color": graficos.TINTA}, separators=",.",
                      hoverlabel={"bgcolor": "#FFFFFF", "bordercolor": "#E4E7EB",
                                  "font": {"family": "Inter, system-ui, sans-serif", "size": 12, "color": graficos.TINTA}},
                      dragmode=False, clickmode="event+select")
    return fig
