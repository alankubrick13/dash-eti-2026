"""Componentes de interface compartilhados pelas páginas."""

from __future__ import annotations

import base64
import html
import math
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from . import config, graficos, metrics, painel

IR_PARA = "_ir_para"  # página pedida por um clique (o app troca de página antes de desenhar a atual)


def aplicar_estilo() -> None:
    if config.ARQ_CSS.exists():
        st.html(f"<style>{config.ARQ_CSS.read_text(encoding='utf-8')}</style>")


def data_local(iso: str | None, fuso: str, com_hora: bool = True) -> str | None:
    if not iso:
        return None
    try:
        momento = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    if momento.tzinfo is not None:
        momento = momento.astimezone(ZoneInfo(fuso))
    return momento.strftime("%d/%m/%Y %H:%M" if com_hora else "%d/%m/%Y")


def periodo_respostas(base) -> str | None:
    """Período das respostas às inscrições no cadastro (ex.: "08/07 a 13/08/2026"), pela própria data de resposta."""
    if not base.tem_cadastro or "data_resposta" not in base.cursistas:
        return None
    datas = pd.to_datetime(base.cursistas["data_resposta"], errors="coerce", format="%Y-%m-%d").dropna()
    if datas.empty:
        return None
    inicio, fim = datas.min(), datas.max()
    if inicio == fim:
        return f"{fim:%d/%m/%Y}"
    return f"{inicio:%d/%m} a {fim:%d/%m/%Y}" if inicio.year == fim.year else f"{inicio:%d/%m/%Y} a {fim:%d/%m/%Y}"


def referencias_dados(base, fuso: str) -> list[tuple[str, str]]:
    """Identificação do período/versão de cada fonte, para o cabeçalho e as notas."""
    itens = []
    cad, atv, esc = base.meta.get("cadastro"), base.meta.get("atividade"), base.meta.get("escolas")
    periodo = periodo_respostas(base)
    if cad:
        itens.append(("Cadastro", f"respostas de {periodo}" if periodo else
                      f"importado em {data_local(cad['importado_em'], fuso, False)}"))
    else:
        itens.append(("Cadastro", "não importado"))
    if atv:
        if atv.get("referencia_em"):
            texto = f"posição de {data_local(atv['referencia_em'], fuso)}"
        else:
            texto = f"importada em {data_local(atv['importado_em'], fuso, False)} (data de exportação não informada)"
    else:
        texto = "não encontrada na pasta"
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
        quando = f"posição de {data_local(atv['referencia_em'], fuso)}"
    else:
        quando = f"importado em {data_local(atv.get('importado_em'), fuso, False)}, data da exportação não informada"
    return f"Fonte: relatório de participantes da plataforma do curso, {quando}."


def fonte_cadastro(base, fuso: str) -> str:
    cad = base.meta.get("cadastro") or {}
    periodo = periodo_respostas(base)
    return (f"Fonte: cadastro dos cursistas{f' (respostas de {periodo})' if periodo else ''}, "
            f"lido em {data_local(cad.get('importado_em'), fuso, False)}.")


def fonte_escolas(base) -> str:
    esc = base.meta.get("escolas") or {}
    return f"Fonte: {esc.get('referencia_descricao')}." if esc else "Base escolar oficial não carregada."


