"""Base escolar com o pacote oficial do Inep (em cache) e os dados do painel.

A leitura do pacote de 2025 leva cerca de um minuto (marca ``lento``; para pular: ``-m "not lento"``).
"""

import hashlib
import io
import json
import os
import zipfile

import pandas as pd
import pytest
from conftest import confere

from src import config, school_data
from src.loaders import ErroImportacao, ler_tabela
from src.normalization import eh_vazio

LIMITE_DOWNLOAD = 2 << 20  # trecho real do pacote usado nos testes de download (2 MB)


@pytest.fixture(scope="module")
def leitura_inep(pacote_inep, base_real):
    cursistas = base_real.cursistas
    codigos = set(cursistas.loc[cursistas["inep_status"] == "valido", "inep"])
    ufs = set(cursistas["uf"].dropna()) | {config.UFS[c[:2]][0] for c in codigos if c[:2] in config.UFS}
    dados, meta = school_data.ler_microdados(pacote_inep, pacote_inep.name, codigos, ufs)
    return codigos, dados, meta, school_data.normalizar_microdados(dados)


@pytest.mark.lento
def test_pacote_oficial_lido_e_conferido(leitura_inep, base_real):
    codigos, dados, meta, escolas = leitura_inep
    assert meta["md5_confere"] is True  # soma publicada pelo Inep dentro do pacote
    assert meta["ano_referencia"] == int(base_real.meta["escolas"]["referencia_em"])
    assert len(escolas) == int(base_real.meta["escolas"]["n_registros"])  # a mesma base gravada no painel
    localizados = codigos & set(escolas["co_entidade"])
    no_painel = set(base_real.cursistas.loc[
        base_real.cursistas["situacao_inep"] == school_data.SITUACAO_INEP_LOCALIZADO, "inep"])
    assert localizados == no_painel


@pytest.mark.lento
def test_etapas_derivadas_das_matriculas(leitura_inep):
    _, _, meta, escolas = leitura_inep
    if not meta["formato"].startswith("Tabela_Escola"):
        pytest.skip("pacote anterior a 2025: etapas vêm dos indicadores oficiais")
    rotulos = dict(school_data.ETAPAS)
    incoerentes = 0
    for etapas, atributos in zip(escolas["etapas"].fillna(""), escolas["atributos"]):
        for var, contagem in school_data.ETAPA_POR_CONTAGEM.items():
            valor = pd.to_numeric(atributos.get(contagem), errors="coerce")
            if eh_vazio(valor):
                continue
            tem = int(valor) > 0
            incoerentes += tem != (rotulos[var] in etapas)
    confere(incoerentes == 0, f"{incoerentes} etapa(s) incoerente(s) com as matrículas declaradas")


@pytest.mark.lento
def test_soma_md5_divergente_bloqueia(leitura_inep, pacote_inep):
    _, _, meta, escolas = leitura_inep
    previa = school_data.preparar_escolas(escolas, {**meta, "md5_confere": False}, school_data.FONTE_MICRODADOS,
                                          [{"arquivo": pacote_inep.name}])
    assert not previa.pode_confirmar


@pytest.mark.lento
def test_rotulos_oficiais_do_inep(leitura_inep):
    _, _, _, escolas = leitura_inep
    for coluna, rotulos in (("dependencia", school_data.DEPENDENCIA), ("localizacao", school_data.LOCALIZACAO),
                            ("localizacao_diferenciada", school_data.LOCALIZACAO_DIFERENCIADA),
                            ("situacao_funcionamento", school_data.SITUACAO_FUNCIONAMENTO)):
        assert set(escolas[coluna].dropna()) <= set(rotulos.values()), coluna


def test_pacote_sem_tabela_de_escolas_e_recusado(arquivos_cadastro):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr(arquivos_cadastro[0].name, arquivos_cadastro[0].read_bytes())
    with pytest.raises(ErroImportacao):
        school_data.ler_microdados(buffer.getvalue(), "pacote.zip")


def test_enriquecimento_pelo_codigo_inep(base_real):
    cursistas = base_real.cursistas[["inep", "inep_status"]]
    resultado = school_data.enriquecer(cursistas, base_real.escolas)
    codigos = set(base_real.escolas["co_entidade"])
    esperado = [
        school_data.SITUACAO_INEP_AUSENTE if s == "ausente" else school_data.SITUACAO_INEP_INVALIDO if s == "invalido"
        else school_data.SITUACAO_INEP_LOCALIZADO if c in codigos else school_data.SITUACAO_INEP_NAO_LOCALIZADO
        for c, s in zip(cursistas["inep"], cursistas["inep_status"])
    ]
    assert resultado["situacao_inep"].tolist() == esperado
    nao_localizados = resultado["situacao_inep"] != school_data.SITUACAO_INEP_LOCALIZADO
    confere(resultado.loc[nao_localizados, "escola_oficial"].isna().all(), "dado oficial atribuído a código não localizado")
    sem_base = school_data.enriquecer(cursistas, base_real.escolas.iloc[0:0])
    assert set(sem_base.loc[cursistas["inep_status"] == "valido", "situacao_inep"]) <= {school_data.SITUACAO_INEP_SEM_BASE}


