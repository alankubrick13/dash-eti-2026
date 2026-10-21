"""Componentes de interface compartilhados pelas páginas."""

from __future__ import annotations

import base64
import html
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from . import config, graficos, metrics


def aplicar_estilo() -> None:
    if config.ARQ_CSS.exists():
        st.html(f"<style>{config.ARQ_CSS.read_text(encoding='utf-8')}</style>")


def _data_local(iso: str | None, fuso: str, com_hora: bool = True) -> str | None:
    if not iso:
        return None
    try:
        momento = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    if momento.tzinfo is not None:
        momento = momento.astimezone(ZoneInfo(fuso))
    return momento.strftime("%d/%m/%Y %H:%M" if com_hora else "%d/%m/%Y")


def referencias_dados(base, fuso: str) -> list[tuple[str, str]]:
    """Identificação do período/versão de cada fonte, para o cabeçalho e as notas."""
    itens = []
    cad, atv, esc = base.meta.get("cadastro"), base.meta.get("atividade"), base.meta.get("escolas")
    itens.append(("Cadastro", f"importado em {_data_local(cad['importado_em'], fuso, False)}" if cad else "não importado"))
    if atv:
        if atv.get("referencia_em"):
            texto = f"exportação de {_data_local(atv['referencia_em'], fuso)}"
        else:
            texto = f"importada em {_data_local(atv['importado_em'], fuso, False)} (data de exportação não informada)"
    else:
        texto = "não importada"
    itens.append(("Atividade", texto))
    itens.append(("Escolas", f"Censo Escolar {esc['referencia_em']}" if esc and esc.get("referencia_em") else
                  "base oficial não carregada"))
    return itens


def _marca_oficial() -> str | None:
    """Marca do Programa (arquivo em assets/marca/), sem alterações de cor ou proporção."""
    for nome, tipo in (("marca_eti.svg", "image/svg+xml"), ("marca_eti.png", "image/png")):
        arquivo = config.DIR_MARCA / nome
        if arquivo.exists():
            dados = base64.b64encode(arquivo.read_bytes()).decode()
            # Largura acima do mínimo de 157 px (manual, seção 3); o espaço ao redor é a área de proteção.
            return f'<img class="eti-marca" src="data:{tipo};base64,{dados}" alt="Escola em Tempo Integral">'
    return None


def recorte_territorial(base) -> str:
    """Ex.: "Região Norte · Ciclo 2026", a partir dos próprios dados."""
    partes = []
    if base.tem_cadastro:
        regioes = base.cursistas["regiao"].dropna().unique()
        if len(regioes) == 1:
            partes.append(f"Região {regioes[0]}")
        ciclos = base.cursistas["ciclo"].dropna().unique()
        if len(ciclos) == 1:
            partes.append(f"Ciclo {ciclos[0]}")
    return " · ".join(partes)


def chamada(base) -> str:
    """Linha de contexto acima dos títulos: "Escola em Tempo Integral · Região Norte"."""
    regioes = base.cursistas["regiao"].dropna().unique() if base.tem_cadastro else []
    return "Escola em Tempo Integral" + (f" · Região {regioes[0]}" if len(regioes) == 1 else "")


def fonte_atividade(base, fuso: str) -> str:
    atv = base.meta.get("atividade") or {}
    if atv.get("referencia_em"):
        quando = f"posição de {_data_local(atv['referencia_em'], fuso)}"
    else:
        quando = f"importado em {_data_local(atv.get('importado_em'), fuso, False)}, data da exportação não informada"
    return f"Fonte: relatório de participantes da plataforma do curso, {quando}."


def fonte_cadastro(base, fuso: str) -> str:
    cad = base.meta.get("cadastro") or {}
    return f"Fonte: cadastro dos cursistas, importado em {_data_local(cad.get('importado_em'), fuso, False)}."


def fonte_escolas(base) -> str:
    esc = base.meta.get("escolas") or {}
    return f"Fonte: {esc.get('referencia_descricao')}." if esc else "Base escolar oficial não carregada."


