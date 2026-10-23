"""Qualidade e conciliação: a saúde dos dados do painel e a revisão das associações cadastro ↔ plataforma."""

import json

import pandas as pd
import streamlit as st

from src import cartoes, fichas, graficos, importacao, metrics, painel, school_data, ui
from src import reconciliation as rc
from src.security import mascarar_email
from src.validators import ALERTA, ERRO

ctx = painel.contexto()
base = ctx.base
admin = ctx.usuario.administrador
publicada = ctx.cfg.ambiente == "publicacao"
fuso = ctx.cfg.fuso_horario
ui.titulo_pagina(
    "Qualidade e conciliação",
    "Como estão os dados que alimentam o painel: preenchimento, códigos, duplicidades, correspondência entre o "
    "cadastro e a plataforma e histórico das importações. Nada aqui altera as planilhas originais.",
)
ui.recorte(ctx)
if not base.tem_cadastro and not base.tem_atividade:
    ui.faltam_arquivos(ctx.cfg, "cadastro")
    st.stop()

cur = ctx.cursistas
cores = graficos.cores_faixas(painel.ordem_faixas(base.parametros["faixas_inatividade_dias"]))
ids_recorte = set(cur["id_registro"])
contas_recorte = set(ctx.contas["id_conta"]) if base.tem_atividade else set()
pc = base.problemas_cadastro[base.problemas_cadastro["id_registro"].isin(ids_recorte)].merge(
    base.cursistas[["id_registro", "nome", "uf", "ente"]], on="id_registro", how="left").assign(fonte="Cadastro")
pa = (base.problemas_atividade[base.problemas_atividade["id_conta"].isin(contas_recorte)].merge(
    base.contas[["id_conta", "nome_completo"]], on="id_conta", how="left")
    .rename(columns={"nome_completo": "nome"}).assign(fonte="Atividade")) if base.tem_atividade else pd.DataFrame()
problemas = pd.concat([pc, pa], ignore_index=True)
relevantes = problemas[problemas["gravidade"].isin([ERRO, ALERTA])] if not problemas.empty else problemas

SECOES = ["Conciliação", "Pendências nos registros", "Códigos INEP e IBGE", "Duplicidades", "Importações"]


def _ir_para_secao(secao: str) -> None:
    st.session_state["qualidade_secao"] = secao


# ---------------------------------------------------------------- checagem
n = len(cur)
n_dup = int(cur[["dup_cpf", "dup_email", "dup_nome_nascimento", "dup_linha"]].notna().any(axis=1).sum()) if n else 0
pendentes_reg = int(cur["status_conciliacao"].isin([rc.PENDENTE, rc.AMBIGUO]).sum()) if n else 0
associados = int((cur["status_conciliacao"] == rc.CORRESPONDENTE).sum()) if n else 0
estudantes = ctx.contas[ctx.contas["eh_cursista"] == 1] if base.tem_atividade else pd.DataFrame()
sem_cadastro = (estudantes[estudantes["status_conciliacao"] == rc.SEM_CORRESPONDENCIA]
                if not estudantes.empty else estudantes)


def _proporcao(validos: int, total: int, rotulo: str, secao: str, unidade: str = "registros",
               detalhe_extra: str = "") -> tuple:
    estado = "ok" if validos == total else "atencao"
    return (estado, rotulo, metrics.percentual(validos / total if total else None),
            f"{metrics.numero(validos)} de {metrics.numero(total)} {unidade}{detalhe_extra}", secao)


verificacoes = []
if n:
    arquivos = cur["arquivo_origem"].value_counts()
    verificacoes.append(("ok", "Registros do cadastro", metrics.numero(n),
                         f"lidos de {len(arquivos)} planilha(s); nenhum registro é excluído por problema", "Importações"))
    verificacoes.append(("ok" if not n_dup else "atencao", "Registros em duplicidade", metrics.numero(n_dup),
                         "mesmo CPF, e-mail, nome e nascimento ou linha repetida", "Duplicidades"))
    verificacoes.append(_proporcao(int((cur["cpf_status"].fillna("").str.startswith("valido")).sum()), n, "CPF válido",
                                   "Pendências nos registros", detalhe_extra=" (o CPF não é exibido nem gravado)"))
    verificacoes.append(_proporcao(int((cur["email_status"] == "valido").sum()), n, "E-mail válido",
                                   "Pendências nos registros"))
    verificacoes.append(_proporcao(int((cur["cod_ibge_status"] == "valido").sum()), n, "Código IBGE do ente válido",
                                   "Códigos INEP e IBGE"))
    verificacoes.append(_proporcao(int((cur["inep_status"] == "valido").sum()), n, "Código INEP da escola válido",
                                   "Códigos INEP e IBGE"))
    if base.tem_escolas:
        validos = cur.loc[cur["inep_status"] == "valido", "inep"].nunique()
        localizadas = cur.loc[cur["situacao_inep"] == school_data.SITUACAO_INEP_LOCALIZADO, "inep"].nunique()
        ano = (base.meta.get("escolas") or {}).get("referencia_em")
        verificacoes.append(("ok" if localizadas == validos else "atencao", f"Escolas localizadas no Censo {ano}",
                             f"{metrics.numero(localizadas)} de {metrics.numero(validos)}",
                             "escolas com código INEP válido encontradas na base oficial", "Códigos INEP e IBGE"))
