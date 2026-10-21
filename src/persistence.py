"""Persistência em SQLite (desenvolvimento e instalações pequenas).

Cada importação é um retrato completo de uma fonte. A troca do retrato ativo
é transacional: se qualquer etapa falhar, o retrato anterior continua ativo.
Para um ambiente compartilhado de produção, esta classe é o ponto único a
adaptar para PostgreSQL (o SQL usado é padrão, exceto ``BEGIN IMMEDIATE``).
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .config import PARAMETROS_PADRAO
from .security import garantir_diretorio_privado

FONTES = ("cadastro", "atividade", "escolas")

COLUNAS: dict[str, list[str]] = {
    "cadastro": [
        "id_registro", "arquivo_origem", "linha_origem", "chave_pessoa", "tipo_chave",
        "regiao", "uf", "uf_status", "ente", "cod_ibge", "cod_ibge_status",
        "data_resposta", "data_resposta_status", "ciclo", "articulador", "esfera",
        "nome", "nome_chave", "email", "email_status", "telefone", "whatsapp",
        "tipo", "origem", "situacao", "raca_cor", "genero", "escolaridade", "cargo_funcao",
        "escola", "inep", "inep_status", "cpf_status", "nascimento_status", "id_compartilhado",
        "dup_cpf", "dup_email", "dup_nome_nascimento", "dup_linha", "problemas",
    ],
    "atividade": [
        "id_conta", "arquivo_origem", "linha_origem", "chave_conta", "nome_completo", "nome_chave",
        "email", "email_status", "papeis", "grupos", "ultimo_acesso_texto", "acesso_tipo",
        "acesso_segundos", "acesso_momento", "acesso_base", "situacao_conta",
        "eh_cursista", "eh_equipe", "id_compartilhado", "dup_email", "problemas",
    ],
    "escolas": [
        "co_entidade", "no_entidade", "sg_uf", "co_municipio", "no_municipio", "dependencia",
        "categoria_administrativa", "localizacao", "localizacao_diferenciada",
        "situacao_funcionamento", "etapas", "porte", "latitude", "longitude", "atributos",
    ],
}
_TIPOS = {
    "linha_origem": "INTEGER", "acesso_segundos": "REAL", "eh_cursista": "INTEGER",
    "eh_equipe": "INTEGER", "latitude": "REAL", "longitude": "REAL",
}

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS importacoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fonte TEXT NOT NULL CHECK (fonte IN ('cadastro', 'atividade', 'escolas')),
    status TEXT NOT NULL CHECK (status IN ('pendente', 'ativa', 'substituida', 'expurgada')),
    arquivos TEXT NOT NULL,
    importado_em TEXT NOT NULL,
    importado_por TEXT NOT NULL,
    referencia_em TEXT,
    referencia_descricao TEXT,
    n_registros INTEGER NOT NULL,
    n_com_problemas INTEGER,
    n_duplicados INTEGER,
    mapeamento TEXT,
    resumo TEXT
);
CREATE INDEX IF NOT EXISTS ix_importacoes_fonte ON importacoes (fonte, status);
CREATE TABLE IF NOT EXISTS decisoes_conciliacao (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chave_pessoa TEXT NOT NULL,
    chave_conta TEXT NOT NULL,
    decisao TEXT NOT NULL CHECK (decisao IN ('associar', 'rejeitar')),
    observacao TEXT,
    decidido_por TEXT NOT NULL,
    decidido_em TEXT NOT NULL,
    ativa INTEGER NOT NULL DEFAULT 1,
    revogada_por TEXT,
    revogada_em TEXT
);
CREATE TABLE IF NOT EXISTS parametros (
    chave TEXT PRIMARY KEY,
    valor TEXT NOT NULL,
    atualizado_em TEXT NOT NULL,
    atualizado_por TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS auditoria (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    momento TEXT NOT NULL,
    usuario TEXT NOT NULL,
    acao TEXT NOT NULL,
    alvo TEXT,
    detalhe TEXT
);
"""


