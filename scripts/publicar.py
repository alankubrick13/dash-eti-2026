"""Gera a versão publicada do painel (data/publicado/) a partir do banco local, sem dados de contato.

Uso: .venv/bin/python scripts/publicar.py
Depois, envie data/publicado/ ao GitHub (git add, commit e push): o painel online passa a mostrar a nova
versão. O painel local também gera a versão publicada sozinho sempre que os dados mudam (arquivos novos
na pasta, decisões de conciliação ou parâmetros).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config, publicacao  # noqa: E402
from src.persistence import Repositorio  # noqa: E402
from src.security import obter_chave_pseudonimizacao  # noqa: E402

cfg = config.carregar_configuracao()
if cfg.ambiente != "local":
    sys.exit("A versão publicada é gerada a partir do banco local (ETI_AMBIENTE=local).")
banco = cfg.dir_dados / "eti.sqlite3"
info = publicacao.gerar(banco, obter_chave_pseudonimizacao(cfg), cfg.pasta_publicada, Repositorio(banco).versao())
print(f"Versão publicada gerada em {cfg.pasta_publicada}: "
      + ", ".join(f"{n} registros de {f}" for f, n in info["registros"].items()))