if base.tem_atividade and n:
    verificacoes.append(("ok" if not pendentes_reg else "atencao", "Registros associados a uma conta",
                         metrics.numero(associados),
                         f"{metrics.numero(pendentes_reg)} aguarda{'m' if pendentes_reg > 1 else ''} revisão de conciliação"
                         if pendentes_reg
                         else "nenhuma sugestão aguardando revisão", "Conciliação"))
    verificacoes.append(("ok" if sem_cadastro.empty else "atencao", "Contas de estudante sem cadastro",
                         metrics.numero(len(sem_cadastro)), f"de {metrics.numero(len(estudantes))} contas de estudante",
                         "Conciliação"))
if base.tem_atividade:
    atv = base.meta.get("atividade") or {}
    data_lista = ui.data_local(atv.get("referencia_em"), fuso, False)
    verificacoes.append(("ok" if data_lista else "atencao", "Data da lista da plataforma", data_lista or "não informada",
                         "posição da lista de participantes (ver Importações)", "Importações"))

with st.container(key="verificacoes"):
    for i, (estado, titulo, valor, detalhe, secao) in enumerate(verificacoes):
        ui.clicavel(cartoes.verificacao(estado, titulo, valor, detalhe, com_seta=True), f"verificacao_{i}",
                    f"{titulo}: {valor}. Ver {secao}", _ir_para_secao, (secao,))
if base.alertas_conciliacao:
    for alerta in base.alertas_conciliacao:
        st.warning(alerta)

st.session_state.setdefault("qualidade_secao", SECOES[0])  # os cartões da checagem também escolhem a seção
secao = st.segmented_control("Seção", SECOES, key="qualidade_secao", label_visibility="collapsed") or SECOES[0]


def _linhas_de_registros(registros: pd.DataFrame, descricoes: dict, chave: str) -> None:
    """Uma linha por registro, com os problemas; o clique abre a ficha do cursista."""
    for i, pessoa in enumerate(registros.itertuples(index=False)):
        ui.clicavel(cartoes.linha_pendencia(pessoa, descricoes.get(pessoa.id_registro, []), cores), f"{chave}_{i}",
                    f"Abrir a ficha de {cartoes.nome_legivel(pessoa.nome)}", fichas.pedir, ("cursista", pessoa.id_registro))