def test_exportacao_do_catalogo_de_escolas():
    caminho = os.environ.get("ETI_TESTE_CATALOGO")
    if not caminho:
        pytest.skip("nenhuma exportação real do Catálogo de Escolas informada (ETI_TESTE_CATALOGO)")
    from pathlib import Path

    arquivo = Path(caminho)
    tabela = ler_tabela(arquivo.name, arquivo.read_bytes(), school_data.CAMPOS_CATALOGO)
    dados, meta = school_data.normalizar_catalogo(tabela, int(os.environ.get("ETI_TESTE_CATALOGO_ANO", "2025")))
    assert len(dados) == len(tabela.dados)
    coordenadas = dados.dropna(subset=["latitude", "longitude"])
    assert coordenadas["latitude"].between(-34, 6).all() and coordenadas["longitude"].between(-74, -28).all()


def test_cadeia_de_certificados_inclui_intermediario(tmp_path):
    conteudo = open(school_data.cadeia_certificados(tmp_path), encoding="utf-8").read()
    intermediario = config.ARQ_CERT_INEP.read_text(encoding="utf-8").strip()
    assert intermediario in conteudo and conteudo.count("BEGIN CERTIFICATE") > 100


def _trecho(pacote_inep) -> bytes:
    with open(pacote_inep, "rb") as f:
        return f.read(LIMITE_DOWNLOAD)


def test_download_reaproveita_o_cache(tmp_path, monkeypatch, pacote_inep):
    """O servidor do Inep é substituído por um que entrega um trecho do pacote oficial."""
    trecho = _trecho(pacote_inep)
    pedidos = []

    class Resposta:
        headers = {"Content-Length": str(len(trecho)), "Last-Modified": "Wed, 08 Jul 2026 12:22:27 GMT"}
        status_code = 200

        def iter_content(self, tamanho):
            yield trecho

    def requisitar(metodo, url, verificar, **kwargs):
        pedidos.append(metodo)
        return Resposta(), False

    monkeypatch.setattr(school_data, "_requisitar", requisitar)
    ano = max(config.URLS_MICRODADOS_INEP)
    caminho, meta = school_data.baixar_microdados(ano, tmp_path)
    assert caminho.read_bytes() == trecho and meta["origem_cache"] is False
    assert json.loads(caminho.with_suffix(".json").read_text())["sha256"] == hashlib.sha256(trecho).hexdigest()
    _, meta2 = school_data.baixar_microdados(ano, tmp_path)
    assert meta2["origem_cache"] is True and pedidos == ["HEAD", "GET", "HEAD"]
    with pytest.raises(ErroImportacao):
        school_data.baixar_microdados(min(config.URLS_MICRODADOS_INEP) - 30, tmp_path)


def test_download_retoma_de_onde_parou(tmp_path, monkeypatch, pacote_inep):
    trecho = _trecho(pacote_inep)
    ano = max(config.URLS_MICRODADOS_INEP)
    destino = tmp_path / config.URLS_MICRODADOS_INEP[ano].rsplit("/", 1)[-1]
    metade = len(trecho) // 2
    destino.with_suffix(".parcial").write_bytes(trecho[:metade])
    pedidos = []

    class Resposta:
        headers = {"Content-Length": str(len(trecho)), "Last-Modified": "Wed, 08 Jul 2026 12:22:27 GMT"}

        def __init__(self, inicio):
            self.inicio, self.status_code = inicio, 206 if inicio else 200

        def iter_content(self, tamanho):
            yield trecho[self.inicio:]

    def requisitar(metodo, url, verificar, cabecalhos_extra=None, **kwargs):
        faixa = (cabecalhos_extra or {}).get("Range")
        pedidos.append((metodo, faixa))
        return Resposta(int(faixa.split("=")[1].rstrip("-")) if faixa else 0), False

    monkeypatch.setattr(school_data, "_requisitar", requisitar)
    caminho, meta = school_data.baixar_microdados(ano, tmp_path)
    assert pedidos[-1] == ("GET", f"bytes={metade}-")
    assert caminho.read_bytes() == trecho and meta["sha256"] == hashlib.sha256(trecho).hexdigest()


def test_tabela_de_atributos_do_painel(base_real):
    atributos = base_real.atributos_escolas
    assert len(atributos) == len(base_real.escolas)
    assert isinstance(atributos, pd.DataFrame) and "co_entidade" in atributos
