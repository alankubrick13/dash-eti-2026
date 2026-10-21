"""Atividade e participação na plataforma de formação."""

import pandas as pd
import streamlit as st

from src import graficos, metrics, painel, ui
from src import reconciliation as rc
from src.normalization import chave_comparacao
from src.security import mascarar_email

ctx = painel.contexto()
base = ctx.base
ui.titulo_pagina(
    "Atividade e participação",
    "Uso da plataforma segundo a exportação de participantes. Situação da conta e atividade são coisas "
    "diferentes: uma conta ativa pode estar sem acesso há semanas.",
)
ui.recorte(ctx)
if not base.tem_atividade:
    ui.vazio("A base de atividade ainda não foi importada.")
    st.stop()

meta = base.meta["atividade"]
ui.nota(
    f"Referência: {meta.get('referencia_descricao')} O último acesso ao curso não informa frequência, "
    "conclusão de atividades nem desempenho."
)
limites = base.parametros["faixas_inatividade_dias"]
ordem_faixas = painel.ordem_faixas(limites)[:-1]  # contas sempre existem: sem a faixa "sem conta"
cores = graficos.cores_faixas(painel.ordem_faixas(limites))
fonte = ui.fonte_atividade(base, ctx.cfg.fuso_horario)

papeis_por_conta = ctx.contas["papeis"].fillna("Sem papel").map(lambda p: [x.strip() for x in p.split(",") if x.strip()])
papeis = sorted({p for lista in papeis_por_conta for p in lista})
padrao = [p for p in papeis if chave_comparacao(p) in {chave_comparacao(x) for x in base.parametros["papeis_cursista"]}]
papel_sel = st.multiselect("Papéis na plataforma", papeis, default=padrao or papeis, key="atividade_papeis",
                           help="Por padrão, apenas os papéis definidos como de cursista nos parâmetros operacionais.")
contas = ctx.contas[papeis_por_conta.map(lambda lista: bool(set(lista) & set(papel_sel)))] if papel_sel else ctx.contas.iloc[0:0]

r = metrics.calcular_contas(contas, base.parametros["janela_acesso_recente_dias"])
ui.indicadores([r["contas_recorte"], r["pct_situacao_ativa"], r["pct_com_acesso"], r["pct_acesso_recente_contas"], r["contas_nunca"]], colunas=5)
if contas.empty:
    st.stop()

esquerda, direita = ui.colunas([3, 2], "atividade_principal")
with esquerda:
    contagem = contas["faixa_acesso"].value_counts().reindex(ordem_faixas).dropna()
    contagem = contagem[contagem > 0]
    total = int(contagem.sum())
    fig = graficos.barras_horizontais(
        contagem.index.tolist(), contagem.astype(int).tolist(), "Tempo desde o último acesso ao curso",
        f"Contas no recorte ({metrics.numero(total)}), na data de referência da base de atividade",
        rotulos=[f"{metrics.numero(v)} ({metrics.percentual(v / total)})" for v in contagem],
        cores=[cores[f] for f in contagem.index],
    )
    ui.grafico(fig, contagem.rename_axis("Faixa").reset_index(name="Contas"), "atividade_faixas", fonte=fonte)
with direita:
    situacoes = contas["situacao_conta"].fillna("Não informada").value_counts()
    fig = graficos.barras_horizontais(
        situacoes.index.tolist(), situacoes.tolist(), "Situação das contas na plataforma",
        "Situação da inscrição no curso, como exportada",
        rotulos=[metrics.numero(v) for v in situacoes],
    )
    ui.grafico(fig, situacoes.rename_axis("Situação").reset_index(name="Contas"), "atividade_situacao", fonte=fonte)

ui.secao("Comparação entre grupos e territórios",
         "Composição do tempo desde o último acesso. Contas sem vínculo no cadastro aparecem como tal "
         "nas comparações territoriais.")
DIMENSOES = {"Estado da turma": "estado_turma", "Turma": "grupo", "UF do cadastro": "uf", "Ciclo": "ciclo",
             "Articulador": "articulador", "Papel": "papel"}
dimensao = st.segmented_control("Comparar por", list(DIMENSOES), default="Estado da turma", key="atividade_dimensao",
                                help="Estado da turma: estado no nome da turma da plataforma (ex.: “Para 3” → Pará). "
                                     "UF do cadastro: estado informado na inscrição.") or "Estado da turma"
coluna = DIMENSOES[dimensao]
if coluna == "estado_turma":
    # Uma conta conta uma vez por estado, mesmo se estiver em duas turmas do mesmo estado
    estados = contas["lista_grupos"].map(
        lambda grupos: sorted({painel.turma(g)[0] for g in grupos if painel.turma(g)}) or ["Sem turma identificada"])
    comparacao = contas.assign(dim=estados).explode("dim", ignore_index=True)
elif coluna == "grupo":
    comparacao = contas.assign(dim=contas["lista_grupos"].map(lambda g: g or ["Sem grupo"])).explode("dim", ignore_index=True)
    # "Para 3" -> "Pará · T3" (só na exibição; nomes fora do padrão ficam como vieram)
    comparacao["dim"] = comparacao["dim"].map(lambda g: f"{painel.turma(g)[0]} · T{painel.turma(g)[1]}" if painel.turma(g) else g)
