# Dados

| Pasta | Conteúdo | Versionado? |
|---|---|---|
| `referencias/` | `municipios_ibge.csv`: lista oficial de municípios (código IBGE, nome, UF, região), obtida da API de localidades do IBGE (`servicodados.ibge.gov.br/api/v1/localidades/municipios`) em 21/10/2026. Usada para validar o campo CODIBGE. Dado público, sem informação pessoal. | Sim |
| `synthetic/` | Arquivos fictícios gerados por `python scripts/gerar_dados_sinteticos.py`. | Não |
| `privado/` | Banco SQLite, chave de pseudonimização e cache dos microdados do Inep (padrão de `ETI_DIRETORIO_DADOS`). Criada com permissão 700. | **Nunca** |

Planilhas reais não devem ser guardadas dentro do repositório. Se estiverem na raiz do projeto, o
`.gitignore` as ignora, mas o lugar mais seguro é fora da pasta do projeto ou dentro de `data/privado/`.
