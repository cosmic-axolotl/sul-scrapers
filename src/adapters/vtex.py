"""Executor VTEX. É o mais barato: busca e frete saem em JSON.

Referência de endpoints (confirmar contra uma loja real antes de
confiar — salve a resposta em tests/fixtures/):
  busca:  /api/catalog_system/pub/products/search?ft={termo}
  frete:  /api/checkout/pub/orderForms/simulation?sc=1
"""

from __future__ import annotations

from urllib.parse import quote

from src.adapters.base import Executor
from src.models import ProdutoBruto


class VtexExecutor(Executor):
    plataforma = "vtex"

    def buscar(self, termo: str) -> list[ProdutoBruto]:
        url = (
            f"{self.fornecedor.url_base.rstrip('/')}"
            f"/api/catalog_system/pub/products/search?ft={quote(termo)}&_from=0&_to=23"
        )
        try:
            dados = self.cliente.get_json(url)
        except Exception:
            return []

        produtos: list[ProdutoBruto] = []
        for p in dados if isinstance(dados, list) else []:
            item = (p.get("items") or [{}])[0]
            oferta = (item.get("sellers") or [{}])[0].get("commertialOffer", {})
            produtos.append(
                ProdutoBruto(
                    titulo=p.get("productName", ""),
                    url=p.get("link", ""),
                    preco=oferta.get("Price"),
                    disponivel=bool(oferta.get("AvailableQuantity", 0)),
                    sku=item.get("itemId"),
                )
            )
        return produtos

    def cotar_frete(self, url_produto: str, cep: str) -> tuple[float | None, str]:
        """TODO: POST em /api/checkout/pub/orderForms/simulation com
        {"items":[{"id": sku, "quantity":1, "seller":"1"}],
         "country":"BRA", "postalCode": cep}
        e pegar o menor logisticsInfo[].slas[].price (em centavos).
        """
        raise NotImplementedError
