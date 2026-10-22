"""Visão geral: leitura rápida da situação da formação no recorte selecionado."""

import pandas as pd
import streamlit as st

from src import graficos, mapas, metrics, painel, ui
from src.config import NOME_DA_SIGLA
from src.normalization import chave_comparacao

ctx = painel.contexto()
base = ctx.base
fuso = ctx.cfg.fuso_horario
ui.titulo_pagina(
    "Visão geral",
    "Situação dos cursistas no cadastro e na plataforma de formação. O ícone de ajuda de cada "
    "indicador traz a definição, a fórmula, a fonte e as limitações.",
)
ui.recorte(ctx)

if not base.tem_cadastro:
    ui.faltam_arquivos(ctx.cfg, "cadastro")
    st.stop()

r = metrics.calcular(ctx.cursistas, ctx.contas, base, base.parametros)
ui.secao("Cadastro")
ui.indicadores([r["pessoas_cadastradas"], r["entes_representados"], r["escolas_identificadas"], r["pct_inep_valido"]])

referencia = dict(ui.referencias_dados(base, fuso))["Atividade"]
ui.secao(
    "Presença na plataforma de formação",
    f"Base de atividade: {referencia}. O tempo sem acesso é medido na data de referência dessa base.",
)
ui.indicadores([r["pct_contas_encontradas"], r["pct_contas_ativas"], r["pct_acesso_recente"], r["pessoas_acompanhamento"]])

pendentes = r["registros_pendentes"]
if pendentes.disponivel and pendentes.valor:
    with st.container(border=True):
        texto, acao = st.columns([4, 1.3], vertical_alignment="center")
        texto.markdown(
            f"**{metrics.numero(pendentes.valor)} registro(s) aguardam conciliação manual.** "
            "Enquanto não forem revisados, essas pessoas não entram nos percentuais de presença na plataforma."
        )
        acao.page_link("paginas/6_qualidade_conciliacao.py", label="Revisar conciliação")

if not base.tem_atividade:
    ui.faltam_arquivos(ctx.cfg, "atividade")
    st.stop()

limites = base.parametros["faixas_inatividade_dias"]
ordem = painel.ordem_faixas(limites)
cores = graficos.cores_faixas(ordem)
chamada = ui.chamada(base)
fonte = ui.fonte_atividade(base, fuso)
estudantes = ctx.contas[ctx.contas["eh_cursista"] == 1]


def nome_uf(sigla) -> str:
    return NOME_DA_SIGLA.get(sigla, sigla) if isinstance(sigla, str) else "UF não informada"


def estado_da_turma(grupos: list[str]) -> list[str]:
    estados = {painel.turma(g)[0] for g in grupos if painel.turma(g)}
    return sorted(estados) or ["Sem turma identificada"]


st.divider()
esquerda, direita = ui.colunas(2, "estados_turmas")
with esquerda:
    por_cadastro = st.session_state.get("visao_referencia_estado") == "UF do cadastro"
    ui.cabecalho_grafico(
        "Situação de cada estado",
        "Pessoas cadastradas de cada estado, pelo tempo desde o último acesso e por quem nunca entrou" if por_cadastro
        else "Todos os estudantes de cada estado, pelo tempo desde o último acesso e por quem nunca entrou",
        chamada, destaque=True,
    )
    referencia_estado = st.segmented_control(
        "Estado de cada estudante", ["Turma na plataforma", "UF do cadastro"], default="Turma na plataforma",
        key="visao_referencia_estado",
        help="Turma: estado no nome da turma do Moodle (ex.: “Para 3”). UF do cadastro: estado informado na inscrição. "
             "As duas podem diferir, porque as turmas não são formadas apenas por pessoas do mesmo estado.",
    ) or "Turma na plataforma"
    if referencia_estado == "UF do cadastro":
        dados = painel.pessoas_de(ctx.cursistas).assign(estado=lambda d: d["uf"].map(nome_uf))
        unidade = "pessoas"
    else:
        dados = estudantes.assign(estado=estudantes["lista_grupos"].map(estado_da_turma)).explode("estado", ignore_index=True)
        unidade = "estudantes"
    faixas = [f for f in ordem if f in set(dados["faixa_acesso"].dropna())]
    tabela = pd.crosstab(dados["estado"], dados["faixa_acesso"]).reindex(columns=faixas, fill_value=0)
    if tabela.empty:
        ui.vazio("Sem dados de acesso no recorte.")
    else:
        proporcao_nunca = tabela.get(painel.FAIXA_NUNCA, 0) / tabela.sum(axis=1)
        ordem_linhas = proporcao_nunca.sort_values(kind="stable").index.tolist()
        sem_estado = [e for e in ordem_linhas if e in ("Sem turma identificada", "UF não informada")]
        tabela = tabela.loc[[e for e in ordem_linhas if e not in sem_estado] + sem_estado]
        fig = graficos.barras_empilhadas_100(tabela.index.tolist(), {f: tabela[f].tolist() for f in faixas}, cores,
                                             "Situação de cada estado")
        ui.grafico(fig, tabela.rename_axis("Estado").reset_index(), "visao_estados",
                   f"Estados ordenados da menor para a maior proporção de quem nunca acessou. Contagem de {unidade}. "
                   "Turma: estado no nome da turma da plataforma; UF do cadastro: estado informado na inscrição.",
                   fonte if referencia_estado != "UF do cadastro" else f"{fonte} {ui.fonte_cadastro(base, fuso)}",
                   cabecalho=False)

