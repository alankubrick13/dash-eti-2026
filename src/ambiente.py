"""Obtém o repositório de dados adequado ao modo de execução.

- demonstração: cada sessão recebe uma cópia própria de um banco-modelo
  sintético (criado uma vez por processo). Nada é compartilhado entre
  visitantes e nada persiste além de algumas horas.
- local/produção: um único banco SQLite no diretório de dados privado.
"""

from __future__ import annotations

import shutil
import tempfile
import time
import uuid
from pathlib import Path

import streamlit as st

from . import synthetic
from .persistence import Repositorio
from .security import CHAVE_DEMONSTRACAO, Pseudonimizador, obter_chave_pseudonimizacao

DIR_DEMONSTRACAO = Path(tempfile.gettempdir()) / "painel_eti_demonstracao"
VALIDADE_SESSAO_DEMO_S = 12 * 3600


def _limpar_sessoes_antigas() -> None:
    limite = time.time() - VALIDADE_SESSAO_DEMO_S
    for arquivo in DIR_DEMONSTRACAO.glob("sessao_*.sqlite3*"):
        try:
            if arquivo.stat().st_mtime < limite:
                arquivo.unlink()
        except OSError:
            continue


@st.cache_resource(show_spinner="Preparando os dados fictícios da demonstração…")
def modelo_demonstracao() -> tuple[str, dict[str, str]]:
    DIR_DEMONSTRACAO.mkdir(parents=True, exist_ok=True)
    _limpar_sessoes_antigas()
    caminhos = synthetic.gerar_arquivos(DIR_DEMONSTRACAO / "arquivos")
    modelo = DIR_DEMONSTRACAO / f"modelo_{uuid.uuid4().hex}.sqlite3"
    repo = Repositorio(modelo).inicializar()
    synthetic.popular_repositorio(repo, Pseudonimizador(CHAVE_DEMONSTRACAO), caminhos)
    repo.consolidar()
    return str(modelo), {k: str(v) for k, v in caminhos.items()}


def arquivos_demonstracao() -> dict[str, Path]:
    return {k: Path(v) for k, v in modelo_demonstracao()[1].items()}


def _repositorio_demonstracao() -> Repositorio:
    caminho = st.session_state.get("_demo_db")
    if not caminho or not Path(caminho).exists():
        modelo, _ = modelo_demonstracao()
        _limpar_sessoes_antigas()
        destino = DIR_DEMONSTRACAO / f"sessao_{uuid.uuid4().hex}.sqlite3"
        shutil.copyfile(modelo, destino)
        caminho = str(destino)
        st.session_state["_demo_db"] = caminho
    return Repositorio(Path(caminho))


@st.cache_resource(show_spinner=False)
def _repositorio_persistente(caminho: str, retencao: int) -> Repositorio:
    return Repositorio(Path(caminho), retencao).inicializar()


@st.cache_resource(show_spinner=False)
def _pseudonimizador(chave: str) -> Pseudonimizador:
    return Pseudonimizador(chave)


def obter_repositorio(cfg) -> tuple[Repositorio, Pseudonimizador]:
    pseudo = _pseudonimizador(obter_chave_pseudonimizacao(cfg))
    if cfg.demonstracao:
        return _repositorio_demonstracao(), pseudo
    return _repositorio_persistente(str(cfg.dir_dados / "eti.sqlite3"), cfg.retencao_importacoes), pseudo
