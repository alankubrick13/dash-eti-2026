"""Importação pela linha de comando, com o mesmo pipeline e as mesmas validações do painel.

Imprime apenas contagens e códigos de problema (nunca valores de células).
Sem --confirmar, só valida e mostra o relatório.

Exemplos:
  python scripts/importar.py cadastro planilha.xlsx lista_novos.xlsx
  python scripts/importar.py cadastro planilha.xlsx lista_novos.xlsx --confirmar
  python scripts/importar.py atividade participantes.txt --referencia "2026-10-21 14:58" --confirmar
  python scripts/importar.py escolas microdados_censo_escolar_2024.zip --confirmar
  python scripts/importar.py escolas --baixar 2025 --confirmar
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config, importacao, school_data  # noqa: E402
from src.loaders import CAMPOS_ATIVIDADE, CAMPOS_CADASTRO, ErroImportacao, ler_tabela  # noqa: E402
from src.persistence import Repositorio  # noqa: E402
from src.security import Pseudonimizador, obter_chave_pseudonimizacao  # noqa: E402


def _relatorio(previa: importacao.Previa, comparacao: dict) -> None:
    print(f"\n== Prévia: {previa.fonte}")
    for arquivo in previa.arquivos:
        detalhes = []
        if "linhas" in arquivo:
            detalhes.append(f"{arquivo['linhas']} linhas")
        if arquivo.get("formato") == "texto do Moodle":
            detalhes.append("texto copiado da página de participantes")
        elif arquivo.get("linha_cabecalho"):
            detalhes.append(f"cabeçalho na linha {arquivo['linha_cabecalho']}")
        print(f"   arquivo: {arquivo.get('arquivo')}" + (f" ({'; '.join(detalhes)})" if detalhes else ""))
    for arquivo, mapa in previa.mapeamentos.items():
        nao_usadas = [c for c in (next((a for a in previa.arquivos if a["arquivo"] == arquivo), {}).get("cabecalhos") or [])
                      if c not in mapa]
        print(f"   colunas reconhecidas em {arquivo}: {len(mapa)}; não utilizadas: {nao_usadas or 'nenhuma'}")
    for chave in ("n_registros", "n_pessoas", "n_com_problemas", "n_duplicados", "contas_cursista", "contas_equipe",
                  "acesso_por_tipo", "email_valido", "inep_valido", "ibge_valido", "chave_pessoa", "ano_referencia",
                  "escolas_selecionadas", "md5_confere"):
        if chave in previa.resumo:
            print(f"   {chave}: {previa.resumo[chave]}")
    for item in previa.resumo.get("por_codigo", []):
        print(f"   problema [{item['gravidade']}] {item['problema']}: {item['registros']}")
    for b in previa.bloqueios:
        print(f"   BLOQUEIO: {b}")
    for a in previa.avisos:
        print(f"   aviso: {a}")
    if comparacao.get("ha_anterior"):
        print(f"   comparação: entram {comparacao['entraram']}, saem {comparacao['sairam']}, "
              f"permanecem {comparacao['permaneceram']}; alterações {comparacao['alteracoes_por_campo']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("fonte", choices=("cadastro", "atividade", "escolas"))
    parser.add_argument("arquivos", nargs="*", type=Path)
    parser.add_argument("--banco", type=Path, help="Banco SQLite (padrão: <ETI_DIRETORIO_DADOS>/eti.sqlite3)")
    parser.add_argument("--referencia", help="Data e hora da exportação da atividade (AAAA-MM-DD HH:MM, fuso configurado)")
    parser.add_argument("--baixar", type=int, help="Ano dos microdados oficiais a baixar (escolas)")
    parser.add_argument("--usuario", default="linha de comando")
    parser.add_argument("--confirmar", action="store_true", help="Grava a importação (sem isto, apenas valida)")
    args = parser.parse_args()

    cfg = config.carregar_configuracao()
    banco = args.banco or cfg.dir_dados / "eti.sqlite3"
    repo = Repositorio(banco, cfg.retencao_importacoes).inicializar()
    pseudo = Pseudonimizador(obter_chave_pseudonimizacao(cfg))
    try:
        if args.fonte in ("cadastro", "atividade"):
            campos = CAMPOS_CADASTRO if args.fonte == "cadastro" else CAMPOS_ATIVIDADE
            permitidos = ("xlsx", "csv") if args.fonte == "cadastro" else ("xlsx", "csv", "txt")
            tabelas = [ler_tabela(a.name, a.read_bytes(), campos, permitidos) for a in args.arquivos]
            if args.fonte == "cadastro":
                previa = importacao.preparar_cadastro(tabelas, pseudo)
            else:
                referencia = (datetime.fromisoformat(args.referencia).replace(tzinfo=ZoneInfo(cfg.fuso_horario))
                              if args.referencia else None)
                previa = importacao.preparar_atividade(tabelas, pseudo, referencia, cfg.fuso_horario,
                                                       repo.parametros()["papeis_cursista"])
        else:
            cad = repo.registros("cadastro")
            codigos = set(cad.loc[cad["inep_status"] == "valido", "inep"])
            ufs = set(cad["uf"].dropna()) | {config.UFS[c[:2]][0] for c in codigos}
            if not codigos:
                print("Importe o cadastro antes da base escolar (os códigos INEP definem as escolas selecionadas).")
                return 2
            url = None
            if args.baixar:
                caminho, info = school_data.baixar_microdados(args.baixar, cfg.dir_dados / "cache_inep",
                                                              lambda p: print(f"\r   download {p:.0%}", end=""))
                print(f"\n   {'cache local' if info.get('origem_cache') else 'baixado'}: {caminho.name} "
                      f"(publicado em {info.get('publicado_em')})")
                url = info.get("url")
            else:
                caminho = args.arquivos[0]
            dados, meta = school_data.ler_microdados(caminho, caminho.name, codigos, ufs)
            previa = school_data.preparar_escolas(school_data.normalizar_microdados(dados), meta,
                                                  school_data.FONTE_MICRODADOS, [{"arquivo": caminho.name}], url=url)
            encontrados = len(codigos & set(previa.registros["co_entidade"]))
            print(f"   códigos INEP do cadastro encontrados na base: {encontrados} de {len(codigos)}")
    except ErroImportacao as exc:
        print(f"Erro: {exc}")
        return 1
    _relatorio(previa, importacao.comparar_com_ativa(repo, previa))
    if not args.confirmar:
        print("\nValidação concluída. Nada foi gravado (use --confirmar para gravar).")
        return 0
    if not previa.pode_confirmar:
        print("\nImportação bloqueada; nada foi gravado.")
        return 1
    novo_id = importacao.confirmar(repo, previa, args.usuario)
    print(f"\nImportação nº {novo_id} gravada em {banco}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
