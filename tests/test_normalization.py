from datetime import date, datetime, timezone

import pytest

from src.importacao import carregar_municipios
from src.normalization import (
    chave_comparacao,
    classificar_ibge,
    classificar_inep,
    digitos_de_codigo,
    interpretar_data,
    interpretar_ultimo_acesso,
    normalizar_email,
    normalizar_uf,
    unificar_categorias,
    validar_cpf,
)


@pytest.mark.parametrize("valor, esperado", [
    (" Maria.Silva@Correio.EXAMPLE ", ("maria.silva@correio.example", "valido")),
    ("mailto:ana@escola.example", ("ana@escola.example", "valido")),
    ("<jose@mail.example>", ("jose@mail.example", "valido")),
    ("ana silva@mail.example", ("ana silva@mail.example", "invalido")),
    ("ana@mail", ("ana@mail", "invalido")),
    ("ana..souza@mail.example", ("ana..souza@mail.example", "invalido")),
    ("ana@@mail.example", ("ana@@mail.example", "invalido")),
    ("", (None, "ausente")),
    (None, (None, "ausente")),
])
def test_normalizar_email(valor, esperado):
    assert normalizar_email(valor) == esperado


def test_codigos_preservam_zeros_e_sao_texto():
    assert digitos_de_codigo("0012345") == ("0012345", True)
    assert digitos_de_codigo(13012345) == ("13012345", True)
    assert digitos_de_codigo(13012345.0) == ("13012345", True)
    assert digitos_de_codigo("13012345.0") == ("13012345", True)
    assert digitos_de_codigo("13.012.345") == ("13012345", True)
    assert digitos_de_codigo("13A12345")[1] is False


@pytest.mark.parametrize("valor, status", [
    (13012345, "valido"), ("15012345", "valido"), ("13012345.0", "valido"), ("1301234", "invalido"),
    ("99012345", "invalido"), ("ABC", "invalido"), (None, "ausente"), ("", "ausente"),
])
def test_classificar_inep(valor, status):
    assert classificar_inep(valor)[1] == status


def test_classificar_ibge_com_lista_oficial():
    municipios = carregar_municipios()
    assert municipios is not None and len(municipios) > 5000
    assert classificar_ibge(1302603, "AM", municipios) == ("1302603", "valido")  # Manaus
    assert classificar_ibge("1302603", "PA", municipios)[1] == "uf_divergente"
    assert classificar_ibge(13, "AM", municipios) == ("13", "valido")  # ente estadual
    assert classificar_ibge("1399999", "AM", municipios)[1] == "inexistente"
    assert classificar_ibge("123", "AM", municipios)[1] == "invalido"
    assert classificar_ibge(None, "AM", municipios)[1] == "ausente"


def test_normalizar_uf():
    assert normalizar_uf(" pa ") == ("PA", "valido")
    assert normalizar_uf("Pará") == ("PA", "valido")
    assert normalizar_uf("Amapá") == ("AP", "valido")
    assert normalizar_uf("XX")[1] == "invalido"


def _cpf_com_dv(base9: str) -> str:
    digitos = [int(c) for c in base9]
    for n in (9, 10):
        soma = sum(d * (n + 1 - i) for i, d in enumerate(digitos))
        digitos.append((soma * 10) % 11 % 10)
    return "".join(map(str, digitos))


def test_validar_cpf():
    valido = _cpf_com_dv("123456789")
    assert validar_cpf(f"{valido[:3]}.{valido[3:6]}.{valido[6:9]}-{valido[9:]}") == (valido, "valido")
    assert validar_cpf("111.111.111-11")[1] == "invalido"
    assert validar_cpf(valido[:-1] + str((int(valido[-1]) + 1) % 10))[1] == "invalido"
    assert validar_cpf(None)[1] == "ausente"
    # Célula numérica do Excel que perdeu o zero à esquerda
    com_zero = _cpf_com_dv("012345678")
    assert validar_cpf(int(com_zero)) == (com_zero, "valido_recomposto")
    # Texto com 10 dígitos não é recomposto (não há como saber que era número)
    assert validar_cpf(com_zero[1:])[1] == "invalido"


@pytest.mark.parametrize("valor, esperado", [
    ("14/08/2026", date(2026, 8, 14)), ("2026-08-14", date(2026, 8, 14)),
    ("2026-08-14 00:00:00", date(2026, 8, 14)), (datetime(2026, 8, 14, 9, 0), date(2026, 8, 14)),
    (46248, date(2026, 8, 14)),
])
def test_interpretar_data_valida(valor, esperado):
    assert interpretar_data(valor) == (esperado, "valida")


def test_interpretar_data_invalida_ou_ausente():
    assert interpretar_data("31/02/1980") == (None, "invalida")
    assert interpretar_data("1980-13-01") == (None, "invalida")
    assert interpretar_data(None) == (None, "ausente")


@pytest.mark.parametrize("texto, segundos", [
    ("1 hora 33 minutos", 5580), ("1 hora e 33 minutos", 5580), ("14 dias 22 horas", 14 * 86400 + 22 * 3600),
    ("2 dias", 2 * 86400), ("1 dia", 86400), ("23 minutos 5 segundos", 23 * 60 + 5),
    ("3 days 2 hours", 3 * 86400 + 7200), ("1 ano 15 dias", 365 * 86400 + 15 * 86400), ("agora", 0),
])
def test_ultimo_acesso_relativo(texto, segundos):
    acesso = interpretar_ultimo_acesso(texto)
    assert acesso.tipo == "relativo" and acesso.duracao_s == segundos and acesso.momento is None


def test_ultimo_acesso_sem_informacao_nao_vira_data():
    assert interpretar_ultimo_acesso("Nunca").tipo == "nunca"
    assert interpretar_ultimo_acesso("never").tipo == "nunca"
    assert interpretar_ultimo_acesso("").tipo == "vazio"
    assert interpretar_ultimo_acesso(None).tipo == "vazio"
    # Sobrenomes com "dias"/"mes" não podem ser confundidos com tempo
    assert interpretar_ultimo_acesso("DIAS").tipo == "nao_interpretado"
    assert interpretar_ultimo_acesso("MESQUITA DIAS").tipo == "nao_interpretado"


def test_ultimo_acesso_absoluto_usa_fuso():
    acesso = interpretar_ultimo_acesso("15/10/2024 14:32", "America/Sao_Paulo")
    assert acesso.tipo == "absoluto"
    assert acesso.momento == datetime(2024, 10, 15, 17, 32, tzinfo=timezone.utc)
    manaus = interpretar_ultimo_acesso("15/10/2024 14:32", "America/Manaus")
    assert manaus.momento == datetime(2024, 10, 15, 18, 32, tzinfo=timezone.utc)
    extenso = interpretar_ultimo_acesso("terça-feira, 15 out 2024, 14:32", "America/Sao_Paulo")
    assert extenso.tipo == "absoluto" and extenso.momento == acesso.momento
    assert interpretar_ultimo_acesso("2024-10-15T17:32:00Z").momento == acesso.momento


def test_unificar_categorias_preserva_grafia_mais_comum():
    assert unificar_categorias(["Aceitou", "aceitou ", "ACEITOU", "Aceitou", None, " "]) == [
        "Aceitou", "Aceitou", "Aceitou", "Aceitou", None, None]
    assert unificar_categorias(["Especialização", "Especializacao", "Especializacao"])[0] == "Especializacao"


def test_chave_comparacao():
    assert chave_comparacao("  Maria  da Conceição ") == "maria da conceicao"
    assert chave_comparacao(None) is None