# ---------------------------------------------------------------- conciliação
if secao == "Conciliação":
    if not base.tem_atividade:
        ui.vazio("A conciliação depende da lista de participantes da plataforma.")
    else:
        regras = base.associacoes[base.associacoes["id_registro"].isin(ids_recorte)]["regra"].value_counts()
        equipe = int((ctx.contas["eh_equipe"] == 1).sum())
        st.html(cartoes.numeros([
            ("Registros associados", metrics.numero(associados),
             "; ".join(f"{regra.lower()}: {metrics.numero(v)}" for regra, v in regras.items()) or None),
            ("Sugestões aguardando revisão", metrics.numero(pendentes_reg), "nome igual ou semelhante, e-mail diferente"),
            ("Contas de estudante sem cadastro", metrics.numero(len(sem_cadastro)), None),
            ("Contas da equipe do curso", metrics.numero(equipe), "formadores, coordenação e suporte (fora dos indicadores)"),
        ]))
        with st.expander("Como funciona a conciliação"):
            st.markdown(
                "**Regras, em ordem de prioridade:** (1) decisões manuais registradas por coordenadores; "
                "(2) e-mail normalizado, quando há exatamente uma conta e uma pessoa com aquele e-mail; "
                "(2b) outros registros da mesma pessoa (mesmo CPF ou e-mail) herdam a conta associada; "
                "(3) identificador compartilhado, se as duas fontes tiverem um; "
                "(4) nome idêntico ou semelhante gera apenas **sugestão** — nunca associa sozinho. "
                "CPF não é usado no cruzamento."
            )

        cad_info = base.cursistas[["id_registro", "chave_pessoa", "nome", "uf", "ente", "escola", "email"]]
        conta_info = base.contas[["id_conta", "chave_conta", "nome_completo", "grupos", "lista_grupos", "papeis", "email",
                                  "ultimo_acesso_texto", "status_conciliacao"]].rename(
            columns={"email": "email_conta", "status_conciliacao": "status_conta"})
        candidatos = base.candidatos
        if not candidatos.empty:
            candidatos = (candidatos[candidatos["id_registro"].isin(ids_recorte)]
                          .merge(cad_info, on="id_registro").merge(conta_info, on="id_conta"))
        ver_emails = False
        if ctx.usuario.acesso_contatos and not publicada:
            ver_emails = st.toggle("Mostrar e-mails completos (consulta registrada na auditoria)", key="conc_emails")
            if ver_emails and not st.session_state.get("_conc_emails_auditado"):
                ctx.repo.auditar(ctx.usuario.identificador, "exibiu_emails_conciliacao")
                st.session_state["_conc_emails_auditado"] = True
        mostrar = (lambda e: e) if ver_emails else mascarar_email

        ui.secao(f"Sugestões aguardando revisão ({metrics.numero(len(candidatos))})",
                 "Cada sugestão compara o registro do cadastro com a conta da plataforma. Associar faz a pessoa "
                 "passar a contar com essa conta; rejeitar descarta a sugestão. As decisões ficam registradas.")
        if candidatos.empty:
            ui.vazio("Nenhuma sugestão pendente ou ambígua no recorte.")
        else:
            for i, par in enumerate(candidatos.itertuples(index=False)):
                with st.container(border=True, key=f"par_{i}"):
                    st.html(cartoes.sugestao_conciliacao(par, mostrar))
                    if admin and not publicada:
                        associar, rejeitar, _ = st.columns([1, 1, 2.5])
                        if associar.button("Associar", type="primary", key=f"par_associar_{i}", width="stretch",
                                           icon=":material/link:"):
                            ctx.repo.registrar_decisao(par.chave_pessoa, par.chave_conta, "associar", None,
                                                       ctx.usuario.identificador)
                            st.rerun()
                        if rejeitar.button("Rejeitar", key=f"par_rejeitar_{i}", width="stretch",
                                           icon=":material/link_off:"):
                            ctx.repo.registrar_decisao(par.chave_pessoa, par.chave_conta, "rejeitar", None,
                                                       ctx.usuario.identificador)
                            st.rerun()
            if publicada:
                ui.nota("As decisões de conciliação são registradas pela coordenação no painel local; esta é a "
                        "versão publicada, só para leitura.")
            elif not admin:
                ui.nota("Decisões de conciliação são registradas por administradores.")

        if not sem_cadastro.empty:
            ui.secao(f"Contas de estudante sem registro no cadastro ({metrics.numero(len(sem_cadastro))})",
                     "Podem indicar inscrição fora do cadastro, e-mail diferente ou conta da equipe com papel de "
                     "estudante. Nome como está na plataforma; e-mail parcial.")
            for conta in sem_cadastro.itertuples(index=False):
                st.html(cartoes.linha_conta(conta))

        if admin and not publicada:
            with st.expander("Associar manualmente um registro a uma conta"):
                livres = cur[cur["status_conciliacao"] != rc.CORRESPONDENTE]
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

        decisoes = base.decisoes
        ui.secao(f"Decisões manuais em vigor ({metrics.numero(len(decisoes))})")
        if decisoes.empty:
            ui.nota("Nenhuma decisão manual registrada: todas as associações vieram do e-mail.")
        else:
            pessoas_nome = base.cursistas.drop_duplicates("chave_pessoa").set_index("chave_pessoa")["nome"]
            contas_nome = base.contas.drop_duplicates("chave_conta").set_index("chave_conta")["nome_completo"]
            vista = decisoes.assign(pessoa=decisoes["chave_pessoa"].map(pessoas_nome).fillna("(registro ausente do retrato atual)"),
                                    conta=decisoes["chave_conta"].map(contas_nome).fillna("(conta ausente do retrato atual)"))
            ui.tabela(vista, {"id": "Nº", "decisao": "Decisão", "pessoa": "Pessoa", "conta": "Conta",
                              "observacao": "Observação", "decidido_por": "Por", "decidido_em": "Em"})
            if admin and not publicada:
                revogar = st.selectbox("Revogar decisão", decisoes["id"].tolist(), index=None,
                                       placeholder="Nº da decisão", key="conc_revogar")
                if st.button("Revogar", disabled=revogar is None):
                    ctx.repo.revogar_decisao(int(revogar), ctx.usuario.identificador)
                    st.rerun()