def cabecalho(cfg, base) -> None:
    referencias = "".join(
        f'<div class="eti-ref"><span class="eti-ref-rotulo">{html.escape(r)}</span>'
        f'<span class="eti-ref-valor">{html.escape(v)}</span></div>'
        for r, v in referencias_dados(base, cfg.fuso_horario)
    )
    marca = _marca_oficial() if cfg.exibir_marca else None
    marca_html = f'<div class="eti-marca-bloco">{marca}</div>' if marca else ""
    programa = "" if marca else f'<div class="eti-programa">{html.escape(config.NOME_PROGRAMA)}</div>'
    territorio = recorte_territorial(base)
    demo = ('<div class="eti-demo">Demonstração com dados fictícios. Nenhuma informação corresponde a '
            'pessoas ou escolas reais.</div>') if cfg.demonstracao else ""
    st.html(
        f'<header class="eti-cabecalho">{marca_html}<div class="eti-identidade">{programa}'
        f'<div class="eti-ferramenta">{html.escape(config.NOME_FERRAMENTA)}</div>'
        + (f'<div class="eti-territorio">{html.escape(territorio)}</div>' if territorio else "")
        + f'<div class="eti-natureza">{html.escape(config.AVISO_NATUREZA)}</div></div>'
        f'<div class="eti-refs">{referencias}</div></header>{demo}'
    )


def titulo_pagina(titulo: str, descricao: str | None = None) -> None:
    st.markdown(f"# {titulo}")
    if descricao:
        st.html(f'<p class="eti-lead">{html.escape(descricao)}</p>')


def secao(titulo: str, descricao: str | None = None) -> None:
    st.markdown(f"## {titulo}")
    if descricao:
        st.html(f'<p class="eti-descricao">{html.escape(descricao)}</p>')


def nota(texto: str) -> None:
    st.html(f'<p class="eti-nota">{html.escape(texto)}</p>')


def recorte(ctx) -> None:
    """Explicita a população de referência quando há filtros ativos."""
    if ctx.filtros_ativos:
        rotulos = dict(_rotulos_filtros())
        partes = [f"{rotulos[c]}: {', '.join(map(str, v[:3]))}{'…' if len(v) > 3 else ''}"
                  for c, v in ctx.filtros.items() if v]
        nota(f"Recorte aplicado — {'; '.join(partes)}. "
             f"{metrics.numero(len(ctx.cursistas))} de {metrics.numero(len(ctx.base.cursistas))} registros.")


def _rotulos_filtros():
    from .painel import FILTROS

    return FILTROS


def indicadores(resultados: list[metrics.Resultado], colunas: int = 4) -> None:
    """Uma linha de indicadores; cada um com definição (ícone de ajuda) e numerador/denominador."""
    cols = st.columns(colunas)
    for coluna, resultado in zip(cols, resultados):
        with coluna:
            st.metric(resultado.indicador.nome, metrics.valor_formatado(resultado),
                      help=metrics.ajuda(resultado.indicador))
            st.html(f'<p class="eti-metrica-contexto">{html.escape(metrics.contexto_formatado(resultado))}</p>')


def colunas(espec, chave: str, gap: str = "large", **kwargs):
    """Colunas de conteúdo (gráficos, fichas) que se empilham quando a área útil fica estreita.

    O contêiner recebe a classe ``st-key-colunas_<chave>``, e o CSS dá uma largura mínima a cada coluna.
    """
    with st.container(key=f"colunas_{chave}"):
        return st.columns(espec, gap=gap, **kwargs)


def clicavel(conteudo_html: str, chave: str, rotulo: str, ao_clicar, args: tuple = (), ativo: bool = False) -> None:
    """Bloco HTML inteiro clicável: um botão transparente cobre o bloco (CSS ``st-key-clic_*``/``st-key-alvo_*``).

    O rótulo do botão é o que leitores de tela anunciam; o foco do teclado contorna o bloco.
    """
    with st.container(key=f"clic_{'ativo_' if ativo else ''}{chave}"):
        st.html(conteudo_html)
        st.button(rotulo, key=f"alvo_{chave}", on_click=ao_clicar, args=args)


def grade(itens: list, desenhar, chave: str) -> None:
    """Cartões numa grade CSS responsiva (CSS ``st-key-grade_*``): tantas colunas quantas couberem."""
    with st.container(key=f"grade_{chave}"):
        for i, item in enumerate(itens):
            desenhar(i, item)


