"""Sobre os dados: fontes e datas, como ler as cores, definição de cada indicador e o que fica fora da versão publicada."""

import html

import streamlit as st

from src import cartoes, config, graficos, metrics, painel, school_data, ui
from src import reconciliation as rc

ctx = painel.contexto()
base = ctx.base
fuso = ctx.cfg.fuso_horario
parametros = base.parametros
ui.titulo_pagina(
    "Sobre os dados",
    "De onde vêm os números do painel, de quando são, como cada indicador é calculado e o que fica de fora da "
    "versão publicada. Todos os números vêm dos arquivos da coordenação e de fontes oficiais; nada é estimado.",
)

# ---------------------------------------------------------------- fontes
ui.secao("Fontes e datas")
cad, atv, esc = (base.meta.get(f) or {} for f in ("cadastro", "atividade", "escolas"))
arquivos_cadastro = ", ".join(a.get("arquivo", "") for a in cad.get("arquivos", []))
arquivos_atividade = ", ".join(a.get("arquivo", "") for a in atv.get("arquivos", []))
contas = base.contas
fontes = [
    cartoes.fonte_dados(
        "badge", "Cadastro dos cursistas",
        "Planilhas de inscrição da coordenação, colocadas na pasta do painel e lidas sem alteração.",
        [("Registros", metrics.numero(len(base.cursistas)) if base.tem_cadastro else "não encontrado"),
         ("Respostas às inscrições", ui.periodo_respostas(base)),
         ("Arquivos", arquivos_cadastro), ("Lido em", ui.data_local(cad.get("importado_em"), fuso))],
    ),
    cartoes.fonte_dados(
        "school", "Lista de participantes da plataforma",
        "Página “Participantes” do curso no Moodle, copiada para um arquivo de texto (ou planilha exportada). "
        "O último acesso vem como tempo decorrido (ex.: “3 dias 5 horas”).",
        [("Contas", f"{metrics.numero(len(contas))} ({metrics.numero(int((contas['eh_cursista'] == 1).sum()))} de "
                    f"estudantes, {metrics.numero(int((contas['eh_equipe'] == 1).sum()))} da equipe)"
          if base.tem_atividade else "não encontrada"),
         ("Data da lista", atv.get("referencia_descricao")), ("Arquivo", arquivos_atividade),
         ("Lida em", ui.data_local(atv.get("importado_em"), fuso))],
    ),
    cartoes.fonte_dados(
        "domain", "Base escolar oficial",
        "Microdados do Censo Escolar do Inep, baixados do portal oficial, cruzados com o cadastro sempre pelo "
        "código INEP da escola (nunca pelo nome).",
        [("Referência", esc.get("referencia_descricao")),
         ("Escolas dos cursistas", metrics.numero(len(base.escolas)) if base.tem_escolas else "base não carregada"),
         ("Página oficial", ("Microdados do Censo Escolar no portal do Inep", config.PAGINA_MICRODADOS_INEP))],
    ),
    cartoes.fonte_dados(
        "map", "Territórios",
        "Malhas municipais e nomes dos municípios das APIs oficiais do IBGE (serviço de dados), usados no mapa. "
        "O município de cada pessoa é o da escola no Censo ou, sem escola localizada, o do ente.",
        [("Malhas", "API de malhas territoriais v3, qualidade mínima"), ("Nomes", "API de localidades")],
    ),
]
st.html(f'<div class="eti-fontes">{"".join(fontes)}</div>')
if ctx.cfg.ambiente == "publicacao":
    publicado = ui.publicado_em(ctx.cfg)
    ui.nota(f"Esta é a versão publicada do painel, gerada em {publicado or 'data não registrada'} a partir do painel "
            "local da coordenação.")
ui.nota("Data da lista da plataforma: vale a data e a hora escritas no nome do arquivo (ex.: "
        "participantes_21out26_14h58.txt) ou, sem elas, o momento em que o arquivo foi gravado na pasta. Se o "
        "arquivo for copiado de novo, vale a data da cópia; para fixar a data, escreva-a no nome do arquivo. "
        "O tempo sem acesso é sempre o que a plataforma informou, medido na data da lista.")

# ---------------------------------------------------------------- cores
ui.secao("Como ler as cores",
         "As mesmas cores aparecem em todos os gráficos, cartões e pontos do painel: a situação de acesso de "
         "cada pessoa na data da lista da plataforma.")
