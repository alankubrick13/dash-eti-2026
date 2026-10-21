"""Qualidade e conciliação: ferramenta de gestão dos dados."""

import json

import pandas as pd
import streamlit as st

from src import graficos, importacao, metrics, painel, school_data, ui
from src import reconciliation as rc
from src.security import mascarar_email
from src.validators import ALERTA, ERRO

ctx = painel.contexto()
base = ctx.base
admin = ctx.usuario.administrador
ui.titulo_pagina(
    "Qualidade e conciliação",
    "Problemas de preenchimento, duplicidades, códigos escolares e territoriais, correspondência entre o "
    "cadastro e a plataforma e histórico das importações. Nada aqui altera as planilhas originais.",
)
ui.recorte(ctx)
if not base.tem_cadastro and not base.tem_atividade:
    ui.vazio("Nenhuma base foi importada ainda.")
    st.stop()

ids_recorte = set(ctx.cursistas["id_registro"])
contas_recorte = set(ctx.contas["id_conta"]) if base.tem_atividade else set()
pc = base.problemas_cadastro[base.problemas_cadastro["id_registro"].isin(ids_recorte)].merge(
    base.cursistas[["id_registro", "nome", "uf", "ente"]], on="id_registro", how="left").assign(fonte="Cadastro")
pa = (base.problemas_atividade[base.problemas_atividade["id_conta"].isin(contas_recorte)].merge(
    base.contas[["id_conta", "nome_completo"]], on="id_conta", how="left")
    .rename(columns={"nome_completo": "nome"}).assign(fonte="Atividade")) if base.tem_atividade else pd.DataFrame()
problemas = pd.concat([pc, pa], ignore_index=True)

abas = st.tabs(["Resumo", "Duplicidades", "Preenchimento e formatos", "Códigos INEP e IBGE", "Conciliação", "Importações"])

# ---------------------------------------------------------------- resumo
with abas[0]:
    relevantes = problemas[problemas["gravidade"].isin([ERRO, ALERTA])] if not problemas.empty else problemas
    cur = ctx.cursistas
    n_dup = int(cur[["dup_cpf", "dup_email", "dup_nome_nascimento", "dup_linha"]].notna().any(axis=1).sum())
    col = st.columns(4)
    col[0].metric("Registros com problemas", metrics.numero(relevantes.loc[relevantes["fonte"] == "Cadastro", "id_registro"].nunique()
                                                         if not relevantes.empty else 0),
                  help="Registros do cadastro com ao menos um problema de gravidade “erro” ou “alerta”.")
    col[1].metric("Registros em duplicidade", metrics.numero(n_dup),
                  help="Registros que compartilham CPF, e-mail, nome e nascimento, ou todas as colunas com outro registro.")
    col[2].metric("E-mails ausentes ou inválidos", metrics.numero(int((cur["email_status"] != "valido").sum())))
    col[3].metric("Códigos IBGE inconsistentes", metrics.numero(int((cur["cod_ibge_status"] != "valido").sum())))
    col = st.columns(4)
    col[0].metric("Códigos INEP ausentes ou inválidos", metrics.numero(int((cur["inep_status"] != "valido").sum())))
    col[1].metric("Códigos INEP não localizados", metrics.numero(int((cur["situacao_inep"] == school_data.SITUACAO_INEP_NAO_LOCALIZADO).sum())),
                  help="Código com formato válido que não consta da base escolar carregada.")
    col[2].metric("Registros pendentes de conciliação", metrics.numero(int(cur["status_conciliacao"].isin([rc.PENDENTE, rc.AMBIGUO]).sum())))
    if base.tem_atividade:
        contas_cursista = ctx.contas[ctx.contas["eh_cursista"] == 1]
        col[3].metric("Contas de cursista sem cadastro", metrics.numero(int((contas_cursista["status_conciliacao"] == rc.SEM_CORRESPONDENCIA).sum())))
    if not problemas.empty:
        por_tipo = problemas.groupby(["fonte", "problema", "gravidade"]).size().reset_index(name="registros").sort_values(
            ["fonte", "registros"], ascending=[True, False])
        st.markdown("#### Problemas por tipo")
        ui.tabela(por_tipo, {"fonte": "Fonte", "problema": "Problema", "gravidade": "Gravidade", "registros": "Registros"})
        st.markdown("#### Relatório de inconsistências")
        ui.nota("O relatório identifica arquivo, linha e coluna de origem para correção na fonte, sem CPF, "
                "contatos ou outros dados pessoais. O nome pode ser incluído por administradores, se necessário.")
        incluir_nome = admin and st.checkbox("Incluir o nome do cursista no relatório", key="qualidade_incluir_nome")
        rotulos = {"fonte": "Fonte", "arquivo": "Arquivo", "linha": "Linha", "coluna_original": "Coluna",
                   "problema": "Problema", "gravidade": "Gravidade", "codigo": "Código do problema"}
        if incluir_nome:
            rotulos = {"nome": "Nome", **rotulos}
        ui.exportacao_controlada(ctx, problemas.sort_values(["fonte", "arquivo", "linha"]), rotulos,
                                 "relatorio_inconsistencias.csv", "Baixar relatório de inconsistências")
    for alerta in base.alertas_conciliacao:
        st.warning(alerta)

