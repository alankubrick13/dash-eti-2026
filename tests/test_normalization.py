"""Normalização de e-mails, códigos, CPF, datas e último acesso, conferida nos dados reais.

Cada verificação percorre os valores reais dos arquivos fornecidos. Variações (outra formatação do mesmo
código, um dígito verificador trocado) são derivadas desses valores; nenhum dado é inventado.
"""

import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from conftest import FUSO, confere, quadro, valores

from src.config import CODIGO_DA_SIGLA, NOME_DA_SIGLA
from src.importacao import carregar_municipios
from src.loaders import CAMPOS_ATIVIDADE, CAMPOS_CADASTRO
from src.normalization import (
    chave_comparacao,
    classificar_ibge,
    classificar_inep,
    descrever_duracao,
    interpretar_data,
    interpretar_ultimo_acesso,
    limpar_texto,
    momento_no_nome,
    normalizar_email,
    normalizar_uf,
    unificar_categorias,
    validar_cpf,
)


def _emails(tabelas_cadastro, tabela_atividade) -> list:
    return valores(tabelas_cadastro, "email", CAMPOS_CADASTRO) + valores([tabela_atividade], "email", CAMPOS_ATIVIDADE)


def test_emails_reais_normalizados(tabelas_cadastro, tabela_atividade):
    brutos = _emails(tabelas_cadastro, tabela_atividade)
    confere(len(brutos) > 1000, "poucos e-mails lidos dos arquivos reais")
    inconsistentes = 0
    for bruto in brutos:
        email, status = normalizar_email(bruto)
        if status != "valido":
            continue
        variantes = (f"  {bruto} ", str(bruto).upper(), f"mailto:{bruto}", f"<{bruto}>", email)
        if email != email.lower() or any(normalizar_email(v) != (email, "valido") for v in variantes):
            inconsistentes += 1
    confere(inconsistentes == 0, f"{inconsistentes} e-mail(s) real(is) normalizado(s) de forma inconsistente")


def test_emails_reais_malformados_sao_invalidos(tabelas_cadastro, tabela_atividade):
    validos = [e for e, s in map(normalizar_email, _emails(tabelas_cadastro, tabela_atividade)) if s == "valido"]
    aceitos = 0
    for email in validos:
        local, dominio = email.split("@", 1)
        defeitos = (email.replace("@", " @"), email.replace("@", "@@"), f"{local}@{dominio.split('.')[0]}",
                    f"{local}..{local}@{dominio}")
        aceitos += sum(normalizar_email(d)[1] == "valido" for d in defeitos)
    confere(aceitos == 0, f"{aceitos} variação(ões) malformada(s) de e-mails reais aceita(s) como válida(s)")


def test_codigos_inep_reais(tabelas_cadastro):
    brutos = valores(tabelas_cadastro, "inep", CAMPOS_CADASTRO)
    confere(len(brutos) > 1000, "poucos códigos INEP lidos")
    problemas = validos = 0
    for bruto in brutos:
        codigo, status = classificar_inep(bruto)
        if status != "valido":
            continue
        validos += 1
        if not (isinstance(codigo, str) and len(codigo) == 8 and codigo.isdigit()):
            problemas += 1
        # O mesmo código escrito de outras formas (número do Excel, texto com ".0", com pontos)
        for variante in (int(codigo), float(codigo), f"{codigo}.0", f"{codigo[:2]}.{codigo[2:5]}.{codigo[5:]}"):
            problemas += classificar_inep(variante) != (codigo, "valido")
        problemas += classificar_inep(codigo[:-1])[1] != "invalido"  # faltando um dígito
    confere(validos > 0 and problemas == 0, f"{problemas} inconsistência(s) nos códigos INEP reais")


def test_codigos_ibge_reais_contra_a_lista_oficial(tabelas_cadastro):
    municipios = carregar_municipios()
    confere(municipios is not None and len(municipios) > 5000, "lista oficial de municípios do IBGE indisponível")
    dados = quadro(tabelas_cadastro, CAMPOS_CADASTRO)
    siglas = sorted({normalizar_uf(u)[0] for u in dados["uf"] if normalizar_uf(u)[1] == "valido"})
    problemas = municipais = 0
    for bruto, uf in zip(dados["cod_ibge"], dados["uf"]):
        sigla = normalizar_uf(uf)[0]
        codigo, status = classificar_ibge(bruto, sigla, municipios)
        if status != "valido":
            continue
        if len(codigo) == 7:
            municipais += 1
            problemas += codigo not in municipios or municipios[codigo][1] != sigla
        outra = next((s for s in siglas if s != sigla), None)
        if outra:
            problemas += classificar_ibge(bruto, outra, municipios)[1] != "uf_divergente"
    # Código de 7 dígitos com prefixo de UF real, mas ausente da lista oficial
    for sigla in siglas:
        prefixo = CODIGO_DA_SIGLA[sigla]
        ausente = next(f"{prefixo}{n:05d}" for n in range(99999, 0, -1) if f"{prefixo}{n:05d}" not in municipios)
        problemas += classificar_ibge(ausente, sigla, municipios)[1] != "inexistente"
    confere(municipais > 0 and problemas == 0, f"{problemas} inconsistência(s) nos códigos IBGE reais")


