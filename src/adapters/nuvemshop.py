"""Executor Nuvemshop/Tiendanube. Busca por HTML.

  /search?q={termo}

TODO: confirmar contra uma loja real e salvar a resposta em
tests/fixtures/ antes de confiar nos nomes de campo.
"""

from __future__ import annotations

from urllib.parse import quote

from src.adapters.base import Executor
from src.models import ProdutoBruto


class NuvemshopExecutor(Executor):
    plataforma = "nuvemshop"

    def buscar(self, termo: str) -> list[ProdutoBruto]:
        url = (f"{self.fornecedor.url_base.rstrip('/')}"
               f"/wp-json/wc/store/v1/products?search={quote(termo)}&per_page=20")
        raise NotImplementedError
