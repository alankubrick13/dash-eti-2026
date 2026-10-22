"""Configuração central: ambiente de execução, caminhos, referências oficiais e parâmetros.

Os valores vêm, nesta ordem, de variáveis de ambiente, de ``st.secrets`` e dos
padrões definidos aqui. Nenhum segredo tem valor padrão no código.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DIR_ASSETS = RAIZ / "assets"
DIR_REFERENCIAS = RAIZ / "data" / "referencias"
ARQ_MUNICIPIOS = DIR_REFERENCIAS / "municipios_ibge.csv"
ARQ_CERT_INEP = DIR_ASSETS / "certificados" / "rnp_icpedu_gr46_ov_tls_ca_2025.pem"
ARQ_CSS = DIR_ASSETS / "estilo.css"
DIR_MARCA = DIR_ASSETS / "marca"

# O painel trabalha só com dados reais: os fornecidos pela coordenação e os de fontes oficiais (Inep, IBGE).
# local: este computador, com tudo; publicacao: leitura da versão publicada (data/publicado), para quem abre o
# painel online; producao: servidor institucional com login.
AMBIENTES = ("local", "publicacao", "producao")
DIR_PUBLICADO = RAIZ / "data" / "publicado"
EXTENSOES_DADOS = (".xlsx", ".csv", ".txt")

NOME_PROGRAMA = "Programa Escola em Tempo Integral"
NOME_FERRAMENTA = "Painel de acompanhamento da formação"
AVISO_NATUREZA = (
    "Ferramenta de apoio à coordenação da formação. "
    "Não é sistema oficial do Ministério da Educação."
)

# Unidades da Federação: código IBGE -> (sigla, nome, região). Tabela oficial do IBGE.
UFS: dict[str, tuple[str, str, str]] = {
    "11": ("RO", "Rondônia", "Norte"),
    "12": ("AC", "Acre", "Norte"),
    "13": ("AM", "Amazonas", "Norte"),
    "14": ("RR", "Roraima", "Norte"),
    "15": ("PA", "Pará", "Norte"),
    "16": ("AP", "Amapá", "Norte"),
    "17": ("TO", "Tocantins", "Norte"),
    "21": ("MA", "Maranhão", "Nordeste"),
    "22": ("PI", "Piauí", "Nordeste"),
    "23": ("CE", "Ceará", "Nordeste"),
    "24": ("RN", "Rio Grande do Norte", "Nordeste"),
    "25": ("PB", "Paraíba", "Nordeste"),
    "26": ("PE", "Pernambuco", "Nordeste"),
    "27": ("AL", "Alagoas", "Nordeste"),
    "28": ("SE", "Sergipe", "Nordeste"),
    "29": ("BA", "Bahia", "Nordeste"),
    "31": ("MG", "Minas Gerais", "Sudeste"),
    "32": ("ES", "Espírito Santo", "Sudeste"),
    "33": ("RJ", "Rio de Janeiro", "Sudeste"),
    "35": ("SP", "São Paulo", "Sudeste"),
    "41": ("PR", "Paraná", "Sul"),
    "42": ("SC", "Santa Catarina", "Sul"),
    "43": ("RS", "Rio Grande do Sul", "Sul"),
    "50": ("MS", "Mato Grosso do Sul", "Centro-Oeste"),
    "51": ("MT", "Mato Grosso", "Centro-Oeste"),
    "52": ("GO", "Goiás", "Centro-Oeste"),
    "53": ("DF", "Distrito Federal", "Centro-Oeste"),
}
CODIGO_DA_SIGLA = {sigla: codigo for codigo, (sigla, _, _) in UFS.items()}
REGIAO_DA_SIGLA = {sigla: regiao for _, (sigla, _, regiao) in UFS.items()}
NOME_DA_SIGLA = {sigla: nome for _, (sigla, nome, _) in UFS.items()}

# Microdados do Censo Escolar: endereços publicados na página oficial do Inep
# (conferidos em 21/10/2026). O arquivo de 2025 tem "_" antes de ".zip".
PAGINA_MICRODADOS_INEP = (
    "https://www.gov.br/inep/pt-br/acesso-a-informacao/dados-abertos/microdados/censo-escolar"
)
PAGINA_CATALOGO_ESCOLAS = (
    "https://www.gov.br/inep/pt-br/acesso-a-informacao/dados-abertos/inep-data/catalogo-de-escolas"
)
URLS_MICRODADOS_INEP: dict[int, str] = {
    2025: "https://download.inep.gov.br/dados_abertos/microdados_censo_escolar_2025_.zip",
    2024: "https://download.inep.gov.br/dados_abertos/microdados_censo_escolar_2024.zip",
    2023: "https://download.inep.gov.br/dados_abertos/microdados_censo_escolar_2023.zip",
}

# Parâmetros operacionais (editáveis na Administração). Não são definições
# oficiais de evasão ou abandono.
PARAMETROS_PADRAO: dict = {
    "faixas_inatividade_dias": [1, 7, 14],
    "limite_acompanhamento_dias": 14,
    "janela_acesso_recente_dias": 7,
    "papeis_cursista": ["Estudante"],
    "situacoes_conta_ativa": ["Ativo"],
}


@dataclass(frozen=True)
class Configuracao:
    ambiente: str
    dir_dados: Path
    pasta_arquivos: Path  # onde a coordenação coloca as planilhas e a exportação da plataforma
    pasta_publicada: Path  # versão publicada do banco (data/publicado), lida no modo publicacao
    usuarios_autorizados: frozenset[str]
    administradores: frozenset[str]
    acesso_contatos: frozenset[str]
    fuso_horario: str
    retencao_importacoes: int
    exibir_marca: bool
    chave_pseudonimizacao: str | None

    @property
    def producao(self) -> bool:
        return self.ambiente == "producao"


def _carregar_dotenv(caminho: Path) -> None:
    """Lê um arquivo .env simples (CHAVE=valor). Variáveis já definidas no ambiente têm prioridade."""
    if not caminho.exists():
        return
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, valor = linha.split("=", 1)
        valor = valor.strip().strip('"').strip("'")
        if valor:
            os.environ.setdefault(chave.strip(), valor)


def _segredo(nome: str):
    """Lê um valor de st.secrets sem falhar quando não há arquivo de segredos."""
    try:
        import streamlit as st

        return st.secrets.get(nome)
    except Exception:
        return None


def ler_opcao(nome: str, padrao: str | None = None) -> str | None:
    valor = os.environ.get(nome)
    if valor is None:
        valor = _segredo(nome)
    if valor is None:
        return padrao
    return str(valor).strip()


def _lista_emails(valor: str | None) -> frozenset[str]:
    if not valor:
        return frozenset()
    itens = valor.replace(";", ",").replace("\n", ",").split(",")
    return frozenset(i.strip().lower() for i in itens if i.strip())


def _verdadeiro(valor: str | None) -> bool:
    return str(valor or "").strip().lower() in {"1", "true", "sim", "yes"}


def _ambiente_padrao(dir_dados: Path, pasta_arquivos: Path, pasta_publicada: Path) -> str:
    """Sem ETI_AMBIENTE: "publicacao" onde só existe a versão publicada (o painel online); senão, "local"."""
    if (dir_dados / "eti.sqlite3").exists() or not (pasta_publicada / "eti.sqlite3").exists():
        return "local"
    arquivos = pasta_arquivos.iterdir() if pasta_arquivos.is_dir() else []
    if any(p.is_file() and p.suffix.lower() in EXTENSOES_DADOS and not p.name.startswith("requirements")
           for p in arquivos):
        return "local"
    return "publicacao"


def carregar_configuracao() -> Configuracao:
    _carregar_dotenv(RAIZ / ".env")
    dir_dados = Path(ler_opcao("ETI_DIRETORIO_DADOS", str(RAIZ / "data" / "privado")))
    if not dir_dados.is_absolute():
        dir_dados = RAIZ / dir_dados
    pasta_arquivos = Path(ler_opcao("ETI_PASTA_ARQUIVOS", str(RAIZ)))
    if not pasta_arquivos.is_absolute():
        pasta_arquivos = RAIZ / pasta_arquivos
    pasta_publicada = Path(ler_opcao("ETI_PASTA_PUBLICADA", str(DIR_PUBLICADO)))
    ambiente = (ler_opcao("ETI_AMBIENTE") or _ambiente_padrao(dir_dados, pasta_arquivos, pasta_publicada)).lower()
    if ambiente == "demonstracao":
        raise ValueError("O modo demonstração foi removido: o painel trabalha só com dados reais. "
                         "Use ETI_AMBIENTE=local (este computador) ou producao (servidor institucional).")
    if ambiente not in AMBIENTES:
        raise ValueError(
            f"ETI_AMBIENTE inválido: use um de {', '.join(AMBIENTES)}."
        )
    if ambiente == "publicacao":
        dir_dados = Path(tempfile.gettempdir()) / "painel_eti_publicado"  # cópia de trabalho da versão publicada
    administradores = _lista_emails(ler_opcao("ETI_ADMINISTRADORES"))
    contatos = _lista_emails(ler_opcao("ETI_ACESSO_CONTATOS")) or administradores
    try:
        retencao = max(2, int(ler_opcao("ETI_RETENCAO_IMPORTACOES", "3")))
    except ValueError:
        retencao = 3
    return Configuracao(
        ambiente=ambiente,
        dir_dados=dir_dados,
        pasta_arquivos=pasta_arquivos,
        pasta_publicada=pasta_publicada,
        usuarios_autorizados=_lista_emails(ler_opcao("ETI_USUARIOS_AUTORIZADOS")) | administradores,
        administradores=administradores,
        acesso_contatos=contatos,
        fuso_horario=ler_opcao("ETI_FUSO_HORARIO", "America/Sao_Paulo") or "America/Sao_Paulo",
        retencao_importacoes=retencao,
        exibir_marca=_verdadeiro(ler_opcao("ETI_EXIBIR_MARCA", "1")),
        chave_pseudonimizacao=ler_opcao("ETI_CHAVE_PSEUDONIMIZACAO"),
    )
