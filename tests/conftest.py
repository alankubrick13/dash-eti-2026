"""Fixtures dos testes: somente dados reais.

Os testes usam os arquivos fornecidos pela coordenação (planilhas do cadastro e texto da página de
participantes do Moodle, na raiz do projeto e fora do git), o banco do painel (copiado para uma pasta
temporária; o original nunca é alterado) e as bases oficiais já obtidas (pacote de microdados do Inep
em cache, lista de municípios e malhas do IBGE). Nenhuma pessoa, escola ou registro é inventado: quando
um caso precisa de uma variação (um e-mail malformado, uma coluna ausente), ela é derivada de um valor
real. Sem os arquivos, os testes que dependem deles são ignorados.

As verificações sobre dados pessoais usam ``confere``, que só mostra a mensagem: nenhum nome, e-mail ou
CPF aparece na saída dos testes, nem em caso de falha.

Caminhos alternativos: ETI_TESTE_CADASTRO (planilhas separadas por ``os.pathsep``), ETI_TESTE_ATIVIDADE,
ETI_TESTE_DADOS (pasta com eti.sqlite3).
"""

import os
import secrets
import shutil
import sqlite3
import sys
from pathlib import Path

import pandas as pd
import pytest

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from src import importacao, painel  # noqa: E402
from src.loaders import CAMPOS_ATIVIDADE, CAMPOS_CADASTRO, ler_tabela, mapear_colunas  # noqa: E402
from src.normalization import eh_vazio  # noqa: E402
from src.persistence import Repositorio  # noqa: E402
from src.security import Pseudonimizador  # noqa: E402

FUSO = "America/Sao_Paulo"
PAPEIS_CURSISTA = ["Estudante"]


def _caminhos(variavel: str, padrao: list[Path]) -> list[Path]:
    valor = os.environ.get(variavel)
    return [Path(p) for p in valor.split(os.pathsep) if p] if valor else padrao


ARQUIVOS_CADASTRO = [p for p in _caminhos("ETI_TESTE_CADASTRO", sorted(RAIZ.glob("*.xlsx"))) if p.exists()]
ARQUIVOS_ATIVIDADE = [p for p in _caminhos("ETI_TESTE_ATIVIDADE", sorted(
    p for p in RAIZ.glob("*.txt") if not p.name.startswith("requirements"))) if p.exists()]
DIR_DADOS = Path(os.environ.get("ETI_TESTE_DADOS", RAIZ / "data" / "privado"))
BANCO_REAL = DIR_DADOS / "eti.sqlite3"
PACOTES_INEP = sorted((DIR_DADOS / "cache_inep").glob("microdados_censo_escolar_*.zip"))


def confere(condicao: bool, mensagem: str) -> None:
    """Asserção que nunca mostra valores, só a mensagem (os testes lidam com dados pessoais reais)."""
    if not condicao:
        pytest.fail(mensagem, pytrace=False)


def quadro(tabelas, campos) -> pd.DataFrame:
    """Valores brutos dos arquivos reais (como vieram), com os nomes internos dos campos."""
    partes = []
    for tabela in tabelas:
        mapa = mapear_colunas(tabela.cabecalhos, campos).original_para_interno
        partes.append(tabela.dados[list(mapa)].rename(columns=mapa))
    return pd.concat(partes, ignore_index=True)


def valores(tabelas, campo: str, campos) -> list:
    """Valores não vazios de um campo nos arquivos reais."""
    dados = quadro(tabelas, campos)
    return [v for v in dados[campo].tolist() if not eh_vazio(v)] if campo in dados else []


@pytest.fixture(scope="session")
def arquivos_cadastro() -> list[Path]:
    if not ARQUIVOS_CADASTRO:
        pytest.skip("planilhas reais do cadastro não encontradas na raiz do projeto")
    return ARQUIVOS_CADASTRO


@pytest.fixture(scope="session")
def arquivo_atividade() -> Path:
    if not ARQUIVOS_ATIVIDADE:
        pytest.skip("exportação real da plataforma (texto do Moodle) não encontrada na raiz do projeto")
    return ARQUIVOS_ATIVIDADE[0]


@pytest.fixture(scope="session")
def tabelas_cadastro(arquivos_cadastro):
    return [ler_tabela(p.name, p.read_bytes(), CAMPOS_CADASTRO) for p in arquivos_cadastro]


@pytest.fixture(scope="session")
def tabela_atividade(arquivo_atividade):
    return ler_tabela(arquivo_atividade.name, arquivo_atividade.read_bytes(), CAMPOS_ATIVIDADE, ("xlsx", "csv", "txt"))


@pytest.fixture(scope="session")
def pseudo():
    """Chave aleatória da sessão de testes (não é a chave do painel)."""
    return Pseudonimizador(secrets.token_hex(32))


@pytest.fixture(scope="session")
def previa_cadastro(tabelas_cadastro, pseudo):
    return importacao.preparar_cadastro(tabelas_cadastro, pseudo)


@pytest.fixture(scope="session")
def previa_atividade(tabela_atividade, pseudo):
    return importacao.preparar_atividade([tabela_atividade], pseudo, None, FUSO, PAPEIS_CURSISTA)


@pytest.fixture
def repo(tmp_path):
    return Repositorio(tmp_path / "teste.sqlite3", retencao=2).inicializar()


@pytest.fixture(scope="session")
def dir_dados_real(tmp_path_factory) -> Path:
    """Cópia do banco do painel (e da sua chave) numa pasta temporária; o original nunca é alterado."""
    if not BANCO_REAL.exists():
        pytest.skip("banco do painel (data/privado/eti.sqlite3) não encontrado")
    destino = tmp_path_factory.mktemp("dados_reais")
    origem = sqlite3.connect(f"file:{BANCO_REAL}?mode=ro", uri=True)
    copia = sqlite3.connect(destino / "eti.sqlite3")
    with copia:
        origem.backup(copia)  # retrato consistente, inclusive com o painel aberto
    origem.close()
    copia.close()
    chave = DIR_DADOS / ".chave_pseudonimizacao"
    if chave.exists():
        shutil.copy2(chave, destino / ".chave_pseudonimizacao")
    return destino


@pytest.fixture(scope="session")
def base_real(dir_dados_real):
    return painel.montar_base(Repositorio(dir_dados_real / "eti.sqlite3"))


@pytest.fixture(scope="session")
def pacote_inep() -> Path:
    if not PACOTES_INEP:
        pytest.skip("pacote de microdados do Inep não encontrado em data/privado/cache_inep")
    return PACOTES_INEP[-1]
