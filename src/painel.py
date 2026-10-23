"""Base analítica do painel e filtros globais.

Une os retratos ativos (cadastro, atividade, escolas) com a conciliação e
deriva as classificações operacionais. As funções ``montar_*`` são puras e
testáveis; as que usam Streamlit ficam no fim do módulo.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta

import pandas as pd

from . import reconciliation as rc
from . import school_data
from .normalization import chave_comparacao
from .persistence import Repositorio

FAIXA_NUNCA = "Nunca acessou"
FAIXA_NAO_INTERPRETADO = "Acesso não interpretado"
FAIXA_SEM_CONTA = "Sem conta associada"

MOTIVO_SEM_CONTA = "Sem conta localizada"
MOTIVO_CONTA_INATIVA = "Conta não ativa"
MOTIVO_NUNCA = "Sem registro de acesso"
MOTIVO_INATIVIDADE = "Inatividade acima do limite"
MOTIVO_CONCILIACAO = "Conciliação pendente"
PRIORIDADE_MOTIVO = {MOTIVO_NUNCA: 1, MOTIVO_SEM_CONTA: 1, MOTIVO_CONTA_INATIVA: 2,
                     MOTIVO_INATIVIDADE: 3, MOTIVO_CONCILIACAO: 4}

FILTROS = (
    ("regiao", "Região"), ("uf", "UF"), ("ente", "Ente"), ("ciclo", "Ciclo"),
    ("articulador", "Articulador"), ("esfera", "Esfera"), ("tipo", "Tipo"), ("origem", "Origem"),
    ("situacao", "Situação cadastral"), ("grupo", "Grupo de formação"),
    ("municipio_escola", "Município da escola"),
)
FILTROS_PRINCIPAIS = ("regiao", "uf", "ente", "ciclo")

# Grupos da galeria de cursistas (os destaques da Visão geral levam direto a eles)
GRUPO_TODAS = "Todas as pessoas"
GRUPO_ACOMPANHAMENTO = "Requerem acompanhamento"
GRUPO_NUNCA = "Nunca acessaram"
GRUPO_SEM_CONTA = "Sem conta na plataforma"
GRUPO_CONCILIACAO = "Conta em conciliação"


def grupo_recentes(janela: int) -> str:
    return f"Acesso nos últimos {janela} dias"


def grupo_inativos(limite: int) -> str:
    return f"Sem acesso há mais de {limite} dias"


# Perfil (cadastro) e contexto da escola (Censo): colunas levadas também às contas vinculadas
DIMENSOES_PERFIL = (
    ("Cargo ou função", "cargo_funcao"), ("Origem da vaga", "origem"), ("Escolaridade", "escolaridade"),
    ("Esfera", "esfera"), ("Semana da inscrição", "semana_inscricao"),
)
DIMENSOES_ESCOLA = (
    ("Localização da escola", "localizacao"), ("Área diferenciada", "localizacao_diferenciada"),
    ("Internet na escola", "internet_escola"), ("Banda larga na escola", "banda_larga_escola"),
)
COLUNAS_PERFIL = tuple(c for _, c in (*DIMENSOES_PERFIL, *DIMENSOES_ESCOLA))

# Categorias que vêm sem acento na planilha: muda só a exibição, o valor gravado fica como veio
ROTULOS_EXIBICAO = {"escolaridade": {"Especializacao": "Especialização", "Medio": "Médio"}}
# Ordem de exibição das categorias que têm ordem própria (as demais seguem a ordem alfabética/natural)
ORDENS = {"escolaridade": ("Fundamental", "Medio", "Superior", "Especializacao", "Mestrado", "Doutorado")}


def rotulos_faixas(limites: list[int]) -> list[str]:
    """Faixas de tempo desde o último acesso: [0, l1), [l1, l2), [l2, l3] e mais de l3 dias."""
    l1, l2, l3 = limites
    return [
        "Até 24 horas" if l1 == 1 else f"Até {l1} dias",
        f"{l1} a {l2} dias",
        f"{l2} a {l3} dias",
        f"Mais de {l3} dias",
    ]


def ordem_faixas(limites: list[int]) -> list[str]:
    return [*rotulos_faixas(limites), FAIXA_NUNCA, FAIXA_NAO_INTERPRETADO, FAIXA_SEM_CONTA]


def classificar_faixa(acesso_tipo, segundos, limites: list[int]) -> str:
    if acesso_tipo == "nunca":
        return FAIXA_NUNCA
    if segundos is None or (isinstance(segundos, float) and math.isnan(segundos)):
        return FAIXA_NAO_INTERPRETADO
    dias = segundos / 86400
    rotulos = rotulos_faixas(limites)
    l1, l2, l3 = limites
    if dias < l1:
        return rotulos[0]
    if dias < l2:
        return rotulos[1]
    return rotulos[2] if dias <= l3 else rotulos[3]


def _lista(valor) -> list:
    if isinstance(valor, list):
        return valor
    if valor is None or (isinstance(valor, float) and math.isnan(valor)):
        return []
    try:
        return json.loads(valor)
    except (TypeError, ValueError):
        return []


def _grupos(valor) -> list[str]:
    if not isinstance(valor, str) or not valor.strip():
        return []
    return [g.strip() for g in valor.split(",") if g.strip()]


@dataclass
class Base:
    cursistas: pd.DataFrame
    contas: pd.DataFrame
    escolas: pd.DataFrame
    atributos_escolas: pd.DataFrame
    associacoes: pd.DataFrame
    candidatos: pd.DataFrame
    problemas_cadastro: pd.DataFrame
    problemas_atividade: pd.DataFrame
    decisoes: pd.DataFrame
    meta: dict
    parametros: dict
    alertas_conciliacao: list[str] = field(default_factory=list)

    @property
    def tem_cadastro(self) -> bool:
        return not self.cursistas.empty

    @property
    def tem_atividade(self) -> bool:
        return not self.contas.empty

    @property
    def tem_escolas(self) -> bool:
        return not self.escolas.empty


def _problemas_longos(registros: pd.DataFrame, coluna_id: str, mapeamento: dict) -> pd.DataFrame:
    from .validators import tabela_problemas

    cabecalhos = {arquivo: {v: k for k, v in mapa.items()} for arquivo, mapa in (mapeamento or {}).items()}
    return tabela_problemas(registros, coluna_id, cabecalhos)


def montar_base(repo: Repositorio, fuso: str = "America/Sao_Paulo") -> Base:
    parametros = repo.parametros()
    limites = parametros["faixas_inatividade_dias"]
    limite_acomp = parametros["limite_acompanhamento_dias"]
    situacoes_ativas = {s.strip().lower() for s in parametros["situacoes_conta_ativa"]}
    meta = {f: repo.importacao_ativa(f) for f in ("cadastro", "atividade", "escolas")}

    cad = repo.registros("cadastro")
    atv = repo.registros("atividade")
    esc = repo.registros("escolas")
    # A base escolar cobre UFs inteiras; o painel só precisa das escolas citadas no cadastro.
    esc = esc[esc["co_entidade"].isin(set(cad["inep"].dropna()))].reset_index(drop=True)
    cad["problemas"] = cad["problemas"].map(_lista)
    atv["problemas"] = atv["problemas"].map(_lista)
    if not esc.empty:
        esc["atributos"] = esc["atributos"].map(lambda v: json.loads(v) if isinstance(v, str) else (v or {}))
    for coluna in ("eh_cursista", "eh_equipe"):
        atv[coluna] = pd.to_numeric(atv[coluna], errors="coerce").fillna(0).astype(int)
    atv["acesso_segundos"] = pd.to_numeric(atv["acesso_segundos"], errors="coerce")
    # Dia do último acesso no fuso do painel: só existe quando a lista tem data de referência
    momentos = pd.to_datetime(atv["acesso_momento"], errors="coerce", utc=True)
    atv["acesso_dia"] = momentos.dt.tz_convert(fuso).dt.strftime("%Y-%m-%d")
    decisoes = repo.decisoes()

    resultado = rc.conciliar(cad, atv, decisoes) if not cad.empty else None

    # --- contas
    atv["faixa_acesso"] = [classificar_faixa(t, s, limites) for t, s in zip(atv["acesso_tipo"], atv["acesso_segundos"])]
    atv["dias_sem_acesso"] = (atv["acesso_segundos"] / 86400).astype("Float64")
    atv["conta_ativa"] = atv["situacao_conta"].fillna("").str.strip().str.lower().isin(situacoes_ativas)
    atv["lista_grupos"] = atv["grupos"].map(_grupos)
    if resultado is not None:
        contas = atv.merge(resultado.status_contas, on="id_conta", how="left")
    else:
        contas = atv.assign(status_conciliacao=rc.SEM_CORRESPONDENCIA, n_pessoas=0)

    # --- cursistas (um registro de inscrição por linha)
    cursistas = cad.copy()
    if resultado is not None:
        cursistas = cursistas.merge(resultado.status_registros, on="id_registro", how="left")
    else:
        cursistas = cursistas.assign(status_conciliacao=None, regra_conciliacao=None, id_conta=None)
    campos_conta = ["id_conta", "nome_completo", "email", "papeis", "grupos", "lista_grupos", "situacao_conta",
                    "conta_ativa", "ultimo_acesso_texto", "acesso_tipo", "acesso_segundos", "acesso_momento",
                    "acesso_dia", "acesso_base", "faixa_acesso", "dias_sem_acesso", "eh_cursista", "eh_equipe"]
    contas_resumo = atv[campos_conta].rename(columns={"nome_completo": "conta_nome", "email": "conta_email"})
    cursistas = cursistas.merge(contas_resumo, on="id_conta", how="left")
    ha_atividade = not atv.empty
    # Sem base de atividade não há como dizer que a conta não existe: a faixa fica vazia.
    cursistas.loc[cursistas["id_conta"].isna(), "faixa_acesso"] = FAIXA_SEM_CONTA if ha_atividade else None
    cursistas["lista_grupos"] = cursistas["lista_grupos"].map(lambda v: v if isinstance(v, list) else [])

    motivos, prioridades = [], []
    colunas_motivo = ["status_conciliacao", "id_conta", "conta_ativa", "acesso_tipo", "dias_sem_acesso"]
    for linha in cursistas[colunas_motivo].itertuples(index=False):
        m = []
        if ha_atividade and pd.isna(linha.id_conta):
            m.append(MOTIVO_CONCILIACAO if linha.status_conciliacao in (rc.PENDENTE, rc.AMBIGUO) else MOTIVO_SEM_CONTA)
        elif ha_atividade:
            if not pd.isna(linha.conta_ativa) and not bool(linha.conta_ativa):
                m.append(MOTIVO_CONTA_INATIVA)
            if linha.acesso_tipo == "nunca":
                m.append(MOTIVO_NUNCA)
            elif not pd.isna(linha.dias_sem_acesso) and linha.dias_sem_acesso > limite_acomp:
                m.append(MOTIVO_INATIVIDADE)
        motivos.append(m)
        prioridades.append(min((PRIORIDADE_MOTIVO[x] for x in m), default=None))
    cursistas["conta_ativa"] = cursistas["conta_ativa"].astype("boolean")
    cursistas["motivos"] = motivos
    cursistas["requer_acompanhamento"] = [
        any(x != MOTIVO_CONCILIACAO for x in m) for m in motivos
    ]
    cursistas["prioridade"] = pd.array(prioridades, dtype="Int64")
    cursistas = school_data.enriquecer(cursistas, esc)
    atributos = school_data.tabela_atributos(esc)
    cursistas["semana_inscricao"] = semana_de(cursistas["data_resposta"])
    cursistas["internet_escola"], cursistas["banda_larga_escola"] = _conectividade(cursistas["inep"], atributos)
    cursistas["grupo"] = cursistas["lista_grupos"].map(", ".join).replace("", None)
    # Busca por nome, escola (informada e oficial), ente, município da escola, turma e código INEP
    cursistas["texto_busca"] = [
        " ".join(filter(None, [chave_comparacao(x) if isinstance(x, str) else None for x in campos[:-1]] + [str(campos[-1] or "")]))
        for campos in zip(cursistas["nome"], cursistas["escola"], cursistas["escola_oficial"], cursistas["ente"],
                          cursistas["municipio_escola"], cursistas["grupo"], cursistas["inep"].fillna(""))
    ]

    # Território, perfil e escola da pessoa vinculada: para filtrar e comparar as contas
    colunas_vinculo = ["uf", "ente", "articulador", "ciclo", *COLUNAS_PERFIL]
    if resultado is not None and not resultado.associacoes.empty:
        vinculo = (resultado.associacoes.merge(cursistas[["id_registro", *colunas_vinculo]], on="id_registro")
                   .drop_duplicates("id_conta")[["id_conta", *colunas_vinculo]])
        contas = contas.merge(vinculo, on="id_conta", how="left")
    else:
        contas = contas.assign(**dict.fromkeys(colunas_vinculo))

    return Base(
        cursistas=cursistas,
        contas=contas,
        escolas=esc,
        atributos_escolas=atributos,
        associacoes=resultado.associacoes if resultado else pd.DataFrame(),
        candidatos=resultado.candidatos if resultado else pd.DataFrame(),
        problemas_cadastro=_problemas_longos(cad, "id_registro", (meta["cadastro"] or {}).get("mapeamento")),
        problemas_atividade=_problemas_longos(atv, "id_conta", (meta["atividade"] or {}).get("mapeamento")),
        decisoes=decisoes,
        meta=meta,
        parametros=parametros,
        alertas_conciliacao=resultado.alertas if resultado else [],
    )


def semana_de(datas: pd.Series) -> pd.Series:
    """Segunda-feira da semana de cada data (AAAA-MM-DD), para agrupar as respostas às inscrições."""
    dias = pd.to_datetime(datas, errors="coerce", format="%Y-%m-%d")
    return (dias - pd.to_timedelta(dias.dt.weekday, unit="D")).dt.strftime("%Y-%m-%d")


def _conectividade(inep: pd.Series, atributos: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Internet e banda larga da escola segundo o Censo; vazio quando a escola não foi localizada."""
    if atributos.empty or "IN_INTERNET" not in atributos:
        return pd.Series(None, index=inep.index, dtype=object), pd.Series(None, index=inep.index, dtype=object)
    tabela = atributos.drop_duplicates("co_entidade").set_index("co_entidade")
    internet = inep.map(tabela["IN_INTERNET"])
    banda = inep.map(tabela["IN_BANDA_LARGA"]) if "IN_BANDA_LARGA" in tabela else pd.Series(None, index=inep.index)
    texto_internet = internet.map({"1": "Com internet", "0": "Sem internet"})
    # O Censo só pergunta sobre banda larga a quem tem internet: sem internet, não há banda larga
    texto_banda = banda.map({"1": "Com banda larga", "0": "Sem banda larga"}).where(
        banda.notna(), internet.map({"0": "Sem banda larga"}))
    return texto_internet, texto_banda


