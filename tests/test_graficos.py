"""Gráficos em HTML (histograma do último acesso e barras em blocos), montados com os dados reais."""

import re

import pandas as pd
import pytest

from src import graficos, painel, ui
from src import reconciliation as rc


def _numeros(html: str, classe: str) -> list[int]:
    return [int(v.replace(".", "")) for v in re.findall(rf'class="{classe}">([\d.]+)<', html)]


def test_histograma_do_ultimo_acesso_real(base_real):
    if not base_real.tem_atividade:
        pytest.skip("base de atividade não importada")
    parametros = base_real.parametros
    janela, limite = parametros["janela_acesso_recente_dias"], parametros["limite_acompanhamento_dias"]
    contas = base_real.contas[base_real.contas["eh_cursista"] == 1]
    nunca = int((contas["acesso_tipo"] == "nunca").sum())
    fig = ui.histograma_acesso(contas["dias_sem_acesso"], nunca, base_real, "America/Sao_Paulo", "contas")
    classes = painel.classes_de_dias(contas["dias_sem_acesso"], parametros["faixas_inatividade_dias"], (janela, limite))
    # Uma coluna por classe e a coluna "Nunca"; o número escrito em cada coluna é a contagem
    assert fig.corpo.count('class="viz-hist-col') == len(classes) + 1
    assert _numeros(fig.corpo, "viz-hist-valor") == [*classes["contagem"].tolist(), nunca]
    marcas = re.findall(r'viz-hist-marca-texto">([^<]+)<', fig.corpo)
    assert len(marcas) == len({janela, limite})
    if (base_real.meta.get("atividade") or {}).get("referencia_em"):
        assert all(re.search(r"\d{2}/\d{2}$", m) for m in marcas)  # com a data da lista, a data de cada marca
    # Legenda: o total de cada faixa (as faixas com tempo somam quem tem acesso)
    totais = [int(re.sub(r"\D", "", nome.split(":")[-1])) for nome, _ in fig.legenda]
    assert sum(totais) == int(contas["dias_sem_acesso"].notna().sum()) + nunca


def test_barras_em_blocos_com_o_total_de_cada_linha(base_real):
    pessoas = painel.pessoas_de(base_real.cursistas)
    ordem = painel.ordem_faixas(base_real.parametros["faixas_inatividade_dias"])
    linhas, grupos, series = [], [], {f: [] for f in ordem}
    for nome, coluna in [d for d in painel.DIMENSOES_PERFIL if d[1] in ("cargo_funcao", "origem")]:
        cruz = pd.crosstab(pessoas[coluna].fillna("Não informado"), pessoas["faixa_acesso"]).reindex(columns=ordem, fill_value=0)
        for valor in cruz.index:
            linhas.append(valor)
            grupos.append(nome)
            for f in ordem:
                series[f].append(int(cruz.loc[valor, f]))
    series = {f: v for f, v in series.items() if any(v)}
    fig = graficos.barras_empilhadas_100(linhas, series, graficos.cores_faixas(ordem), "Perfil", grupos=grupos,
                                         mostrar_total=True)
    assert fig.corpo.count('class="viz-grupo"') == len(set(grupos))
    assert _numeros(fig.corpo, "viz-n") == [sum(v[i] for v in series.values()) for i in range(len(linhas))]
    assert sum(_numeros(fig.corpo, "viz-n")) == 2 * len(pessoas)  # cada pessoa aparece uma vez em cada bloco


def test_textos_dos_graficos_escapados(base_real):
    escola = base_real.cursistas["escola"].dropna().iloc[0]
    rotulo = f"{escola} <b>"
    fig = graficos.histograma([{"rotulo": rotulo, "valor": 1, "cor": graficos.COR_SERIE, "dica": rotulo,
                                "marca": rotulo}], rotulo)
    assert "<b>" not in fig.corpo and "&lt;b&gt;" in fig.corpo
    fig = graficos.barras_empilhadas_100([rotulo], {"x": [1]}, {"x": graficos.COR_SERIE}, "t", grupos=[rotulo])
    assert "<b>" not in fig.corpo


def test_proporcao_do_mapa_segue_o_enquadramento():
    """Mapa da região: largura ÷ altura na projeção de Mercator, a partir das malhas oficiais do IBGE (em cache)."""
    from src import mapas

    ufs = frozenset({"PA", "AM"})
    municipios_geo, contornos_geo, faltando = mapas.malhas_das_ufs(ufs)
    if faltando or not contornos_geo["features"]:
        pytest.skip("malhas do IBGE indisponíveis")
    proporcao = mapas.proporcao(municipios_geo, contornos_geo)
    lon0, lon1, lat0, lat1 = mapas._janela(municipios_geo, contornos_geo)
    assert 0.5 < proporcao < 4 and proporcao > (lon1 - lon0) / (lat1 - lat0) * 0.9  # Mercator alonga pouco perto do equador
    legenda = mapas.legenda_html(pd.DataFrame(), "Acessaram o curso")
    assert "100%" in legenda and "Sem cursistas" in legenda


def test_comparacao_por_contexto_da_escola_soma_as_pessoas(base_real):
    if not (base_real.tem_atividade and base_real.tem_escolas):
        pytest.skip("base de atividade ou escolar não importada")
    pessoas = painel.pessoas_de(base_real.cursistas)
    com_conta = pessoas[pessoas["status_conciliacao"] == rc.CORRESPONDENTE]
    for _, coluna in painel.DIMENSOES_ESCOLA:
        contagem = com_conta[coluna].fillna("Escola sem dados do Inep").value_counts()
        assert contagem.sum() == len(com_conta), coluna
