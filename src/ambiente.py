"""Obtém o repositório de dados: um único banco SQLite no diretório de dados privado (fora do git).

O painel trabalha só com dados reais: os arquivos fornecidos pela coordenação (cadastro e plataforma)
e as bases oficiais (Inep, IBGE). Não há dados de exemplo nem gerados.
"""

from __future__ import annotations

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


def obter_repositorio(cfg) -> tuple[Repositorio, Pseudonimizador]:
    pseudo = _pseudonimizador(obter_chave_pseudonimizacao(cfg))
    return _repositorio_persistente(str(cfg.dir_dados / "eti.sqlite3"), cfg.retencao_importacoes), pseudo
