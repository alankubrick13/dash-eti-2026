"""Dados sintéticos realistas para demonstração e testes.

Pessoas, escolas, códigos INEP, CPFs e contatos são fictícios; municípios e
códigos IBGE são reais (lista oficial do IBGE), para que as validações
territoriais funcionem. E-mails usam o domínio reservado ".example" (RFC 2606).
Os arquivos seguem os formatos das fontes reais: planilha cadastral com os
mesmos cabeçalhos, texto copiado da página de participantes do Moodle e CSV no
formato dos microdados do Censo Escolar. Gerados localmente, não versionados.
"""

from __future__ import annotations

import csv
import io
import random
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from . import config
from .normalization import normalizar_email

CABECALHOS_CADASTRO = [
    "Região", "UF", "Ente", "CODIBGE", "Data resposta", "Ciclo", "Articulador", "Esfera", "Nome", "CPF",
    "Data Nascimento", "E-mail", "Telefone", "WhatsApp", "Tipo", "Origem", "Situação", "Raça/Cor",
    "Gênero", "Escolaridade", "Cargo/Função", "Escola", "INEP",
]
PESOS_UF = {"PA": 0.55, "TO": 0.18, "AM": 0.16, "RO": 0.04, "RR": 0.03, "AC": 0.025, "AP": 0.015}
ENTES_POR_UF = {"PA": 64, "TO": 38, "AM": 30, "RO": 10, "RR": 7, "AC": 7, "AP": 5}
DDD = {"PA": "91", "TO": "63", "AM": "92", "RO": "69", "RR": "95", "AC": "68", "AP": "96"}
NOME_GRUPO = {"PA": "Para", "TO": "Tocantins", "AM": "Amazonas", "RO": "Rondonia", "RR": "Roraima",
              "AC": "Acre", "AP": "Amapa"}
REFERENCIA_EXPORTACAO = datetime(2026, 10, 19, 17, 30, tzinfo=ZoneInfo("America/Sao_Paulo"))
REFERENCIA_NOVA_EXPORTACAO = datetime(2026, 10, 24, 9, 0, tzinfo=ZoneInfo("America/Sao_Paulo"))
ANO_CENSO_SINTETICO = 2025

