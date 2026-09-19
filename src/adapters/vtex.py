"""Executor VTEX. É o mais barato: busca e frete saem em JSON.

Referência de endpoints (confirmar contra uma loja real antes de
confiar -- salve a resposta em tests/fixtures/):
  busca:  /api/catalog_system/pub/products/search?ft={termo}
  ficha:  /api/catalog_system/pub/products/search/{slug}/p
  frete:  /api/checkout/pub/orderForms/simulation?sc=1

Três decisões deste arquivo, todas pelo mesmo motivo -- a planilha tem
uma linha por item, e a linha errada não dá para descobrir depois:

1. **Uma linha por SKU, não por produto.** A versão anterior pegava
   `items[0]`: numa página de tábua de corte com 30, 40 e 50 cm, isso
   devolve sempre a primeira variação, com o preço dela. O matching é
   quem sabe qual medida foi pedida, então o adapter devolve todas e
   deixa a escolha para quem tem a descrição do item na mão.

2. **Todos os sellers, não `sellers[0]`.** O primeiro seller pode ser um
   lojista de marketplace sem estoque. Preferimos o seller padrão e,
   entre os disponíveis, o mais barato.

3. **`ListPrice` e `Price` são coisas diferentes.** `Price` é o que se
   paga; `ListPrice` é o preço riscado. A entrega tem coluna para os
   dois mais a diferença, e ler só um dos campos apaga o desconto.

Exceção não vira lista vazia: um timeout e um "a loja não vende isso"
tinham a mesma aparência no resultado da varredura, e a pessoa ia
reescrever o termo de busca quando o problema era outro.
"""

from __future__ import annotations

from urllib.parse import quote, urlparse

from src.adapters.base import Executor
from src.core.frete import SEM_ENTREGA
from src.core.http import ErroHTTP, RespostaInvalida, SiteBloqueado
from src.core.log import obter
from src.models import ProdutoBruto

log = obter(__name__)

# VTEX devolve preço em reais na API de catálogo e em CENTAVOS na de
# checkout (frete). Confundir os dois dá frete de R$ 1.590,00.
CENTAVOS = 100.0


