"""Dados escolares oficiais do Inep, recuperados pelo código INEP do cadastro.

Não há API pública documentada de consulta por código INEP. Por isso:
- fonte principal automática: arquivo oficial dos Microdados do Censo Escolar
  (download pelo endereço publicado no portal do Inep, com cache local);
- alternativa: arquivo exportado manualmente do Catálogo de Escolas (Inep Data)
  ou o pacote de microdados baixado previamente, importados pela Administração.

Os rótulos e categorias abaixo seguem o "Dicionário de Dados da Educação
Básica" que acompanha os microdados (conferido na edição 2024). Variáveis
ausentes no arquivo carregado aparecem como indisponíveis; nada é estimado.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import socket
import threading
import time
import zipfile
from contextlib import contextmanager
from pathlib import Path

import pandas as pd

from . import config
from .loaders import ErroImportacao, TabelaBruta, definir_campo, mapear_colunas
from .normalization import classificar_inep, digitos_de_codigo, eh_vazio, limpar_texto, unificar_categorias
from .persistence import COLUNAS, agora_utc
from .validators import grupos_de_duplicidade, resumo_problemas, tabela_problemas

FONTE_MICRODADOS = "Microdados do Censo Escolar da Educação Básica (Inep)"
FONTE_CATALOGO = "Catálogo de Escolas (Inep Data)"

DEFINICAO_TEMPO_INTEGRAL = (
    "Segundo o dicionário de dados do Censo Escolar, considera-se em tempo integral a matrícula "
    "cujo tempo de permanência semanal na turma de escolarização presencial é igual ou superior "
    "a 35 horas, incluídas as turmas de atividade complementar, de atendimento educacional "
    "especializado e exclusivas de itinerário formativo que, somadas, atinjam 35 horas ou mais."
)
AVISO_PROGRAMA = (
    "Participar da formação do Programa Escola em Tempo Integral não significa que a escola "
    "oferte matrículas em tempo integral, nem informa a jornada efetiva dos estudantes. "
    "Os números de matrícula abaixo são declarações ao Censo Escolar no ano de referência indicado."
)

DEPENDENCIA = {"1": "Federal", "2": "Estadual", "3": "Municipal", "4": "Privada"}
LOCALIZACAO = {"1": "Urbana", "2": "Rural"}
LOCALIZACAO_DIFERENCIADA = {
    "0": "Não está em área de localização diferenciada",
    "1": "Área de assentamento",
    "2": "Terra indígena",
    "3": "Comunidade quilombola",
    "8": "Área de povos e comunidades tradicionais",
}
SITUACAO_FUNCIONAMENTO = {
    "1": "Em atividade",
    "2": "Paralisada",
    "3": "Extinta (no ano do Censo)",
    "4": "Extinta em anos anteriores",
}

ETAPAS = (
    ("IN_INF", "Educação Infantil"),
    ("IN_FUND_AI", "Ensino Fundamental – anos iniciais"),
    ("IN_FUND_AF", "Ensino Fundamental – anos finais"),
    ("IN_MED", "Ensino Médio"),
    ("IN_PROF", "Educação Profissional"),
    ("IN_EJA", "Educação de Jovens e Adultos"),
    ("IN_ESP", "Educação Especial"),
)
INFRAESTRUTURA = (
    ("IN_AGUA_POTAVEL", "Água potável para consumo humano"),
    ("IN_ENERGIA_REDE_PUBLICA", "Energia elétrica da rede pública"),
    ("IN_ESGOTO_REDE_PUBLICA", "Esgoto sanitário pela rede pública"),
    ("IN_INTERNET", "Acesso à internet"),
    ("IN_INTERNET_ALUNOS", "Internet para uso dos alunos"),
    ("IN_BANDA_LARGA", "Internet banda larga"),
    ("IN_BIBLIOTECA_SALA_LEITURA", "Biblioteca e/ou sala de leitura"),
    ("IN_LABORATORIO_INFORMATICA", "Laboratório de informática"),
    ("IN_LABORATORIO_CIENCIAS", "Laboratório de ciências"),
    ("IN_QUADRA_ESPORTES", "Quadra de esportes"),
    ("IN_REFEITORIO", "Refeitório"),
    ("IN_COZINHA", "Cozinha"),
    ("IN_PATIO_COBERTO", "Pátio coberto"),
    ("IN_BANHEIRO_PNE", "Banheiro acessível a pessoas com deficiência"),
    ("IN_ALIMENTACAO", "Alimentação escolar (PNAE/FNDE)"),
)
MATRICULAS = (
    ("QT_MAT_BAS", "Matrículas na educação básica"),
    ("QT_MAT_BAS_INT", "Educação básica em tempo integral"),
    ("QT_MAT_INF_INT", "Educação Infantil em tempo integral"),
    ("QT_MAT_FUND_AI_INT", "Ensino Fundamental – anos iniciais em tempo integral"),
    ("QT_MAT_FUND_AF_INT", "Ensino Fundamental – anos finais em tempo integral"),
    ("QT_MAT_FUND_INT", "Ensino Fundamental em tempo integral"),
    ("QT_MAT_MED_INT", "Ensino Médio em tempo integral"),
)
VARIAVEIS_INT_TOTAL = ("QT_MAT_INF_INT", "QT_MAT_FUND_INT", "QT_MAT_MED_INT")

_IDENTIFICACAO = (
    "NU_ANO_CENSO", "NO_REGIAO", "SG_UF", "CO_UF", "NO_MUNICIPIO", "CO_MUNICIPIO",
    "NO_ENTIDADE", "CO_ENTIDADE", "TP_DEPENDENCIA", "TP_CATEGORIA_ESCOLA_PRIVADA",
    "TP_LOCALIZACAO", "TP_LOCALIZACAO_DIFERENCIADA", "TP_SITUACAO_FUNCIONAMENTO",
)
# Etapa "ofertada" = escola com ao menos uma matrícula na etapa (definição do IN_* no dicionário de 2024).
# A partir de 2025 os indicadores IN_INF/IN_FUND/IN_MED deixaram de existir (e os novos IN_COMUM_* têm outro
# significado: matrículas de estudantes da educação especial em classes comuns); a oferta é então
# derivada da contagem correspondente, pela mesma definição.
ETAPA_POR_CONTAGEM = {
    "IN_INF": "QT_MAT_INF", "IN_FUND_AI": "QT_MAT_FUND_AI", "IN_FUND_AF": "QT_MAT_FUND_AF", "IN_MED": "QT_MAT_MED",
    "IN_PROF": "QT_MAT_PROF", "IN_EJA": "QT_MAT_EJA", "IN_ESP": "QT_MAT_ESP",
}
VARIAVEIS_DESEJADAS = tuple(dict.fromkeys((
    *_IDENTIFICACAO, "IN_FUND",
    *(v for v, _ in ETAPAS), *(v for v, _ in INFRAESTRUTURA), *(v for v, _ in MATRICULAS),
    *ETAPA_POR_CONTAGEM.values(), "QT_MAT_FUND", "QT_DOC_BAS", "QT_TUR_BAS", "QT_SALAS_UTILIZADAS",
)))
_RE_CSV_MICRODADOS = re.compile(r"microdados_ed_basica_(\d{4})\.csv$", re.I)
_RE_TABELA_ESCOLA = re.compile(r"tabela_escola_(\d{4})[^/]*\.csv$", re.I)
_RE_TABELA_MATRICULA = re.compile(r"tabela_matricula_(\d{4})[^/]*\.csv$", re.I)
_RE_MD5 = re.compile(r"^([0-9a-f]{32})\s+\*?(\S+)$", re.I)


# ---------------------------------------------------------------- leitura dos microdados


class _LeitorComHash(io.RawIOBase):
    def __init__(self, bruto):
        self._bruto = bruto
        self.md5 = hashlib.md5()

    def readable(self) -> bool:
        return True

    def readinto(self, buffer) -> int:
        dados = self._bruto.read(len(buffer))
        buffer[:len(dados)] = dados
        self.md5.update(dados)
        return len(dados)


def _ler_csv(bruto, desejadas, filtrar, progresso=None) -> tuple[pd.DataFrame, str, list[str]]:
    """Lê um CSV do Inep em blocos, só com as colunas desejadas e as linhas filtradas.

    Retorna (dados, md5 do arquivo inteiro, colunas existentes no arquivo).
    """
    leitor = _LeitorComHash(bruto)
    buffer = io.BufferedReader(leitor, buffer_size=1 << 20)
    amostra = buffer.peek(1 << 16)
    try:
        amostra.decode("utf-8")
        codificacao = "utf-8-sig" if amostra.startswith(b"\xef\xbb\xbf") else "utf-8"
    except UnicodeDecodeError:
        codificacao = "latin-1"
    texto = io.TextIOWrapper(buffer, encoding=codificacao, newline="")
    cabecalho = texto.readline().rstrip("\r\n")
    separador = ";" if cabecalho.count(";") >= cabecalho.count(",") else ","
    colunas = [c.strip().strip('"') for c in cabecalho.split(separador)]
    if "CO_ENTIDADE" not in colunas:
        raise ErroImportacao("O arquivo não tem a coluna CO_ENTIDADE dos microdados do Inep.")
    usar = [c for c in desejadas if c in colunas]
    partes, lidas = [], 0
    for bloco in pd.read_csv(texto, sep=separador, header=None, names=colunas, usecols=usar, dtype=str,
                             keep_default_na=False, chunksize=50_000):
        lidas += len(bloco)
        partes.append(bloco[filtrar(bloco)])
        if progresso:
            progresso(lidas)
    dados = pd.concat(partes, ignore_index=True) if partes else pd.DataFrame(columns=usar)
    return dados, leitor.md5.hexdigest(), colunas


def _md5_publicados(zf: zipfile.ZipFile) -> dict[str, str]:
    publicados = {}
    for info in zf.infolist():
        if info.filename.lower().endswith(".txt") and "md5" in info.filename.lower():
            for linha in zf.read(info).decode("latin-1").splitlines():
                if m := _RE_MD5.match(linha.strip()):
                    publicados[m.group(2).lower()] = m.group(1).lower()
    return publicados


def ler_microdados(
    origem: Path | bytes,
    nome: str,
    codigos: set[str] | None = None,
    ufs: set[str] | None = None,
    progresso=None,
) -> tuple[pd.DataFrame, dict]:
    """Lê os dados de escolas dos microdados do Censo Escolar, filtrando por código INEP ou UF.

    Aceita o pacote ZIP oficial (formato até 2024, com microdados_ed_basica_AAAA.csv, ou a partir de
    2025, com Tabela_Escola_AAAA e Tabela_Matricula_AAAA) ou um CSV já extraído.
    """
    def filtro_escolas(bloco):
        if not codigos and not ufs:
            return pd.Series(True, index=bloco.index)
        mascara = pd.Series(False, index=bloco.index)
        if codigos:
            mascara |= bloco["CO_ENTIDADE"].isin(codigos)
        if ufs and "SG_UF" in bloco:
            mascara |= bloco["SG_UF"].isin(ufs)
        return mascara

    conteudo = origem if isinstance(origem, bytes) else None
    with (io.BytesIO(conteudo) if conteudo is not None else open(origem, "rb")) as arquivo:
        e_zip = arquivo.read(4) == b"PK\x03\x04"
    arquivos_lidos, md5 = [], {}
    if not e_zip:
        bruto = io.BytesIO(conteudo) if conteudo is not None else open(origem, "rb")
        with bruto:
            dados, md5_calc, colunas = _ler_csv(bruto, VARIAVEIS_DESEJADAS, filtro_escolas, progresso)
        arquivos_lidos.append(nome)
        md5[nome] = (None, md5_calc)
        formato = "arquivo CSV"
    else:
        with zipfile.ZipFile(io.BytesIO(conteudo) if conteudo is not None else origem) as zf:
            publicados = _md5_publicados(zf)
            membros = {i.filename: i for i in zf.infolist()}
            antigo = [n for n in membros if _RE_CSV_MICRODADOS.search(n)]
            escola = [n for n in membros if _RE_TABELA_ESCOLA.search(n)]
            matricula = [n for n in membros if _RE_TABELA_MATRICULA.search(n)]
            if antigo:
                principal, formato = antigo[0], "microdados_ed_basica (até 2024)"
            elif escola:
                principal, formato = escola[0], "Tabela_Escola + Tabela_Matricula (2025 em diante)"
            else:
                raise ErroImportacao(
                    "O pacote não contém a tabela de escolas dos microdados do Censo Escolar "
                    "(microdados_ed_basica_AAAA.csv ou Tabela_Escola_AAAA.csv)."
                )
            with zf.open(principal) as bruto:
                dados, md5_calc, colunas = _ler_csv(bruto, VARIAVEIS_DESEJADAS, filtro_escolas, progresso)
            nome_principal = Path(principal).name
            arquivos_lidos.append(nome_principal)
            md5[nome_principal] = (publicados.get(nome_principal.lower()), md5_calc)
            if not antigo and matricula:
                selecionadas = set(dados["CO_ENTIDADE"])
                desejadas = ["CO_ENTIDADE", *(c for c in VARIAVEIS_DESEJADAS if c.startswith("QT_MAT_"))]
                with zf.open(matricula[0]) as bruto:
                    mat, md5_mat, colunas_mat = _ler_csv(
                        bruto, desejadas, lambda b: b["CO_ENTIDADE"].isin(selecionadas))
                nome_mat = Path(matricula[0]).name
                arquivos_lidos.append(nome_mat)
                md5[nome_mat] = (publicados.get(nome_mat.lower()), md5_mat)
                novas = [c for c in mat.columns if c == "CO_ENTIDADE" or c not in dados.columns]
                dados = dados.merge(mat[novas].drop_duplicates("CO_ENTIDADE"), on="CO_ENTIDADE", how="left")
                colunas = list(dict.fromkeys(colunas + colunas_mat))
    if "NO_ENTIDADE" not in dados.columns:
        raise ErroImportacao("A tabela de escolas não tem a coluna NO_ENTIDADE.")
    anos = dados["NU_ANO_CENSO"].replace("", None).dropna() if "NU_ANO_CENSO" in dados else pd.Series(dtype=str)
    conferidos = [publicado == calculado for publicado, calculado in md5.values() if publicado]
    meta = {
        "formato": formato,
        "arquivos_internos": arquivos_lidos,
        "escolas_selecionadas": int(len(dados)),
        "ano_referencia": int(anos.mode().iloc[0]) if not anos.empty else None,
        "variaveis_disponiveis": [c for c in VARIAVEIS_DESEJADAS if c in dados.columns],
        "variaveis_ausentes": [c for c in VARIAVEIS_DESEJADAS if c not in colunas],
        "etapas_derivadas_de_matriculas": [v for v, q in ETAPA_POR_CONTAGEM.items()
                                           if v not in dados.columns and q in dados.columns],
        "md5_confere": (all(conferidos) if conferidos else None),
    }
    return dados, meta


def _valor(linha: dict, var: str) -> str | None:
    """Valor da célula como texto; célula vazia (inclusive NaN do leitor de CSV) fica None, nunca "nan"."""
    v = linha.get(var)
    if eh_vazio(v):
        return None
    texto = str(v).strip()
    return None if texto.lower() == "nan" else texto


def _oferta(linha: dict, var: str) -> str | None:
    """"1" se a escola tem matrícula na etapa: indicador oficial, ou contagem > 0 quando ele não existe."""
    if var in linha:
        return _valor(linha, var)
    contagem = _valor(linha, ETAPA_POR_CONTAGEM.get(var, ""))
    if contagem is None:
        return None
    try:
        return "1" if int(float(contagem)) > 0 else "0"
    except ValueError:
        return None


def normalizar_microdados(dados: pd.DataFrame) -> pd.DataFrame:
    """Converte as colunas do Inep para o esquema interno, com rótulos oficiais."""
    registros = []
    for linha in dados.to_dict("records"):
        dep = _valor(linha, "TP_DEPENDENCIA")
        ofertas = {var: _oferta(linha, var) for var, _ in ETAPAS}
        etapas = [rotulo for var, rotulo in ETAPAS if ofertas[var] == "1"]
        if all(ofertas[v] is None for v in ("IN_FUND_AI", "IN_FUND_AF")) and _valor(linha, "IN_FUND") == "1":
            etapas.insert(1, "Ensino Fundamental")
        atributos = {
            var: _valor(linha, var)
            for var in (*(v for v, _ in INFRAESTRUTURA), *(v for v, _ in MATRICULAS), *ETAPA_POR_CONTAGEM.values(),
                        "IN_FUND", "QT_MAT_FUND", "QT_DOC_BAS", "QT_TUR_BAS", "QT_SALAS_UTILIZADAS", "NU_ANO_CENSO")
            if var in linha
        }
        atributos.update({var: valor for var, valor in ofertas.items() if valor is not None})
        registros.append({
            "co_entidade": _valor(linha, "CO_ENTIDADE"),
            "no_entidade": _valor(linha, "NO_ENTIDADE"),
            "sg_uf": _valor(linha, "SG_UF"),
            "co_municipio": _valor(linha, "CO_MUNICIPIO"),
            "no_municipio": _valor(linha, "NO_MUNICIPIO"),
            "dependencia": DEPENDENCIA.get(dep),
            "categoria_administrativa": ("Pública" if dep in ("1", "2", "3") else "Privada" if dep == "4" else None),
            "localizacao": LOCALIZACAO.get(_valor(linha, "TP_LOCALIZACAO")),
            "localizacao_diferenciada": LOCALIZACAO_DIFERENCIADA.get(_valor(linha, "TP_LOCALIZACAO_DIFERENCIADA")),
            "situacao_funcionamento": SITUACAO_FUNCIONAMENTO.get(_valor(linha, "TP_SITUACAO_FUNCIONAMENTO")),
            "etapas": "; ".join(etapas) if etapas else None,
            "porte": None,
            "latitude": None,
            "longitude": None,
            "atributos": atributos,
        })
    return pd.DataFrame(registros, columns=COLUNAS["escolas"])


# ---------------------------------------------------------------- Catálogo de Escolas

CAMPOS_CATALOGO = (
    definir_campo("co_entidade", "Código INEP", "codigo inep", "cod inep", "codigo da escola", "co entidade",
           "inep", obrigatorio=True),
    definir_campo("no_entidade", "Escola", "nome da escola", "no entidade", obrigatorio=True),
    definir_campo("sg_uf", "UF", "sigla uf"),
    definir_campo("no_municipio", "Município", "municipio"),
    definir_campo("co_municipio", "Código do Município", "codigo municipio", "co municipio"),
    definir_campo("localizacao", "Localização"),
    definir_campo("localizacao_diferenciada", "Localidade Diferenciada", "localizacao diferenciada"),
    definir_campo("categoria_administrativa", "Categoria Administrativa"),
    definir_campo("dependencia", "Dependência Administrativa"),
    definir_campo("situacao_funcionamento", "Situação de Funcionamento", "situacao funcionamento",
           "restricao de atendimento"),
    definir_campo("porte", "Porte da Escola", "porte"),
    definir_campo("etapas", "Etapas e Modalidade de Ensino Oferecidas",
           "etapas e modalidades de ensino oferecidas", "etapas de ensino"),
    definir_campo("latitude", "Latitude"),
    definir_campo("longitude", "Longitude"),
)


def _coordenada(valor, minimo: float, maximo: float) -> float | None:
    texto = limpar_texto(valor)
    if texto is None:
        return None
    try:
        numero = float(texto.replace(",", "."))
    except ValueError:
        return None
    return numero if minimo <= numero <= maximo else None


def normalizar_catalogo(tabela: TabelaBruta, ano_referencia: int) -> tuple[pd.DataFrame, dict]:
    mapa = mapear_colunas(tabela.cabecalhos, CAMPOS_CATALOGO)
    if mapa.faltando_obrigatorios:
        raise ErroImportacao(
            "O arquivo não parece ser uma exportação do Catálogo de Escolas: faltam as colunas "
            + ", ".join(mapa.faltando_obrigatorios) + "."
        )
    origem = mapa.interno_para_original
    col = lambda nome: tabela.dados[origem[nome]].tolist() if nome in origem else [None] * len(tabela.dados)  # noqa: E731
    codigos = [classificar_inep(v)[0] for v in col("co_entidade")]
    dados = pd.DataFrame({
        "co_entidade": codigos,
        "no_entidade": [limpar_texto(v) for v in col("no_entidade")],
        "sg_uf": [(limpar_texto(v) or "").upper() or None for v in col("sg_uf")],
        "co_municipio": [digitos_de_codigo(v)[0] for v in col("co_municipio")],
        "no_municipio": [limpar_texto(v) for v in col("no_municipio")],
        "dependencia": unificar_categorias(col("dependencia")),
        "categoria_administrativa": unificar_categorias(col("categoria_administrativa")),
        "localizacao": unificar_categorias(col("localizacao")),
        "localizacao_diferenciada": unificar_categorias(col("localizacao_diferenciada")),
        "situacao_funcionamento": unificar_categorias(col("situacao_funcionamento")),
        "etapas": [limpar_texto(v) for v in col("etapas")],
        "porte": unificar_categorias(col("porte")),
        "latitude": [_coordenada(v, -34.0, 6.0) for v in col("latitude")],
        "longitude": [_coordenada(v, -74.0, -28.0) for v in col("longitude")],
        "atributos": [{"ano_referencia_informado": ano_referencia} for _ in codigos],
    }, columns=COLUNAS["escolas"])
    meta = {
        "colunas_reconhecidas": sorted(origem.keys()),
        "colunas_nao_utilizadas": mapa.nao_mapeadas,
        "ano_referencia": ano_referencia,
        "com_coordenadas": int((dados["latitude"].notna() & dados["longitude"].notna()).sum()),
    }
    return dados, meta


# ---------------------------------------------------------------- prévia (mesmo fluxo das demais fontes)


def preparar_escolas(dados: pd.DataFrame, meta: dict, fonte: str, arquivos: list[dict], url: str | None = None):
    from .importacao import Previa

    dados = dados.copy()
    validos = [classificar_inep(c) for c in dados["co_entidade"]]
    dados["co_entidade"] = [c for c, _ in validos]
    duplicados = grupos_de_duplicidade([c for c, _ in validos], "ESC-")
    problemas = []
    for (_, status), dup in zip(validos, duplicados):
        p = []
        if status != "valido":
            p.append("escola_codigo_invalido")
        if dup:
            p.append("escola_codigo_duplicado")
        problemas.append(p)
    controle = pd.DataFrame({
        "co_entidade": dados["co_entidade"], "arquivo_origem": arquivos[0]["arquivo"] if arquivos else "",
        "linha_origem": range(2, len(dados) + 2), "problemas": problemas,
    })
    tabela = tabela_problemas(controle, "co_entidade", {})
    resumo = resumo_problemas(tabela, len(dados), "co_entidade")
    resumo.update({k: v for k, v in meta.items() if k != "variaveis_disponiveis"})
    resumo["fonte"] = fonte
    resumo["url"] = url
    resumo["variaveis_disponiveis"] = meta.get("variaveis_disponiveis")
    ano = meta.get("ano_referencia")
    bloqueios = [] if len(dados) else ["Nenhuma escola selecionada no arquivo (confira UFs e códigos)."]
    avisos = []
    if meta.get("md5_confere") is False:
        bloqueios.append("A soma MD5 do arquivo não confere com a publicada no pacote: o arquivo pode estar corrompido.")
    if ano is None:
        bloqueios.append("Não foi possível identificar o ano de referência da base escolar.")
    dados = dados.drop_duplicates("co_entidade").reset_index(drop=True)
    descricao = f"{fonte}, ano de referência {ano}" if ano else fonte
    return Previa(
        "escolas", dados[COLUNAS["escolas"]], tabela, bloqueios, avisos, resumo, arquivos, {},
        referencia_em=str(ano) if ano else None, referencia_descricao=descricao,
    )


# ---------------------------------------------------------------- download com cache

_TRAVA_IPV4 = threading.Lock()


@contextmanager
def _somente_ipv4():
    """Força IPv4 durante uma requisição (alguns servidores públicos derrubam rotas IPv6/NAT64)."""
    import urllib3.util.connection as conexao

    with _TRAVA_IPV4:
        original = conexao.allowed_gai_family
        conexao.allowed_gai_family = lambda: socket.AF_INET
        try:
            yield
        finally:
            conexao.allowed_gai_family = original


def cadeia_certificados(dir_cache: Path) -> str:
    """certifi + intermediário "RNP ICPEdu GR46 OV TLS CA 2025", que o servidor do Inep não envia.

    O intermediário é um certificado público emitido pela GlobalSign Root R46 (já
    confiável no certifi); a verificação TLS continua completa.
    """
    import certifi

    destino = dir_cache / "cadeia_certificados_inep.pem"
    conteudo = Path(certifi.where()).read_text(encoding="utf-8")
    if config.ARQ_CERT_INEP.exists():
        conteudo += "\n" + config.ARQ_CERT_INEP.read_text(encoding="utf-8")
    if not destino.exists() or destino.read_text(encoding="utf-8") != conteudo:
        destino.write_text(conteudo, encoding="utf-8")
    return str(destino)


def _requisitar(metodo: str, url: str, verificar: str, cabecalhos_extra: dict | None = None, **kwargs):
    import requests

    cabecalhos = {"User-Agent": "painel-acompanhamento-eti/1.0", **(cabecalhos_extra or {})}
    ultimo_erro: Exception | None = None
    for tentativa in range(4):
        forcar_ipv4 = tentativa % 2 == 1
        try:
            if forcar_ipv4:
                with _somente_ipv4():
                    resposta = requests.request(metodo, url, headers=cabecalhos, timeout=60,
                                                verify=verificar, **kwargs)
            else:
                resposta = requests.request(metodo, url, headers=cabecalhos, timeout=60,
                                            verify=verificar, **kwargs)
            resposta.raise_for_status()
            return resposta, forcar_ipv4
        except requests.HTTPError:
            raise
        except requests.RequestException as exc:
            ultimo_erro = exc
            time.sleep(1.5 * (tentativa + 1))
    raise ErroImportacao(
        "Não foi possível conectar ao servidor de downloads do Inep. Baixe o arquivo "
        f"manualmente em {config.PAGINA_MICRODADOS_INEP} e importe-o pela Administração."
    ) from ultimo_erro


def baixar_microdados(ano: int, dir_cache: Path, progresso=None) -> tuple[Path, dict]:
    """Baixa (ou reutiliza do cache) o pacote oficial de microdados do ano informado."""
    import requests

    if ano not in config.URLS_MICRODADOS_INEP:
        raise ErroImportacao(f"Não há endereço oficial cadastrado para os microdados de {ano}.")
    url = config.URLS_MICRODADOS_INEP[ano]
    dir_cache.mkdir(parents=True, exist_ok=True)
    destino = dir_cache / url.rsplit("/", 1)[-1]
    arquivo_meta = destino.with_suffix(".json")
    verificar = cadeia_certificados(dir_cache)
    try:
        cabeca, _ = _requisitar("HEAD", url, verificar, allow_redirects=True)
    except requests.HTTPError as exc:
        raise ErroImportacao(f"O Inep respondeu {exc.response.status_code} para o arquivo de {ano}.") from exc
    tamanho = int(cabeca.headers.get("Content-Length") or 0)
    publicado = cabeca.headers.get("Last-Modified")
    if destino.exists() and arquivo_meta.exists():
        meta = json.loads(arquivo_meta.read_text(encoding="utf-8"))
        if meta.get("tamanho") == tamanho and meta.get("publicado_em") == publicado:
            meta["origem_cache"] = True
            return destino, meta
    # Download retomável: um .parcial de tentativa anterior continua de onde parou (HTTP Range).
    parcial = destino.with_suffix(".parcial")
    ja_baixado = parcial.stat().st_size if parcial.exists() else 0
    extra = {"Range": f"bytes={ja_baixado}-"} if 0 < ja_baixado < tamanho else {}
    resposta, _ = _requisitar("GET", url, verificar, cabecalhos_extra=extra, stream=True)
    retomando = bool(extra) and resposta.status_code == 206
    baixados = ja_baixado if retomando else 0
    with open(parcial, "ab" if retomando else "wb") as f:
        for bloco in resposta.iter_content(1 << 20):
            f.write(bloco)
            baixados += len(bloco)
            if progresso and tamanho:
                progresso(min(baixados / tamanho, 1.0))
    if tamanho and baixados != tamanho:
        raise ErroImportacao("O download foi interrompido; tente de novo para continuar de onde parou.")
    soma = hashlib.sha256()
    with open(parcial, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            soma.update(bloco)
    parcial.replace(destino)
    meta = {
        "url": url, "ano": ano, "tamanho": baixados, "publicado_em": publicado,
        "baixado_em": agora_utc(), "sha256": soma.hexdigest(), "origem_cache": False,
    }
    arquivo_meta.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return destino, meta


# ---------------------------------------------------------------- enriquecimento

SITUACAO_INEP_LOCALIZADO = "Localizado na base escolar"
SITUACAO_INEP_NAO_LOCALIZADO = "Não localizado na base escolar"
SITUACAO_INEP_SEM_BASE = "Base escolar não carregada"
SITUACAO_INEP_INVALIDO = "Código inválido"
SITUACAO_INEP_AUSENTE = "Código ausente"
ORDEM_SITUACAO_INEP = (
    SITUACAO_INEP_LOCALIZADO, SITUACAO_INEP_NAO_LOCALIZADO, SITUACAO_INEP_SEM_BASE,
    SITUACAO_INEP_INVALIDO, SITUACAO_INEP_AUSENTE,
)


def enriquecer(cursistas: pd.DataFrame, escolas: pd.DataFrame) -> pd.DataFrame:
    """Acrescenta dados oficiais da escola, sempre pelo código INEP (nunca pelo nome)."""
    base_carregada = not escolas.empty
    esc = escolas.drop_duplicates("co_entidade").set_index("co_entidade") if base_carregada else None
    resultado = cursistas.copy()
    situacoes = []
    for codigo, status in zip(resultado["inep"], resultado["inep_status"]):
        if status == "ausente":
            situacoes.append(SITUACAO_INEP_AUSENTE)
        elif status != "valido":
            situacoes.append(SITUACAO_INEP_INVALIDO)
        elif not base_carregada:
            situacoes.append(SITUACAO_INEP_SEM_BASE)
        elif codigo in esc.index:
            situacoes.append(SITUACAO_INEP_LOCALIZADO)
        else:
            situacoes.append(SITUACAO_INEP_NAO_LOCALIZADO)
    resultado["situacao_inep"] = situacoes
    campos = {
        "no_entidade": "escola_oficial", "sg_uf": "uf_escola", "co_municipio": "cod_municipio_escola",
        "no_municipio": "municipio_escola", "dependencia": "dependencia",
        "categoria_administrativa": "categoria_administrativa", "localizacao": "localizacao",
        "localizacao_diferenciada": "localizacao_diferenciada",
        "situacao_funcionamento": "situacao_funcionamento", "etapas": "etapas", "porte": "porte",
    }
    for origem, destino in campos.items():
        if base_carregada:
            resultado[destino] = resultado["inep"].map(esc[origem]).where(
                resultado["situacao_inep"] == SITUACAO_INEP_LOCALIZADO)
        else:
            resultado[destino] = None
    return resultado


def tabela_atributos(escolas: pd.DataFrame) -> pd.DataFrame:
    """Expande o JSON de atributos (indicadores do Censo) em colunas."""
    if escolas.empty:
        return pd.DataFrame()
    linhas = []
    for codigo, atributos in zip(escolas["co_entidade"], escolas["atributos"]):
        dados = atributos if isinstance(atributos, dict) else json.loads(atributos or "{}")
        linhas.append({"co_entidade": codigo, **dados})
    return pd.DataFrame(linhas)
