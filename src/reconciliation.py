"""Conciliação entre o cadastro de cursistas e as contas da plataforma.

Ordem de prioridade (explícita e auditável):
1. decisões manuais registradas por coordenadores (associar / rejeitar par);
2. e-mail normalizado, quando inequívoco (uma conta e uma pessoa);
3. identificador estável compartilhado pelas duas fontes, se existir;
4. nome completo apenas como SUGESTÃO: nunca associa sozinho.

A conciliação é recalculada a cada carga a partir dos retratos ativos; as
planilhas originais nunca são alteradas.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher

import pandas as pd

CORRESPONDENTE = "Correspondente"
PENDENTE = "Pendente"
AMBIGUO = "Ambíguo"
SEM_CORRESPONDENCIA = "Sem correspondência"
STATUS_ORDEM = (CORRESPONDENTE, PENDENTE, AMBIGUO, SEM_CORRESPONDENCIA)

REGRA_MANUAL = "Associação manual"
REGRA_EMAIL = "E-mail normalizado"
REGRA_ID = "Identificador compartilhado"
REGRA_MESMA_PESSOA = "Mesma pessoa (CPF ou e-mail) de registro já associado"

MOTIVO_EMAIL_MULTIPLAS_CONTAS = "E-mail associado a mais de uma conta"
MOTIVO_EMAIL_PESSOAS_DIFERENTES = "Mesmo e-mail em cadastros de pessoas diferentes"
MOTIVO_NOME_EMAIL_DIFERENTE = "Nome idêntico, e-mails diferentes (possível mudança de e-mail)"
MOTIVO_NOME_SEM_EMAIL = "Nome idêntico; cadastro sem e-mail válido"
MOTIVO_NOME_HOMONIMOS = "Nome idêntico a mais de uma conta ou pessoa (homônimos)"
MOTIVO_NOME_SEMELHANTE = "Nome semelhante"
MOTIVO_ID_AMBIGUO = "Identificador compartilhado repetido"

SIMILARIDADE_MINIMA = 0.92


@dataclass
class ResultadoConciliacao:
    associacoes: pd.DataFrame  # id_registro, id_conta, regra, observacao
    candidatos: pd.DataFrame  # id_registro, id_conta, situacao, motivo, similaridade
    status_registros: pd.DataFrame  # id_registro, status_conciliacao, regra, id_conta
    status_contas: pd.DataFrame  # id_conta, status_conciliacao, n_pessoas
    decisoes_sem_efeito: int = 0
    alertas: list[str] = field(default_factory=list)


def _agrupar(df: pd.DataFrame, chave: str, valor: str) -> dict:
    grupos: dict = defaultdict(list)
    for k, v in zip(df[chave], df[valor]):
        if isinstance(k, str) and k:
            grupos[k].append(v)
    return grupos


def _blocos(nome_chave: str) -> tuple[str, ...]:
    """Chaves de bloqueio: primeiro nome e último sobrenome (pega variações em um dos dois)."""
    partes = nome_chave.split()
    return (f"p:{partes[0]}", f"u:{partes[-1]}") if partes else ()


def conciliar(
    cadastro: pd.DataFrame,
    atividade: pd.DataFrame,
    decisoes: pd.DataFrame | None = None,
) -> ResultadoConciliacao:
    cad = cadastro[["id_registro", "chave_pessoa", "email", "email_status", "nome_chave", "id_compartilhado"]]
    atv = atividade[["id_conta", "chave_conta", "email", "email_status", "nome_chave", "eh_equipe", "id_compartilhado"]]
    pessoa_de = dict(zip(cad["id_registro"], cad["chave_pessoa"]))
    chave_conta_de = dict(zip(atv["id_conta"], atv["chave_conta"]))
    email_reg = dict(zip(cad["id_registro"], cad["email"]))
    status_email_reg = dict(zip(cad["id_registro"], cad["email_status"]))
    email_conta = dict(zip(atv["id_conta"], atv["email"]))

    rejeitados: set[tuple[str, str]] = set()
    manuais: list[tuple[str, str]] = []
    if decisoes is not None and not decisoes.empty:
        for d in decisoes.itertuples(index=False):
            par = (d.chave_pessoa, d.chave_conta)
            if d.decisao == "associar":
                manuais.append(par)
            else:
                rejeitados.add(par)

    associacoes: list[dict] = []
    candidatos: list[dict] = []
    reg_assoc: dict[str, str] = {}
    contas_assoc: dict[str, set[str]] = defaultdict(set)

    def associar(id_registro: str, id_conta: str, regra: str, observacao: str = "") -> None:
        associacoes.append({"id_registro": id_registro, "id_conta": id_conta, "regra": regra, "observacao": observacao})
        reg_assoc[id_registro] = id_conta
        contas_assoc[id_conta].add(pessoa_de[id_registro])

    def candidatar(id_registro: str, id_conta: str, situacao: str, motivo: str, similaridade=None) -> None:
        if (pessoa_de[id_registro], chave_conta_de[id_conta]) in rejeitados:
            return
        candidatos.append({"id_registro": id_registro, "id_conta": id_conta, "situacao": situacao,
                           "motivo": motivo, "similaridade": similaridade})

    # 1. decisões manuais
    regs_por_pessoa = _agrupar(cad, "chave_pessoa", "id_registro")
    contas_por_chave = _agrupar(atv, "chave_conta", "id_conta")
    sem_efeito = 0
    for chave_pessoa, chave_conta in manuais:
        regs, contas = regs_por_pessoa.get(chave_pessoa, []), contas_por_chave.get(chave_conta, [])
        if not regs or not contas:
            sem_efeito += 1
            continue
        for r in regs:
            if r not in reg_assoc:
                associar(r, contas[0], REGRA_MANUAL)

    # 2. e-mail normalizado
    livres_cad = cad[(cad["email_status"] == "valido") & ~cad["id_registro"].isin(reg_assoc.keys())]
    livres_atv = atv[(atv["email_status"] == "valido") & ~atv["id_conta"].isin(contas_assoc.keys())]
    regs_por_email = _agrupar(livres_cad, "email", "id_registro")
    contas_por_email = _agrupar(livres_atv, "email", "id_conta")
    for email in regs_por_email.keys() & contas_por_email.keys():
        regs, contas = regs_por_email[email], contas_por_email[email]
        pessoas = {pessoa_de[r] for r in regs}
        if len(contas) == 1 and len(pessoas) == 1:
            if (pessoas.pop(), chave_conta_de[contas[0]]) in rejeitados:
                continue
            obs = "Registros duplicados da mesma pessoa" if len(regs) > 1 else ""
            for r in regs:
                associar(r, contas[0], REGRA_EMAIL, obs)
        else:
            motivo = MOTIVO_EMAIL_MULTIPLAS_CONTAS if len(contas) > 1 else MOTIVO_EMAIL_PESSOAS_DIFERENTES
            for r in regs:
                for c in contas:
                    candidatar(r, c, AMBIGUO, motivo)

    # 2b. outros registros da mesma pessoa (mesmo CPF ou e-mail) herdam a conta já associada
    conta_da_pessoa = {}
    for a in associacoes:
        conta_da_pessoa.setdefault(pessoa_de[a["id_registro"]], a["id_conta"])
    em_disputa = {c["id_registro"] for c in candidatos}
    for r in cad["id_registro"]:
        chave = pessoa_de[r] or ""
        conta = conta_da_pessoa.get(chave)
        # Só identificadores fortes (CPF ou e-mail); nome + ente não basta para herdar a conta.
        if conta and chave.startswith(("cpf:", "email:")) and r not in reg_assoc and r not in em_disputa:
            associar(r, conta, REGRA_MESMA_PESSOA)

    # 3. identificador compartilhado (só se as duas fontes tiverem a coluna preenchida)
    if cad["id_compartilhado"].notna().any() and atv["id_compartilhado"].notna().any():
        livres_cad = cad[~cad["id_registro"].isin(reg_assoc.keys()) & ~cad["id_registro"].isin(em_disputa)]
        livres_atv = atv[~atv["id_conta"].isin(contas_assoc.keys())]
        regs_por_id = _agrupar(livres_cad, "id_compartilhado", "id_registro")
        contas_por_id = _agrupar(livres_atv, "id_compartilhado", "id_conta")
        for ident in regs_por_id.keys() & contas_por_id.keys():
            regs, contas = regs_por_id[ident], contas_por_id[ident]
            if len(contas) == 1 and len({pessoa_de[r] for r in regs}) == 1:
                if (pessoa_de[regs[0]], chave_conta_de[contas[0]]) not in rejeitados:
                    for r in regs:
                        associar(r, contas[0], REGRA_ID)
            else:
                for r in regs:
                    for c in contas:
                        candidatar(r, c, AMBIGUO, MOTIVO_ID_AMBIGUO)

    # 4. nome: apenas sugestões para revisão manual
    em_disputa = {c["id_registro"] for c in candidatos}
    contas_em_disputa = {c["id_conta"] for c in candidatos}
    livres_cad = cad[~cad["id_registro"].isin(reg_assoc.keys()) & ~cad["id_registro"].isin(em_disputa)
                     & cad["nome_chave"].notna()]
    livres_atv = atv[~atv["id_conta"].isin(contas_assoc.keys()) & ~atv["id_conta"].isin(contas_em_disputa)
                     & atv["nome_chave"].notna() & (atv["eh_equipe"].fillna(0).astype(int) == 0)]
    contas_por_nome = _agrupar(livres_atv, "nome_chave", "id_conta")
    regs_por_nome = _agrupar(livres_cad, "nome_chave", "id_registro")
    sem_candidato_exato = []
    for nome, regs in regs_por_nome.items():
        contas = contas_por_nome.get(nome)
        if not contas:
            sem_candidato_exato.extend(regs)
            continue
        unico = len(contas) == 1 and len({pessoa_de[r] for r in regs}) == 1
        for r in regs:
            for c in contas:
                if not unico:
                    candidatar(r, c, AMBIGUO, MOTIVO_NOME_HOMONIMOS, 1.0)
                elif status_email_reg[r] == "valido" and email_reg[r] != email_conta[c]:
                    candidatar(r, c, PENDENTE, MOTIVO_NOME_EMAIL_DIFERENTE, 1.0)
                else:
                    candidatar(r, c, PENDENTE, MOTIVO_NOME_SEM_EMAIL, 1.0)

    # 4b. nome semelhante (mesmo primeiro nome ou mesmo último sobrenome), só sem candidato exato
    contas_com_exato = {c["id_conta"] for c in candidatos}
    blocos: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for id_conta, nome in zip(livres_atv["id_conta"], livres_atv["nome_chave"]):
        if id_conta not in contas_com_exato:
            for bloco in _blocos(nome):
                blocos[bloco].append((id_conta, nome))
    nome_reg = dict(zip(cad["id_registro"], cad["nome_chave"]))
    for r in sem_candidato_exato:
        comparadas = {conta for bloco in _blocos(nome_reg[r]) for conta in blocos.get(bloco, [])}
        achados = []
        for id_conta, nome_conta in sorted(comparadas):
            similaridade = SequenceMatcher(None, nome_reg[r], nome_conta).ratio()
            if similaridade >= SIMILARIDADE_MINIMA:
                achados.append((id_conta, similaridade))
        for id_conta, similaridade in achados:
            candidatar(r, id_conta, PENDENTE if len(achados) == 1 else AMBIGUO,
                       MOTIVO_NOME_SEMELHANTE, round(similaridade, 3))

    # Situação por registro e por conta
    df_assoc = pd.DataFrame(associacoes, columns=["id_registro", "id_conta", "regra", "observacao"])
    df_cand = pd.DataFrame(candidatos, columns=["id_registro", "id_conta", "situacao", "motivo", "similaridade"])
    situacao_reg = {}
    for r in cad["id_registro"]:
        if r in reg_assoc:
            situacao_reg[r] = CORRESPONDENTE
    for c in candidatos:
        atual = situacao_reg.get(c["id_registro"])
        if atual == CORRESPONDENTE:
            continue
        situacao_reg[c["id_registro"]] = AMBIGUO if AMBIGUO in (atual, c["situacao"]) else PENDENTE
    regra_reg = dict(zip(df_assoc["id_registro"], df_assoc["regra"]))
    status_registros = pd.DataFrame({
        "id_registro": cad["id_registro"],
        "status_conciliacao": [situacao_reg.get(r, SEM_CORRESPONDENCIA) for r in cad["id_registro"]],
        "regra_conciliacao": [regra_reg.get(r) for r in cad["id_registro"]],
        "id_conta": [reg_assoc.get(r) for r in cad["id_registro"]],
    })

    situacao_conta = {}
    for c in candidatos:
        atual = situacao_conta.get(c["id_conta"])
        situacao_conta[c["id_conta"]] = AMBIGUO if AMBIGUO in (atual, c["situacao"]) else PENDENTE
    status_contas = pd.DataFrame({
        "id_conta": atv["id_conta"],
        "status_conciliacao": [
            CORRESPONDENTE if c in contas_assoc else situacao_conta.get(c, SEM_CORRESPONDENCIA)
            for c in atv["id_conta"]
        ],
        "n_pessoas": [len(contas_assoc.get(c, ())) for c in atv["id_conta"]],
    })
    alertas = []
    multiplas = int((status_contas["n_pessoas"] > 1).sum())
    if multiplas:
        alertas.append(f"{multiplas} conta(s) associada(s) a mais de uma pessoa (revise as associações manuais).")
    if sem_efeito:
        alertas.append(f"{sem_efeito} decisão(ões) manual(is) referem-se a registros ausentes dos retratos atuais.")
    return ResultadoConciliacao(df_assoc, df_cand, status_registros, status_contas, sem_efeito, alertas)
