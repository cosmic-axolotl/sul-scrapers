"""Etapa 2 — a loja X tem algo parecido com o item Y?

Sem preço, sem frete, sem detalhe: guarda o link e segue. Separar isso
da coleta é o que permite rodar a varredura inteira em poucas horas e
descobrir cedo quais itens ninguém vende.

Saída: data/interim/achados/{dominio}.csv — um arquivo por site.
"""

from __future__ import annotations

import csv
from dataclasses import asdict
from pathlib import Path

from src.adapters.base import Executor
from src.core import matching
from src.models import Achado, Item

DESTINO = Path("data/interim/achados")


def varrer_site(executor: Executor, itens: list[Item]) -> dict:
    """Varre UM site atrás de TODOS os itens do seu lote.

    O executor já chegou aqui aberto, instanciado uma vez pelo
    orquestrador. Esta função nunca abre sessão.
    """
    achados: list[Achado] = []
    dominio = executor.fornecedor.dominio

    for item in itens:
        melhor: tuple[float, object] | None = None

        for termo in item.termos_busca or matching.gerar_termos(item):
            for produto in executor.buscar(termo):
                score = matching.pontuar(item.descricao, produto.titulo)
                if melhor is None or score > melhor[0]:
                    melhor = (score, produto)
            # Termos vão do mais específico ao mais genérico: se o
            # específico já deu match bom, não precisa dos outros.
            if melhor and matching.classificar(melhor[0]) == "aceito":
                break

        if melhor and matching.classificar(melhor[0]) != "descartado":
            score, produto = melhor
            achados.append(
                Achado(
                    id_item=item.id_item,
                    dominio=dominio,
                    url_produto=produto.url,
                    titulo_encontrado=produto.titulo,
                    score_match=round(score / 100, 3),
                    preco_indicativo=produto.preco,
                )
            )

    gravar(dominio, achados)
    return {"itens_buscados": len(itens), "achados": len(achados)}


def gravar(dominio: str, achados: list[Achado]) -> None:
    DESTINO.mkdir(parents=True, exist_ok=True)
    caminho = DESTINO / f"{dominio}.csv"
    if not achados:
        caminho.touch()
        return
    with caminho.open("w", newline="", encoding="utf-8") as f:
        escritor = csv.DictWriter(f, fieldnames=list(asdict(achados[0]).keys()))
        escritor.writeheader()
        for a in achados:
            escritor.writerow(asdict(a))
