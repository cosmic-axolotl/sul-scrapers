"""Uma loja VTEX de mentira, servida em localhost.

Existe para provar o fluxo inteiro sem tocar em site nenhum de verdade:
busca em JSON, ficha do produto, simulação de frete e uma página HTML
com campo de CEP -- que é o que o print precisa mostrar.

Ela é deliberadamente hostil nos pontos em que o pipeline já errou:
  - o primeiro SKU é a unidade avulsa de 30 cm, e o item pede o kit de 5;
  - o primeiro seller do kit está sem estoque e mais caro;
  - o preço tem ListPrice maior que Price (desconto de verdade);
  - o frete muda nos três CEPs do Sul.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

# Frete diferente por CEP: é o caso TABELA_POR_CEP, o mais comum.
FRETES = {"80010010": 2490, "88010400": 3150, "90010150": 3890}

PAGINA = """<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<title>Tabua de Corte Polietileno</title>
<style>
 body{{font-family:sans-serif;margin:40px;color:#111}}
 .preco{{font-size:32px;color:#0a7}} .riscado{{text-decoration:line-through;color:#888}}
 .frete{{margin-top:20px;padding:12px;border:1px solid #ccc;background:#f7f7f7}}
</style></head><body>
<h1>Tabua de Corte Polietileno &mdash; Kit 5 unidades 50 x 30 x 0,8 cm</h1>
<p class="riscado">De R$ 229,90</p>
<p class="preco">R$ 189,90</p>
<div class="frete">
  <label>Calcular frete. CEP: <input name="cep" id="cep" placeholder="Digite seu CEP"></label>
  <div id="resultado-frete"></div>
</div>
<script>
 const tabela = {tabela};
 const campo = document.getElementById('cep');
 function calcular() {{
   const cep = campo.value.replace(/\\D/g, '');
   const centavos = tabela[cep];
   document.getElementById('resultado-frete').innerHTML = centavos === undefined
     ? '<b>CEP fora da area de entrega</b>'
     : '<b>Entrega Normal: R$ ' + (centavos/100).toFixed(2).replace('.', ',') +
       ' &mdash; 7 dias uteis</b>';
 }}
 campo.addEventListener('change', calcular);
 campo.addEventListener('keydown', e => {{ if (e.key === 'Enter') calcular(); }});
</script>
</body></html>
"""


def _produto(base: str) -> dict:
    return {
        "productId": "1001",
        "productName": "Tabua de Corte Polietileno",
        "link": f"{base}/tabua-de-corte-polietileno/p",
        "linkText": "tabua-de-corte-polietileno",
        "items": [
            {
                "itemId": "5001",
                "name": "30 cm",
                "nameComplete": "Tabua de Corte Polietileno 30 cm unidade",
                "sellers": [{
                    "sellerId": "1", "sellerDefault": True,
                    "commertialOffer": {"Price": 39.9, "ListPrice": 49.9,
                                        "AvailableQuantity": 50},
                }],
            },
            {
                "itemId": "5002",
                "name": "Kit 5 unidades 50 x 30 x 0,8 cm",
                "nameComplete":
                    "Tabua de Corte Polietileno Kit 5 unidades 50 x 30 x 0,8 cm",
                "sellers": [
                    {"sellerId": "parceiro", "sellerDefault": False,
                     "commertialOffer": {"Price": 250.0, "ListPrice": 250.0,
                                         "AvailableQuantity": 0}},
                    {"sellerId": "1", "sellerDefault": True,
                     "commertialOffer": {"Price": 189.9, "ListPrice": 229.9,
                                         "AvailableQuantity": 12}},
                ],
            },
        ],
    }


def _manipulador(base_ref: dict):
    class Manipulador(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def _responder(self, corpo: str, tipo: str = "application/json") -> None:
            dados = corpo.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", f"{tipo}; charset=utf-8")
            self.send_header("Content-Length", str(len(dados)))
            self.end_headers()
            self.wfile.write(dados)

        def do_GET(self):
            caminho = urlparse(self.path).path
            if caminho == "/":
                # O marcador que src/core/plataforma.py procura.
                self._responder(
                    '<html><body><img src="https://loja.vtexassets.com/x.png">'
                    "</body></html>",
                    "text/html",
                )
            elif caminho.startswith("/api/catalog_system/pub/products/search"):
                termo = parse_qs(urlparse(self.path).query).get("ft", [""])[0].lower()
                achou = "tabua" in termo or "corte" in termo or caminho.endswith("/p")
                self._responder(json.dumps([_produto(base_ref["base"])] if achou else []))
            elif caminho.endswith("/p"):
                self._responder(PAGINA.format(tabela=json.dumps(FRETES)), "text/html")
            else:
                self.send_error(404)

        def do_POST(self):
            if "simulation" not in self.path:
                self.send_error(404)
                return
            tamanho = int(self.headers.get("Content-Length", 0))
            pedido = json.loads(self.rfile.read(tamanho) or "{}")
            preco = FRETES.get(pedido.get("postalCode", ""))
            if preco is None:
                self._responder(json.dumps({"logisticsInfo": [{"slas": []}]}))
                return
            self._responder(json.dumps({"logisticsInfo": [{"slas": [
                {"name": "Normal", "price": preco, "shippingEstimate": "7bd"},
                {"name": "Expressa", "price": preco * 2, "shippingEstimate": "2bd"},
            ]}]}))

    return Manipulador


def subir() -> tuple[HTTPServer, str]:
    """Sobe a loja numa porta livre. Devolve (servidor, url_base)."""
    base_ref = {"base": ""}
    servidor = HTTPServer(("127.0.0.1", 0), _manipulador(base_ref))
    base_ref["base"] = f"http://127.0.0.1:{servidor.server_port}"
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    return servidor, base_ref["base"]
