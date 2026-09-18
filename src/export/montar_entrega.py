"""Monta a entrega a partir de data/coletas/. Não raspa nada.

Lê a pasta inteira, junta com itens.csv e fornecedores_master.csv, corta
nos 5 fornecedores por item e UF, e escreve uma planilha por categoria.

Pode rodar com a coleta pela metade — e deve. Rodar isto no primeiro site
coletado, antes de disparar os outros quarenta, é meia hora que economiza
um dia.
"""

from __future__ import annotations

import argparse
from pathlib import Path

# As 15 colunas do template FNDE_output.xlsx, mais PRINT.
COLUNAS = [
    "Categoria", "Código FGV", "Item", "UF", "Data coleta", "Nome Empresa",
    "CNPJ", "FONTE", "PRODUTO PESQUISADO", "Preço PRODUTO", "VALOR DESCONTO",
    "OBS Desconto", "PREÇO FINAL", "VALOR FRETE", "OBS FRETE", "PRINT",
]

ALVO_POR_ITEM = 5


def escolher_cinco(candidatos: list[dict]) -> tuple[list[dict], list[dict]]:
    """Os 5 que vão para a entrega e os que sobram para a reserva.

    Critério, nessa ordem: maior score_match, depois menor preço final.
    A reserva vai para data/interim/reserva.csv e fica só no repositório.
    """
    ordenados = sorted(
        candidatos,
        key=lambda c: (-c.get("score_match", 0), c.get("preco_final") or float("inf")),
    )
    return ordenados[:ALVO_POR_ITEM], ordenados[ALVO_POR_ITEM:]


def montar(entrada: Path, saida: Path, categorias: list[str] | None = None) -> None:
    """TODO: ler os .jsonl, juntar, escolher os 5, gerar um .xlsx por
    categoria com a miniatura na coluna PRINT (ver export/prints.py)."""
    raise NotImplementedError


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--entrada", type=Path, default=Path("data/coletas"))
    p.add_argument("--saida", type=Path, default=Path("data/output"))
    p.add_argument("--categoria", action="append", dest="categorias")
    a = p.parse_args()
    montar(a.entrada, a.saida, a.categorias)
