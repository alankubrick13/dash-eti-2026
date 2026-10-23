# Painel de acompanhamento da formação — Programa Escola em Tempo Integral

Aplicação web, feita em Streamlit, para os coordenadores acompanharem os cursistas das ações formativas
do Programa Escola em Tempo Integral. Ela cruza três fontes: o cadastro dos cursistas, a exportação de
participantes da plataforma de formação (Moodle) e os dados oficiais das escolas do Inep, buscados pelo
código INEP.

> **Natureza da ferramenta.** É uma ferramenta de apoio à coordenação da formação. **Não é sistema oficial
> do Ministério da Educação**, e a interface informa isso em todas as páginas.

> **Só dados reais.** O painel trabalha exclusivamente com os arquivos fornecidos pela coordenação (cadastro
> e exportação da plataforma) e com bases oficiais (microdados do Inep, APIs do IBGE). Não há modo de
> demonstração, dados de exemplo nem dados gerados, nem no painel nem nos testes.

---

## Sumário

1. [Instalação (Ubuntu/Linux)](#1-instalação-ubuntulinux)
2. [Execução](#2-execução)
3. [Como importar as planilhas](#3-como-importar-as-planilhas)
4. [Como atualizar os dados escolares do Inep](#4-como-atualizar-os-dados-escolares-do-inep)
5. [O que o painel mostra](#5-o-que-o-painel-mostra)
6. [Regras de dados](#6-regras-de-dados)
7. [Segurança e privacidade](#7-segurança-e-privacidade)
8. [Identidade visual](#8-identidade-visual)
9. [Estrutura do projeto](#9-estrutura-do-projeto)
10. [Testes e desempenho](#10-testes-e-desempenho)
11. [Limitações](#11-limitações)
12. [O que falta para um ambiente institucional de produção](#12-o-que-falta-para-um-ambiente-institucional-de-produção)
13. [Fontes consultadas](#13-fontes-consultadas)

---

## 1. Instalação (Ubuntu/Linux)

Requisitos: Python 3.12 ou superior (testado com 3.14) e cerca de 600 MB livres para o ambiente virtual.

```bash
sudo apt install python3-venv          # se o módulo venv ainda não estiver instalado
cd "dash ETI 2026"
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install -r requirements-dev.txt   # apenas para rodar os testes
```

## 2. Execução

O modo é definido pela variável `ETI_AMBIENTE`, que pode estar no ambiente, num arquivo `.env` (veja
`.env.example`) ou em `.streamlit/secrets.toml`. Os dois modos usam os mesmos dados reais.

| Modo | Para quê | Dados | Login |
|---|---|---|---|
| `local` (padrão) | Uso num computador confiável | Reais, em `data/privado/` (fora do git) | Não exige: o painel abre direto |
| `publicacao` | Painel online, para quem precisa ver os dados | Reais: a versão publicada, em `data/publicado/` | Não exige; só leitura |
| `producao` | Servidor institucional | Reais | **OIDC obrigatório** + lista de e-mails autorizados |

```bash
# Uso local com dados reais, acessível só neste computador (atalho)
./abrir_painel.sh

# O mesmo, por extenso
.venv/bin/streamlit run app.py --server.address localhost
```

Depois, abra o endereço indicado no terminal (normalmente http://localhost:8501).

O cabeçalho traz o selo "Dados reais". Enquanto uma base não é importada, as páginas dizem que ela
falta; nunca a preenchem com dados de exemplo. `ETI_AMBIENTE=demonstracao` é recusado com uma mensagem:
esse modo foi removido.

**Sem login, o painel local mostra tudo a quem abrir o endereço dele**, inclusive contatos e a
Administração. Por isso o atalho `./abrir_painel.sh` liga o servidor só neste computador (`localhost`).
Para outras pessoas, use o painel online (abaixo), que é só de leitura e não tem contatos.

### Painel online (versão publicada)

O painel online mostra os mesmos dados e os mesmos números do painel local, a partir de
`data/publicado/eti.sqlite3`, que vai para o GitHub. Ele abre direto, só para leitura: não tem a página
Administração, não exibe contatos e não registra decisões de conciliação.

A versão publicada é gerada a partir do banco local e **não contém**:

- CPF e data de nascimento (que nem o banco local guarda);
- e-mails, trocados por códigos irreversíveis, iguais no cadastro e na plataforma, para que a
  conciliação dê o mesmo resultado; a chave desses códigos fica só neste computador;
- telefone, WhatsApp, raça/cor e gênero;
- o registro de auditoria, as observações e os autores das decisões de conciliação.

Antes de gravar, o gerador confere que nenhum e-mail ou telefone do banco local passou para a cópia; se
passar, nada é publicado.

Para atualizar o painel online:

1. Troque ou acrescente os arquivos na pasta e abra o painel local: ele lê os arquivos e já gera a nova
   versão publicada (ou rode `.venv/bin/python scripts/publicar.py`). Decisões de conciliação e mudanças de
   parâmetros também geram uma nova versão publicada: o arquivo `publicacao.json` guarda a versão dos
   dados de que ela foi gerada, e o painel local a refaz sempre que os dados mudam.
2. Envie `data/publicado/` ao GitHub (`git add data/publicado`, `git commit`, `git push`).

Sem configuração, o painel escolhe o modo sozinho: onde só existe a versão publicada (o servidor
online), abre em `publicacao`; onde há banco local ou arquivos de dados na pasta, em `local`.

**Quem pode ver.** O painel online não tem login. Na hospedagem (por exemplo, no Streamlit Community
Cloud), é possível restringir quem abre o endereço nas configurações de compartilhamento do aplicativo.

## 3. Como importar as planilhas

**Os dados do painel são os arquivos da pasta.** Coloque na pasta do painel (a pasta do projeto; outra
pode ser indicada em `ETI_PASTA_ARQUIVOS`):

- as planilhas do cadastro (.xlsx ou .csv com as colunas do modelo; a principal e a lista de novos
  inscritos formam juntas o cadastro);
- a exportação de participantes da plataforma: o texto copiado da página "Participantes" do Moodle (.txt)
  ou a planilha exportada.

Ao abrir, o painel reconhece cada arquivo pelo conteúdo e confere a soma SHA-256 de cada um. Se algum
arquivo entrou, saiu ou mudou, ele importa a nova versão sozinho, com a mesma validação descrita abaixo,
e avisa no canto da tela. Os arquivos originais nunca são alterados. A base escolar vem do pacote oficial
do Inep: se ele já estiver no cache (`data/privado/cache_inep/`), é lido sozinho; senão, baixe-o na
Administração (seção 4).

A página **Administração** mostra quais arquivos estão em uso e também aceita o envio de arquivos que
estejam em outro lugar. Em uso local sem login, o usuário local é administrador. O envio segue o fluxo:

1. **Enviar** o(s) arquivo(s). Nada é gravado nesta etapa.
2. **Validar arquivos.** O painel mostra:
   - a correspondência entre os cabeçalhos originais e os campos do painel;
   - os registros lidos, as pessoas distintas, os problemas por tipo e as duplicidades;
   - os avisos e os bloqueios;
   - a comparação com a versão em uso: quem entra, quem sai e o que mudou, campo a campo.
3. Se uma coluna obrigatória não for reconhecida, **indique a correspondência manualmente** e valide de
   novo.
4. **Confirmar importação.** A troca é transacional: se a gravação falhar, a versão anterior continua em
   uso. Para descartar a prévia, use **Cancelar**.

### Cadastro dos cursistas (XLSX ou CSV)

- Envie **um ou mais arquivos com a mesma estrutura**, por exemplo a planilha principal e a lista de
  novos inscritos. Juntos, eles formam a nova versão completa do cadastro.
- Obrigatórias: `Nome` e `E-mail`. Recomendadas: `UF`, `Ente`, `CODIBGE`, `INEP`, `Escola`, `Situação`,
  `Ciclo`, `Região`. As demais colunas do modelo (`Articulador`, `Esfera`, `Tipo`, `Origem`, `Cargo/Função`
  etc.) são reconhecidas automaticamente.
- O cabeçalho pode estar em qualquer uma das 30 primeiras linhas, e variações de grafia são aceitas
  ("E-mail", "Endereço de e-mail", "Raça/Cor"…).
- Planilhas com várias abas mostram um seletor de aba.

### Atividade na plataforma (XLSX, CSV ou TXT)

São aceitos dois formatos:

- a exportação de participantes do Moodle ("Baixar dados da tabela como"), em `.xlsx` ou `.csv`;
- o **texto copiado da página "Participantes"** (`.txt`), que é o formato do arquivo
  `Desmarcar todas as seleções.txt`.

**Data da lista.** O Moodle registra o último acesso em tempo relativo ("3 dias 2 horas"), contado a partir
do momento em que a lista foi tirada. Na leitura da pasta, essa data de referência é:

1. a data e a hora escritas no **nome do arquivo**, quando houver: `participantes_21out26_14h58.txt`,
   `participantes 2026-10-21 14h58.txt` ou `participantes_21-10-2026_1458.txt`;
2. senão, o momento em que o arquivo foi **gravado na pasta** (a data de modificação do arquivo).

O painel mostra a origem da data ("conforme o nome do arquivo" ou "conforme a data do arquivo"), a
posição da lista no topo de todas as páginas e o dia aproximado do último acesso de cada pessoa (data da
lista menos o tempo informado pelo Moodle). As faixas de tempo sem acesso não dependem dessa data. Se o
arquivo for copiado de novo, vale a data da cópia; para fixar a data, escreva-a no nome do arquivo. No
envio pela Administração, informe a data e a hora no próprio formulário.

### Pela linha de comando (alternativa local)

```bash
export ETI_AMBIENTE=local
.venv/bin/python scripts/importar.py cadastro planilha_principal.xlsx lista_novos.xlsx            # só valida
.venv/bin/python scripts/importar.py cadastro planilha_principal.xlsx lista_novos.xlsx --confirmar
.venv/bin/python scripts/importar.py atividade "Desmarcar todas as seleções.txt" \
  --referencia "2026-10-21 14:58" --confirmar
```

O script usa o mesmo pipeline e as mesmas validações da interface, e imprime **apenas contagens e códigos
de problema**, nunca valores de células.

## 4. Como atualizar os dados escolares do Inep

**Não existe API pública documentada para consultar escolas pelo código INEP.** Por isso, o painel
trabalha com arquivos oficiais, em três caminhos, todos em **Administração › Base escolar**:

1. **Baixar microdados oficiais do Inep.** O painel baixa o pacote dos Microdados do Censo Escolar pelo
   endereço publicado no portal do Inep e guarda uma cópia em `data/privado/cache_inep/`. Antes de baixar
   de novo, confere tamanho e data de publicação. Depois:
   - lê só as escolas das UFs e dos códigos INEP presentes no cadastro;
   - confere o MD5 publicado dentro do pacote;
   - mostra a cobertura, isto é, quantos códigos do cadastro foram encontrados.

   O pacote de 2025 tem 537 MB e o de 2024, 34 MB; a leitura de 2025 leva cerca de 1 minuto.
2. **Importar um pacote de microdados já baixado** (ZIP ou CSV, até 120 MB por envio). Para o pacote de
   2025, que é maior, use a linha de comando:
   ```bash
   .venv/bin/python scripts/importar.py escolas microdados_censo_escolar_2025_.zip --confirmar
   .venv/bin/python scripts/importar.py escolas --baixar 2025 --confirmar     # baixa e importa
   ```
3. **Importar a exportação do Catálogo de Escolas** (Inep Data). No Catálogo, filtre as UFs e exporte a
   tabela. Na importação, informe o ano de referência exibido no Catálogo; o painel não o presume. É o
   único caminho que traz **coordenadas** das escolas; o painel as guarda, mas os mapas são por
   município (seção 5), porque os microdados não têm coordenadas.

A base escolar é atualizada **sem reimportar o cadastro**. Cada informação escolar exibida traz a fonte e
o ano de referência.

**Formatos aceitos dos microdados**

- **Até 2024:** um único arquivo, `microdados_ed_basica_AAAA.csv`.
- **A partir de 2025:** as tabelas `Tabela_Escola_AAAA` e `Tabela_Matricula_AAAA`, unidas pelo código da
  escola. Em 2025, os indicadores `IN_INF`, `IN_FUND` e `IN_MED` deixaram de existir. Os novos
  `IN_COMUM_*` significam outra coisa: matrículas de estudantes da educação especial em classes comuns.
  Por isso, a oferta de cada etapa é derivada da contagem de matrículas (`QT_MAT_* > 0`), que é a mesma
  definição do indicador no dicionário de 2024 ("possui uma ou mais matrículas").

**Detalhes técnicos do download**

- **Certificado intermediário.** O servidor `download.inep.gov.br` não envia o certificado intermediário
  "RNP ICPEdu GR46 OV TLS CA 2025". O painel embarca esse certificado público
  (`assets/certificados/`) e o acrescenta à cadeia do `certifi`; a verificação TLS continua completa.
- **IPv6/NAT64.** Em algumas redes, o servidor derruba conexões por IPv6/NAT64. O downloader tenta de
  novo forçando IPv4.

## 5. O que o painel mostra

| Página | Conteúdo |
|---|---|
| **Visão geral** | Abre com quatro **destaques** calculados no recorte (quantos já acessaram, quantos acessaram nos últimos 7 dias, quantos nunca acessaram e a menor taxa de acesso entre as turmas, citando todas as empatadas); cada destaque leva ao detalhe (por exemplo, à galeria de cursistas já no grupo "Nunca acessaram"). Depois, indicadores de cadastro e de presença em cartões, cada um com definição, fórmula, fonte e limitações no ícone de ajuda, numerador e denominador e uma barra da proporção; o aviso de pendências de conciliação; a situação de cada estado (pela turma ou pela UF do cadastro); o mapa de calor das turmas; o mapa do acesso por município ao lado do **histograma do tempo desde o último acesso** (classes de dias na cor da faixa, a coluna "Nunca" e as marcas dos 7 e 14 dias com as datas correspondentes); e **perfil e participação**: cargo, origem da vaga, escolaridade e semana da inscrição pela situação de acesso. |
| **Cursistas** | Galeria de cartões, um por pessoa: iniciais na cor da situação de acesso, cargo, escola, município e turma, a situação na plataforma ("Último acesso há 3 dias (18/10)", "Nunca acessou"…) e a marca "Acompanhar" quando a pessoa entra nos critérios de acompanhamento. Cartões de filtro no topo (todas, requerem acompanhamento, acesso recente, sem acesso há mais de 14 dias, nunca acessaram, sem conta, conta em conciliação), busca por nome, escola, município ou turma, e ordenação ("Atenção primeiro" é a padrão). Os cartões não mostram CPF, nascimento nem contatos. |
| **Atividade e turmas** | Indicadores das contas, o histograma do tempo desde o último acesso e a **galeria de turmas**: um cartão por turma da plataforma, com um ponto por estudante na cor da sua situação, quantos já acessaram, quantos nunca acessaram e quantos estão acima do limite de acompanhamento; filtro por estado e ordenação ("Atenção primeiro"). Clicar em uma turma abre a ficha dela. Em "Comparar grupos", o tempo desde o último acesso por estado da turma, turma, UF, cargo, origem da vaga, escolaridade, esfera, semana da inscrição, localização da escola, área diferenciada, internet e banda larga na escola (Censo), articulador ou papel; dimensões com um único valor ficam de fora. |
| **Escolas** | Galeria de cartões, um por escola: município, nome oficial (como publicado pelo Inep), um ponto por cursista na cor da sua situação de acesso e a barra de quantos já acessaram. Cartões de filtro pela situação da escola (todos já acessaram, parte ainda não, ninguém acessou, ninguém com conta), busca e ordenação. Abaixo, a **participação por contexto da escola** (localização, área diferenciada, internet e banda larga declaradas ao Censo: comparação descritiva), o panorama das escolas no Censo e a situação dos códigos INEP. |
| **Mapa e território** | Mapa dos municípios (malhas oficiais do IBGE), colorido por acesso ao curso, por quem nunca acessou, por quem requer acompanhamento, por cursistas ou por escolas; o mapa ocupa a área toda em qualquer largura de tela. Ao lado, os **municípios que pedem atenção** (mais pessoas com conta que nunca acessaram primeiro). Ao clicar em um município, no mapa ou na lista, aparecem os números dele e os cartões das suas escolas; clicar em uma escola abre a ficha dela. Também traz a distribuição por UF e por ente e o cruzamento entre o estado da turma e a UF do cadastro. |
| **Qualidade e conciliação** | Abre com a **checagem dos dados** em cartões (registros lidos, duplicidades, CPF, e-mail, códigos IBGE e INEP, escolas no Censo, conciliação, contas de estudante sem cadastro e data da lista); cada cartão leva à sua seção. As sugestões de conciliação aparecem em **cartões lado a lado** (cadastro ↔ plataforma, com a semelhança dos nomes e e-mails parciais), com Associar e Rejeitar no painel local; também há associação manual, desfazer e revogar. As pendências viram linhas que abrem a ficha; as importações, uma linha do tempo; e as tabelas detalhadas ficam em "Ver tabela", para auditoria. |
| **Sobre os dados** | Fontes e datas (cadastro, lista da plataforma, Censo Escolar, malhas do IBGE), como ler as cores, a definição de cada indicador (fórmula, valores ausentes, limitações), o que fica fora da versão publicada e como os dados são atualizados. |
| **Administração** | Importações com prévia, base escolar, parâmetros operacionais, auditoria e relatórios. |

**Fichas em gaveta lateral.** Clicar em um cartão de pessoa, de escola ou de turma, em qualquer página
(Cursistas, Escolas, Atividade e turmas, Mapa e território, Qualidade e conciliação, ou num destaque da
Visão geral), abre a ficha numa gaveta à direita, sem sair da página:

- **Ficha do cursista:** situação, etapas da participação (inscrição → conta na plataforma → acesso ao
  curso → último acesso), pontos de atenção, a escola (clique para abrir a ficha dela) e os detalhes em
  seções recolhidas (inscrição e vínculo, plataforma, origem dos dados). Contatos e dados declarados
  (raça/cor, gênero) só aparecem por ação explícita de usuário autorizado, e a consulta é registrada na
  auditoria.
- **Ficha da escola:** números da escola na formação, quem dela participa (clique para abrir a ficha da
  pessoa), matrículas declaradas ao Censo, matrículas em tempo integral por etapa, infraestrutura e
  dados cadastrais do Inep.
- **Ficha da turma:** estudantes, quem já acessou, quem acessou nos últimos 7 dias, quem nunca acessou e
  quem está acima do limite de acompanhamento; um ponto por estudante; a lista de quem precisa de
  atenção (clique para abrir a ficha da pessoa) e, recolhida, a de quem está com o acesso em dia. A
  equipe da turma (formadores, coordenação, suporte) aparece só como contagem por papel.

De uma ficha aberta a partir da outra, "Voltar" retorna à anterior. A gaveta fecha no X, com Esc ou com
um clique fora dela.

Os **filtros globais** ficam na barra lateral e valem para todas as páginas: Região, UF, Ente, Ciclo,
Articulador, Esfera, Tipo, Origem, Situação cadastral, Grupo de formação e Município da escola. Filtros
com um único valor nos dados ficam ocultos.

## 6. Regras de dados

### Unidades: pessoas, registros, contas e escolas

| Unidade | Definição |
|---|---|
| **Pessoas** | Identificadores pseudônimos distintos: CPF válido; na falta dele, e-mail válido; na falta dos dois, nome + ente. |
| **Registros** | Linhas de inscrição, incluindo duplicidades. |
| **Contas** | Linhas da exportação da plataforma. Só os papéis configurados como de cursista (padrão: "Estudante") entram nos indicadores de cursistas. |
| **Escolas** | Códigos INEP válidos distintos. |

As definições completas de cada indicador estão no próprio painel, em "Notas metodológicas", e em
`src/metrics.py`.

### Normalização (sem perder o original para auditoria)

- **Códigos INEP e IBGE** são sempre texto, com os zeros à esquerda preservados.
  - INEP: 8 dígitos, começando por um código de UF válido.
  - IBGE: 7 dígitos (município) ou 2 (UF, para entes estaduais), conferido contra a lista oficial de
    municípios em `data/referencias/`.
- **E-mails** são passados para minúsculas e aparados. Um e-mail inválido continua inválido: é
  sinalizado, não corrigido.
- **Categorias** com grafias diferentes ("aceitou", "ACEITOU ") são unificadas na grafia mais frequente
  da própria fonte.
- **Nenhum registro é descartado.** Problemas viram códigos, contados no relatório de qualidade. Cada
  problema cita arquivo, linha e coluna original.

### Conciliação entre cadastro e plataforma (conservadora e auditável)

A conciliação aplica as regras abaixo, nesta ordem:

1. Decisões manuais dos coordenadores: associar ou rejeitar um par. Elas ficam registradas com autor e
   data e nunca alteram as planilhas.
2. E-mail normalizado, quando é inequívoco: exatamente uma conta e uma pessoa com aquele e-mail.
   - 2b. Outros registros da mesma pessoa (mesmo CPF ou e-mail) herdam a conta associada.
3. Identificador compartilhado, se as duas fontes tiverem um.
4. Nome idêntico ou semelhante gera **apenas sugestão**, pendente ou ambígua, para revisão.
   **Nunca associa sozinho.**

Situações possíveis: Correspondente, Pendente, Ambíguo e Sem correspondência. O CPF não é usado no
cruzamento.

### Atividade, acesso e acompanhamento

- **Faixas de tempo desde o último acesso.** O padrão é 1, 7 e 14 dias (até 24 horas, 1 a 7 dias, 7 a 14
  dias e mais de 14 dias), configurável na Administração.
  Há ainda três faixas sem medida de tempo: "Sem registro de acesso", "Acesso não interpretado" e "Sem
  conta associada".
- **Requer acompanhamento.** A pessoa entra nessa lista quando:
  - não tem conta localizada;
  - tem conta não ativa;
  - nunca acessou;
  - ou está sem acesso há mais tempo que o limite configurado (padrão: 14 dias).

  São critérios operacionais configuráveis. **Não são classificação de evasão, abandono ou desistência.**
- **Situação da conta ≠ atividade.** O último acesso não informa frequência, conclusão de atividades nem
  desempenho.

## 7. Segurança e privacidade

| Medida | Implementação |
|---|---|
| Minimização | **CPF e data de nascimento não são gravados.** São usados em memória para validar e detectar duplicidades; o CPF vira um HMAC-SHA256 (pseudônimo) com chave guardada fora do repositório. |
| Pseudonimização ≠ anonimização | Com a chave e os CPFs, a correspondência pode ser refeita. Guarde a chave com o mesmo cuidado do banco. |
| Tabelas sem dados desnecessários | A tabela de cursistas, as listas e os relatórios não incluem CPF, contatos nem dados declarados. A exportação controlada só está disponível para administradores, remove colunas de contato e fica registrada na auditoria. |
| Acesso a contatos | Só para usuários em `ETI_ACESSO_CONTATOS` (padrão: administradores), por ação explícita, com registro na auditoria. |
| Logs | Um filtro remove e-mails, CPFs e telefones das mensagens e dos rastreamentos de erro. |
| Erros na tela | `client.showErrorDetails = "none"`: o navegador nunca recebe rastreamento de erro. As mensagens de importação citam arquivo, linha e coluna, nunca valores. |
| URLs | Não há dado pessoal em URLs ou parâmetros. As páginas ficam em `paginas/`, e não em `pages/`, para que todas passem pelo `app.py` (configuração, carga dos dados e, em produção, o login). |
| Uploads | A extensão e a assinatura binária são conferidas. Arquivos com macros são recusados, há proteção contra *zip bomb* e há limites de tamanho e de linhas. |
| Arquivos | O banco é criado com permissão 600 e a pasta de dados com 700. O `.gitignore` bloqueia planilhas, bancos, `.env` e `secrets.toml`. |
| Retenção | Mantêm-se as últimas N versões de cada base (`ETI_RETENCAO_IMPORTACOES`, padrão 3). As mais antigas têm os registros apagados e só os metadados ficam. |
| Cache | Os dados carregados ficam no cache do processo, chaveado pela versão do banco. O cache só é consultado depois da autorização do usuário, e todos os coordenadores autorizados veem as mesmas informações. |

Repositório privado não é proteção de dados, e hospedagem gratuita não está automaticamente autorizada
para dados institucionais: o painel só deve ser publicado em hospedagem aprovada pela instituição
(seção 12).

## 8. Identidade visual

- **Marca:** `assets/marca/marca_eti.png`, a logo do programa indicada pela coordenação. Ela aparece no
  cabeçalho sem alterações, com mais de 157 px de largura e área de proteção, sobre fundo branco, como
  pede o manual (MEC/ACS, v1.0, jan/2024). Para ocultá-la, use `ETI_EXIBIR_MARCA=0`.
- **Estilo dos gráficos:** segue a referência visual definida pela coordenação.
  - Fonte Inter, servida localmente sob a licença SIL OFL 1.1.
  - Títulos grandes, com uma linha de contexto acima ("Escola em Tempo Integral · Região Norte") e a
    fonte dos dados no rodapé.
  - Paleta de um só matiz, verde-petróleo: do tom mais escuro (acesso mais recente) ao mais claro, mais
    cinza para "Nunca acessou".
  - Contagens escritas dentro das barras e mapa de calor em blocos arredondados (percentual e fração).
  - Barras, histograma e mapas de calor são HTML/CSS próprios (`src/graficos.py`, `assets/estilo.css`);
    só o mapa dos municípios usa Plotly (`src/mapas.py`), num contêiner com a proporção da região, para
    ocupar a área toda em qualquer largura de tela.
  - Os gráficos se ajustam à largura da coluna em que estão (consultas de contêiner do CSS). Um número
    que não cabe dentro da barra vai para logo depois dela, ou fica só na dica do segmento; nada é cortado.
    Gráficos lado a lado passam a ficar um embaixo do outro quando a área útil é estreita, como em telas de
    1024 px com a barra lateral aberta.
  - Todo gráfico tem tabela equivalente em "Ver dados do gráfico".
- **Cartões:** indicadores, destaques, checagem dos dados, turmas, escolas e pessoas seguem o mesmo
  padrão (borda clara, cantos arredondados, número em destaque); os clicáveis inteiros ganham contorno
  de foco ao navegar pelo teclado.
- **Contraste:** textos secundários pequenos usam cinza com contraste de pelo menos 4,5:1 sobre o branco
  (WCAG AA).
- **Faixas de acesso (padrão):** Até 24 horas, 1 a 7 dias, 7 a 14 dias, Mais de 14 dias e Nunca acessou.
  São configuráveis na Administração.
- **Desvio em relação ao manual:** o manual indica a família Rawline e as cores azul, verde, vermelho e
  amarelo do programa. A interface usa Inter e verde-petróleo por decisão da coordenação; as cores do
  programa aparecem na logo.

## 9. Estrutura do projeto

```
app.py                      ponto de entrada: autenticação, carga, filtros globais, navegação
paginas/                    1_visao_geral … 7_administracao, 8_sobre
src/
  config.py                 ambiente, caminhos, UFs, endereços oficiais, parâmetros padrão
  loaders.py                leitura de XLSX/CSV/TXT do Moodle, validação de upload, mapeamento de colunas
  normalization.py          e-mail, códigos INEP/IBGE/CPF, datas, último acesso
  validators.py             catálogo de problemas, duplicidades, verificação estrutural
  importacao.py             pipeline de importação, prévia, comparação e confirmação
  reconciliation.py         conciliação cadastro × plataforma
  school_data.py            microdados do Censo, Catálogo, download com cache, enriquecimento
  painel.py                 base analítica, faixas, motivos de acompanhamento, filtros
  metrics.py                indicadores documentados
  persistence.py            SQLite com troca transacional, decisões, parâmetros, auditoria
  security.py               pseudonimização, mascaramento, logs, autenticação
  ambiente.py               repositório de dados (banco SQLite em data/privado ou cópia da versão publicada)
  pasta.py                  leitura automática dos arquivos de dados colocados na pasta
  publicacao.py             geração e conferência da versão publicada
  mapas.py                  mapa dos municípios (malhas do IBGE) e agregação por município
  cartoes.py                cartões das galerias, destaques, checagem dos dados e peças visuais das fichas
  fichas.py                 fichas da escola, da turma e do cursista (gavetas laterais)
  graficos.py, ui.py        gráficos e componentes de interface
scripts/                    importar.py (importação pela linha de comando), publicar.py (versão publicada)
assets/                     estilo.css, certificado intermediário do Inep, pasta para a marca
static/fonts/               Inter (OFL)
data/referencias/           lista oficial de municípios e malhas territoriais do IBGE (Região Norte)
data/publicado/             versão publicada do banco (sem contatos), lida pelo painel online
tests/                      131 testes com os dados reais (pytest + AppTest)
.streamlit/config.toml      tema, fontes, segurança de erros e uploads
```

## 10. Testes e desempenho

```bash
.venv/bin/python -m pytest                 # todos os testes (cerca de 3,5 minutos)
.venv/bin/python -m pytest -m "not lento"  # sem os que leem o pacote do Inep
```

**Os testes usam somente dados reais**, os mesmos do painel:

- as planilhas do cadastro e o texto da página de participantes do Moodle, na raiz do projeto (fora do
  git);
- uma cópia do banco do painel, feita numa pasta temporária (o banco original nunca é alterado);
- o pacote de microdados do Inep em cache e as referências do IBGE (lista de municípios e malhas).

Nenhuma pessoa, escola ou registro é inventado. Quando um caso de erro precisa de uma variação (um
e-mail malformado, uma coluna ausente, um e-mail repetido em outra pessoa), ela é derivada de um valor
real. Os únicos textos fixos são especificações de formato, como "2 dias 3 horas". Sem os arquivos
reais (por exemplo, numa cópia do repositório), os testes que dependem deles são ignorados.

Privacidade na saída dos testes: as verificações sobre dados pessoais só informam contagens, e o pytest
roda com `--assert=plain`; nenhum nome, e-mail ou CPF aparece na tela, nem em caso de falha.

São 131 testes (130 aprovados e 1 ignorado: o da exportação do Catálogo de Escolas, que não foi
fornecida). Eles cobrem:

- leitura das planilhas e do texto do Moodle (valores preservados como vieram, mesmo conteúdo em CSV,
  recusa de formatos incompatíveis);
- normalização de cada e-mail, CPF, código INEP e IBGE, data e último acesso reais, e a data escrita no
  nome dos arquivos reais;
- importação (problemas sinalizados conforme cada campo, CPF e data de nascimento nunca gravados) e
  conciliação (e-mail inequívoco associa, nome apenas sugere, decisões manuais prevalecem);
- persistência transacional, retenção, permissões do banco e da pasta de dados;
- segurança (redação de logs, pseudonimização, mascaramento);
- base escolar com o pacote oficial do Inep (MD5, etapas derivadas das matrículas, enriquecimento);
- indicadores, faixas de acesso, filtros e mapas; os destaques conferidos contra os indicadores; o
  histograma somando quem tem acesso; as turmas cobrindo todos os estudantes; o perfil e a escola de cada
  conta vindos do cadastro;
- cartões de todas as pessoas, escolas e turmas reais, sem nenhum contato dentro deles;
- as oito páginas abertas sobre a cópia do banco, as galerias, as gavetas e a navegação entre elas
  (destaque → galeria filtrada, turma → pessoa → turma, lista de municípios → município, decisão de
  conciliação gravada na cópia);
- leitura automática dos arquivos da pasta (inclusive num painel sem banco) e a data da lista vinda do
  arquivo, relida quando o arquivo é gravado de novo;
- versão publicada: sem contatos nem dados sensíveis, com os mesmos números e a mesma data da lista do
  painel local, regerada quando os dados mudam, e o painel online só de leitura.

Desempenho com os arquivos reais:

| Etapa | Tempo |
|---|---|
| Validação do cadastro (1.269 registros) | 2,8 s |
| Validação da atividade (1.330 contas) | 0,2 s |
| Montagem da base analítica | 1,0 s, uma vez por versão dos dados (fica em cache) |
| Cada interação com filtros e indicadores | 0,07 s |

Resultado da importação dos arquivos reais:

- **Cadastro:** 1.269 registros, todas as colunas reconhecidas e 4 sem código INEP.
- **Atividade:** 1.330 contas, com 100% dos "últimos acessos" interpretados; lista salva em 21/10/2026
  14:58 (data do arquivo), com últimos acessos de 01/09 a 21/10/2026.
- **Conciliação:** 1.264 associações por e-mail; das 5 sugestões de nome igual ou semelhante, 4 foram
  associadas por decisão manual registrada no painel local e 1 segue em revisão.
- **Escolas:** 745 de 745 códigos INEP localizados no Censo Escolar 2025.

## 11. Limitações

- **Inep:** não há API de consulta. O download depende da disponibilidade de `download.inep.gov.br`,
  cujo servidor tem a cadeia TLS incompleta (tratado) e recusa algumas rotas IPv6 (tratado com IPv4).
  Os microdados não trazem coordenadas, que só vêm da exportação manual do Catálogo de Escolas; por isso
  os mapas mostram municípios, nunca escolas em posições aproximadas. Os dados escolares se referem ao
  ano do Censo indicado, não ao momento atual.
- **Mapas:** o município de cada pessoa é o da escola segundo o Inep; sem escola localizada, é o do ente,
  quando o ente é um município. Pessoas de redes estaduais com escola não localizada ficam fora do mapa
  (o indicador "Pessoas sem município identificado" mostra quantas são). As malhas são as de qualidade
  mínima do IBGE, com contornos simplificados, adequadas à escala estadual. Para outras UFs, o painel
  baixa as malhas do IBGE na primeira vez e guarda uma cópia em `data/referencias/malhas/`.
- **Moodle:**
  - O último acesso exportado é relativo e tem a precisão das duas maiores unidades ("14 dias 22
    horas"). O dia aproximado do acesso depende da data da lista: a do nome do arquivo ou, sem ela, a
    data em que o arquivo foi gravado, que pode ser posterior à exportação se o arquivo for copiado.
  - O leitor do texto copiado depende do layout da página "Participantes" em português. Se uma nova
    versão do Moodle mudar esse layout, prefira a exportação em XLSX/CSV.
- **Categorias do cadastro** ("Situação", "Tipo", "Origem") são exibidas como vieram da fonte; o painel
  não reinterpreta o seu significado.
- **Autenticação OIDC:** está implementada com o mecanismo nativo do Streamlit, mas não foi testada de
  ponta a ponta aqui, por falta de credenciais de um provedor institucional.
- **SQLite:** atende a instalações pequenas, com um servidor e poucos administradores simultâneos.

## 12. O que falta para um ambiente institucional de produção

1. **Autorização institucional.** É preciso:
   - aprovar a finalidade e a base legal (LGPD), com registro da operação de tratamento e, se
     necessário, relatório de impacto;
   - definir o prazo de retenção;
   - obter autorização para o uso da marca, se ela for exibida.
2. **Hospedagem aprovada pela instituição.** Exige HTTPS por proxy reverso (nginx, Caddy ou similar),
   `server.allowedHosts` configurado e backups cifrados do banco e da chave de pseudonimização. Não use o
   Community Cloud para dados reais.
3. **Provedor de identidade** (Google Workspace, Microsoft Entra ID, gov.br ou outro OIDC), registrado e
   configurado em `.streamlit/secrets.toml`, seguindo o modelo em `secrets.toml.example`. Também é
   preciso definir `ETI_USUARIOS_AUTORIZADOS`, `ETI_ADMINISTRADORES`, `ETI_ACESSO_CONTATOS` e
   `ETI_CHAVE_PSEUDONIMIZACAO`.
4. **Rotina de atualização.** Definir quem exporta o cadastro e a atividade, com que frequência, e
   **escrever a data e a hora de cada exportação no nome do arquivo** (ex.: `participantes_21out26_14h58.txt`).
5. **Banco compartilhado (opcional).** Para mais de um servidor ou muitos administradores, migrar
   `src/persistence.py` para PostgreSQL. O SQL é padrão, exceto `BEGIN IMMEDIATE`.
6. **Revisão dos parâmetros operacionais** (faixas, limite de acompanhamento, papéis de cursista) com a
   coordenação pedagógica.

## 13. Fontes consultadas

Fontes consultadas em 21/10/2026:

- Inep — Microdados do Censo Escolar: https://www.gov.br/inep/pt-br/acesso-a-informacao/dados-abertos/microdados/censo-escolar
  (dicionários de dados das edições 2024 e 2025, dentro dos pacotes).
- Inep — Catálogo de Escolas: https://www.gov.br/inep/pt-br/acesso-a-informacao/dados-abertos/inep-data/catalogo-de-escolas
- IBGE — API de localidades: https://servicodados.ibge.gov.br/api/docs/localidades
- IBGE — API de malhas territoriais (versão 3, qualidade mínima, por UF e por município):
  https://servicodados.ibge.gov.br/api/docs/malhas?versao=3
- MEC — Manual de Identidade Visual da Escola em Tempo Integral, cópia arquivada:
  https://web.archive.org/web/20250405071735/https://www.gov.br/mec/pt-br/centrais-de-conteudo/marcas/MIV_EscolaemTempoIntegral.pdf
- Padrão Digital de Governo (fonte Rawline): https://cdngovbr-ds.estaleiro.serpro.gov.br/design-system/fonts/rawline/