def publicado_em(cfg) -> str | None:
    """Data e hora em que a versão publicada (painel online) foi gerada."""
    from .publicacao import data_publicacao

    return data_local(data_publicacao(cfg.pasta_publicada), cfg.fuso_horario)


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
    if cfg.ambiente == "publicacao":
        publicado = publicado_em(cfg)
        selo = f"Dados reais · versão publicada em {publicado}" if publicado else "Dados reais · versão publicada"
    else:
        selo = "Dados reais · uso local neste computador" if cfg.ambiente == "local" else "Dados reais · acesso autenticado"
    modo = (f'<div class="eti-modo"><span class="eti-icone" aria-hidden="true">verified_user</span>{html.escape(selo)}'
            "</div>")
    st.html(
        f'<header class="eti-cabecalho">{marca_html}<div class="eti-identidade">{programa}'
        f'<div class="eti-ferramenta">{html.escape(config.NOME_FERRAMENTA)}</div>'
        + (f'<div class="eti-territorio">{html.escape(territorio)}</div>' if territorio else "")
        + f'<div class="eti-natureza">{html.escape(config.AVISO_NATUREZA)}</div>{modo}</div>'
        f'<div class="eti-refs">{referencias}</div></header>'
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


def indicadores(resultados: list[metrics.Resultado], colunas: int = 4, chave: str | None = None) -> None:
    """Uma linha de indicadores em cartões; cada um com definição (ícone de ajuda) e numerador/denominador.

    Os percentuais trazem uma barra fina com a proporção. Em telas estreitas os cartões se reorganizam
    (CSS ``st-key-kpis_*``).
    """
    chave = chave or resultados[0].indicador.id
    with st.container(key=f"kpis_{chave}"):
        cols = st.columns(colunas)
    for i, (coluna, resultado) in enumerate(zip(cols, resultados)):
        with coluna, st.container(border=True, key=f"kpi_{chave}_{i}"):
            st.metric(resultado.indicador.nome, metrics.valor_formatado(resultado),
                      help=metrics.ajuda(resultado.indicador))
            barra = ""
            if resultado.indicador.percentual and resultado.disponivel and resultado.valor is not None:
                fracao = min(max(float(resultado.valor), 0.0), 1.0)
                barra = (f'<div class="eti-kpi-barra" aria-hidden="true"><div style="width:{fracao * 100:.1f}%">'
                         "</div></div>")
            st.html(f'{barra}<p class="eti-metrica-contexto">{html.escape(metrics.contexto_formatado(resultado))}</p>')


def _seguir(acao: tuple) -> None:
    """Clique num destaque: abre a ficha da turma ou leva à página (com o grupo da galeria já escolhido)."""
    from . import fichas

    if acao[0] == "turma":
        fichas.pedir("turma", acao[1])
        return
    _, pagina, grupo = acao
    if grupo:
        st.session_state["cursistas_escolha"] = grupo
        st.session_state["cursistas_limite"] = None
    st.session_state[IR_PARA] = pagina


def destaques(itens: list) -> None:
    """Faixa de destaques (``metrics.destaques``): cartões que levam ao detalhe de cada número."""
    from .cartoes import destaque

    if not itens:
        return
    with st.container(key="destaques"):
        for i, item in enumerate(itens):
            conteudo = destaque(item.icone, item.valor, item.titulo, item.texto, com_seta=bool(item.acao))
            if item.acao:
                clicavel(conteudo, f"destaque_{i}", f"{item.valor} {item.titulo}: ver detalhes", _seguir, (item.acao,))
            else:
                st.html(conteudo)


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


def botao_mais(mostrados: int, total: int, chave: str, passo: int = 24, unidade: str = "itens",
               centralizado: bool = True) -> None:
    """Botão "Mostrar mais"; ``centralizado=False`` ocupa a largura toda (listas em colunas estreitas)."""
    estado = f"{chave}_limite"
    if mostrados >= total:
        return

    def mais() -> None:
        st.session_state[estado] = (st.session_state.get(estado) or passo) + passo

    lugar = st.columns([1, 1.2, 1])[1] if centralizado else st
    lugar.button(f"Mostrar mais {unidade} ({metrics.numero(total - mostrados)} restantes)", on_click=mais,
                 key=f"{chave}_mais", width="stretch", icon=":material/expand_more:")


def _cabecalho_html(titulo: str, subtitulo: str | None, chamada_texto: str | None) -> str:
    e = html.escape
    return ((f'<div class="viz-chamada">{e(chamada_texto)}</div>' if chamada_texto else "")
            + f'<div class="viz-titulo">{e(titulo)}</div>'
            + (f'<p class="viz-sub">{e(subtitulo)}</p>' if subtitulo else ""))


def histograma_acesso(dias: pd.Series, nunca: int, base, fuso: str, unidade: str = "pessoas",
                      titulo: str = "Há quanto tempo foi o último acesso", subtitulo: str | None = None) -> graficos.Visual:
    """Tempo sem acesso em classes de dias, na cor da faixa de cada classe, com a coluna "Nunca".

    Linhas tracejadas marcam a janela de acesso recente e o limite de acompanhamento; quando a lista da
    plataforma tem data de referência, cada marca traz também a data correspondente.
    """
    parametros = base.parametros
    limites = parametros["faixas_inatividade_dias"]
    janela, limite = parametros["janela_acesso_recente_dias"], parametros["limite_acompanhamento_dias"]
    cores = graficos.cores_faixas(painel.ordem_faixas(limites))
    classes = painel.classes_de_dias(dias, limites, (janela, limite))
    referencia = (base.meta.get("atividade") or {}).get("referencia_em")
    momento = datetime.fromisoformat(referencia).astimezone(ZoneInfo(fuso)) if referencia else None

    def marca(dias_marca: int) -> str:
        return f"{dias_marca} dias" + (f" · {momento - timedelta(days=dias_marca):%d/%m}" if momento else "")

    colunas = []
    for c in classes.itertuples(index=False):
        rotulo = f"{c.inicio:g}+" if c.fim == math.inf else f"{c.inicio:g}–{c.fim:g}"
        intervalo = f"mais de {c.inicio:g} dias" if c.fim == math.inf else f"de {c.inicio:g} a {c.fim:g} dias"
        colunas.append({
            "rotulo": rotulo, "valor": c.contagem, "cor": cores[c.faixa],
            "dica": f"Último acesso {intervalo} antes da lista: {metrics.numero(c.contagem)} {unidade} ({c.faixa})",
            "marca": marca(c.inicio) if c.inicio in (janela, limite) else None,
        })
    colunas.append({"rotulo": "Nunca", "valor": nunca, "cor": cores[painel.FAIXA_NUNCA], "separada": True,
                    "dica": f"Nunca acessaram o curso: {metrics.numero(nunca)} {unidade}"})
    por_faixa = classes.groupby("faixa", sort=False)["contagem"].sum()
    legenda = [(f"{faixa}: {metrics.numero(n)}", cores[faixa]) for faixa, n in por_faixa.items() if n]
    if nunca:
        legenda.append((f"{painel.FAIXA_NUNCA}: {metrics.numero(nunca)}", cores[painel.FAIXA_NUNCA]))
    quando = f" (lista de {momento:%d/%m/%Y})" if momento else ""
    eixo = f"Dias entre o último acesso e a data da lista da plataforma{quando}"
    if subtitulo is None:
        subtitulo = (f"Cada coluna conta {unidade} pelo tempo sem acesso. Tracejado: últimos {janela} dias e "
                     f"limite de acompanhamento ({limite} dias)")
    return graficos.histograma(colunas, titulo, subtitulo, eixo, legenda)


def comparacao_faixas(dados: pd.DataFrame, dimensoes: list[tuple[str, str]], ordem: list[str], cores: dict[str, str],
                      titulo: str, subtitulo: str | None, chave: str, nota_texto: str | None = None,
                      fonte: str | None = None, chamada_texto: str | None = None,
                      sem_valor: str = "Não informado") -> None:
    """Tempo desde o último acesso em cada categoria de uma ou mais dimensões (ex.: cargo, origem da vaga).

    Uma linha por categoria, com o total ao lado do rótulo; com mais de uma dimensão, as linhas ficam em
    blocos com o nome da dimensão. ``dados`` tem a coluna ``faixa_acesso`` e as colunas das dimensões;
    ``ordem`` são as faixas mostradas e ``cores`` a cor de cada faixa (``graficos.cores_faixas``).
    """
    linhas, grupos, tabela = [], [], []
    series: dict[str, list[int]] = {f: [] for f in ordem}
    for nome, coluna in dimensoes:
        cruz = pd.crosstab(dados[coluna].fillna(sem_valor), dados["faixa_acesso"]).reindex(columns=ordem, fill_value=0)
        for valor in sorted(cruz.index, key=lambda v: (v == sem_valor, painel.chave_ordem(coluna, v))):
            linhas.append(painel.rotulo(coluna, valor))
            grupos.append(nome)
            contagens = {f: int(cruz.loc[valor, f]) for f in ordem}
            for f in ordem:
                series[f].append(contagens[f])
            tabela.append({"Dimensão": nome, "Categoria": painel.rotulo(coluna, valor), **contagens})
    if not linhas:
        vazio("Sem dados para a comparação no recorte.")
        return
    series = {f: v for f, v in series.items() if any(v)}
    fig = graficos.barras_empilhadas_100(linhas, series, cores, titulo, subtitulo,
                                         grupos=grupos if len(dimensoes) > 1 else None, mostrar_total=True)
    grafico(fig, pd.DataFrame(tabela), chave, nota_texto, fonte, chamada_texto)


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


def faltam_arquivos(cfg, fonte: str) -> None:
    """A base ainda não está no painel: diz qual arquivo colocar na pasta (lida automaticamente)."""
    if fonte == "cadastro":
        texto = ("Nenhuma planilha do cadastro foi encontrada na pasta do painel. Coloque nela o arquivo do "
                 "cadastro (.xlsx ou .csv, com as colunas do modelo) e recarregue a página: ele é lido sozinho.")
    else:
        texto = ("A exportação de participantes da plataforma não foi encontrada na pasta do painel. Coloque nela o "
                 "texto copiado da página Participantes do Moodle (.txt) ou a planilha exportada e recarregue a página.")
    vazio(f"{texto} Pasta: {cfg.pasta_arquivos}")


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