def rotulo(coluna: str, valor) -> str:
    """Texto de exibição de uma categoria; o valor original não muda."""
    if coluna == "semana_inscricao" and isinstance(valor, str):
        inicio = date.fromisoformat(valor)
        return f"{inicio:%d/%m} a {inicio + timedelta(days=6):%d/%m}"
    return ROTULOS_EXIBICAO.get(coluna, {}).get(valor, valor)


def chave_ordem(coluna: str, valor):
    """Chave de ordenação das categorias de uma coluna (ordem própria, quando há, ou ordem natural)."""
    ordem = ORDENS.get(coluna)
    if ordem and valor in ordem:
        return (0, ordem.index(valor), [])
    return (1, 0, ordem_natural(valor))


def classes_de_dias(dias: pd.Series, limites: list[int], marcas: tuple[int, ...] = ()) -> pd.DataFrame:
    """Classes do histograma do tempo sem acesso (em dias), cada uma dentro de uma única faixa de acesso.

    As bordas são as das faixas, as ``marcas`` (janela de acesso recente, limite de acompanhamento) e
    valores "redondos" entre elas; classes vazias depois do maior valor observado são omitidas.
    """
    l1, l2, l3 = limites
    rotulos = rotulos_faixas(limites)
    faixas = [(0, l1, rotulos[0]), (l1, l2, rotulos[1]), (l2, l3, rotulos[2]), (l3, math.inf, rotulos[3])]
    candidatas = sorted({1, 2, 3, 5, 7, 10, 14, 21, 30, 45, 60, 90, 120, 180, 365, *limites, *marcas})
    valores = pd.to_numeric(dias, errors="coerce").dropna()
    maximo = float(valores.max()) if not valores.empty else 0.0
    linhas = []
    for inicio, fim, faixa in faixas:
        bordas = [inicio, *[b for b in candidatas if inicio < b < fim], fim]
        for a, b in zip(bordas, bordas[1:]):
            if a > maximo and linhas:
                break
            # As faixas são [0, l1), [l1, l2), [l2, l3] e (l3, ∞): a borda l3 fica na terceira faixa
            if faixa == rotulos[2] and b == l3:
                dentro = (valores >= a) & (valores <= b)
            elif faixa == rotulos[3] and a == l3:
                dentro = (valores > a) & (valores < b)
            else:
                dentro = (valores >= a) & (valores < b)
            linhas.append({"inicio": a, "fim": b, "faixa": faixa, "contagem": int(dentro.sum())})
    return pd.DataFrame(linhas, columns=["inicio", "fim", "faixa", "contagem"])


