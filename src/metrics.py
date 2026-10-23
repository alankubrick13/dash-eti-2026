"""Indicadores do painel: definição documentada + cálculo sobre os dados carregados.

Unidades nunca se misturam: "pessoas" são identificadores pseudônimos distintos
do cadastro; "registros" são linhas de inscrição; "contas" são contas da
plataforma; "escolas" são códigos INEP distintos.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from . import reconciliation as rc
from . import school_data
from .painel import (GRUPO_NUNCA, MOTIVO_CONCILIACAO, grupo_inativos, grupo_recentes, ordem_natural,
                     pessoas_de, resumo_turmas)


@dataclass(frozen=True)
class Indicador:
    id: str
    nome: str
    unidade: str
    definicao: str
    formula: str
    fonte: str
    ausentes: str
    limitacoes: str
    percentual: bool = False


@dataclass
class Resultado:
    indicador: Indicador
    valor: float | int | None
    numerador: int | None = None
    denominador: int | None = None
    disponivel: bool = True
    motivo: str | None = None
    contexto: str | None = None


_FONTE_CAD = "Planilha cadastral dos cursistas (importação ativa)."
_FONTE_ATV = "Exportação de participantes da plataforma de formação (importação ativa), conciliada com o cadastro."
_FONTE_ESC = "Base escolar oficial do Inep carregada (ver ano de referência), cruzada pelo código INEP."

INDICADORES: dict[str, Indicador] = {i.id: i for i in (
    Indicador("pessoas_cadastradas", "Pessoas cadastradas", "pessoas",
              "Pessoas distintas no cadastro. Duas linhas com o mesmo CPF (ou, sem CPF válido, o mesmo "
              "e-mail) contam como uma pessoa.",
              "contagem de identificadores pseudônimos distintos", _FONTE_CAD,
              "Registros sem CPF nem e-mail válidos são identificados por nome + ente.",
              "Pessoas cadastradas com CPFs diferentes (erro de digitação) contam em dobro até a correção."),
    Indicador("registros_inscricao", "Registros de inscrição", "registros",
              "Linhas de inscrição no cadastro, incluindo duplicidades.", "contagem de linhas", _FONTE_CAD,
              "Todas as linhas são contadas, com ou sem problemas de preenchimento.",
              "Não equivale ao número de pessoas."),
    Indicador("entes_representados", "Entes representados", "entes",
              "Entes federados (municípios ou estados) com ao menos uma pessoa cadastrada.",
              "códigos IBGE distintos; sem código válido, nomes de ente distintos", _FONTE_CAD,
              "Registros sem código IBGE e sem nome de ente não são contados.",
              "Grafias diferentes do mesmo ente sem código IBGE podem ser contadas em separado."),
    Indicador("escolas_identificadas", "Escolas identificadas", "escolas",
              "Escolas distintas informadas no cadastro com código INEP de formato válido.",
              "códigos INEP válidos distintos", _FONTE_CAD,
              "Registros com código ausente ou inválido não entram.",
              "Formato válido não garante que a escola exista; ver “Escolas localizadas”."),
    Indicador("escolas_localizadas", "Escolas localizadas na base oficial", "escolas",
              "Escolas do cadastro cujo código INEP foi encontrado na base escolar carregada.",
              "códigos INEP válidos distintos presentes na base escolar", _FONTE_ESC,
              "Indisponível enquanto não houver base escolar carregada.",
              "A base escolar se refere ao ano do Censo indicado, não ao momento atual."),
    Indicador("pct_inep_valido", "Registros com código INEP válido", "registros",
              "Proporção dos registros de inscrição com código INEP de formato válido (8 dígitos, "
              "iniciando por código de UF).",
              "registros com INEP válido ÷ registros de inscrição", _FONTE_CAD,
              "Código ausente conta no denominador e não no numerador.",
              "Não verifica a existência da escola.", percentual=True),
    Indicador("pct_contas_encontradas", "Pessoas com conta encontrada", "pessoas",
              "Proporção das pessoas cadastradas que têm conta na plataforma associada pela conciliação "
              "(e-mail inequívoco, identificador compartilhado ou associação manual).",
              "pessoas com conta associada ÷ pessoas cadastradas", _FONTE_ATV,
              "Casos pendentes ou ambíguos ficam fora do numerador até a revisão manual.",
              "Uma pessoa pode ter conta com outro e-mail ainda não conciliada.", percentual=True),
    Indicador("pct_ja_acessaram", "Já acessaram o curso", "pessoas",
              "Entre as pessoas com conta encontrada, proporção das que têm algum acesso ao curso registrado "
              "na exportação da plataforma.",
              "pessoas com último acesso informado ÷ pessoas com conta encontrada", _FONTE_ATV,
              "“Nunca acessou” e acesso não interpretado contam no denominador e não no numerador.",
              "Um único acesso basta para entrar no numerador; não informa frequência nem conclusão de atividades.",
              percentual=True),
    Indicador("pct_contas_ativas", "Contas com situação ativa", "pessoas",
              "Entre as pessoas com conta encontrada, proporção cuja conta está em situação considerada "
              "ativa (parâmetro configurável).",
              "pessoas com conta ativa ÷ pessoas com conta encontrada", _FONTE_ATV,
              "Situação em branco conta como não ativa.",
              "Conta ativa não significa uso efetivo da plataforma.", percentual=True),
    Indicador("pct_acesso_recente", "Pessoas com acesso recente", "pessoas",
              "Entre as pessoas com conta encontrada, proporção com último acesso dentro da janela de "
              "acesso recente (padrão: 7 dias), medida na data de referência da base de atividade.",
              "pessoas com acesso ≤ N dias ÷ pessoas com conta encontrada", _FONTE_ATV,
              "“Nunca acessou” e acesso não interpretado contam no denominador e não no numerador.",
              "Mede apenas o último acesso ao curso; não informa frequência, conclusão de atividades "
              "nem aprendizagem.", percentual=True),
    Indicador("pessoas_acompanhamento", "Requerem acompanhamento", "pessoas",
              "Pessoas com ao menos um destes critérios: sem conta localizada, conta não ativa, sem "
              "registro de acesso ou inatividade acima do limite configurado.",
              "contagem de pessoas com ao menos um critério", _FONTE_ATV,
              "Pessoas com conciliação pendente não entram até a revisão.",
              "Critério operacional configurável; não é classificação de evasão, abandono ou desistência."),
    Indicador("registros_pendentes", "Registros pendentes de conciliação", "registros",
              "Registros de inscrição com sugestão de associação pendente ou ambígua, aguardando "
              "decisão manual.", "contagem de registros pendentes ou ambíguos", _FONTE_ATV,
              "—", "Depende das regras de conciliação descritas na página de qualidade."),
    Indicador("contas_cursista", "Contas de cursistas na plataforma", "contas",
              "Contas da exportação com papel considerado de cursista (parâmetro configurável).",
              "contagem de contas com papel de cursista", _FONTE_ATV,
              "Contas sem papel não entram.", "Contas da equipe (formadores, suporte) ficam de fora."),
    Indicador("contas_sem_cadastro", "Contas de cursistas sem correspondência no cadastro", "contas",
              "Contas com papel de cursista que não foram associadas a nenhum registro do cadastro.",
              "contagem de contas de cursista sem correspondência", _FONTE_ATV,
              "Contas pendentes ou ambíguas são contadas à parte.",
              "Pode indicar inscrição fora do cadastro ou e-mail diferente."),
)}


INDICADORES_CONTAS: dict[str, Indicador] = {i.id: i for i in (
    Indicador("contas_recorte", "Contas no recorte", "contas",
              "Contas da exportação da plataforma com os papéis selecionados, no recorte de filtros.",
              "contagem de contas", _FONTE_ATV, "—",
              "Filtros territoriais só alcançam contas associadas a um registro do cadastro."),
    Indicador("pct_situacao_ativa", "Situação ativa", "contas",
              "Proporção das contas cuja situação na plataforma é considerada ativa.",
              "contas ativas ÷ contas no recorte", _FONTE_ATV, "Situação em branco conta como não ativa.",
              "Situação da conta não é sinônimo de uso: uma conta ativa pode estar sem acesso.", percentual=True),
    Indicador("pct_com_acesso", "Com acesso registrado", "contas",
              "Proporção das contas que registram algum acesso ao curso.",
              "contas com último acesso informado ÷ contas no recorte", _FONTE_ATV,
              "“Nunca” e valores em branco ficam fora do numerador.",
              "Um único acesso basta para entrar no numerador.", percentual=True),
    Indicador("pct_acesso_recente_contas", "Com acesso recente", "contas",
              "Proporção das contas com último acesso dentro do janela de acesso recente configurada (padrão: 7 dias), na data de "
              "referência da base de atividade.",
              "contas com acesso ≤ N dias ÷ contas no recorte", _FONTE_ATV,
              "Acesso não interpretado conta no denominador e não no numerador.",
              "Não mede frequência nem conclusão de atividades.", percentual=True),
    Indicador("contas_nunca", "Sem registro de acesso", "contas",
              "Contas cujo último acesso ao curso aparece como “Nunca”.", "contagem de contas", _FONTE_ATV, "—",
              "Ausência de acesso não equivale a desistência: pode haver problema de cadastro, de e-mail ou de acesso."),
)}


def calcular_contas(contas: pd.DataFrame, limite_recente: int) -> dict[str, Resultado]:
    n = len(contas)
    i = INDICADORES_CONTAS
    if n == 0:
        return {k: Resultado(v, None, disponivel=False, motivo="Nenhuma conta no recorte.") for k, v in i.items()}
    com_acesso = contas["acesso_tipo"].isin(["relativo", "absoluto"])
    recentes = (contas["dias_sem_acesso"].fillna(10**9) <= limite_recente)
    return {
        "contas_recorte": Resultado(i["contas_recorte"], n, contexto="contas com os papéis selecionados"),
        "pct_situacao_ativa": Resultado(i["pct_situacao_ativa"], contas["conta_ativa"].mean(), int(contas["conta_ativa"].sum()), n),
        "pct_com_acesso": Resultado(i["pct_com_acesso"], com_acesso.mean(), int(com_acesso.sum()), n),
        "pct_acesso_recente_contas": Resultado(i["pct_acesso_recente_contas"], recentes.mean(), int(recentes.sum()), n),
        "contas_nunca": Resultado(i["contas_nunca"], int((contas["acesso_tipo"] == "nunca").sum()),
                                  contexto=f"de {numero(n)} contas no recorte"),
    }


def ajuda(indicador: Indicador) -> str:
    return (
        f"**Definição.** {indicador.definicao}\n\n**Fórmula.** {indicador.formula}\n\n"
        f"**Fonte.** {indicador.fonte}\n\n**Ausentes.** {indicador.ausentes}\n\n"
        f"**Limitações.** {indicador.limitacoes}"
    )


def _razao(indicador_id: str, numerador: int, denominador: int) -> Resultado:
    ind = INDICADORES[indicador_id]
    if not denominador:
        return Resultado(ind, None, numerador, denominador, False, "Sem população de referência no recorte.")
    return Resultado(ind, numerador / denominador, numerador, denominador)


def _indisponivel(indicador_id: str, motivo: str) -> Resultado:
    return Resultado(INDICADORES[indicador_id], None, disponivel=False, motivo=motivo)


def calcular(cursistas: pd.DataFrame, contas: pd.DataFrame, base, parametros: dict) -> dict[str, Resultado]:
    r: dict[str, Resultado] = {}
    if cursistas.empty:
        motivo = "Nenhum registro no recorte." if base.tem_cadastro else "Planilha do cadastro não encontrada na pasta."
        return {i: _indisponivel(i, motivo) for i in INDICADORES}
    pessoas = pessoas_de(cursistas)
    n_pessoas = len(pessoas)
    r["pessoas_cadastradas"] = Resultado(INDICADORES["pessoas_cadastradas"], n_pessoas,
                                         contexto=f"a partir de {numero(len(cursistas))} registros de inscrição")
    r["registros_inscricao"] = Resultado(INDICADORES["registros_inscricao"], len(cursistas),
                                         contexto="linhas do cadastro, incluindo duplicidades")

    ente = cursistas["cod_ibge"].where(cursistas["cod_ibge_status"] == "valido")
    ente = ente.fillna(cursistas["ente"].map(lambda v: f"nome:{v.lower()}" if isinstance(v, str) else None))
    r["entes_representados"] = Resultado(INDICADORES["entes_representados"], int(ente.dropna().nunique()),
                                         contexto="municípios e estados com pessoas cadastradas")

    validos = cursistas.loc[cursistas["inep_status"] == "valido", "inep"]
    r["escolas_identificadas"] = Resultado(INDICADORES["escolas_identificadas"], int(validos.nunique()),
                                           contexto="códigos INEP válidos distintos")
    if base.tem_escolas:
        localizadas = cursistas.loc[cursistas["situacao_inep"] == school_data.SITUACAO_INEP_LOCALIZADO, "inep"]
        r["escolas_localizadas"] = Resultado(
            INDICADORES["escolas_localizadas"], int(localizadas.nunique()), int(localizadas.nunique()),
            int(validos.nunique()), contexto=f"de {numero(validos.nunique())} escolas identificadas")
    else:
        r["escolas_localizadas"] = _indisponivel("escolas_localizadas", "Base escolar não carregada.")
    r["pct_inep_valido"] = _razao("pct_inep_valido", int((cursistas["inep_status"] == "valido").sum()), len(cursistas))

    if not base.tem_atividade:
        for i in ("pct_contas_encontradas", "pct_ja_acessaram", "pct_contas_ativas", "pct_acesso_recente", "pessoas_acompanhamento",
                  "registros_pendentes", "contas_cursista", "contas_sem_cadastro"):
            r[i] = _indisponivel(i, "Exportação da plataforma não encontrada na pasta.")
        return r

    com_conta = pessoas[pessoas["status_conciliacao"] == rc.CORRESPONDENTE]
    r["pct_contas_encontradas"] = _razao("pct_contas_encontradas", len(com_conta), n_pessoas)
    acessaram = int(com_conta["acesso_tipo"].isin(["relativo", "absoluto"]).sum())
    r["pct_ja_acessaram"] = _razao("pct_ja_acessaram", acessaram, len(com_conta))
    ativas = int(com_conta["conta_ativa"].fillna(False).astype(bool).sum())
    r["pct_contas_ativas"] = _razao("pct_contas_ativas", ativas, len(com_conta))
    limite = parametros["janela_acesso_recente_dias"]
    recentes = int((com_conta["dias_sem_acesso"].fillna(10**9) <= limite).sum())
    r["pct_acesso_recente"] = _razao("pct_acesso_recente", recentes, len(com_conta))
    n_acomp = int(pessoas["requer_acompanhamento"].sum())
    r["pessoas_acompanhamento"] = Resultado(
        INDICADORES["pessoas_acompanhamento"], n_acomp, n_acomp, n_pessoas,
        contexto=f"de {numero(n_pessoas)} pessoas ({percentual(n_acomp / n_pessoas if n_pessoas else None)})")
    pendentes = int(cursistas["status_conciliacao"].isin([rc.PENDENTE, rc.AMBIGUO]).sum())
    r["registros_pendentes"] = Resultado(INDICADORES["registros_pendentes"], pendentes, pendentes, len(cursistas),
                                         contexto="aguardando decisão de um coordenador")
    contas_cursista = contas[contas["eh_cursista"] == 1]
    r["contas_cursista"] = Resultado(INDICADORES["contas_cursista"], len(contas_cursista),
                                     contexto=f"de {numero(len(contas))} contas na exportação")
    r["contas_sem_cadastro"] = Resultado(
        INDICADORES["contas_sem_cadastro"],
        int((contas_cursista["status_conciliacao"] == rc.SEM_CORRESPONDENCIA).sum()),
        denominador=len(contas_cursista), contexto=f"de {numero(len(contas_cursista))} contas de cursistas",
    )
    return r


@dataclass
class Destaque:
    """Um fato do recorte, com o número principal e a população de referência na frase."""

    icone: str
    valor: str
    titulo: str
    texto: str
    acao: tuple | None = None  # ("pagina", caminho, grupo da galeria) ou ("turma", grupo)


def destaques(cursistas: pd.DataFrame, contas: pd.DataFrame, parametros: dict, minimo_turma: int = 10) -> list[Destaque]:
    """Os fatos que abrem a Visão geral, calculados no recorte; vazio sem cadastro ou sem atividade."""
    if cursistas.empty or contas.empty:
        return []
    pessoas = pessoas_de(cursistas)
    com_conta = pessoas[pessoas["status_conciliacao"] == rc.CORRESPONDENTE]
    n = len(com_conta)
    if not n:
        return []
    janela, limite = parametros["janela_acesso_recente_dias"], parametros["limite_acompanhamento_dias"]
    acessaram = int(com_conta["acesso_tipo"].isin(["relativo", "absoluto"]).sum())
    recentes = int((com_conta["dias_sem_acesso"].fillna(10**9) <= janela).sum())
    nunca = int((com_conta["acesso_tipo"] == "nunca").sum())
    inativos = int((com_conta["dias_sem_acesso"].fillna(-1) > limite).sum())
    itens = [
        Destaque("how_to_reg", percentual(acessaram / n), "já acessaram o curso",
                 f"{numero(acessaram)} de {numero(n)} pessoas com conta na plataforma",
                 ("pagina", "paginas/3_atividade.py", None)),
        Destaque("schedule", numero(recentes), f"acessaram nos últimos {janela} dias",
                 f"{percentual(recentes / n)} das pessoas com conta",
                 ("pagina", "paginas/2_cursistas.py", grupo_recentes(janela))),
        Destaque("person_off", numero(nunca), "nunca acessaram",
                 f"e {numero(inativos)} estão sem acesso há mais de {limite} dias",
                 ("pagina", "paginas/2_cursistas.py", GRUPO_NUNCA)),
    ]
    turmas = resumo_turmas(contas, janela, limite)
    turmas = turmas[turmas["estudantes"] >= minimo_turma]
    if not turmas.empty:
        # Empates são comuns (ex.: 20 de 30 em várias turmas): todas as empatadas são citadas
        menor = turmas["taxa_acesso"].min()
        piores = turmas[(turmas["taxa_acesso"] - menor).abs() < 1e-9].sort_values("rotulo", key=lambda r: r.map(ordem_natural))
        pares = set(zip(piores["acessaram"], piores["estudantes"]))
        contagem = f"{numero(piores['acessaram'].iloc[0])} de {numero(piores['estudantes'].iloc[0])}"
        if len(piores) == 1:
            texto = f"{piores['rotulo'].iloc[0]}: {contagem} estudantes já entraram"
            acao = ("turma", piores["grupo"].iloc[0])
        else:
            nomes = list(piores["rotulo"])
            lista = ", ".join(nomes[:-1]) + " e " + nomes[-1]
            texto = f"{len(nomes)} turmas empatadas{f' ({contagem} em cada)' if len(pares) == 1 else ''}: {lista}"
            acao = ("pagina", "paginas/3_atividade.py", None)
        itens.append(Destaque("groups", percentual(menor, 0), "é a menor taxa de acesso entre as turmas", texto, acao))
    if inativos and len(itens) < 4:
        itens.append(Destaque("hourglass_bottom", numero(inativos), f"sem acesso há mais de {limite} dias",
                              f"{percentual(inativos / n)} das pessoas com conta",
                              ("pagina", "paginas/2_cursistas.py", grupo_inativos(limite))))
    return itens


def contagem_motivos(cursistas: pd.DataFrame) -> pd.DataFrame:
    """Pessoas por motivo de acompanhamento (uma pessoa pode ter mais de um motivo)."""
    pessoas = pessoas_de(cursistas)
    linhas = [m for motivos in pessoas["motivos"] for m in motivos if m != MOTIVO_CONCILIACAO]
    if not linhas:
        return pd.DataFrame(columns=["motivo", "pessoas"])
    return pd.Series(linhas).value_counts().rename_axis("motivo").reset_index(name="pessoas")


# ---------------------------------------------------------------- formatação pt-BR


def numero(valor) -> str:
    if valor is None or (isinstance(valor, float) and valor != valor):
        return "—"
    return f"{int(round(valor)):,}".replace(",", ".")


def percentual(valor, casas: int = 1) -> str:
    if valor is None or (isinstance(valor, float) and valor != valor):
        return "—"
    return f"{valor * 100:.{casas}f}%".replace(".", ",")


def valor_formatado(resultado: Resultado) -> str:
    if not resultado.disponivel or resultado.valor is None:
        return "—"
    return percentual(resultado.valor) if resultado.indicador.percentual else numero(resultado.valor)


def contexto_formatado(resultado: Resultado) -> str:
    """Linha de apoio: numerador e denominador, sempre com a população de referência."""
    ind = resultado.indicador
    if not resultado.disponivel:
        return resultado.motivo or "Indisponível."
    if resultado.contexto:
        return resultado.contexto
    if ind.percentual:
        return f"{numero(resultado.numerador)} de {numero(resultado.denominador)} {ind.unidade}"
    if resultado.denominador:
        return f"de {numero(resultado.denominador)} {ind.unidade} no recorte"
    return ind.unidade.capitalize()


# ---------------------------------------------------------------- escolas

_FONTE_ESC_CAD = "Cadastro dos cursistas cruzado, pelo código INEP, com a base escolar oficial do Inep."
INDICADORES_ESCOLAS: dict[str, Indicador] = {i.id: i for i in (
    Indicador("escolas_com_cursistas", "Escolas com cursistas", "escolas",
              "Escolas distintas informadas no cadastro: por código INEP válido ou, sem ele, pelo nome informado.",
              "contagem de escolas distintas", _FONTE_CAD,
              "Escolas sem código válido contam pelo nome + UF.",
              "Grafias diferentes da mesma escola sem código INEP podem ser contadas em separado."),
    Indicador("escolas_tempo_integral", "Com matrícula em tempo integral", "escolas",
              "Escolas localizadas na base oficial com ao menos uma matrícula em tempo integral declarada ao Censo "
              "(Educação Infantil, Ensino Fundamental ou Médio).",
              "escolas com QT_MAT_INF_INT + QT_MAT_FUND_INT + QT_MAT_MED_INT > 0", _FONTE_ESC_CAD,
              "Escolas não localizadas na base ficam fora do numerador e do denominador.",
              "Dado do ano do Censo indicado. Participar da formação não implica ofertar tempo integral."),
    Indicador("escolas_sem_acesso", "Escolas em que ninguém acessou", "escolas",
              "Escolas cujos cursistas com conta na plataforma nunca acessaram o curso.",
              "escolas com cursistas com conta e nenhum acesso registrado", _FONTE_ATV,
              "Escolas sem nenhum cursista com conta encontrada ficam fora.",
              "Critério operacional para priorizar contato; não indica desistência."),
)}


def calcular_escolas(escolas: pd.DataFrame, atributos: pd.DataFrame, tem_atividade: bool) -> dict[str, Resultado]:
    i = INDICADORES_ESCOLAS
    r = {"escolas_com_cursistas": Resultado(i["escolas_com_cursistas"], len(escolas),
                                            contexto=f"{numero(escolas['inep'].notna().sum())} com código INEP válido")}
    localizadas = escolas[escolas["situacao_inep"] == school_data.SITUACAO_INEP_LOCALIZADO]
    variaveis = [v for v in school_data.VARIAVEIS_INT_TOTAL if not atributos.empty and v in atributos]
    if localizadas.empty or not variaveis:
        r["escolas_tempo_integral"] = Resultado(i["escolas_tempo_integral"], None, disponivel=False,
                                                motivo="Base escolar oficial não carregada ou sem essas variáveis.")
    else:
        dados = atributos[atributos["co_entidade"].isin(localizadas["inep"])]
        com_integral = int((dados[variaveis].apply(pd.to_numeric, errors="coerce").fillna(0).sum(axis=1) > 0).sum())
        r["escolas_tempo_integral"] = Resultado(i["escolas_tempo_integral"], com_integral, com_integral, len(dados),
                                                contexto=f"de {numero(len(dados))} escolas localizadas na base oficial")
    if not tem_atividade:
        r["escolas_sem_acesso"] = Resultado(i["escolas_sem_acesso"], None, disponivel=False,
                                            motivo="Exportação da plataforma não encontrada na pasta.")
    else:
        avaliaveis = escolas[escolas["com_conta"] > 0]
        nenhum = int((avaliaveis["acessaram"] == 0).sum())
        r["escolas_sem_acesso"] = Resultado(i["escolas_sem_acesso"], nenhum, nenhum, len(avaliaveis),
                                            contexto=f"de {numero(len(avaliaveis))} escolas com cursistas com conta")
    return r