def filtros_em_cartoes(opcoes: list[tuple[str, int, str]], total: int, chave: str) -> str:
    """Cartões de filtro (rótulo, contagem, cor), um deles ativo; devolve o rótulo escolhido."""
    estado = f"{chave}_escolha"
    rotulos = [r for r, _, _ in opcoes]
    if st.session_state.get(estado) not in rotulos:
        st.session_state[estado] = rotulos[0]

    def escolher(rotulo: str) -> None:
        st.session_state[estado] = rotulo
        st.session_state[f"{chave}_limite"] = None  # volta ao início da galeria

    from .cartoes import filtro

    with st.container(key=f"filtros_{chave}"):
        for i, (rotulo, valor, cor) in enumerate(opcoes):
            clicavel(filtro(rotulo, valor, total, cor), f"filtro_{chave}_{i}", f"Mostrar: {rotulo} ({valor})",
                     escolher, (rotulo,), ativo=st.session_state[estado] == rotulo)
    return st.session_state[estado]


def mais_itens(total: int, chave: str, passo: int = 24) -> int:
    """Quantos itens mostrar na galeria; o botão "Mostrar mais" acrescenta ``passo``."""
    estado = f"{chave}_limite"
    limite = st.session_state.get(estado) or passo
    st.session_state[estado] = limite
    return min(limite, total)


def botao_mais(mostrados: int, total: int, chave: str, passo: int = 24, unidade: str = "itens") -> None:
    estado = f"{chave}_limite"
    if mostrados >= total:
        return

    def mais() -> None:
        st.session_state[estado] = (st.session_state.get(estado) or passo) + passo

    _, centro, _ = st.columns([1, 1.2, 1])
    centro.button(f"Mostrar mais {unidade} ({metrics.numero(total - mostrados)} restantes)", on_click=mais,
                  key=f"{chave}_mais", width="stretch", icon=":material/expand_more:")


def _cabecalho_html(titulo: str, subtitulo: str | None, chamada_texto: str | None) -> str:
    e = html.escape
    return ((f'<div class="viz-chamada">{e(chamada_texto)}</div>' if chamada_texto else "")
            + f'<div class="viz-titulo">{e(titulo)}</div>'
            + (f'<p class="viz-sub">{e(subtitulo)}</p>' if subtitulo else ""))


def cabecalho_grafico(titulo: str, subtitulo: str | None = None, chamada_texto: str | None = None,
                      destaque: bool = False) -> None:
    """Chamada, título e subtítulo de uma figura cujo corpo vem depois (mapa, ou gráfico com controle no meio)."""
    st.html(f'<figure class="viz{" viz-destaque" if destaque else ""}">'
            f'{_cabecalho_html(titulo, subtitulo, chamada_texto)}</figure>')


def grafico(fig, tabela: pd.DataFrame | None = None, chave: str | None = None, nota_texto: str | None = None,
            fonte: str | None = None, chamada_texto: str | None = None, destaque: bool = False,
            cabecalho: bool = True) -> None:
    """Figura completa: chamada, título, subtítulo, gráfico, legenda, nota e fonte; tabela equivalente abaixo.

    Com ``cabecalho=False`` o título já foi escrito antes (``cabecalho_grafico``) e sai só o corpo.
    """
    if isinstance(fig, graficos.Visual):
        e = html.escape
        legenda = "".join(f'<span><i style="background:{cor}"></i>{e(nome)}</span>' for nome, cor in fig.legenda)
        st.html(
            f'<figure class="viz{" viz-destaque" if destaque else ""}">'
            + (_cabecalho_html(fig.titulo, fig.subtitulo, chamada_texto) if cabecalho else "")
            + f'<div class="viz-corpo{"" if cabecalho else " viz-corpo-solto"}">{fig.corpo}</div>'
            + (f'<div class="viz-legenda">{legenda}</div>' if legenda else "")
            + (f'<p class="viz-nota">{e(nota_texto)}</p>' if nota_texto else "")
            + (f'<p class="viz-fonte">{e(fonte)}</p>' if fonte else "")
            + "</figure>"
        )
    else:
        meta = fig.layout.meta or {}
        if meta.get("titulo") and cabecalho:
            cabecalho_grafico(meta["titulo"], meta.get("subtitulo"), chamada_texto, destaque)
        st.plotly_chart(fig, theme=None, config=graficos.CONFIG, width="stretch", key=chave)
        if nota_texto:
            nota(nota_texto)
    if tabela is not None:
        with st.expander("Ver dados do gráfico"):
            st.dataframe(tabela, hide_index=True, width="stretch")


