"""Escolas: galeria das escolas dos cursistas; cada cartão abre a ficha da escola em gaveta lateral."""

import pandas as pd
import streamlit as st

from src import cartoes, fichas, graficos, mapas, metrics, painel, school_data, ui
from src.normalization import chave_comparacao

ctx = painel.contexto()
base = ctx.base
ui.titulo_pagina(
    "Escolas",
    "As escolas dos cursistas e a participação de cada uma na formação. Cada ponto de um cartão é uma pessoa, na cor "
    "da sua situação de acesso. Clique em uma escola para ver os dados oficiais do Inep e quem dela participa.",
)
ui.recorte(ctx)
if not base.tem_cadastro:
    ui.vazio("O cadastro de cursistas ainda não foi importado.")
    st.stop()

escolas = painel.resumo_escolas(ctx.cursistas)
fonte_escolas = ui.fonte_escolas(base)
cores = graficos.cores_faixas(painel.ordem_faixas(base.parametros["faixas_inatividade_dias"]))

r = metrics.calcular_escolas(escolas, base.atributos_escolas, base.tem_atividade)
geral = metrics.calcular(ctx.cursistas, ctx.contas, base, base.parametros)
ui.indicadores([r["escolas_com_cursistas"], geral["escolas_localizadas"], r["escolas_tempo_integral"],
                r["escolas_sem_acesso"]])

# Um item por pessoa em cada escola: a cor de cada ponto do cartão
dados = ctx.cursistas.assign(_chave=painel.chave_escola(ctx.cursistas)).drop_duplicates(["_chave", "chave_pessoa"])
faixas_por_escola = dados.groupby("_chave")["faixa_acesso"].agg(list).to_dict()
escolas["situacao"] = [cartoes.situacao_escola(c, a) for c, a in zip(escolas["com_conta"], escolas["acessaram"])]

# ---------------------------------------------------------------- galeria
st.divider()
opcoes = [("Todas as escolas", len(escolas), graficos.TINTA)]
if base.tem_atividade:
    cor_situacao = dict(zip(cartoes.SITUACOES_ESCOLA, (graficos.PETROLEO[0], graficos.PETROLEO[2], mapas.ALERTA_MAX, "#9AA5B1")))
    opcoes += [(s, int((escolas["situacao"] == s).sum()), cor_situacao[s]) for s in cartoes.SITUACOES_ESCOLA]
escolha = ui.filtros_em_cartoes(opcoes, len(escolas), "escolas")

busca, ordem_col = ui.colunas([3, 1.4], "busca_escolas", gap="small", vertical_alignment="bottom")
termo = busca.text_input("Buscar escola", placeholder="Buscar por nome da escola, município ou código INEP",
                         key="escolas_busca", label_visibility="collapsed", icon=":material/search:")
ORDENACOES = {
    "Atenção primeiro": (["acompanhamento", "nunca", "taxa_acesso", "escola"], [False, False, True, True]),
    "Mais cursistas": (["pessoas", "escola"], [False, True]),
    "Menor taxa de acesso": (["taxa_acesso", "pessoas"], [True, False]),
    "Nome (A–Z)": (["escola"], [True]),
    "Município (A–Z)": (["municipio", "escola"], [True, True]),
}
ordem = ordem_col.selectbox("Ordenar", list(ORDENACOES), key="escolas_ordem", label_visibility="collapsed")

vista = escolas if escolha == "Todas as escolas" else escolas[escolas["situacao"] == escolha]
if termo:
    chave = chave_comparacao(termo) or ""
    texto = (vista["escola"].map(chave_comparacao).fillna("") + " " + vista["escola_informada"].map(chave_comparacao).fillna("")
             + " " + vista["municipio"].map(chave_comparacao).fillna("") + " " + vista["inep"].fillna(""))
    vista = vista[texto.str.contains(chave, regex=False)]
colunas_ordem, ascendente = ORDENACOES[ordem]
vista = vista.sort_values(colunas_ordem, ascending=ascendente, na_position="last", kind="stable")

assinatura = (escolha, termo, ordem, tuple(sorted((k, tuple(v)) for k, v in ctx.filtros.items())))
if st.session_state.get("_escolas_assinatura") != assinatura:
    st.session_state["_escolas_assinatura"] = assinatura
    st.session_state["escolas_limite"] = None
mostrados = ui.mais_itens(len(vista), "escolas")

ui.nota(f"{metrics.numero(len(vista))} escola(s) em “{escolha}”" + (f" com “{termo}”" if termo else "")
        + f". Mostrando {metrics.numero(mostrados)}.")
if vista.empty:
    ui.vazio("Nenhuma escola corresponde ao grupo e à busca escolhidos.")
else:
    legenda = "".join(f'<span><i style="background:{cor}"></i>{f}</span>' for f, cor in cores.items()
                      if f in set(dados["faixa_acesso"].dropna()))
    st.html(f'<div class="viz-legenda eti-legenda-pontos">{legenda}</div>')

    def desenhar(i, escola) -> None:
        ui.clicavel(cartoes.cartao_escola(escola, faixas_por_escola.get(escola.chave_escola, []), cores),
                    f"escola_{i}", f"Abrir a ficha da escola {cartoes.nome_legivel(escola.escola)}", fichas.pedir,
                    ("escola", escola.chave_escola))

    ui.grade(list(vista.head(mostrados).itertuples(index=False)), desenhar, "escolas")
    ui.botao_mais(mostrados, len(vista), "escolas", unidade="escolas")