PRENOMES_F = (
    "MARIA", "ANA", "FRANCISCA", "ANTONIA", "ADRIANA", "JULIANA", "MARCIA", "FERNANDA", "PATRICIA", "ALINE",
    "SANDRA", "CAMILA", "AMANDA", "BRUNA", "JESSICA", "LETICIA", "JULIA", "LUCIANA", "VANESSA", "MARIANA",
    "GABRIELA", "VALERIA", "ADRIANE", "ELIANE", "SIMONE", "CRISTIANE", "ROSANGELA", "KATIA", "DANIELE",
    "RAIMUNDA", "SILVANA", "ROSILENE", "ELIZANGELA", "CLEIDE", "LUCILENE", "SOLANGE", "TATIANE", "NAZARE",
    "IVONETE", "JOSIANE", "MARLENE", "EDILENE", "SUELEN", "DAYANE", "KELLY", "LUANA", "RAQUEL", "ROSA",
    "TEREZA", "ZILDA", "CLAUDIA", "DEBORA", "GISELE", "ILMA", "JOANA", "LIDIANE", "NEUSA", "ODETE",
)
PRENOMES_M = (
    "JOSE", "JOAO", "ANTONIO", "FRANCISCO", "CARLOS", "PAULO", "PEDRO", "LUCAS", "LUIZ", "MARCOS",
    "RAIMUNDO", "MANOEL", "EDSON", "RAFAEL", "DANIEL", "MARCELO", "BRUNO", "EDUARDO", "FELIPE", "RODRIGO",
    "SEBASTIAO", "WALDIR", "CLEBER", "ELIAS", "GILSON", "JORGE", "NILSON", "ROBSON", "SERGIO", "VALDECI",
)
# Partículas só antes dos sobrenomes com que costumam aparecer.
PARTICULAS = {
    "DA": ("SILVA", "COSTA", "CONCEICAO", "CRUZ", "ROCHA", "LUZ", "PAIXAO", "FONSECA", "CUNHA", "MOTA"),
    "DOS": ("SANTOS", "ANJOS", "REIS", "PASSOS", "PRAZERES"),
    "DE": ("SOUZA", "SOUSA", "OLIVEIRA", "JESUS", "ABREU", "LIMA", "MELO", "FREITAS", "CARVALHO", "ASSIS"),
}
SOBRENOMES = (
    "SILVA", "SANTOS", "OLIVEIRA", "SOUZA", "SOUSA", "LIMA", "PEREIRA", "FERREIRA", "COSTA", "RODRIGUES",
    "ALVES", "NASCIMENTO", "ARAUJO", "CARVALHO", "GOMES", "MARTINS", "ROCHA", "RIBEIRO", "BARBOSA",
    "CARDOSO", "MONTEIRO", "MOREIRA", "PINHEIRO", "CAMPOS", "TAVARES", "BRITO", "MACEDO", "FARIAS", "MELO",
    "CORREA", "MACIEL", "BATISTA", "QUEIROZ", "PANTOJA", "FURTADO", "BARRETO", "VIEIRA", "CUNHA", "MIRANDA",
    "LOBATO", "MAGALHAES", "SARAIVA", "TEIXEIRA", "BENTES", "CASTRO", "AMARAL", "BORGES", "PALHETA", "PIMENTEL",
    "QUARESMA", "CORDEIRO", "FONSECA", "GUIMARAES", "NUNES", "PAIVA", "REIS", "SALES", "VASCONCELOS",
)
DOMINIOS = ("correio.example", "webmail.example", "mail.example", "caixapostal.example")
PADROES_ESCOLA = (
    ("ESCOLA MUNICIPAL DE ENSINO FUNDAMENTAL {p}", "EMEF {p}"),
    ("ESCOLA MUNICIPAL {p}", "ESCOLA MUNICIPAL {p}"),
    ("ESCOLA MUNICIPAL DE EDUCACAO INFANTIL E ENSINO FUNDAMENTAL {p}", "EMEIF {p}"),
    ("UNIDADE MUNICIPAL DE ENSINO {p}", "UME {p}"),
)
PADROES_ESCOLA_ESTADUAL = (("ESCOLA ESTADUAL {p}", "EE {p}"), ("ESCOLA ESTADUAL DE ENSINO MEDIO {p}", "EEEM {p}"))
INFRA_URBANA = {
    "IN_AGUA_POTAVEL": .97, "IN_ENERGIA_REDE_PUBLICA": .95, "IN_ESGOTO_REDE_PUBLICA": .35, "IN_INTERNET": .9,
    "IN_INTERNET_ALUNOS": .55, "IN_BANDA_LARGA": .7, "IN_BIBLIOTECA_SALA_LEITURA": .6,
    "IN_LABORATORIO_INFORMATICA": .35, "IN_LABORATORIO_CIENCIAS": .12, "IN_QUADRA_ESPORTES": .55,
    "IN_REFEITORIO": .55, "IN_COZINHA": .97, "IN_PATIO_COBERTO": .5, "IN_BANHEIRO_PNE": .5, "IN_ALIMENTACAO": .99,
}
INFRA_RURAL = {
    "IN_AGUA_POTAVEL": .8, "IN_ENERGIA_REDE_PUBLICA": .7, "IN_ESGOTO_REDE_PUBLICA": .03, "IN_INTERNET": .55,
    "IN_INTERNET_ALUNOS": .2, "IN_BANDA_LARGA": .3, "IN_BIBLIOTECA_SALA_LEITURA": .25,
    "IN_LABORATORIO_INFORMATICA": .08, "IN_LABORATORIO_CIENCIAS": .02, "IN_QUADRA_ESPORTES": .2,
    "IN_REFEITORIO": .25, "IN_COZINHA": .9, "IN_PATIO_COBERTO": .2, "IN_BANHEIRO_PNE": .2, "IN_ALIMENTACAO": .99,
}


def _sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))


def gerar_cpf(rng: random.Random) -> str:
    base = [rng.randint(0, 9) for _ in range(9)]
    for n in (9, 10):
        soma = sum(d * (n + 1 - i) for i, d in enumerate(base))
        base.append((soma * 10) % 11 % 10)
    d = "".join(map(str, base))
    return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"


def _municipios_norte() -> dict[str, list[tuple[str, str]]]:
    por_uf: dict[str, list[tuple[str, str]]] = {}
    with open(config.ARQ_MUNICIPIOS, encoding="utf-8") as f:
        for linha in csv.DictReader(f):
            if linha["uf"] in PESOS_UF:
                por_uf.setdefault(linha["uf"], []).append((linha["codigo_ibge"], linha["nome"]))
    return por_uf


@dataclass
class Escola:
    inep: str
    nome_oficial: str
    nome_cadastro: str
    uf: str
    cod_municipio: str
    municipio: str
    dependencia: str  # código Inep (2 estadual, 3 municipal)
    rural: bool


