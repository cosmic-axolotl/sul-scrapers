"""Escolhe o executor certo para um fornecedor, pela plataforma detectada."""

from __future__ import annotations

from src.adapters.base import Executor
from src.adapters.generico_playwright import PlaywrightExecutor
from src.adapters.nuvemshop import NuvemshopExecutor
from src.adapters.shopify import ShopifyExecutor
from src.adapters.vtex import VtexExecutor
from src.adapters.woocommerce import WooExecutor
from src.core.http import Cliente
from src.models import Fornecedor, Plataforma

# Um arquivo por plataforma, uma pessoa por arquivo. Só o VTEX tem busca
# implementada; os outros três são esqueleto.
EXECUTORES: dict[Plataforma, type[Executor]] = {
    Plataforma.VTEX: VtexExecutor,
    Plataforma.WOOCOMMERCE: WooExecutor,
    Plataforma.SHOPIFY: ShopifyExecutor,
    Plataforma.NUVEMSHOP: NuvemshopExecutor,
}


def criar(fornecedor: Fornecedor, cliente: Cliente) -> Executor:
    classe = EXECUTORES.get(fornecedor.plataforma, PlaywrightExecutor)
    return classe(fornecedor, cliente)