def texto_valor(valor) -> str:
    from .normalization import eh_vazio

    if isinstance(valor, bool):
        return "Sim" if valor else "Não"
    if eh_vazio(valor) or valor is pd.NA:
        return "—"
    return str(valor)


def lista_definicoes(pares: list[tuple[str, object]]) -> None:
    """Pares rótulo/valor em grade de duas colunas (uma coluna em telas estreitas)."""
    itens = "".join(f"<dt>{html.escape(r)}</dt><dd>{html.escape(texto_valor(v))}</dd>" for r, v in pares)
    st.html(f'<dl class="eti-dl">{itens}</dl>')


def cabecalho_ficha(chamada_texto: str, titulo: str, detalhes: list[str]) -> None:
    pilulas = "".join(f'<span class="eti-pilula">{html.escape(d)}</span>' for d in detalhes if d)
    st.html(f'<div class="eti-ficha-cabecalho"><div class="viz-chamada">{html.escape(chamada_texto)}</div>'
            f'<div class="eti-ficha-titulo">{html.escape(titulo)}</div><div class="eti-pilulas">{pilulas}</div></div>')


def tabela(df: pd.DataFrame, rotulos: dict[str, str], altura: int | None = None, **kwargs) -> None:
    """Tabela com colunas renomeadas para rótulos legíveis (apenas as colunas listadas)."""
    visivel = df[[c for c in rotulos if c in df.columns]].rename(columns=rotulos)
    # Ausência aparece como traço, nunca como "None"/"nan"
    texto = [c for c in visivel.columns if visivel[c].dtype == object or pd.api.types.is_string_dtype(visivel[c])]
    visivel[texto] = visivel[texto].fillna("—")
    argumentos = {"hide_index": True, "width": "stretch", **kwargs}
    if altura:
        argumentos["height"] = altura
    return st.dataframe(visivel, **argumentos)


def exportacao_controlada(ctx, df: pd.DataFrame, rotulos: dict[str, str], nome_arquivo: str, rotulo_botao: str) -> None:
    """Exportação apenas para administradores, sem colunas de contato, registrada na auditoria."""
    if not ctx.usuario.administrador:
        nota("Exportação disponível apenas para administradores.")
        return
    proibidas = {"email", "conta_email", "telefone", "whatsapp", "raca_cor", "genero", "cpf"}
    colunas = [c for c in rotulos if c in df.columns and c not in proibidas]
    conteudo = df[colunas].rename(columns=rotulos).to_csv(index=False, sep=";").encode("utf-8-sig")

    def registrar() -> None:
        ctx.repo.auditar(ctx.usuario.identificador, "exportacao", nome_arquivo, f"{len(df)} linhas")

    st.download_button(rotulo_botao, conteudo, file_name=nome_arquivo, mime="text/csv", on_click=registrar,
                       key=f"exportar_{nome_arquivo}")


def vazio(mensagem: str) -> None:
    st.html(f'<div class="eti-vazio">{html.escape(mensagem)}</div>')


def selo(texto: str, cor: str = "gray") -> str:
    return f":{cor}-badge[{texto}]"


# ---------------------------------------------------------------- telas de acesso


def _tela(titulo: str, texto: str) -> None:
    st.html(
        f'<div class="eti-tela"><div class="eti-programa">{html.escape(config.NOME_PROGRAMA)}</div>'
        f'<h1>{html.escape(titulo)}</h1><p>{html.escape(texto)}</p>'
        f'<p class="eti-natureza">{html.escape(config.AVISO_NATUREZA)}</p></div>'
    )


def tela_login() -> None:
    _tela(config.NOME_FERRAMENTA,
          "Acesso restrito a coordenadores autorizados. Entre com a sua conta institucional.")
    provedor = config.ler_opcao("ETI_PROVEDOR_OIDC")
    _, centro, _ = st.columns([1, 1, 1])
    with centro:
        if st.button("Entrar", type="primary", width="stretch"):
            if provedor:
                st.login(provedor)
            else:
                st.login()


def tela_acesso_negado(texto: str, permitir_sair: bool = False) -> None:
    _tela("Acesso não autorizado", texto + " Procure a coordenação geral para solicitar acesso.")
    if permitir_sair:
        _, centro, _ = st.columns([1, 1, 1])
        with centro:
            if st.button("Sair", width="stretch"):
                st.logout()


def tela_configuracao_pendente(texto: str) -> None:
    _tela("Configuração necessária", texto)
