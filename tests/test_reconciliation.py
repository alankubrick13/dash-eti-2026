"""Regras de conciliação: e-mail inequívoco associa; nome apenas sugere; decisões manuais prevalecem."""

import pandas as pd

from src import reconciliation as rc
from src.normalization import chave_comparacao


def _cad(*registros):
    linhas = []
    for i, (pessoa, nome, email) in enumerate(registros, start=1):
        linhas.append({"id_registro": f"C{i}", "chave_pessoa": pessoa, "nome_chave": chave_comparacao(nome),
                       "email": email, "email_status": "valido" if email and "@" in email and "." in email.split("@")[-1] else "invalido",
                       "id_compartilhado": None})
    return pd.DataFrame(linhas)


def _atv(*contas):
    linhas = []
    for i, (nome, email, *papel) in enumerate(contas, start=1):
        equipe = 1 if papel and papel[0] == "equipe" else 0
        linhas.append({"id_conta": f"A{i}", "chave_conta": f"email:{email}", "nome_chave": chave_comparacao(nome),
                       "email": email, "email_status": "valido", "eh_equipe": equipe, "id_compartilhado": None})
    return pd.DataFrame(linhas)


def _status(resultado):
    return dict(zip(resultado.status_registros["id_registro"], resultado.status_registros["status_conciliacao"]))


def test_email_inequivoco_associa():
    r = rc.conciliar(_cad(("cpf:1", "ANA SOUZA", "ana@mail.example")), _atv(("ANA SOUZA", "ana@mail.example")))
    assert _status(r) == {"C1": rc.CORRESPONDENTE}
    assert r.associacoes.iloc[0]["regra"] == rc.REGRA_EMAIL


def test_email_de_pessoas_diferentes_e_ambiguo():
    r = rc.conciliar(
        _cad(("cpf:1", "ANA SOUZA", "escola@mail.example"), ("cpf:2", "JOAO LIMA", "escola@mail.example")),
        _atv(("ANA SOUZA", "escola@mail.example")),
    )
    assert _status(r) == {"C1": rc.AMBIGUO, "C2": rc.AMBIGUO}
    assert set(r.candidatos["motivo"]) == {rc.MOTIVO_EMAIL_PESSOAS_DIFERENTES}
    assert r.associacoes.empty


def test_email_em_duas_contas_e_ambiguo():
    r = rc.conciliar(_cad(("cpf:1", "ANA SOUZA", "ana@mail.example")),
                     _atv(("ANA SOUZA", "ana@mail.example"), ("ANA S", "ana@mail.example")))
    assert _status(r)["C1"] == rc.AMBIGUO


def test_nome_igual_nunca_associa_sozinho():
    r = rc.conciliar(_cad(("cpf:1", "ANA SOUZA", "ana@mail.example")), _atv(("ANA SOUZA", "ana.souza@outro.example")))
    assert _status(r)["C1"] == rc.PENDENTE
    assert r.associacoes.empty
    assert r.candidatos.iloc[0]["motivo"] == rc.MOTIVO_NOME_EMAIL_DIFERENTE


def test_homonimos_ficam_ambiguos():
    r = rc.conciliar(_cad(("cpf:1", "ANA SOUZA", "ana@mail.example")),
                     _atv(("ANA SOUZA", "a1@mail.example"), ("ANA SOUZA", "a2@mail.example")))
    assert _status(r)["C1"] == rc.AMBIGUO
    assert len(r.candidatos) == 2


def test_nome_semelhante_gera_sugestao_com_similaridade():
    r = rc.conciliar(_cad(("cpf:1", "MARIA APARECIDA SOUZA", "maria@mail.example")),
                     _atv(("MARIA APARECIDA SOUSA", "m.souza@mail.example")))
    assert _status(r)["C1"] == rc.PENDENTE
    assert r.candidatos.iloc[0]["motivo"] == rc.MOTIVO_NOME_SEMELHANTE
    assert r.candidatos.iloc[0]["similaridade"] >= rc.SIMILARIDADE_MINIMA


def test_conta_da_equipe_nao_e_sugerida_por_nome():
    r = rc.conciliar(_cad(("cpf:1", "RITA ALVES", "rita@mail.example")),
                     _atv(("RITA ALVES", "rita@formacao.example", "equipe")))
    assert _status(r)["C1"] == rc.SEM_CORRESPONDENCIA


def test_decisao_manual_associa_e_rejeicao_desfaz():
    cad = _cad(("cpf:1", "ANA SOUZA", "ana@mail.example"))
    atv = _atv(("ANA S. SOUZA", "outra@mail.example"))
    decisoes = pd.DataFrame([{"chave_pessoa": "cpf:1", "chave_conta": "email:outra@mail.example", "decisao": "associar"}])
    r = rc.conciliar(cad, atv, decisoes)
    assert _status(r)["C1"] == rc.CORRESPONDENTE
    assert r.associacoes.iloc[0]["regra"] == rc.REGRA_MANUAL

    atv2 = _atv(("ANA SOUZA", "ana@mail.example"))
    rejeicao = pd.DataFrame([{"chave_pessoa": "cpf:1", "chave_conta": "email:ana@mail.example", "decisao": "rejeitar"}])
    r2 = rc.conciliar(cad, atv2, rejeicao)
    assert _status(r2)["C1"] == rc.SEM_CORRESPONDENCIA  # nem por e-mail, nem como sugestão por nome


def test_registro_duplicado_da_mesma_pessoa_herda_a_conta():
    r = rc.conciliar(
        _cad(("cpf:1", "ANA SOUZA", "ana@mail.example"), ("cpf:1", "ANA SOUZA", "ana.antigo@mail.example")),
        _atv(("ANA SOUZA", "ana@mail.example")),
    )
    assert _status(r) == {"C1": rc.CORRESPONDENTE, "C2": rc.CORRESPONDENTE}
    assert set(r.associacoes["regra"]) == {rc.REGRA_EMAIL, rc.REGRA_MESMA_PESSOA}


def test_decisao_sobre_registro_ausente_e_contada():
    decisoes = pd.DataFrame([{"chave_pessoa": "cpf:999", "chave_conta": "email:x@mail.example", "decisao": "associar"}])
    r = rc.conciliar(_cad(("cpf:1", "ANA SOUZA", "ana@mail.example")), _atv(("ANA SOUZA", "ana@mail.example")), decisoes)
    assert r.decisoes_sem_efeito == 1 and r.alertas


def test_contas_sem_correspondencia_no_cadastro():
    r = rc.conciliar(_cad(("cpf:1", "ANA SOUZA", "ana@mail.example")),
                     _atv(("ANA SOUZA", "ana@mail.example"), ("PEDRO REIS", "pedro@mail.example")))
    contas = dict(zip(r.status_contas["id_conta"], r.status_contas["status_conciliacao"]))
    assert contas == {"A1": rc.CORRESPONDENTE, "A2": rc.SEM_CORRESPONDENCIA}
