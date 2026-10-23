"""Cartões em HTML das galerias (cursistas e escolas) e peças visuais das fichas.

As cores de situação são as mesmas dos gráficos (faixas de acesso em verde-petróleo, cinzas para
quem nunca acessou ou não tem conta). Os nomes em caixa alta são exibidos em caixa de título, só na
tela; o valor original continua na ficha.
"""

from __future__ import annotations

import html
import math
import re
from collections import Counter

from . import graficos, metrics, painel, school_data
from . import reconciliation as rc
from .normalization import eh_vazio

PARTICULAS = {"a", "à", "ao", "aos", "as", "com", "da", "das", "de", "do", "dos", "e", "em", "na", "nas", "no",
              "nos", "o", "os", "para", "pela", "pelo", "por"}
# Siglas comuns em nomes de escolas e instituições (ficam em caixa alta)
SIGLAS = {
    "APAE", "CAIC", "CE", "CEB", "CEEJA", "CEF", "CEI", "CEJA", "CEMEI", "CEPI", "CETI", "CIEP", "CMEF", "CMEI",
    "CRAS", "EB", "EE", "EEB", "EEEF", "EEEFM", "EEEM", "EEF", "EEFM", "EEIEF", "EEM", "EETEPA", "EF", "EJA", "EM",
    "EMEB", "EMEF", "EMEFM", "EMEI", "EMEIEF", "EMEIF", "EMF", "EMI", "ETE", "ETEC", "IFAC", "IFAM", "IFAP", "IFPA",
    "IFRO", "IFRR", "IFTO", "NAEE", "NEI", "SEDUC", "SEMED", "SENAC", "SENAI", "SESC", "SESI", "UE", "UEA", "UEE",
    "UEF", "UEI", "UEPA", "UES", "UFAM", "UFPA", "UMEF", "UMEI", "UMEIF",
}
_ROMANO = re.compile(r"^(?=[IVXLC])(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$")
_ICONE = '<span class="eti-icone" aria-hidden="true">{}</span>'


def _e(texto) -> str:
    return html.escape(str(texto))


def nome_legivel(texto) -> str:
    """Nome em caixa alta passa para caixa de título, só na tela: partículas ("da", "de", "e"…) em minúsculas,
    siglas e algarismos romanos mantidos; as letras não mudam. Texto em caixa mista fica como está."""
    if eh_vazio(texto):
        return "—"
    texto = " ".join(str(texto).split())
    if not texto.isupper():
        return texto
    palavras = []
    for i, palavra in enumerate(texto.split(" ")):
        nucleo = palavra.strip(".,;:()–-/\"'")
        if nucleo in SIGLAS or _ROMANO.match(nucleo) or any(c.isdigit() for c in nucleo) or "." in nucleo:
            palavras.append(palavra)
        elif i > 0 and palavra.lower() in PARTICULAS:
            palavras.append(palavra.lower())
        else:
            palavras.append("-".join(p[:1] + p[1:].lower() for p in palavra.split("-")))
    return " ".join(palavras)


def iniciais(nome) -> str:
    partes = [p for p in str(nome or "").split() if p.lower() not in PARTICULAS and p[:1].isalpha()]
    if not partes:
        return "?"
    return (partes[0][0] + (partes[-1][0] if len(partes) > 1 else "")).upper()


