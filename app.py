"""Painel de acompanhamento da formação — Programa Escola em Tempo Integral.

Ponto de entrada: autenticação, carga dos dados, filtros globais e navegação.
As páginas ficam em ``paginas/`` (e não em ``pages/``) para que nenhuma delas
seja acessível sem passar por este arquivo, onde está a barreira de acesso.

Execução: streamlit run app.py   (ver README para os modos de execução)
"""

import streamlit as st

st.set_page_config(
    page_title="Acompanhamento da formação · Escola em Tempo Integral",
    page_icon=":material/school:",
    layout="wide",
    initial_sidebar_state="auto",
)

from src import ambiente, config, fichas, painel, pasta, publicacao, security, ui  # noqa: E402

PAGINAS = (
    ("Acompanhamento", "paginas/1_visao_geral.py", "Visão geral", "visao-geral", False),
    ("Acompanhamento", "paginas/2_cursistas.py", "Cursistas", "cursistas", False),
    ("Acompanhamento", "paginas/4_escolas.py", "Escolas", "escolas", False),
    ("Acompanhamento", "paginas/3_atividade.py", "Atividade e participação", "atividade", False),
    ("Acompanhamento", "paginas/5_territorio.py", "Mapa e território", "territorio", False),
    ("Gestão dos dados", "paginas/6_qualidade_conciliacao.py", "Qualidade e conciliação", "qualidade", False),
    ("Gestão dos dados", "paginas/7_administracao.py", "Administração", "administracao", True),
)


def _limpar_filtros() -> None:
    for coluna, _ in painel.FILTROS:
        st.session_state[f"filtro_{coluna}"] = []


def barra_lateral(base: painel.Base, cfg, usuario) -> dict[str, list]:
    filtros: dict[str, list] = {}
    rotulos = dict(painel.FILTROS)
    with st.sidebar:
        st.markdown("#### Filtros")
        if not base.tem_cadastro:
            st.caption("Os filtros ficam disponíveis depois da importação do cadastro.")
        else:
            principais = [c for c, _ in painel.FILTROS if c in painel.FILTROS_PRINCIPAIS]
            extras = [c for c, _ in painel.FILTROS if c not in painel.FILTROS_PRINCIPAIS]

            def campo(coluna: str) -> None:
                opcoes = painel.opcoes_filtro(base, coluna, filtros)
                chave = f"filtro_{coluna}"
                selecionados = [v for v in st.session_state.get(chave, []) if v in opcoes]
                st.session_state[chave] = selecionados
                if len(opcoes) > 1 or selecionados:
                    filtros[coluna] = st.multiselect(rotulos[coluna], opcoes, key=chave, placeholder="Todos")

            for coluna in principais:
                campo(coluna)
            abertos = any(st.session_state.get(f"filtro_{c}") for c in extras)
            with st.expander("Mais filtros", expanded=abertos):
                for coluna in extras:
                    campo(coluna)
            if any(filtros.values()):
                st.button("Limpar filtros", on_click=_limpar_filtros, width="stretch")
            st.caption("Os filtros valem para todas as páginas.")
        st.divider()
        st.caption(f"Usuário: {usuario.nome}")
        if usuario.metodo == "oidc" and st.button("Sair", width="stretch"):
            st.logout()
        st.caption(config.AVISO_NATUREZA)
    return filtros


def main() -> None:
    try:
        cfg = config.carregar_configuracao()
    except ValueError as exc:
        ui.tela_configuracao_pendente(str(exc))
        st.stop()
    logger = security.configurar_logging()
    ui.aplicar_estilo()
    usuario = security.resolver_usuario(cfg)  # interrompe a execução se não autorizado
    try:
        repo, pseudo = ambiente.obter_repositorio(cfg)
    except (RuntimeError, ValueError) as exc:
        ui.tela_configuracao_pendente(str(exc))
        st.stop()
    # Os dados são os arquivos colocados na pasta (no painel online, a versão publicada já traz tudo)
    leitura = pasta.sincronizar(repo, pseudo, cfg) if cfg.ambiente == "local" else pasta.Resultado()
    if leitura.importadas:  # arquivos novos na pasta: a versão publicada acompanha (falta só enviá-la)
        try:
            publicacao.gerar(cfg.dir_dados / "eti.sqlite3", security.obter_chave_pseudonimizacao(cfg), cfg.pasta_publicada)
        except Exception:
            logger.exception("falha ao gerar a versão publicada")
    base = painel.carregar_base(repo)
    filtros = barra_lateral(base, cfg, usuario)
    cursistas, contas = painel.aplicar_filtros(base, filtros)
    st.session_state["_contexto"] = painel.Contexto(cfg, usuario, repo, base, filtros, cursistas, contas, pseudo)

    secoes: dict[str, list] = {}
    for secao, arquivo, titulo, caminho, restrita in PAGINAS:
        if restrita and not usuario.administrador:
            continue
        secoes.setdefault(secao, []).append(
            st.Page(arquivo, title=titulo, url_path=caminho, default=(caminho == "visao-geral"))
        )
    navegacao = st.navigation(secoes, position="sidebar")
    ui.cabecalho(cfg, base)
    if leitura.importadas:
        st.toast("Dados atualizados a partir dos arquivos da pasta: " + "; ".join(leitura.importadas) + ".",
                 icon=":material/sync:")
    for problema in leitura.problemas:
        st.error(problema, icon=":material/error:")
    try:
        fichas.abrir_pendente()  # ficha de escola ou de cursista pedida por um clique (gaveta lateral)
        navegacao.run()
    except Exception:
        # Mensagem genérica na tela; o log (com filtro de dados pessoais) guarda o tipo do erro.
        logger.exception("erro ao renderizar a página %s", navegacao.title)
        st.error("Ocorreu um erro ao montar esta página. A equipe responsável pode consultar o registro do servidor.")


main()
