"""Administração: importação transacional das bases, base escolar, parâmetros e auditoria."""

import hashlib
from datetime import datetime, time
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from src import config, importacao, metrics, painel, school_data, synthetic, ui
from src.loaders import CAMPOS_ATIVIDADE, CAMPOS_CADASTRO, ErroImportacao, listar_abas, ler_tabela
from src.security import configurar_logging

ctx = painel.contexto()
if not ctx.usuario.administrador:
    st.error("Área restrita a administradores.")
    st.stop()

ui.titulo_pagina(
    "Administração",
    "Importação e atualização das bases. Cada importação passa por validação e só substitui a anterior "
    "depois de confirmada; se a gravação falhar, a versão anterior continua valendo. Os arquivos originais "
    "nunca são alterados.",
)
demo = ctx.cfg.demonstracao
if demo:
    st.info(
        "Demonstração: o envio de arquivos está desativado para que nenhum dado real seja carregado em ambiente "
        "público. Experimente o fluxo com os arquivos fictícios abaixo; as alterações valem só para esta sessão.",
        icon=":material/info:",
    )

OPCOES_DEMO = {
    "cadastro": {
        "Cadastro atualizado, com entradas e saídas (fictício)": ["cadastro_atualizacao"],
        "Cadastro sem a coluna de e-mail (erro estrutural, fictício)": ["cadastro_sem_email"],
        "Cadastro original e lista de novos inscritos (fictícios)": ["cadastro", "cadastro_novos"],
    },
    "atividade": {
        "Nova exportação de participantes, 5 dias depois (fictícia)": ["atividade_nova"],
        "Exportação original de participantes (fictícia)": ["atividade"],
    },
}
REFERENCIAS_DEMO = {"atividade_nova": synthetic.REFERENCIA_NOVA_EXPORTACAO, "atividade": synthetic.REFERENCIA_EXPORTACAO}
ROTULOS_CADASTRO = {c.nome: c.rotulo for c in CAMPOS_CADASTRO}
ROTULOS_ATIVIDADE = {c.nome: c.rotulo for c in CAMPOS_ATIVIDADE}


def _arquivos_demo(fonte: str) -> tuple[list[tuple[str, bytes]], str]:
    from src.ambiente import arquivos_demonstracao

    caminhos = arquivos_demonstracao()
    escolha = st.radio("Arquivos fictícios", list(OPCOES_DEMO[fonte]), key=f"demo_{fonte}")
    chaves = OPCOES_DEMO[fonte][escolha]
    return [(caminhos[k].name, caminhos[k].read_bytes()) for k in chaves], chaves[0]


def _arquivos_enviados(fonte: str, tipos: list[str], multiplos: bool) -> list[tuple[str, bytes]]:
    enviados = st.file_uploader(
        "Arquivos", type=tipos, accept_multiple_files=multiplos, key=f"envio_{fonte}",
        help="Os arquivos são lidos em memória para validação; nada é gravado antes da confirmação.",
    )
    if not enviados:
        return []
    enviados = enviados if isinstance(enviados, list) else [enviados]
    return [(a.name, a.getvalue()) for a in enviados]


def _assinatura(arquivos: list[tuple[str, bytes]]) -> str:
    h = hashlib.sha256()
    for nome, conteudo in arquivos:
        h.update(nome.encode())
        h.update(hashlib.sha256(conteudo).digest())
    return h.hexdigest()


