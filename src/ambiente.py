"""Obtém o repositório de dados: um único banco SQLite no diretório de dados privado (fora do git).

O painel trabalha só com dados reais: os arquivos fornecidos pela coordenação (cadastro e plataforma)
e as bases oficiais (Inep, IBGE). Não há dados de exemplo nem gerados.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import streamlit as st

from .persistence import Repositorio
from .security import Pseudonimizador, obter_chave_pseudonimizacao


@st.cache_resource(show_spinner=False)
def _repositorio_persistente(caminho: str, retencao: int) -> Repositorio:
    return Repositorio(Path(caminho), retencao).inicializar()


@st.cache_resource(show_spinner=False)
def _pseudonimizador(chave: str) -> Pseudonimizador:
    return Pseudonimizador(chave)


def _copiar_versao_publicada(cfg) -> None:
    """O arquivo publicado (no repositório) nunca é aberto para escrita: o painel lê uma cópia de trabalho."""
    origem, destino = cfg.pasta_publicada / "eti.sqlite3", cfg.dir_dados / "eti.sqlite3"
    if not origem.exists():
        raise RuntimeError("A versão publicada do painel (data/publicado/eti.sqlite3) não foi encontrada.")
    if not destino.exists() or destino.stat().st_mtime < origem.stat().st_mtime:
        cfg.dir_dados.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origem, destino)


def obter_repositorio(cfg) -> tuple[Repositorio, Pseudonimizador]:
    if cfg.ambiente == "publicacao":
        _copiar_versao_publicada(cfg)
    pseudo = _pseudonimizador(obter_chave_pseudonimizacao(cfg))
    return _repositorio_persistente(str(cfg.dir_dados / "eti.sqlite3"), cfg.retencao_importacoes), pseudo