# ---------------------------------------------------------------- panorama no Censo
ui.secao("Panorama das escolas no Censo Escolar",
         "Características oficiais das escolas do recorte que foram localizadas na base do Inep.")
if not base.tem_escolas:
    ui.vazio("A base escolar oficial ainda não foi carregada. Um administrador pode baixá-la ou importá-la na Administração.")
else:
    localizadas = ctx.cursistas[ctx.cursistas["situacao_inep"] == school_data.SITUACAO_INEP_LOCALIZADO].drop_duplicates("inep")
    atributos = base.atributos_escolas
    atributos = atributos[atributos["co_entidade"].isin(localizadas["inep"])] if not atributos.empty else atributos
    n_escolas = len(localizadas)

    disponiveis = [v for v in school_data.VARIAVEIS_INT_TOTAL if not atributos.empty and v in atributos]
    if disponiveis:
        numeros = atributos[disponiveis].apply(pd.to_numeric, errors="coerce").fillna(0)
        total_int = int(numeros.sum().sum())
        basica = (pd.to_numeric(atributos["QT_MAT_BAS"], errors="coerce").fillna(0).sum()
                  if "QT_MAT_BAS" in atributos else None)
        st.html(cartoes.numeros([
            ("Escolas localizadas no Censo", metrics.numero(n_escolas),
             f"Censo Escolar {(base.meta.get('escolas') or {}).get('referencia_em')}"),
            ("Com alguma matrícula em tempo integral", metrics.numero(int((numeros.sum(axis=1) > 0).sum())),
             f"de {metrics.numero(len(atributos))} escolas localizadas"),
            ("Matrículas em tempo integral", metrics.numero(total_int),
             f"{metrics.percentual(total_int / basica)} das {metrics.numero(basica)} da educação básica" if basica else None),
        ]))
        ui.nota(f"{school_data.DEFINICAO_TEMPO_INTEGRAL} {school_data.AVISO_PROGRAMA}")

    def barras_escolas(coluna: str, titulo: str, chave: str) -> None:
        contagem = localizadas[coluna].fillna("Não informado na fonte").value_counts()
        if contagem.empty:
            return
        fig = graficos.barras_horizontais(
            contagem.index.tolist(), contagem.tolist(), titulo, f"Escolas distintas ({metrics.numero(n_escolas)})",
            rotulos=[f"{metrics.numero(v)} ({metrics.percentual(v / n_escolas)})" for v in contagem],
        )
        ui.grafico(fig, contagem.rename_axis(titulo).reset_index(name="Escolas"), chave)

    def percentuais(variaveis, titulo: str, chave: str, nota_texto: str | None = None) -> None:
        linhas = []
        for var, rotulo in variaveis:
            if atributos.empty or var not in atributos:
                continue
            valores = atributos[var]
            linhas.append({"Item": rotulo, "Escolas": int((valores == "1").sum()), "proporcao": float((valores == "1").mean())})
        if not linhas:
            ui.vazio(f"{titulo}: variáveis indisponíveis na base escolar carregada.")
            return
        tab = pd.DataFrame(linhas).sort_values("proporcao", ascending=False)
        fig = graficos.barras_horizontais(
            tab["Item"].tolist(), tab["proporcao"].tolist(), titulo,
            f"Proporção das escolas localizadas ({metrics.numero(len(atributos))})",
            rotulos=[metrics.percentual(v, 0) for v in tab["proporcao"]], eixo_percentual=True,
        )
        ui.grafico(fig, tab.rename(columns={"proporcao": "Proporção"}), chave, nota_texto)

    col1, col2 = ui.colunas(2, "perfil_etapas_infra")
    with col1:
        percentuais(school_data.ETAPAS, "Etapas e modalidades ofertadas", "esc_etapas",
                    "Escola com ao menos uma matrícula na etapa ou modalidade, segundo o Censo.")
    with col2:
        percentuais(school_data.INFRAESTRUTURA, "Infraestrutura declarada ao Censo", "esc_infra",
                    "Banda larga: escolas sem internet aparecem como “não”.")
    col1, col2 = ui.colunas(2, "perfil_escolas")
    with col1:
        barras_escolas("dependencia", "Dependência administrativa", "esc_dependencia")
        barras_escolas("localizacao_diferenciada", "Localização diferenciada", "esc_loc_dif")
    with col2:
        barras_escolas("localizacao", "Localização", "esc_localizacao")
        barras_escolas("situacao_funcionamento", "Situação de funcionamento", "esc_funcionamento")

# ---------------------------------------------------------------- qualidade dos códigos
ui.secao("Códigos INEP do cadastro")
situacao = ctx.cursistas["situacao_inep"].value_counts().reindex(school_data.ORDEM_SITUACAO_INEP).dropna()
situacao = situacao[situacao > 0]
total_reg = int(situacao.sum())
fig = graficos.barras_horizontais(
    situacao.index.tolist(), situacao.astype(int).tolist(), "Situação dos códigos INEP do cadastro",
    f"Registros de inscrição ({metrics.numero(total_reg)}); associação sempre pelo código, nunca pelo nome da escola",
    rotulos=[f"{metrics.numero(v)} ({metrics.percentual(v / total_reg)})" for v in situacao],
)
ui.grafico(fig, situacao.rename_axis("Situação").reset_index(name="Registros"), "escolas_situacao_inep", fonte=fonte_escolas)
st.page_link("paginas/6_qualidade_conciliacao.py", label="Ver os registros com código ausente, inválido ou não localizado",
             icon=":material/fact_check:")