def _mostrar_previa(previa: importacao.Previa, rotulos_campos: dict[str, str]) -> None:
    for bloqueio in previa.bloqueios:
        st.error(bloqueio, icon=":material/block:")
    if previa.avisos:
        with st.container(border=True):
            st.markdown("**Avisos**")
            for aviso in previa.avisos:
                st.markdown(f"- {aviso}")
    resumo = previa.resumo
    if resumo:
        col = st.columns(4)
        col[0].metric("Registros lidos", metrics.numero(resumo.get("n_registros")))
        if previa.fonte == "cadastro":
            col[1].metric("Pessoas distintas", metrics.numero(resumo.get("n_pessoas")))
        elif previa.fonte == "atividade":
            col[1].metric("Contas de cursista", metrics.numero(resumo.get("contas_cursista")))
        else:
            col[1].metric("Ano de referência", resumo.get("ano_referencia") or "—")
        col[2].metric("Com problemas", metrics.numero(resumo.get("n_com_problemas")))
        col[3].metric("Em duplicidade", metrics.numero(resumo.get("n_duplicados")))
    if previa.mapeamentos:
        linhas = []
        for arquivo, mapa in previa.mapeamentos.items():
            meta = next((a for a in previa.arquivos if a["arquivo"] == arquivo), {})
            for original in meta.get("cabecalhos", []) or list(mapa):
                linhas.append({"Arquivo": arquivo, "Cabeçalho original": original,
                               "Campo do painel": rotulos_campos.get(mapa.get(original), "— (não utilizado)")})
        with st.expander("Correspondência das colunas (cabeçalhos originais preservados)"):
            st.dataframe(pd.DataFrame(linhas), hide_index=True, width="stretch")
    if resumo.get("por_codigo"):
        with st.expander("Relatório de qualidade por tipo de problema", expanded=True):
            st.dataframe(pd.DataFrame(resumo["por_codigo"]).rename(columns={
                "codigo": "Código", "problema": "Problema", "gravidade": "Gravidade", "registros": "Registros"}),
                hide_index=True, width="stretch")


def _mostrar_comparacao(previa: importacao.Previa) -> None:
    if not previa.pode_confirmar:
        return
    dif = importacao.comparar_com_ativa(ctx.repo, previa)
    st.markdown("**Comparação com a versão em uso**")
    if not dif.get("ha_anterior"):
        ui.nota("Não há versão anterior desta base: esta será a primeira.")
        return
    col = st.columns(4)
    col[0].metric("Antes", metrics.numero(dif["registros_antes"]))
    col[1].metric("Depois", metrics.numero(dif["registros_depois"]))
    col[2].metric("Entram", metrics.numero(dif["entraram"]))
    col[3].metric("Saem", metrics.numero(dif["sairam"]))
    alteracoes = {k: v for k, v in dif["alteracoes_por_campo"].items() if v}
    if alteracoes:
        st.dataframe(pd.Series(alteracoes).rename_axis("Campo").reset_index(name="Registros alterados"),
                     hide_index=True, width="stretch")
    if dif.get("passaram_a_registrar_acesso"):
        ui.nota(f"{metrics.numero(dif['passaram_a_registrar_acesso'])} conta(s) passaram a registrar acesso.")
    if dif.get("colunas_novas") or dif.get("colunas_ausentes"):
        ui.nota(f"Colunas novas: {', '.join(dif.get('colunas_novas') or ['nenhuma'])}. "
                f"Colunas que deixaram de vir: {', '.join(dif.get('colunas_ausentes') or ['nenhuma'])}.")


def _confirmacao(fonte: str, previa: importacao.Previa) -> None:
    ciente = True
    for aviso in previa.exige_confirmacao:
        st.warning(aviso)
    if previa.exige_confirmacao:
        ciente = st.checkbox("Li os avisos e quero importar mesmo assim", key=f"ciente_{fonte}")
    confirmar, cancelar, _ = st.columns([1.2, 1, 3])
    if confirmar.button("Confirmar importação", type="primary", disabled=not (previa.pode_confirmar and ciente),
                        key=f"confirmar_{fonte}", width="stretch"):
        try:
            novo_id = importacao.confirmar(ctx.repo, previa, ctx.usuario.identificador)
        except Exception:
            configurar_logging().exception("falha ao gravar importação de %s", fonte)
            st.error("A gravação falhou e foi desfeita; a versão anterior continua em uso.")
        else:
            st.session_state.pop(f"previa_{fonte}", None)
            st.session_state["mensagem_admin"] = f"Importação nº {novo_id} confirmada ({fonte})."
            st.rerun()
    if cancelar.button("Cancelar", key=f"cancelar_{fonte}", width="stretch"):
        st.session_state.pop(f"previa_{fonte}", None)
        st.rerun()


def _ler(arquivos, campos, permitidos, abas: dict[str, str]) -> list:
    tabelas = []
    for nome, conteudo in arquivos:
        tabelas.append(ler_tabela(nome, conteudo, campos, permitidos, abas.get(nome)))
    return tabelas