with direita:
    linhas = []
    for conta in estudantes.itertuples(index=False):
        for grupo in conta.lista_grupos:
            identificada = painel.turma(grupo)
            if identificada:
                linhas.append({"estado": identificada[0], "turma": identificada[1],
                               "acessou": conta.acesso_tipo in ("relativo", "absoluto")})
    if not linhas:
        ui.vazio("Os nomes das turmas não seguem o padrão “Estado N”; o mapa de calor das turmas não pode ser montado.")
    else:
        turmas = pd.DataFrame(linhas).groupby(["estado", "turma"]).agg(acessaram=("acessou", "sum"),
                                                                        total=("acessou", "size")).reset_index()
        estados = sorted(turmas["estado"].unique(), key=chave_comparacao)
        numeros = sorted(turmas["turma"].unique())
        indice = {(e, t): (a, n) for e, t, a, n in turmas.itertuples(index=False)}
        valores, textos, subtextos = [], [], []
        for estado in estados:
            linha_valores, linha_textos, linha_sub = [], [], []
            for numero in numeros:
                celula = indice.get((estado, numero))
                if celula is None:
                    linha_valores.append(None)
                    linha_textos.append("")
                    linha_sub.append("")
                    continue
                acessaram, total = celula
                linha_valores.append(acessaram / total)
                linha_textos.append(metrics.percentual(acessaram / total, 0))
                linha_sub.append(f"{int(acessaram)}/{int(total)}")
            valores.append(linha_valores)
            textos.append(linha_textos)
            subtextos.append(linha_sub)
        fig = graficos.mapa_calor(estados, [f"T{t}" for t in numeros], valores, "Mapa de calor das turmas",
                                  "Taxa de acesso de cada turma. Quanto mais escura a cor, maior a parcela que já entrou no curso",
                                  textos, subtextos)
        tabela_turmas = turmas.assign(taxa=(turmas["acessaram"] / turmas["total"]).round(3))
        ui.grafico(fig, tabela_turmas.rename(columns={"estado": "Estado", "turma": "Turma", "acessaram": "Acessaram",
                                                      "total": "Estudantes", "taxa": "Taxa de acesso"}),
                   "visao_turmas",
                   f"T1 a T{max(numeros)} são as turmas 1 a {max(numeros)} de cada estado. Em cada quadro: "
                   "estudantes que acessaram / total de estudantes da turma.", fonte, chamada, destaque=True)

st.divider()
col_mapa, col_motivos = ui.colunas([1.6, 1], "mapa_motivos")
with col_mapa:
    resumo_mun = mapas.resumo_por_municipio(ctx.cursistas)
    municipios_geo, contornos_geo, _ = mapas.malhas_das_ufs(mapas.ufs_do_mapa(ctx.cursistas, resumo_mun))
    ui.cabecalho_grafico("Acesso ao curso por município",
                         "Proporção das pessoas com conta que já acessaram o curso, no município da escola. "
                         "Municípios em cinza não têm cursistas.", chamada)
    st.plotly_chart(mapas.figura(resumo_mun, municipios_geo, contornos_geo, "Acessaram o curso", altura=440),
                    theme=None, config=graficos.CONFIG, width="stretch", key="visao_mapa")
    st.page_link("paginas/5_territorio.py", label="Explorar o mapa e as escolas de cada município",
                 icon=":material/map:")
with col_motivos:
    motivos = metrics.contagem_motivos(ctx.cursistas)
    if motivos.empty:
        ui.vazio("Nenhuma pessoa do recorte se enquadra nos critérios de acompanhamento.")
    else:
        fig = graficos.barras_horizontais(motivos["motivo"].tolist(), motivos["pessoas"].tolist(),
                                          "Por que acompanhar", "Pessoas por critério; uma pessoa pode ter mais de um")
        ui.grafico(fig, motivos.rename(columns={"motivo": "Critério", "pessoas": "Pessoas"}), "visao_motivos",
                   f"Inatividade: sem acesso há mais de {base.parametros['limite_acompanhamento_dias']} dias. Critérios "
                   "operacionais configuráveis; não equivalem a evasão ou desistência.")


def barras_categoria(coluna: str, titulo: str, chave: str) -> None:
    pessoas = painel.pessoas_de(ctx.cursistas)
    contagem = pessoas[coluna].fillna("Não informado").value_counts()
    if contagem.empty:
        return
    total = int(contagem.sum())
    fig = graficos.barras_horizontais(
        contagem.index.tolist(), contagem.tolist(), titulo, f"Pessoas cadastradas (total {metrics.numero(total)})",
        rotulos=[f"{metrics.numero(v)} ({metrics.percentual(v / total)})" for v in contagem],
    )
    ui.grafico(fig, contagem.rename_axis(titulo).reset_index(name="Pessoas"), chave)


col1, col2 = ui.colunas(2, "cargo_origem")
with col1:
    barras_categoria("cargo_funcao", "Cargo ou função", "visao_cargo")
with col2:
    barras_categoria("origem", "Origem da vaga", "visao_origem")

with st.expander("Notas metodológicas dos indicadores"):
    notas = pd.DataFrame([
        {"Indicador": i.nome, "Unidade": i.unidade, "Definição": i.definicao, "Fórmula": i.formula,
         "Fonte": i.fonte, "Valores ausentes": i.ausentes, "Limitações": i.limitacoes}
        for i in metrics.INDICADORES.values()
    ])
    st.dataframe(notas, hide_index=True, width="stretch")
    ui.nota(
        "Pessoas são contadas por identificador pseudônimo (CPF ou, na falta dele, e-mail). Registros são linhas "
        "do cadastro. Contas são linhas da exportação da plataforma. Os percentuais sempre informam numerador e "
        "denominador abaixo do valor."
    )
