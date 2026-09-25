"""Executor WooCommerce. Busca em JSON pela Store API.

  /wp-json/wc/store/v1/products?search={termo}

A Store API é pública e não pede chave, ao contrário da REST API
(/wp-json/wc/v3), que exige consumer key.

TODO: confirmar contra uma loja real e salvar a resposta em
tests/fixtures/ antes de confiar nos nomes de campo.

Atenção ao formato de preço: a Store API devolve STRING em unidade
menor, com `currency_minor_unit` dizendo quantas casas. "12990" com
minor_unit 2 é R$ 129,90 -- ler como float direto dá R$ 12.990,00.
"""

from __future__ import annotations

from urllib.parse import quote

from src.adapters.base import Executor
from src.core.http import ErroHTTP, RespostaInvalida, SiteBloqueado
from src.core.log import obter
from src.models import ProdutoBruto

log = obter(__name__)


class WooExecutor(Executor):
    plataforma = "woocommerce"

    # 15 das 20 lojas Woo aprovadas respondem 404 aqui. Quem não
    # responder é varrido pelo navegador -- ver Executor.api_responde().
    SONDA = "{base}/wp-json/wc/store/v1/products?per_page=1"

    def buscar(self, termo: str) -> list[ProdutoBruto]:
        url = (f"{self.fornecedor.url_base.rstrip('/')}"
               f"/wp-json/wc/store/v1/products?search={quote(termo)}&per_page=20")
        try:
            dados = self.cliente.get_json(url)
        except SiteBloqueado:
            raise
        except RespostaInvalida as e:
            log.error("%s: Store API nao devolveu JSON para %r (%s)",
                      self.fornecedor.dominio, termo, e)
            return []
        except ErroHTTP as e:
            log.error("%s: Store API falhou para %r (%s)",
                      self.fornecedor.dominio, termo, type(e).__name__)
            return []

        if not isinstance(dados, list):
            log.error("%s: Store API devolveu %s, esperava lista",
                      self.fornecedor.dominio, type(dados).__name__)
            return []

        produtos = [p for p in (self._produto(d) for d in dados) if p]
        log.info("%s: %r -> %d produtos", self.fornecedor.dominio, termo, len(produtos))
        return produtos

    def _produto(self, d: dict) -> ProdutoBruto | None:
        """Único lugar que conhece os nomes de campo da Store API."""
        if not isinstance(d, dict):
            return None
        precos = d.get("prices") or {}
        escala = 10 ** int(precos.get("currency_minor_unit", 2) or 0)

        preco = _para_real(precos.get("price"), escala)
        regular = _para_real(precos.get("regular_price"), escala)
        if regular is not None and preco is not None and regular <= preco:
            regular = None

        return ProdutoBruto(
            titulo=_sem_html(d.get("name") or ""),
            url=d.get("permalink") or "",
            preco=preco,
            disponivel=bool(d.get("is_in_stock", True)),
            sku=str(d.get("sku") or d.get("id") or "") or None,
            preco_lista=regular,
        )

    def detalhar(self, url_produto: str) -> ProdutoBruto:
        """A listagem da Store API já traz preço confiável.

        Sobrescrever isto só vale se a loja usar plugin de preço
        dinâmico, em que a listagem e a página divergem.
        """
        raise NotImplementedError(
            "WooCommerce: usar o produto da busca, ou implementar a leitura "
            "de /wp-json/wc/store/v1/products/{id} para esta loja"
        )


def _para_real(valor, escala: float) -> float | None:
    if valor in (None, ""):
        return None
    try:
        return float(valor) / escala
    except (TypeError, ValueError):
        return None


def _sem_html(texto: str) -> str:
    import html
    import re

    return html.unescape(re.sub(r"<[^>]+>", "", texto)).strip()
