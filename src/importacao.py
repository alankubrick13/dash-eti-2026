"""Pipeline de importação: mapeamento → normalização → validação → prévia → confirmação.

Nada é gravado até a confirmação explícita. CPF e data de nascimento são usados
apenas em memória (validação e duplicidades) e não são persistidos.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

import pandas as pd

from . import config
from .loaders import CAMPOS_ATIVIDADE, CAMPOS_CADASTRO, Mapeamento, TabelaBruta, mapear_colunas
from .normalization import (
    chave_comparacao,
    classificar_ibge,
    eh_vazio,
    classificar_inep,
    interpretar_data,
    interpretar_ultimo_acesso,
    limpar_texto,
    normalizar_email,
    normalizar_uf,
    sigla_uf_do_codigo,
    unificar_categorias,
    validar_cpf,
)
from .persistence import COLUNAS, Repositorio, agora_utc
from .security import Pseudonimizador
from .validators import grupos_de_duplicidade, resumo_problemas, tabela_problemas, verificar_estrutura

CATEGORICOS_CADASTRO = (
    "regiao", "ente", "ciclo", "articulador", "esfera", "tipo", "origem", "situacao",
    "raca_cor", "genero", "escolaridade", "cargo_funcao", "escola", "whatsapp",
)
SEM_GRUPO = {"nenhum grupo", "no groups", "sem grupo", "nenhum", "none"}
LIMITE_EMAILS_INVALIDOS = 0.5


@dataclass
class Previa:
    fonte: str
    registros: pd.DataFrame
    problemas: pd.DataFrame
    bloqueios: list[str]
    avisos: list[str]
    resumo: dict
    arquivos: list[dict]
    mapeamentos: dict[str, dict[str, str]]
    referencia_em: str | None = None
    referencia_descricao: str | None = None
    importado_em: str = field(default_factory=agora_utc)
    exige_confirmacao: list[str] = field(default_factory=list)

    @property
    def pode_confirmar(self) -> bool:
        return not self.bloqueios and not self.registros.empty

    def metadados(self) -> dict:
        return {
            "arquivos": self.arquivos,
            "importado_em": self.importado_em,
            "referencia_em": self.referencia_em,
            "referencia_descricao": self.referencia_descricao,
            "n_com_problemas": self.resumo.get("n_com_problemas"),
            "n_duplicados": self.resumo.get("n_duplicados"),
            "mapeamento": self.mapeamentos,
            "resumo": self.resumo,
        }


@lru_cache(maxsize=1)
def carregar_municipios() -> dict[str, tuple[str, str]] | None:
    """Lista oficial de municípios do IBGE: código -> (nome, UF)."""
    if not config.ARQ_MUNICIPIOS.exists():
        return None
    with open(config.ARQ_MUNICIPIOS, encoding="utf-8") as f:
        return {linha["codigo_ibge"]: (linha["nome"], linha["uf"]) for linha in csv.DictReader(f)}


def _aplicar_mapeamento(tabela: TabelaBruta, mapa: Mapeamento, campos) -> pd.DataFrame:
    dados = {}
    for campo in campos:
        original = mapa.interno_para_original.get(campo.nome)
        dados[campo.nome] = tabela.dados[original].tolist() if original else [None] * len(tabela.dados)
    quadro = pd.DataFrame(dados, dtype=object)
    quadro["arquivo_origem"] = tabela.arquivo
    quadro["linha_origem"] = tabela.dados["__linha__"].astype(int).tolist()
    return quadro


def _mapeamentos_texto(mapas: dict[str, Mapeamento]) -> dict[str, dict[str, str]]:
    return {arquivo: dict(m.original_para_interno) for arquivo, m in mapas.items()}


def _cabecalhos_por_campo(mapas: dict[str, Mapeamento]) -> dict[str, dict[str, str]]:
    return {arquivo: m.interno_para_original for arquivo, m in mapas.items()}


def _previa_bloqueada(fonte, tabelas, mapas, bloqueios, avisos) -> Previa:
    return Previa(
        fonte=fonte,
        registros=pd.DataFrame(columns=COLUNAS[fonte]),
        problemas=pd.DataFrame(),
        bloqueios=bloqueios,
        avisos=avisos,
        resumo={},
        arquivos=[t.metadados() for t in tabelas],
        mapeamentos=_mapeamentos_texto(mapas),
    )


# ---------------------------------------------------------------- cadastro


def preparar_cadastro(
    tabelas: list[TabelaBruta],
    pseudo: Pseudonimizador,
    manual: dict[str, dict[str, str]] | None = None,
    hoje: date | None = None,
) -> Previa:
    hoje = hoje or date.today()
    municipios = carregar_municipios()
    mapas = {
        t.arquivo: mapear_colunas(t.cabecalhos, CAMPOS_CADASTRO, (manual or {}).get(t.arquivo))
        for t in tabelas
    }
    bloqueios, avisos = verificar_estrutura(mapas, sum(len(t.dados) for t in tabelas), campos=CAMPOS_CADASTRO)
    for t in tabelas:
        avisos.extend(f"“{t.arquivo}”: {a}" for a in t.avisos)
    if bloqueios:
        return _previa_bloqueada("cadastro", tabelas, mapas, bloqueios, avisos)

    bruto = pd.concat([_aplicar_mapeamento(t, mapas[t.arquivo], CAMPOS_CADASTRO) for t in tabelas],
                      ignore_index=True)
    n = len(bruto)
    reg = pd.DataFrame(index=range(n))
    reg["id_registro"] = [f"C{i + 1:05d}" for i in range(n)]
    reg["arquivo_origem"] = bruto["arquivo_origem"]
    reg["linha_origem"] = bruto["linha_origem"]
    for nome in CATEGORICOS_CADASTRO:
        reg[nome] = unificar_categorias(bruto[nome].tolist())
    reg["nome"] = [limpar_texto(v) for v in bruto["nome"]]
    reg["nome_chave"] = [chave_comparacao(v) for v in reg["nome"]]
    reg["telefone"] = [limpar_texto(v) for v in bruto["telefone"]]
    reg["id_compartilhado"] = [limpar_texto(v) for v in bruto["id_compartilhado"]]

    emails = [normalizar_email(v) for v in bruto["email"]]
    reg["email"] = [e for e, _ in emails]
    reg["email_status"] = [s for _, s in emails]
    ufs = [normalizar_uf(v) for v in bruto["uf"]]
    reg["uf"] = [u for u, _ in ufs]
    reg["uf_status"] = [s for _, s in ufs]
    ibge = [classificar_ibge(v, u if s == "valido" else None, municipios)
            for v, (u, s) in zip(bruto["cod_ibge"], ufs)]
    reg["cod_ibge"] = [c for c, _ in ibge]
    reg["cod_ibge_status"] = [s for _, s in ibge]
    inep = [classificar_inep(v) for v in bruto["inep"]]
    reg["inep"] = [c for c, _ in inep]
    reg["inep_status"] = [s for _, s in inep]
    respostas = [interpretar_data(v) for v in bruto["data_resposta"]]
    reg["data_resposta"] = [d.isoformat() if d else None for d, _ in respostas]
    reg["data_resposta_status"] = [s for _, s in respostas]

    # CPF e nascimento: só em memória, para validação e duplicidade.
    cpfs = [validar_cpf(v) for v in bruto["cpf"]]
    nascimentos = [interpretar_data(v) for v in bruto["data_nascimento"]]
    reg["cpf_status"] = [s for _, s in cpfs]
    status_nasc = []
    for d, s in nascimentos:
        if s == "valida" and not (date(1900, 1, 1) <= d <= date(hoje.year - 14, hoje.month, min(hoje.day, 28))):
            s = "implausivel"
        status_nasc.append(s)
    reg["nascimento_status"] = status_nasc

    cpf_valido = [d if s.startswith("valido") else None for d, s in cpfs]
    reg["dup_cpf"] = grupos_de_duplicidade(cpf_valido, "CPF-")
    reg["dup_email"] = grupos_de_duplicidade(
        [e if s == "valido" else None for e, s in emails], "EML-")
    reg["dup_nome_nascimento"] = grupos_de_duplicidade(
        [f"{nc}|{d.isoformat()}" if nc and d else None
         for nc, (d, _) in zip(reg["nome_chave"], nascimentos)], "NOM-")
    assinatura = [
        "|".join(str(limpar_texto(v) or "").lower() for v in linha)
        for linha in bruto[[c.nome for c in CAMPOS_CADASTRO]].itertuples(index=False, name=None)
    ]
    reg["dup_linha"] = grupos_de_duplicidade(assinatura, "LIN-")

    # Identificador pseudônimo da pessoa: CPF válido > e-mail válido > nome + ente.
    tipos = []
    for cpf, (_, s_email) in zip(cpf_valido, emails):
        tipos.append("cpf" if cpf else "email" if s_email == "valido" else "nome")
    reg["tipo_chave"] = tipos
    reg["chave_pessoa"] = [
        pseudo.chave("cpf", cpf) if tipo == "cpf"
        else pseudo.chave("email", email) if tipo == "email"
        else pseudo.chave("nome", f"{nome_chave}|{chave_comparacao(ente)}")
        for tipo, cpf, (email, _), nome_chave, ente in zip(tipos, cpf_valido, emails, reg["nome_chave"], reg["ente"])
    ]

    v = {c: reg[c].tolist() for c in reg.columns}  # listas: acesso por índice muito mais rápido que .at
    problemas = []
    for i in range(n):
        p = []
        if eh_vazio(v["nome"][i]):
            p.append("nome_ausente")
        if v["email_status"][i] != "valido":
            p.append("email_ausente" if v["email_status"][i] == "ausente" else "email_invalido")
        s_cpf = v["cpf_status"][i]
        if s_cpf == "ausente":
            p.append("cpf_ausente")
        elif s_cpf == "invalido":
            p.append("cpf_invalido")
        elif s_cpf == "valido_recomposto":
            p.append("cpf_zeros_recompostos")
        if status_nasc[i] == "invalida":
            p.append("nascimento_invalido")
        elif status_nasc[i] == "implausivel":
            p.append("nascimento_implausivel")
        s_resp = v["data_resposta_status"][i]
        if s_resp == "invalida":
            p.append("data_resposta_invalida")
        elif s_resp == "valida" and respostas[i][0] > hoje:
            p.append("data_resposta_futura")
        uf, s_uf = ufs[i]
        if s_uf != "valido":
            p.append("uf_ausente" if s_uf == "ausente" else "uf_invalida")
        regiao = v["regiao"][i]
        if not eh_vazio(regiao) and s_uf == "valido" and chave_comparacao(regiao) != chave_comparacao(config.REGIAO_DA_SIGLA[uf]):
            p.append("regiao_divergente")
        if eh_vazio(v["ente"][i]):
            p.append("ente_ausente")
        s_ibge = v["cod_ibge_status"][i]
        if s_ibge != "valido":
            p.append({"ausente": "ibge_ausente", "invalido": "ibge_invalido",
                      "uf_divergente": "ibge_uf_divergente", "inexistente": "ibge_inexistente"}[s_ibge])
        s_inep = v["inep_status"][i]
        if s_inep != "valido":
            p.append("inep_ausente" if s_inep == "ausente" else "inep_invalido")
        elif s_uf == "valido" and sigla_uf_do_codigo(v["inep"][i]) != uf:
            p.append("inep_uf_divergente")
        if eh_vazio(v["escola"][i]):
            p.append("escola_ausente")
        if eh_vazio(v["situacao"][i]):
            p.append("situacao_ausente")
        for coluna, codigo in (("dup_cpf", "duplicado_cpf"), ("dup_email", "duplicado_email"),
                               ("dup_nome_nascimento", "duplicado_nome_nascimento"), ("dup_linha", "linha_repetida")):
            if not eh_vazio(v[coluna][i]):
                p.append(codigo)
        problemas.append(p)
    reg["problemas"] = problemas
    reg = reg[COLUNAS["cadastro"]]

    tabela = tabela_problemas(reg, "id_registro", _cabecalhos_por_campo(mapas))
    resumo = resumo_problemas(tabela, n, "id_registro")
    resumo.update({
        "n_pessoas": int(reg["chave_pessoa"].nunique()),
        "chave_pessoa": {k: int(v) for k, v in pd.Series(tipos).value_counts().items()},
        "email_valido": int((reg["email_status"] == "valido").sum()),
        "inep_valido": int((reg["inep_status"] == "valido").sum()),
        "ibge_valido": int((reg["cod_ibge_status"] == "valido").sum()),
    })
    exige = []
    if n and (n - resumo["email_valido"]) / n > LIMITE_EMAILS_INVALIDOS:
        exige.append(
            f"Mais da metade dos registros ({n - resumo['email_valido']} de {n}) está sem e-mail válido; "
            "a conciliação com a plataforma ficará muito limitada."
        )
    return Previa("cadastro", reg, tabela, bloqueios, avisos, resumo,
                  [t.metadados() for t in tabelas], _mapeamentos_texto(mapas), exige_confirmacao=exige)


# ---------------------------------------------------------------- atividade


def descrever_referencia(referencia_em: datetime | None, fuso: str) -> str:
    if referencia_em is None:
        return ("Momento da exportação não informado: tempos relativos contados a partir da "
                "exportação, sem data absoluta.")
    local = referencia_em.astimezone(ZoneInfo(fuso))
    return f"Exportação de {local:%d/%m/%Y %H:%M} ({fuso}), informada na importação."


def preparar_atividade(
    tabelas: list[TabelaBruta],
    pseudo: Pseudonimizador,
    referencia_em: datetime | None,
    fuso: str,
    papeis_cursista: list[str],
    manual: dict[str, dict[str, str]] | None = None,
    agora: datetime | None = None,
) -> Previa:
    agora = agora or datetime.now(timezone.utc)
    if referencia_em is not None and referencia_em.tzinfo is None:
        referencia_em = referencia_em.replace(tzinfo=ZoneInfo(fuso))
    mapas = {
        t.arquivo: mapear_colunas(t.cabecalhos, CAMPOS_ATIVIDADE, (manual or {}).get(t.arquivo))
        for t in tabelas
    }
    bloqueios, avisos = verificar_estrutura(
        mapas, sum(len(t.dados) for t in tabelas),
        requisitos_alternativos=[("nome_completo", "nome")], campos=CAMPOS_ATIVIDADE,
    )
    for t in tabelas:
        avisos.extend(f"“{t.arquivo}”: {a}" for a in t.avisos)
    if bloqueios:
        return _previa_bloqueada("atividade", tabelas, mapas, bloqueios, avisos)

    bruto = pd.concat([_aplicar_mapeamento(t, mapas[t.arquivo], CAMPOS_ATIVIDADE) for t in tabelas],
                      ignore_index=True)
    n = len(bruto)
    reg = pd.DataFrame(index=range(n))
    reg["id_conta"] = [f"A{i + 1:05d}" for i in range(n)]
    reg["arquivo_origem"] = bruto["arquivo_origem"]
    reg["linha_origem"] = bruto["linha_origem"]
    nomes = []
    for completo, nome, sobrenome in zip(bruto["nome_completo"], bruto["nome"], bruto["sobrenome"]):
        texto = limpar_texto(completo) or " ".join(p for p in (limpar_texto(nome), limpar_texto(sobrenome)) if p)
        nomes.append(texto or None)
    reg["nome_completo"] = nomes
    reg["nome_chave"] = [chave_comparacao(v) for v in nomes]
    emails = [normalizar_email(v) for v in bruto["email"]]
    reg["email"] = [e for e, _ in emails]
    reg["email_status"] = [s for _, s in emails]
    reg["papeis"] = [limpar_texto(v) for v in bruto["papeis"]]
    reg["grupos"] = [None if chave_comparacao(v) in SEM_GRUPO else limpar_texto(v) for v in bruto["grupos"]]
    reg["situacao_conta"] = unificar_categorias(bruto["situacao_conta"].tolist())
    reg["id_compartilhado"] = [limpar_texto(v) for v in bruto["id_compartilhado"]]
    reg["ultimo_acesso_texto"] = [limpar_texto(v) if not isinstance(v, datetime) else v.isoformat()
                                  for v in bruto["ultimo_acesso"]]

    chaves_cursista = {chave_comparacao(p) for p in papeis_cursista}
    cursista, equipe = [], []
    for papeis in reg["papeis"]:
        lista = [chave_comparacao(p) for p in (papeis if isinstance(papeis, str) else "").split(",") if p.strip()]
        eh = any(p in chaves_cursista for p in lista)
        cursista.append(int(eh))
        equipe.append(int(bool(lista) and not eh))
    reg["eh_cursista"] = cursista
    reg["eh_equipe"] = equipe

    tipos, segundos, momentos, bases, posteriores = [], [], [], [], []
    for valor in bruto["ultimo_acesso"]:
        acesso = interpretar_ultimo_acesso(valor, fuso)
        tipos.append(acesso.tipo)
        posterior = False
        if acesso.tipo == "relativo":
            segundos.append(acesso.duracao_s)
            momentos.append((referencia_em - pd.Timedelta(seconds=acesso.duracao_s)).astimezone(timezone.utc).isoformat()
                            if referencia_em else None)
            bases.append("relativo_exportacao")
        elif acesso.tipo == "absoluto":
            base = referencia_em or agora
            delta = (base - acesso.momento).total_seconds()
            if delta < 0:
                posterior, delta = True, 0.0
            segundos.append(delta)
            momentos.append(acesso.momento.isoformat())
            bases.append("referencia_informada" if referencia_em else "data_importacao")
        else:
            segundos.append(None)
            momentos.append(None)
            bases.append(None)
        posteriores.append(posterior)
    reg["acesso_tipo"] = tipos
    reg["acesso_segundos"] = segundos
    reg["acesso_momento"] = momentos
    reg["acesso_base"] = bases
    reg["dup_email"] = grupos_de_duplicidade([e if s == "valido" else None for e, s in emails], "EML-")
    reg["chave_conta"] = [
        pseudo.chave("email", e) if s == "valido" else pseudo.chave("conta", f"{nc}|{ln}")
        for (e, s), nc, ln in zip(emails, reg["nome_chave"], reg["linha_origem"])
    ]

    v = {c: reg[c].tolist() for c in reg.columns}  # listas: acesso por índice muito mais rápido que .at
    problemas = []
    for i in range(n):
        p = []
        if eh_vazio(v["nome_completo"][i]):
            p.append("conta_sem_nome")
        s_email = v["email_status"][i]
        if s_email != "valido":
            p.append("conta_email_ausente" if s_email == "ausente" else "conta_email_invalido")
        if not eh_vazio(v["dup_email"][i]):
            p.append("conta_email_duplicado")
        if tipos[i] == "vazio":
            p.append("acesso_vazio")
        elif tipos[i] == "nao_interpretado":
            p.append("acesso_nao_interpretado")
        if posteriores[i]:
            p.append("acesso_posterior_referencia")
        if eh_vazio(v["situacao_conta"][i]):
            p.append("situacao_conta_ausente")
        if eh_vazio(v["papeis"][i]):
            p.append("sem_papel")
        grupos = v["grupos"][i]
        if eh_vazio(grupos):
            p.append("sem_grupo")
        elif "," in grupos:
            p.append("multiplos_grupos")
        problemas.append(p)
    reg["problemas"] = problemas
    reg = reg[COLUNAS["atividade"]]

    tabela = tabela_problemas(reg, "id_conta", _cabecalhos_por_campo(mapas))
    resumo = resumo_problemas(tabela, n, "id_conta")
    resumo.update({
        "contas_cursista": int(sum(cursista)),
        "contas_equipe": int(sum(equipe)),
        "acesso_por_tipo": {k: int(v) for k, v in pd.Series(tipos).value_counts().items()},
        "email_valido": int((reg["email_status"] == "valido").sum()),
    })
    if referencia_em is None and "absoluto" in tipos:
        avisos.append("Há datas de acesso absolutas e o momento da exportação não foi informado: "
                      "para elas, o tempo sem acesso é contado até a data desta importação.")
    if referencia_em is None and "relativo" in tipos:
        avisos.append("Os tempos de acesso são relativos (ex.: “3 dias 2 horas”) e o momento da exportação "
                      "não foi informado: o painel mostrará o tempo sem acesso no momento da exportação, "
                      "sem converter em datas.")
    return Previa(
        "atividade", reg, tabela, bloqueios, avisos, resumo,
        [t.metadados() for t in tabelas], _mapeamentos_texto(mapas),
        referencia_em=referencia_em.astimezone(timezone.utc).isoformat() if referencia_em else None,
        referencia_descricao=descrever_referencia(referencia_em, fuso),
        importado_em=agora.isoformat(timespec="seconds"),
    )


# ---------------------------------------------------------------- comparação e confirmação

_CAMPOS_COMPARACAO = {
    "cadastro": ("chave_pessoa", ["situacao", "email", "inep", "escola", "ente", "uf", "ciclo", "cargo_funcao", "origem"]),
    "atividade": ("chave_conta", ["situacao_conta", "grupos", "papeis"]),
    "escolas": ("co_entidade", ["no_entidade", "dependencia", "situacao_funcionamento", "localizacao"]),
}
ROTULOS_CAMPOS = {
    "situacao": "Situação cadastral", "email": "E-mail", "inep": "Código INEP", "escola": "Escola",
    "ente": "Ente", "uf": "UF", "ciclo": "Ciclo", "cargo_funcao": "Cargo/Função", "origem": "Origem",
    "situacao_conta": "Situação da conta", "grupos": "Grupos", "papeis": "Papéis",
    "no_entidade": "Nome da escola", "dependencia": "Dependência administrativa",
    "situacao_funcionamento": "Situação de funcionamento", "localizacao": "Localização",
}


def comparar_importacoes(fonte: str, novos: pd.DataFrame, anteriores: pd.DataFrame | None,
                         mapa_novo: dict | None = None, mapa_anterior: dict | None = None) -> dict:
    """Diferenças entre a prévia e o retrato ativo, contadas pela chave estável da fonte."""
    if anteriores is None or anteriores.empty:
        return {"ha_anterior": False}
    chave, campos = _CAMPOS_COMPARACAO[fonte]
    a = anteriores.dropna(subset=[chave]).drop_duplicates(chave).set_index(chave)
    b = novos.dropna(subset=[chave]).drop_duplicates(chave).set_index(chave)
    comuns = a.index.intersection(b.index)
    mudancas = {}
    for campo in campos:
        va = a.loc[comuns, campo].fillna("")
        vb = b.loc[comuns, campo].fillna("")
        mudancas[ROTULOS_CAMPOS.get(campo, campo)] = int((va != vb).sum())
    resultado = {
        "ha_anterior": True,
        "registros_antes": int(len(anteriores)),
        "registros_depois": int(len(novos)),
        "entraram": int(len(b.index.difference(a.index))),
        "sairam": int(len(a.index.difference(b.index))),
        "permaneceram": int(len(comuns)),
        "alteracoes_por_campo": mudancas,
    }
    if fonte == "atividade":
        antes_nunca = a.loc[comuns, "acesso_tipo"] == "nunca"
        depois_nunca = b.loc[comuns, "acesso_tipo"] == "nunca"
        resultado["passaram_a_registrar_acesso"] = int((antes_nunca & ~depois_nunca).sum())
    if mapa_novo is not None and mapa_anterior is not None:
        col_novas = {c for m in mapa_novo.values() for c in m}
        col_antigas = {c for m in mapa_anterior.values() for c in m}
        resultado["colunas_novas"] = sorted(col_novas - col_antigas)
        resultado["colunas_ausentes"] = sorted(col_antigas - col_novas)
    return resultado


def comparar_com_ativa(repo: Repositorio, previa: Previa) -> dict:
    ativa = repo.importacao_ativa(previa.fonte)
    if ativa is None:
        return {"ha_anterior": False}
    anteriores = repo.registros(previa.fonte, ativa["id"])
    return comparar_importacoes(previa.fonte, previa.registros, anteriores,
                                previa.mapeamentos, ativa.get("mapeamento") or {})


def confirmar(repo: Repositorio, previa: Previa, usuario: str) -> int:
    if not previa.pode_confirmar:
        raise ValueError("A prévia tem bloqueios e não pode ser confirmada.")
    return repo.registrar_importacao(previa.fonte, previa.registros, previa.metadados(), usuario)
