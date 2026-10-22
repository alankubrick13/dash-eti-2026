"""Painel de acompanhamento da formação do Programa Escola em Tempo Integral."""

import time

import pandas as pd

# Momento em que o código foi carregado; o app.py compara com a data dos arquivos para recarregar o código
# atualizado (ex.: depois de um commit novo no servidor online).
CARREGADO_EM = time.time()

# Texto em armazenamento Python: o pipeline percorre colunas elemento a elemento (normalização,
# conciliação), e a iteração sobre arrays pyarrow é bem mais lenta nesse uso.
pd.set_option("mode.string_storage", "python")