def test_ufs_reais(tabelas_cadastro):
    problemas = 0
    for bruto in valores(tabelas_cadastro, "uf", CAMPOS_CADASTRO):
        sigla, status = normalizar_uf(bruto)
        if status != "valido":
            continue
        for variante in (str(bruto).lower(), f" {bruto} ", NOME_DA_SIGLA[sigla], NOME_DA_SIGLA[sigla].upper()):
            problemas += normalizar_uf(variante) != (sigla, "valido")
    confere(problemas == 0, f"{problemas} inconsistência(s) na leitura das UFs reais")


def test_cpfs_reais(tabelas_cadastro):
    brutos = valores(tabelas_cadastro, "cpf", CAMPOS_CADASTRO)
    confere(len(brutos) > 1000, "poucos CPFs lidos")
    problemas = validos = 0
    for bruto in brutos:
        digitos, status = validar_cpf(bruto)
        if status not in ("valido", "valido_recomposto"):
            continue
        validos += 1
        formatado = f"{digitos[:3]}.{digitos[3:6]}.{digitos[6:9]}-{digitos[9:]}"
        problemas += validar_cpf(formatado) != (digitos, "valido")
        problemas += validar_cpf(digitos[:-1] + str((int(digitos[-1]) + 1) % 10))[1] != "invalido"
        if digitos.startswith("0"):
            # Célula numérica do Excel que perdeu o zero à esquerda: recomposta; texto com 10 dígitos, não
            problemas += validar_cpf(int(digitos)) != (digitos, "valido_recomposto")
            problemas += validar_cpf(digitos[1:])[1] != "invalido"
    confere(validos > 0 and problemas == 0, f"{problemas} inconsistência(s) na validação dos CPFs reais")


def test_datas_reais(tabelas_cadastro):
    problemas = validas = 0
    for campo in ("data_resposta", "data_nascimento"):
        for bruto in valores(tabelas_cadastro, campo, CAMPOS_CADASTRO):
            data, status = interpretar_data(bruto)
            if status != "valida":
                continue
            validas += 1
            variantes = [data.strftime("%d/%m/%Y"), data.isoformat(), f"{data.isoformat()} 00:00:00",
                         datetime.combine(data, datetime.min.time())]
            serial = (data - date(1899, 12, 30)).days
            if 20000 <= serial <= 80000:  # número de série do Excel
                variantes.append(serial)
            problemas += sum(interpretar_data(v) != (data, "valida") for v in variantes)
            problemas += interpretar_data(f"31/02/{data.year}") != (None, "invalida")  # dia inexistente
    confere(validas > 0 and problemas == 0, f"{problemas} inconsistência(s) na leitura das datas reais")


def test_ultimo_acesso_real_interpretado_sem_inventar_datas(tabela_atividade):
    textos = valores([tabela_atividade], "ultimo_acesso", CAMPOS_ATIVIDADE)
    confere(len(textos) > 1000, "poucos registros de último acesso lidos")
    acessos = [interpretar_ultimo_acesso(t) for t in textos]
    confere(all(a.tipo != "nao_interpretado" for a in acessos), "há último acesso real não interpretado")
    relativos = [a for a in acessos if a.tipo == "relativo"]
    confere(all(a.duracao_s >= 0 and a.momento is None for a in relativos),
            "tempo relativo virou data sem a data de exportação")
    # Descrever e reler o tempo devolve o mesmo valor (a descrição do painel não mostra segundos)
    confere(all(interpretar_ultimo_acesso(descrever_duracao(a.duracao_s)).duracao_s == a.duracao_s - a.duracao_s % 60
                for a in relativos if a.duracao_s >= 60), "descrição do tempo sem acesso não confere")


def test_nomes_reais_nao_sao_confundidos_com_tempo(tabelas_cadastro, tabela_atividade):
    nomes = valores(tabelas_cadastro, "nome", CAMPOS_CADASTRO) + valores([tabela_atividade], "nome_completo", CAMPOS_ATIVIDADE)
    confundidos = sum(interpretar_ultimo_acesso(n).tipo != "nao_interpretado" for n in nomes)
    confere(confundidos == 0, f"{confundidos} nome(s) real(is) lido(s) como tempo de acesso")


