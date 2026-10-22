"""Pipeline de importação aplicado aos arquivos reais: validação, duplicidades, minimização e comparação.

Casos de erro (coluna ausente, linha repetida) são derivados dos próprios arquivos reais.
"""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from conftest import FUSO, PAPEIS_CURSISTA, confere, quadro

from src.importacao import comparar_importacoes, preparar_atividade, preparar_cadastro
from src.loaders import CAMPOS_CADASTRO, mapear_colunas
from src.normalization import interpretar_data, validar_cpf
from src.persistence import COLUNAS


def sem_coluna(tabela, interno: str):
    """A tabela real sem a coluna de um campo (como se o arquivo viesse sem ela)."""
    mapa = mapear_colunas(tabela.cabecalhos, CAMPOS_CADASTRO).original_para_interno
    original = next(c for c, i in mapa.items() if i == interno)
    return replace(tabela, cabecalhos=[c for c in tabela.cabecalhos if c != original],
                   dados=tabela.dados.drop(columns=[original]))


def test_cadastro_real_validado_sem_excluir_registros(previa_cadastro, tabelas_cadastro):
    assert previa_cadastro.pode_confirmar
    assert len(previa_cadastro.registros) == sum(len(t.dados) for t in tabelas_cadastro)
    assert list(previa_cadastro.registros.columns) == COLUNAS["cadastro"]
    assert set(previa_cadastro.registros["arquivo_origem"]) == {t.arquivo for t in tabelas_cadastro}


def test_problemas_sinalizados_conforme_cada_campo(previa_cadastro):
    reg = previa_cadastro.registros
    esperado = {
        "email_invalido": reg["email_status"] == "invalido", "email_ausente": reg["email_status"] == "ausente",
        "cpf_invalido": reg["cpf_status"] == "invalido", "cpf_ausente": reg["cpf_status"] == "ausente",
        "inep_ausente": reg["inep_status"] == "ausente", "inep_invalido": reg["inep_status"] == "invalido",
        "ibge_uf_divergente": reg["cod_ibge_status"] == "uf_divergente",
        "ibge_inexistente": reg["cod_ibge_status"] == "inexistente",
        "duplicado_cpf": reg["dup_cpf"].notna(), "duplicado_email": reg["dup_email"].notna(),
        "linha_repetida": reg["dup_linha"].notna(),
    }
    divergentes = sum(int((reg["problemas"].map(lambda p, c=codigo: c in p) != mascara).sum())
                      for codigo, mascara in esperado.items())
    confere(divergentes == 0, f"{divergentes} registro(s) real(is) com problema sinalizado de forma incoerente")
    assert previa_cadastro.resumo["n_com_problemas"] == int((reg["problemas"].map(len) > 0).sum())


def test_codigos_gravados_como_texto(previa_cadastro):
    reg = previa_cadastro.registros
    inep = reg.loc[reg["inep_status"] == "valido", "inep"]
    ibge = reg.loc[reg["cod_ibge_status"] == "valido", "cod_ibge"]
    confere(len(inep) > 0 and inep.map(lambda c: isinstance(c, str) and len(c) == 8 and c.isdigit()).all(),
            "código INEP real não gravado como texto de 8 dígitos")
    confere(ibge.map(lambda c: isinstance(c, str) and len(c) in (2, 7) and c.isdigit()).all(),
            "código IBGE real não gravado como texto de 2 ou 7 dígitos")


def test_duplicidades_reais_e_linha_repetida(previa_cadastro, tabelas_cadastro, pseudo):
    reg = previa_cadastro.registros
    mesma_pessoa = reg.dropna(subset=["dup_cpf"]).groupby("dup_cpf")["chave_pessoa"].nunique()
    confere((mesma_pessoa == 1).all(), "registros com o mesmo CPF tratados como pessoas diferentes")
    assert previa_cadastro.resumo["n_pessoas"] == reg["chave_pessoa"].nunique()
    # A primeira linha real repetida no arquivo: sinalizada, sem ser excluída
    primeira = tabelas_cadastro[0]
    repetida = replace(primeira, dados=pd.concat([primeira.dados, primeira.dados.iloc[[0]]], ignore_index=True))
    previa = preparar_cadastro([repetida, *tabelas_cadastro[1:]], pseudo)
    assert len(previa.registros) == len(reg) + 1
    confere(int(previa.registros["dup_linha"].notna().sum()) >= 2, "linha repetida não sinalizada")


