"""Executor Shopify. Busca em JSON pelo endpoint de sugestões.

  /search/suggest.json?q={termo}&resources[type]=product

TODO: confirmar contra uma loja real e salvar a resposta em
tests/fixtures/ antes de confiar nos nomes de campo.
"""

from __future__ import annotations

from urllib.parse import quote

from src.adapters.base import Executor
from src.models import ProdutoBruto


class ShopifyExecutor(Executor):
    plataforma = "shopify"

    def buscar(self, termo: str) -> list[ProdutoBruto]:
        url = (f"{self.fornecedor.url_base.rstrip('/')}"
               f"/wp-json/wc/store/v1/products?search={quote(termo)}&per_page=20")
        raise NotImplementedError