elif coluna == "papel":
    comparacao = contas.assign(dim=papeis_por_conta.loc[contas.index]).explode("dim", ignore_index=True)
else:
    comparacao = contas.assign(dim=contas[coluna].fillna("Sem vínculo no cadastro"))
tabela = pd.crosstab(comparacao["dim"], comparacao["faixa_acesso"]).reindex(
    columns=[f for f in ordem_faixas if f in set(comparacao["faixa_acesso"])], fill_value=0)
sem_dimensao = ("Sem turma identificada", "Sem grupo", "Sem vínculo no cadastro")
tabela = tabela.loc[sorted(tabela.index, key=lambda d: (d in sem_dimensao, painel.ordem_natural(d)))]
fig = graficos.barras_empilhadas_100(
    tabela.index.tolist(), {f: tabela[f].tolist() for f in tabela.columns}, cores,
    f"Tempo desde o último acesso, por {dimensao[0].lower() + dimensao[1:]}",
    "Contas de cada linha pelo tempo desde o último acesso; o número em cada faixa é a contagem de contas",
)
ui.grafico(fig, tabela.rename_axis(dimensao).reset_index(), "atividade_comparacao",
           fonte=fonte, chamada_texto=ui.chamada(base))
if coluna in ("grupo", "estado_turma"):
    ui.nota("Uma conta em turmas de mais de um estado (ou em mais de uma turma) é contada em cada uma delas.")

ui.secao("Listas para verificação")
pessoas = painel.pessoas_de(ctx.cursistas)
prioritaria = pessoas[pessoas["requer_acompanhamento"]].sort_values(["prioridade", "dias_sem_acesso"], ascending=[True, False])
prioritaria = prioritaria.assign(motivos_texto=prioritaria["motivos"].map("; ".join),
                                 prioridade_texto=prioritaria["prioridade"].map(lambda p: f"{p}" if pd.notna(p) else ""))
nunca = pessoas[pessoas["acesso_tipo"] == "nunca"]
sem_cadastro = contas[contas["status_conciliacao"] == rc.SEM_CORRESPONDENCIA].assign(
    email_mascarado=lambda d: d["email"].map(mascarar_email))
em_revisao = contas[contas["status_conciliacao"].isin([rc.PENDENTE, rc.AMBIGUO])].assign(
    email_mascarado=lambda d: d["email"].map(mascarar_email))

COLUNAS_PESSOA = {"prioridade_texto": "Prioridade", "motivos_texto": "Motivo", "nome": "Nome", "uf": "UF",
                  "ente": "Ente", "escola": "Escola", "grupo": "Grupo", "situacao_conta": "Situação da conta",
                  "ultimo_acesso_texto": "Último acesso (como exportado)", "articulador": "Articulador"}
COLUNAS_CONTA = {"nome_completo": "Nome na plataforma", "email_mascarado": "E-mail (parcial)", "papeis": "Papel",
                 "grupos": "Grupos", "situacao_conta": "Situação", "ultimo_acesso_texto": "Último acesso",
                 "status_conciliacao": "Conciliação"}
abas = st.tabs([
    f"Prioridade de verificação ({metrics.numero(len(prioritaria))})",
    f"Sem registro de acesso ({metrics.numero(len(nunca))})",
    f"Contas sem correspondência no cadastro ({metrics.numero(len(sem_cadastro))})",
    f"Contas em revisão de conciliação ({metrics.numero(len(em_revisao))})",
])
with abas[0]:
    ui.nota("Prioridade 1: sem conta localizada ou sem registro de acesso; 2: conta não ativa; "
            f"3: sem acesso há mais de {base.parametros['limite_acompanhamento_dias']} dias. "
            "Critérios operacionais configuráveis; não indicam evasão ou desistência.")
    ui.tabela(prioritaria, COLUNAS_PESSOA, altura=420)
    ui.exportacao_controlada(ctx, prioritaria, COLUNAS_PESSOA, "lista_prioridade_verificacao.csv", "Baixar lista (sem contatos)")
with abas[1]:
    ui.tabela(nunca.assign(motivos_texto=nunca["motivos"].map("; ".join), prioridade_texto=""), COLUNAS_PESSOA, altura=420)
with abas[2]:
    ui.nota("Contas com os papéis selecionados sem registro correspondente no cadastro. Podem indicar inscrição "
            "fora do cadastro, e-mail diferente ou conta da equipe com papel de cursista.")
    ui.tabela(sem_cadastro, COLUNAS_CONTA, altura=360)
with abas[3]:
    ui.nota("Contas com sugestão de associação aguardando decisão. A revisão é feita em Qualidade e conciliação.")
    ui.tabela(em_revisao, COLUNAS_CONTA, altura=360)
    st.page_link("paginas/6_qualidade_conciliacao.py", label="Abrir a revisão de conciliação")