# ---------------------------------------------------------------- duplicidades
with abas[1]:
    criterios = {"Mesmo CPF": "dup_cpf", "Mesmo e-mail": "dup_email",
                 "Mesmo nome e data de nascimento": "dup_nome_nascimento", "Registro idêntico (todas as colunas)": "dup_linha"}
    criterio = st.radio("Critério", list(criterios), horizontal=True, key="qualidade_criterio")
    coluna = criterios[criterio]
    dups = ctx.cursistas[ctx.cursistas[coluna].notna()].sort_values([coluna, "id_registro"])
    ui.nota(f"{metrics.numero(dups[coluna].nunique())} grupo(s), {metrics.numero(len(dups))} registros. "
            "O CPF e a data de nascimento não são exibidos nem armazenados: o critério informa apenas que os valores coincidem. "
            "Registros duplicados permanecem na base até a correção na fonte.")
    if dups.empty:
        ui.vazio("Nenhuma duplicidade por este critério no recorte.")
    else:
        ui.tabela(dups.assign(email_parcial=dups["email"].map(mascarar_email)),
                  {coluna: "Grupo", "nome": "Nome", "uf": "UF", "ente": "Ente", "escola": "Escola",
                   "email_parcial": "E-mail (parcial)", "situacao": "Situação", "arquivo_origem": "Arquivo",
                   "linha_origem": "Linha", "status_conciliacao": "Conciliação"}, altura=420)

# ---------------------------------------------------------------- preenchimento
with abas[2]:
    if problemas.empty:
        ui.vazio("Nenhum problema de preenchimento no recorte.")
    else:
        tipos = sorted(problemas["problema"].unique())
        padrao = [t for t in tipos if not any(t.startswith(p) for p in ("Mesmo", "Registro idêntico"))]
        escolhidos = st.multiselect("Tipos de problema", tipos, default=padrao, key="qualidade_tipos")
        selecao = problemas[problemas["problema"].isin(escolhidos)].sort_values(["fonte", "arquivo", "linha"])
        ui.tabela(selecao, {"fonte": "Fonte", "nome": "Nome", "uf": "UF", "ente": "Ente", "arquivo": "Arquivo",
                            "linha": "Linha", "coluna_original": "Coluna", "problema": "Problema",
                            "gravidade": "Gravidade"}, altura=460)
        ui.nota("Registros com problemas não são excluídos: continuam no painel e são sinalizados aqui.")

