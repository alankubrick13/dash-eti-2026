"""Base escolar: leitura dos microdados, Catálogo, enriquecimento por código INEP e cache de download."""

import hashlib
import io
import json
import zipfile

import pandas as pd
import pytest
from conftest import tabela

from src import school_data
from src.loaders import ErroImportacao

CABECALHO = ("NU_ANO_CENSO;NO_REGIAO;SG_UF;CO_UF;NO_MUNICIPIO;CO_MUNICIPIO;NO_ENTIDADE;CO_ENTIDADE;TP_DEPENDENCIA;"
             "TP_LOCALIZACAO;TP_LOCALIZACAO_DIFERENCIADA;TP_SITUACAO_FUNCIONAMENTO;IN_INF;IN_FUND;IN_FUND_AI;IN_FUND_AF;"
             "IN_MED;IN_INTERNET;QT_MAT_BAS;QT_MAT_FUND_INT;QT_MAT_INF_INT;QT_MAT_MED_INT")
LINHAS = [
    "2024;Norte;PA;15;Belém;1501402;ESCOLA MUNICIPAL ÁGUA LIMPA;15012345;3;1;0;1;1;1;1;0;0;1;420;80;0;0",
    "2024;Norte;AM;13;Manaus;1302603;ESCOLA ESTADUAL RIO NEGRO;13012345;2;2;2;1;0;1;0;1;1;0;900;0;0;120",
    "2024;Nordeste;CE;23;Fortaleza;2304400;ESCOLA DE OUTRA REGIAO;23012345;3;1;0;2;1;1;1;0;0;1;300;0;0;0",
]


def _csv() -> bytes:
    return ("\n".join([CABECALHO, *LINHAS]) + "\n").encode("latin-1")


def _zip(md5: str | None = None) -> bytes:
    csv = _csv()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("microdados_censo_escolar_2024/dados/microdados_ed_basica_2024.csv", csv)
        zf.writestr("microdados_censo_escolar_2024/dados/md5_microdados_ed_basica_2024.txt",
                    f"{(md5 or hashlib.md5(csv).hexdigest()).upper()} *microdados_ed_basica_2024.csv\n")
    return buffer.getvalue()


def test_microdados_csv_filtrados_por_codigo_e_uf():
    dados, meta = school_data.ler_microdados(_csv(), "escolas.csv", codigos={"23012345"}, ufs={"PA"})
    assert sorted(dados["CO_ENTIDADE"]) == ["15012345", "23012345"]
    assert meta["ano_referencia"] == 2024
    assert "QT_MAT_FUND_AI_INT" in meta["variaveis_ausentes"]
    assert meta["md5_confere"] is None


def test_microdados_zip_com_md5_publicado():
    dados, meta = school_data.ler_microdados(_zip(), "pacote.zip", ufs={"PA", "AM"})
    assert len(dados) == 2 and meta["md5_confere"] is True
    _, meta_ruim = school_data.ler_microdados(_zip(md5="0" * 32), "pacote.zip", ufs={"PA"})
    assert meta_ruim["md5_confere"] is False
    previa = school_data.preparar_escolas(school_data.normalizar_microdados(dados), meta_ruim,
                                          school_data.FONTE_MICRODADOS, [{"arquivo": "pacote.zip"}])
    assert not previa.pode_confirmar  # arquivo possivelmente corrompido não é aceito