def test_formatos_de_tempo_do_moodle():
    """Especificação de formato (como o Moodle escreve o tempo), não registros."""
    casos = {"1 hora 33 minutos": 5580, "1 hora e 33 minutos": 5580, "14 dias 22 horas": 14 * 86400 + 22 * 3600,
             "2 dias": 2 * 86400, "23 minutos 5 segundos": 23 * 60 + 5, "3 days 2 hours": 3 * 86400 + 7200,
             "1 ano 15 dias": 380 * 86400, "agora": 0}
    for texto, segundos in casos.items():
        acesso = interpretar_ultimo_acesso(texto)
        assert (acesso.tipo, acesso.duracao_s, acesso.momento) == ("relativo", segundos, None), texto
    assert interpretar_ultimo_acesso("Nunca").tipo == interpretar_ultimo_acesso("never").tipo == "nunca"
    assert interpretar_ultimo_acesso("").tipo == interpretar_ultimo_acesso(None).tipo == "vazio"


def test_data_absoluta_usa_o_fuso(arquivo_atividade):
    # Momento real: quando o arquivo da plataforma foi salvo neste computador
    momento = datetime.fromtimestamp(arquivo_atividade.stat().st_mtime, ZoneInfo(FUSO)).replace(second=0, microsecond=0)
    esperado = momento.astimezone(timezone.utc)
    assert interpretar_ultimo_acesso(momento.strftime("%d/%m/%Y %H:%M"), FUSO).momento == esperado
    manaus = momento.replace(tzinfo=ZoneInfo("America/Manaus"))
    assert interpretar_ultimo_acesso(momento.strftime("%d/%m/%Y %H:%M"), "America/Manaus").momento == manaus.astimezone(timezone.utc)
    assert interpretar_ultimo_acesso(esperado.strftime("%Y-%m-%dT%H:%M:%SZ")).momento == esperado
    assert esperado - timedelta(days=1) < datetime.now(timezone.utc)


def test_data_e_hora_no_nome_dos_arquivos(arquivos_cadastro, arquivo_atividade):
    """O nome real da planilha do cadastro traz a posição (ex.: "14ago26_8h02"); arquivos sem data no nome ficam sem."""
    meses = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
    lidos = 0
    for arquivo in arquivos_cadastro:
        momento = momento_no_nome(arquivo.name, FUSO)
        if momento is None:
            confere(not re.search(r"\d{1,2}(" + "|".join(meses) + r")\d{2}", arquivo.name.lower()),
                    "data no nome de uma planilha real não foi lida")
            continue
        local = momento.astimezone(ZoneInfo(FUSO))
        confere(f"{local.day}{meses[local.month - 1]}{local:%y}_{local.hour}h{local:%M}" in arquivo.name.lower(),
                "data e hora lidas não correspondem ao nome da planilha real")
        lidos += 1
    if not lidos:
        pytest.skip("nenhuma planilha real com data no nome")
    assert momento_no_nome(arquivo_atividade.name, FUSO) is None  # a lista do Moodle não traz data no nome
    # Especificação dos formatos, com o momento real em que a lista da plataforma foi salva
    salvo = datetime.fromtimestamp(arquivo_atividade.stat().st_mtime, ZoneInfo(FUSO)).replace(second=0, microsecond=0)
    nomes = (f"participantes_{salvo.day}{meses[salvo.month - 1]}{salvo:%y}_{salvo.hour}h{salvo:%M}.txt",
             f"participantes {salvo:%Y-%m-%d} {salvo:%H}h{salvo:%M}.txt", f"lista_{salvo:%d-%m-%Y}_{salvo:%H%M}.txt")
    for nome in nomes:
        assert momento_no_nome(nome, FUSO) == salvo.astimezone(timezone.utc), nome
    assert momento_no_nome(f"lista_31fev{salvo:%y}.txt", FUSO) is None  # data impossível não vira data


def test_categorias_reais_unificadas_pela_grafia_da_fonte(tabelas_cadastro):
    problemas = 0
    for campo in ("situacao", "tipo", "origem", "escolaridade", "cargo_funcao"):
        brutos = [b for b in valores(tabelas_cadastro, campo, CAMPOS_CADASTRO) if isinstance(b, str)]
        if not brutos:
            continue
        variantes = [b.lower() for b in brutos[:10]] + [f" {b.upper()} " for b in brutos[:10]]
        unificadas = unificar_categorias(brutos + variantes)
        originais = {limpar_texto(b) for b in brutos}
        problemas += not set(unificadas) <= originais  # nenhuma grafia nova é criada
        por_chave = {}
        for valor in unificadas:
            por_chave.setdefault(chave_comparacao(valor), set()).add(valor)
        problemas += sum(len(v) > 1 for v in por_chave.values())
    confere(problemas == 0, f"{problemas} inconsistência(s) na unificação das categorias reais")


def test_chave_de_comparacao_dos_nomes_reais(tabelas_cadastro):
    problemas = 0
    for nome in valores(tabelas_cadastro, "nome", CAMPOS_CADASTRO):
        chave = chave_comparacao(nome)
        problemas += not (chave and chave == chave.lower() and "  " not in chave and chave.isascii())
        problemas += chave_comparacao(chave) != chave or chave_comparacao(f"  {str(nome).lower()} ") != chave
    confere(problemas == 0, f"{problemas} inconsistência(s) na chave de comparação dos nomes reais")
