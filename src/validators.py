"""Validação: catálogo de problemas, duplicidades e verificações estruturais.

Registros com problemas nunca são descartados: recebem códigos de problema,
contados no relatório de qualidade e inspecionáveis na página de qualidade.
"""

from __future__ import annotations

from collections import Counter

import pandas as pd

from .loaders import Campo, Mapeamento

ERRO, ALERTA, INFO = "erro", "alerta", "informativo"

# código -> (descrição, campo interno relacionado, gravidade)
CATALOGO_PROBLEMAS: dict[str, tuple[str, str | None, str]] = {
    # cadastro
    "nome_ausente": ("Nome ausente", "nome", ERRO),
    "email_ausente": ("E-mail ausente", "email", ALERTA),
    "email_invalido": ("E-mail com formato inválido", "email", ALERTA),
    "cpf_ausente": ("CPF ausente", "cpf", ALERTA),
    "cpf_invalido": ("CPF inválido (formato ou dígitos verificadores)", "cpf", ALERTA),
    "cpf_zeros_recompostos": ("CPF numérico com zeros à esquerda recompostos", "cpf", INFO),
    "nascimento_invalido": ("Data de nascimento em formato não reconhecido", "data_nascimento", ALERTA),
    "nascimento_implausivel": ("Data de nascimento fora do intervalo plausível", "data_nascimento", ALERTA),
    "data_resposta_invalida": ("Data de resposta em formato não reconhecido", "data_resposta", ALERTA),
    "data_resposta_futura": ("Data de resposta posterior à data da importação", "data_resposta", ALERTA),
    "uf_ausente": ("UF ausente", "uf", ALERTA),
    "uf_invalida": ("UF não reconhecida", "uf", ALERTA),
    "regiao_divergente": ("Região informada difere da região da UF", "regiao", ALERTA),
    "ente_ausente": ("Ente ausente", "ente", ALERTA),
    "ibge_ausente": ("Código IBGE ausente", "cod_ibge", ALERTA),
    "ibge_invalido": ("Código IBGE com formato inválido", "cod_ibge", ALERTA),
    "ibge_uf_divergente": ("Código IBGE de outra UF", "cod_ibge", ALERTA),
    "ibge_inexistente": ("Código IBGE fora da lista oficial de municípios", "cod_ibge", ALERTA),
    "inep_ausente": ("Código INEP ausente", "inep", ALERTA),
    "inep_invalido": ("Código INEP com formato inválido", "inep", ALERTA),
    "inep_uf_divergente": ("Código INEP de escola de outra UF", "inep", ALERTA),
    "escola_ausente": ("Nome da escola ausente", "escola", INFO),
    "situacao_ausente": ("Situação cadastral ausente", "situacao", ALERTA),
    "duplicado_cpf": ("Mesmo CPF em mais de um registro", "cpf", ALERTA),
    "duplicado_email": ("Mesmo e-mail em mais de um registro", "email", ALERTA),
    "duplicado_nome_nascimento": ("Mesmo nome e data de nascimento em mais de um registro", "nome", ALERTA),
    "linha_repetida": ("Registro idêntico a outro (todas as colunas)", None, ALERTA),
    # atividade
    "conta_sem_nome": ("Conta sem nome", "nome_completo", ALERTA),
    "conta_email_ausente": ("Conta sem e-mail", "email", ALERTA),
    "conta_email_invalido": ("Conta com e-mail inválido", "email", ALERTA),
    "conta_email_duplicado": ("Mesmo e-mail em mais de uma conta", "email", ALERTA),
    "acesso_vazio": ("Último acesso em branco", "ultimo_acesso", ALERTA),
    "acesso_nao_interpretado": ("Último acesso em formato não reconhecido", "ultimo_acesso", ALERTA),
    "acesso_posterior_referencia": ("Último acesso posterior à data de referência informada", "ultimo_acesso", ALERTA),
    "situacao_conta_ausente": ("Situação da conta ausente", "situacao_conta", INFO),
    "sem_papel": ("Conta sem papel atribuído", "papeis", INFO),
    "sem_grupo": ("Conta sem grupo de formação", "grupos", INFO),
    "multiplos_grupos": ("Conta em mais de um grupo", "grupos", INFO),
    # base escolar
    "escola_codigo_invalido": ("Código de escola inválido na base escolar", "co_entidade", ALERTA),
    "escola_codigo_duplicado": ("Código de escola repetido na base escolar", "co_entidade", ALERTA),
}

CODIGOS_DUPLICIDADE = ("duplicado_cpf", "duplicado_email", "duplicado_nome_nascimento", "linha_repetida")