def tempo_desde(segundos) -> str | None:
    """Tempo relativo curto: "há 5 horas", "há 3 dias"."""
    if segundos is None or (isinstance(segundos, float) and math.isnan(segundos)):
        return None
    if segundos < 3600:
        return "há menos de 1 hora"
    if segundos < 86400:
        horas = int(segundos // 3600)
        return f"há {horas} hora{'s' if horas > 1 else ''}"
    dias = int(segundos // 86400)
    return f"há {dias} dia{'s' if dias > 1 else ''}"


# ---------------------------------------------------------------- situação de uma pessoa


def dia_curto(dia) -> str | None:
    """"2026-10-18" -> "18/10" (dia do último acesso, quando a lista tem data de referência)."""
    if not isinstance(dia, str) or len(dia) != 10:
        return None
    return f"{dia[8:10]}/{dia[5:7]}"


def situacao(pessoa, cores: dict[str, str]) -> tuple[str, str]:
    """(texto, cor) da situação na plataforma, para avatar e etiqueta."""
    faixa = pessoa.faixa_acesso
    cor = cores.get(faixa, graficos.CINZA_SEM_CONTA)
    if pessoa.acesso_tipo in ("relativo", "absoluto"):
        dia = dia_curto(getattr(pessoa, "acesso_dia", None))
        return f"Último acesso {tempo_desde(pessoa.acesso_segundos) or ''}".strip() + (f" ({dia})" if dia else ""), cor
    if pessoa.acesso_tipo == "nunca":
        return "Nunca acessou", cor
    if pessoa.status_conciliacao in (rc.PENDENTE, rc.AMBIGUO):
        return "Conta em conciliação", cor
    if faixa == painel.FAIXA_SEM_CONTA:
        return "Sem conta na plataforma", cor
    return str(faixa), cor


def avatar(nome, cor: str, classe: str = "") -> str:
    return (f'<span class="eti-avatar {classe}" style="background:{cor};color:{graficos.cor_texto_sobre(cor)}" '
            f'aria-hidden="true">{_e(iniciais(nome))}</span>')


def etiqueta(texto: str, cor: str | None = None) -> str:
    ponto = f'<i style="background:{cor}"></i>' if cor else ""
    return f'<span class="eti-etiqueta">{ponto}{_e(texto)}</span>'


def alerta(texto: str) -> str:
    return f'<span class="eti-etiqueta eti-etiqueta-alerta">{_e(texto)}</span>'


def _municipio(pessoa) -> str | None:
    municipio = pessoa.municipio_escola if not eh_vazio(pessoa.municipio_escola) else pessoa.ente
    if eh_vazio(municipio):
        return pessoa.uf if not eh_vazio(pessoa.uf) else None
    return f"{municipio} ({pessoa.uf})" if not eh_vazio(pessoa.uf) else str(municipio)


def turma_legivel(pessoa) -> str | None:
    grupos = pessoa.lista_grupos if isinstance(pessoa.lista_grupos, list) else []
    textos = []
    for grupo in grupos:
        identificada = painel.turma(grupo)
        textos.append(f"{identificada[0]} · T{identificada[1]}" if identificada else grupo)
    return ", ".join(textos) or None


# Motivos que a etiqueta de situação já diz ("Nunca acessou", "Sem conta na plataforma", "Último acesso há…")
_MOTIVOS_IMPLICITOS = {painel.MOTIVO_NUNCA, painel.MOTIVO_SEM_CONTA, painel.MOTIVO_INATIVIDADE, painel.MOTIVO_CONCILIACAO}


def motivo_curto(pessoa) -> str | None:
    """Motivo de acompanhamento que a etiqueta de situação não mostra (ex.: conta não ativa)."""
    motivos = pessoa.motivos if isinstance(pessoa.motivos, list) else []
    extras = [m for m in motivos if m not in _MOTIVOS_IMPLICITOS]
    return extras[0] if extras and pessoa.requer_acompanhamento else None


def bandeira(pessoa) -> str:
    """Marca de acompanhamento, com os motivos na dica."""
    if not pessoa.requer_acompanhamento:
        return ""
    motivos = pessoa.motivos if isinstance(pessoa.motivos, list) else []
    return (f'<span class="eti-bandeira" title="{_e("; ".join(motivos))}">'
            f'<span class="eti-icone" aria-hidden="true">flag</span>Acompanhar</span>')


def cartao_pessoa(pessoa, cores: dict[str, str]) -> str:
    texto, cor = situacao(pessoa, cores)
    escola = pessoa.escola_oficial if not eh_vazio(pessoa.escola_oficial) else pessoa.escola
    local = " · ".join(x for x in (_municipio(pessoa), turma_legivel(pessoa)) if x)
    motivo = motivo_curto(pessoa)
    linhas = ""
    if not eh_vazio(escola):
        linhas += f'<div class="eti-cartao-linha">{_ICONE.format("school")}<span>{_e(nome_legivel(escola))}</span></div>'
    if local:
        linhas += (f'<div class="eti-cartao-linha eti-1linha">{_ICONE.format("location_on")}'
                   f'<span>{_e(local)}</span></div>')
    return (
        '<div class="eti-cartao eti-cartao-pessoa">'
        f'<div class="eti-cartao-topo">{avatar(pessoa.nome, cor)}<div class="eti-cartao-id">'
        f'<div class="eti-cartao-titulo">{_e(nome_legivel(pessoa.nome))}</div>'
        f'<div class="eti-cartao-sub">{_e(pessoa.cargo_funcao if not eh_vazio(pessoa.cargo_funcao) else "Cargo não informado")}</div>'
        f'</div></div><div class="eti-cartao-linhas">{linhas}</div>'
        f'<div class="eti-cartao-rodape">{etiqueta(texto, cor)}{alerta(motivo) if motivo else ""}{bandeira(pessoa)}</div></div>'
    )


def linha_pessoa(pessoa, cores: dict[str, str]) -> str:
    """Versão compacta do cartão, para a lista de cursistas dentro da ficha da escola."""
    texto, cor = situacao(pessoa, cores)
    motivo = motivo_curto(pessoa)
    return (
        f'<div class="eti-linha-pessoa">{avatar(pessoa.nome, cor, "eti-avatar-p")}'
        f'<div class="eti-cartao-id"><div class="eti-cartao-titulo">{_e(nome_legivel(pessoa.nome))}</div>'
        f'<div class="eti-cartao-sub">{_e(pessoa.cargo_funcao if not eh_vazio(pessoa.cargo_funcao) else "Cargo não informado")}'
        f'{" · " + _e(turma_legivel(pessoa)) if turma_legivel(pessoa) else ""}</div></div>'
        f'<div class="eti-linha-situacao">{etiqueta(texto, cor)}{alerta(motivo) if motivo else ""}{bandeira(pessoa)}</div>'
        f'<span class="eti-icone eti-seta" aria-hidden="true">chevron_right</span></div>'
    )


# ---------------------------------------------------------------- escolas

SITUACOES_ESCOLA = ("Todos já acessaram", "Parte ainda não acessou", "Ninguém acessou ainda", "Sem cursistas na plataforma")


def situacao_escola(com_conta: int, acessaram: int) -> str:
    if not com_conta:
        return SITUACOES_ESCOLA[3]
    if acessaram >= com_conta:
        return SITUACOES_ESCOLA[0]
    return SITUACOES_ESCOLA[2] if not acessaram else SITUACOES_ESCOLA[1]


def pontos(faixas: list[str], cores: dict[str, str], limite: int = 28) -> str:
    """Um ponto por cursista, na cor da sua situação de acesso (dos mais recentes aos sem conta).

    Acima de ``limite`` pessoas, os pontos ficam proporcionais (cada situação presente mantém ao menos um).
    """
    ordem = {f: i for i, f in enumerate(cores)}
    grupos = sorted(Counter(faixas).items(), key=lambda par: ordem.get(par[0], len(ordem)))
    total, escala = len(faixas), ""
    if total > limite:
        cotas = [max(1, round(n * limite / total)) for _, n in grupos]
        while sum(cotas) > limite:
            cotas[cotas.index(max(cotas))] -= 1
        while sum(cotas) < limite:
            cotas[max(range(len(grupos)), key=lambda i: grupos[i][1])] += 1
        escala = f"<span>1 ponto ≈ {total / limite:.1f} pessoas</span>".replace(".", ",")
    else:
        cotas = [n for _, n in grupos]
    visiveis = "".join(f'<i style="background:{cores.get(f, graficos.CINZA_SEM_CONTA)}" title="{_e(f)}: {n}"></i>' * cota
                       for (f, n), cota in zip(grupos, cotas))
    return f'<div class="eti-pontos" role="img" aria-label="{total} cursistas">{visiveis}{escala}</div>'


def cartao_escola(escola, faixas: list[str], cores: dict[str, str], com_local: bool = True) -> str:
    local = " · ".join(x for x in (escola.municipio if not eh_vazio(escola.municipio) else None,
                                   escola.uf if not eh_vazio(escola.uf) else None) if x)
    detalhes = " · ".join(str(x) for x in (escola.dependencia, escola.localizacao) if not eh_vazio(x))
    if escola.situacao_inep != school_data.SITUACAO_INEP_LOCALIZADO:
        detalhes = " · ".join(x for x in (detalhes, "Sem dados do Inep") if x)
    com_conta, acessaram, nunca = int(escola.com_conta), int(escola.acessaram), int(escola.nunca)
    fracao = acessaram / com_conta if com_conta else 0
    pessoas = int(escola.pessoas)
    if com_conta:
        resumo = f"<b>{acessaram} de {com_conta}</b> já acessaram"
    else:
        resumo = "Ninguém com conta na plataforma"
    chamada = (f'<div class="eti-cartao-chamada">{_ICONE.format("location_on")}{_e(local or "Município não identificado")}</div>'
               if com_local else "")
    return (
        f'<div class="eti-cartao eti-cartao-escola">{chamada}'
        f'<div class="eti-cartao-titulo eti-4linhas">{_e(nome_legivel(escola.escola))}</div>'
        f'<div class="eti-cartao-sub">{_e(detalhes)}</div>'
        f'<div class="eti-cartao-meio"><div class="eti-cartao-contagem">{pessoas} cursista{"s" if pessoas != 1 else ""}</div>'
        f'{pontos(faixas, cores)}</div>'
        f'<div class="eti-progresso" title="{_e(f"{acessaram} de {com_conta} com conta já acessaram")}">'
        f'<div style="width:{fracao * 100:.1f}%"></div></div>'
        f'<div class="eti-cartao-rodape"><span class="eti-cartao-resumo">{resumo}</span>'
        f'{alerta(f"{nunca} nunca acess" + ("aram" if nunca > 1 else "ou")) if nunca else ""}</div></div>'
    )


def cartao_turma(turma, cores: dict[str, str], limite: int) -> str:
    """Cartão de uma turma da plataforma: estudantes, quem já entrou e quem precisa de atenção."""
    estudantes, acessaram = int(turma.estudantes), int(turma.acessaram)
    fracao = acessaram / estudantes if estudantes else 0
    estado = turma.estado if not eh_vazio(turma.estado) else "Turma da plataforma"
    titulo = f"Turma {turma.numero}" if not eh_vazio(turma.numero) else turma.grupo
    alertas = ""
    if turma.nunca:
        alertas += alerta(f"{turma.nunca} nunca acess" + ("aram" if turma.nunca > 1 else "ou"))
    if turma.inativos:
        alertas += alerta(f"{turma.inativos} há mais de {limite} dias")
    return (
        f'<div class="eti-cartao eti-cartao-turma"><div class="eti-cartao-chamada">{_ICONE.format("groups")}'
        f'{_e(estado)}</div><div class="eti-cartao-titulo">{_e(titulo)}</div>'
        f'<div class="eti-cartao-sub">Grupo “{_e(turma.grupo)}” na plataforma</div>'
        f'<div class="eti-cartao-meio"><div class="eti-cartao-contagem">{estudantes} estudante{"s" if estudantes != 1 else ""}'
        f'</div>{pontos(turma.faixas, cores, limite=60)}</div>'
        f'<div class="eti-progresso" title="{_e(f"{acessaram} de {estudantes} já acessaram")}">'
        f'<div style="width:{fracao * 100:.1f}%"></div></div>'
        f'<div class="eti-cartao-rodape"><span class="eti-cartao-resumo"><b>{acessaram} de {estudantes}</b> já acessaram'
        f'</span>{alertas}</div></div>'
    )


def _email_legivel(texto) -> str | None:
    """E-mail (parcial ou completo) para exibir; None quando só restaria a máscara (na versão publicada os e-mails
    viram códigos e a máscara mostraria apenas "•••")."""
    return texto if isinstance(texto, str) and "@" in texto else None


def linha_conta(conta) -> str:
    """Conta da plataforma sem registro no cadastro (nome como está na plataforma; e-mail parcial)."""
    from .security import mascarar_email

    partes = [conta.papeis if not eh_vazio(conta.papeis) else "Sem papel", turma_legivel(conta) or "Sem turma",
              _email_legivel(mascarar_email(conta.email))]
    acesso = conta.ultimo_acesso_texto if not eh_vazio(conta.ultimo_acesso_texto) else "não informado"
    return (
        f'<div class="eti-linha-pessoa eti-linha-conta">{avatar(conta.nome_completo, graficos.CINZA_SEM_CONTA, "eti-avatar-p")}'
        f'<div class="eti-cartao-id"><div class="eti-cartao-titulo">{_e(nome_legivel(conta.nome_completo))}</div>'
        f'<div class="eti-cartao-sub">{_e(" · ".join(p for p in partes if p))}</div></div>'
        f'<div class="eti-linha-situacao">{etiqueta(f"Último acesso: {acesso}")}</div></div>'
    )


def linha_municipio(municipio: str, dados, cor_barra: str = graficos.CALOR_MAX) -> str:
    """Linha do ranking de municípios: cursistas, escolas, barra de acesso e quem nunca acessou."""
    com_conta, acessaram, nunca = int(dados.com_conta), int(dados.acessaram), int(dados.nunca)
    fracao = acessaram / com_conta if com_conta else 0
    resumo = f"<b>{acessaram} de {com_conta}</b> já acessaram" if com_conta else "Ninguém com conta na plataforma"
    pessoas, escolas = int(dados.pessoas), int(dados.escolas)
    return (
        f'<div class="eti-linha-municipio"><div class="eti-cartao-id"><div class="eti-cartao-titulo">{_e(municipio)}</div>'
        f'<div class="eti-cartao-sub">{pessoas} cursista{"s" if pessoas != 1 else ""} · '
        f'{escolas} escola{"s" if escolas != 1 else ""}</div></div>'
        f'<div class="eti-linha-municipio-acesso"><div class="eti-progresso"><div style="width:{fracao * 100:.1f}%;'
        f'background:{cor_barra}"></div></div><span class="eti-cartao-resumo">{resumo}</span></div>'
        f'<div class="eti-linha-situacao">{alerta(f"{nunca} nunca acess" + ("aram" if nunca > 1 else "ou")) if nunca else ""}'
        f'</div><span class="eti-icone eti-seta" aria-hidden="true">chevron_right</span></div>'
    )


def linha_pendencia(pessoa, problemas: list[str], cores: dict[str, str]) -> str:
    """Registro com dado a corrigir na fonte: pessoa, escola informada e os problemas encontrados."""
    _, cor = situacao(pessoa, cores)
    local = " · ".join(x for x in (_municipio(pessoa), nome_legivel(pessoa.escola) if not eh_vazio(pessoa.escola) else None)
                       if x)
    chips = "".join(alerta(p) for p in problemas)
    return (
        f'<div class="eti-linha-pessoa">{avatar(pessoa.nome, cor, "eti-avatar-p")}'
        f'<div class="eti-cartao-id"><div class="eti-cartao-titulo">{_e(nome_legivel(pessoa.nome))}</div>'
        f'<div class="eti-cartao-sub">{_e(local or "Sem ente e escola")} · {_e(pessoa.arquivo_origem)}, linha '
        f'{_e(pessoa.linha_origem)}</div></div><div class="eti-linha-situacao">{chips}</div>'
        f'<span class="eti-icone eti-seta" aria-hidden="true">chevron_right</span></div>'
    )


ICONES_FONTE = {"cadastro": "badge", "atividade": "school", "escolas": "domain"}
ROTULOS_FONTE = {"cadastro": "Cadastro dos cursistas", "atividade": "Lista da plataforma",
                 "escolas": "Base escolar do Inep"}


def importacao(imp, quando: str, arquivos: str) -> str:
    """Item da linha do tempo das importações (uma por versão de cada base)."""
    ativa = imp.status == "ativa"
    situacao_texto = "em uso" if ativa else str(imp.status)
    registros = f"{metrics.numero(imp.n_registros)} registros"
    if imp.n_com_problemas:
        registros += f" · {metrics.numero(imp.n_com_problemas)} com problemas"
    if imp.n_duplicados:
        registros += f" · {metrics.numero(imp.n_duplicados)} em duplicidade"
    return (
        f'<li class="eti-importacao{" eti-importacao-ativa" if ativa else ""}">'
        f'<span class="eti-importacao-marca" aria-hidden="true">{_ICONE.format(ICONES_FONTE.get(imp.fonte, "description"))}</span>'
        f'<div><div class="eti-importacao-titulo">{_e(ROTULOS_FONTE.get(imp.fonte, imp.fonte))} '
        f'{etiqueta(situacao_texto, graficos.PETROLEO[0] if ativa else graficos.CINZA_NUNCA)}</div>'
        f'<div class="eti-importacao-detalhe">Nº {_e(imp.id)} · {_e(quando)} · {_e(imp.importado_por)} · {_e(registros)}</div>'
        + (f'<div class="eti-importacao-detalhe">{_e(imp.referencia_descricao)}</div>'
           if not eh_vazio(imp.referencia_descricao) else "")
        + f'<div class="eti-importacao-arquivos">{_ICONE.format("description")}{_e(arquivos)}</div></div></li>'
    )


# ---------------------------------------------------------------- destaques e verificações


def destaque(icone: str, valor: str, titulo: str, texto: str, com_seta: bool = True) -> str:
    """Cartão de destaque da Visão geral: ícone, número grande, o que ele conta e a população de referência."""
    seta = '<span class="eti-icone eti-seta" aria-hidden="true">arrow_forward</span>' if com_seta else ""
    return (
        f'<div class="eti-destaque"><span class="eti-destaque-icone" aria-hidden="true">{_ICONE.format(_e(icone))}</span>'
        f'<div class="eti-destaque-valor">{_e(valor)}</div><div class="eti-destaque-titulo">{_e(titulo)}</div>'
        f'<p class="eti-destaque-texto">{_e(texto)}</p>{seta}</div>'
    )


ESTADOS_VERIFICACAO = {"ok": "check", "atencao": "priority_high", "info": "info"}


def verificacao(estado: str, titulo: str, valor: str, detalhe: str | None = None, com_seta: bool = False) -> str:
    """Item da checagem dos dados: estado ("ok", "atencao", "info"), número e explicação curta."""
    seta = '<span class="eti-icone eti-seta" aria-hidden="true">chevron_right</span>' if com_seta else ""
    return (
        f'<div class="eti-verificacao eti-verificacao-{estado}"><span class="eti-verificacao-marca" aria-hidden="true">'
        f'{_ICONE.format(ESTADOS_VERIFICACAO[estado])}</span><div class="eti-verificacao-corpo">'
        f'<div class="eti-verificacao-valor">{_e(valor)}</div><div class="eti-verificacao-titulo">{_e(titulo)}</div>'
        + (f'<div class="eti-verificacao-detalhe">{_e(detalhe)}</div>' if detalhe else "")
        + f"</div>{seta}</div>"
    )


def sugestao_conciliacao(par, mostrar_email) -> str:
    """Sugestão de associação: o registro do cadastro e a conta da plataforma lado a lado."""
    local = " · ".join(x for x in (f"{par.ente} ({par.uf})" if not eh_vazio(par.ente) else None,
                                   nome_legivel(par.escola) if not eh_vazio(par.escola) else None) if x)
    turma = turma_legivel(par) or (par.grupos if not eh_vazio(par.grupos) else "Sem turma")
    acesso = par.ultimo_acesso_texto if not eh_vazio(par.ultimo_acesso_texto) else "não informado"
    semelhanca = f"{float(par.similaridade) * 100:.0f}%" if not eh_vazio(par.similaridade) else "—"
    email_cadastro, email_conta = _email_legivel(mostrar_email(par.email)), _email_legivel(mostrar_email(par.email_conta))
    return (
        '<div class="eti-par">'
        f'<div class="eti-par-lado"><div class="eti-par-rotulo">{_ICONE.format("badge")}Cadastro</div>'
        f'<div class="eti-par-nome">{_e(nome_legivel(par.nome))}</div>'
        f'<div class="eti-par-detalhe">{_e(local or "Ente e escola não informados")}</div>'
        + (f'<div class="eti-par-detalhe">{_e(email_cadastro)}</div>' if email_cadastro else "") + "</div>"
        f'<div class="eti-par-meio"><span class="eti-icone" aria-hidden="true">sync_alt</span>'
        f'<div class="eti-par-semelhanca">{semelhanca}</div><small>semelhança dos nomes</small></div>'
        f'<div class="eti-par-lado"><div class="eti-par-rotulo">{_ICONE.format("school")}Plataforma</div>'
        f'<div class="eti-par-nome">{_e(nome_legivel(par.nome_completo))}</div>'
        f'<div class="eti-par-detalhe">{_e(turma)} · último acesso: {_e(acesso)}</div>'
        + (f'<div class="eti-par-detalhe">{_e(email_conta)}</div>' if email_conta else "") + "</div>"
        f'<div class="eti-par-motivo">{_e(par.motivo)}</div></div>'
    )


def fonte_dados(icone: str, titulo: str, texto: str, itens: list[tuple[str, str | tuple[str, str]]]) -> str:
    """Cartão de uma fonte de dados (página Sobre): o que é, de onde vem e os números da versão em uso.

    Um valor pode ser um par (texto, endereço), exibido como link.
    """
    def valor(v) -> str:
        if isinstance(v, tuple):
            texto_link, endereco = v
            return f'<a href="{_e(endereco)}" target="_blank" rel="noopener noreferrer">{_e(texto_link)}</a>'
        return _e(v)

    pares = "".join(f"<dt>{_e(r)}</dt><dd>{valor(v)}</dd>" for r, v in itens if v)
    return (f'<div class="eti-fonte"><div class="eti-fonte-topo">{_ICONE.format(_e(icone))}<span>{_e(titulo)}</span></div>'
            f'<p>{_e(texto)}</p><dl class="eti-dl eti-dl-compacta">{pares}</dl></div>')


def definicao_indicador(indicador) -> str:
    """Cartão com a definição documentada de um indicador (``metrics.Indicador``)."""
    return (
        f'<div class="eti-indicador"><div class="eti-indicador-topo"><span class="eti-indicador-nome">{_e(indicador.nome)}'
        f'</span>{etiqueta(indicador.unidade)}</div><p>{_e(indicador.definicao)}</p>'
        f'<div class="eti-indicador-formula">{_ICONE.format("function")}<span>{_e(indicador.formula)}</span></div>'
        f'<dl class="eti-dl eti-dl-compacta"><dt>Valores ausentes</dt><dd>{_e(indicador.ausentes)}</dd>'
        f'<dt>Limitações</dt><dd>{_e(indicador.limitacoes)}</dd></dl></div>'
    )


# ---------------------------------------------------------------- blocos das fichas


def filtro(rotulo: str, valor: int, total: int, cor: str) -> str:
    """Cartão de filtro: rótulo, contagem e barra da proporção no total."""
    fracao = valor / total if total else 0
    return (
        f'<div class="eti-filtro"><div class="eti-filtro-rotulo"><i style="background:{cor}"></i>{_e(rotulo)}</div>'
        f'<div class="eti-filtro-valor">{metrics.numero(valor)}</div>'
        f'<div class="eti-filtro-barra"><div style="width:{fracao * 100:.1f}%;background:{cor}"></div></div></div>'
    )


def numeros(itens: list[tuple[str, str, str | None]]) -> str:
    """Blocos de números: (rótulo, valor, complemento)."""
    blocos = "".join(
        f'<div class="eti-numero"><div class="eti-numero-rotulo">{_e(r)}</div><div class="eti-numero-valor">{_e(v)}</div>'
        + (f'<div class="eti-numero-sub">{_e(c)}</div>' if c else "") + "</div>"
        for r, v, c in itens
    )
    return f'<div class="eti-numeros">{blocos}</div>'


def jornada(passos: list[tuple[str, str, str]]) -> str:
    """Etapas da participação: (estado "ok" | "atencao" | "pendente", título, detalhe)."""
    marcas = {"ok": "check", "atencao": "priority_high", "pendente": "remove"}
    itens = "".join(
        f'<li class="eti-passo eti-passo-{estado}"><span class="eti-passo-marca" aria-hidden="true">'
        f'<span class="eti-icone">{marcas[estado]}</span></span>'
        f'<div><div class="eti-passo-titulo">{_e(titulo)}</div><div class="eti-passo-detalhe">{_e(detalhe)}</div></div></li>'
        for estado, titulo, detalhe in passos
    )
    return f'<ol class="eti-jornada">{itens}</ol>'


def cabecalho_pessoa(nome, cor: str, subtitulo: str, etiquetas: str) -> str:
    return (f'<div class="eti-perfil">{avatar(nome, cor, "eti-avatar-g")}<div>'
            f'<div class="eti-ficha-titulo">{_e(nome_legivel(nome))}</div>'
            f'<div class="eti-perfil-sub">{_e(subtitulo)}</div>'
            f'<div class="eti-pilulas">{etiquetas}</div></div></div>')


def infraestrutura(itens: list[tuple[str, str, str | None]]) -> str:
    """Itens sim/não do Censo como blocos com ícone: (ícone, rótulo, "1" | "0" | None)."""
    blocos = []
    for icone, rotulo, valor in itens:
        classe, resposta = {"1": ("sim", "Sim"), "0": ("nao", "Não")}.get(valor, ("na", "Não informado"))
        blocos.append(f'<li class="eti-infra-{classe}">{_ICONE.format(icone)}<span>{_e(rotulo)}</span>'
                      f'<b>{resposta}</b></li>')
    return f'<ul class="eti-infra">{"".join(blocos)}</ul>'
