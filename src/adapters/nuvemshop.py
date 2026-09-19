"""Executor Nuvemshop/Tiendanube. Busca por HTML.

  /search?q={termo}

Nuvemshop não tem busca pública em JSON: a API de loja pede token de
aplicativo. O que a página entrega de graça é JSON-LD -- o bloco
<script type="application/ld+json"> que a plataforma injeta para o Google
ler. É JSON estruturado dentro do HTML, e é muito mais estável do que
qualquer seletor de CSS, que muda a cada troca de tema.

TODO: confirmar contra uma loja real e salvar a resposta em
tests/fixtures/ antes de confiar nos nomes de campo. Loja com tema
antigo pode não emitir JSON-LD: nesse caso ela cai no PlaywrightExecutor,
que é o caminho certo para HTML que depende de tema.
"""

from __future__ import annotations

import json
import re
from urllib.parse import quote, urljoin

from src.adapters.base import Executor
from src.core.http import ErroHTTP, SiteBloqueado
from src.core.log import obter
from src.models import ProdutoBruto

log = obter(__name__)

RE_JSONLD = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)


class NuvemshopExecutor(Executor):
    plataforma = "nuvemshop"

    def buscar(self, termo: str) -> list[ProdutoBruto]:
        base = self.fornecedor.url_base.rstrip("/")
        url = f"{base}/search?q={quote(termo)}"
        try:
            html = self.cliente.get(url)
        except SiteBloqueado:
            raise
        except ErroHTTP as e:
            log.error("%s: busca falhou para %r (%s)",
                      self.fornecedor.dominio, termo, type(e).__name__)
            return []

        produtos = [
            p for p in (self._produto(no, base) for no in _produtos_jsonld(html)) if p
        ]
        if not produtos:
            log.info("%s: %r -> nenhum produto no JSON-LD (tema sem JSON-LD?)",
                     self.fornecedor.dominio, termo)
        else:
            log.info("%s: %r -> %d produtos",
                     self.fornecedor.dominio, termo, len(produtos))
        return produtos

    def _produto(self, no: dict, base: str) -> ProdutoBruto | None:
        """Único lugar que conhece o formato do JSON-LD."""
        oferta = no.get("offers")
        if isinstance(oferta, list):
            oferta = oferta[0] if oferta else {}
        oferta = oferta if isinstance(oferta, dict) else {}

        url = no.get("url") or oferta.get("url") or ""
        disponibilidade = str(oferta.get("availability") or "").lower()

        return ProdutoBruto(
            titulo=str(no.get("name") or "").strip(),
            url=urljoin(base + "/", url) if url else "",
            preco=_numero(oferta.get("price") or oferta.get("lowPrice")),
            disponivel="outofstock" not in disponibilidade.replace("_", ""),
            sku=str(no.get("sku") or "") or None,
        )


def _produtos_jsonld(html: str) -> list[dict]:
    """Todo nó @type=Product de todos os blocos JSON-LD da página."""
    encontrados: list[dict] = []

    for bloco in RE_JSONLD.findall(html or ""):
        try:
            dados = json.loads(bloco.strip())
        except ValueError:
            continue
        _coletar(dados, encontrados)

    return encontrados


def _coletar(no, saida: list[dict]) -> None:
    """JSON-LD aninha Product dentro de ItemList, @graph e listas soltas."""
    if isinstance(no, list):
        for filho in no:
            _coletar(filho, saida)
        return
    if not isinstance(no, dict):
        return

    tipo = no.get("@type")
    tipos = tipo if isinstance(tipo, list) else [tipo]
    if "Product" in tipos:
        saida.append(no)
        return

    for chave in ("@graph", "itemListElement", "item", "mainEntity"):
        if chave in no:
            _coletar(no[chave], saida)


def _numero(valor) -> float | None:
    if valor in (None, ""):
        return None
    texto = str(valor).strip()
    if "," in texto and "." in texto:
        texto = texto.replace(".", "").replace(",", ".")
    elif "," in texto:
        texto = texto.replace(",", ".")
    try:
        return float(texto)
    except ValueError:
        return None