def test_formato_2025_com_tabelas_separadas():
    escola = ("NU_ANO_CENSO;SG_UF;NO_MUNICIPIO;CO_MUNICIPIO;NO_ENTIDADE;CO_ENTIDADE;TP_DEPENDENCIA;TP_LOCALIZACAO;"
              "TP_SITUACAO_FUNCIONAMENTO;IN_EJA;IN_COMUM_CRECHE;IN_INTERNET\n"
              "2025;PA;Belém;1501402;ESCOLA A;15012345;3;1;1;0;1;1\n"
              "2025;AM;Manaus;1302603;ESCOLA B;13012345;2;1;1;0;0;0\n").encode("latin-1")
    matricula = ("NU_ANO_CENSO;CO_ENTIDADE;NO_ENTIDADE;QT_MAT_BAS;QT_MAT_INF;QT_MAT_FUND_AI;QT_MAT_FUND_AF;QT_MAT_MED;"
                 "QT_MAT_EJA;QT_MAT_BAS_INT;QT_MAT_INF_INT;QT_MAT_FUND_INT;QT_MAT_MED_INT\n"
                 "2025;15012345;ESCOLA A;300;0;200;100;0;0;80;0;80;0\n"
                 "2025;13012345;ESCOLA B;500;0;0;0;450;50;90;0;0;90\n").encode("latin-1")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("m_2025_v2/dados/Tabela_Escola_2025_V2.csv", escola)
        zf.writestr("m_2025_v2/dados/Tabela_Matricula_2025_V2.csv", matricula)
        zf.writestr("m_2025_v2/dados/md5_microdados_ed_basica_2025.txt",
                    f"{hashlib.md5(escola).hexdigest().upper()} *Tabela_Escola_2025_v2.csv\n"
                    f"{hashlib.md5(matricula).hexdigest().upper()} *Tabela_Matricula_2025_v2.csv\n")
    dados, meta = school_data.ler_microdados(buffer.getvalue(), "pacote2025.zip", codigos={"15012345", "13012345"})
    assert meta["ano_referencia"] == 2025 and meta["md5_confere"] is True
    assert meta["formato"].startswith("Tabela_Escola")
    assert "IN_INF" in meta["etapas_derivadas_de_matriculas"]
    escolas = school_data.normalizar_microdados(dados).set_index("co_entidade")
    # IN_COMUM_CRECHE (educação especial em classe comum) NÃO indica oferta de creche
    assert escolas.loc["15012345", "etapas"] == "Ensino Fundamental – anos iniciais; Ensino Fundamental – anos finais"
    assert escolas.loc["13012345", "etapas"] == "Ensino Médio"  # IN_EJA oficial = 0, embora haja QT_MAT_EJA
    assert escolas.loc["13012345", "atributos"]["QT_MAT_MED_INT"] == "90"


def test_zip_sem_arquivo_de_escolas_e_rejeitado():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("leia-me.txt", "nada")
    with pytest.raises(ErroImportacao):
        school_data.ler_microdados(buffer.getvalue(), "outro.zip")


def test_rotulos_oficiais():
    dados, _ = school_data.ler_microdados(_csv(), "escolas.csv")
    escolas = school_data.normalizar_microdados(dados).set_index("co_entidade")
    assert escolas.loc["15012345", "dependencia"] == "Municipal"
    assert escolas.loc["15012345", "categoria_administrativa"] == "Pública"
    assert escolas.loc["13012345", "localizacao"] == "Rural"
    assert escolas.loc["13012345", "localizacao_diferenciada"] == "Terra indígena"
    assert escolas.loc["23012345", "situacao_funcionamento"] == "Paralisada"
    assert escolas.loc["15012345", "etapas"] == "Educação Infantil; Ensino Fundamental – anos iniciais"
    assert escolas.loc["13012345", "atributos"]["QT_MAT_MED_INT"] == "120"


def test_enriquecimento_distingue_ausente_invalido_e_nao_localizado():
    dados, _ = school_data.ler_microdados(_csv(), "escolas.csv")
    escolas = school_data.normalizar_microdados(dados)
    cursistas = pd.DataFrame({
        "inep": [None, "1501234", "15012345", "15999999"],
        "inep_status": ["ausente", "invalido", "valido", "valido"],
    })
    resultado = school_data.enriquecer(cursistas, escolas)
    assert resultado["situacao_inep"].tolist() == [
        school_data.SITUACAO_INEP_AUSENTE, school_data.SITUACAO_INEP_INVALIDO,
        school_data.SITUACAO_INEP_LOCALIZADO, school_data.SITUACAO_INEP_NAO_LOCALIZADO]
    assert resultado.loc[2, "escola_oficial"] == "ESCOLA MUNICIPAL ÁGUA LIMPA"
    assert pd.isna(resultado.loc[3, "escola_oficial"])  # nada é inventado para código não localizado
    sem_base = school_data.enriquecer(cursistas, escolas.iloc[0:0])
    assert sem_base.loc[2, "situacao_inep"] == school_data.SITUACAO_INEP_SEM_BASE