def resumo_turmas(contas: pd.DataFrame, janela: int, limite: int) -> pd.DataFrame:
    """Uma linha por turma (grupo da plataforma), com os estudantes e a situação de acesso de cada um.

    Estudantes são as contas com papel de cursista; a equipe (formadores, coordenação, suporte) só é
    contada por papel. Uma conta em duas turmas conta nas duas.
    """
    colunas = ["grupo", "rotulo", "estado", "numero", "estudantes", "acessaram", "nunca", "recentes", "inativos",
               "atencao", "taxa_acesso", "faixas", "equipe"]
    turmas: dict[str, dict] = {}
    for conta in contas.itertuples(index=False):
        for grupo in conta.lista_grupos:
            item = turmas.setdefault(grupo, {"grupo": grupo, "estudantes": 0, "acessaram": 0, "nunca": 0,
                                             "recentes": 0, "inativos": 0, "atencao": 0, "faixas": [],
                                             "equipe": Counter()})
            if conta.eh_equipe == 1:
                for papel in (conta.papeis if isinstance(conta.papeis, str) else "").split(","):
                    if papel.strip():
                        item["equipe"][papel.strip()] += 1
            if conta.eh_cursista != 1:
                continue
            dias = conta.dias_sem_acesso
            nunca = conta.acesso_tipo == "nunca"
            inativa = not pd.isna(dias) and dias > limite
            item["estudantes"] += 1
            item["acessaram"] += conta.acesso_tipo in ("relativo", "absoluto")
            item["nunca"] += nunca
            item["recentes"] += not pd.isna(dias) and dias <= janela
            item["inativos"] += inativa
            item["atencao"] += nunca or inativa or not bool(conta.conta_ativa)
            item["faixas"].append(conta.faixa_acesso)
    linhas = []
    for item in turmas.values():
        if not item["estudantes"]:
            continue
        identificada = turma(item["grupo"])
        item["estado"], item["numero"] = identificada if identificada else (None, None)
        item["rotulo"] = f"{identificada[0]} · T{identificada[1]}" if identificada else item["grupo"]
        item["taxa_acesso"] = item["acessaram"] / item["estudantes"]
        item["equipe"] = dict(item["equipe"])
        linhas.append(item)
    return pd.DataFrame(linhas, columns=colunas)


