"""Proteção de dados pessoais, verificada com os valores reais (e-mails, CPFs, telefones, códigos INEP)."""

import logging
import os
import re
import secrets
import stat
from dataclasses import replace

import pytest
from conftest import confere, quadro

from src.config import carregar_configuracao
from src.loaders import CAMPOS_CADASTRO
from src.normalization import classificar_inep, normalizar_email, validar_cpf
from src.security import (
    FiltroRedacao,
    Pseudonimizador,
    mascarar_email,
    mascarar_telefone,
    obter_chave_pseudonimizacao,
    redigir,
)


@pytest.fixture(scope="module")
def reais(tabelas_cadastro):
    """Amostra de valores reais válidos (até 50 linhas com e-mail, CPF, telefone e INEP)."""
    dados = quadro(tabelas_cadastro, CAMPOS_CADASTRO)
    amostra = []
    for _, linha in dados.iterrows():
        email, s_email = normalizar_email(linha["email"])
        cpf, s_cpf = validar_cpf(linha["cpf"])
        inep, s_inep = classificar_inep(linha["inep"])
        telefone = re.sub(r"\D", "", str(linha.get("telefone") or ""))
        if s_email == "valido" and s_cpf.startswith("valido") and s_inep == "valido" and len(telefone) >= 10:
            amostra.append({"email": email, "cpf": cpf, "inep": inep, "telefone": telefone})
        if len(amostra) == 50:
            break
    if not amostra:
        pytest.skip("sem linhas reais completas para a amostra")
    return amostra


def test_redacao_remove_dados_pessoais_reais(reais):
    vazados = preservados = 0
    for v in reais:
        cpf_formatado = f"{v['cpf'][:3]}.{v['cpf'][3:6]}.{v['cpf'][6:9]}-{v['cpf'][9:]}"
        telefone = f"({v['telefone'][:2]}) {v['telefone'][2:-4]}-{v['telefone'][-4:]}"
        texto = redigir(f"falha com {v['email']}, CPF {cpf_formatado}, tel {telefone}, INEP {v['inep']}")
        vazados += v["email"] in texto or cpf_formatado in texto or v["telefone"][-8:] in texto.replace("-", "")
        preservados += v["inep"] in texto  # código de escola não é dado pessoal
    confere(vazados == 0, f"{vazados} mensagem(ns) com dado pessoal real depois da redação")
    assert preservados == len(reais)


def test_filtro_de_log_redige_mensagem_e_rastreamento(reais):
    registros = []

    class Coletor(logging.Handler):
        def emit(self, record):
            registros.append(self.format(record))

    logger = logging.getLogger("teste_redacao")
    coletor = Coletor()
    coletor.addFilter(FiltroRedacao())
    logger.addHandler(coletor)
    try:
        for v in reais[:10]:
            try:
                raise ValueError(f"e-mail inválido: {v['email']}")
            except ValueError:
                logger.exception("erro ao importar %s", v["email"])
    finally:
        logger.removeHandler(coletor)
    vazados = sum(v["email"] in r for v, r in zip(reais, registros))
    confere(len(registros) == min(10, len(reais)) and vazados == 0, f"{vazados} registro(s) de log com e-mail real")
    assert all("[e-mail]" in r for r in registros)


def test_pseudonimizacao_dos_cpfs_reais(reais):
    a, b = Pseudonimizador(secrets.token_hex(32)), Pseudonimizador(secrets.token_hex(32))
    problemas = sum(a.chave("cpf", v["cpf"]) != a.chave("cpf", v["cpf"]) or a.chave("cpf", v["cpf"]) == b.chave("cpf", v["cpf"])
                    or v["cpf"] in a.chave("cpf", v["cpf"]) for v in reais)
    confere(problemas == 0, f"{problemas} pseudônimo(s) instável(is), igual(is) entre chaves ou com o CPF exposto")
    assert len({a.chave("cpf", v["cpf"]) for v in reais}) == len({v["cpf"] for v in reais})
    assert a.chave("cpf", None) is None


def test_mascaramento_dos_contatos_reais(reais):
    problemas = 0
    for v in reais:
        local, dominio = v["email"].split("@")
        mascarado = mascarar_email(v["email"])
        problemas += not (mascarado.endswith(f"@{dominio}") and local not in mascarado.split("@")[0] or len(local) <= 2)
        telefone = mascarar_telefone(v["telefone"])
        problemas += v["telefone"][2:-2] in re.sub(r"\D", "", telefone)
    confere(problemas == 0, f"{problemas} contato(s) real(is) mal mascarado(s)")


def test_chave_local_gerada_com_permissao_restrita(tmp_path, monkeypatch):
    monkeypatch.setenv("ETI_AMBIENTE", "local")
    monkeypatch.setenv("ETI_DIRETORIO_DADOS", str(tmp_path / "privado"))
    monkeypatch.delenv("ETI_CHAVE_PSEUDONIMIZACAO", raising=False)
    cfg = carregar_configuracao()
    chave = obter_chave_pseudonimizacao(cfg)
    assert len(chave) == 64 and obter_chave_pseudonimizacao(cfg) == chave
    if os.name == "posix":
        assert stat.S_IMODE(os.stat(tmp_path / "privado" / ".chave_pseudonimizacao").st_mode) == 0o600


def test_producao_exige_chave(tmp_path, monkeypatch):
    monkeypatch.setenv("ETI_AMBIENTE", "producao")
    monkeypatch.setenv("ETI_DIRETORIO_DADOS", str(tmp_path))
    monkeypatch.delenv("ETI_CHAVE_PSEUDONIMIZACAO", raising=False)
    cfg = carregar_configuracao()
    with pytest.raises(RuntimeError):
        obter_chave_pseudonimizacao(cfg)
    with pytest.raises(ValueError):
        obter_chave_pseudonimizacao(replace(cfg, chave_pseudonimizacao="curta"))


@pytest.mark.parametrize("ambiente", ["demonstracao", "publico"])
def test_modos_sem_dados_reais_sao_recusados(monkeypatch, ambiente):
    monkeypatch.setenv("ETI_AMBIENTE", ambiente)
    with pytest.raises(ValueError):
        carregar_configuracao()