@dataclass
class Pessoa:
    nome: str
    cpf: str
    nascimento: date
    email: str
    escola: Escola
    ente: str
    cod_ibge: str
    esfera: str
    articulador: str
    cargo: str
    origem: str
    situacao: str
    data_resposta: date


class Gerador:
    def __init__(self, semente: int = 2026):
        self.rng = random.Random(semente)
        self.nomes_usados: set[str] = set()
        self.emails_usados: set[str] = set()
        self.ineps_usados: set[str] = set()

    def nome(self, feminino: bool | None = None) -> str:
        for _ in range(1000):
            fem = self.rng.random() < 0.76 if feminino is None else feminino
            lista = PRENOMES_F if fem else PRENOMES_M
            partes = self.rng.sample(lista, 2) if self.rng.random() < 0.3 else [self.rng.choice(lista)]
            if self.rng.random() < 0.35:
                particula = self.rng.choice(list(PARTICULAS))
                partes += [particula, self.rng.choice(PARTICULAS[particula])]
            partes += self.rng.sample(SOBRENOMES, self.rng.choice((1, 1, 2)))
            nome = " ".join(partes)
            if nome not in self.nomes_usados:
                self.nomes_usados.add(nome)
                return nome
        raise RuntimeError("espaço de nomes esgotado")

    def email(self, nome: str) -> str:
        partes = _sem_acento(nome).lower().split()
        partes = [p for p in partes if p not in ("da", "dos", "de", "das")]
        for _ in range(100):
            estilo = self.rng.random()
            if estilo < 0.4:
                local = f"{partes[0]}.{partes[-1]}"
            elif estilo < 0.7:
                local = f"{partes[0]}{partes[-1]}{self.rng.randint(1, 99)}"
            else:
                local = f"{partes[0][0]}{partes[-1]}{self.rng.randint(10, 999)}"
            email = f"{local}@{self.rng.choice(DOMINIOS)}"
            if email not in self.emails_usados:
                self.emails_usados.add(email)
                return email
        raise RuntimeError("espaço de e-mails esgotado")

    def inep(self, uf: str) -> str:
        while True:
            codigo = config.CODIGO_DA_SIGLA[uf] + f"{self.rng.randint(0, 999999):06d}"
            if codigo not in self.ineps_usados:
                self.ineps_usados.add(codigo)
                return codigo

    def escola(self, uf: str, cod_mun: str, municipio: str, estadual: bool = False) -> Escola:
        patrono = self.nome().replace(" DA ", " ").replace(" DOS ", " ")
        if self.rng.random() < 0.45:
            patrono = ("PROFESSORA " if self.rng.random() < 0.7 else "PROFESSOR ") + patrono
        oficial, abreviado = self.rng.choice(PADROES_ESCOLA_ESTADUAL if estadual else PADROES_ESCOLA)
        nome_cadastro = (abreviado if self.rng.random() < 0.5 else oficial).format(p=patrono)
        return Escola(self.inep(uf), oficial.format(p=patrono), nome_cadastro, uf, cod_mun, municipio,
                      "2" if estadual else "3", self.rng.random() < 0.45)


