"""Gera os arquivos fictícios de demonstração em data/synthetic/ (não versionados).

Uso: python scripts/gerar_dados_sinteticos.py [pasta_destino] [--semente 2026]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config, synthetic  # noqa: E402

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("destino", nargs="?", type=Path, default=config.DIR_SINTETICOS)
parser.add_argument("--semente", type=int, default=2026)
args = parser.parse_args()
for chave, caminho in synthetic.gerar_arquivos(args.destino, args.semente).items():
    print(f"{chave:>22}: {caminho} ({caminho.stat().st_size / 1024:.0f} KB)")
