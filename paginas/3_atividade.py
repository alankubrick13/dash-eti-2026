"""Atividade e turmas: uso da plataforma de formação e acompanhamento turma a turma."""

import pandas as pd
import streamlit as st

from src import cartoes, fichas, graficos, metrics, painel, ui
from src import reconciliation as rc
from src.normalization import chave_comparacao

ctx = painel.contexto()
base = ctx.base
fuso = ctx.cfg.fuso_horario
ui.titulo_pagina(
    "Atividade e turmas",
    "Uso da plataforma segundo a lista de participantes, turma a turma. Situação da conta e atividade são coisas "
    "diferentes: uma conta ativa pode estar sem acesso há semanas.",
)
ui.recorte(ctx)
if not base.tem_atividade:
    ui.faltam_arquivos(ctx.cfg, "atividade")
    st.stop()

meta = base.meta["atividade"]
ui.nota(
    f"Referência: {meta.get('referencia_descricao')} O último acesso ao curso não informa frequência, "
    "conclusão de atividades nem desempenho."
)
limites = base.parametros["faixas_inatividade_dias"]
janela, limite = base.parametros["janela_acesso_recente_dias"], base.parametros["limite_acompanhamento_dias"]
ordem_faixas = painel.ordem_faixas(limites)[:-1]  # contas sempre existem: sem a faixa "sem conta"
cores = graficos.cores_faixas(painel.ordem_faixas(limites))
fonte = ui.fonte_atividade(base, fuso)

papeis_por_conta = ctx.contas["papeis"].fillna("Sem papel").map(lambda p: [x.strip() for x in p.split(",") if x.strip()])
papeis = sorted({p for lista in papeis_por_conta for p in lista})
padrao = [p for p in papeis if chave_comparacao(p) in {chave_comparacao(x) for x in base.parametros["papeis_cursista"]}]
papel_sel = st.multiselect("Papéis na plataforma", papeis, default=padrao or papeis, key="atividade_papeis",
                           help="Por padrão, apenas os papéis definidos como de cursista nos parâmetros operacionais.")
contas = ctx.contas[papeis_por_conta.map(lambda lista: bool(set(lista) & set(papel_sel)))] if papel_sel else ctx.contas.iloc[0:0]

r = metrics.calcular_contas(contas, janela)
ui.indicadores([r["contas_recorte"], r["pct_situacao_ativa"], r["pct_com_acesso"], r["pct_acesso_recente_contas"],
                r["contas_nunca"]], colunas=5, chave="contas")
if contas.empty:
    st.stop()

fig = ui.histograma_acesso(
    contas["dias_sem_acesso"], int((contas["acesso_tipo"] == "nunca").sum()), base, fuso, "contas",
    subtitulo=f"Contas com os papéis selecionados ({metrics.numero(len(contas))}) pelo tempo desde o último acesso. "
              f"Tracejado: últimos {janela} dias e limite de acompanhamento ({limite} dias)",
)
classes = painel.classes_de_dias(contas["dias_sem_acesso"], limites, (janela, limite))
ui.grafico(fig, classes.rename(columns={"inicio": "De (dias)", "fim": "Até (dias)", "faixa": "Faixa",
                                        "contagem": "Contas"}), "atividade_tempo", fonte=fonte,
           chamada_texto=ui.chamada(base), destaque=True)

# ---------------------------------------------------------------- turmas
ui.secao("Turmas",
         "Cada cartão é uma turma da plataforma: um ponto por estudante, na cor da sua situação de acesso. "
         "Clique em uma turma para ver quem precisa de atenção.")
turmas = painel.resumo_turmas(ctx.contas, janela, limite)
if turmas.empty:
    ui.vazio("Nenhuma turma com estudantes no recorte.")
else:
    estados = sorted(turmas["estado"].dropna().unique(), key=chave_comparacao)
    opcoes = [("Todas as turmas", len(turmas), graficos.TINTA)]
    opcoes += [(e, int((turmas["estado"] == e).sum()), graficos.PETROLEO[1]) for e in estados]
    if turmas["estado"].isna().any():
        opcoes.append(("Outros grupos", int(turmas["estado"].isna().sum()), graficos.CINZA_NUNCA))
    escolha = ui.filtros_em_cartoes(opcoes, len(turmas), "turmas")
    ORDENACOES = {
        "Atenção primeiro": "atencao",
        "Menor taxa de acesso": "taxa",
        "Estado e turma": "nome",
    }
    _, ordem_col = ui.colunas([3, 1.4], "ordem_turmas", gap="small", vertical_alignment="bottom")
    ordenacao = ordem_col.selectbox("Ordenar", list(ORDENACOES), key="turmas_ordem", label_visibility="collapsed")
    vista = turmas if escolha == "Todas as turmas" else (
        turmas[turmas["estado"].isna()] if escolha == "Outros grupos" else turmas[turmas["estado"] == escolha])
    vista = vista.assign(_atencao=vista["atencao"] / vista["estudantes"],
                         _numero=pd.to_numeric(vista["numero"], errors="coerce"))
    nome = ["estado", "_numero", "grupo"]
    criterio = ORDENACOES[ordenacao]
    if criterio == "atencao":
        vista = vista.sort_values(["_atencao", "taxa_acesso", *nome], ascending=[False, True, True, True, True],
                                  na_position="last", kind="stable")
    elif criterio == "taxa":
        vista = vista.sort_values(["taxa_acesso", *nome], na_position="last", kind="stable")
    else:
        vista = vista.sort_values(nome, na_position="last", kind="stable")
    ui.nota(f"{metrics.numero(len(vista))} turma(s) em “{escolha}”, com {metrics.numero(int(vista['estudantes'].sum()))} "
            f"estudantes. “Precisam de atenção”: nunca acessaram ou estão há mais de {limite} dias sem acesso.")
    legenda = "".join(f'<span><i style="background:{cor}"></i>{f}</span>' for f, cor in cores.items()
                      if f in {x for fs in vista["faixas"] for x in fs})
    st.html(f'<div class="viz-legenda eti-legenda-pontos">{legenda}</div>')

    def desenhar(i, turma) -> None:
        ui.clicavel(cartoes.cartao_turma(turma, cores, limite), f"turma_{i}", f"Abrir a ficha da turma {turma.rotulo}",
                    fichas.pedir, ("turma", turma.grupo))

    ui.grade(list(vista.itertuples(index=False)), desenhar, "turmas")

