import io
import zipfile

import openpyxl
import pytest

from src.loaders import (
    CAMPOS_ATIVIDADE,
    CAMPOS_CADASTRO,
    ErroImportacao,
    identificar_formato,
    ler_tabela,
    ler_texto_participantes_moodle,
    listar_abas,
    mapear_colunas,
)


def _xlsx(linhas: list[list], aba: str = "Dados") -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = aba
    for linha in linhas:
        ws.append(linha)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def test_xlsx_com_titulo_acima_do_cabecalho_e_tipos_preservados():
    conteudo = _xlsx([
        ["Relatório de inscrições"], [],
        ["UF", "Nome", "E-mail", "CPF", "INEP", "Código local"],
        ["PA", "ANA LIMA", "ana@mail.example", "012.345.678-90", 15012345, "00123"],
    ])
    t = ler_tabela("cadastro.xlsx", conteudo, CAMPOS_CADASTRO)
    assert t.linha_cabecalho == 3
    assert t.cabecalhos == ["UF", "Nome", "E-mail", "CPF", "INEP", "Código local"]
    linha = t.dados.iloc[0]
    assert linha["INEP"] == 15012345  # número do Excel preservado como veio; vira texto na normalização
    assert linha["Código local"] == "00123"  # texto com zeros à esquerda intacto
    assert linha["CPF"] == "012.345.678-90"
    assert int(linha["__linha__"]) == 4  # linha real na planilha, para auditoria


def test_xlsx_varias_abas():
    wb = openpyxl.Workbook()
    wb.active.title = "Resumo"
    wb.create_sheet("Dados").append(["Nome", "E-mail"])
    wb["Dados"].append(["ANA", "ana@mail.example"])
    buffer = io.BytesIO()
    wb.save(buffer)
    assert listar_abas(buffer.getvalue()) == ["Resumo", "Dados"]
    t = ler_tabela("x.xlsx", buffer.getvalue(), CAMPOS_CADASTRO, aba="Dados")
    assert len(t.dados) == 1


def test_csv_ponto_e_virgula_em_cp1252():
    texto = "Nome;E-mail;INEP\nJOÃO SÉRGIO;joao@mail.example;13012345\n"
    t = ler_tabela("cad.csv", texto.encode("cp1252"), CAMPOS_CADASTRO)
    assert t.cabecalhos == ["Nome", "E-mail", "INEP"]
    assert t.dados.iloc[0]["Nome"] == "JOÃO SÉRGIO"
    assert t.dados.iloc[0]["INEP"] == "13012345"  # CSV: sempre texto


def test_linhas_vazias_sao_ignoradas_e_conteudo_sem_cabecalho_avisado():
    t = ler_tabela("cad.csv", "Nome,E-mail\nANA,ana@mail.example,extra\n,\n".encode(), CAMPOS_CADASTRO)
    assert len(t.dados) == 1
    assert any("sem cabeçalho" in a for a in t.avisos)


TEXTO_MOODLE = (
    "\nDesmarcar todas as seleções\n"
    "\tNomeOrdenar por Nome Ascendente / SobrenomeOrdenar por Sobrenome Ascendente\n"
    "\tEndereço de emailOrdenar por Endereço de email Ascendente\n\tPapéis\n\tGrupos\n"
    "\tÚltimo acesso ao cursoOrdenar por Último acesso ao curso Ascendente\n\tSituação\n"
    "Selecione 'CARLA SOUZA'\n\tCARLA SOUZA\tcarla@mail.example\tEstudante\tPara 1\t3 dias 2 horas\t\nAtivo\n"
    "Selecione 'PEDRO LIMA'\n\tPEDRO LIMA\tpedro@mail.example\tEstudante\tPara 1, Para 2\tNunca\t\nSuspenso\n"
    "Selecione 'RITA ALVES'\n\tRITA ALVES\trita@formacao.example\tFormador (Tutor não editor)\t\t1 hora 5 minutos\t\nAtivo\n"
    "Selecione 'SEM EMAIL'\n\tSEM EMAIL\tsem-email\tEstudante\tPara 3\t2 dias\t\nAtivo\n"
)


def test_texto_copiado_da_pagina_de_participantes():
    registros, origem, nao_reconhecidas = ler_texto_participantes_moodle(TEXTO_MOODLE)
    assert [r[0] for r in registros] == ["CARLA SOUZA", "PEDRO LIMA", "RITA ALVES"]
    assert registros[0][1:] == ["carla@mail.example", "Estudante", "Para 1", "3 dias 2 horas", "Ativo"]
    assert registros[1][3:] == ["Para 1, Para 2", "Nunca", "Suspenso"]
    assert registros[2][3] is None  # sem grupo
    assert len(nao_reconhecidas) == 1  # linha com estrutura de participante sem e-mail: não é descartada em silêncio


def test_ler_tabela_txt_do_moodle_avisa_linhas_nao_lidas():
    t = ler_tabela("participantes.txt", TEXTO_MOODLE.encode(), CAMPOS_ATIVIDADE, permitidos=("txt",))
    assert t.formato == "texto do Moodle"
    assert len(t.dados) == 3
    assert any("não foram lidas" in a for a in t.avisos)
    mapa = mapear_colunas(t.cabecalhos, CAMPOS_ATIVIDADE)
    assert not mapa.faltando_obrigatorios


def test_mapeamento_de_cabecalhos_variantes_e_manual():
    mapa = mapear_colunas(["Raça/Cor", "Endereço de e-mail", "NOME COMPLETO", "Cód. INEP", "Outra"], CAMPOS_CADASTRO)
    assert mapa.original_para_interno == {"Raça/Cor": "raca_cor", "Endereço de e-mail": "email",
                                          "NOME COMPLETO": "nome", "Cód. INEP": "inep"}
    assert mapa.nao_mapeadas == ["Outra"]
    manual = mapear_colunas(["Nome", "Correio"], CAMPOS_CADASTRO, manual={"email": "Correio"})
    assert manual.original_para_interno["Correio"] == "email"
    assert not manual.faltando_obrigatorios
    assert mapear_colunas(["Nome"], CAMPOS_CADASTRO).faltando_obrigatorios == ["E-mail"]


def test_rejeita_arquivos_incompativeis():
    with pytest.raises(ErroImportacao, match="extensão"):
        identificar_formato("planilha.xls", b"qualquer", ("xlsx", "csv"))
    with pytest.raises(ErroImportacao, match="assinatura"):
        identificar_formato("falso.xlsx", b"isto nao e zip", ("xlsx",))
    with pytest.raises(ErroImportacao, match="vazio"):
        identificar_formato("vazio.csv", b"", ("csv",))
    with pytest.raises(ErroImportacao, match="texto"):
        identificar_formato("binario.csv", b"a\x00b", ("csv",))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("xl/workbook.xml", "<workbook/>")
        zf.writestr("xl/vbaProject.bin", b"macro")
    with pytest.raises(ErroImportacao, match="macros"):
        identificar_formato("macro.xlsx", buffer.getvalue(), ("xlsx",))


def test_mensagens_de_erro_nao_repetem_conteudo_das_celulas():
    with pytest.raises(ErroImportacao) as erro:
        identificar_formato("dados.csv", "maria@mail.example;123.456.789-00\x00".encode(), ("csv",))
    assert "maria" not in str(erro.value) and "123.456" not in str(erro.value)