def descrever(codigo: str) -> str:
    return CATALOGO_PROBLEMAS.get(codigo, (codigo, None, ALERTA))[0]


def gravidade(codigo: str) -> str:
    return CATALOGO_PROBLEMAS.get(codigo, (codigo, None, ALERTA))[2]


def grupos_de_duplicidade(chaves: list, prefixo: str) -> list[str | None]:
    """Para cada posição, um identificador de grupo se a chave aparece mais de uma vez."""
    contagem = Counter(c for c in chaves if c)
    grupos: dict = {}
    resultado = []
    for chave in chaves:
        if chave and contagem[chave] > 1:
            if chave not in grupos:
                grupos[chave] = f"{prefixo}{len(grupos) + 1:04d}"
            resultado.append(grupos[chave])
        else:
            resultado.append(None)
    return resultado


def verificar_estrutura(mapeamentos: dict[str, Mapeamento], n_registros: int,
                        requisitos_alternativos: list[tuple[str, ...]] | None = None,
                        campos: tuple[Campo, ...] = ()) -> tuple[list[str], list[str]]:
    """Retorna (bloqueios, avisos). Bloqueios impedem a confirmação da importação."""
    bloqueios, avisos = [], []
    rotulos = {c.nome: c.rotulo for c in campos}
    for arquivo, mapa in mapeamentos.items():
        if mapa.faltando_obrigatorios:
            bloqueios.append(
                f"“{arquivo}”: coluna(s) obrigatória(s) não encontrada(s): "
                + ", ".join(mapa.faltando_obrigatorios) + ". Indique a correspondência manualmente."
            )
        for grupo in requisitos_alternativos or []:
            if not set(grupo) & set(mapa.original_para_interno.values()):
                bloqueios.append(
                    f"“{arquivo}”: é preciso ao menos uma destas colunas: "
                    + " ou ".join(rotulos.get(c, c) for c in grupo) + "."
                )
        if mapa.faltando_recomendados:
            avisos.append(
                f"“{arquivo}”: colunas recomendadas ausentes (funções que dependem delas ficam "
                f"indisponíveis): " + ", ".join(mapa.faltando_recomendados) + "."
            )
        avisos.extend(f"“{arquivo}”: {a}" for a in mapa.ambiguidades)
    if n_registros == 0:
        bloqueios.append("Nenhum registro encontrado nos arquivos.")
    return bloqueios, avisos


def tabela_problemas(registros: pd.DataFrame, coluna_id: str, mapa_cabecalhos: dict[str, dict[str, str]]) -> pd.DataFrame:
    """Uma linha por (registro, problema), sem valores das células.

    ``mapa_cabecalhos``: arquivo -> {campo interno -> cabeçalho original}, para
    citar a coluna como ela aparece na planilha de origem.
    """
    linhas = []
    for reg in registros[[coluna_id, "arquivo_origem", "linha_origem", "problemas"]].itertuples(index=False):
        for codigo in reg.problemas or []:
            descricao, campo, grav = CATALOGO_PROBLEMAS.get(codigo, (codigo, None, ALERTA))
            original = mapa_cabecalhos.get(reg.arquivo_origem, {}).get(campo, campo) if campo else "—"
            linhas.append({
                coluna_id: getattr(reg, coluna_id),
                "arquivo": reg.arquivo_origem,
                "linha": reg.linha_origem,
                "coluna_original": original,
                "codigo": codigo,
                "problema": descricao,
                "gravidade": grav,
            })
    return pd.DataFrame(linhas, columns=[coluna_id, "arquivo", "linha", "coluna_original", "codigo", "problema", "gravidade"])


def resumo_problemas(problemas: pd.DataFrame, n_registros: int, coluna_id: str) -> dict:
    relevantes = problemas[problemas["gravidade"] != INFO] if not problemas.empty else problemas
    por_codigo = (
        problemas.groupby(["codigo", "problema", "gravidade"]).size().reset_index(name="registros")
        .sort_values("registros", ascending=False).to_dict("records")
        if not problemas.empty else []
    )
    duplicados = problemas[problemas["codigo"].isin(CODIGOS_DUPLICIDADE)] if not problemas.empty else problemas
    return {
        "n_registros": int(n_registros),
        "n_com_problemas": int(relevantes[coluna_id].nunique()) if not relevantes.empty else 0,
        "n_duplicados": int(duplicados[coluna_id].nunique()) if not duplicados.empty else 0,
        "por_codigo": por_codigo,
    }
