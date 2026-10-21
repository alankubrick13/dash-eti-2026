"""Base analítica do painel e filtros globais.

Une os retratos ativos (cadastro, atividade, escolas) com a conciliação e
deriva as classificações operacionais. As funções ``montar_*`` são puras e
testáveis; as que usam Streamlit ficam no fim do módulo.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field

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


def montar_base(repo: Repositorio) -> Base:
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
                    "acesso_base", "faixa_acesso", "dias_sem_acesso", "eh_cursista", "eh_equipe"]
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
    cursistas["grupo"] = cursistas["lista_grupos"].map(", ".join).replace("", None)
    # Busca por nome, escola (informada e oficial), ente, município da escola, turma e código INEP
    cursistas["texto_busca"] = [
        " ".join(filter(None, [chave_comparacao(x) if isinstance(x, str) else None for x in campos[:-1]] + [str(campos[-1] or "")]))
        for campos in zip(cursistas["nome"], cursistas["escola"], cursistas["escola_oficial"], cursistas["ente"],
                          cursistas["municipio_escola"], cursistas["grupo"], cursistas["inep"].fillna(""))
    ]

    # Atributos territoriais da pessoa vinculada, para filtrar contas por território
    if resultado is not None and not resultado.associacoes.empty:
        vinculo = (resultado.associacoes.merge(cad[["id_registro", "uf", "ente", "articulador", "ciclo"]], on="id_registro")
                   .drop_duplicates("id_conta")[["id_conta", "uf", "ente", "articulador", "ciclo"]])
        contas = contas.merge(vinculo, on="id_conta", how="left")
    else:
        contas = contas.assign(uf=None, ente=None, articulador=None, ciclo=None)

    return Base(
        cursistas=cursistas,
        contas=contas,
        escolas=esc,
        atributos_escolas=school_data.tabela_atributos(esc),
        associacoes=resultado.associacoes if resultado else pd.DataFrame(),
        candidatos=resultado.candidatos if resultado else pd.DataFrame(),
        problemas_cadastro=_problemas_longos(cad, "id_registro", (meta["cadastro"] or {}).get("mapeamento")),
        problemas_atividade=_problemas_longos(atv, "id_conta", (meta["atividade"] or {}).get("mapeamento")),
        decisoes=decisoes,
        meta=meta,
        parametros=parametros,
        alertas_conciliacao=resultado.alertas if resultado else [],
    )


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


def carregar_base(repo: Repositorio) -> Base:
    import streamlit as st

    @st.cache_data(show_spinner="Carregando dados…", max_entries=6, ttl=3600)
    def _carregar(caminho: str, versao: str, retencao: int) -> Base:
        return montar_base(Repositorio(caminho, retencao))

    return _carregar(str(repo.caminho), repo.versao(), repo.retencao)


def contexto():
    import streamlit as st

    ctx = st.session_state.get("_contexto")
    if ctx is None:
        st.error("A página foi aberta fora do fluxo do painel. Volte à página inicial.")
        st.stop()
    return ctx
