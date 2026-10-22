#!/usr/bin/env bash
# Abre o painel com os dados reais deste computador (modo local), acessível só aqui (localhost), sem login.
set -euo pipefail
cd "$(dirname "$0")"
export ETI_AMBIENTE=local
exec .venv/bin/streamlit run app.py --server.address localhost --server.port "${PORTA:-8501}" "$@"
