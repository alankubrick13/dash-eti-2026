"""Persistência: troca transacional de retratos, retenção, decisões e permissões."""

import os
import stat
from datetime import date

import pytest
from conftest import linha_cadastro, tabela

from src import importacao
from src.persistence import Repositorio


def _previa(pseudo, cabecalhos, nomes):
    linhas = [linha_cadastro(n, email=f"{n.split()[0].lower()}@correio.example") for n in nomes]
    return importacao.preparar_cadastro([tabela("cad.xlsx", cabecalhos, linhas)], pseudo, hoje=date(2026, 10, 20))


def test_importacao_falha_preserva_versao_anterior(repo, pseudo, cabecalhos_cadastro, monkeypatch):
    primeira = _previa(pseudo, cabecalhos_cadastro, ["ANA SOUZA", "BRUNO LIMA"])
    id1 = importacao.confirmar(repo, primeira, "teste")
    segunda = _previa(pseudo, cabecalhos_cadastro, ["CARLA DIAS", "DANIEL REIS", "ELISA MOTA"])
    # Simula falha no meio da gravação (depois de inserir parte dos dados)
    original = Repositorio._expurgar

    def falhar(self, con, fonte):
        raise RuntimeError("falha simulada")

    monkeypatch.setattr(Repositorio, "_expurgar", falhar)
    with pytest.raises(RuntimeError):
        importacao.confirmar(repo, segunda, "teste")
    monkeypatch.setattr(Repositorio, "_expurgar", original)
    ativa = repo.importacao_ativa("cadastro")
    assert ativa["id"] == id1
    assert sorted(repo.registros("cadastro")["nome"]) == ["ANA SOUZA", "BRUNO LIMA"]
    assert repo.historico()["status"].tolist() == ["ativa"]  # nenhum resto da importação desfeita


def test_previa_bloqueada_nao_pode_ser_confirmada(repo, pseudo, cabecalhos_cadastro):
    sem_nome = [h for h in cabecalhos_cadastro if h != "Nome"]
    linha = [v for h, v in zip(cabecalhos_cadastro, linha_cadastro()) if h != "Nome"]
    previa = importacao.preparar_cadastro([tabela("x.xlsx", sem_nome, [linha])], pseudo)
    with pytest.raises(ValueError):
        importacao.confirmar(repo, previa, "teste")
    assert repo.importacao_ativa("cadastro") is None


def test_retencao_expurga_retratos_antigos(repo, pseudo, cabecalhos_cadastro):
    ids = [importacao.confirmar(repo, _previa(pseudo, cabecalhos_cadastro, [f"PESSOA NUMERO {i}"]), "teste")
           for i in range(4)]
    historico = repo.historico("cadastro").set_index("id")["status"].to_dict()
    assert historico[ids[3]] == "ativa" and historico[ids[2]] == "substituida"
    assert historico[ids[0]] == historico[ids[1]] == "expurgada"
    assert repo.registros("cadastro", ids[0]).empty  # dados apagados; metadados mantidos
    assert repo.importacao_anterior("cadastro")["id"] == ids[2]


def test_decisoes_e_versao(repo):
    versao = repo.versao()
    decisao = repo.registrar_decisao("cpf:1", "email:a@b.example", "associar", "conferido", "coord@x.example")
    assert repo.versao() != versao
    assert repo.decisoes()["decisao"].tolist() == ["associar"]
    repo.registrar_decisao("cpf:1", "email:a@b.example", "rejeitar", None, "coord@x.example")
    assert repo.decisoes()["decisao"].tolist() == ["rejeitar"]  # nova decisão substitui a anterior do mesmo par
    antes = repo.versao()
    repo.revogar_decisao(int(repo.decisoes()["id"].iloc[0]), "coord@x.example")
    assert repo.decisoes().empty and repo.versao() != antes
    assert decisao > 0
    assert {"conciliacao_associar", "conciliacao_rejeitar", "conciliacao_revogada"} <= set(repo.auditoria()["acao"])


def test_parametros_com_padrao(repo):
    assert repo.parametros()["faixas_inatividade_dias"] == [1, 7, 14]
    repo.salvar_parametros({"faixas_inatividade_dias": [5, 10, 20], "chave_desconhecida": 1}, "admin")
    assert repo.parametros()["faixas_inatividade_dias"] == [5, 10, 20]


@pytest.mark.skipif(os.name != "posix", reason="permissões POSIX")
def test_banco_criado_com_permissao_restrita(tmp_path):
    Repositorio(tmp_path / "privado" / "eti.sqlite3").inicializar()
    assert stat.S_IMODE(os.stat(tmp_path / "privado" / "eti.sqlite3").st_mode) == 0o600
    assert stat.S_IMODE(os.stat(tmp_path / "privado").st_mode) == 0o700