def agora_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _esquema_fonte(fonte: str) -> str:
    colunas = ",\n    ".join(f"{c} {_TIPOS.get(c, 'TEXT')}" for c in COLUNAS[fonte])
    return (
        f"CREATE TABLE IF NOT EXISTS {fonte} (\n"
        f"    importacao_id INTEGER NOT NULL REFERENCES importacoes (id),\n    {colunas}\n);\n"
        f"CREATE INDEX IF NOT EXISTS ix_{fonte}_importacao ON {fonte} (importacao_id);"
    )


def _para_sql(valor):
    if valor is None:
        return None
    if isinstance(valor, float) and valor != valor:
        return None
    if isinstance(valor, (list, dict)):
        return json.dumps(valor, ensure_ascii=False)
    if valor is pd.NA or valor is pd.NaT:
        return None
    if hasattr(valor, "item"):  # escalares numpy
        return valor.item()
    return valor


class Repositorio:
    def __init__(self, caminho: Path, retencao: int = 3):
        self.caminho = Path(caminho)
        self.retencao = max(2, retencao)

    # ------------------------------------------------------------ conexão

    def conectar(self) -> sqlite3.Connection:
        conexao = sqlite3.connect(self.caminho, isolation_level=None, timeout=30)
        conexao.execute("PRAGMA foreign_keys = ON")
        conexao.execute("PRAGMA busy_timeout = 30000")
        return conexao

    @contextmanager
    def transacao(self):
        conexao = self.conectar()
        try:
            conexao.execute("BEGIN IMMEDIATE")
            yield conexao
            conexao.execute("COMMIT")
        except BaseException:
            conexao.execute("ROLLBACK")
            raise
        finally:
            conexao.close()

    def inicializar(self) -> "Repositorio":
        novo = not self.caminho.exists()
        garantir_diretorio_privado(self.caminho.parent)
        conexao = self.conectar()
        try:
            conexao.execute("PRAGMA journal_mode = WAL")
            conexao.executescript(_ESQUEMA + "\n".join(_esquema_fonte(f) for f in FONTES))
        finally:
            conexao.close()
        if novo:
            try:
                os.chmod(self.caminho, 0o600)
            except OSError:  # pragma: no cover
                pass
        return self

    def consolidar(self) -> None:
        """Grava o log WAL no arquivo principal (para copiar o banco com segurança)."""
        conexao = self.conectar()
        try:
            conexao.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            conexao.close()

    # ------------------------------------------------------------ importações

    def registrar_importacao(self, fonte: str, registros: pd.DataFrame, meta: dict, usuario: str) -> int:
        """Grava um novo retrato e o torna ativo numa única transação."""
        if fonte not in FONTES:
            raise ValueError(f"fonte desconhecida: {fonte}")
        if registros.empty:
            raise ValueError("importação sem registros")
        colunas = COLUNAS[fonte]
        faltando = [c for c in colunas if c not in registros.columns]
        if faltando:
            raise ValueError(f"colunas ausentes para gravação: {faltando}")
        linhas = [
            tuple(_para_sql(v) for v in linha)
            for linha in registros[colunas].itertuples(index=False, name=None)
        ]
        with self.transacao() as con:
            cursor = con.execute(
                "INSERT INTO importacoes (fonte, status, arquivos, importado_em, importado_por, "
                "referencia_em, referencia_descricao, n_registros, n_com_problemas, n_duplicados, "
                "mapeamento, resumo) VALUES (?, 'pendente', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    fonte,
                    json.dumps(meta.get("arquivos", []), ensure_ascii=False),
                    meta.get("importado_em") or agora_utc(),
                    usuario,
                    meta.get("referencia_em"),
                    meta.get("referencia_descricao"),
                    len(linhas),
                    meta.get("n_com_problemas"),
                    meta.get("n_duplicados"),
                    json.dumps(meta.get("mapeamento", {}), ensure_ascii=False),
                    json.dumps(meta.get("resumo", {}), ensure_ascii=False, default=str),
                ),
            )
            novo_id = cursor.lastrowid
            marcadores = ", ".join("?" for _ in range(len(colunas) + 1))
            con.executemany(
                f"INSERT INTO {fonte} (importacao_id, {', '.join(colunas)}) VALUES ({marcadores})",
                [(novo_id, *linha) for linha in linhas],
            )
            con.execute(
                "UPDATE importacoes SET status = 'substituida' WHERE fonte = ? AND status = 'ativa'",
                (fonte,),
            )
            con.execute("UPDATE importacoes SET status = 'ativa' WHERE id = ?", (novo_id,))
            self._expurgar(con, fonte)
            con.execute(
                "INSERT INTO auditoria (momento, usuario, acao, alvo, detalhe) VALUES (?, ?, ?, ?, ?)",
                (agora_utc(), usuario, f"importacao_{fonte}", str(novo_id), f"{len(linhas)} registros"),
            )
        return novo_id

    def _expurgar(self, con: sqlite3.Connection, fonte: str) -> None:
        """Mantém apenas os últimos N retratos com registros (retenção configurável)."""
        ids = [r[0] for r in con.execute(
            "SELECT id FROM importacoes WHERE fonte = ? AND status IN ('ativa', 'substituida') "
            "ORDER BY id DESC", (fonte,))]
        for antigo in ids[self.retencao:]:
            con.execute(f"DELETE FROM {fonte} WHERE importacao_id = ?", (antigo,))
            con.execute("UPDATE importacoes SET status = 'expurgada' WHERE id = ?", (antigo,))

    def _importacao(self, sql: str, parametros: tuple) -> dict | None:
        con = self.conectar()
        try:
            con.row_factory = sqlite3.Row
            linha = con.execute(sql, parametros).fetchone()
        finally:
            con.close()
        if linha is None:
            return None
        dados = dict(linha)
        for campo in ("arquivos", "mapeamento", "resumo"):
            dados[campo] = json.loads(dados[campo]) if dados.get(campo) else ({} if campo != "arquivos" else [])
        return dados

    def importacao_ativa(self, fonte: str) -> dict | None:
        return self._importacao(
            "SELECT * FROM importacoes WHERE fonte = ? AND status = 'ativa' ORDER BY id DESC LIMIT 1",
            (fonte,),
        )

    def importacao_anterior(self, fonte: str) -> dict | None:
        return self._importacao(
            "SELECT * FROM importacoes WHERE fonte = ? AND status = 'substituida' ORDER BY id DESC LIMIT 1",
            (fonte,),
        )

    def registros(self, fonte: str, importacao_id: int | None = None) -> pd.DataFrame:
        if importacao_id is None:
            ativa = self.importacao_ativa(fonte)
            if ativa is None:
                return pd.DataFrame(columns=COLUNAS[fonte])
            importacao_id = ativa["id"]
        con = self.conectar()
        try:
            return pd.read_sql_query(
                f"SELECT {', '.join(COLUNAS[fonte])} FROM {fonte} WHERE importacao_id = ?",
                con, params=(importacao_id,),
            )
        finally:
            con.close()

    def historico(self, fonte: str | None = None, limite: int = 50) -> pd.DataFrame:
        con = self.conectar()
        try:
            sql = ("SELECT id, fonte, status, importado_em, importado_por, referencia_descricao, "
                   "n_registros, n_com_problemas, n_duplicados, arquivos FROM importacoes "
                   "WHERE status != 'pendente'")
            parametros: tuple = ()
            if fonte:
                sql += " AND fonte = ?"
                parametros = (fonte,)
            sql += " ORDER BY id DESC LIMIT ?"
            return pd.read_sql_query(sql, con, params=(*parametros, limite))
        finally:
            con.close()

    # ------------------------------------------------------------ conciliação manual

    def decisoes(self, apenas_ativas: bool = True) -> pd.DataFrame:
        con = self.conectar()
        try:
            sql = "SELECT * FROM decisoes_conciliacao"
            if apenas_ativas:
                sql += " WHERE ativa = 1"
            return pd.read_sql_query(sql + " ORDER BY id", con)
        finally:
            con.close()

    def registrar_decisao(self, chave_pessoa: str, chave_conta: str, decisao: str,
                          observacao: str | None, usuario: str) -> int:
        if decisao not in ("associar", "rejeitar"):
            raise ValueError("decisão inválida")
        with self.transacao() as con:
            # Uma nova decisão sobre o mesmo par substitui a anterior.
            con.execute(
                "UPDATE decisoes_conciliacao SET ativa = 0, revogada_por = ?, revogada_em = ? "
                "WHERE chave_pessoa = ? AND chave_conta = ? AND ativa = 1",
                (usuario, agora_utc(), chave_pessoa, chave_conta),
            )
            cursor = con.execute(
                "INSERT INTO decisoes_conciliacao (chave_pessoa, chave_conta, decisao, observacao, "
                "decidido_por, decidido_em) VALUES (?, ?, ?, ?, ?, ?)",
                (chave_pessoa, chave_conta, decisao, observacao, usuario, agora_utc()),
            )
            con.execute(
                "INSERT INTO auditoria (momento, usuario, acao, alvo, detalhe) VALUES (?, ?, ?, ?, ?)",
                (agora_utc(), usuario, f"conciliacao_{decisao}", chave_pessoa, chave_conta),
            )
            return cursor.lastrowid

    def revogar_decisao(self, decisao_id: int, usuario: str) -> None:
        with self.transacao() as con:
            con.execute(
                "UPDATE decisoes_conciliacao SET ativa = 0, revogada_por = ?, revogada_em = ? "
                "WHERE id = ? AND ativa = 1",
                (usuario, agora_utc(), decisao_id),
            )
            con.execute(
                "INSERT INTO auditoria (momento, usuario, acao, alvo) VALUES (?, ?, ?, ?)",
                (agora_utc(), usuario, "conciliacao_revogada", str(decisao_id)),
            )

    # ------------------------------------------------------------ parâmetros e auditoria

    def parametros(self) -> dict:
        valores = {k: (list(v) if isinstance(v, list) else v) for k, v in PARAMETROS_PADRAO.items()}
        con = self.conectar()
        try:
            for chave, valor in con.execute("SELECT chave, valor FROM parametros"):
                if chave in valores:
                    valores[chave] = json.loads(valor)
        finally:
            con.close()
        return valores

    def salvar_parametros(self, valores: dict, usuario: str) -> None:
        with self.transacao() as con:
            for chave, valor in valores.items():
                if chave not in PARAMETROS_PADRAO:
                    continue
                con.execute(
                    "INSERT INTO parametros (chave, valor, atualizado_em, atualizado_por) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT (chave) DO UPDATE SET valor = excluded.valor, "
                    "atualizado_em = excluded.atualizado_em, atualizado_por = excluded.atualizado_por",
                    (chave, json.dumps(valor, ensure_ascii=False), agora_utc(), usuario),
                )
            con.execute(
                "INSERT INTO auditoria (momento, usuario, acao) VALUES (?, ?, ?)",
                (agora_utc(), usuario, "parametros_alterados"),
            )

    def auditar(self, usuario: str, acao: str, alvo: str | None = None, detalhe: str | None = None) -> None:
        with self.transacao() as con:
            con.execute(
                "INSERT INTO auditoria (momento, usuario, acao, alvo, detalhe) VALUES (?, ?, ?, ?, ?)",
                (agora_utc(), usuario, acao, alvo, detalhe),
            )

    def auditoria(self, limite: int = 200) -> pd.DataFrame:
        con = self.conectar()
        try:
            return pd.read_sql_query(
                "SELECT momento, usuario, acao, alvo, detalhe FROM auditoria ORDER BY id DESC LIMIT ?",
                con, params=(limite,),
            )
        finally:
            con.close()

    # ------------------------------------------------------------ versão (chave de cache)

    def versao(self) -> str:
        """Muda sempre que dados, decisões ou parâmetros mudam."""
        con = self.conectar()
        try:
            partes = [
                con.execute("SELECT group_concat(id) FROM importacoes WHERE status = 'ativa'").fetchone()[0],
                con.execute("SELECT count(*), max(id), sum(ativa) FROM decisoes_conciliacao").fetchone(),
                con.execute("SELECT max(atualizado_em), count(*) FROM parametros").fetchone(),
            ]
        finally:
            con.close()
        return hashlib.sha256(repr(partes).encode()).hexdigest()[:16]
