"""Mapa e território: cursistas por município (malhas oficiais do IBGE), UFs, entes e turmas."""

import html

import pandas as pd
import streamlit as st

from src import cartoes, config, fichas, graficos, mapas, metrics, painel, ui
from src import reconciliation as rc
from src.normalization import chave_comparacao

ctx = painel.contexto()
base = ctx.base
ui.titulo_pagina(
    "Mapa e território",
    "Onde estão as escolas dos cursistas e como está o acesso ao curso em cada município. Clique em um município "
    "no mapa (ou escolha na lista) para ver as suas escolas.",
)
ui.recorte(ctx)
if not base.tem_cadastro:
    ui.faltam_arquivos(ctx.cfg, "cadastro")
    st.stop()

cursistas = ctx.cursistas
pessoas = painel.pessoas_de(cursistas)
resumo = mapas.resumo_por_municipio(cursistas)
nomes = mapas.nomes_municipios()
ufs = mapas.ufs_do_mapa(pessoas, resumo)
municipios_geo, contornos_geo, faltando = mapas.malhas_das_ufs(ufs)
sem_municipio = int(painel.municipio_do_registro(pessoas).isna().sum())

r = metrics.calcular(cursistas, ctx.contas, base, base.parametros)
com_acesso = resumo.dropna(subset=["taxa_acesso"]) if not resumo.empty else resumo
melhor = (com_acesso["taxa_acesso"] >= 0.9).sum() if not com_acesso.empty else 0
numeros_territorio = [
    ("Municípios com cursistas", metrics.numero(len(resumo)), f"em {len(ufs)} UF(s)",
     "Municípios onde ficam as escolas dos cursistas (segundo o Inep) ou, sem escola localizada, o município do ente."),
    (r["entes_representados"].indicador.nome, metrics.valor_formatado(r["entes_representados"]),
     metrics.contexto_formatado(r["entes_representados"]), metrics.ajuda(r["entes_representados"].indicador)),
    ("Municípios com 90% ou mais de acesso", metrics.numero(melhor),
     f"de {metrics.numero(len(com_acesso))} com cursistas com conta",
     "Municípios em que ao menos 90% das pessoas com conta já acessaram o curso."),
    ("Pessoas sem município identificado", metrics.numero(sem_municipio), f"de {metrics.numero(len(pessoas))} pessoas",
     "Sem escola localizada na base do Inep e sem código IBGE municipal no cadastro (ex.: entes estaduais com escola "
     "não localizada). Não aparecem no mapa."),
]
with st.container(key="kpis_territorio"):
    colunas_kpi = st.columns(4)
for i, (coluna_kpi, (rotulo_kpi, valor, contexto, ajuda)) in enumerate(zip(colunas_kpi, numeros_territorio)):
    with coluna_kpi, st.container(border=True, key=f"kpi_territorio_{i}"):
        st.metric(rotulo_kpi, valor, help=ajuda)
        st.html(f'<p class="eti-metrica-contexto">{html.escape(contexto)}</p>')

# ---------------------------------------------------------------- mapa
ui.secao("Mapa dos municípios")
opcoes = list(mapas.METRICAS) if base.tem_atividade else ["Cursistas", "Escolas"]
metrica = st.segmented_control("Colorir o mapa por", opcoes, default=opcoes[0], key="mapa_metrica") or opcoes[0]
if faltando:
    st.warning(f"Malha municipal indisponível para: {', '.join(faltando)} (sem conexão com o IBGE).")

codigos = sorted(resumo["codigo"], key=lambda c: chave_comparacao(nomes.get(c, (c, ""))[0]) or c)
rotulo_municipio = {c: f"{nomes.get(c, (c, ''))[0]} ({nomes.get(c, ('', ''))[1]})" for c in codigos}

