"""Detecta a plataforma de e-commerce lendo o HTML da home, uma vez.

Este módulo é o atalho que evita escrever 50 scrapers. A maioria das
lojas roda numa de meia dúzia de plataformas, e quatro delas expõem
busca em JSON — sem navegador, sem parser de HTML.
"""

from __future__ import annotations

from src.core.http import Cliente
from src.models import Plataforma

# Ordem importa: o primeiro marcador que casar decide.
MARCADORES: list[tuple[Plataforma, tuple[str, ...]]] = [
    (Plataforma.VTEX, ("vtexassets.com", "vteximg.com.br", "vtex.com.br")),
    (Plataforma.SHOPIFY, ("cdn.shopify.com", "shopify-features")),
    (Plataforma.NUVEMSHOP, ("nuvemshop", "tiendanube", "d2r9epyceweg5n.cloudfront.net")),
    (Plataforma.TRAY, ("tray.com.br", "traycdn")),
    (Plataforma.MAGENTO, ("catalogsearch", "/static/version", "Mage.Cookies")),
    (Plataforma.WOOCOMMERCE, ("wp-content", "woocommerce")),
]


def detectar(url_base: str, cliente: Cliente) -> Plataforma:
    try:
        html = cliente.get(url_base)
    except Exception:
        return Plataforma.DESCONHECIDA
    return detectar_no_html(html)


def detectar_no_html(html: str) -> Plataforma:
    baixo = html.lower()
    for plataforma, marcadores in MARCADORES:
        if any(m.lower() in baixo for m in marcadores):
            return plataforma
    return Plataforma.DESCONHECIDA