pessoas = painel.pessoas_de(ctx.cursistas)
prioritaria = pessoas[pessoas["requer_acompanhamento"]].sort_values(["prioridade", "dias_sem_acesso"], ascending=[True, False])
if ctx.usuario.administrador and not prioritaria.empty:
    prioritaria = prioritaria.assign(motivos_texto=prioritaria["motivos"].map("; ".join),
                                     prioridade_texto=prioritaria["prioridade"].map(lambda p: f"{p}" if pd.notna(p) else ""))
    ui.exportacao_controlada(ctx, prioritaria, {
        "prioridade_texto": "Prioridade", "motivos_texto": "Motivo", "nome": "Nome", "uf": "UF", "ente": "Ente",
        "escola": "Escola", "grupo": "Grupo", "situacao_conta": "Situação da conta",
        "ultimo_acesso_texto": "Último acesso (como exportado)", "articulador": "Articulador",
    }, "lista_prioridade_verificacao.csv",
        f"Baixar a lista de quem requer acompanhamento ({metrics.numero(len(prioritaria))} pessoas, sem contatos)")

# ---------------------------------------------------------------- comparação entre grupos
ui.secao("Comparar grupos",
         "Composição do tempo desde o último acesso em cada grupo. O número ao lado de cada categoria é o total de "
         "contas; contas sem vínculo no cadastro aparecem como tal nas comparações de cadastro e de escola.")
DIMENSOES = {"Estado da turma": "estado_turma", "Turma": "grupo", "UF do cadastro": "uf",
             **{nome: coluna for nome, coluna in painel.DIMENSOES_PERFIL},
             **{nome: coluna for nome, coluna in painel.DIMENSOES_ESCOLA},
             "Articulador": "articulador", "Papel": "papel"}
# Dimensões do cadastro com um único valor no recorte (ex.: Ciclo) não diferenciam ninguém: ficam de fora
DIMENSOES = {n: c for n, c in DIMENSOES.items()
             if c in ("estado_turma", "grupo", "papel") or contas[c].dropna().nunique() > 1}
dimensao = st.pills("Comparar por", list(DIMENSOES), default="Estado da turma", key="atividade_dimensao",
                    help="Estado da turma: estado no nome da turma da plataforma (ex.: “Para 3” → Pará). "
                         "UF do cadastro: estado informado na inscrição. Localização, área diferenciada, internet e "
                         "banda larga: dados da escola no Censo Escolar.") or "Estado da turma"
coluna = DIMENSOES[dimensao]
SEM_VINCULO = "Sem vínculo no cadastro"
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
    sem_dado = "Escola sem dados do Inep" if coluna in dict(painel.DIMENSOES_ESCOLA).values() else "Não informado"
    vinculada = contas["status_conciliacao"] == rc.CORRESPONDENTE
    comparacao = contas.assign(dim=contas[coluna].where(vinculada, SEM_VINCULO).fillna(sem_dado))
sem_dimensao = ("Sem turma identificada", "Sem grupo", SEM_VINCULO, "Não informado", "Escola sem dados do Inep")
tabela = pd.crosstab(comparacao["dim"], comparacao["faixa_acesso"]).reindex(
    columns=[f for f in ordem_faixas if f in set(comparacao["faixa_acesso"])], fill_value=0)
tabela = tabela.loc[sorted(tabela.index, key=lambda d: (d in sem_dimensao, painel.chave_ordem(coluna, d)))]
tabela.index = [painel.rotulo(coluna, d) for d in tabela.index]
fig = graficos.barras_empilhadas_100(
    tabela.index.tolist(), {f: tabela[f].tolist() for f in tabela.columns}, cores,
    f"Tempo desde o último acesso, por {dimensao[0].lower() + dimensao[1:]}",
    "Contas de cada linha pelo tempo desde o último acesso; o número em cada faixa é a contagem de contas",
    mostrar_total=True,
)
nota = None
if coluna in ("grupo", "estado_turma"):
    nota = "Uma conta em turmas de mais de um estado (ou em mais de uma turma) é contada em cada uma delas."
elif coluna in dict(painel.DIMENSOES_ESCOLA).values():
    nota = ("Dados da escola no Censo Escolar. Comparação descritiva: o curso pode ser acessado de fora da escola, "
            "e diferenças entre grupos pequenos podem ser casuais.")
ui.grafico(fig, tabela.rename_axis(dimensao).reset_index(), "atividade_comparacao", nota, fonte, ui.chamada(base))
