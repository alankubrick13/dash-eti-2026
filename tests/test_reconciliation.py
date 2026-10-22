"""Conciliação cadastro × plataforma com os dados reais: e-mail inequívoco associa; nome apenas sugere.

Os casos de ambiguidade são montados a partir de registros reais (um e-mail real repetido em outra
pessoa ou em outra conta).
"""

import pandas as pd
import pytest
from conftest import confere

from src import reconciliation as rc

REGRAS_SEM_NOME = {rc.REGRA_EMAIL, rc.REGRA_MANUAL, rc.REGRA_ID, rc.REGRA_MESMA_PESSOA}
MOTIVOS_POR_NOME = {rc.MOTIVO_NOME_EMAIL_DIFERENTE, rc.MOTIVO_NOME_SEM_EMAIL, rc.MOTIVO_NOME_HOMONIMOS,
                    rc.MOTIVO_NOME_SEMELHANTE}


@pytest.fixture(scope="module")
def dados(previa_cadastro, previa_atividade):
    cad, atv = previa_cadastro.registros, previa_atividade.registros
    return cad, atv, rc.conciliar(cad, atv)


def _status(resultado) -> dict:
    return dict(zip(resultado.status_registros["id_registro"], resultado.status_registros["status_conciliacao"]))


def test_associacoes_por_email_sao_inequivocas(dados):
    cad, atv, r = dados
    email_reg = dict(zip(cad["id_registro"], cad["email"]))
    email_conta = dict(zip(atv["id_conta"], atv["email"]))
    por_email = r.associacoes[r.associacoes["regra"] == rc.REGRA_EMAIL]
    confere(len(por_email) > 0, "nenhuma associação por e-mail nos dados reais")
    divergentes = sum(email_reg[a] != email_conta[b] for a, b in zip(por_email["id_registro"], por_email["id_conta"]))
    confere(divergentes == 0, f"{divergentes} associação(ões) por e-mail com endereços diferentes")
    contas_por_email = atv.groupby("email")["id_conta"].nunique()
    pessoas_por_email = cad.groupby("email")["chave_pessoa"].nunique()
    ambiguos = sum(contas_por_email.get(email_conta[b], 0) > 1 or pessoas_por_email.get(email_conta[b], 0) > 1
                   for b in por_email["id_conta"])
    confere(ambiguos == 0, f"{ambiguos} associação(ões) feitas com e-mail ambíguo")


def test_nome_nunca_associa_sozinho(dados):
    _, _, r = dados
    confere(set(r.associacoes["regra"]) <= REGRAS_SEM_NOME, "associação feita só por nome")
    por_nome = r.candidatos[r.candidatos["motivo"].isin(MOTIVOS_POR_NOME)]
    pares = set(zip(r.associacoes["id_registro"], r.associacoes["id_conta"]))
    confere(not any(p in pares for p in zip(por_nome["id_registro"], por_nome["id_conta"])),
            "sugestão por nome tratada como associação")
    pendentes = {k for k, v in _status(r).items() if v in (rc.PENDENTE, rc.AMBIGUO)}
    confere(set(r.candidatos["id_registro"]) <= pendentes | set(r.associacoes["id_registro"]),
            "sugestão de registro fora da revisão")


def test_sugestoes_por_nome_semelhante_tem_similaridade_minima(dados):
    _, _, r = dados
    semelhantes = r.candidatos[r.candidatos["motivo"] == rc.MOTIVO_NOME_SEMELHANTE]
    confere((semelhantes["similaridade"] >= rc.SIMILARIDADE_MINIMA).all(), "sugestão com similaridade abaixo do mínimo")


def test_contas_da_equipe_nao_sao_sugeridas_por_nome(dados):
    _, atv, r = dados
    equipe = set(atv.loc[atv["eh_equipe"] == 1, "id_conta"])
    sugeridas = r.candidatos[r.candidatos["motivo"].isin(MOTIVOS_POR_NOME)]
    confere(not set(sugeridas["id_conta"]) & equipe, "conta da equipe sugerida por nome")