esquerda, direita = ui.colunas([2, 1], "mapa_municipio")
with esquerda:
    _, _, descricao = mapas.METRICAS[metrica]
    ui.cabecalho_grafico(f"{metrica}, por município", f"{descricao}. Municípios em cinza não têm cursistas.",
                         ui.chamada(base))
    fig = mapas.figura(resumo, municipios_geo, contornos_geo, metrica, st.session_state.get("municipio_sel"),
                       altura=None, escala=False)
    # O contêiner tem a proporção do enquadramento: o mapa ocupa a área toda em qualquer largura de tela
    st.html(f"<style>.st-key-mapa_territorio {{ --proporcao-mapa: {mapas.proporcao(municipios_geo, contornos_geo):.3f}; }}"
            "</style>")
    with st.container(key="mapa_territorio"):
        evento = st.plotly_chart(fig, theme=None, config=graficos.CONFIG, width="stretch", height="stretch",
                                 key="mapa_municipios", on_select="rerun", selection_mode="points")
    st.html(mapas.legenda_html(resumo, metrica))
    clicados = tuple(p.get("location") for p in (evento.selection.points if evento else []) if p.get("location") in rotulo_municipio)
    if clicados and clicados != st.session_state.get("_mapa_clique_processado"):
        st.session_state["_mapa_clique_processado"] = clicados
        st.session_state["municipio_sel"] = clicados[0]
        # A lista de municípios ainda não foi desenhada nesta execução: pode receber o valor clicado
        st.session_state["mapa_municipio_escolha"] = clicados[0]
        st.rerun()
    ui.nota("Malhas municipais: IBGE (API de malhas territoriais, qualidade mínima). O município é o da escola segundo "
            f"o Inep ou, sem escola localizada, o do ente. {ui.fonte_atividade(base, ctx.cfg.fuso_horario) if base.tem_atividade else ''}")

atual = st.session_state.get("municipio_sel")


def _selecionar_municipio(codigo: str | None) -> None:
    st.session_state["municipio_sel"] = codigo
    st.session_state["mapa_municipio_escolha"] = codigo


with direita:
    def _ao_escolher_municipio() -> None:
        st.session_state["municipio_sel"] = st.session_state.get("mapa_municipio_escolha")

    if "mapa_municipio_escolha" not in st.session_state and atual in codigos:
        st.session_state["mapa_municipio_escolha"] = atual
    st.selectbox("Município", codigos, index=None, format_func=rotulo_municipio.get, placeholder="Escolha ou clique no mapa",
                 key="mapa_municipio_escolha", on_change=_ao_escolher_municipio)
    if atual in rotulo_municipio:
        dados = resumo[resumo["codigo"] == atual].iloc[0]
        st.html(f'<div class="eti-ficha-cabecalho eti-ficha-compacta"><div class="eti-ficha-titulo">'
                f'{html.escape(rotulo_municipio[atual])}</div></div>')
        st.html(cartoes.numeros(
            [("Cursistas", metrics.numero(dados["pessoas"]), None), ("Escolas", metrics.numero(dados["escolas"]), None)]
            + ([("Acessaram o curso", metrics.percentual(dados["taxa_acesso"], 0),
                 f"{metrics.numero(dados['acessaram'])} de {metrics.numero(dados['com_conta'])} com conta"),
                ("Nunca acessaram", metrics.numero(dados["nunca"]), None)]
               if base.tem_atividade and dados["com_conta"] else [])
        ))
        ui.nota("As escolas do município estão logo abaixo do mapa.")
        st.button("Ver a lista de municípios", icon=":material/format_list_bulleted:", type="tertiary",
                  on_click=_selecionar_municipio, args=(None,), key="mapa_limpar")
    else:
        # Sem município escolhido: a lista dos que pedem atenção (o clique escolhe o município no mapa)
        st.html('<div class="viz-titulo">Municípios que pedem atenção</div>'
                '<p class="viz-sub">Mais pessoas com conta que nunca acessaram primeiro. Clique para ver no mapa.</p>')
        ranking = resumo.assign(nome=resumo["codigo"].map(lambda c: rotulo_municipio.get(c, c)))
        ranking = ranking.sort_values(["nunca", "taxa_acesso", "pessoas"], ascending=[False, True, False],
                                      na_position="last", kind="stable")
        mostrados = ui.mais_itens(len(ranking), "municipios", passo=8)
        with st.container(key="lista_municipios"):
            for i, linha in enumerate(ranking.head(mostrados).itertuples(index=False)):
                ui.clicavel(cartoes.linha_municipio(linha.nome, linha), f"municipio_{i}", f"Ver {linha.nome} no mapa",
                            _selecionar_municipio, (linha.codigo,))
        ui.botao_mais(mostrados, len(ranking), "municipios", passo=8, unidade="municípios", centralizado=False)

