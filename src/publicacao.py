"""Versão publicada do painel: cópia do banco local para quem abre o painel online.

Vai para a versão publicada o que o painel mostra: nomes, escolas, territórios, situação na
plataforma, conciliação e indicadores, com os mesmos números do painel local. Ficam de fora:

- e-mails, trocados por códigos irreversíveis (HMAC com a chave local, que não é publicada), iguais
  no cadastro e na plataforma, para que a conciliação dê o mesmo resultado;
- telefone, WhatsApp, raça/cor e gênero;
- o registro de auditoria, as observações e os autores das decisões de conciliação;
- as versões anteriores das bases e as escolas que não são de nenhum cursista.

CPF e data de nascimento não são gravados nem no banco local.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ARQUIVO = "eti.sqlite3"
INFO = "publicacao.json"
AUTOR = "coordenação"


class PublicacaoInsegura(RuntimeError):
    """Algum dado de contato do banco local apareceu na cópia publicada."""


def _copiar(origem: Path, destino: Path) -> None:
    fonte = sqlite3.connect(f"file:{origem}?mode=ro", uri=True)
    copia = sqlite3.connect(destino)
    with copia:
        fonte.backup(copia)
    fonte.close()
    copia.close()


def gerar(origem: Path, chave: str, pasta_destino: Path) -> dict:
    """Gera ``pasta_destino/eti.sqlite3`` e ``publicacao.json`` a partir do banco local."""
    pasta_destino.mkdir(parents=True, exist_ok=True)
    temporario = pasta_destino / f"{ARQUIVO}.tmp"
    temporario.unlink(missing_ok=True)
    _copiar(origem, temporario)

    def codigo(email):
        if email is None:
            return None
        return "codigo:" + hmac.new(chave.encode(), str(email).encode(), hashlib.sha256).hexdigest()[:32]

    con = sqlite3.connect(temporario)
    con.create_function("codigo_email", 1, codigo, deterministic=True)
    with con:
        ativas = dict(con.execute("SELECT fonte, id FROM importacoes WHERE status = 'ativa'").fetchall())
        for fonte in ("cadastro", "atividade", "escolas"):
            con.execute(f"DELETE FROM {fonte} WHERE importacao_id != ?", (ativas.get(fonte, -1),))
        con.execute("DELETE FROM importacoes WHERE status != 'ativa'")
        con.execute("UPDATE cadastro SET email = codigo_email(email), telefone = NULL, whatsapp = NULL, "
                    "raca_cor = NULL, genero = NULL")
        con.execute("UPDATE atividade SET email = codigo_email(email)")
        con.execute("DELETE FROM escolas WHERE co_entidade NOT IN (SELECT inep FROM cadastro WHERE inep IS NOT NULL)")
        con.execute("UPDATE importacoes SET n_registros = (SELECT COUNT(*) FROM escolas) WHERE fonte = 'escolas'")
        con.execute("UPDATE importacoes SET importado_por = ?", (AUTOR,))
        con.execute("UPDATE decisoes_conciliacao SET observacao = NULL, decidido_por = ?, "
                    "revogada_por = CASE WHEN revogada_por IS NULL THEN NULL ELSE ? END", (AUTOR, AUTOR))
        con.execute("UPDATE parametros SET atualizado_por = ?", (AUTOR,))
        con.execute("DELETE FROM auditoria")
    con.execute("PRAGMA journal_mode = DELETE")
    con.execute("VACUUM")
    contagens = {f: con.execute(f"SELECT COUNT(*) FROM {f}").fetchone()[0] for f in ("cadastro", "atividade", "escolas")}
    con.close()

    vazados = verificar(origem, temporario)
    if vazados:
        temporario.unlink(missing_ok=True)
        raise PublicacaoInsegura(f"{vazados} dado(s) de contato apareceriam na versão publicada; nada foi publicado.")
    temporario.replace(pasta_destino / ARQUIVO)
    info = {"publicado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"), "registros": contagens}
    (pasta_destino / INFO).write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    return info


def verificar(origem: Path, publicado: Path) -> int:
    """Quantos e-mails ou telefones do banco local aparecem na cópia publicada (deve ser zero)."""
    fonte = sqlite3.connect(f"file:{origem}?mode=ro", uri=True)
    emails = {e for (e,) in fonte.execute("SELECT email FROM cadastro UNION SELECT email FROM atividade") if e}
    telefones = {re.sub(r"\D", "", str(t)) for (t,) in fonte.execute(
        "SELECT telefone FROM cadastro UNION SELECT whatsapp FROM cadastro") if t}
    fonte.close()
    copia = sqlite3.connect(f"file:{publicado}?mode=ro", uri=True)
    texto = "\n".join(copia.iterdump()).lower()
    copia.close()
    numeros = {re.sub(r"\D", "", n) for n in re.findall(r"\(?\d[\d ().-]{6,}\d", texto)}
    return sum(e.lower() in texto for e in emails) + sum(len(t) >= 8 and t in numeros for t in telefones)


def data_publicacao(pasta: Path) -> str | None:
    try:
        return json.loads((pasta / INFO).read_text(encoding="utf-8")).get("publicado_em")
    except (OSError, ValueError):
        return None