# ---------------------------------------------------------------- pendências
elif secao == "Pendências nos registros":
    registros_cad = relevantes[relevantes["fonte"] == "Cadastro"] if not relevantes.empty else relevantes
    ui.secao(f"Registros com dados a corrigir na fonte ({metrics.numero(registros_cad['id_registro'].nunique() if not registros_cad.empty else 0)})",
             "Registros com problema de gravidade “erro” ou “alerta”. Eles continuam no painel e são sinalizados "
             "aqui; a correção é feita na planilha original. Clique para abrir a ficha.")
    if registros_cad.empty:
        ui.vazio("Nenhum registro do cadastro com erro ou alerta no recorte.")
    else:
        descricoes = registros_cad.groupby("id_registro")["problema"].agg(list).to_dict()
        _linhas_de_registros(cur[cur["id_registro"].isin(descricoes)], descricoes, "pendencia")
    informativos = problemas[~problemas["gravidade"].isin([ERRO, ALERTA])] if not problemas.empty else problemas
    if not informativos.empty:
        contagem = informativos.groupby(["fonte", "problema"]).size()
        ui.nota("Informativos (não exigem correção): " + "; ".join(
            f"{problema} ({fonte.lower()}): {metrics.numero(v)}" for (fonte, problema), v in contagem.items()) + ".")
    if not problemas.empty:
        with st.expander("Ver tabela de problemas (arquivo, linha e coluna de origem)"):
            ui.tabela(problemas.sort_values(["fonte", "arquivo", "linha"]),
                      {"fonte": "Fonte", "nome": "Nome", "uf": "UF", "ente": "Ente", "arquivo": "Arquivo", "linha": "Linha",
                       "coluna_original": "Coluna", "problema": "Problema", "gravidade": "Gravidade"}, altura=360)
        if admin and not publicada:
            incluir_nome = st.checkbox("Incluir o nome do cursista no relatório", key="qualidade_incluir_nome")
            rotulos = {"fonte": "Fonte", "arquivo": "Arquivo", "linha": "Linha", "coluna_original": "Coluna",
                       "problema": "Problema", "gravidade": "Gravidade", "codigo": "Código do problema"}
            if incluir_nome:
                rotulos = {"nome": "Nome", **rotulos}
            ui.exportacao_controlada(ctx, problemas.sort_values(["fonte", "arquivo", "linha"]), rotulos,
                                     "relatorio_inconsistencias.csv", "Baixar relatório de inconsistências")

# ---------------------------------------------------------------- códigos
elif secao == "Códigos INEP e IBGE":
    esquerda, direita = ui.colunas(2, "qualidade_graficos")
    with esquerda:
        situacao = cur["situacao_inep"].value_counts().reindex(school_data.ORDEM_SITUACAO_INEP).dropna()
        situacao = situacao[situacao > 0]
        fig = graficos.barras_horizontais(situacao.index.tolist(), situacao.astype(int).tolist(), "Códigos INEP",
                                          "Registros de inscrição", rotulos=[metrics.numero(v) for v in situacao])
        ui.grafico(fig, situacao.rename_axis("Situação").reset_index(name="Registros"), "codigos_inep",
                   fonte=ui.fonte_escolas(base))
    with direita:
        rotulos_ibge = {"valido": "Válido", "ausente": "Ausente", "invalido": "Formato inválido",
                        "uf_divergente": "Código de outra UF", "inexistente": "Fora da lista oficial do IBGE"}
        situacao = cur["cod_ibge_status"].map(rotulos_ibge).value_counts()
        fig = graficos.barras_horizontais(situacao.index.tolist(), situacao.tolist(), "Códigos IBGE dos entes",
                                          "Registros de inscrição; conferência com a lista oficial de municípios do IBGE",
                                          rotulos=[metrics.numero(v) for v in situacao])
        ui.grafico(fig, situacao.rename_axis("Situação").reset_index(name="Registros"), "codigos_ibge")
    divergentes = cur["problemas"].map(lambda p: "inep_uf_divergente" in p)
    sem_problema = cur["situacao_inep"].isin([school_data.SITUACAO_INEP_LOCALIZADO, school_data.SITUACAO_INEP_SEM_BASE])
    com_problema = cur[~sem_problema | divergentes | (cur["cod_ibge_status"] != "valido")]
    ui.secao(f"Registros com código a conferir ({metrics.numero(len(com_problema))})",
             "Código INEP ausente, inválido, não localizado ou de escola de outra UF, e código IBGE do ente "
             "inconsistente. A associação com a escola é sempre pelo código, nunca pelo nome.")
    if com_problema.empty:
        ui.vazio("Todos os códigos INEP e IBGE do recorte conferem.")
    else:
        descricoes = {}
        for registro in com_problema.itertuples(index=False):
            itens = []
            if registro.situacao_inep not in (school_data.SITUACAO_INEP_LOCALIZADO, school_data.SITUACAO_INEP_SEM_BASE):
                itens.append(registro.situacao_inep)
            if "inep_uf_divergente" in registro.problemas:
                itens.append("Escola de outra UF")
            if registro.cod_ibge_status != "valido":
                itens.append(f"IBGE: {rotulos_ibge.get(registro.cod_ibge_status, registro.cod_ibge_status).lower()}")
            descricoes[registro.id_registro] = itens
        _linhas_de_registros(com_problema, descricoes, "codigo")