def turma(grupo: str) -> tuple[str, int] | None:
    """Turmas nomeadas como "<Estado> <n>" (ex.: "Para 3") -> ("Pará", 3); outras -> None."""
    import re

    from .config import NOME_DA_SIGLA

    m = re.fullmatch(r"\s*(.+?)\s+(\d+)\s*", grupo or "")
    if not m:
        return None
    chave = chave_comparacao(m.group(1))
    for nome in NOME_DA_SIGLA.values():
        if chave_comparacao(nome) == chave:
            return nome, int(m.group(2))
    return None


def municipio_do_registro(cursistas: pd.DataFrame) -> pd.Series:
    """Município da escola segundo o Inep; na falta dele, o código IBGE do ente quando é municipal (7 dígitos)."""
    escola = cursistas["cod_municipio_escola"] if "cod_municipio_escola" in cursistas else pd.Series(None, index=cursistas.index)
    ente = cursistas["cod_ibge"].where(cursistas["cod_ibge"].fillna("").str.len() == 7)
    return escola.fillna(ente)


def chave_escola(cursistas: pd.DataFrame) -> pd.Series:
    """Identifica a escola: código INEP válido ou, sem ele, o nome informado + UF."""
    sem_codigo = "sem-inep:" + cursistas["escola"].fillna("escola não informada") + "|" + cursistas["uf"].fillna("")
    return cursistas["inep"].where(cursistas["inep_status"] == "valido", sem_codigo)


