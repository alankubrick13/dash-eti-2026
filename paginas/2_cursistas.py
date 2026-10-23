"""Cursistas: galeria de pessoas por situação na formação; cada cartão abre a ficha em gaveta lateral."""

import streamlit as st

from src import cartoes, fichas, graficos, mapas, metrics, painel, ui
from src import reconciliation as rc
from src.normalization import chave_comparacao

ctx = painel.contexto()
base = ctx.base
ui.titulo_pagina(
    "Cursistas",
    "Quem participa da formação e como está a participação de cada pessoa. Escolha um grupo, procure pelo nome "
    "e clique em um cartão para abrir a ficha. Não são exibidos CPF, data de nascimento nem contatos.",
)
ui.recorte(ctx)
if not base.tem_cadastro:
    ui.faltam_arquivos(ctx.cfg, "cadastro")
    st.stop()

pessoas = painel.pessoas_de(ctx.cursistas)
cores = graficos.cores_faixas(painel.ordem_faixas(base.parametros["faixas_inatividade_dias"]))
janela = base.parametros["janela_acesso_recente_dias"]
limite = base.parametros["limite_acompanhamento_dias"]
pendente = pessoas["status_conciliacao"].isin([rc.PENDENTE, rc.AMBIGUO])

# ---------------------------------------------------------------- grupos (cartões de filtro)
grupos = {painel.GRUPO_TODAS: (pessoas["chave_pessoa"].notna(), graficos.TINTA)}
if base.tem_atividade:
    grupos |= {
        painel.GRUPO_ACOMPANHAMENTO: (pessoas["requer_acompanhamento"].astype(bool), mapas.ALERTA_MAX),
        painel.grupo_recentes(janela): (pessoas["dias_sem_acesso"].fillna(10**9) <= janela, graficos.PETROLEO[0]),
        painel.grupo_inativos(limite): (pessoas["dias_sem_acesso"].fillna(-1) > limite, graficos.PETROLEO[3]),
        painel.GRUPO_NUNCA: (pessoas["acesso_tipo"] == "nunca", graficos.CINZA_NUNCA),
        painel.GRUPO_SEM_CONTA: ((pessoas["faixa_acesso"] == painel.FAIXA_SEM_CONTA) & ~pendente, "#9AA5B1"),
        painel.GRUPO_CONCILIACAO: (pendente, "#D9A441"),
    }
escolha = ui.filtros_em_cartoes([(r, int(m.sum()), cor) for r, (m, cor) in grupos.items()], len(pessoas), "cursistas")

busca, ordem_col = ui.colunas([3, 1.4], "busca_cursistas", gap="small", vertical_alignment="bottom")
termo = busca.text_input("Buscar", placeholder="Buscar por nome, escola, município ou turma", key="cursistas_busca",
                         label_visibility="collapsed", icon=":material/search:")
ORDENACOES = {
    "Atenção primeiro": (["prioridade", "dias_sem_acesso", "nome_chave"], [True, False, True]),
    "Nome (A–Z)": (["nome_chave"], [True]),
    "Maior tempo sem acesso": (["dias_sem_acesso", "nome_chave"], [False, True]),
    "Escola (A–Z)": (["escola", "nome_chave"], [True, True]),
}
ordem = ordem_col.selectbox("Ordenar", list(ORDENACOES), key="cursistas_ordem", label_visibility="collapsed")

vista = pessoas[grupos[escolha][0]]
if termo:
    chave = chave_comparacao(termo) or ""
    vista = vista[vista["texto_busca"].str.contains(chave, regex=False, na=False)]
colunas_ordem, ascendente = ORDENACOES[ordem]
vista = vista.sort_values(colunas_ordem, ascending=ascendente, na_position="last", kind="stable")

# Recomeça do início da galeria quando o grupo, a busca, a ordem ou os filtros mudam
assinatura = (escolha, termo, ordem, tuple(sorted((k, tuple(v)) for k, v in ctx.filtros.items())))
if st.session_state.get("_cursistas_assinatura") != assinatura:
    st.session_state["_cursistas_assinatura"] = assinatura
    st.session_state["cursistas_limite"] = None
mostrados = ui.mais_itens(len(vista), "cursistas")

ui.nota(f"{metrics.numero(len(vista))} pessoa(s) em “{escolha}”" + (f" com “{termo}”" if termo else "")
        + f". Mostrando {metrics.numero(mostrados)}."
        + (" O tempo sem acesso é medido na data de referência da base de atividade." if base.tem_atividade else ""))
if vista.empty:
    ui.vazio("Ninguém corresponde ao grupo e à busca escolhidos.")
else:
    def desenhar(i, pessoa) -> None:
        ui.clicavel(cartoes.cartao_pessoa(pessoa, cores), f"pessoa_{i}",
                    f"Abrir a ficha de {cartoes.nome_legivel(pessoa.nome)}", fichas.pedir,
                    ("cursista", pessoa.id_registro))

    ui.grade(list(vista.head(mostrados).itertuples(index=False)), desenhar, "cursistas")
    ui.botao_mais(mostrados, len(vista), "cursistas", unidade="pessoas")
