"""Etapa 3 — preço, frete e print, site por site.

Não procura nada: recebe do plano de coleta a lista de itens que aquele
site tem, com as URLs já descobertas na varredura.

Saída: data/coletas/{dominio}.jsonl — uma linha por registro, gravada
conforme vai coletando. Se o site cair na metade, o rerun pula o que já
existe e continua.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from src.adapters.base import Executor
from src.core import frete
from src.models import CEPS_SUL, Coleta, Item

DESTINO = Path("data/coletas")
PRINTS = Path("data/output/prints")


def ja_coletados(caminho: Path) -> set[tuple[str, str]]:
    """(id_item, uf) já gravados, para o rerun não refazer."""
    if not caminho.exists():
        return set()
    feitos = set()
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        if linha.strip():
            r = json.loads(linha)
            feitos.add((r["id_item"], r["uf"]))
    return feitos


def coletar_site(executor: Executor, itens: list[Item]) -> dict:
    """Coleta UM site inteiro. O executor chega aberto, e é reaproveitado
    pelos N itens da loja — é aqui que está a economia do projeto.

    Dois níveis: uma passada por item (preço e desconto, que não mudam
    entre UFs) e três por item (frete e print, que mudam).

    TODO: ler a URL do produto do plano de coleta, chamar executor.detalhar(),
    depois frete.cotar_produto() e executor.capturar_print() por UF.
    """
    dominio = executor.fornecedor.dominio
    DESTINO.mkdir(parents=True, exist_ok=True)
    arquivo = DESTINO / f"{dominio}.jsonl"
    feitos = ja_coletados(arquivo)

    gravados = 0
    with arquivo.open("a", encoding="utf-8") as saida:
        for item in itens:
            for uf in CEPS_SUL:
                if (item.id_item, uf) in feitos:
                    continue
                raise NotImplementedError
    return {"itens": len(itens), "gravados": gravados}


def caminho_print(categoria: str, id_item: str, dominio: str, uf: str) -> Path:
    """O montador deriva este mesmo caminho das colunas da linha —
    nenhuma amarração manual entre imagem e planilha."""
    return PRINTS / categoria / f"{id_item}__{dominio}__{uf}.png"