# ---------------------------------------------------------------- códigos
with abas[3]:
    esquerda, direita = ui.colunas(2, "qualidade_graficos")
    cur = ctx.cursistas
    with esquerda:
        situacao = cur["situacao_inep"].value_counts().reindex(school_data.ORDEM_SITUACAO_INEP).dropna()
        situacao = situacao[situacao > 0]
        fig = graficos.barras_horizontais(situacao.index.tolist(), situacao.astype(int).tolist(), "Códigos INEP",
                                          "Registros de inscrição", rotulos=[metrics.numero(v) for v in situacao])
        ui.grafico(fig, situacao.rename_axis("Situação").reset_index(name="Registros"), "codigos_inep")
        divergentes = cur["problemas"].map(lambda p: "inep_uf_divergente" in p)
        sem_problema = cur["situacao_inep"].isin([school_data.SITUACAO_INEP_LOCALIZADO, school_data.SITUACAO_INEP_SEM_BASE])
        problemas_inep = cur[~sem_problema | divergentes]
        ui.tabela(problemas_inep.assign(divergente=divergentes[problemas_inep.index].map({True: "Sim", False: ""})),
                  {"nome": "Nome", "uf": "UF", "ente": "Ente", "escola": "Escola informada", "inep": "Código",
                   "situacao_inep": "Situação", "divergente": "Escola de outra UF"}, altura=320)
    with direita:
        rotulos_ibge = {"valido": "Válido", "ausente": "Ausente", "invalido": "Formato inválido",
                        "uf_divergente": "Código de outra UF", "inexistente": "Fora da lista oficial do IBGE"}
        situacao = cur["cod_ibge_status"].map(rotulos_ibge).value_counts()
        fig = graficos.barras_horizontais(situacao.index.tolist(), situacao.tolist(), "Códigos IBGE dos entes",
                                          "Registros de inscrição; conferência com a lista oficial de municípios do IBGE",
                                          rotulos=[metrics.numero(v) for v in situacao])
        ui.grafico(fig, situacao.rename_axis("Situação").reset_index(name="Registros"), "codigos_ibge")
        problemas_ibge = cur[cur["cod_ibge_status"] != "valido"].assign(
            situacao_ibge=lambda d: d["cod_ibge_status"].map(rotulos_ibge))
        ui.tabela(problemas_ibge, {"nome": "Nome", "uf": "UF", "ente": "Ente", "esfera": "Esfera",
                                   "cod_ibge": "Código informado", "situacao_ibge": "Situação"}, altura=320)