def _seletor_abas(arquivos) -> dict[str, str]:
    abas = {}
    for nome, conteudo in arquivos:
        if nome.lower().endswith(".xlsx"):
            try:
                disponiveis = listar_abas(conteudo)
            except ErroImportacao as exc:
                st.error(str(exc))
                continue
            if len(disponiveis) > 1:
                abas[nome] = st.selectbox(f"Aba de “{nome}”", disponiveis, key=f"aba_{nome}")
    return abas


def _mapeamento_manual(fonte: str, previa: importacao.Previa, campos) -> dict | None:
    """Permite indicar à mão a coluna de um campo obrigatório não reconhecido."""
    faltando = {}
    for arquivo, mapa in previa.mapeamentos.items():
        internos = set(mapa.values())
        ausentes = [c for c in campos if c.obrigatorio and c.nome not in internos]
        if fonte == "atividade" and not {"nome_completo", "nome"} & internos:
            ausentes.append(next(c for c in campos if c.nome == "nome_completo"))
        if ausentes:
            faltando[arquivo] = ausentes
    if not faltando:
        return None
    st.markdown("**Indique a correspondência das colunas não reconhecidas**")
    manual = {}
    for arquivo, ausentes in faltando.items():
        meta = next(a for a in previa.arquivos if a["arquivo"] == arquivo)
        manual[arquivo] = {}
        for campo in ausentes:
            escolha = st.selectbox(f"“{arquivo}”: coluna com {campo.rotulo}", meta.get("cabecalhos", []), index=None,
                                   key=f"manual_{fonte}_{arquivo}_{campo.nome}", placeholder="Selecione a coluna")
            if escolha:
                manual[arquivo][campo.nome] = escolha
    return manual


def _fluxo(fonte: str, campos, permitidos: tuple[str, ...], preparar) -> None:
    if demo:
        arquivos, chave_demo = _arquivos_demo(fonte)
    else:
        arquivos, chave_demo = _arquivos_enviados(fonte, list(permitidos), multiplos=True), None
    if not arquivos:
        return
    abas = _seletor_abas(arquivos)
    extras = preparar_extras(fonte, chave_demo)
    estado = st.session_state.get(f"previa_{fonte}")
    assinatura = _assinatura(arquivos) + repr(sorted(abas.items())) + repr(extras)
    if st.button("Validar arquivos", key=f"validar_{fonte}"):
        try:
            tabelas = _ler(arquivos, campos, permitidos, abas)
            previa = preparar(tabelas, None, extras)
        except ErroImportacao as exc:
            st.error(str(exc))
            return
        estado = {"assinatura": assinatura, "previa": previa, "tabelas": tabelas}
        st.session_state[f"previa_{fonte}"] = estado
    if not estado or estado["assinatura"] != assinatura:
        return
    previa = estado["previa"]
    manual = _mapeamento_manual(fonte, previa, campos)
    if manual and any(manual.values()) and st.button("Validar novamente com esta correspondência", key=f"revalidar_{fonte}"):
        previa = preparar(estado["tabelas"], manual, extras)
        estado["previa"] = previa
        st.rerun()
    _mostrar_previa(previa, ROTULOS_CADASTRO if fonte == "cadastro" else ROTULOS_ATIVIDADE)
    _mostrar_comparacao(previa)
    _confirmacao(fonte, previa)


def preparar_extras(fonte: str, chave_demo: str | None) -> dict:
    """Entradas adicionais da importação de atividade: data e hora da exportação."""
    if fonte != "atividade":
        return {}
    fuso = ctx.cfg.fuso_horario
    padrao = REFERENCIAS_DEMO.get(chave_demo) if chave_demo else None
    informar = st.checkbox(
        "Informar a data e a hora da exportação", value=padrao is not None, key="atividade_informar_ref",
        help="Necessária para converter tempos relativos (“3 dias 2 horas”) em datas. Sem ela, o painel mostra "
             "o tempo sem acesso no momento da exportação, sem inventar datas.",
    )
    if not informar:
        return {"referencia": None}
    c1, c2 = st.columns(2)
    dia = c1.date_input("Data da exportação", value=padrao.date() if padrao else None, format="DD/MM/YYYY",
                        key="atividade_data_ref")
    hora = c2.time_input("Hora da exportação", value=padrao.time() if padrao else time(12, 0), key="atividade_hora_ref",
                         step=300)
    if padrao:
        ui.nota("Valor da demonstração preenchido automaticamente.")
    ui.nota(f"Fuso horário: {fuso}.")
    if not dia:
        return {"referencia": None}
    return {"referencia": datetime.combine(dia, hora).replace(tzinfo=ZoneInfo(fuso)).isoformat()}


