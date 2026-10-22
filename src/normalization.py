"""Normalização e validação de valores individuais.

Funções puras: recebem o valor como veio da planilha (texto, número do Excel,
data) e devolvem o valor normalizado e um status. Nunca descartam o registro;
quem decide o que fazer com um status inválido é a camada de validação.
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .config import CODIGO_DA_SIGLA, NOME_DA_SIGLA, UFS

# ---------------------------------------------------------------- texto


def eh_vazio(valor) -> bool:
    if valor is None:
        return True
    if isinstance(valor, str):
        return not valor.strip()
    if isinstance(valor, float):
        return math.isnan(valor)
    try:
        import pandas as pd

        return valor is pd.NA or valor is pd.NaT
    except ImportError:  # pragma: no cover
        return False


def remover_acentos(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c)
    )


def limpar_texto(valor) -> str | None:
    """Valor de exibição: espaços aparados e colapsados; vazio vira None."""
    if eh_vazio(valor):
        return None
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    texto = " ".join(str(valor).replace(" ", " ").split())
    return texto or None


@lru_cache(maxsize=262_144)
def _chave_de_texto(texto: str) -> str | None:
    texto = re.sub(r"[^a-z0-9]+", " ", remover_acentos(texto).lower())
    return " ".join(texto.split()) or None


def chave_comparacao(valor) -> str | None:
    """Forma canônica para comparar nomes e categorias (sem acento, minúsculas)."""
    texto = limpar_texto(valor)
    return None if texto is None else _chave_de_texto(texto)


def chave_cabecalho(valor) -> str:
    if eh_vazio(valor):
        return ""
    return re.sub(r"[^a-z0-9]", "", remover_acentos(str(valor)).lower())


def unificar_categorias(valores: list) -> list[str | None]:
    """Unifica grafias de uma mesma categoria ("aceitou", "ACEITOU ") pela forma mais frequente.

    A comparação ignora acentos, caixa e espaços; o valor exibido é a grafia
    original mais comum, para não inventar uma forma que não está na fonte.
    """
    from collections import Counter

    limpos = [limpar_texto(v) for v in valores]
    chave_de = {t: (_chave_de_texto(t) or t) for t in set(limpos) if t is not None}
    contagem: dict[str, Counter] = {}
    for texto in limpos:
        if texto is not None:
            contagem.setdefault(chave_de[texto], Counter())[texto] += 1
    preferida = {chave: c.most_common(1)[0][0] for chave, c in contagem.items()}
    return [None if t is None else preferida[chave_de[t]] for t in limpos]


# ---------------------------------------------------------------- e-mail

_LOCAL = r"[a-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[a-z0-9!#$%&'*+/=?^_`{|}~-]+)*"
_DOMINIO = r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}"
RE_EMAIL = re.compile(rf"^{_LOCAL}@{_DOMINIO}$")


def normalizar_email(valor) -> tuple[str | None, str]:
    """Retorna (e-mail em minúsculas, status ausente|invalido|valido).

    Não corrige o endereço além de aparar espaços nas pontas, remover "mailto:"
    e usar minúsculas: um e-mail com espaço interno continua inválido.
    """
    texto = limpar_texto(valor)
    if texto is None:
        return None, "ausente"
    texto = texto.strip("<> ")
    if texto.lower().startswith("mailto:"):
        texto = texto[7:]
    texto = texto.lower()
    if " " in texto or not RE_EMAIL.match(texto):
        return texto, "invalido"
    return texto, "valido"


# ---------------------------------------------------------------- códigos


def digitos_de_codigo(valor) -> tuple[str | None, bool]:
    """Converte um código lido da planilha em texto de dígitos.

    Aceita número do Excel (inteiro ou terminado em ".0") e separadores comuns
    (pontos, traços, barras, espaços). Retorna (texto, formato_ok); o texto é
    sempre string, para preservar zeros à esquerda.
    """
    if eh_vazio(valor):
        return None, True
    if isinstance(valor, bool):
        return str(valor), False
    if isinstance(valor, int):
        return str(valor), True
    if isinstance(valor, float):
        return (str(int(valor)), True) if valor.is_integer() else (str(valor), False)
    texto = limpar_texto(valor)
    if re.fullmatch(r"\d+\.0+", texto):
        texto = texto.split(".")[0]
    if re.fullmatch(r"[\d\s.\-/]+", texto):
        digitos = re.sub(r"\D", "", texto)
        return (digitos, True) if digitos else (texto, False)
    return texto, False


def classificar_inep(valor) -> tuple[str | None, str]:
    """Código de escola do Inep: 8 dígitos, iniciando pelo código da UF."""
    codigo, formato_ok = digitos_de_codigo(valor)
    if codigo is None:
        return None, "ausente"
    if not formato_ok or len(codigo) != 8 or codigo[:2] not in UFS:
        return codigo, "invalido"
    return codigo, "valido"


def sigla_uf_do_codigo(codigo: str | None) -> str | None:
    if not codigo or codigo[:2] not in UFS:
        return None
    return UFS[codigo[:2]][0]


def normalizar_uf(valor) -> tuple[str | None, str]:
    texto = limpar_texto(valor)
    if texto is None:
        return None, "ausente"
    sigla = texto.upper()
    if sigla in CODIGO_DA_SIGLA:
        return sigla, "valido"
    chave = chave_comparacao(texto)
    for s, nome in NOME_DA_SIGLA.items():
        if chave_comparacao(nome) == chave:
            return s, "valido"
    return texto, "invalido"


def classificar_ibge(
    valor, sigla_uf: str | None, municipios: dict[str, tuple[str, str]] | None
) -> tuple[str | None, str]:
    """Código IBGE do ente: 7 dígitos (município) ou 2 dígitos (UF, entes estaduais).

    Status: ausente | invalido | uf_divergente | inexistente | valido.
    "inexistente" só é usado quando a lista oficial de municípios está disponível.
    """
    codigo, formato_ok = digitos_de_codigo(valor)
    if codigo is None:
        return None, "ausente"
    if not formato_ok or len(codigo) not in (2, 7) or codigo[:2] not in UFS:
        return codigo, "invalido"
    if sigla_uf and sigla_uf in CODIGO_DA_SIGLA and codigo[:2] != CODIGO_DA_SIGLA[sigla_uf]:
        return codigo, "uf_divergente"
    if len(codigo) == 7 and municipios is not None and codigo not in municipios:
        return codigo, "inexistente"
    return codigo, "valido"


def validar_cpf(valor) -> tuple[str | None, str]:
    """Retorna (dígitos, status ausente|invalido|valido|valido_recomposto).

    "valido_recomposto": a célula era numérica e perdeu zeros à esquerda no
    Excel; os zeros foram recompostos (CPF tem sempre 11 dígitos) e os
    dígitos verificadores conferem. Até quatro zeros: no cadastro real há CPFs
    que começam com "000" e "0000".
    """
    if eh_vazio(valor):
        return None, "ausente"
    numerico = isinstance(valor, (int, float)) and not isinstance(valor, bool)
    digitos, formato_ok = digitos_de_codigo(valor)
    if digitos is None or not formato_ok:
        return digitos, "invalido"
    recomposto = False
    if numerico and 7 <= len(digitos) < 11:
        digitos, recomposto = digitos.zfill(11), True
    if len(digitos) != 11 or digitos == digitos[0] * 11:
        return digitos, "invalido"
    for n in (9, 10):
        soma = sum(int(digitos[i]) * (n + 1 - i) for i in range(n))
        if (soma * 10) % 11 % 10 != int(digitos[n]):
            return digitos, "invalido"
    return digitos, "valido_recomposto" if recomposto else "valido"


# ---------------------------------------------------------------- datas

_FORMATOS_DATA = ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y")


def interpretar_data(valor) -> tuple[date | None, str]:
    """Retorna (data, status ausente|invalida|valida). Aceita serial do Excel."""
    if eh_vazio(valor):
        return None, "ausente"
    if isinstance(valor, datetime):
        return valor.date(), "valida"
    if isinstance(valor, date):
        return valor, "valida"
    if isinstance(valor, (int, float)) and not isinstance(valor, bool):
        if 20000 <= float(valor) <= 80000:
            return date(1899, 12, 30) + timedelta(days=int(valor)), "valida"
        return None, "invalida"
    texto = limpar_texto(valor)
    if re.match(r"^\d{4}-\d{2}-\d{2}[ T]\d", texto):
        texto = texto[:10]
    for formato in _FORMATOS_DATA:
        try:
            return datetime.strptime(texto, formato).date(), "valida"
        except ValueError:
            continue
    return None, "invalida"


# ---------------------------------------------------------------- último acesso

_UNIDADES = {
    **dict.fromkeys(("ano", "anos", "year", "years"), 365 * 86400),
    **dict.fromkeys(("semana", "semanas", "week", "weeks"), 7 * 86400),
    **dict.fromkeys(("dia", "dias", "day", "days"), 86400),
    **dict.fromkeys(("hora", "horas", "hour", "hours"), 3600),
    **dict.fromkeys(("minuto", "minutos", "min", "mins", "minute", "minutes"), 60),
    **dict.fromkeys(("segundo", "segundos", "seg", "sec", "secs", "second", "seconds"), 1),
}
_NUNCA = {"nunca", "never", "nunca acessou", "nenhum acesso", "sem acesso"}
_AGORA = {"agora", "now", "agora mesmo", "just now"}
_MESES = {
    "jan": 1, "fev": 2, "feb": 2, "mar": 3, "abr": 4, "apr": 4, "mai": 5, "may": 5,
    "jun": 6, "jul": 7, "ago": 8, "aug": 8, "set": 9, "sep": 9, "out": 10, "oct": 10,
    "nov": 11, "dez": 12, "dec": 12,
}
_RE_PAR = re.compile(r"(\d+)\s*([a-z]+)")
_RE_DATA_NUM = re.compile(
    r"^(\d{1,2})/(\d{1,2})/(\d{4})(?:[,\s]+(?:as\s+)?(\d{1,2}):(\d{2})(?::(\d{2}))?)?$"
)
_RE_DATA_ISO = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})(?:[ t](\d{2}):(\d{2})(?::(\d{2}))?)?(z|[+-]\d{2}:?\d{2})?$"
)
_RE_DATA_EXTENSO = re.compile(
    r"(\d{1,2})\s+(?:de\s+)?([a-z]{3})[a-z.]*\s+(?:de\s+)?(\d{4})"
    r"(?:[,\s]+(?:as\s+)?(\d{1,2}):(\d{2})\s*(am|pm)?)?"
)


@dataclass(frozen=True)
class Acesso:
    """Último acesso interpretado.

    tipo: relativo | absoluto | nunca | vazio | nao_interpretado
    duracao_s: tempo decorrido até o momento da exportação (só para "relativo")
    momento: instante do acesso em UTC (só para "absoluto")
    """

    tipo: str
    duracao_s: float | None = None
    momento: datetime | None = None


def _duracao_relativa(texto: str) -> float | None:
    t = re.sub(r"\b(e|and|ha|atras|ago)\b", " ", texto.replace(",", " "))
    pares = _RE_PAR.findall(t)
    if not pares or _RE_PAR.sub(" ", t).strip():
        return None
    total = 0
    for numero, unidade in pares:
        if unidade not in _UNIDADES:
            return None
        total += int(numero) * _UNIDADES[unidade]
    return float(total)


def _como_utc(ano, mes, dia, hora, minuto, segundo, fuso: str) -> datetime | None:
    try:
        local = datetime(int(ano), int(mes), int(dia), int(hora or 0), int(minuto or 0), int(segundo or 0))
    except ValueError:
        return None
    return local.replace(tzinfo=ZoneInfo(fuso)).astimezone(timezone.utc)


def interpretar_ultimo_acesso(valor, fuso: str = "America/Sao_Paulo") -> Acesso:
    """Interpreta "Último acesso ao curso" do Moodle.

    Textos relativos ("1 dia 3 horas", "1 hora e 33 minutos") viram duração
    contada a partir do momento da exportação; nunca viram data absoluta aqui.
    Datas/horas explícitas são lidas no fuso informado e convertidas para UTC.
    """
    if eh_vazio(valor):
        return Acesso("vazio")
    if isinstance(valor, datetime):
        momento = valor if valor.tzinfo else valor.replace(tzinfo=ZoneInfo(fuso))
        return Acesso("absoluto", momento=momento.astimezone(timezone.utc))
    texto = remover_acentos(limpar_texto(valor).lower())
    if texto in _NUNCA:
        return Acesso("nunca")
    if texto in _AGORA:
        return Acesso("relativo", duracao_s=0.0)
    duracao = _duracao_relativa(texto)
    if duracao is not None:
        return Acesso("relativo", duracao_s=duracao)
    if m := _RE_DATA_NUM.match(texto):
        d, mes, a, h, mi, s = m.groups()
        momento = _como_utc(a, mes, d, h, mi, s, fuso)
        return Acesso("absoluto", momento=momento) if momento else Acesso("nao_interpretado")
    if m := _RE_DATA_ISO.match(texto):
        a, mes, d, h, mi, s, tz = m.groups()
        if tz:
            try:
                momento = datetime.fromisoformat(texto.upper().replace(" ", "T")).astimezone(timezone.utc)
                return Acesso("absoluto", momento=momento)
            except ValueError:
                return Acesso("nao_interpretado")
        momento = _como_utc(a, mes, d, h, mi, s, fuso)
        return Acesso("absoluto", momento=momento) if momento else Acesso("nao_interpretado")
    if m := _RE_DATA_EXTENSO.search(texto):
        d, nome_mes, a, h, mi, ampm = m.groups()
        mes = _MESES.get(nome_mes)
        if mes:
            hora = int(h) if h else 0
            if ampm == "pm" and hora < 12:
                hora += 12
            elif ampm == "am" and hora == 12:
                hora = 0
            momento = _como_utc(a, mes, d, hora, mi, 0, fuso)
            if momento:
                return Acesso("absoluto", momento=momento)
    return Acesso("nao_interpretado")


def descrever_duracao(segundos: float | None) -> str:
    """Duração legível, no estilo do Moodle (duas maiores unidades)."""
    if segundos is None or (isinstance(segundos, float) and math.isnan(segundos)):
        return "—"
    s = int(segundos)
    partes = []
    for nome_s, nome_p, tam in (("ano", "anos", 365 * 86400), ("dia", "dias", 86400),
                                ("hora", "horas", 3600), ("minuto", "minutos", 60)):
        if s >= tam:
            n, s = divmod(s, tam)
            partes.append(f"{n} {nome_s if n == 1 else nome_p}")
        if len(partes) == 2:
            break
    return " e ".join(partes) if partes else "menos de 1 minuto"
