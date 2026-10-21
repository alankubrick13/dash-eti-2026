"""Fixtures compartilhadas. Todos os dados dos testes são fictícios."""

import random
import sys
import zlib
from pathlib import Path

import pandas as pd
import pytest

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from src.loaders import TabelaBruta  # noqa: E402
from src.persistence import Repositorio  # noqa: E402
from src.security import Pseudonimizador  # noqa: E402
from src.synthetic import CABECALHOS_CADASTRO, gerar_cpf  # noqa: E402


@pytest.fixture
def pseudo():
    return Pseudonimizador("chave-de-teste-com-mais-de-32-caracteres")


@pytest.fixture
def repo(tmp_path):
    return Repositorio(tmp_path / "teste.sqlite3", retencao=2).inicializar()


def tabela(nome: str, cabecalhos: list[str], linhas: list[list]) -> TabelaBruta:
    dados = pd.DataFrame(linhas, columns=cabecalhos, dtype=object)
    dados["__linha__"] = list(range(2, len(linhas) + 2))
    return TabelaBruta(nome, None, "xlsx", "0" * 64, 0, 1, list(cabecalhos), dados)


def cpf(semente: int) -> str:
    return gerar_cpf(random.Random(semente))


def linha_cadastro(nome="MARIA DA SILVA", email="maria.silva@correio.example", inep=15012345, uf="PA",
                   cod_ibge=1501402, cpf_valor=None, nascimento="10/05/1980", situacao="Aceitou", escola="EMEF TESTE",
                   ente="Belém") -> list:
    valores = {
        "Região": "Norte", "UF": uf, "Ente": ente, "CODIBGE": cod_ibge, "Data resposta": "14/08/2026",
        "Ciclo": "2026", "Articulador": "JOANA PEREIRA", "Esfera": "Municipal", "Nome": nome,
        "CPF": cpf_valor or cpf(zlib.crc32(nome.encode())), "Data Nascimento": nascimento, "E-mail": email,
        "Telefone": "91900001234", "WhatsApp": "Não", "Tipo": "Titular", "Origem": "Regular",
        "Situação": situacao, "Raça/Cor": "Parda", "Gênero": "Feminino", "Escolaridade": "Especializacao",
        "Cargo/Função": "Diretor Escolar", "Escola": escola, "INEP": inep,
    }
    return [valores[h] for h in CABECALHOS_CADASTRO]


@pytest.fixture
def cabecalhos_cadastro():
    return list(CABECALHOS_CADASTRO)


@pytest.fixture(scope="session")
def arquivos_sinteticos(tmp_path_factory):
    from src import synthetic

    return synthetic.gerar_arquivos(tmp_path_factory.mktemp("sinteticos"))