def _preparar_cadastro(tabelas, manual, extras):
    return importacao.preparar_cadastro(tabelas, ctx.pseudo, manual)


def _preparar_atividade(tabelas, manual, extras):
    referencia = datetime.fromisoformat(extras["referencia"]) if extras.get("referencia") else None
    return importacao.preparar_atividade(tabelas, ctx.pseudo, referencia, ctx.cfg.fuso_horario,
                                         ctx.base.parametros["papeis_cursista"], manual)


if mensagem := st.session_state.pop("mensagem_admin", None):
    st.success(mensagem, icon=":material/check_circle:")

abas = st.tabs(["Cadastro", "Atividade", "Base escolar", "Parâmetros", "Histórico e auditoria"])

with abas[0]:
    ui.nota("Aceita um ou mais arquivos .xlsx ou .csv com a mesma estrutura (por exemplo, a planilha principal e a "
            "lista de novos inscritos); juntos, eles formam a nova versão completa do cadastro. CPF e data de "
            "nascimento são usados só na validação e não são gravados.")
    _fluxo("cadastro", CAMPOS_CADASTRO, ("xlsx", "csv"), _preparar_cadastro)

with abas[1]:
    ui.nota("Aceita a exportação de participantes do Moodle (.xlsx ou .csv) ou o texto copiado da página "
            "“Participantes” (.txt). Situação da conta e último acesso são lidos como exportados.")
    _fluxo("atividade", CAMPOS_ATIVIDADE, ("xlsx", "csv", "txt"), _preparar_atividade)