# ---------------------------------------------------------------- conciliação
with abas[4]:
    if not base.tem_atividade:
        ui.vazio("A conciliação depende da base de atividade.")
    else:
        st.markdown(
            "**Regras, em ordem de prioridade:** (1) decisões manuais registradas por coordenadores; "
            "(2) e-mail normalizado, quando há exatamente uma conta e uma pessoa com aquele e-mail; "
            "(2b) outros registros da mesma pessoa (mesmo CPF ou e-mail) herdam a conta associada; "
            "(3) identificador compartilhado, se as duas fontes tiverem um; "
            "(4) nome idêntico ou semelhante gera apenas **sugestão** — nunca associa sozinho. "
            "CPF não é usado no cruzamento."
        )
        resumo_reg = ctx.cursistas["status_conciliacao"].value_counts().reindex(rc.STATUS_ORDEM, fill_value=0)
        resumo_conta = ctx.contas["status_conciliacao"].value_counts().reindex(rc.STATUS_ORDEM, fill_value=0)
        regras = base.associacoes[base.associacoes["id_registro"].isin(ids_recorte)]["regra"].value_counts()
        a, b, c = st.columns(3)
        a.markdown("**Registros do cadastro**")
        a.dataframe(resumo_reg.rename_axis("Situação").reset_index(name="Registros"), hide_index=True, width="stretch")
        b.markdown("**Contas da plataforma**")
        b.dataframe(resumo_conta.rename_axis("Situação").reset_index(name="Contas"), hide_index=True, width="stretch")
        c.markdown("**Associações por regra**")
        c.dataframe(regras.rename_axis("Regra").reset_index(name="Registros"), hide_index=True, width="stretch")

        cad_info = base.cursistas[["id_registro", "chave_pessoa", "nome", "uf", "ente", "escola", "email"]]
        conta_info = base.contas[["id_conta", "chave_conta", "nome_completo", "grupos", "papeis", "email",
                                  "ultimo_acesso_texto", "status_conciliacao"]].rename(
            columns={"email": "email_conta", "status_conciliacao": "status_conta"})
        candidatos = base.candidatos
        if not candidatos.empty:
            candidatos = (candidatos[candidatos["id_registro"].isin(ids_recorte)]
                          .merge(cad_info, on="id_registro").merge(conta_info, on="id_conta"))
        ver_emails = False
        if ctx.usuario.acesso_contatos:
            ver_emails = st.toggle("Mostrar e-mails completos (consulta registrada na auditoria)", key="conc_emails")
            if ver_emails and not st.session_state.get("_conc_emails_auditado"):
                ctx.repo.auditar(ctx.usuario.identificador, "exibiu_emails_conciliacao")
                st.session_state["_conc_emails_auditado"] = True
        mostrar = (lambda e: e) if ver_emails else mascarar_email

        st.markdown(f"#### Sugestões aguardando revisão ({metrics.numero(len(candidatos))})")
        if candidatos.empty:
            ui.vazio("Nenhuma sugestão pendente ou ambígua no recorte.")
        else:
            vista = candidatos.assign(email_cad=candidatos["email"].map(mostrar),
                                      email_c=candidatos["email_conta"].map(mostrar))
            ui.tabela(vista, {"situacao": "Situação", "motivo": "Motivo", "nome": "Nome no cadastro", "uf": "UF",
                              "ente": "Ente", "escola": "Escola", "email_cad": "E-mail no cadastro",
                              "nome_completo": "Nome na plataforma", "email_c": "E-mail na plataforma",
                              "grupos": "Grupo", "ultimo_acesso_texto": "Último acesso", "similaridade": "Similaridade"},
                      altura=360)
            if admin:
                rotulos_par = {
                    i: f"{l.nome} ↔ {l.nome_completo} · {l.motivo}" for i, l in enumerate(candidatos.itertuples())
                }
                escolha = st.selectbox("Par a decidir", list(rotulos_par), format_func=rotulos_par.get, index=None,
                                       placeholder="Selecione uma sugestão", key="conc_par")
                observacao = st.text_input("Observação (opcional, sem dados pessoais)", key="conc_obs", max_chars=200)
                bot1, bot2, _ = st.columns([1, 1, 3])
                if escolha is not None:
                    par = candidatos.iloc[escolha]
                    if bot1.button("Associar", type="primary", width="stretch"):
                        ctx.repo.registrar_decisao(par["chave_pessoa"], par["chave_conta"], "associar", observacao or None,
                                                   ctx.usuario.identificador)
                        st.rerun()
                    if bot2.button("Rejeitar sugestão", width="stretch"):
                        ctx.repo.registrar_decisao(par["chave_pessoa"], par["chave_conta"], "rejeitar", observacao or None,
                                                   ctx.usuario.identificador)
                        st.rerun()
            else:
                ui.nota("Decisões de conciliação são registradas por administradores.")

        if admin:
            with st.expander("Associar manualmente um registro a uma conta"):
                livres = ctx.cursistas[ctx.cursistas["status_conciliacao"] != rc.CORRESPONDENTE]
                contas_livres = base.contas[(base.contas["status_conciliacao"] != rc.CORRESPONDENTE) & (base.contas["eh_equipe"] == 0)]
                if livres.empty or contas_livres.empty:
                    ui.nota("Não há registros ou contas livres para associar.")
                else:
                    reg = st.selectbox("Registro do cadastro", livres["id_registro"].tolist(), index=None,
                                       format_func=lambda i: "{} — {} ({})".format(*livres.loc[livres["id_registro"] == i, ["nome", "escola", "uf"]].iloc[0].fillna("—")),
                                       placeholder="Digite para buscar", key="conc_manual_reg")
                    conta = st.selectbox("Conta na plataforma", contas_livres["id_conta"].tolist(), index=None,
                                         format_func=lambda i: "{} — {}".format(*contas_livres.loc[contas_livres["id_conta"] == i, ["nome_completo", "grupos"]].iloc[0].fillna("—")),
                                         placeholder="Digite para buscar", key="conc_manual_conta")
                    obs = st.text_input("Justificativa", key="conc_manual_obs", max_chars=200)
                    if st.button("Registrar associação manual", disabled=not (reg and conta and obs)):
                        pessoa = livres.loc[livres["id_registro"] == reg, "chave_pessoa"].iloc[0]
                        chave_conta = contas_livres.loc[contas_livres["id_conta"] == conta, "chave_conta"].iloc[0]
                        ctx.repo.registrar_decisao(pessoa, chave_conta, "associar", obs, ctx.usuario.identificador)
                        st.rerun()
                    ui.nota("A justificativa é obrigatória e fica registrada com autor e data.")
            with st.expander("Desfazer uma associação existente"):
                assoc = base.associacoes[base.associacoes["id_registro"].isin(ids_recorte)].merge(cad_info, on="id_registro").merge(conta_info, on="id_conta")
                if assoc.empty:
                    ui.nota("Nenhuma associação no recorte.")
                else:
                    indice = st.selectbox("Associação", list(range(len(assoc))), index=None,
                                          format_func=lambda i: f"{assoc.iloc[i]['nome']} ↔ {assoc.iloc[i]['nome_completo']} · {assoc.iloc[i]['regra']}",
                                          placeholder="Digite para buscar", key="conc_desfazer")
                    motivo = st.text_input("Motivo", key="conc_desfazer_obs", max_chars=200)
                    if st.button("Desfazer (rejeitar este par)", disabled=indice is None or not motivo):
                        linha = assoc.iloc[indice]
                        ctx.repo.registrar_decisao(linha["chave_pessoa"], linha["chave_conta"], "rejeitar", motivo,
                                                   ctx.usuario.identificador)
                        st.rerun()

        st.markdown("#### Decisões manuais em vigor")
        decisoes = base.decisoes
        if decisoes.empty:
            ui.nota("Nenhuma decisão manual registrada.")
        else:
            pessoas_nome = base.cursistas.drop_duplicates("chave_pessoa").set_index("chave_pessoa")["nome"]
            contas_nome = base.contas.drop_duplicates("chave_conta").set_index("chave_conta")["nome_completo"]
            vista = decisoes.assign(pessoa=decisoes["chave_pessoa"].map(pessoas_nome).fillna("(registro ausente do retrato atual)"),
                                    conta=decisoes["chave_conta"].map(contas_nome).fillna("(conta ausente do retrato atual)"))
            ui.tabela(vista, {"id": "Nº", "decisao": "Decisão", "pessoa": "Pessoa", "conta": "Conta",
                              "observacao": "Observação", "decidido_por": "Por", "decidido_em": "Em"})
            if admin:
                revogar = st.selectbox("Revogar decisão", decisoes["id"].tolist(), index=None,
                                       placeholder="Nº da decisão", key="conc_revogar")
                if st.button("Revogar", disabled=revogar is None):
                    ctx.repo.revogar_decisao(int(revogar), ctx.usuario.identificador)
                    st.rerun()