def test_cpf_e_nascimento_reais_nao_sao_gravados(previa_cadastro, tabelas_cadastro):
    reg = previa_cadastro.registros
    assert "cpf" not in reg.columns and "data_nascimento" not in reg.columns
    texto = "\n".join(" ".join(map(str, linha)) for linha in reg.itertuples(index=False))
    dados = quadro(tabelas_cadastro, CAMPOS_CADASTRO)
    cpfs = {validar_cpf(c)[0] for c in dados["cpf"] if validar_cpf(c)[1].startswith("valido")}
    nascimentos = {interpretar_data(d)[0] for d in dados["data_nascimento"] if interpretar_data(d)[1] == "valida"}
    vazados = sum(c in texto for c in cpfs)
    vazados += sum(d.strftime("%d/%m/%Y") in texto or d.isoformat() in texto for d in nascimentos)
    confere(len(cpfs) > 0 and vazados == 0, f"{vazados} CPF(s) ou data(s) de nascimento real(is) nos registros")
    confere(reg["chave_pessoa"].str.match(r"^(cpf|email|nome):").all(), "chave de pessoa fora do padrão pseudônimo")


def test_coluna_obrigatoria_ausente_bloqueia(tabelas_cadastro, pseudo):
    previa = preparar_cadastro([sem_coluna(t, "email") for t in tabelas_cadastro], pseudo)
    assert not previa.pode_confirmar
    assert any("E-mail" in b for b in previa.bloqueios)


def test_entes_estaduais_com_codigo_da_uf(previa_cadastro):
    reg = previa_cadastro.registros
    estaduais = reg[reg["cod_ibge"].fillna("").str.len() == 2]
    if estaduais.empty:
        pytest.skip("o cadastro real não tem entes estaduais")
    confere((estaduais["cod_ibge_status"] == "valido").all(), "ente estadual com código de UF marcado como inválido")


def test_atividade_real_sem_data_de_exportacao(previa_atividade, tabela_atividade):
    reg = previa_atividade.registros
    assert len(reg) == len(tabela_atividade.dados)
    confere(reg.loc[reg["acesso_tipo"] == "relativo", "acesso_momento"].isna().all(),
            "tempo relativo virou data sem a data de exportação")
    assert any("não foi informado" in a for a in previa_atividade.avisos)
    eh_estudante = reg["papeis"].fillna("").str.contains("Estudante")
    confere(((reg["eh_cursista"] == 1) == eh_estudante).all(), "papel de cursista classificado de forma incoerente")
    confere(((reg["eh_equipe"] == 1) == (~eh_estudante & reg["papeis"].notna())).all(),
            "conta da equipe classificada de forma incoerente")


def test_atividade_real_com_referencia(tabela_atividade, arquivo_atividade, pseudo):
    """Referência real: o momento em que o arquivo da plataforma foi salvo neste computador."""
    referencia = datetime.fromtimestamp(arquivo_atividade.stat().st_mtime, ZoneInfo(FUSO))
    previa = preparar_atividade([tabela_atividade], pseudo, referencia, FUSO, PAPEIS_CURSISTA)
    reg = previa.registros[previa.registros["acesso_tipo"] == "relativo"]
    calculados = [datetime.fromisoformat(m) for m in reg["acesso_momento"]]
    esperados = [referencia.astimezone(timezone.utc) - timedelta(seconds=s) for s in reg["acesso_segundos"]]
    confere(len(reg) > 0 and all(abs((c - e).total_seconds()) < 1 for c, e in zip(calculados, esperados)),
            "data do último acesso não confere com a referência menos o tempo relativo")
    assert referencia.strftime("%d/%m/%Y %H:%M") in previa.referencia_descricao


def test_comparacao_entre_versoes_reais_do_cadastro(tabelas_cadastro, previa_cadastro, pseudo):
    if len(tabelas_cadastro) < 2:
        pytest.skip("só há uma planilha do cadastro")
    principal = preparar_cadastro(tabelas_cadastro[:1], pseudo)
    dif = comparar_importacoes("cadastro", previa_cadastro.registros, principal.registros)
    antes, depois = set(principal.registros["chave_pessoa"]), set(previa_cadastro.registros["chave_pessoa"])
    assert (dif["entraram"], dif["sairam"], dif["permaneceram"]) == (len(depois - antes), len(antes - depois),
                                                                     len(antes & depois))
    assert dif["registros_depois"] - dif["registros_antes"] == len(tabelas_cadastro[1].dados) + sum(
        len(t.dados) for t in tabelas_cadastro[2:])