class VtexExecutor(Executor):
    plataforma = "vtex"

    # --- Etapa 2: varredura -------------------------------------------------

    def buscar(self, termo: str) -> list[ProdutoBruto]:
        url = (
            f"{self.fornecedor.url_base.rstrip('/')}"
            f"/api/catalog_system/pub/products/search?ft={quote(termo)}&_from=0&_to=23"
        )
        try:
            dados = self.cliente.get_json(url)
        except SiteBloqueado:
            # Bloqueio não é "não achei": sobe para o runner registrar o
            # domínio e parar de insistir nele.
            raise
        except RespostaInvalida as e:
            log.error("%s: busca VTEX nao devolveu JSON para %r (%s)",
                      self.fornecedor.dominio, termo, e)
            return []
        except ErroHTTP as e:
            log.error("%s: busca VTEX falhou para %r (%s)",
                      self.fornecedor.dominio, termo, type(e).__name__)
            return []

        if not isinstance(dados, list):
            log.error("%s: busca VTEX devolveu %s, esperava lista (termo %r)",
                      self.fornecedor.dominio, type(dados).__name__, termo)
            return []

        produtos = self._produtos_do_json(dados)
        log.info("%s: %r -> %d produtos, %d variacoes",
                 self.fornecedor.dominio, termo, len(dados), len(produtos))
        return produtos

    def _produtos_do_json(self, dados: list) -> list[ProdutoBruto]:
        """Achata produto -> SKUs -> seller escolhido.

        Único lugar que conhece os nomes de campo da VTEX. Se a loja
        responder num formato diferente, conserta-se aqui.
        """
        produtos: list[ProdutoBruto] = []

        for p in dados:
            if not isinstance(p, dict):
                continue
            nome_produto = p.get("productName") or ""
            link = p.get("link") or p.get("linkText") or ""

            for sku in p.get("items") or []:
                oferta = self._melhor_oferta(sku.get("sellers") or [])
                if oferta is None:
                    continue
                vendedor, comercial = oferta

                nome_sku = (sku.get("nameComplete") or sku.get("name") or "").strip()
                # "Tábua de Corte" + "50 cm" -- o matching precisa da
                # medida no título, senão não tem como comparar.
                titulo = nome_sku if nome_sku.startswith(nome_produto) else (
                    f"{nome_produto} {nome_sku}".strip() if nome_sku else nome_produto
                )

                preco = _numero(comercial.get("Price"))
                lista = _numero(comercial.get("ListPrice")) or _numero(
                    comercial.get("PriceWithoutDiscount")
                )
                # ListPrice às vezes vem igual ou menor que Price; nesse
                # caso não há desconto para registrar.
                if lista is not None and preco is not None and lista <= preco:
                    lista = None

                produtos.append(
                    ProdutoBruto(
                        titulo=titulo,
                        url=self._url_sku(link, sku.get("itemId")),
                        preco=preco,
                        disponivel=bool(comercial.get("AvailableQuantity", 0)),
                        sku=sku.get("itemId"),
                        preco_lista=lista,
                        vendedor=vendedor,
                        variacao=nome_sku or None,
                    )
                )

        return produtos

    @staticmethod
    def _melhor_oferta(sellers: list) -> tuple[str, dict] | None:
        """(sellerId, commertialOffer) do seller que vamos citar.

        Ordem: quem tem estoque, depois o seller padrão da loja, depois o
        mais barato. Um marketplace sem estoque listado primeiro não pode
        definir o preço que vai para a planilha.
        """
        candidatos: list[tuple[bool, bool, float, str, dict]] = []
        for s in sellers:
            if not isinstance(s, dict):
                continue
            oferta = s.get("commertialOffer") or {}
            preco = _numero(oferta.get("Price"))
            candidatos.append((
                not bool(oferta.get("AvailableQuantity", 0)),  # False ordena antes
                not bool(s.get("sellerDefault")),
                preco if preco is not None else float("inf"),
                str(s.get("sellerId") or ""),
                oferta,
            ))

        if not candidatos:
            return None
        escolhido = min(candidatos, key=lambda c: c[:4])
        return escolhido[3], escolhido[4]

    @staticmethod
    def _url_sku(link: str, sku_id: str | None) -> str:
        """A URL da variação, não a do produto.

        Sem `?skuId=`, o print abre na variação padrão da loja e não na
        que foi cotada -- e o print é a prova do preço.
        """
        if not link or not sku_id:
            return link
        juncao = "&" if "?" in link else "?"
        return f"{link}{juncao}skuId={sku_id}"

    # --- Etapa 3: coleta ----------------------------------------------------

    def detalhar(self, url_produto: str) -> ProdutoBruto:
        """Relê a ficha do produto na hora da coleta.

        A listagem de busca pode estar desatualizada em relação à página;
        o preço que vai para a entrega tem que ser o mesmo que o print
        mostra.
        """
        slug = _slug(url_produto)
        url = (
            f"{self.fornecedor.url_base.rstrip('/')}"
            f"/api/catalog_system/pub/products/search/{slug}/p"
        )
        dados = self.cliente.get_json(url)
        if not isinstance(dados, list) or not dados:
            raise RespostaInvalida(f"ficha vazia para {url_produto}", url)

        variacoes = self._produtos_do_json(dados)
        if not variacoes:
            raise RespostaInvalida(f"sem SKU vendavel em {url_produto}", url)

        # A URL carrega o skuId desde a varredura: é a variação que foi
        # aprovada pelo matching, e nenhuma outra serve.
        sku_pedido = _sku_da_url(url_produto)
        if sku_pedido:
            for v in variacoes:
                if v.sku == sku_pedido:
                    return v
            log.warning("%s: SKU %s sumiu da ficha %s; usando a variacao disponivel",
                        self.fornecedor.dominio, sku_pedido, url_produto)
        return variacoes[0]

    def cotar_frete(
        self,
        url_produto: str,
        cep: str,
        produto: ProdutoBruto | None = None,
    ) -> tuple[float | None, str]:
        """Menor SLA da simulação de checkout, para 1 unidade naquele CEP.

        `produto` vem da coleta, que já chamou `detalhar()` uma vez e não
        precisa repetir a requisição a cada uma das três UFs. O seller
        tem que ser o mesmo que definiu o preço: cotar frete do seller A
        com preço do seller B monta uma linha que não existe na loja.
        """
        sku = (produto.sku if produto else None) or _sku_da_url(url_produto)
        vendedor = produto.vendedor if produto else None
        if not sku:
            achado = self.detalhar(url_produto)
            sku, vendedor = achado.sku, achado.vendedor
        if not sku:
            return None, "SKU desconhecido: nao deu para simular o frete"

        url = (f"{self.fornecedor.url_base.rstrip('/')}"
               f"/api/checkout/pub/orderForms/simulation?sc=1")
        corpo = {
            "items": [{"id": str(sku), "quantity": 1, "seller": str(vendedor or "1")}],
            "country": "BRA",
            "postalCode": _digitos(cep),
        }

        try:
            dados = self.cliente.post_json(url, corpo)
        except ErroHTTP as e:
            log.warning("%s: simulacao de frete falhou (%s)",
                        self.fornecedor.dominio, type(e).__name__)
            return None, f"simulacao de frete indisponivel ({type(e).__name__})"

        if not isinstance(dados, dict):
            return None, "simulacao devolveu formato inesperado"

        slas = [
            sla
            for info in (dados.get("logisticsInfo") or [])
            for sla in (info.get("slas") or [])
            if isinstance(sla, dict)
        ]
        if not slas:
            # A loja respondeu e nao entrega neste CEP. O marcador vem de
            # core.frete porque quem le isso -- a etapa 1, para reprovar, e
            # o montador, para nao deixar a linha entrar sem frete -- precisa
            # distinguir recusa de "nao consegui cotar".
            return None, f"{SEM_ENTREGA} para este CEP"

        melhor = min(slas, key=lambda s: _numero(s.get("price")) or 0.0)
        centavos = _numero(melhor.get("price"))
        if centavos is None:
            return None, "SLA sem preco"

        valor = centavos / CENTAVOS
        nome = melhor.get("name") or "entrega"
        prazo = melhor.get("shippingEstimate") or ""
        if valor == 0:
            return 0.0, f"frete gratis ({nome} {prazo})".strip()
        return valor, f"{nome} {prazo}".strip()


# ---------------------------------------------------------------------------

def _numero(valor) -> float | None:
    """VTEX manda número, string e None no mesmo campo conforme a loja."""
    if valor is None or isinstance(valor, bool):
        return None
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def _digitos(texto: str) -> str:
    return "".join(c for c in str(texto) if c.isdigit())


def _slug(url_produto: str) -> str:
    """'https://loja.com.br/tabua-corte-50cm/p?skuId=9' -> 'tabua-corte-50cm'"""
    caminho = urlparse(url_produto).path.strip("/")
    partes = [p for p in caminho.split("/") if p and p != "p"]
    return partes[-1] if partes else caminho


def _sku_da_url(url_produto: str) -> str | None:
    from urllib.parse import parse_qs

    valores = parse_qs(urlparse(url_produto).query).get("skuId")
    return valores[0] if valores else None
