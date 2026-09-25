"""Escolhe o executor certo para um fornecedor, pela plataforma detectada.

A plataforma detectada é um palpite bom, não uma garantia: ela vem de um
marcador no HTML da home, e marcador não prova que o endpoint de busca
está ligado. Por isso a escolha tem duas etapas — a plataforma indica o
adapter, e uma sonda confirma que a loja responde por ele.

Quem não responde cai no navegador. É mais lento e é o certo: varrer 132
itens por uma API que devolve 404 produz "0 achados" em todos eles, que
é exatamente igual a uma loja que não vende nada.
"""

from __future__ import annotations

from src.adapters.base import Executor
from src.adapters.generico_playwright import PlaywrightExecutor
from src.adapters.nuvemshop import NuvemshopExecutor
from src.adapters.shopify import ShopifyExecutor
from src.adapters.vtex import VtexExecutor
from src.adapters.woocommerce import WooExecutor
from src.core.http import Cliente
from src.core.log import obter
from src.models import Fornecedor, Plataforma

log = obter(__name__)

# Um arquivo por plataforma, uma pessoa por arquivo. Tray e Magento não
# têm adapter: vão direto para o navegador.
EXECUTORES: dict[Plataforma, type[Executor]] = {
    Plataforma.VTEX: VtexExecutor,
    Plataforma.WOOCOMMERCE: WooExecutor,
    Plataforma.SHOPIFY: ShopifyExecutor,
    Plataforma.NUVEMSHOP: NuvemshopExecutor,
}


def criar(fornecedor: Fornecedor, cliente: Cliente, sondar: bool = True) -> Executor:
    """O executor deste site, já confirmado contra a loja.

    `sondar=False` pula a confirmação e devolve o adapter da plataforma
    na fé — serve para teste e para quando a sonda já foi feita.
    """
    # Configuração conferida à mão é decisão tomada: quem preencheu
    # abriu a loja, buscou e viu o resultado. Nem sonda, nem adapter de
    # plataforma -- vai para o navegador, que é quem sabe usar as duas.
    if fornecedor.url_busca or fornecedor.seletor_busca:
        return PlaywrightExecutor(fornecedor, cliente)

    classe = EXECUTORES.get(fornecedor.plataforma)
    if classe is None:
        return PlaywrightExecutor(fornecedor, cliente)

    executor = classe(fornecedor, cliente)
    if not sondar or executor.api_responde():
        return executor

    log.warning("%s: detectado %s, mas a API nao responde -- varrendo pelo navegador",
                fornecedor.dominio, fornecedor.plataforma)
    return PlaywrightExecutor(fornecedor, cliente)
