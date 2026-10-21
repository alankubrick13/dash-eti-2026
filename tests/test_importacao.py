"""Validação, duplicidades e minimização de dados no pipeline de importação."""

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from conftest import cpf, linha_cadastro, tabela

from src.importacao import comparar_importacoes, preparar_atividade, preparar_cadastro
from src.loaders import CABECALHOS_MOODLE_TEXTO
from src.persistence import COLUNAS


def _previa(cabecalhos, linhas, pseudo):
    return preparar_cadastro([tabela("cad.xlsx", cabecalhos, linhas)], pseudo, hoje=date(2026, 10, 20))


def test_registros_invalidos_sao_sinalizados_e_nao_excluidos(cabecalhos_cadastro, pseudo):
    linhas = [
        linha_cadastro("ANA PAULA SOUZA", email="ana.paula@correio"),  # e-mail inválido
        linha_cadastro("BRUNO COSTA", email="bruno@correio.example", inep=None),  # sem INEP
        linha_cadastro("CARLA DIAS", email="carla@correio.example", inep=1501234),  # INEP com 7 dígitos
        linha_cadastro("DANIEL REIS", email="daniel@correio.example", nascimento="31/02/1980"),
        linha_cadastro("ELISA MOTA", email="elisa@correio.example", cod_ibge=1302603),  # IBGE do AM numa linha do PA
    ]
    previa = _previa(cabecalhos_cadastro, linhas, pseudo)
    assert previa.pode_confirmar
    assert len(previa.registros) == 5
    codigos = dict(zip(previa.registros["nome"], previa.registros["problemas"]))
    assert "email_invalido" in codigos["ANA PAULA SOUZA"]
    assert "inep_ausente" in codigos["BRUNO COSTA"]
    assert "inep_invalido" in codigos["CARLA DIAS"]
    assert "nascimento_invalido" in codigos["DANIEL REIS"]
    assert "ibge_uf_divergente" in codigos["ELISA MOTA"]
    assert previa.resumo["n_com_problemas"] == 5


def test_inep_e_ibge_viram_texto_de_8_e_7_digitos(cabecalhos_cadastro, pseudo):
    previa = _previa(cabecalhos_cadastro, [linha_cadastro(inep=15012345, cod_ibge=1501402)], pseudo)
    registro = previa.registros.iloc[0]
    assert registro["inep"] == "15012345" and isinstance(registro["inep"], str)
    assert registro["cod_ibge"] == "1501402" and registro["cod_ibge_status"] == "valido"


def test_duplicidades_por_cpf_email_e_linha(cabecalhos_cadastro, pseudo):
    mesma_pessoa = cpf(7)
    linhas = [
        linha_cadastro("ANA SOUZA", email="ana@correio.example", cpf_valor=mesma_pessoa),
        linha_cadastro("ANA SOUZA", email="ana.souza@mail.example", cpf_valor=mesma_pessoa),  # mesmo CPF
        linha_cadastro("JOAO LIMA", email="escola@correio.example"),
        linha_cadastro("PEDRO REIS", email="escola@correio.example"),  # e-mail compartilhado
        linha_cadastro("RITA ALVES", email="rita@correio.example"),
        linha_cadastro("RITA ALVES", email="rita@correio.example"),  # linha idêntica
    ]
    previa = _previa(cabecalhos_cadastro, linhas, pseudo)
    reg = previa.registros
    assert reg.loc[0, "dup_cpf"] == reg.loc[1, "dup_cpf"] is not None
    assert reg.loc[2, "dup_email"] == reg.loc[3, "dup_email"] is not None
    assert reg.loc[4, "dup_linha"] == reg.loc[5, "dup_linha"] is not None
    # Mesmo CPF => mesma pessoa; e-mail compartilhado entre pessoas diferentes => pessoas distintas
    assert reg.loc[0, "chave_pessoa"] == reg.loc[1, "chave_pessoa"]
    assert reg.loc[2, "chave_pessoa"] != reg.loc[3, "chave_pessoa"]
    assert previa.resumo["n_pessoas"] == 4  # Ana (2 registros), João, Pedro, Rita (2 registros)
    assert previa.resumo["n_duplicados"] == 6


def test_cpf_e_nascimento_nao_sao_persistidos(cabecalhos_cadastro, pseudo):
    valor = cpf(11)
    previa = _previa(cabecalhos_cadastro, [linha_cadastro("ANA SOUZA", cpf_valor=valor, nascimento="02/03/1977")], pseudo)
    assert "cpf" not in previa.registros.columns and "data_nascimento" not in previa.registros.columns
    texto = " ".join(str(v) for v in previa.registros.iloc[0].tolist())
    digitos = valor.replace(".", "").replace("-", "")
    assert valor not in texto and digitos not in texto and "1977" not in texto
    assert previa.registros.iloc[0]["chave_pessoa"].startswith("cpf:")


