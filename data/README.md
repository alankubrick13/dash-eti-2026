# Dados

| Pasta | Conteúdo | Versionado? |
|---|---|---|
| `referencias/` | `municipios_ibge.csv`: lista oficial de municípios (código IBGE, nome, UF, região), obtida da API de localidades do IBGE (`servicodados.ibge.gov.br/api/v1/localidades/municipios`) em 21/10/2026, usada para validar o campo CODIBGE. `malhas/`: malhas territoriais da Região Norte (municípios e UFs), da API de malhas do IBGE (versão 3, qualidade mínima), usadas nos mapas. Dados públicos, sem informação pessoal. | Sim |
| `privado/` | Banco SQLite, chave de pseudonimização e cache dos microdados do Inep (padrão de `ETI_DIRETORIO_DADOS`). Criada com permissão 700. | **Nunca** |

O painel trabalha só com dados reais: os arquivos fornecidos pela coordenação (cadastro e exportação da
plataforma) e as bases oficiais (Inep e IBGE). Não há dados de exemplo nem gerados.

Planilhas reais não devem ser guardadas dentro do repositório. Se estiverem na raiz do projeto, o
`.gitignore` as ignora, mas o lugar mais seguro é fora da pasta do projeto ou dentro de `data/privado/`.