# ---------------------------------------------------------------- importações
with abas[5]:
    historico = ctx.repo.historico()
    if historico.empty:
        ui.vazio("Nenhuma importação registrada.")
    else:
        historico["arquivos"] = historico["arquivos"].map(
            lambda a: ", ".join(x.get("arquivo", "") for x in json.loads(a)) if isinstance(a, str) else "")
        ui.tabela(historico, {"id": "Nº", "fonte": "Fonte", "status": "Situação", "importado_em": "Importado em (UTC)",
                              "importado_por": "Por", "referencia_descricao": "Referência", "n_registros": "Registros",
                              "n_com_problemas": "Com problemas", "n_duplicados": "Em duplicidade", "arquivos": "Arquivos"})
        ui.nota("Retratos “substituídos” são mantidos para comparação até o limite de retenção; os mais antigos "
                "são expurgados e só os metadados permanecem.")
        st.markdown("#### Diferenças em relação à importação anterior")
        for fonte, rotulo in (("cadastro", "Cadastro"), ("atividade", "Atividade"), ("escolas", "Base escolar")):
            ativa, anterior = ctx.repo.importacao_ativa(fonte), ctx.repo.importacao_anterior(fonte)
            if not ativa or not anterior:
                continue
            dif = importacao.comparar_importacoes(
                fonte, ctx.repo.registros(fonte, ativa["id"]), ctx.repo.registros(fonte, anterior["id"]),
                ativa.get("mapeamento"), anterior.get("mapeamento"))
            st.markdown(f"**{rotulo}** — importação nº {ativa['id']} comparada à nº {anterior['id']}")
            c1, c2, c3 = st.columns(3)
            c1.metric("Entraram", metrics.numero(dif["entraram"]))
            c2.metric("Saíram", metrics.numero(dif["sairam"]))
            c3.metric("Permaneceram", metrics.numero(dif["permaneceram"]))
            alteracoes = pd.Series(dif["alteracoes_por_campo"]).rename_axis("Campo").reset_index(name="Alterados")
            st.dataframe(alteracoes[alteracoes["Alterados"] > 0], hide_index=True, width="stretch")
            if dif.get("colunas_novas") or dif.get("colunas_ausentes"):
                ui.nota(f"Colunas novas: {', '.join(dif.get('colunas_novas') or ['nenhuma'])}. "
                        f"Colunas que deixaram de vir: {', '.join(dif.get('colunas_ausentes') or ['nenhuma'])}.")