limites = parametros["faixas_inatividade_dias"]
cores = graficos.cores_faixas(painel.ordem_faixas(limites))
explicacoes = {
    painel.FAIXA_NUNCA: "a conta existe, mas a plataforma registra “Nunca” como último acesso",
    painel.FAIXA_NAO_INTERPRETADO: "o texto do último acesso não pôde ser lido",
    painel.FAIXA_SEM_CONTA: "nenhuma conta da plataforma associada à pessoa (inclui quem está em conciliação)",
}
itens = "".join(
    f'<li><i style="background:{cor}"></i><b>{html.escape(faixa)}</b>'
    f'<span>{html.escape(explicacoes.get(faixa, "tempo desde o último acesso ao curso"))}</span></li>'
    for faixa, cor in cores.items()
)
st.html(f'<ul class="eti-cores">{itens}</ul>')
ui.nota(f"Parâmetros em uso: acesso recente = até {parametros['janela_acesso_recente_dias']} dias; requer "
        f"acompanhamento = sem conta localizada, conta não ativa, nunca acessou ou mais de "
        f"{parametros['limite_acompanhamento_dias']} dias sem acesso. São critérios operacionais, configuráveis na "
        "Administração, e não equivalem a evasão ou desistência.")

# ---------------------------------------------------------------- indicadores
ui.secao("Indicadores",
         "Definição, fórmula, tratamento de valores ausentes e limitações de cada número. Pessoas são contadas por "
         "identificador pseudônimo (CPF ou, na falta dele, e-mail); registros são linhas do cadastro; contas são "
         "linhas da lista da plataforma; escolas são códigos INEP distintos.")
grupos_indicadores = (
    ("Cadastro", [i for i in metrics.INDICADORES.values() if "plataforma" not in i.fonte]),
    ("Plataforma de formação", [i for i in metrics.INDICADORES.values() if "plataforma" in i.fonte]),
    ("Contas da plataforma (página Atividade e turmas)", list(metrics.INDICADORES_CONTAS.values())),
    ("Escolas", list(metrics.INDICADORES_ESCOLAS.values())),
)
for titulo, indicadores in grupos_indicadores:
    st.markdown(f"#### {titulo}")
    st.html(f'<div class="eti-indicadores">{"".join(cartoes.definicao_indicador(i) for i in indicadores)}</div>')
ui.nota(f"{school_data.DEFINICAO_TEMPO_INTEGRAL} {school_data.AVISO_PROGRAMA}")

# ---------------------------------------------------------------- privacidade
ui.secao("Privacidade",
         "O painel mostra nomes, escolas, territórios e a situação na plataforma, para que a coordenação acompanhe a "
         "formação. Dados de contato e dados sensíveis ficam de fora.")
nunca_publicados = [
    ("CPF e data de nascimento", "não são gravados nem no painel local: só servem para identificar a mesma pessoa, "
                                 "por um código irreversível"),
    ("E-mails", "trocados por códigos irreversíveis na versão publicada, iguais no cadastro e na plataforma, para "
                "que a conciliação dê o mesmo resultado"),
    ("Telefone, WhatsApp, raça/cor e gênero", "ficam só no painel local, com consulta registrada"),
    ("Observações e autores das decisões de conciliação, registro de auditoria",
     "ficam só no painel local"),
]
st.html('<ul class="eti-privacidade">' + "".join(
    f'<li><span class="eti-icone" aria-hidden="true">lock</span><div><b>{html.escape(t)}</b>'
    f"<span>{html.escape(d)}</span></div></li>" for t, d in nunca_publicados) + "</ul>")

# ---------------------------------------------------------------- atualização
ui.secao("Como os dados são atualizados")
passos = [
    ("folder_open", "Arquivos na pasta", "A coordenação coloca na pasta do painel as planilhas do cadastro e a lista "
                                          "de participantes da plataforma (substituindo as antigas)."),
    ("sync", "Painel local", "Ao abrir, o painel local lê os arquivos sozinho, valida tudo e gera a versão publicada "
                              "(sem contatos nem dados sensíveis)."),
    ("cloud_upload", "Painel online", "A versão publicada é enviada ao repositório; o painel online passa a mostrá-la."),
]
st.html('<ol class="eti-passos-atualizacao">' + "".join(
    f'<li><span class="eti-icone" aria-hidden="true">{i}</span><div><b>{html.escape(t)}</b>'
    f"<span>{html.escape(d)}</span></div></li>" for i, t, d in passos) + "</ol>")
pessoas = painel.pessoas_de(base.cursistas) if base.tem_cadastro else base.cursistas
if base.tem_atividade and not pessoas.empty:
    associadas = int((pessoas["status_conciliacao"] == rc.CORRESPONDENTE).sum())
    ui.nota(f"Conciliação em uso: {metrics.numero(associadas)} de {metrics.numero(len(pessoas))} pessoas associadas a "
            "uma conta da plataforma pelo e-mail ou por decisão manual. Detalhes em Qualidade e conciliação.")
ui.nota(config.AVISO_NATUREZA)
