"""Visualizações do painel, no estilo editorial adotado pela coordenação.

Barras, histograma e mapas de calor são HTML/CSS próprios (tipografia nítida, números dentro das
barras, blocos arredondados); só o mapa dos municípios (``mapas.py``) usa Plotly. A paleta é um único matiz (verde-petróleo)
do acesso mais recente ao mais antigo, com cinzas para ausência de acesso ou de informação. Todo
gráfico traz os valores escritos e uma tabela equivalente em "Ver dados do gráfico".
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field

TINTA = "#1F2933"
TINTA_SUAVE = "#5B6670"
# Do mais escuro (acesso mais recente) ao mais claro
PETROLEO = ("#0E6F7C", "#4E939C", "#88B7BD", "#BAD6DA")
CINZA_NUNCA = "#C5CBD3"
CINZA_NAO_INTERPRETADO = "#D9DDE2"
CINZA_SEM_CONTA = "#E8EBEE"
COR_SERIE = "#2C8592"
CALOR_MIN = "#E1ECEE"
CALOR_MAX = "#0E6F7C"

CONFIG = {"displayModeBar": False, "responsive": True, "locale": "pt-BR"}


@dataclass
class Visual:
    """Gráfico em HTML; título, subtítulo e legenda são montados por ``ui.grafico``."""

    corpo: str
    titulo: str
    subtitulo: str | None = None
    legenda: list[tuple[str, str]] = field(default_factory=list)


def _hex_rgb(cor: str) -> tuple[int, int, int]:
    cor = cor.lstrip("#")
    return tuple(int(cor[i:i + 2], 16) for i in (0, 2, 4))


def _luminancia(cor: str) -> float:
    lin = [(c / 255 / 12.92) if c / 255 <= 0.04045 else ((c / 255 + 0.055) / 1.055) ** 2.4 for c in _hex_rgb(cor)]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def cor_texto_sobre(fundo: str) -> str:
    """Branco ou tinta, o que tiver mais contraste com o fundo."""
    branco = 1.05 / (_luminancia(fundo) + 0.05)
    tinta = (_luminancia(fundo) + 0.05) / (_luminancia(TINTA) + 0.05)
    return "#FFFFFF" if branco >= tinta else TINTA


def interpolar(cor_a: str, cor_b: str, t: float) -> str:
    a, b = _hex_rgb(cor_a), _hex_rgb(cor_b)
    t = min(max(t, 0.0), 1.0)
    return "#{:02X}{:02X}{:02X}".format(*(round(x + (y - x) * t) for x, y in zip(a, b)))


def cores_faixas(ordem: list[str]) -> dict[str, str]:
    """Faixas de acesso: quatro tons de petróleo e três cinzas (nunca, não interpretado, sem conta)."""
    cores = dict(zip(ordem[:4], PETROLEO))
    cores.update(dict(zip(ordem[4:], (CINZA_NUNCA, CINZA_NAO_INTERPRETADO, CINZA_SEM_CONTA))))
    return cores


def _numero(valor) -> str:
    return f"{int(round(valor)):,}".replace(",", ".")


def _pct(valor: float, casas: int = 0) -> str:
    return f"{valor * 100:.{casas}f}%".replace(".", ",")


def _e(texto) -> str:
    return html.escape(str(texto))


def _largura_texto(texto: str) -> float:
    """Largura aproximada (rem) de um rótulo numérico em negrito, com o recuo lateral."""
    return 0.56 * len(texto) + 1.2


def _classe_largura(texto: str) -> str:
    """Faixa de comprimento do texto; o CSS mostra o texto dentro da barra só se a barra comportar essa faixa."""
    for limite in (2, 3, 5, 8, 12, 16, 20):
        if len(texto) <= limite:
            return f"viz-l{limite}"
    return "viz-l99"


# ---------------------------------------------------------------- barras empilhadas


def barras_empilhadas_100(
    linhas: list[str],
    series: dict[str, list[float]],
    cores: dict[str, str],
    titulo: str,
    subtitulo: str | None = None,
    totais: list[int] | None = None,
    grupos: list[str] | None = None,
    mostrar_total: bool = False,
) -> Visual:
    """Uma barra por linha, dividida pelas séries; cada segmento mostra a contagem.

    ``grupos`` (um por linha) separa as linhas em blocos com subtítulo (ex.: Cargo, Origem da vaga);
    ``mostrar_total`` escreve o total de cada linha ao lado do rótulo.
    """
    if totais is None:
        totais = [sum(v) for v in zip(*series.values())] if series else []
    partes = []
    grupo_atual = None
    for i, linha in enumerate(linhas):
        if grupos and grupos[i] != grupo_atual:
            grupo_atual = grupos[i]
            partes.append(f'<div class="viz-grupo">{_e(grupo_atual)}</div>')
        total = totais[i] if i < len(totais) else 0
        segmentos = []
        for nome, contagens in series.items():
            valor = contagens[i]
            if not valor or not total:
                continue
            fracao = valor / total
            cor = cores.get(nome, CINZA_NAO_INTERPRETADO)
            texto = _numero(valor)
            dica = f"{linha} · {nome}: {_numero(valor)} de {_numero(total)} ({_pct(fracao, 1)})"
            # O número fica oculto (CSS, consulta de contêiner) quando o segmento é estreito demais para ele.
            segmentos.append(
                f'<div class="viz-seg {_classe_largura(texto)}" style="flex:{valor} 1 0;background:{cor};'
                f'color:{cor_texto_sobre(cor)}" title="{_e(dica)}"><span>{texto}</span></div>'
            )
        total_html = f' <span class="viz-n">{_numero(total)}</span>' if mostrar_total else ""
        partes.append(
            f'<div class="viz-rotulo">{_e(linha)}{total_html}</div>'
            f'<div class="viz-barra" role="img" aria-label="{_e(linha)}: total {_numero(total)}">{"".join(segmentos)}</div>'
        )
    legenda = [(nome, cores.get(nome, CINZA_NAO_INTERPRETADO)) for nome, v in series.items() if any(v)]
    return Visual(f'<div class="viz-empilhado">{"".join(partes)}</div>', titulo, subtitulo, legenda)


# ---------------------------------------------------------------- histograma (colunas verticais)


def histograma(colunas: list[dict], titulo: str, subtitulo: str | None = None, eixo: str | None = None,
               legenda: list[tuple[str, str]] | None = None) -> Visual:
    """Colunas verticais com o valor escrito em cima.

    Cada coluna: ``rotulo``, ``valor``, ``cor``, ``dica``; opcionais ``marca`` (texto de uma linha vertical
    tracejada na borda esquerda da coluna, ex.: limite de acompanhamento) e ``separada`` (espaço antes,
    para uma coluna que não faz parte da escala, como "Nunca").
    """
    maximo = max([c["valor"] for c in colunas] or [1]) or 1
    partes = []
    for c in colunas:
        classes = "viz-hist-col" + (" viz-hist-separada" if c.get("separada") else "") + (
            " viz-hist-marca" if c.get("marca") else "")
        marca = f'<span class="viz-hist-marca-texto">{_e(c["marca"])}</span>' if c.get("marca") else ""
        altura = c["valor"] / maximo * 88 if c["valor"] else 0  # 88%: o valor escrito cabe acima da maior coluna
        partes.append(
            f'<div class="{classes}" title="{_e(c["dica"])}">{marca}<div class="viz-hist-pilha">'
            f'<span class="viz-hist-valor">{_numero(c["valor"])}</span>'
            f'<div class="viz-hist-barra" style="height:{max(altura, 1.5 if c["valor"] else 0):.1f}%;'
            f'background:{c["cor"]}"></div></div><div class="viz-hist-rotulo">{_e(c["rotulo"])}</div></div>'
        )
    corpo = (f'<div class="viz-hist" role="img" aria-label="{_e(titulo)}" style="--colunas:{len(colunas)}">'
             f'{"".join(partes)}</div>' + (f'<div class="viz-hist-eixo">{_e(eixo)}</div>' if eixo else ""))
    return Visual(corpo, titulo, subtitulo, legenda or [])


# ---------------------------------------------------------------- barras simples


def barras_horizontais(
    categorias: list[str],
    valores: list[float],
    titulo: str,
    subtitulo: str | None = None,
    rotulos: list[str] | None = None,
    cor: str = COR_SERIE,
    hover: str | None = None,
    eixo_percentual: bool = False,
    cores: list[str] | None = None,
) -> Visual:
    """Barras horizontais com o valor escrito: dentro da barra quando cabe, logo após ela quando não cabe.

    A escala desconta a largura do rótulo mais longo, para que nenhum rótulo externo ultrapasse o trilho.
    """
    maximo = 1.0 if eixo_percentual else max([v for v in valores if v] or [1])
    rotulos = rotulos or [_pct(v) if eixo_percentual else _numero(v) for v in valores]
    reserva = _largura_texto(max(rotulos, key=len, default=""))
    partes = []
    for i, (categoria, valor) in enumerate(zip(categorias, valores)):
        fracao = (valor or 0) / maximo if maximo else 0
        fundo = cores[i] if cores and i < len(cores) else cor
        partes.append(
            f'<div class="viz-rotulo">{_e(categoria)}</div>'
            f'<div class="viz-trilho" title="{_e(categoria)}: {_e(rotulos[i])}">'
            f'<div class="viz-preenchido {_classe_largura(rotulos[i])}" '
            f'style="width:calc((100% - var(--reserva)) * {max(fracao, 0.004):.4f});background:{fundo}">'
            f'<span class="viz-valor-dentro" style="color:{cor_texto_sobre(fundo)}">{_e(rotulos[i])}</span>'
            f'<span class="viz-valor-fora">{_e(rotulos[i])}</span></div></div>'
        )
    return Visual(f'<div class="viz-barras" style="--reserva:{reserva:.2f}rem">{"".join(partes)}</div>',
                  titulo, subtitulo)


# ---------------------------------------------------------------- proporções (parte de um total)


def proporcoes(itens: list[tuple[str, float, float]], titulo: str, subtitulo: str | None = None,
               rotulo_parte: str = "parte") -> Visual:
    """Uma barra por item: o trilho claro é o total, o trecho escuro é a parte (ex.: tempo integral)."""
    partes = []
    for rotulo, parte, total in itens:
        fracao = (parte / total) if total else 0
        texto = f"{_numero(parte)} de {_numero(total)} ({_pct(fracao)})"
        partes.append(
            f'<div class="viz-rotulo">{_e(rotulo)}</div>'
            f'<div class="viz-proporcao" title="{_e(rotulo)}: {_e(texto)} {_e(rotulo_parte)}">'
            f'<div class="viz-proporcao-trilho"><div class="viz-proporcao-parte" style="width:{fracao * 100:.2f}%"></div></div>'
            f'<span class="viz-valor-fora">{_e(texto)}</span></div>'
        )
    legenda = [(rotulo_parte.capitalize(), CALOR_MAX), ("Total", "#DCE8EA")]
    return Visual(f'<div class="viz-barras">{"".join(partes)}</div>', titulo, subtitulo, legenda)


# ---------------------------------------------------------------- mapa de calor


def mapa_calor(
    linhas: list[str],
    colunas: list[str],
    valores: list[list[float | None]],
    titulo: str,
    subtitulo: str | None = None,
    textos: list[list[str]] | None = None,
    subtextos: list[list[str]] | None = None,
) -> Visual:
    """Blocos arredondados; quanto mais escura a cor, maior o valor (do menor ao maior observado)."""
    observados = [v for linha in valores for v in linha if v is not None]
    minimo, maximo = (min(observados), max(observados)) if observados else (0, 1)
    amplitude = (maximo - minimo) or 1
    cabecalho = "<div></div>" + "".join(f'<div class="viz-calor-col">{_e(c)}</div>' for c in colunas)
    corpo = []
    for i, linha in enumerate(linhas):
        corpo.append(f'<div class="viz-calor-linha">{_e(linha)}</div>')
        for j, coluna in enumerate(colunas):
            valor = valores[i][j]
            if valor is None:
                corpo.append('<div class="viz-bloco viz-bloco-vazio" title="Sem dados">—</div>')
                continue
            fundo = interpolar(CALOR_MIN, CALOR_MAX, (valor - minimo) / amplitude)
            texto = textos[i][j] if textos else _numero(valor)
            sub = subtextos[i][j] if subtextos else ""
            corpo.append(
                f'<div class="viz-bloco" style="background:{fundo};color:{cor_texto_sobre(fundo)}" '
                f'title="{_e(linha)} · {_e(coluna)}: {_e(texto)} {_e(sub)}"><b>{_e(texto)}</b>'
                + (f"<small>{_e(sub)}</small>" if sub else "") + "</div>"
            )
    grade = f'<div class="viz-calor" style="--colunas:{len(colunas)}">{cabecalho}{"".join(corpo)}</div>'
    return Visual(grade, titulo, subtitulo)