# ---------------------------------------------------------------- duplicidades
elif secao == "Duplicidades":
    criterios = {"Mesmo CPF": "dup_cpf", "Mesmo e-mail": "dup_email",
                 "Mesmo nome e data de nascimento": "dup_nome_nascimento", "Registro idêntico (todas as colunas)": "dup_linha"}
    criterio = st.radio("Critério", list(criterios), horizontal=True, key="qualidade_criterio")
    coluna = criterios[criterio]
    dups = cur[cur[coluna].notna()].sort_values([coluna, "id_registro"])
    ui.nota(f"{metrics.numero(dups[coluna].nunique())} grupo(s), {metrics.numero(len(dups))} registros. "
            "O CPF e a data de nascimento não são exibidos nem armazenados: o critério informa apenas que os valores coincidem. "
            "Registros duplicados permanecem na base até a correção na fonte.")
    if dups.empty:
        ui.vazio("Nenhuma duplicidade por este critério no recorte.")
    else:
        descricoes = {r.id_registro: [f"Grupo {getattr(r, coluna)}"] for r in dups.itertuples(index=False)}
        _linhas_de_registros(dups, descricoes, "duplicidade")

# ---------------------------------------------------------------- importações
else:
    historico = ctx.repo.historico()
    if historico.empty:
        ui.vazio("Nenhuma importação registrada.")
    else:
        itens = []
        for imp in historico.itertuples(index=False):
            arquivos = ", ".join(x.get("arquivo", "") for x in json.loads(imp.arquivos)) if isinstance(imp.arquivos, str) else ""
            itens.append(cartoes.importacao(imp, ui.data_local(imp.importado_em, fuso) or "—", arquivos or "—"))
        st.html(f'<ol class="eti-linha-do-tempo">{"".join(itens)}</ol>')
        ui.nota("Versões “substituídas” são mantidas para comparação até o limite de retenção; as mais antigas "
                "são expurgadas e só os metadados permanecem. Os dados vêm dos arquivos da pasta do painel.")
        for fonte, rotulo in (("cadastro", "Cadastro"), ("atividade", "Lista da plataforma"), ("escolas", "Base escolar")):
            ativa, anterior = ctx.repo.importacao_ativa(fonte), ctx.repo.importacao_anterior(fonte)
            if not ativa or not anterior:
                continue
            dif = importacao.comparar_importacoes(
                fonte, ctx.repo.registros(fonte, ativa["id"]), ctx.repo.registros(fonte, anterior["id"]),
                ativa.get("mapeamento"), anterior.get("mapeamento"))
            ui.secao(f"{rotulo}: o que mudou da importação nº {anterior['id']} para a nº {ativa['id']}")
            st.html(cartoes.numeros([("Entraram", metrics.numero(dif["entraram"]), None),
                                     ("Saíram", metrics.numero(dif["sairam"]), None),
                                     ("Permaneceram", metrics.numero(dif["permaneceram"]), None)]))
            alteracoes = pd.Series(dif["alteracoes_por_campo"]).rename_axis("Campo").reset_index(name="Alterados")
            alteracoes = alteracoes[alteracoes["Alterados"] > 0]
            if not alteracoes.empty:
                with st.expander("Campos alterados"):
                    st.dataframe(alteracoes, hide_index=True, width="stretch")
            if dif.get("colunas_novas") or dif.get("colunas_ausentes"):
                ui.nota(f"Colunas novas: {', '.join(dif.get('colunas_novas') or ['nenhuma'])}. "
                        f"Colunas que deixaram de vir: {', '.join(dif.get('colunas_ausentes') or ['nenhuma'])}.")
