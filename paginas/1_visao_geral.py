"""Visão geral: leitura rápida da situação da formação no recorte selecionado."""

import pandas as pd
import streamlit as st

from src import graficos, mapas, metrics, painel, ui
from src import reconciliation as rc
from src.config import NOME_DA_SIGLA
from src.normalization import chave_comparacao

ctx = painel.contexto()
base = ctx.base
fuso = ctx.cfg.fuso_horario
ui.titulo_pagina(
    "Visão geral",
    "Situação dos cursistas no cadastro e na plataforma de formação. Clique em um destaque para ver quem está "
    "por trás do número; o ícone de ajuda de cada indicador traz a definição, a fórmula e as limitações.",
)
ui.recorte(ctx)

if not base.tem_cadastro:
    ui.faltam_arquivos(ctx.cfg, "cadastro")
    st.stop()

r = metrics.calcular(ctx.cursistas, ctx.contas, base, base.parametros)
ui.destaques(metrics.destaques(ctx.cursistas, ctx.contas, base.parametros))

ui.secao("Cadastro")
ui.indicadores([r["pessoas_cadastradas"], r["entes_representados"], r["escolas_identificadas"], r["pct_inep_valido"]],
               chave="cadastro")

referencia = dict(ui.referencias_dados(base, fuso))["Atividade"]
ui.secao(
    "Presença na plataforma de formação",
    f"Base de atividade: {referencia}. O tempo sem acesso é medido na data dessa lista.",
)
ui.indicadores([r["pct_contas_encontradas"], r["pct_ja_acessaram"], r["pct_acesso_recente"], r["pessoas_acompanhamento"]],
               chave="plataforma")

pendentes = r["registros_pendentes"]
if pendentes.disponivel and pendentes.valor:
    with st.container(border=True, key="aviso_pendentes"):
        texto, acao = st.columns([4, 1.3], vertical_alignment="center")
        um = pendentes.valor == 1
        texto.markdown(
            f"**{metrics.numero(pendentes.valor)} {'registro aguarda' if um else 'registros aguardam'} conciliação "
            f"manual.** Enquanto não {'for revisado, essa pessoa não entra' if um else 'forem revisados, essas pessoas não entram'} "
            "nos percentuais de presença na plataforma."
        )
        acao.page_link("paginas/6_qualidade_conciliacao.py", label="Revisar conciliação", icon=":material/fact_check:")

if not base.tem_atividade:
    ui.faltam_arquivos(ctx.cfg, "atividade")
    st.stop()

limites = base.parametros["faixas_inatividade_dias"]
ordem = painel.ordem_faixas(limites)
cores = graficos.cores_faixas(ordem)
chamada = ui.chamada(base)
fonte = ui.fonte_atividade(base, fuso)
estudantes = ctx.contas[ctx.contas["eh_cursista"] == 1]
pessoas = painel.pessoas_de(ctx.cursistas)


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
        dados = pessoas.assign(estado=lambda d: d["uf"].map(nome_uf))
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
                                             "Situação de cada estado", mostrar_total=True)
        ui.grafico(fig, tabela.rename_axis("Estado").reset_index(), "visao_estados",
                   f"Estados ordenados da menor para a maior proporção de quem nunca acessou. Contagem de {unidade}; "
                   "o número ao lado do estado é o total. Turma: estado no nome da turma da plataforma; UF do "
                   "cadastro: estado informado na inscrição.",
                   fonte if referencia_estado != "UF do cadastro" else f"{fonte} {ui.fonte_cadastro(base, fuso)}",
                   cabecalho=False)

with direita:
    turmas = painel.resumo_turmas(ctx.contas, base.parametros["janela_acesso_recente_dias"],
                                  base.parametros["limite_acompanhamento_dias"])
    turmas = turmas.dropna(subset=["estado"])
    if turmas.empty:
        ui.vazio("Os nomes das turmas não seguem o padrão “Estado N”; o mapa de calor das turmas não pode ser montado.")
    else:
        estados = sorted(turmas["estado"].unique(), key=chave_comparacao)
        numeros = sorted(turmas["numero"].astype(int).unique())
        indice = {(e, int(n)): (a, t) for e, n, a, t in turmas[["estado", "numero", "acessaram", "estudantes"]]
                  .itertuples(index=False)}
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
        tabela_turmas = turmas.assign(taxa=turmas["taxa_acesso"].round(3))[["estado", "numero", "acessaram", "estudantes", "taxa"]]
        ui.grafico(fig, tabela_turmas.rename(columns={"estado": "Estado", "numero": "Turma", "acessaram": "Acessaram",
                                                      "estudantes": "Estudantes", "taxa": "Taxa de acesso"}),
                   "visao_turmas",
                   f"T1 a T{max(numeros)} são as turmas 1 a {max(numeros)} de cada estado. Em cada quadro: "
                   "estudantes que acessaram / total de estudantes da turma.", fonte, chamada, destaque=True)
        st.page_link("paginas/3_atividade.py", label="Ver as turmas e quem precisa de atenção em cada uma",
                     icon=":material/groups:")

