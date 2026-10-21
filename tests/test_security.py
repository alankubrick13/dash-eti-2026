import logging
import os
import stat
from dataclasses import replace

import pytest

from src.config import carregar_configuracao
from src.security import (
    FiltroRedacao,
    Pseudonimizador,
    mascarar_email,
    mascarar_telefone,
    obter_chave_pseudonimizacao,
    redigir,
)


def test_redigir_remove_dados_pessoais():
    texto = redigir("falha com maria@mail.example, CPF 123.456.789-09, tel (91) 98888-7777, INEP 15012345")
    assert "maria" not in texto and "123.456" not in texto and "98888" not in texto
    assert "15012345" in texto  # códigos de escola não são dados pessoais


def test_filtro_de_log_redige_mensagem_e_rastreamento():
    registro = None

    class Coletor(logging.Handler):
        def emit(self, record):
            nonlocal registro
            registro = self.format(record)

    logger = logging.getLogger("teste_redacao")
    coletor = Coletor()
    coletor.addFilter(FiltroRedacao())
    logger.addHandler(coletor)
    try:
        raise ValueError("e-mail inválido: jose@mail.example")
    except ValueError:
        logger.exception("erro ao importar %s", "ana@mail.example")
    logger.removeHandler(coletor)
    assert "jose@mail.example" not in registro and "ana@mail.example" not in registro
    assert "[e-mail]" in registro


def test_pseudonimizador_estavel_e_dependente_da_chave():
    a = Pseudonimizador("chave-a" * 6)
    b = Pseudonimizador("chave-b" * 6)
    assert a.chave("cpf", "12345678909") == a.chave("cpf", "12345678909")
    assert a.chave("cpf", "12345678909") != b.chave("cpf", "12345678909")
    assert "12345678909" not in a.chave("cpf", "12345678909")
    assert a.chave("cpf", None) is None


def test_mascaramento():
    assert mascarar_email("maria.silva@mail.example") == "ma•••@mail.example"
    assert mascarar_telefone("91988887777") == "(91) •••••-••77"


def test_chave_local_gerada_com_permissao_restrita(tmp_path, monkeypatch):
    monkeypatch.setenv("ETI_AMBIENTE", "local")
    monkeypatch.setenv("ETI_DIRETORIO_DADOS", str(tmp_path / "privado"))
    monkeypatch.delenv("ETI_CHAVE_PSEUDONIMIZACAO", raising=False)
    cfg = carregar_configuracao()
    chave = obter_chave_pseudonimizacao(cfg)
    assert len(chave) == 64 and obter_chave_pseudonimizacao(cfg) == chave
    arquivo = tmp_path / "privado" / ".chave_pseudonimizacao"
    if os.name == "posix":
        assert stat.S_IMODE(os.stat(arquivo).st_mode) == 0o600


def test_producao_exige_chave(tmp_path, monkeypatch):
    monkeypatch.setenv("ETI_AMBIENTE", "producao")
    monkeypatch.setenv("ETI_DIRETORIO_DADOS", str(tmp_path))
    monkeypatch.delenv("ETI_CHAVE_PSEUDONIMIZACAO", raising=False)
    cfg = carregar_configuracao()
    with pytest.raises(RuntimeError):
        obter_chave_pseudonimizacao(cfg)
    with pytest.raises(ValueError):
        obter_chave_pseudonimizacao(replace(cfg, chave_pseudonimizacao="curta"))


def test_ambiente_invalido(monkeypatch):
    monkeypatch.setenv("ETI_AMBIENTE", "publico")
    with pytest.raises(ValueError):
        carregar_configuracao()