def test_registros_da_mesma_pessoa_herdam_a_conta(dados):
    cad, _, r = dados
    status = cad[["id_registro", "chave_pessoa"]].assign(s=cad["id_registro"].map(_status(r)))
    mistos = status.groupby("chave_pessoa")["s"].agg(lambda s: rc.CORRESPONDENTE in set(s) and len(set(s)) > 1).sum()
    confere(int(mistos) == 0, f"{int(mistos)} pessoa(s) com registros em situações diferentes de conciliação")


def test_email_real_em_duas_pessoas_fica_ambiguo(dados):
    cad, atv, r = dados
    associados = r.associacoes[r.associacoes["regra"] == rc.REGRA_EMAIL]["id_registro"]
    primeiro = cad[cad["id_registro"] == associados.iloc[0]].iloc[0]
    outro = cad[(cad["chave_pessoa"] != primeiro["chave_pessoa"]) & (cad["email_status"] == "valido")].index[0]
    alterado = cad.copy()
    alterado.loc[outro, "email"] = primeiro["email"]  # o e-mail real de uma pessoa repetido em outra
    s = _status(rc.conciliar(alterado, atv))
    assert s[primeiro["id_registro"]] == s[alterado.loc[outro, "id_registro"]] == rc.AMBIGUO


def test_email_real_em_duas_contas_fica_ambiguo(dados):
    cad, atv, r = dados
    associacao = r.associacoes[r.associacoes["regra"] == rc.REGRA_EMAIL].iloc[0]
    conta = atv[atv["id_conta"] == associacao["id_conta"]]
    copia = conta.assign(id_conta=conta["id_conta"] + "_copia", chave_conta=conta["chave_conta"] + "_copia")
    s = _status(rc.conciliar(cad, pd.concat([atv, copia], ignore_index=True)))
    assert s[associacao["id_registro"]] == rc.AMBIGUO


def test_decisoes_manuais_prevalecem(dados):
    cad, atv, r = dados
    pessoa_de = dict(zip(cad["id_registro"], cad["chave_pessoa"]))
    chave_de = dict(zip(atv["id_conta"], atv["chave_conta"]))
    # Rejeitar uma associação real por e-mail desfaz a associação
    associacao = r.associacoes[r.associacoes["regra"] == rc.REGRA_EMAIL].iloc[0]
    rejeicao = pd.DataFrame([{"chave_pessoa": pessoa_de[associacao["id_registro"]],
                              "chave_conta": chave_de[associacao["id_conta"]], "decisao": "rejeitar"}])
    assert _status(rc.conciliar(cad, atv, rejeicao))[associacao["id_registro"]] != rc.CORRESPONDENTE
    # Associar manualmente uma sugestão real em revisão
    if r.candidatos.empty:
        pytest.skip("os dados reais não têm sugestões em revisão")
    sugestao = r.candidatos.iloc[0]
    associar = pd.DataFrame([{"chave_pessoa": pessoa_de[sugestao["id_registro"]],
                              "chave_conta": chave_de[sugestao["id_conta"]], "decisao": "associar"}])
    manual = rc.conciliar(cad, atv, associar)
    assert _status(manual)[sugestao["id_registro"]] == rc.CORRESPONDENTE
    assert rc.REGRA_MANUAL in set(manual.associacoes.loc[manual.associacoes["id_registro"] == sugestao["id_registro"], "regra"])


def test_decisao_sobre_pessoa_ausente_e_contada(dados):
    cad, atv, _ = dados
    decisao = pd.DataFrame([{"chave_pessoa": "cpf:sem-registro-no-cadastro", "chave_conta": atv["chave_conta"].iloc[0],
                             "decisao": "associar"}])
    r = rc.conciliar(cad, atv, decisao)
    assert r.decisoes_sem_efeito == 1 and r.alertas


def test_situacao_das_contas_coerente_com_as_associacoes(dados):
    _, atv, r = dados
    contas = dict(zip(r.status_contas["id_conta"], r.status_contas["status_conciliacao"]))
    associadas = set(r.associacoes["id_conta"])
    assert set(contas) == set(atv["id_conta"])
    confere(all((contas[c] == rc.CORRESPONDENTE) == (c in associadas) for c in contas),
            "situação de conta incoerente com as associações")
