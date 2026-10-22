"""Versão publicada (painel online): mesmos números do painel local, sem contatos nem dados sensíveis.

Gerada a partir da cópia do banco real e conferida contra os arquivos originais.
"""

import re
import sqlite3

import pytest
from conftest import APP_PATH, confere, quadro, valores
from streamlit.testing.v1 import AppTest

from src import config, metrics, painel, publicacao
from src.loaders import CAMPOS_ATIVIDADE, CAMPOS_CADASTRO
from src.normalization import interpretar_data, normalizar_email, validar_cpf
from src.persistence import Repositorio


@pytest.fixture(scope="module")
def publicado(tmp_path_factory, dir_dados_real):
    arquivo_chave = dir_dados_real / ".chave_pseudonimizacao"
    if not arquivo_chave.exists():
        pytest.skip("chave de pseudonimização local não encontrada")
    destino = tmp_path_factory.mktemp("publicado")
    publicacao.gerar(dir_dados_real / "eti.sqlite3", arquivo_chave.read_text().strip(), destino)
    return destino


def test_sem_contatos_nem_dados_sensiveis(publicado, tabelas_cadastro, tabela_atividade):
    con = sqlite3.connect(publicado / "eti.sqlite3")
    texto = "\n".join(con.iterdump()).lower()
    numeros = {re.sub(r"\D", "", n) for n in re.findall(r"\(?\d[\d ().-]{6,}\d", texto)}
    dados = quadro(tabelas_cadastro, CAMPOS_CADASTRO)
    brutos = [*dados["email"], *valores([tabela_atividade], "email", CAMPOS_ATIVIDADE)]
    emails = {normalizar_email(e)[0] for e in brutos if normalizar_email(e)[0]}
    telefones = {re.sub(r"\D", "", str(t)) for t in [*dados["telefone"].dropna(), *dados["whatsapp"].dropna()]}
    cpfs = {validar_cpf(c)[0] for c in dados["cpf"] if validar_cpf(c)[1].startswith("valido")}
    nascimentos = {interpretar_data(d)[0] for d in dados["data_nascimento"] if interpretar_data(d)[1] == "valida"}
    vazados = sum(e in texto for e in emails)
    vazados += sum(len(t) >= 8 and t in numeros for t in telefones) + sum(c in numeros for c in cpfs)
    vazados += sum(d.strftime("%d/%m/%Y") in texto or d.isoformat() in texto for d in nascimentos)
    confere(len(emails) > 1000 and vazados == 0, f"{vazados} dado(s) pessoal(is) real(is) na versão publicada")
    sensiveis = con.execute("SELECT COUNT(*) FROM cadastro WHERE telefone IS NOT NULL OR whatsapp IS NOT NULL "
                            "OR raca_cor IS NOT NULL OR genero IS NOT NULL").fetchone()[0]
    assert sensiveis == 0
    assert con.execute("SELECT COUNT(*) FROM auditoria").fetchone()[0] == 0
    assert publicacao.verificar(config.DIR_PUBLICADO.parent / "privado" / "eti.sqlite3", publicado / "eti.sqlite3") == 0


def test_mesmos_numeros_do_painel_local(publicado, base_real):
    base = painel.montar_base(Repositorio(publicado / "eti.sqlite3"))
    local = metrics.calcular(base_real.cursistas, base_real.contas, base_real, base_real.parametros)
    online = metrics.calcular(base.cursistas, base.contas, base, base.parametros)
    diferentes = [i for i in local if (local[i].valor, local[i].numerador, local[i].denominador)
                  != (online[i].valor, online[i].numerador, online[i].denominador)]
    assert diferentes == []
    assert base.cursistas["faixa_acesso"].value_counts().to_dict() == base_real.cursistas["faixa_acesso"].value_counts().to_dict()
    assert base.cursistas["status_conciliacao"].value_counts().to_dict() == \
        base_real.cursistas["status_conciliacao"].value_counts().to_dict()
    assert len(painel.resumo_escolas(base.cursistas)) == len(painel.resumo_escolas(base_real.cursistas))


def test_modo_escolhido_conforme_o_lugar(tmp_path):
    publicada = tmp_path / "publicado"
    publicada.mkdir()
    (publicada / "eti.sqlite3").write_bytes(b"")
    vazia, com_arquivos, com_banco = tmp_path / "vazia", tmp_path / "arquivos", tmp_path / "banco"
    for pasta in (vazia, com_arquivos, com_banco):
        pasta.mkdir()
    (com_arquivos / "cadastro.xlsx").write_bytes(b"")
    (com_banco / "eti.sqlite3").write_bytes(b"")
    assert config._ambiente_padrao(vazia, vazia, publicada) == "publicacao"  # o painel online
    assert config._ambiente_padrao(vazia, com_arquivos, publicada) == "local"  # há arquivos na pasta
    assert config._ambiente_padrao(com_banco, vazia, publicada) == "local"  # há banco local
    assert config._ambiente_padrao(vazia, vazia, tmp_path / "sem_publicacao") == "local"


def test_painel_online_so_para_leitura(publicado, monkeypatch):
    monkeypatch.setenv("ETI_AMBIENTE", "publicacao")
    monkeypatch.setenv("ETI_PASTA_PUBLICADA", str(publicado))
    teste = AppTest.from_file(APP_PATH, default_timeout=240)
    teste.run()
    confere(not teste.exception and not teste.error, "o painel online não abriu")
    for pagina in ("paginas/1_visao_geral.py", "paginas/2_cursistas.py", "paginas/4_escolas.py",
                   "paginas/3_atividade.py", "paginas/5_territorio.py", "paginas/6_qualidade_conciliacao.py"):
        teste.switch_page(pagina).run()
        confere(not teste.exception and not teste.error, f"{pagina}: erro no painel online")
        texto = " ".join([m.value for m in teste.markdown] + [h.proto.body for h in teste.get("html")]).lower()
        confere("codigo:" not in texto, f"{pagina}: código de e-mail exibido na tela")
        confere("versão publicada" in texto, f"{pagina}: selo da versão publicada ausente")
    teste.switch_page("paginas/2_cursistas.py").run()
    cartoes = [h for h in teste.get("html") if h.proto.body.startswith('<div class="eti-cartao')]
    confere(len(cartoes) == 24, "a galeria online não mostrou os cursistas")
    [abrir] = [b for b in teste.button if b.label.startswith("Abrir a ficha de ")][:1]
    abrir.click().run()
    confere(not [b for b in teste.button if b.label == "Exibir dados de contato"], "contato disponível online")
    with pytest.raises(Exception):
        teste.switch_page("paginas/7_administracao.py").run()  # Administração não existe para o visitante