def test_catalogo_de_escolas_com_coordenadas_validadas():
    cab = ["Restrição de Atendimento", "Escola", "Código INEP", "UF", "Município", "Dependência Administrativa",
           "Latitude", "Longitude"]
    t = tabela("catalogo.xlsx", cab, [
        ["ESCOLA EM FUNCIONAMENTO", "ESCOLA A", 15012345, "PA", "Belém", "Municipal", "-1,4558", "-48,4902"],
        ["ESCOLA EM FUNCIONAMENTO", "ESCOLA B", 13012345, "AM", "Manaus", "Estadual", "95", "-60"],
    ])
    dados, meta = school_data.normalizar_catalogo(t, 2025)
    assert dados.loc[0, "latitude"] == pytest.approx(-1.4558) and dados.loc[0, "longitude"] == pytest.approx(-48.4902)
    assert pd.isna(dados.loc[1, "latitude"])  # fora do território: descartada, não corrigida
    assert meta["ano_referencia"] == 2025 and meta["com_coordenadas"] == 1


def test_catalogo_sem_colunas_obrigatorias():
    with pytest.raises(ErroImportacao):
        school_data.normalizar_catalogo(tabela("x.xlsx", ["Nome", "Cidade"], [["A", "B"]]), 2025)


def test_cadeia_de_certificados_inclui_intermediario(tmp_path):
    caminho = school_data.cadeia_certificados(tmp_path)
    conteudo = open(caminho, encoding="utf-8").read()
    intermediario = school_data.config.ARQ_CERT_INEP.read_text(encoding="utf-8").strip()
    assert intermediario in conteudo and conteudo.count("BEGIN CERTIFICATE") > 100


def test_download_usa_cache(tmp_path, monkeypatch):
    pacote = _zip()
    chamadas = []

    class Resposta:
        def __init__(self, metodo):
            self.headers = {"Content-Length": str(len(pacote)), "Last-Modified": "Wed, 08 Jul 2026 12:22:27 GMT"}
            self.metodo = metodo

        def iter_content(self, tamanho):
            yield pacote

    def falso(metodo, url, verificar, **kwargs):
        chamadas.append(metodo)
        return Resposta(metodo), False

    monkeypatch.setattr(school_data, "_requisitar", falso)
    caminho, meta = school_data.baixar_microdados(2024, tmp_path)
    assert caminho.read_bytes() == pacote and meta["origem_cache"] is False
    assert json.loads(caminho.with_suffix(".json").read_text())["sha256"] == hashlib.sha256(pacote).hexdigest()
    _, meta2 = school_data.baixar_microdados(2024, tmp_path)
    assert meta2["origem_cache"] is True
    assert chamadas == ["HEAD", "GET", "HEAD"]  # o segundo pedido não baixa de novo
    with pytest.raises(ErroImportacao):
        school_data.baixar_microdados(1990, tmp_path)


def test_download_retoma_de_onde_parou(tmp_path, monkeypatch):
    pacote = _zip()
    metade = len(pacote) // 2
    (tmp_path / "microdados_censo_escolar_2024.parcial").write_bytes(pacote[:metade])
    pedidos = []

    class Resposta:
        def __init__(self, inicio):
            self.headers = {"Content-Length": str(len(pacote)), "Last-Modified": "Wed, 08 Jul 2026 12:22:27 GMT"}
            self.status_code = 206 if inicio else 200
            self.inicio = inicio

        def iter_content(self, tamanho):
            yield pacote[self.inicio:]

    def falso(metodo, url, verificar, cabecalhos_extra=None, **kwargs):
        faixa = (cabecalhos_extra or {}).get("Range")
        pedidos.append((metodo, faixa))
        return Resposta(int(faixa.split("=")[1].rstrip("-")) if faixa else 0), False

    monkeypatch.setattr(school_data, "_requisitar", falso)
    caminho, meta = school_data.baixar_microdados(2024, tmp_path)
    assert pedidos[-1] == ("GET", f"bytes={metade}-")
    assert caminho.read_bytes() == pacote
    assert meta["sha256"] == hashlib.sha256(pacote).hexdigest()
