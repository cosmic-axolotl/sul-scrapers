"""Qual executor cada loja recebe — e por quê a plataforma não basta.

A detecção lê um marcador no HTML da home. Marcador não prova endpoint
ligado: das 20 lojas WooCommerce aprovadas, 15 respondem 404 na Store
API. Sem a sonda, essas 15 varrem 132 itens contra um 404 e saem do
relatório como "não vende nada".
"""

from __future__ import annotations

import pytest

from src.adapters.generico_playwright import PlaywrightExecutor
from src.adapters.registro import criar
from src.adapters.vtex import VtexExecutor
from src.adapters.woocommerce import WooExecutor
from src.core.http import FalhaDeRede
from src.models import Fornecedor, Plataforma, Status


def loja(plataforma: Plataforma) -> Fornecedor:
    return Fornecedor(
        nome="Loja Exemplo",
        dominio="loja-exemplo.com.br",
        url_base="https://loja-exemplo.com.br",
        uf="PR",
        plataforma=plataforma,
        status=Status.APROVADO,
    )


def test_api_que_responde_fica_com_o_adapter_da_plataforma(cliente_falso):
    cliente = cliente_falso({"wp-json/wc/store": [{"name": "Panela"}]})

    assert isinstance(criar(loja(Plataforma.WOOCOMMERCE), cliente), WooExecutor)


def test_api_que_nao_responde_cai_para_o_navegador(cliente_falso):
    cliente = cliente_falso(erro=FalhaDeRede("status 404"))

    executor = criar(loja(Plataforma.WOOCOMMERCE), cliente)

    assert isinstance(executor, PlaywrightExecutor)


def test_a_sonda_bate_no_endpoint_da_plataforma(cliente_falso):
    cliente = cliente_falso({"catalog_system": []})

    criar(loja(Plataforma.VTEX), cliente)

    assert "api/catalog_system" in cliente.pedidos[0]


def test_plataforma_sem_adapter_vai_direto_para_o_navegador(cliente_falso):
    """Tray e Magento não têm API implementada; sondar seria requisição à toa."""
    cliente = cliente_falso()

    for plataforma in (Plataforma.TRAY, Plataforma.MAGENTO, Plataforma.DESCONHECIDA):
        executor = criar(loja(plataforma), cliente)
        assert isinstance(executor, PlaywrightExecutor)

    assert cliente.pedidos == []


def test_sondar_desligado_devolve_o_adapter_sem_perguntar(cliente_falso):
    cliente = cliente_falso(erro=FalhaDeRede("status 404"))

    executor = criar(loja(Plataforma.WOOCOMMERCE), cliente, sondar=False)

    assert isinstance(executor, WooExecutor)
    assert cliente.pedidos == []


@pytest.mark.parametrize("plataforma", [Plataforma.VTEX, Plataforma.WOOCOMMERCE,
                                        Plataforma.SHOPIFY])
def test_toda_plataforma_com_api_tem_sonda(plataforma, cliente_falso):
    executor = criar(loja(plataforma), cliente_falso(), sondar=False)
    assert executor.SONDA, f"{plataforma} precisa de SONDA para ser confirmada"
