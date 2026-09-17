import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import config as config


@dataclass
class Produto:
    fornecedor: str
    categoria: str
    nome: str
    marca: Optional[str]
    preco: float
    quantidade: Optional[float]
    unidade: Optional[str]
    preco_atacado: Optional[float] = None
    qtd_minima_atacado: Optional[int] = None
    desconto: Optional[str] = None
    # preço "cheio" riscado (ex: Asun); distinto de preco_atacado, que é
    # o preço por quantidade mínima (ex: Atacadão)
    preco_original: Optional[float] = None
    url_produto: Optional[str] = None
    imagem_print: Optional[str] = None
    coletado_em: str = None

    def __post_init__(self):
        if self.coletado_em is None:
            self.coletado_em = datetime.now().isoformat(timespec="seconds")


@contextmanager
def get_connection():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS produtos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fornecedor TEXT NOT NULL,
                categoria TEXT,
                nome TEXT NOT NULL,
                marca TEXT,
                preco REAL NOT NULL,
                quantidade REAL,
                unidade TEXT,
                preco_atacado REAL,
                qtd_minima_atacado INTEGER,
                desconto TEXT,
                url_produto TEXT,
                imagem_print TEXT,
                preco_original REAL,
                coletado_em TEXT NOT NULL
            )
            """)
        # Migrações incrementais para bancos criados antes desses campos
        # existirem (SQLite ignora ADD COLUMN se a coluna já existir e
        # gera OperationalError, que capturamos abaixo).
        for coluna_sql in (
            "ALTER TABLE produtos ADD COLUMN imagem_print TEXT",
            "ALTER TABLE produtos ADD COLUMN preco_original REAL",
        ):
            try:
                conn.execute(coluna_sql)
            except sqlite3.OperationalError:
                pass

        conn.execute("CREATE INDEX IF NOT EXISTS idx_nome ON produtos(nome)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_categoria ON produtos(categoria)")


def inserir_produto(produto: Produto) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO produtos (
                fornecedor, categoria, nome, marca, preco,
                quantidade, unidade, preco_atacado,
                qtd_minima_atacado, desconto, url_produto, imagem_print,
                preco_original, coletado_em
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                produto.fornecedor,
                produto.categoria,
                produto.nome,
                produto.marca,
                produto.preco,
                produto.quantidade,
                produto.unidade,
                produto.preco_atacado,
                produto.qtd_minima_atacado,
                produto.desconto,
                produto.url_produto,
                produto.imagem_print,
                produto.preco_original,
                produto.coletado_em,
            ),
        )


def listar_por_nome(apenas_ultima_coleta: bool = True) -> list[sqlite3.Row]:
    with get_connection() as conn:
        if apenas_ultima_coleta:
            query = """
                SELECT p.* FROM produtos p
                INNER JOIN (
                    SELECT nome, fornecedor, MAX(coletado_em) AS max_data
                    FROM produtos GROUP BY nome, fornecedor
                ) ultimo
                ON p.nome = ultimo.nome AND p.fornecedor = ultimo.fornecedor
                AND p.coletado_em = ultimo.max_data
                ORDER BY p.nome COLLATE NOCASE ASC
            """
        else:
            query = "SELECT * FROM produtos ORDER BY nome COLLATE NOCASE ASC"
        return conn.execute(query).fetchall()


def filtrar_por_categoria_ou_palavra(termo: str) -> list[sqlite3.Row]:
    termo_like = f"%{termo}%"
    with get_connection() as conn:
        query = """
            SELECT * FROM produtos
            WHERE nome LIKE ? COLLATE NOCASE
               OR marca LIKE ? COLLATE NOCASE
               OR categoria LIKE ? COLLATE NOCASE
            ORDER BY coletado_em DESC
        """
        return conn.execute(query, (termo_like, termo_like, termo_like)).fetchall()


if __name__ == "__main__":
    init_db()
    print("Banco inicializado em:", config.DB_PATH)
    print("Produtos por nome:", len(listar_por_nome()))