st.divider()
col_mapa, col_tempo = ui.colunas([1.15, 1], "mapa_tempo")
with col_mapa:
    resumo_mun = mapas.resumo_por_municipio(ctx.cursistas)
    municipios_geo, contornos_geo, _ = mapas.malhas_das_ufs(mapas.ufs_do_mapa(ctx.cursistas, resumo_mun))
    ui.cabecalho_grafico("Acesso ao curso por município",
                         "Proporção das pessoas com conta que já acessaram o curso, no município da escola. "
                         "Municípios em cinza não têm cursistas.", chamada)
    st.html(f"<style>.st-key-mapa_visao {{ --proporcao-mapa: {mapas.proporcao(municipios_geo, contornos_geo):.3f}; }}"
            "</style>")
    with st.container(key="mapa_visao"):
        st.plotly_chart(mapas.figura(resumo_mun, municipios_geo, contornos_geo, "Acessaram o curso", altura=None,
                                     escala=False),
                        theme=None, config=graficos.CONFIG, width="stretch", height="stretch", key="visao_mapa")
    st.html(mapas.legenda_html(resumo_mun, "Acessaram o curso"))
    st.page_link("paginas/5_territorio.py", label="Explorar o mapa e as escolas de cada município",
                 icon=":material/map:")
with col_tempo:
    com_conta = pessoas[pessoas["status_conciliacao"] == rc.CORRESPONDENTE]
    fig = ui.histograma_acesso(
        com_conta["dias_sem_acesso"], int((com_conta["acesso_tipo"] == "nunca").sum()), base, fuso, "pessoas",
        subtitulo=f"Pessoas com conta na plataforma ({metrics.numero(len(com_conta))}) pelo tempo desde o último "
                  f"acesso. Tracejado: últimos {base.parametros['janela_acesso_recente_dias']} dias e limite de "
                  f"acompanhamento ({base.parametros['limite_acompanhamento_dias']} dias)",
    )
    classes = painel.classes_de_dias(com_conta["dias_sem_acesso"], limites)
    ui.grafico(fig, classes.rename(columns={"inicio": "De (dias)", "fim": "Até (dias)", "faixa": "Faixa",
                                            "contagem": "Pessoas"}), "visao_tempo",
               "Critérios de acompanhamento operacionais e configuráveis; não equivalem a evasão ou desistência.",
               fonte, chamada, destaque=True)

ui.secao("Perfil e participação",
         "Quem são os cursistas e como cada grupo está na plataforma: pessoas cadastradas pelo tempo desde o "
         "último acesso. O número ao lado de cada categoria é o total de pessoas.")
col_perfil, col_semana = ui.colunas(2, "perfil_semana")
with col_perfil:
    ui.comparacao_faixas(pessoas, [d for d in painel.DIMENSOES_PERFIL if d[1] in ("cargo_funcao", "origem", "escolaridade")],
                         ordem, cores, "Participação por perfil", "Cargo, origem da vaga e escolaridade informados no cadastro",
                         "visao_perfil", fonte=ui.fonte_cadastro(base, fuso), chamada_texto=chamada)
with col_semana:
    ui.comparacao_faixas(pessoas, [("Semana da inscrição", "semana_inscricao")], ordem, cores,
                         "Participação por semana da inscrição",
                         "Semana (segunda a domingo) da resposta à inscrição, segundo o cadastro",
                         "visao_semana", "Quem respondeu à inscrição em cada semana, pela situação de acesso de hoje.",
                         ui.fonte_cadastro(base, fuso), chamada)

st.page_link("paginas/8_sobre.py", label="Como cada indicador é calculado e de onde vêm os dados",
             icon=":material/info:")