def _data_texto(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def gerar_base(semente: int = 2026) -> tuple[list[Pessoa], list[Escola], Gerador]:
    g = Gerador(semente)
    rng = g.rng
    municipios = _municipios_norte()
    pessoas: list[Pessoa] = []
    escolas: list[Escola] = []
    for uf, n_entes in ENTES_POR_UF.items():
        entes = rng.sample(municipios[uf], min(n_entes, len(municipios[uf])))
        alvo_uf = round(1240 * PESOS_UF[uf])
        por_ente = [max(1, round(alvo_uf / len(entes) * rng.uniform(0.4, 1.6))) for _ in entes]
        for (cod, nome_mun), alvo in zip(entes, por_ente):
            articulador = g.nome()
            n_escolas = max(1, round(alvo / 1.7))
            for _ in range(n_escolas):
                esc = g.escola(uf, cod, nome_mun)
                escolas.append(esc)
                cargos = ["Diretor Escolar"] + (["Coordenador Pedagógico"] if rng.random() < 0.72 else [])
                for cargo in cargos:
                    pessoas.append(_pessoa(g, esc, nome_mun, cod, "Municipal", articulador, cargo))
    # Entes estaduais (como na lista de novos inscritos: CODIBGE com 2 dígitos)
    for uf in ("RO", "RR", "AC", "AP"):
        cod_mun, nome_mun = rng.choice(municipios[uf])
        articulador = g.nome()
        for _ in range(2):
            esc = g.escola(uf, cod_mun, nome_mun, estadual=True)
            escolas.append(esc)
            pessoas.append(_pessoa(g, esc, f"Governo do Estado de {config.NOME_DA_SIGLA[uf]}",
                                   config.CODIGO_DA_SIGLA[uf], "Estadual", articulador,
                                   rng.choice(("Diretor Escolar", "Coordenador Pedagógico"))))
    return pessoas, escolas, g


def _pessoa(g: Gerador, esc: Escola, ente: str, cod_ibge: str, esfera: str, articulador: str, cargo: str) -> Pessoa:
    rng = g.rng
    nome = g.nome(feminino=rng.random() < 0.76)
    situacao = rng.choices(("Aceitou", "Aguardando resposta", "Recusou"), (0.95, 0.03, 0.02))[0]
    return Pessoa(
        nome=nome, cpf=gerar_cpf(rng),
        nascimento=date(1962, 1, 1) + timedelta(days=rng.randint(0, 365 * 36)),
        email=g.email(nome), escola=esc, ente=ente, cod_ibge=cod_ibge, esfera=esfera,
        articulador=articulador, cargo=cargo, origem=rng.choices(("Regular", "Suplente"), (0.62, 0.38))[0],
        situacao=situacao, data_resposta=date(2026, 7, 14) + timedelta(days=rng.randint(0, 30)),
    )


def _linha_cadastro(p: Pessoa, rng: random.Random) -> list:
    uf = p.escola.uf
    return [
        "Norte", uf, p.ente, int(p.cod_ibge), _data_texto(p.data_resposta), "2026", p.articulador, p.esfera,
        p.nome, p.cpf, _data_texto(p.nascimento), p.email, f"{DDD[uf]}90000{rng.randint(0, 9999):04d}",
        rng.choice(("Sim", "Não")) if rng.random() < 0.1 else "Não", "Titular", p.origem, p.situacao,
        rng.choices(("Parda", "Branca", "Preta", "Indígena", "Amarela", "Não declarada"),
                    (0.71, 0.13, 0.12, 0.028, 0.007, 0.005))[0],
        rng.choices(("Feminino", "Masculino", "Prefiro não informar"), (0.765, 0.233, 0.002))[0],
        rng.choices(("Especializacao", "Superior", "Mestrado", "Medio", "Doutorado"), (0.69, 0.26, 0.04, 0.015, 0.005))[0],
        p.cargo, p.escola.nome_cadastro, int(p.escola.inep),
    ]


def _imperfeicoes(linhas: list[list], g: Gerador) -> list[list]:
    """Problemas reais de preenchimento, em pequena proporção, para as telas de qualidade."""
    rng = g.rng
    idx = {h: i for i, h in enumerate(CABECALHOS_CADASTRO)}
    alvos = rng.sample(range(len(linhas)), 40)
    sem_inep, inep_curto, inep_outra_uf, email_ruim, espacos, ibge_outra_uf, nasc_ruim = (
        alvos[0:4], alvos[4:7], alvos[7:9], alvos[9:14], alvos[14:17], alvos[17:18], alvos[18:21])
    for i in sem_inep:
        linhas[i][idx["INEP"]] = None
    for i in inep_curto:
        linhas[i][idx["INEP"]] = int(str(linhas[i][idx["INEP"]])[:7])
    for i in inep_outra_uf:
        linhas[i][idx["INEP"]] = int("13" + str(linhas[i][idx["INEP"]])[2:]) if linhas[i][idx["UF"]] != "AM" else int(
            "15" + str(linhas[i][idx["INEP"]])[2:])
    variantes_email = (lambda e: e.split(".example")[0], lambda e: e.replace("@", " @", 1),
                       lambda e: e.replace("@", "@@", 1), lambda e: e.replace(".", "..", 1),
                       lambda e: e.split("@")[0])
    for i, variante in zip(email_ruim, variantes_email):
        linhas[i][idx["E-mail"]] = variante(linhas[i][idx["E-mail"]])
    for i in espacos:
        linhas[i][idx["Nome"]] = "  " + linhas[i][idx["Nome"]].title().replace(" ", "  ", 1) + " "
    for i in ibge_outra_uf:
        linhas[i][idx["CODIBGE"]] = 1302603 if linhas[i][idx["UF"]] != "AM" else 1501402
    linhas[nasc_ruim[0]][idx["Data Nascimento"]] = "31/02/1980"
    linhas[nasc_ruim[1]][idx["Data Nascimento"]] = "1980-13-01"
    linhas[nasc_ruim[2]][idx["Data Nascimento"]] = "02/05/2016"
    # Duplicidades: mesma pessoa inscrita duas vezes (linha repetida; outro e-mail; outra escola)
    base = alvos[21:24]
    extras = [list(linhas[base[0]])]
    outro_email = list(linhas[base[1]])
    outro_email[idx["E-mail"]] = g.email(outro_email[idx["Nome"]])
    extras.append(outro_email)
    outra_escola = list(linhas[base[2]])
    outra_escola[idx["Cargo/Função"]] = "Coordenador Pedagógico"
    extras.append(outra_escola)
    # E-mail institucional compartilhado por duas pessoas diferentes
    for i, j in ((alvos[24], alvos[25]), (alvos[26], alvos[27])):
        linhas[j][idx["E-mail"]] = linhas[i][idx["E-mail"]]
    return linhas + extras


def escrever_xlsx(caminho: Path, cabecalhos: list[str], linhas: list[list], aba: str = "Dados") -> None:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = aba
    ws.append(cabecalhos)
    for linha in linhas:
        ws.append(linha)
    wb.save(caminho)


# ---------------------------------------------------------------- atividade (texto do Moodle)

CABECALHO_MOODLE = (
    "\nDesmarcar todas as seleções\n"
    "\tNomeOrdenar por Nome Ascendente / SobrenomeOrdenar por Sobrenome Ascendente\n"
    "\tEndereço de emailOrdenar por Endereço de email Ascendente\n"
    "\tPapéis\n\tGrupos\n"
    "\tÚltimo acesso ao cursoOrdenar por Último acesso ao curso Ascendente\n"
    "\tSituação\n"
)


def formato_moodle(segundos: int | None) -> str:
    """Tempo no formato do Moodle em português: maior unidade não nula e a seguinte, se não for zero."""
    if segundos is None:
        return "Nunca"
    quantidades, resto = [], int(segundos)
    for singular, plural, tamanho in (("dia", "dias", 86400), ("hora", "horas", 3600),
                                      ("minuto", "minutos", 60), ("segundo", "segundos", 1)):
        n, resto = divmod(resto, tamanho)
        quantidades.append(f"{n} {singular if n == 1 else plural}" if n else None)
    for i, texto in enumerate(quantidades):
        if texto:
            seguinte = quantidades[i + 1] if i + 1 < len(quantidades) else None
            return f"{texto} {seguinte}" if seguinte else texto
    return "0 segundos"


@dataclass
class Conta:
    nome: str
    email: str
    papel: str
    grupos: str
    segundos: int | None
    situacao: str = "Ativo"


def _duracao(rng: random.Random) -> int | None:
    if rng.random() < 0.16:
        return None
    faixa = rng.choices(((0, 7), (7, 14), (14, 30), (30, 62)), (0.36, 0.2, 0.25, 0.19))[0]
    return int(rng.uniform(faixa[0] * 86400 + 600, faixa[1] * 86400))


def gerar_contas(pessoas: list[Pessoa], linhas_cadastro: list[list], g: Gerador) -> list[Conta]:
    rng = g.rng
    idx = {h: i for i, h in enumerate(CABECALHOS_CADASTRO)}
    grupos_uf = {uf: [f"{nome} {n}" for n in range(1, 7)] for uf, nome in NOME_GRUPO.items()}
    todos_grupos = [gr for lista in grupos_uf.values() for gr in lista]
    contas: list[Conta] = []
    vistos, emails_conta = set(), set()
    for linha in linhas_cadastro:
        email_cad, status_email = normalizar_email(linha[idx["E-mail"]])
        nome = " ".join(str(linha[idx["Nome"]]).split()).upper()
        if nome in vistos or linha[idx["Situação"]] != "Aceitou":
            continue
        vistos.add(nome)
        sorteio = rng.random()
        if sorteio < 0.012:
            continue  # inscrito sem conta na plataforma
        if sorteio < 0.03 or status_email != "valido" or email_cad in emails_conta:
            email = g.email(nome)  # conta criada com outro e-mail (o Moodle não aceita e-mail repetido)
        else:
            email = email_cad
        emails_conta.add(email)
        uf = linha[idx["UF"]]
        grupo = rng.choice(grupos_uf[uf]) if rng.random() < 0.55 else rng.choice(todos_grupos)
        contas.append(Conta(nome, email, "Estudante", grupo, _duracao(rng),
                            "Suspenso" if rng.random() < 0.008 else "Ativo"))
    # Contas de cursistas fora do cadastro e um caso de homônimos
    for _ in range(6):
        nome = g.nome()
        contas.append(Conta(nome, g.email(nome), "Estudante", rng.choice(todos_grupos), _duracao(rng)))
    alvo = next(c for c in contas if c.papel == "Estudante")
    contas.append(Conta(alvo.nome, g.email(alvo.nome), "Estudante", rng.choice(todos_grupos), _duracao(rng)))
    alvo.email = g.email(alvo.nome)
    # Contas em dois grupos e sem grupo
    for conta in rng.sample([c for c in contas if c.papel == "Estudante"], 12):
        conta.grupos = f"{conta.grupos}, {rng.choice(todos_grupos)}"
    for conta in rng.sample([c for c in contas if c.papel == "Estudante"], 3):
        conta.grupos = ""
    # Equipe da formação
    for grupo in todos_grupos:
        nome = g.nome()
        contas.append(Conta(nome, g.email(nome).replace(".example", ".formacao.example"),
                            "Formador (Tutor não editor)", grupo, rng.randint(600, 4 * 86400)))
    for papel, n in (("Coord. Estadual (Professor Formador)", 7), ("Suporte Moodle", 5), ("Coordenador de Curso", 3)):
        for _ in range(n):
            nome = g.nome()
            contas.append(Conta(nome, g.email(nome).replace(".example", ".formacao.example"), papel,
                                "", rng.randint(60, 2 * 86400)))
    rng.shuffle(contas)
    return contas


def texto_moodle(contas: list[Conta]) -> str:
    partes = [CABECALHO_MOODLE]
    for c in contas:
        partes.append(f"Selecione '{c.nome}'\n")
        partes.append(f"\t{c.nome}\t{c.email}\t{c.papel}\t{c.grupos}\t{formato_moodle(c.segundos)}\t\n")
        partes.append(f"{c.situacao}\n")
    return "".join(partes)


def avancar_contas(contas: list[Conta], g: Gerador, dias: float) -> list[Conta]:
    """Nova exportação alguns dias depois: parte das pessoas volta a acessar."""
    rng = g.rng
    novas = []
    for c in contas:
        n = Conta(c.nome, c.email, c.papel, c.grupos, c.segundos, c.situacao)
        if c.segundos is None:
            if rng.random() < 0.12:
                n.segundos = rng.randint(3600, int(dias * 86400))
        elif rng.random() < 0.35:
            n.segundos = rng.randint(300, int(dias * 86400))
        else:
            n.segundos = c.segundos + int(dias * 86400)
        novas.append(n)
    return novas


# ---------------------------------------------------------------- escolas (formato dos microdados)

COLUNAS_MICRODADOS = (
    "NU_ANO_CENSO", "NO_REGIAO", "CO_REGIAO", "NO_UF", "SG_UF", "CO_UF", "NO_MUNICIPIO", "CO_MUNICIPIO",
    "NO_ENTIDADE", "CO_ENTIDADE", "TP_DEPENDENCIA", "TP_CATEGORIA_ESCOLA_PRIVADA", "TP_LOCALIZACAO",
    "TP_LOCALIZACAO_DIFERENCIADA", "TP_SITUACAO_FUNCIONAMENTO", *INFRA_URBANA.keys(),
    "IN_INF", "IN_FUND", "IN_FUND_AI", "IN_FUND_AF", "IN_MED", "IN_PROF", "IN_EJA", "IN_ESP",
    "QT_MAT_BAS", "QT_MAT_INF", "QT_MAT_FUND", "QT_MAT_MED", "QT_MAT_INF_INT", "QT_MAT_FUND_INT",
    "QT_MAT_FUND_AI_INT", "QT_MAT_FUND_AF_INT", "QT_MAT_MED_INT", "QT_DOC_BAS", "QT_TUR_BAS", "QT_SALAS_UTILIZADAS",
)


def _linha_microdados(e: Escola, rng: random.Random) -> dict:
    infra = INFRA_RURAL if e.rural else INFRA_URBANA
    linha = {
        "NU_ANO_CENSO": ANO_CENSO_SINTETICO, "NO_REGIAO": "Norte", "CO_REGIAO": 1,
        "NO_UF": config.NOME_DA_SIGLA[e.uf], "SG_UF": e.uf, "CO_UF": config.CODIGO_DA_SIGLA[e.uf],
        "NO_MUNICIPIO": e.municipio, "CO_MUNICIPIO": e.cod_municipio, "NO_ENTIDADE": e.nome_oficial,
        "CO_ENTIDADE": e.inep, "TP_DEPENDENCIA": e.dependencia, "TP_CATEGORIA_ESCOLA_PRIVADA": "",
        "TP_LOCALIZACAO": 2 if e.rural else 1,
        "TP_LOCALIZACAO_DIFERENCIADA": rng.choices((0, 1, 2, 3, 8), (0.86, 0.04, 0.05, 0.02, 0.03))[0] if e.rural else 0,
        "TP_SITUACAO_FUNCIONAMENTO": rng.choices((1, 2), (0.985, 0.015))[0],
    }
    for var, p in infra.items():
        linha[var] = int(rng.random() < p)
    if not linha["IN_INTERNET"]:
        linha["IN_BANDA_LARGA"] = ""
        linha["IN_INTERNET_ALUNOS"] = 0
    medio = e.dependencia == "2"
    ai, af = (0, rng.random() < 0.6) if medio else (rng.random() < 0.85, rng.random() < 0.6)
    inf = 0 if medio else int(rng.random() < 0.55)
    med = int(medio)
    linha.update({"IN_INF": inf, "IN_FUND_AI": int(ai), "IN_FUND_AF": int(af), "IN_FUND": int(ai or af),
                  "IN_MED": med, "IN_PROF": int(medio and rng.random() < 0.2),
                  "IN_EJA": int(rng.random() < 0.25), "IN_ESP": int(rng.random() < 0.7)})
    q_inf = rng.randint(20, 160) if inf else 0
    q_fund = rng.randint(40, 900) if (ai or af) else 0
    q_med = rng.randint(80, 1100) if med else 0
    integral = rng.random() < 0.35
    q_fund_ai_int = rng.randint(0, q_fund // 2) if integral and ai else 0
    q_fund_af_int = rng.randint(0, q_fund // 3) if integral and af else 0
    linha.update({
        "QT_MAT_BAS": q_inf + q_fund + q_med, "QT_MAT_INF": q_inf, "QT_MAT_FUND": q_fund, "QT_MAT_MED": q_med,
        "QT_MAT_INF_INT": rng.randint(0, q_inf // 2) if integral and inf else 0,
        "QT_MAT_FUND_AI_INT": q_fund_ai_int, "QT_MAT_FUND_AF_INT": q_fund_af_int,
        "QT_MAT_FUND_INT": q_fund_ai_int + q_fund_af_int,
        "QT_MAT_MED_INT": rng.randint(0, q_med // 2) if integral and med else 0,
        "QT_DOC_BAS": max(2, (q_inf + q_fund + q_med) // 22), "QT_TUR_BAS": max(1, (q_inf + q_fund + q_med) // 26),
        "QT_SALAS_UTILIZADAS": max(1, (q_inf + q_fund + q_med) // 60),
    })
    return linha


def csv_microdados(escolas: list[Escola], g: Gerador) -> bytes:
    buffer = io.StringIO()
    escritor = csv.DictWriter(buffer, fieldnames=COLUNAS_MICRODADOS, delimiter=";", lineterminator="\n")
    escritor.writeheader()
    for e in escolas:
        escritor.writerow(_linha_microdados(e, g.rng))
    return buffer.getvalue().encode("latin-1")


# ---------------------------------------------------------------- conjunto completo

ARQUIVOS = {
    "cadastro": "cadastro_sintetico.xlsx",
    "cadastro_novos": "cadastro_sintetico_novos.xlsx",
    "atividade": "participantes_moodle_sintetico.txt",
    "escolas": "escolas_sinteticas_formato_microdados.csv",
    "cadastro_atualizacao": "cadastro_sintetico_atualizacao.xlsx",
    "cadastro_sem_email": "cadastro_sintetico_sem_coluna_email.xlsx",
    "atividade_nova": "participantes_moodle_sintetico_nova_exportacao.txt",
}


def gerar_arquivos(destino: Path, semente: int = 2026) -> dict[str, Path]:
    destino.mkdir(parents=True, exist_ok=True)
    pessoas, escolas, g = gerar_base(semente)
    rng = g.rng
    municipais = [p for p in pessoas if p.esfera == "Municipal"]
    estaduais = [p for p in pessoas if p.esfera == "Estadual"]
    linhas = _imperfeicoes([_linha_cadastro(p, rng) for p in municipais], g)
    linhas_novos = [_linha_cadastro(p, rng) for p in estaduais]
    caminhos = {chave: destino / nome for chave, nome in ARQUIVOS.items()}
    escrever_xlsx(caminhos["cadastro"], CABECALHOS_CADASTRO, linhas)
    escrever_xlsx(caminhos["cadastro_novos"], CABECALHOS_CADASTRO, linhas_novos)

    contas = gerar_contas(pessoas, linhas + linhas_novos, g)
    caminhos["atividade"].write_text(texto_moodle(contas), encoding="utf-8")
    caminhos["atividade_nova"].write_text(texto_moodle(avancar_contas(contas, g, 4.6)), encoding="utf-8")

    # A base escolar contém as escolas do cadastro (menos algumas) e outras escolas das mesmas UFs.
    nao_localizadas = set(rng.sample([e.inep for e in escolas], 9))
    extras = []
    municipios = _municipios_norte()
    for uf in PESOS_UF:
        for _ in range(60):
            cod, nome_mun = rng.choice(municipios[uf])
            extras.append(g.escola(uf, cod, nome_mun))
    na_base = [e for e in escolas if e.inep not in nao_localizadas] + extras
    caminhos["escolas"].write_bytes(csv_microdados(na_base, g))

    # Variantes para demonstrar a atualização: nova versão do cadastro e arquivo com erro estrutural.
    idx = {h: i for i, h in enumerate(CABECALHOS_CADASTRO)}
    atualizadas = [list(l) for l in linhas]
    for i in rng.sample(range(len(atualizadas)), 6):
        atualizadas[i] = None
    atualizadas = [l for l in atualizadas if l is not None]
    for linha in rng.sample(atualizadas, 10):
        linha[idx["Situação"]] = "Recusou"
    for linha in rng.sample(atualizadas, 3):
        linha[idx["E-mail"]] = g.email(linha[idx["Nome"]])
    novos = []
    for _ in range(9):
        uf = rng.choice(("PA", "AM", "TO"))
        cod, nome_mun = rng.choice(municipios[uf])
        esc = g.escola(uf, cod, nome_mun)
        for cargo in ("Diretor Escolar", "Coordenador Pedagógico"):
            novos.append(_linha_cadastro(_pessoa(g, esc, nome_mun, cod, "Municipal", g.nome(), cargo), rng))
    escrever_xlsx(caminhos["cadastro_atualizacao"], CABECALHOS_CADASTRO, atualizadas + novos)
    sem_email = [h for h in CABECALHOS_CADASTRO if h != "E-mail"]
    escrever_xlsx(caminhos["cadastro_sem_email"], sem_email,
                  [[v for h, v in zip(CABECALHOS_CADASTRO, l) if h != "E-mail"] for l in linhas[:50]])
    return caminhos


def popular_repositorio(repo, pseudo, caminhos: dict[str, Path], usuario: str = "sistema (dados sintéticos)") -> None:
    """Importa os arquivos sintéticos pelo mesmo fluxo usado com dados reais."""
    from . import importacao, school_data
    from .loaders import CAMPOS_ATIVIDADE, CAMPOS_CADASTRO, ler_tabela

    tabelas = [ler_tabela(caminhos[k].name, caminhos[k].read_bytes(), CAMPOS_CADASTRO)
               for k in ("cadastro", "cadastro_novos")]
    importacao.confirmar(repo, importacao.preparar_cadastro(tabelas, pseudo, hoje=date(2026, 10, 20)), usuario)
    atividade = ler_tabela(caminhos["atividade"].name, caminhos["atividade"].read_bytes(), CAMPOS_ATIVIDADE,
                           permitidos=("txt", "xlsx", "csv"))
    previa = importacao.preparar_atividade([atividade], pseudo, REFERENCIA_EXPORTACAO, "America/Sao_Paulo",
                                           config.PARAMETROS_PADRAO["papeis_cursista"],
                                           agora=REFERENCIA_EXPORTACAO + timedelta(hours=2))
    importacao.confirmar(repo, previa, usuario)
    dados, meta = school_data.ler_microdados(caminhos["escolas"].read_bytes(), caminhos["escolas"].name)
    previa = school_data.preparar_escolas(
        school_data.normalizar_microdados(dados), meta, school_data.FONTE_SINTETICA,
        [{"arquivo": caminhos["escolas"].name, "linhas": int(len(dados))}],
    )
    importacao.confirmar(repo, previa, usuario)
