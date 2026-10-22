"""Os dados do painel são os arquivos da pasta: leitura automática, sem passo de importação.

A coordenação coloca na pasta do painel as planilhas do cadastro (.xlsx ou .csv com as colunas do
modelo) e a exportação de participantes da plataforma (texto copiado da página "Participantes" do
Moodle, .txt, ou planilha). Ao abrir, o painel confere esses arquivos pela soma SHA-256: se algum
entrou, saiu ou mudou, importa a nova versão sozinho, com a mesma validação da Administração. Os
arquivos originais nunca são alterados. A base escolar vem do pacote oficial do Inep, se ele já
estiver no cache.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path

from . import config, importacao, school_data
from .loaders import CAMPOS_ATIVIDADE, CAMPOS_CADASTRO, ErroImportacao, ler_tabela, mapear_colunas
from .security import configurar_logging

EXTENSOES = (".xlsx", ".csv", ".txt")
USUARIO = "arquivos da pasta"
ROTULOS = {"cadastro": "cadastro dos cursistas", "atividade": "atividade na plataforma", "escolas": "base escolar do Inep"}

_TRAVA = threading.Lock()
_ULTIMA_CONFERENCIA: dict[str, tuple] = {}


@dataclass
class Resultado:
    importadas: list[str] = field(default_factory=list)  # o que foi atualizado nesta abertura
    problemas: list[str] = field(default_factory=list)  # mensagens sem dados pessoais
    arquivos: dict[str, list[str]] = field(default_factory=dict)  # fonte -> arquivos encontrados


def candidatos(pasta: Path) -> list[Path]:
    if not pasta.is_dir():
        return []
    return sorted(p for p in pasta.iterdir()
                  if p.is_file() and p.suffix.lower() in EXTENSOES and not p.name.startswith(("~$", "."))
                  and not p.name.lower().startswith("requirements"))


def classificar(nome: str, conteudo: bytes):
    """("cadastro" | "atividade", tabela) pelo conteúdo do arquivo; (None, None) se não for dado do painel."""
    formato = Path(nome).suffix.lower().lstrip(".")
    try:
        if formato == "txt":
            tabela = ler_tabela(nome, conteudo, CAMPOS_ATIVIDADE, ("txt",))
            return ("atividade", tabela) if len(tabela.dados) else (None, None)
        atividade = ler_tabela(nome, conteudo, CAMPOS_ATIVIDADE, (formato,))
        mapa = mapear_colunas(atividade.cabecalhos, CAMPOS_ATIVIDADE)
        if "ultimo_acesso" in mapa.original_para_interno.values() and not mapa.faltando_obrigatorios:
            return "atividade", atividade
        cadastro = ler_tabela(nome, conteudo, CAMPOS_CADASTRO, (formato,))
        mapa = mapear_colunas(cadastro.cabecalhos, CAMPOS_CADASTRO)
        if not mapa.faltando_obrigatorios and {"cpf", "inep", "ente", "uf"} & set(mapa.original_para_interno.values()):
            return "cadastro", cadastro
    except ErroImportacao:
        pass
    return None, None


def _impressao(arquivos: list[Path]) -> tuple:
    """Identificação barata do estado da pasta (nome, tamanho, data de modificação)."""
    return tuple((p.name, p.stat().st_size, p.stat().st_mtime_ns) for p in arquivos)


def sincronizar(repo, pseudo, cfg) -> Resultado:
    """Importa os arquivos da pasta que ainda não estão no painel (ou que mudaram)."""
    resultado = Resultado()
    arquivos = candidatos(cfg.pasta_arquivos)
    with _TRAVA:
        chave = f"{repo.caminho}|{cfg.pasta_arquivos}"
        impressao = (_impressao(arquivos), repo.versao())
        if _ULTIMA_CONFERENCIA.get(chave) == impressao:
            return resultado
        tabelas: dict[str, list] = {"cadastro": [], "atividade": []}
        for caminho in arquivos:
            fonte, tabela = classificar(caminho.name, caminho.read_bytes())
            if fonte:
                tabelas[fonte].append(tabela)
        resultado.arquivos = {f: [t.arquivo for t in ts] for f, ts in tabelas.items()}
        for fonte, lista in tabelas.items():
            if not lista:
                continue
            ativa = repo.importacao_ativa(fonte) or {}
            if sorted(a.get("sha256") for a in ativa.get("arquivos", [])) == sorted(t.sha256 for t in lista):
                continue  # os mesmos arquivos já estão no painel
            try:
                if fonte == "cadastro":
                    previa = importacao.preparar_cadastro(lista, pseudo)
                else:
                    previa = importacao.preparar_atividade(lista, pseudo, None, cfg.fuso_horario,
                                                           repo.parametros()["papeis_cursista"])
                if previa.pode_confirmar:
                    importacao.confirmar(repo, previa, USUARIO)
                    resultado.importadas.append(f"{ROTULOS[fonte]} ({', '.join(t.arquivo for t in lista)})")
                else:
                    resultado.problemas += [f"{ROTULOS[fonte].capitalize()}: {b}" for b in previa.bloqueios]
            except Exception:
                configurar_logging().exception("falha ao ler os arquivos da pasta (%s)", fonte)
                resultado.problemas.append(f"Não foi possível ler os arquivos do {ROTULOS[fonte]}.")
        _importar_escolas_do_cache(repo, cfg, resultado)
        _ULTIMA_CONFERENCIA[chave] = (_impressao(arquivos), repo.versao())
    return resultado


def _importar_escolas_do_cache(repo, cfg, resultado: Resultado) -> None:
    """Base escolar: pacote oficial do Inep já baixado (cache), quando o painel ainda não tem uma."""
    if repo.importacao_ativa("escolas") is not None or repo.importacao_ativa("cadastro") is None:
        return
    pacotes = sorted((cfg.dir_dados / "cache_inep").glob("microdados_censo_escolar_*.zip"))
    if not pacotes:
        return
    cadastro = repo.registros("cadastro")
    codigos = set(cadastro.loc[cadastro["inep_status"] == "valido", "inep"])
    ufs = set(cadastro["uf"].dropna()) | {config.UFS[c[:2]][0] for c in codigos if c[:2] in config.UFS}
    try:
        dados, meta = school_data.ler_microdados(pacotes[-1], pacotes[-1].name, codigos, ufs)
        previa = school_data.preparar_escolas(school_data.normalizar_microdados(dados), meta,
                                              school_data.FONTE_MICRODADOS, [{"arquivo": pacotes[-1].name}])
        if previa.pode_confirmar:
            importacao.confirmar(repo, previa, USUARIO)
            resultado.importadas.append(f"{ROTULOS['escolas']} ({pacotes[-1].name})")
    except Exception:
        configurar_logging().exception("falha ao ler o pacote do Inep em cache")
        resultado.problemas.append("Não foi possível ler o pacote do Inep guardado no cache.")
