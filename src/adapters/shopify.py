"""Executor Shopify. Busca em JSON pelo endpoint de sugestões.

  /search/suggest.json?q={termo}&resources[type]=product
  /{handle}.js                  -> as variações de um produto

TODO: confirmar contra uma loja real e salvar a resposta em
tests/fixtures/ antes de confiar nos nomes de campo.

Duas chamadas, e não uma, porque suggest.json devolve o produto e não as
variações: numa página de tábua com 30, 40 e 50 cm ele dá um resultado
só, com o preço da variação mais barata. Como é a medida que decide se o
produto atende o item, as variações precisam vir -- mesmo custando uma
requisição a mais por produto.

Shopify devolve preço em CENTAVOS no endpoint .js e em texto formatado
no suggest.json. Os dois estão tratados abaixo.
"""

from __future__ import annotations

from urllib.parse import quote, urlparse

from src.adapters.base import Executor
from src.core.http import ErroHTTP, RespostaInvalida, SiteBloqueado
from src.core.log import obter
from src.models import ProdutoBruto

log = obter(__name__)

CENTAVOS = 100.0

# Cada produto custa uma requisição extra para pegar as variações. Acima
# disso o ganho não paga o tempo: a busca já vem ordenada por relevância.
MAX_PRODUTOS_DETALHADOS = 8


class ShopifyExecutor(Executor):
    plataforma = "shopify"

    SONDA = "{base}/search/suggest.json?q=a&resources[type]=product"

    def buscar(self, termo: str) -> list[ProdutoBruto]:
        base = self.fornecedor.url_base.rstrip("/")
        url = (f"{base}/search/suggest.json?q={quote(termo)}"
               f"&resources[type]=product&resources[limit]=10")
        try:
            dados = self.cliente.get_json(url)
        except SiteBloqueado:
            raise
        except RespostaInvalida as e:
            log.error("%s: suggest.json nao devolveu JSON para %r (%s)",
                      self.fornecedor.dominio, termo, e)
            return []
        except ErroHTTP as e:
            log.error("%s: suggest.json falhou para %r (%s)",
                      self.fornecedor.dominio, termo, type(e).__name__)
            return []

        achados = (
            (dados or {}).get("resources", {}).get("results", {}).get("products", [])
            if isinstance(dados, dict) else []
        )
        if not achados:
            log.info("%s: %r -> nenhum produto", self.fornecedor.dominio, termo)
            return []

        produtos: list[ProdutoBruto] = []
        for p in achados[:MAX_PRODUTOS_DETALHADOS]:
            produtos.extend(self._variacoes(base, p))

        log.info("%s: %r -> %d produtos, %d variacoes",
                 self.fornecedor.dominio, termo, len(achados), len(produtos))
        return produtos

    def _variacoes(self, base: str, p: dict) -> list[ProdutoBruto]:
        """Uma linha por variação; cai para o produto se o .js falhar."""
        if not isinstance(p, dict):
            return []

        caminho = p.get("url") or ""
        url_produto = caminho if caminho.startswith("http") else f"{base}{caminho}"
        titulo = p.get("title") or ""

        handle = p.get("handle") or _handle(caminho)
        if handle:
            try:
                ficha = self.cliente.get_json(f"{base}/products/{handle}.js")
            except SiteBloqueado:
                raise
            except ErroHTTP as e:
                log.debug("%s: .js falhou para %s (%s)",
                          self.fornecedor.dominio, handle, type(e).__name__)
            else:
                variacoes = self._do_js(ficha, url_produto, titulo)
                if variacoes:
                    return variacoes

        return [ProdutoBruto(
            titulo=titulo,
            url=url_produto,
            preco=_preco_texto(p.get("price")),
            disponivel=bool(p.get("available", True)),
        )]

    @staticmethod
    def _do_js(ficha, url_produto: str, titulo: str) -> list[ProdutoBruto]:
        if not isinstance(ficha, dict):
            return []
        nome = ficha.get("title") or titulo
        saida: list[ProdutoBruto] = []

        for v in ficha.get("variants") or []:
            if not isinstance(v, dict):
                continue
            nome_variacao = (v.get("title") or "").strip()
            # "Default Title" é o rótulo do Shopify para produto sem
            # variação: colar isso no título só atrapalha o matching.
            if nome_variacao.lower() in ("default title", "default"):
                nome_variacao = ""

            preco = _centavos(v.get("price"))
            comparado = _centavos(v.get("compare_at_price"))
            if comparado is not None and preco is not None and comparado <= preco:
                comparado = None

            saida.append(ProdutoBruto(
                titulo=f"{nome} {nome_variacao}".strip(),
                url=f"{url_produto}?variant={v.get('id')}" if v.get("id") else url_produto,
                preco=preco,
                disponivel=bool(v.get("available", True)),
                sku=str(v.get("sku") or v.get("id") or "") or None,
                preco_lista=comparado,
                variacao=nome_variacao or None,
            ))
        return saida


def _handle(caminho: str) -> str:
    partes = [p for p in urlparse(caminho).path.split("/") if p]
    return partes[-1] if partes else ""


def _centavos(valor) -> float | None:
    if valor in (None, ""):
        return None
    try:
        return float(valor) / CENTAVOS
    except (TypeError, ValueError):
        return None


def _preco_texto(valor) -> float | None:
    """'R$ 1.299,90' -> 1299.90. suggest.json devolve o preço formatado."""
    if valor in (None, ""):
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    limpo = "".join(c for c in str(valor) if c.isdigit() or c in ".,")
    if "," in limpo:  # formato pt-BR: ponto é milhar, vírgula é decimal
        limpo = limpo.replace(".", "").replace(",", ".")
    try:
        return float(limpo)
    except ValueError:
        return None
