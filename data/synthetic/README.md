# Dados sintéticos

Gerados por `python scripts/gerar_dados_sinteticos.py`. Os arquivos deste diretório não são versionados.
O modo demonstração gera os seus próprios arquivos numa pasta temporária.

O que é fictício e o que é real:

- **Fictícios:** pessoas, escolas, códigos INEP, CPFs, telefones e grupos.
- **Reais:** os municípios e os códigos IBGE, vindos da lista oficial, para que as validações
  territoriais funcionem.
- **E-mails:** usam o domínio reservado `.example` (RFC 2606).

Os formatos reproduzem os das fontes reais:

- planilha cadastral com os mesmos 23 cabeçalhos;
- texto copiado da página "Participantes" do Moodle;
- CSV no formato dos microdados do Censo Escolar.

Há também falhas plantadas de propósito: e-mails inválidos, duplicidades, códigos ausentes, troca de
e-mail e homônimos. Elas servem para exercitar as telas de qualidade e de conciliação.
