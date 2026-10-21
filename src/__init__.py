"""Painel de acompanhamento da formação do Programa Escola em Tempo Integral."""

import pandas as pd

# Texto em armazenamento Python: o pipeline percorre colunas elemento a elemento (normalização,
# conciliação), e a iteração sobre arrays pyarrow é bem mais lenta nesse uso.
pd.set_option("mode.string_storage", "python")
