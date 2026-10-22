"""Leitura automática dos arquivos reais colocados na pasta do painel (sem passo de importação)."""

import shutil

import pytest
from conftest import RAIZ, confere

from src import config, pasta
from src.persistence import Repositorio


@pytest.fixture
def pasta_real(tmp_path, arquivos_cadastro, arquivo_atividade):
    """Uma pasta com cópias dos arquivos reais (para poder tirar e trocar arquivos sem tocar nos originais)."""
    destino = tmp_path / "pasta"
    destino.mkdir()
    for arquivo in [*arquivos_cadastro, arquivo_atividade]:
        shutil.copy2(arquivo, destino / arquivo.name)
    return destino


@pytest.fixture
def cfg(tmp_path, pasta_real, monkeypatch):
    monkeypatch.setenv("ETI_AMBIENTE", "local")
    monkeypatch.setenv("ETI_DIRETORIO_DADOS", str(tmp_path / "dados"))
    monkeypatch.setenv("ETI_PASTA_ARQUIVOS", str(pasta_real))
    return config.carregar_configuracao()


def test_arquivos_reais_reconhecidos_pelo_conteudo(arquivos_cadastro, arquivo_atividade):
    for arquivo in arquivos_cadastro:
        assert pasta.classificar(arquivo.name, arquivo.read_bytes())[0] == "cadastro", arquivo.name
    assert pasta.classificar(arquivo_atividade.name, arquivo_atividade.read_bytes())[0] == "atividade"
    nomes = {p.name for p in pasta.candidatos(RAIZ)}
    assert not {n for n in nomes if n.startswith("requirements")}  # arquivos do projeto ficam de fora


def test_pasta_lida_ao_abrir_e_relida_so_quando_muda(cfg, pseudo, pasta_real, arquivos_cadastro, tabelas_cadastro,
                                                     tabela_atividade):
    repo = Repositorio(cfg.dir_dados / "eti.sqlite3").inicializar()
    resultado = pasta.sincronizar(repo, pseudo, cfg)
    assert len(resultado.importadas) == 2 and not resultado.problemas
    assert len(repo.registros("cadastro")) == sum(len(t.dados) for t in tabelas_cadastro)
    assert len(repo.registros("atividade")) == len(tabela_atividade.dados)
    assert repo.importacao_ativa("cadastro")["importado_por"] == pasta.USUARIO
    assert pasta.sincronizar(repo, pseudo, cfg).importadas == []  # nada mudou na pasta
    if len(arquivos_cadastro) < 2:
        pytest.skip("só há uma planilha do cadastro")
    (pasta_real / arquivos_cadastro[1].name).unlink()  # a lista de novos inscritos sai da pasta
    resultado = pasta.sincronizar(repo, pseudo, cfg)
    assert len(resultado.importadas) == 1
    assert len(repo.registros("cadastro")) == len(tabelas_cadastro[0].dados)
    shutil.copy2(arquivos_cadastro[1], pasta_real / arquivos_cadastro[1].name)  # e volta
    pasta.sincronizar(repo, pseudo, cfg)
    assert len(repo.registros("cadastro")) == sum(len(t.dados) for t in tabelas_cadastro)


def test_pasta_sem_arquivos_nao_inventa_nada(tmp_path, pseudo, monkeypatch):
    monkeypatch.setenv("ETI_DIRETORIO_DADOS", str(tmp_path / "dados"))
    monkeypatch.setenv("ETI_PASTA_ARQUIVOS", str(tmp_path / "vazia"))
    (tmp_path / "vazia").mkdir()
    cfg = config.carregar_configuracao()
    repo = Repositorio(cfg.dir_dados / "eti.sqlite3").inicializar()
    resultado = pasta.sincronizar(repo, pseudo, cfg)
    assert resultado.importadas == [] and repo.importacao_ativa("cadastro") is None


@pytest.mark.lento
def test_base_escolar_lida_do_pacote_oficial_em_cache(cfg, pseudo, pacote_inep):
    cache = cfg.dir_dados / "cache_inep"
    cache.mkdir(parents=True)
    (cache / pacote_inep.name).symlink_to(pacote_inep)
    repo = Repositorio(cfg.dir_dados / "eti.sqlite3").inicializar()
    resultado = pasta.sincronizar(repo, pseudo, cfg)
    confere(len(resultado.importadas) == 3 and not resultado.problemas, "cadastro, atividade e escolas não lidos")
    assert repo.importacao_ativa("escolas") is not None
