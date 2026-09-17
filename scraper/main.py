import argparse
import logging

import config
import database
from scraper import executar_coletas
import sheets_sync

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


def imprimir_tabela(
    titulo: str,
    linhas,
    colunas=(
        "nome",
        "marca",
        "preco",
        "preco_original",
        "preco_atacado",
        "url_produto",
        "imagem_print",
    ),
):
    print(f"\n=== {titulo} ({len(linhas)} itens) ===")
    if not linhas:
        print("  (nenhum registro encontrado)")
        return
    for linha in linhas[:20]:
        valores = []
        for c in colunas:
            val = linha[c]
            if val is None:
                valores.append("-")
            else:
                valores.append(str(val))
        print("  - " + " | ".join(valores))
    if len(linhas) > 20:
        print(
            f"  ... e mais {len(linhas) - 20} itens (veja no banco/planilha completos)"
        )


def rodar_relatorios(termo_filtro: str | None = None):
    imprimir_tabela("Produtos ordenados por nome (A-Z)", database.listar_por_nome())

    if termo_filtro:
        imprimir_tabela(
            f"Produtos filtrados por '{termo_filtro}'",
            database.filtrar_por_categoria_ou_palavra(termo_filtro),
        )


def main():
    parser = argparse.ArgumentParser(
        description="Bot de coleta de preços em sites de atacado"
    )
    parser.add_argument(
        "--sem-sheets", action="store_true", help="Não sincroniza com o Google Sheets"
    )
    parser.add_argument(
        "--so-relatorio",
        action="store_true",
        help="Só exibe relatórios do banco atual, sem coletar",
    )
    parser.add_argument(
        "--filtro",
        type=str,
        default=None,
        help="Termo para o relatório de filtro por palavra-chave",
    )
    args = parser.parse_args()

    database.init_db()

    if not args.so_relatorio:
        from data.produtos import TAREFAS_DE_COLETA

        logger.info("Iniciando coleta para %d tarefa(s)...", len(TAREFAS_DE_COLETA))
        produtos = executar_coletas(TAREFAS_DE_COLETA, cep=config.CEP)

        logger.info("Gravando %d produtos no banco SQLite...", len(produtos))
        for produto in produtos:
            database.inserir_produto(produto)

        if not args.sem_sheets:
            try:
                sheets_sync.sincronizar_produtos(produtos)
            except FileNotFoundError:
                logger.error(
                    "Credencial do Google não encontrada em %s. "
                    "Rode com --sem-sheets ou configure as credenciais (veja README.md).",
                    config.GOOGLE_SHEETS_CREDENTIALS_PATH,
                )
            except Exception:
                logger.exception(
                    "Falha ao sincronizar com Google Sheets (a coleta e o banco foram salvos normalmente)."
                )
    else:
        logger.info(
            "Modo --so-relatorio: pulando coleta, usando dados já existentes no banco."
        )

    rodar_relatorios(termo_filtro=args.filtro)


if __name__ == "__main__":
    main()