with abas[2]:
    meta = ctx.base.meta.get("escolas")
    if meta:
        ui.lista_definicoes([
            ("Base em uso", meta.get("referencia_descricao")),
            ("Escolas na base", metrics.numero(meta.get("n_registros"))),
            ("Importada em", meta.get("importado_em")),
        ])
    else:
        ui.nota("Nenhuma base escolar carregada.")
    st.markdown(
        "Não existe API pública documentada para consultar escolas pelo código INEP. O painel usa os "
        f"[microdados do Censo Escolar]({config.PAGINA_MICRODADOS_INEP}) (arquivo oficial, com cache "
        f"local) ou a exportação do [Catálogo de Escolas]({config.PAGINA_CATALOGO_ESCOLAS})."
    )
    cursistas = ctx.base.cursistas
    codigos = set(cursistas.loc[cursistas["inep_status"] == "valido", "inep"])
    # UFs do cadastro e das próprias escolas (o código INEP começa pelo código da UF)
    ufs = set(cursistas["uf"].dropna()) | {config.UFS[c[:2]][0] for c in codigos}
    opcoes = (["Base fictícia da demonstração"] if demo else []) + [
        "Baixar microdados oficiais do Inep", "Importar pacote de microdados já baixado (ZIP ou CSV)",
        "Importar exportação do Catálogo de Escolas (XLSX ou CSV)"]
    modo = st.radio("Origem da base escolar", opcoes, key="escolas_modo")
    estado_escolas = st.session_state.get("previa_escolas", {})
    previa = estado_escolas.get("previa") if estado_escolas.get("modo") == modo else None

    def guardar(previa_nova):
        st.session_state["previa_escolas"] = {"modo": modo, "previa": previa_nova}

    try:
        if modo == "Base fictícia da demonstração":
            if st.button("Processar base fictícia"):
                from src.ambiente import arquivos_demonstracao

                caminho = arquivos_demonstracao()["escolas"]
                dados, info = school_data.ler_microdados(caminho.read_bytes(), caminho.name, codigos, ufs)
                previa = school_data.preparar_escolas(school_data.normalizar_microdados(dados), info,
                                                      school_data.FONTE_SINTETICA, [{"arquivo": caminho.name}])
                guardar(previa)
        elif modo == "Baixar microdados oficiais do Inep":
            if demo:
                ui.nota("Desativado na demonstração.")
            else:
                ano = st.selectbox("Ano do Censo Escolar", sorted(config.URLS_MICRODADOS_INEP, reverse=True))
                st.caption(f"Endereço oficial: {config.URLS_MICRODADOS_INEP[ano]}")
                if st.button("Baixar (ou usar cópia em cache) e processar"):
                    barra = st.progress(0.0, text="Baixando o pacote oficial…")
                    caminho, info_download = school_data.baixar_microdados(
                        ano, ctx.cfg.dir_dados / "cache_inep", lambda p: barra.progress(p, text="Baixando o pacote oficial…"))
                    barra.progress(1.0, text="Lendo o arquivo de escolas…")
                    dados, info = school_data.ler_microdados(caminho, caminho.name, codigos, ufs)
                    info["download"] = info_download
                    previa = school_data.preparar_escolas(school_data.normalizar_microdados(dados), info,
                                                          school_data.FONTE_MICRODADOS,
                                                          [{"arquivo": caminho.name, "publicado_em": info_download.get("publicado_em")}],
                                                          url=info_download.get("url"))
                    barra.empty()
                    guardar(previa)
        elif modo == "Importar pacote de microdados já baixado (ZIP ou CSV)":
            if demo:
                ui.nota("Desativado na demonstração.")
            else:
                enviado = st.file_uploader("Pacote de microdados", type=["zip", "csv"], key="envio_microdados")
                if enviado and st.button("Processar pacote"):
                    from src.loaders import identificar_formato

                    conteudo = enviado.getvalue()
                    identificar_formato(enviado.name, conteudo, ("zip", "csv"))
                    dados, info = school_data.ler_microdados(conteudo, enviado.name, codigos, ufs)
                    previa = school_data.preparar_escolas(school_data.normalizar_microdados(dados), info,
                                                          school_data.FONTE_MICRODADOS, [{"arquivo": enviado.name}])
                    guardar(previa)
        else:
            if demo:
                ui.nota("Desativado na demonstração.")
            else:
                enviado = st.file_uploader("Exportação do Catálogo de Escolas", type=["xlsx", "csv"], key="envio_catalogo")
                ano_ref = st.number_input("Ano de referência (Censo Escolar) indicado no Catálogo", min_value=2007,
                                          max_value=datetime.now().year, value=None, step=1)
                if enviado and ano_ref and st.button("Processar exportação"):
                    tabela = ler_tabela(enviado.name, enviado.getvalue(), school_data.CAMPOS_CATALOGO)
                    dados, info = school_data.normalizar_catalogo(tabela, int(ano_ref))
                    previa = school_data.preparar_escolas(dados, info, school_data.FONTE_CATALOGO, [tabela.metadados()])
                    guardar(previa)
                ui.nota("No Catálogo (Inep Data), filtre as UFs desejadas e exporte a tabela. O ano de referência "
                        "deve ser informado conforme exibido no próprio Catálogo; o painel não o presume.")
    except ErroImportacao as exc:
        st.error(str(exc))
    if previa is not None:
        resumo = previa.resumo
        cobertura = len(codigos & set(previa.registros["co_entidade"])) if codigos else 0
        ui.lista_definicoes([
            ("Fonte", resumo.get("fonte")), ("Ano de referência", resumo.get("ano_referencia")),
            ("Escolas selecionadas", metrics.numero(len(previa.registros))),
            ("Códigos do cadastro encontrados", f"{metrics.numero(cobertura)} de {metrics.numero(len(codigos))}"),
            ("Integridade (MD5 publicado)", {True: "confere", False: "NÃO confere", None: "não verificada"}[resumo.get("md5_confere")]),
            ("Variáveis ausentes no arquivo", ", ".join(resumo.get("variaveis_ausentes") or []) or "nenhuma"),
        ])
        for bloqueio in previa.bloqueios:
            st.error(bloqueio)
        _confirmacao("escolas", previa)

