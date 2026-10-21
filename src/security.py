"""Segurança e privacidade: pseudonimização, mascaramento, logs e autenticação.

Pseudonimização não é anonimização: quem tem a chave HMAC e a lista de CPFs
consegue refazer a correspondência. A chave fica fora do repositório.
"""

from __future__ import annotations

import getpass
import hashlib
import hmac
import logging
import os
import re
import secrets
from dataclasses import dataclass
from pathlib import Path

CHAVE_DEMONSTRACAO = "chave-de-demonstracao-nao-usar-com-dados-reais"
ENDERECOS_LOCAIS = {"localhost", "127.0.0.1", "::1"}


# ---------------------------------------------------------------- pseudonimização


class Pseudonimizador:
    """Gera identificadores estáveis (HMAC-SHA256) sem guardar o valor original."""

    def __init__(self, chave: str):
        self._chave = chave.encode("utf-8")

    def chave(self, tipo: str, valor: str | None) -> str | None:
        if not valor:
            return None
        digest = hmac.new(self._chave, f"{tipo}:{valor}".encode("utf-8"), hashlib.sha256)
        return f"{tipo}:{digest.hexdigest()[:24]}"


def garantir_diretorio_privado(caminho: Path) -> None:
    caminho.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(caminho, 0o700)
    except OSError:  # pragma: no cover - sistemas sem permissões POSIX
        pass


def obter_chave_pseudonimizacao(cfg) -> str:
    """Chave HMAC: segredo em produção; arquivo local protegido em uso local.

    Trocar a chave invalida as decisões manuais de conciliação e a comparação
    entre importações, porque os identificadores pseudônimos mudam.
    """
    if cfg.demonstracao:
        return CHAVE_DEMONSTRACAO
    if cfg.chave_pseudonimizacao:
        if len(cfg.chave_pseudonimizacao) < 32:
            raise ValueError("ETI_CHAVE_PSEUDONIMIZACAO deve ter pelo menos 32 caracteres.")
        return cfg.chave_pseudonimizacao
    if cfg.producao:
        raise RuntimeError("Defina ETI_CHAVE_PSEUDONIMIZACAO nos segredos do ambiente de produção.")
    garantir_diretorio_privado(cfg.dir_dados)
    arquivo = cfg.dir_dados / ".chave_pseudonimizacao"
    if arquivo.exists():
        return arquivo.read_text(encoding="utf-8").strip()
    chave = secrets.token_hex(32)
    descritor = os.open(arquivo, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descritor, "w", encoding="utf-8") as f:
        f.write(chave)
    return chave


# ---------------------------------------------------------------- mascaramento


def mascarar_email(email: str | None) -> str:
    if not email or "@" not in email:
        return "—" if not email else "•••"
    local, dominio = email.split("@", 1)
    return f"{local[:2]}•••@{dominio}"


def mascarar_telefone(telefone: str | None) -> str:
    digitos = re.sub(r"\D", "", telefone or "")
    if len(digitos) < 6:
        return "—" if not digitos else "•••"
    return f"({digitos[:2]}) •••••-••{digitos[-2:]}"


# ---------------------------------------------------------------- logs

_PADROES_PESSOAIS = (
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[e-mail]"),
    (re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b"), "[cpf]"),
    (re.compile(r"\(?\b\d{2}\)?\s?9?\d{4}-?\d{4}\b"), "[telefone]"),
)


def redigir(texto: str) -> str:
    for padrao, substituto in _PADROES_PESSOAIS:
        texto = padrao.sub(substituto, texto)
    return texto


class FiltroRedacao(logging.Filter):
    """Remove e-mails, CPFs e telefones de qualquer mensagem de log (defesa em profundidade)."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redigir(record.getMessage())
        record.args = ()
        if record.exc_info:
            # O rastreamento também pode conter valores; redige e descarta o objeto original.
            record.exc_text = redigir(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None
        return True


def configurar_logging() -> logging.Logger:
    logger = logging.getLogger("eti")
    if not getattr(logger, "_configurado", False):
        manipulador = logging.StreamHandler()
        manipulador.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        manipulador.addFilter(FiltroRedacao())
        logger.addHandler(manipulador)
        logger.setLevel(logging.INFO)
        logger.propagate = False
        logger._configurado = True
    return logger


# ---------------------------------------------------------------- autenticação


@dataclass(frozen=True)
class Usuario:
    identificador: str
    nome: str
    administrador: bool
    acesso_contatos: bool
    metodo: str  # oidc | local | demonstracao


def oidc_configurado() -> bool:
    try:
        import streamlit as st

        return "auth" in st.secrets
    except Exception:
        return False


def servidor_em_endereco_local() -> bool:
    import streamlit as st

    return (st.get_option("server.address") or "").strip() in ENDERECOS_LOCAIS


def _dados_usuario_oidc() -> dict:
    import streamlit as st

    try:
        return dict(st.user.to_dict())
    except Exception:
        return {k: getattr(st.user, k, None) for k in ("email", "name", "email_verified")}


def resolver_usuario(cfg) -> Usuario:
    """Identifica o usuário ou interrompe a página com a tela adequada.

    Nenhum dado é carregado antes desta função retornar um usuário autorizado.
    """
    import streamlit as st

    from . import ui

    if cfg.demonstracao:
        return Usuario("demonstracao", "Visitante da demonstração", True, True, "demonstracao")

    if oidc_configurado():
        if not st.user.is_logged_in:
            ui.tela_login()
            st.stop()
        dados = _dados_usuario_oidc()
        email = str(dados.get("email") or "").strip().lower()
        if dados.get("email_verified") is False or not email:
            ui.tela_acesso_negado("A conta usada não tem e-mail verificado.", permitir_sair=True)
            st.stop()
        if not cfg.usuarios_autorizados:
            ui.tela_configuracao_pendente(
                "A autenticação está configurada, mas a lista de usuários autorizados "
                "(ETI_USUARIOS_AUTORIZADOS) está vazia."
            )
            st.stop()
        if email not in cfg.usuarios_autorizados:
            configurar_logging().info("acesso negado a usuário autenticado não autorizado")
            ui.tela_acesso_negado(
                "Sua conta foi autenticada, mas não consta da lista de coordenadores autorizados.",
                permitir_sair=True,
            )
            st.stop()
        return Usuario(
            email,
            str(dados.get("name") or email),
            email in cfg.administradores,
            email in cfg.acesso_contatos,
            "oidc",
        )

    if cfg.ambiente == "local" and cfg.permitir_local_sem_login:
        if not servidor_em_endereco_local():
            ui.tela_configuracao_pendente(
                "O acesso local sem login só é permitido com o servidor ligado em localhost. "
                "Inicie com: streamlit run app.py --server.address localhost"
            )
            st.stop()
        nome = getpass.getuser()
        return Usuario(f"local:{nome}", nome, True, True, "local")

    ui.tela_configuracao_pendente(
        "Nenhum método de autenticação está configurado. Em produção, configure o provedor "
        "de identidade na seção [auth] de .streamlit/secrets.toml (veja o README)."
    )
    st.stop()
    raise RuntimeError("inalcançável")  # pragma: no cover