def resumo_escolas(cursistas: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por escola, com pessoas distintas e situação de acesso dos seus cursistas."""
    colunas = ["chave_escola", "inep", "escola", "escola_informada", "municipio", "cod_municipio", "uf", "dependencia",
               "localizacao", "situacao_inep", "pessoas", "com_conta", "acessaram", "nunca", "acompanhamento",
               "taxa_acesso"]
    if cursistas.empty:
        return pd.DataFrame(columns=colunas)
    dados = cursistas.assign(chave_escola=chave_escola(cursistas)).drop_duplicates(["chave_escola", "chave_pessoa"])
    com_conta = dados["id_conta"].notna()
    dados = dados.assign(
        _conta=com_conta,
        _acessou=com_conta & dados["acesso_tipo"].isin(["relativo", "absoluto"]),
        _nunca=com_conta & (dados["acesso_tipo"] == "nunca"),
        _acomp=dados["requer_acompanhamento"].astype(bool),
        _municipio=dados["municipio_escola"].fillna(dados["ente"]),
        _cod_municipio=municipio_do_registro(dados),
    )
    resumo = dados.groupby("chave_escola").agg(
        inep=("inep", "first"), escola=("escola_oficial", "first"), escola_informada=("escola", "first"),
        municipio=("_municipio", "first"), cod_municipio=("_cod_municipio", "first"), uf=("uf", "first"),
        dependencia=("dependencia", "first"), localizacao=("localizacao", "first"),
        situacao_inep=("situacao_inep", "first"), pessoas=("chave_pessoa", "nunique"), com_conta=("_conta", "sum"),
        acessaram=("_acessou", "sum"), nunca=("_nunca", "sum"), acompanhamento=("_acomp", "sum"),
    ).reset_index()
    resumo["escola"] = resumo["escola"].fillna(resumo["escola_informada"])
    resumo["taxa_acesso"] = resumo["acessaram"] / resumo["com_conta"].where(resumo["com_conta"] > 0)
    return resumo[colunas]


def pessoas_de(cursistas: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por pessoa (chave pseudônima), mantendo o registro mais bem conciliado."""
    if cursistas.empty:
        return cursistas
    ordem = {s: i for i, s in enumerate(rc.STATUS_ORDEM)}
    return (cursistas.assign(_ordem=cursistas["status_conciliacao"].map(ordem).fillna(len(ordem)))
            .sort_values(["_ordem", "id_registro"])
            .drop_duplicates("chave_pessoa")
            .drop(columns="_ordem"))


def opcoes_filtro(base: Base, coluna: str, filtros: dict) -> list[str]:
    dados = base.cursistas
    if coluna == "grupo":
        valores = {g for gs in dados["lista_grupos"] for g in gs}
        return sorted(valores, key=ordem_natural)
    if coluna == "ente" and filtros.get("uf"):
        dados = dados[dados["uf"].isin(filtros["uf"])]
    if coluna not in dados:
        return []
    return sorted(dados[coluna].dropna().unique().tolist(), key=ordem_natural)


def ordem_natural(texto: str):
    import re

    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", str(texto))]


def aplicar_filtros(base: Base, filtros: dict[str, list]) -> tuple[pd.DataFrame, pd.DataFrame]:
    cursistas = base.cursistas
    filtro_cadastro = False
    grupos = filtros.get("grupo") or []
    for coluna, valores in filtros.items():
        if not valores:
            continue
        if coluna == "grupo":
            selecionados = set(valores)
            cursistas = cursistas[cursistas["lista_grupos"].map(lambda gs: bool(selecionados & set(gs)))]
        elif coluna in cursistas:
            cursistas = cursistas[cursistas[coluna].isin(valores)]
            filtro_cadastro = True
    contas = base.contas
    if any(filtros.values()) and not contas.empty:
        mascara = contas["id_conta"].isin(set(cursistas["id_conta"].dropna()))
        if not filtro_cadastro and grupos:
            sem_vinculo = contas["status_conciliacao"] != rc.CORRESPONDENTE
            no_grupo = contas["lista_grupos"].map(lambda gs: bool(set(grupos) & set(gs)))
            mascara |= sem_vinculo & no_grupo
        contas = contas[mascara]
    return cursistas, contas


# ---------------------------------------------------------------- Streamlit


@dataclass
class Contexto:
    cfg: object
    usuario: object
    repo: Repositorio
    base: Base
    filtros: dict
    cursistas: pd.DataFrame
    contas: pd.DataFrame
    pseudo: object

    @property
    def filtros_ativos(self) -> bool:
        return any(self.filtros.values())


def carregar_base(repo: Repositorio, fuso: str = "America/Sao_Paulo") -> Base:
    import streamlit as st

    @st.cache_data(show_spinner="Carregando dados…", max_entries=6, ttl=3600)
    def _carregar(caminho: str, versao: str, retencao: int, fuso: str) -> Base:
        return montar_base(Repositorio(caminho, retencao), fuso)

    return _carregar(str(repo.caminho), repo.versao(), repo.retencao, fuso)


def contexto():
    import streamlit as st

    ctx = st.session_state.get("_contexto")
    if ctx is None:
        st.error("A página foi aberta fora do fluxo do painel. Volte à página inicial.")
        st.stop()
    return ctx