# ---------------------------------------------------------------- escolas do município selecionado
if atual in rotulo_municipio:
    escolas_mun = painel.resumo_escolas(cursistas)
    escolas_mun = (escolas_mun[escolas_mun["cod_municipio"] == atual]
                   .sort_values(["pessoas", "escola"], ascending=[False, True]))
    ui.secao(f"Escolas de {rotulo_municipio[atual]}",
             "Cada ponto é uma pessoa, na cor da sua situação de acesso. Clique em uma escola para ver os dados "
             "oficiais do Inep e quem dela participa da formação.")
    cores = graficos.cores_faixas(painel.ordem_faixas(base.parametros["faixas_inatividade_dias"]))
    dados_mun = cursistas.assign(_chave=painel.chave_escola(cursistas)).drop_duplicates(["_chave", "chave_pessoa"])
    faixas_por_escola = dados_mun.groupby("_chave")["faixa_acesso"].agg(list).to_dict()

    def desenhar(i, escola) -> None:
        ui.clicavel(cartoes.cartao_escola(escola, faixas_por_escola.get(escola.chave_escola, []), cores, com_local=False),
                    f"mapa_escola_{i}", f"Abrir a ficha da escola {cartoes.nome_legivel(escola.escola)}", fichas.pedir,
                    ("escola", escola.chave_escola))

    ui.grade(list(escolas_mun.itertuples(index=False)), desenhar, "mapa_escolas")

# ---------------------------------------------------------------- UFs e entes
ui.secao("Distribuição territorial")
esquerda, direita = ui.colunas(2, "territorio_distribuicao")
with esquerda:
    por_uf = pessoas["uf"].map(lambda s: config.NOME_DA_SIGLA.get(s, s) if isinstance(s, str) else "UF não informada").value_counts()
    total = int(por_uf.sum())
    fig = graficos.barras_horizontais(
        por_uf.index.tolist(), por_uf.tolist(), "Pessoas cadastradas por estado", f"Total de {metrics.numero(total)} pessoas",
        rotulos=[f"{metrics.numero(v)} ({metrics.percentual(v / total)})" for v in por_uf],
    )
    ui.grafico(fig, por_uf.rename_axis("Estado").reset_index(name="Pessoas"), "territorio_uf",
               fonte=ui.fonte_cadastro(base, ctx.cfg.fuso_horario))
with direita:
    por_ente = pessoas.groupby(["ente", "uf"], dropna=False).size().sort_values(ascending=False)
    topo = por_ente.head(12)
    fig = graficos.barras_horizontais(
        [f"{e or 'Ente não informado'} ({u or '—'})" for e, u in topo.index], topo.tolist(),
        "Entes com mais pessoas cadastradas", f"12 maiores de {metrics.numero(len(por_ente))} entes no recorte",
        rotulos=[metrics.numero(v) for v in topo],
    )
    ui.grafico(fig, None, "territorio_entes", fonte=ui.fonte_cadastro(base, ctx.cfg.fuso_horario))

# ---------------------------------------------------------------- turmas x UF do cadastro
if base.tem_atividade:
    ui.secao("Turmas e estados de origem",
             "As turmas da plataforma têm nome de estado, mas reúnem cursistas de vários estados.")
    com_conta = pessoas[pessoas["status_conciliacao"] == rc.CORRESPONDENTE]
    linhas = []
    for pessoa in com_conta.itertuples(index=False):
        for grupo in pessoa.lista_grupos:
            identificada = painel.turma(grupo)
            linhas.append({"turma": identificada[0] if identificada else "Sem turma identificada",
                           "uf": pessoa.uf if isinstance(pessoa.uf, str) else "Sem UF"})
    if not linhas:
        ui.vazio("Nenhuma pessoa com conta encontrada no recorte.")
    else:
        dados = pd.DataFrame(linhas)
        cruz = pd.crosstab(dados["turma"], dados["uf"])
        cruz = cruz.loc[sorted(cruz.index, key=chave_comparacao)]
        cruz = cruz[sorted(cruz.columns, key=lambda uf: (uf == "Sem UF", uf))]
        valores = [[int(v) if v else None for v in linha] for linha in cruz.values.tolist()]
        fig = graficos.mapa_calor(cruz.index.tolist(), cruz.columns.tolist(), valores,
                                  "De onde vêm os cursistas de cada turma",
                                  "Linhas: estado no nome da turma. Colunas: sigla da UF do cursista no cadastro. "
                                  "Contagem de pessoas")
        ui.grafico(fig, cruz.rename_axis("Turma (estado)").reset_index(), "turmas_uf",
                   "“—” indica nenhuma pessoa. Uma pessoa em duas turmas conta nas duas.",
                   ui.fonte_atividade(base, ctx.cfg.fuso_horario), ui.chamada(base))