def test_coluna_obrigatoria_ausente_bloqueia(cabecalhos_cadastro, pseudo):
    sem_email = [h for h in cabecalhos_cadastro if h != "E-mail"]
    linha = [v for h, v in zip(cabecalhos_cadastro, linha_cadastro()) if h != "E-mail"]
    previa = _previa(sem_email, [linha], pseudo)
    assert not previa.pode_confirmar
    assert any("E-mail" in b for b in previa.bloqueios)


def test_multiplos_arquivos_formam_o_cadastro(cabecalhos_cadastro, pseudo):
    t1 = tabela("principal.xlsx", cabecalhos_cadastro, [linha_cadastro("ANA SOUZA", email="ana@correio.example")])
    estadual = linha_cadastro("BRUNO LIMA", email="bruno@correio.example", cod_ibge=11, uf="RO", inep=11012345)
    t2 = tabela("novos.xlsx", cabecalhos_cadastro, [estadual])
    previa = preparar_cadastro([t1, t2], pseudo, hoje=date(2026, 10, 20))
    assert set(previa.registros["arquivo_origem"]) == {"principal.xlsx", "novos.xlsx"}
    assert previa.registros.iloc[1]["cod_ibge_status"] == "valido"  # código de UF para ente estadual


def _atividade(linhas):
    return tabela("participantes.txt", CABECALHOS_MOODLE_TEXTO, linhas)


def test_atividade_tempo_relativo_com_e_sem_referencia(pseudo):
    linhas = [["ANA SOUZA", "ana@mail.example", "Estudante", "Para 1", "3 dias 2 horas", "Ativo"],
              ["RITA ALVES", "rita@formacao.example", "Formador (Tutor não editor)", "Para 1", "Nunca", "Ativo"]]
    sem_ref = preparar_atividade([_atividade(linhas)], pseudo, None, "America/Sao_Paulo", ["Estudante"])
    reg = sem_ref.registros
    assert reg.loc[0, "acesso_tipo"] == "relativo"
    assert reg.loc[0, "acesso_segundos"] == 3 * 86400 + 2 * 3600
    assert reg.loc[0, "acesso_momento"] is None  # sem data de exportação, nenhuma data é inventada
    assert any("não foi informado" in a for a in sem_ref.avisos)
    assert (reg.loc[0, "eh_cursista"], reg.loc[0, "eh_equipe"]) == (1, 0)
    assert (reg.loc[1, "eh_cursista"], reg.loc[1, "eh_equipe"]) == (0, 1)

    referencia = datetime(2026, 10, 19, 17, 30, tzinfo=ZoneInfo("America/Sao_Paulo"))
    com_ref = preparar_atividade([_atividade(linhas)], pseudo, referencia, "America/Sao_Paulo", ["Estudante"])
    momento = datetime.fromisoformat(com_ref.registros.loc[0, "acesso_momento"])
    assert momento == datetime(2026, 10, 16, 18, 30, tzinfo=timezone.utc)
    assert "19/10/2026 17:30" in com_ref.referencia_descricao


def test_atividade_data_absoluta_contada_ate_a_referencia(pseudo):
    linhas = [["ANA SOUZA", "ana@mail.example", "Estudante", "Para 1", "10/10/2026 08:00", "Ativo"]]
    referencia = datetime(2026, 10, 20, 8, 0, tzinfo=ZoneInfo("America/Sao_Paulo"))
    previa = preparar_atividade([_atividade(linhas)], pseudo, referencia, "America/Sao_Paulo", ["Estudante"])
    assert previa.registros.loc[0, "acesso_tipo"] == "absoluto"
    assert previa.registros.loc[0, "acesso_segundos"] == 10 * 86400
    assert previa.registros.loc[0, "acesso_base"] == "referencia_informada"


def test_comparacao_entre_importacoes(cabecalhos_cadastro, pseudo):
    antes = _previa(cabecalhos_cadastro, [linha_cadastro("ANA SOUZA", email="ana@correio.example"),
                                          linha_cadastro("BRUNO LIMA", email="bruno@correio.example")], pseudo)
    depois = _previa(cabecalhos_cadastro, [linha_cadastro("ANA SOUZA", email="ana.nova@correio.example"),
                                           linha_cadastro("CARLA DIAS", email="carla@correio.example")], pseudo)
    dif = comparar_importacoes("cadastro", depois.registros, antes.registros)
    assert (dif["entraram"], dif["sairam"], dif["permaneceram"]) == (1, 1, 1)
    assert dif["alteracoes_por_campo"]["E-mail"] == 1  # mudança de e-mail da mesma pessoa (mesmo CPF)


def test_colunas_gravadas_correspondem_ao_esquema(cabecalhos_cadastro, pseudo):
    previa = _previa(cabecalhos_cadastro, [linha_cadastro()], pseudo)
    assert list(previa.registros.columns) == COLUNAS["cadastro"]
