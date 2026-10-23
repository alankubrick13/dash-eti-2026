"""Fichas da escola, da turma e do cursista, abertas em gaveta lateral (st.dialog à direita) a partir de qualquer página.

Quem quer abrir uma ficha chama ``pedir`` (em geral no clique de um cartão). A ficha pedida fica na
sessão e o app chama ``abrir_pendente`` a cada execução, antes da página: a gaveta abre por cima da
página atual, sem trocar de página, e continua aberta em novas execuções até a pessoa fechá-la (o
fechamento limpa a sessão). Só uma gaveta pode estar aberta por vez: abrir outra ficha de dentro de
uma gaveta pede uma nova execução do app.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from . import cartoes, graficos, metrics, painel, school_data, ui
from . import reconciliation as rc
from .normalization import chave_comparacao, descrever_duracao, eh_vazio
from .security import mascarar_email
from .validators import descrever, gravidade

ABERTA = "_ficha_aberta"

ICONES_INFRA = {
    "IN_AGUA_POTAVEL": "water_drop", "IN_ENERGIA_REDE_PUBLICA": "bolt", "IN_ESGOTO_REDE_PUBLICA": "plumbing",
    "IN_INTERNET": "wifi", "IN_INTERNET_ALUNOS": "devices", "IN_BANDA_LARGA": "speed",
    "IN_BIBLIOTECA_SALA_LEITURA": "local_library", "IN_LABORATORIO_INFORMATICA": "computer",
    "IN_LABORATORIO_CIENCIAS": "science", "IN_QUADRA_ESPORTES": "sports_soccer", "IN_REFEITORIO": "restaurant",
    "IN_COZINHA": "soup_kitchen", "IN_PATIO_COBERTO": "roofing", "IN_BANHEIRO_PNE": "accessible",
    "IN_ALIMENTACAO": "lunch_dining",
}
STATUS_IBGE = {
    "valido": "válido", "ausente": "não informado", "invalido": "formato inválido",
    "uf_divergente": "código de outra UF", "inexistente": "fora da lista oficial do IBGE",
}


def pedir(tipo: str, chave: str, origem: tuple[str, str] | None = None) -> None:
    """Abre a ficha ("escola", "turma" ou "cursista") a partir da próxima execução."""
    st.session_state[ABERTA] = (tipo, chave, origem)


def fechar() -> None:
    st.session_state.pop(ABERTA, None)


def abrir_pendente() -> None:
    aberta = st.session_state.get(ABERTA)
    if not aberta:
        return
    tipo, chave, origem = aberta
    if tipo == "escola":
        _gaveta_escola(chave, origem)
    elif tipo == "turma":
        _gaveta_turma(chave, origem)
    elif tipo == "cursista":
        _gaveta_cursista(chave, origem)


def _trocar_de_ficha(tipo: str, chave: str) -> None:
    """Um clique dentro da gaveta pediu outra ficha (ou fechou esta): nova execução do app para trocá-la."""
    if (st.session_state.get(ABERTA) or (None, None))[:2] != (tipo, chave):
        st.rerun()


@st.dialog("Ficha da escola", width="large", position="right", icon=":material/school:", on_dismiss=fechar)
def _gaveta_escola(chave: str, origem: tuple[str, str] | None = None) -> None:
    _trocar_de_ficha("escola", chave)
    conteudo_escola(painel.contexto(), chave, origem)


@st.dialog("Ficha da turma", width="large", position="right", icon=":material/groups:", on_dismiss=fechar)
def _gaveta_turma(grupo: str, origem: tuple[str, str] | None = None) -> None:
    _trocar_de_ficha("turma", grupo)
    conteudo_turma(painel.contexto(), grupo)


@st.dialog("Ficha do cursista", width="medium", position="right", icon=":material/person:", on_dismiss=fechar)
def _gaveta_cursista(id_registro: str, origem: tuple[str, str] | None = None) -> None:
    _trocar_de_ficha("cursista", id_registro)
    conteudo_cursista(painel.contexto(), id_registro, origem)


def _cores(base) -> dict[str, str]:
    return graficos.cores_faixas(painel.ordem_faixas(base.parametros["faixas_inatividade_dias"]))


def _data(iso, fuso: str) -> str | None:
    if not isinstance(iso, str) or not iso:
        return None
    momento = datetime.fromisoformat(iso)
    return momento.astimezone(ZoneInfo(fuso)).strftime("%d/%m/%Y %H:%M") if momento.tzinfo else momento.strftime("%d/%m/%Y")


def _dia(c) -> str | None:
    """Dia aproximado do último acesso (data da lista menos o tempo informado pela plataforma)."""
    dia = c["acesso_dia"] if "acesso_dia" in c else None
    return f"{dia[8:10]}/{dia[5:7]}/{dia[:4]}" if isinstance(dia, str) and len(dia) == 10 else None


def _voltar(origem: tuple[str, str] | None, base) -> None:
    if not origem:
        return
    tipo, chave = origem
    if tipo == "escola":
        rotulo = "Voltar para a escola"
    elif tipo == "turma":
        identificada = painel.turma(chave)
        rotulo = f"Voltar para a turma {identificada[0]} · T{identificada[1]}" if identificada else "Voltar para a turma"
    else:
        nome = base.cursistas.loc[base.cursistas["id_registro"] == chave, "nome"]
        rotulo = f"Voltar para a ficha de {cartoes.nome_legivel(nome.iloc[0])}" if len(nome) else "Voltar"
    if st.button(rotulo, icon=":material/arrow_back:", type="tertiary", key="ficha_voltar"):
        pedir(tipo, chave)
        st.rerun()


# ---------------------------------------------------------------- ficha da escola


def _numero_atributo(atributos: dict, var: str) -> int | None:
    valor = atributos.get(var)
    try:
        return int(float(valor)) if valor not in (None, "") else None
    except ValueError:
        return None


def conteudo_escola(ctx, chave: str, origem: tuple[str, str] | None = None) -> None:
    base = ctx.base
    escolas = painel.resumo_escolas(base.cursistas)
    linha = escolas[escolas["chave_escola"] == chave]
    if linha.empty:
        ui.vazio("Escola não encontrada na base atual.")
        return
    e = linha.iloc[0]
    localizada = e["situacao_inep"] == school_data.SITUACAO_INEP_LOCALIZADO
    oficial = base.escolas[base.escolas["co_entidade"] == e["inep"]] if localizada else pd.DataFrame()
    dados = oficial.iloc[0] if not oficial.empty else None
    atributos = dados["atributos"] if dados is not None else {}
    ano = (base.meta.get("escolas") or {}).get("referencia_em")

    _voltar(origem, base)
    ui.cabecalho_ficha(
        f"Censo Escolar {ano}" if localizada and ano else "Dados do cadastro (escola sem dados do Inep)",
        cartoes.nome_legivel(e["escola"]),
        [f"INEP {e['inep']}" if pd.notna(e["inep"]) else "Sem código INEP válido",
         f"{e['municipio']} ({e['uf']})" if pd.notna(e["municipio"]) else None,
         dados["dependencia"] if dados is not None else None,
         dados["localizacao"] if dados is not None else None,
         dados["situacao_funcionamento"] if dados is not None else None],
    )

    # Cursistas da escola (todos, independentemente dos filtros da barra lateral)
    da_escola = base.cursistas[painel.chave_escola(base.cursistas) == chave]
    pessoas = painel.pessoas_de(da_escola)
    com_conta, acessaram = int(e["com_conta"]), int(e["acessaram"])
    st.html(cartoes.numeros([
        ("Cursistas", metrics.numero(len(pessoas)), None),
        ("Já acessaram o curso", f"{acessaram} de {com_conta}" if com_conta else "—",
         metrics.percentual(acessaram / com_conta, 0) + " de quem tem conta" if com_conta else "ninguém com conta"),
        ("Nunca acessaram", metrics.numero(int(e["nunca"])), None),
        ("Requerem acompanhamento", metrics.numero(int(e["acompanhamento"])), None),
    ]))

    st.markdown("#### Quem desta escola participa da formação")
    cores = _cores(base)
    ordem = pessoas.sort_values(["prioridade", "dias_sem_acesso", "nome_chave"], ascending=[True, False, True],
                                na_position="last")
    for i, pessoa in enumerate(ordem.itertuples(index=False)):
        ui.clicavel(cartoes.linha_pessoa(pessoa, cores), f"esc_pessoa_{i}",
                    f"Abrir a ficha de {cartoes.nome_legivel(pessoa.nome)}", pedir,
                    ("cursista", pessoa.id_registro, ("escola", chave)))
    if base.tem_atividade:
        ui.nota(f"Clique em uma pessoa para abrir a ficha. {ui.fonte_atividade(base, ctx.cfg.fuso_horario)}")

    if not localizada:
        st.info(f"Esta escola não tem dados oficiais no painel ({str(e['situacao_inep']).lower()}). Confira o código "
                "INEP no cadastro; a lista de pendências fica em Qualidade e conciliação.", icon=":material/info:")
        return

    st.markdown(f"#### Censo Escolar {ano}")
    etapas = [("Educação Infantil", "QT_MAT_INF_INT", "QT_MAT_INF"),
              ("Fundamental – anos iniciais", "QT_MAT_FUND_AI_INT", "QT_MAT_FUND_AI"),
              ("Fundamental – anos finais", "QT_MAT_FUND_AF_INT", "QT_MAT_FUND_AF"),
              ("Ensino Médio", "QT_MAT_MED_INT", "QT_MAT_MED")]
    itens = [(rotulo, _numero_atributo(atributos, parte) or 0, _numero_atributo(atributos, total))
             for rotulo, parte, total in etapas if _numero_atributo(atributos, total)]
    complementares = [("Matrículas", _numero_atributo(atributos, "QT_MAT_BAS")),
                      ("Em tempo integral", _numero_atributo(atributos, "QT_MAT_BAS_INT")),
                      ("Docentes", _numero_atributo(atributos, "QT_DOC_BAS")),
                      ("Turmas", _numero_atributo(atributos, "QT_TUR_BAS"))]
    st.html(cartoes.numeros([(r, metrics.numero(v), None) for r, v in complementares if v is not None]))
    if itens:
        fig = graficos.proporcoes(itens, "Matrículas em tempo integral por etapa",
                                  f"Declaradas ao Censo Escolar {ano}", "tempo integral")
        ui.grafico(fig, None, None, school_data.DEFINICAO_TEMPO_INTEGRAL)

    st.markdown("#### Infraestrutura declarada ao Censo")
    st.html(cartoes.infraestrutura([(ICONES_INFRA.get(var, "check"), rotulo, atributos.get(var))
                                    for var, rotulo in school_data.INFRAESTRUTURA if var in atributos]))

    with st.expander("Dados cadastrais do Inep"):
        pares = [
            ("Nome oficial", dados["no_entidade"]), ("Código INEP", e["inep"]),
            ("Município", f"{dados['no_municipio']} ({dados['sg_uf']})"),
            ("Dependência administrativa", dados["dependencia"]), ("Categoria", dados["categoria_administrativa"]),
            ("Localização", dados["localizacao"]), ("Localização diferenciada", dados["localizacao_diferenciada"]),
            ("Situação de funcionamento", dados["situacao_funcionamento"]), ("Etapas ofertadas", dados["etapas"]),
            ("Salas de aula utilizadas", metrics.numero(_numero_atributo(atributos, "QT_SALAS_UTILIZADAS"))
             if _numero_atributo(atributos, "QT_SALAS_UTILIZADAS") is not None else None),
        ]
        if chave_comparacao(e["escola_informada"]) != chave_comparacao(dados["no_entidade"]):
            pares.append(("Nome informado no cadastro", e["escola_informada"]))
        ui.lista_definicoes(pares)
    ui.nota(f"{ui.fonte_escolas(base)} {school_data.AVISO_PROGRAMA}")


# ---------------------------------------------------------------- ficha da turma


def conteudo_turma(ctx, grupo: str) -> None:
    base = ctx.base
    parametros = base.parametros
    janela, limite = parametros["janela_acesso_recente_dias"], parametros["limite_acompanhamento_dias"]
    # Todas as contas da turma, independentemente dos filtros da barra lateral (como na ficha da escola)
    resumo = painel.resumo_turmas(base.contas, janela, limite)
    linha = resumo[resumo["grupo"] == grupo]
    if linha.empty:
        ui.vazio("Turma não encontrada na base atual.")
        return
    t = linha.iloc[0]
    equipe = [f"{papel}: {n}" for papel, n in sorted(t["equipe"].items())]
    ui.cabecalho_ficha("Turma da plataforma de formação", t["rotulo"], [f"Grupo “{grupo}”", *equipe])
    st.html(cartoes.numeros([
        ("Estudantes", metrics.numero(t["estudantes"]), None),
        ("Já acessaram o curso", f"{t['acessaram']} de {t['estudantes']}",
         f"{metrics.percentual(t['taxa_acesso'], 0)} da turma"),
        (f"Acessaram nos últimos {janela} dias", metrics.numero(t["recentes"]), None),
        ("Nunca acessaram", metrics.numero(t["nunca"]), None),
        (f"Sem acesso há mais de {limite} dias", metrics.numero(t["inativos"]), None),
    ]))
    cores = _cores(base)
    st.html(cartoes.pontos(t["faixas"], cores, limite=60))

    da_turma = base.cursistas[base.cursistas["lista_grupos"].map(lambda grupos: grupo in grupos)]
    pessoas = painel.pessoas_de(da_turma).sort_values(["prioridade", "dias_sem_acesso", "nome_chave"],
                                                     ascending=[True, False, True], na_position="last")
    atencao = pessoas[pessoas["requer_acompanhamento"]]
    em_dia = pessoas[~pessoas["requer_acompanhamento"]]
    st.markdown(f"#### Precisam de atenção ({metrics.numero(len(atencao))})")
    if atencao.empty:
        ui.vazio("Ninguém desta turma está sem acesso há mais do que o limite de acompanhamento.")
    for i, pessoa in enumerate(atencao.itertuples(index=False)):
        ui.clicavel(cartoes.linha_pessoa(pessoa, cores), f"turma_atencao_{i}",
                    f"Abrir a ficha de {cartoes.nome_legivel(pessoa.nome)}", pedir,
                    ("cursista", pessoa.id_registro, ("turma", grupo)))
    if not em_dia.empty:
        with st.expander(f"Com acesso em dia ({metrics.numero(len(em_dia))})"):
            for i, pessoa in enumerate(em_dia.itertuples(index=False)):
                ui.clicavel(cartoes.linha_pessoa(pessoa, cores), f"turma_em_dia_{i}",
                            f"Abrir a ficha de {cartoes.nome_legivel(pessoa.nome)}", pedir,
                            ("cursista", pessoa.id_registro, ("turma", grupo)))
    sem_cadastro = base.contas[(base.contas["eh_cursista"] == 1) & (base.contas["status_conciliacao"] != rc.CORRESPONDENTE)
                               & base.contas["lista_grupos"].map(lambda grupos: grupo in grupos)]
    if not sem_cadastro.empty:
        st.markdown(f"#### Estudantes sem registro conciliado no cadastro ({metrics.numero(len(sem_cadastro))})")
        for conta in sem_cadastro.itertuples(index=False):
            st.html(cartoes.linha_conta(conta))
    ui.nota(f"Critérios operacionais configuráveis; não indicam evasão ou desistência. "
            f"{ui.fonte_atividade(base, ctx.cfg.fuso_horario)}")


# ---------------------------------------------------------------- ficha do cursista


def _passos(c, base, fuso: str) -> list[tuple[str, str, str]]:
    resposta = _data(c["data_resposta"], fuso)
    situacao = c["situacao"] if not eh_vazio(c["situacao"]) else "Situação não informada"
    passos = [("ok" if situacao == "Aceitou" else "atencao", "Inscrição",
               f"{situacao}" + (f" · resposta em {resposta}" if resposta else ""))]
    if not base.tem_atividade:
        return passos + [("pendente", "Plataforma de formação", "Exportação da plataforma não encontrada na pasta")]
    status = c["status_conciliacao"]
    if status == rc.CORRESPONDENTE:
        conta = f"Conta encontrada ({str(c['regra_conciliacao']).lower()})" if not eh_vazio(c["regra_conciliacao"]) else "Conta encontrada"
        if not eh_vazio(c["situacao_conta"]) and not c["conta_ativa"]:
            passos.append(("atencao", "Conta na plataforma", f"{conta}, mas com situação “{c['situacao_conta']}”"))
        else:
            passos.append(("ok", "Conta na plataforma", conta))
    elif status in (rc.PENDENTE, rc.AMBIGUO):
        return passos + [("atencao", "Conta na plataforma", "Em conciliação: aguarda revisão em Qualidade e conciliação")]
    else:
        return passos + [("pendente", "Conta na plataforma", "Nenhuma conta encontrada com o e-mail do cadastro")]

    if c["acesso_tipo"] == "nunca":
        return passos + [("atencao", "Acesso ao curso", "Ainda não acessou o curso")]
    if c["acesso_tipo"] not in ("relativo", "absoluto"):
        return passos + [("pendente", "Acesso ao curso", "Último acesso não interpretado")]
    passos.append(("ok", "Acesso ao curso", "Já acessou o curso"))
    limite = base.parametros["limite_acompanhamento_dias"]
    tempo = descrever_duracao(c["acesso_segundos"])
    dia = _dia(c)
    quando = f"Há {tempo}" + (f" · por volta de {dia}" if dia else "")
    if c["dias_sem_acesso"] > limite:
        passos.append(("atencao", "Último acesso", f"{quando}: acima do limite de {limite} dias"))
    else:
        passos.append(("ok", "Último acesso", quando))
    return passos


def conteudo_cursista(ctx, id_registro: str, origem: tuple[str, str] | None = None) -> None:
    base, fuso = ctx.base, ctx.cfg.fuso_horario
    registro = base.cursistas[base.cursistas["id_registro"] == id_registro]
    if registro.empty:
        ui.vazio("Registro não encontrado na base atual.")
        return
    c = registro.iloc[0]
    pessoa = next(registro.itertuples(index=False))
    cores = _cores(base)

    _voltar(origem, base)
    texto, cor = cartoes.situacao(pessoa, cores)
    municipio = c["municipio_escola"] if not eh_vazio(c["municipio_escola"]) else c["ente"]
    subtitulo = " · ".join(str(x) for x in (c["cargo_funcao"], f"{municipio} ({c['uf']})" if not eh_vazio(municipio) else None)
                           if not eh_vazio(x))
    etiquetas = cartoes.etiqueta(texto, cor)
    if cartoes.turma_legivel(pessoa):
        etiquetas += cartoes.etiqueta(f"Turma {cartoes.turma_legivel(pessoa)}")
    if pessoa.requer_acompanhamento:
        etiquetas += cartoes.alerta("Requer acompanhamento")
    st.html(cartoes.cabecalho_pessoa(c["nome"], cor, subtitulo, etiquetas))

    st.markdown("#### Participação na formação")
    st.html(cartoes.jornada(_passos(c, base, fuso)))
    if base.tem_atividade:
        ui.nota(f"Tempo sem acesso medido na data de referência da base de atividade. "
                f"{ui.fonte_atividade(base, fuso)} O último acesso não informa frequência, conclusão nem desempenho.")

    motivos = c["motivos"] or []
    problemas = [p for p in (c["problemas"] or []) if gravidade(p) != "informativo"]
    if motivos or problemas:
        itens = "".join(f"<li>{cartoes._e(m)}</li>" for m in motivos)
        itens += "".join(f"<li>Dado a verificar: {cartoes._e(descrever(p))}</li>" for p in problemas)
        st.html(f'<div class="eti-aviso"><div class="eti-aviso-titulo">Pontos de atenção</div><ul>{itens}</ul>'
                '<p>Critérios operacionais configuráveis; não indicam evasão ou desistência.</p></div>')

    st.markdown("#### Escola")
    escola = c["escola_oficial"] if not eh_vazio(c["escola_oficial"]) else c["escola"]
    chave = painel.chave_escola(registro).iloc[0]
    detalhe = " · ".join(str(x) for x in (f"INEP {c['inep']}" if not eh_vazio(c["inep"]) else "Sem código INEP",
                                          c["municipio_escola"], c["dependencia"], c["localizacao"]) if not eh_vazio(x))
    ui.clicavel(
        f'<div class="eti-cartao eti-cartao-mini"><span class="eti-icone eti-icone-g" aria-hidden="true">school</span>'
        f'<div class="eti-cartao-id"><div class="eti-cartao-titulo">{cartoes._e(cartoes.nome_legivel(escola))}</div>'
        f'<div class="eti-cartao-sub">{cartoes._e(detalhe)}</div></div>'
        '<span class="eti-icone eti-seta" aria-hidden="true">chevron_right</span></div>',
        "cursista_escola", "Abrir a ficha da escola", pedir, ("escola", chave, ("cursista", id_registro)),
    )

    st.markdown("#### Detalhes")
    with st.expander("Inscrição e vínculo"):
        outros = base.cursistas[(base.cursistas["chave_pessoa"] == c["chave_pessoa"]) & (base.cursistas["id_registro"] != id_registro)]
        ui.lista_definicoes([
            ("Nome no cadastro", c["nome"]), ("Registro no painel", c["id_registro"]),
            ("Identificação da pessoa", {"cpf": "CPF (pseudonimizado)", "email": "E-mail (pseudonimizado)",
                                         "nome": "Nome e ente (sem CPF ou e-mail válidos)"}.get(c["tipo_chave"])),
            ("Outros registros da mesma pessoa", len(outros) or "Nenhum"),
            ("Ciclo", c["ciclo"]), ("Tipo", c["tipo"]), ("Origem da vaga", c["origem"]),
            ("Situação cadastral", c["situacao"]), ("Data de resposta", _data(c["data_resposta"], fuso)),
            ("Cargo/função", c["cargo_funcao"]), ("Escolaridade", c["escolaridade"]),
            ("Região", c["regiao"]), ("UF", c["uf"]), ("Ente", c["ente"]), ("Esfera", c["esfera"]),
            ("Código IBGE", f"{ui.texto_valor(c['cod_ibge'])} ({STATUS_IBGE.get(c['cod_ibge_status'], c['cod_ibge_status'])})"),
            ("Articulador", c["articulador"]),
            ("Escola informada", c["escola"]), ("Situação do código INEP", c["situacao_inep"]),
        ])
    if base.tem_atividade:
        with st.expander("Plataforma de formação"):
            pares = [("Conciliação", c["status_conciliacao"]), ("Regra aplicada", c["regra_conciliacao"])]
            if pd.notna(c["id_conta"]):
                dia = _dia(c)
                pares += [
                    ("Nome na plataforma", c["conta_nome"]), ("Papel", c["papeis"]), ("Grupo(s)", c["grupo"]),
                    ("Situação da conta", c["situacao_conta"]),
                    ("Último acesso (como exportado)", c["ultimo_acesso_texto"]),
                    ("Faixa", c["faixa_acesso"]),
                    ("Dia aproximado do último acesso",
                     f"{dia} (data da lista menos o tempo informado pela plataforma)" if dia
                     else "não calculado sem a data da lista" if c["acesso_tipo"] == "relativo" else None),
                ]
            ui.lista_definicoes(pares)
    with st.expander("Origem dos dados"):
        meta_cad, meta_atv = base.meta.get("cadastro") or {}, base.meta.get("atividade") or {}
        decisoes = base.decisoes[base.decisoes["chave_pessoa"] == c["chave_pessoa"]] if not base.decisoes.empty else pd.DataFrame()
        ui.lista_definicoes([
            ("Arquivo e linha de origem", f"{c['arquivo_origem']}, linha {c['linha_origem']}"),
            ("Importação do cadastro", f"nº {meta_cad.get('id')} em {_data(meta_cad.get('importado_em'), fuso)} por {meta_cad.get('importado_por')}"),
            ("Importação da atividade", f"nº {meta_atv.get('id')} em {_data(meta_atv.get('importado_em'), fuso)}" if meta_atv else None),
            ("Referência da atividade", meta_atv.get("referencia_descricao")),
            ("Decisões manuais de conciliação", "; ".join(
                f"{d.decisao} em {_data(d.decidido_em, fuso)} por {d.decidido_por}" for d in decisoes.itertuples()) or "Nenhuma"),
        ])
    with st.expander("Dados pessoais e de contato"):
        if ctx.cfg.ambiente == "publicacao":
            ui.nota("Os dados de contato não fazem parte da versão publicada do painel.")
            return
        if not ctx.usuario.acesso_contatos:
            ui.nota("Restritos a usuários com autorização para contato. Solicite à coordenação geral, se necessário.")
            return
        exibir = bool(st.session_state.get(f"contato_{id_registro}"))
        if not exibir:
            # Sem nova execução: a gaveta pode estar sendo desenhada numa execução completa do app
            area = st.empty()
            with area.container():
                ui.nota(f"E-mail: {mascarar_email(c['email'])}. Exiba os dados completos apenas se houver necessidade operacional.")
                clicou = st.button("Exibir dados de contato", key=f"btn_contato_{id_registro}")
            if clicou:
                ctx.repo.auditar(ctx.usuario.identificador, "exibiu_dados_contato", c["chave_pessoa"])
                st.session_state[f"contato_{id_registro}"] = True
                area.empty()
                exibir = True
        if exibir:
            ui.lista_definicoes([
                ("E-mail", c["email"]), ("Telefone", c["telefone"]), ("WhatsApp", c["whatsapp"]),
                ("Raça/cor (declarada)", c["raca_cor"]), ("Gênero (declarado)", c["genero"]),
            ])
            ui.nota("Use apenas para a finalidade da formação. A consulta foi registrada na auditoria.")