with abas[3]:
    parametros = ctx.base.parametros
    with st.form("parametros"):
        st.markdown("**Faixas de tempo desde o último acesso (dias)**")
        c1, c2, c3 = st.columns(3)
        l1 = c1.number_input("Fim da 1ª faixa (1 = até 24 horas)", 1, 365, int(parametros["faixas_inatividade_dias"][0]))
        l2 = c2.number_input("Fim da 2ª faixa", 2, 365, int(parametros["faixas_inatividade_dias"][1]))
        l3 = c3.number_input("Fim da 3ª faixa", 3, 730, int(parametros["faixas_inatividade_dias"][2]))
        c4, c5 = st.columns(2)
        janela = c4.number_input("Acesso recente: últimos (dias)", 1, 365, int(parametros["janela_acesso_recente_dias"]))
        limite = c5.number_input("Requer acompanhamento quando sem acesso há mais de (dias)", 1, 365,
                                 int(parametros["limite_acompanhamento_dias"]))
        papeis_existentes = sorted({p.strip() for v in ctx.base.contas.get("papeis", pd.Series(dtype=str)).dropna()
                                    for p in v.split(",") if p.strip()} | set(parametros["papeis_cursista"]))
        papeis = st.multiselect("Papéis considerados de cursista", papeis_existentes, default=parametros["papeis_cursista"])
        situacoes_existentes = sorted(set(ctx.base.contas.get("situacao_conta", pd.Series(dtype=str)).dropna())
                                      | set(parametros["situacoes_conta_ativa"]))
        ativas = st.multiselect("Situações de conta consideradas ativas", situacoes_existentes,
                                default=parametros["situacoes_conta_ativa"])
        ui.nota("Parâmetros operacionais do acompanhamento, não definições oficiais de evasão ou abandono. "
                "Alterá-los recalcula as faixas e os indicadores para todos os usuários.")
        if st.form_submit_button("Salvar parâmetros", type="primary"):
            if not (l1 < l2 < l3):
                st.error("As faixas precisam ser crescentes.")
            elif not papeis or not ativas:
                st.error("Selecione ao menos um papel de cursista e uma situação ativa.")
            else:
                ctx.repo.salvar_parametros({
                    "faixas_inatividade_dias": [int(l1), int(l2), int(l3)], "limite_acompanhamento_dias": int(limite),
                    "janela_acesso_recente_dias": int(janela),
                    "papeis_cursista": papeis, "situacoes_conta_ativa": ativas}, ctx.usuario.identificador)
                st.session_state["mensagem_admin"] = "Parâmetros salvos."
                st.rerun()

with abas[4]:
    st.markdown("#### Importações")
    ui.tabela(ctx.repo.historico(), {"id": "Nº", "fonte": "Fonte", "status": "Situação", "importado_em": "Em (UTC)",
                                     "importado_por": "Por", "referencia_descricao": "Referência",
                                     "n_registros": "Registros", "n_com_problemas": "Com problemas"})
    st.markdown("#### Registro de auditoria")
    ui.nota("Importações, decisões de conciliação, alterações de parâmetros, exportações e consultas a dados de "
            "contato. Os alvos aparecem pseudonimizados.")
    ui.tabela(ctx.repo.auditoria(), {"momento": "Momento (UTC)", "usuario": "Usuário", "acao": "Ação",
                                     "alvo": "Alvo", "detalhe": "Detalhe"}, altura=360)
    st.markdown("#### Relatórios operacionais")
    resultados = metrics.calcular(ctx.cursistas, ctx.contas, ctx.base, ctx.base.parametros)
    indicadores = pd.DataFrame([{
        "indicador": r.indicador.nome, "valor": metrics.valor_formatado(r), "numerador": r.numerador,
        "denominador": r.denominador, "unidade": r.indicador.unidade, "definicao": r.indicador.definicao,
        "fonte": r.indicador.fonte, "observacao": r.motivo or "",
    } for r in resultados.values()])
    ui.exportacao_controlada(ctx, indicadores, {c: c.capitalize() for c in indicadores.columns},
                             "indicadores_recorte_atual.csv", "Baixar indicadores do recorte atual")
