"""Persistência com as importações reais: troca transacional, retenção, decisões e permissões.

Tudo é gravado num banco temporário; o banco do painel não é usado.
"""

import getpass
import os
import stat

import pytest
from conftest import confere

from src import importacao
from src import reconciliation as rc
from src.persistence import Repositorio
from test_importacao import sem_coluna

USUARIO = f"local:{getpass.getuser()}"


def test_falha_na_gravacao_preserva_a_versao_anterior(repo, previa_cadastro, tabelas_cadastro, pseudo, monkeypatch):
    primeira = importacao.preparar_cadastro(tabelas_cadastro[:1], pseudo)
    id1 = importacao.confirmar(repo, primeira, USUARIO)
    original = Repositorio._expurgar

    def falhar(self, con, fonte):  # falha depois de inserir a nova versão, antes de concluir
        raise RuntimeError("falha simulada na gravação")

    monkeypatch.setattr(Repositorio, "_expurgar", falhar)
    with pytest.raises(RuntimeError):
        importacao.confirmar(repo, previa_cadastro, USUARIO)
    monkeypatch.setattr(Repositorio, "_expurgar", original)
    assert repo.importacao_ativa("cadastro")["id"] == id1
    assert len(repo.registros("cadastro")) == len(primeira.registros)
    assert repo.historico()["status"].tolist() == ["ativa"]  # nada da importação desfeita ficou para trás


def test_previa_bloqueada_nao_pode_ser_confirmada(repo, tabelas_cadastro, pseudo):
    previa = importacao.preparar_cadastro([sem_coluna(t, "nome") for t in tabelas_cadastro], pseudo)
    with pytest.raises(ValueError):
        importacao.confirmar(repo, previa, USUARIO)
    assert repo.importacao_ativa("cadastro") is None


def test_retencao_expurga_versoes_antigas(repo, previa_cadastro):
    ids = [importacao.confirmar(repo, previa_cadastro, USUARIO) for _ in range(4)]
    historico = repo.historico("cadastro").set_index("id")["status"].to_dict()
    assert historico[ids[3]] == "ativa" and historico[ids[2]] == "substituida"
    assert historico[ids[0]] == historico[ids[1]] == "expurgada"
    assert repo.registros("cadastro", ids[0]).empty  # registros apagados; metadados mantidos
    assert len(repo.registros("cadastro", ids[3])) == len(previa_cadastro.registros)
    assert repo.importacao_anterior("cadastro")["id"] == ids[2]


def test_decisoes_sobre_um_par_real(repo, previa_cadastro, previa_atividade):
    r = rc.conciliar(previa_cadastro.registros, previa_atividade.registros)
    par = r.associacoes.iloc[0]
    pessoa = previa_cadastro.registros.set_index("id_registro").loc[par["id_registro"], "chave_pessoa"]
    conta = previa_atividade.registros.set_index("id_conta").loc[par["id_conta"], "chave_conta"]
    versao = repo.versao()
    assert repo.registrar_decisao(pessoa, conta, "associar", "conferido", USUARIO) > 0
    assert repo.versao() != versao
    repo.registrar_decisao(pessoa, conta, "rejeitar", None, USUARIO)
    assert repo.decisoes()["decisao"].tolist() == ["rejeitar"]  # a nova decisão substitui a anterior do mesmo par
    antes = repo.versao()
    repo.revogar_decisao(int(repo.decisoes()["id"].iloc[0]), USUARIO)
    assert repo.decisoes().empty and repo.versao() != antes
    assert {"conciliacao_associar", "conciliacao_rejeitar", "conciliacao_revogada"} <= set(repo.auditoria()["acao"])


def test_parametros_com_padrao(repo):
    assert repo.parametros()["faixas_inatividade_dias"] == [1, 7, 14]
    repo.salvar_parametros({"faixas_inatividade_dias": [5, 10, 20], "chave_desconhecida": 1}, USUARIO)
    assert repo.parametros()["faixas_inatividade_dias"] == [5, 10, 20]
    assert "chave_desconhecida" not in repo.parametros()


@pytest.mark.skipif(os.name != "posix", reason="permissões POSIX")
def test_banco_e_pasta_com_permissao_restrita(tmp_path, dir_dados_real):
    Repositorio(tmp_path / "privado" / "eti.sqlite3").inicializar()
    assert stat.S_IMODE(os.stat(tmp_path / "privado" / "eti.sqlite3").st_mode) == 0o600
    assert stat.S_IMODE(os.stat(tmp_path / "privado").st_mode) == 0o700
    from conftest import BANCO_REAL, DIR_DADOS

    confere(stat.S_IMODE(os.stat(BANCO_REAL).st_mode) == 0o600, "o banco do painel não está com permissão 600")
    confere(stat.S_IMODE(os.stat(DIR_DADOS).st_mode) == 0o700, "a pasta de dados do painel não está com permissão 700")
