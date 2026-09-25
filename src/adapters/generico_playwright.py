"""Fallback para lojas sem plataforma reconhecida: busca pelo navegador.

É o executor de 66 dos 89 sites aprovados — as 58 lojas em que a
detecção não reconheceu plataforma, mais as de Tray e Magento, que não
têm adapter de API. Sem ele a primeira varredura cobre um quarto da
lista.

Só use quando o conteúdo depende de JavaScript, existe desafio de bot
ou a plataforma não expõe busca em JSON. Uma busca via navegador custa
~4 s contra ~200 ms de uma chamada JSON — por isso VTEX, WooCommerce,
Shopify e Nuvemshop têm adapter próprio e não passam por aqui.

## Como ele acha a barra de pesquisa

Três tentativas, nesta ordem, e a primeira que funciona vira o caminho
fixo da sessão (`self._caminho`), para não refazer a descoberta a cada
item:

1. **O campo na home.** Os seletores de `SELETORES_BUSCA`, do mais
   específico ao mais genérico. Digita o termo e dá Enter.
2. **O botão de lupa.** Muita loja só monta o campo depois do clique.
   Clica, espera o campo aparecer e volta ao passo 1.
3. **A URL de busca.** `/busca?q=`, `/?s=`, `/catalogsearch/result/?q=`
   e companhia, na ordem que a plataforma detectada sugere. Loja que
   bloqueia digitação costuma responder a URL montada.

Site em que nada disso funciona não é um bug a resolver no genérico:
sobrescreva `URL_BUSCA` ou `SEL_BUSCA` numa subclasse. É para isso que
os dois existem.

## O que ele devolve

`ProdutoBruto` com título e URL — a varredura não precisa de mais nada.
Preço entra quando aparece no card, como indicativo: preço de verdade é
a etapa 3, na página do produto, com o CEP preenchido.

A extração roda como JavaScript dentro da página (`EXTRAIR`), porque só
lá o DOM já está renderizado. A conversão para `ProdutoBruto` é função
pura (`produtos_da_pagina`) e é o que os testes exercitam.
"""

from __future__ import annotations

import random
import re
import time
from urllib.parse import quote_plus, urljoin

from src.adapters.base import Executor
from src.core.http import INTERVALO_MAX, INTERVALO_MIN, FalhaDeRede, SiteBloqueado
from src.core.log import obter
from src.models import Plataforma, ProdutoBruto

log = obter(__name__)

TEMPO_NAVEGACAO_MS = 45000
TEMPO_SELETOR_MS = 5000
ESPERA_RESULTADO_MS = 3500
MAX_PRODUTOS = 30

# Termo que nenhuma loja vende. Serve para provar que a busca filtra: se
# ela devolve o mesmo resultado para isto e para "panela", não está
# buscando nada -- devolve a vitrine. Uma loja Magento real respondeu as
# mesmas 20 botinas para "panela" e para "tabua de corte".
TERMO_IMPOSSIVEL = "zzqxwv"
LARGURA, ALTURA = 1366, 900

# Ordem de tentativa do campo de busca: nome exato antes de nome que só
# contém, e atributo estável (type, name) antes de placeholder, que muda
# com a campanha de marketing da loja.
SELETORES_BUSCA = (
    "input[type='search']",
    "form[role='search'] input[type='text']",
    "input[name='q']",
    "input[name='s']",
    "input[name='busca']",
    "input[name='search']",
    "input[name='palavra']",
    "input[name*='busca' i]",
    "input[name*='pesquis' i]",
    "input[name*='search' i]",
    "input[name*='query' i]",
    "input[id*='busca' i]",
    "input[id*='pesquis' i]",
    "input[id*='search' i]",
    "input[placeholder*='busca' i]",
    "input[placeholder*='buscar' i]",
    "input[placeholder*='pesquis' i]",
    "input[placeholder*='procur' i]",
    "input[placeholder*='o que voc' i]",
    "input[placeholder*='search' i]",
    "input[aria-label*='busca' i]",
    "input[aria-label*='pesquis' i]",
    "input[aria-label*='search' i]",
)

# A lupa que monta o campo só depois do clique.
SELETORES_LUPA = (
    "[aria-label*='busca' i]",
    "[aria-label*='pesquis' i]",
    "[aria-label*='search' i]",
    "button[class*='search' i]",
    "button[class*='busca' i]",
    "[class*='search-toggle' i]",
    "[class*='btn-search' i]",
    "[data-testid*='search' i]",
)

# URL de busca por plataforma. A ordem geral cobre o que as lojas
# brasileiras usam; a plataforma detectada, quando existe, promove o
# padrão dela para o primeiro lugar.
URLS_BUSCA = (
    "{base}/busca?q={termo}",
    "{base}/?s={termo}&post_type=product",
    "{base}/?s={termo}",
    "{base}/search?q={termo}",
    "{base}/catalogsearch/result/?q={termo}",
    "{base}/busca?busca={termo}",
    "{base}/pesquisa?q={termo}",
    "{base}/loja/busca?q={termo}",
)

URL_POR_PLATAFORMA = {
    Plataforma.TRAY: "{base}/busca?q={termo}",
    Plataforma.MAGENTO: "{base}/catalogsearch/result/?q={termo}",
    Plataforma.WOOCOMMERCE: "{base}/?s={termo}&post_type=product",
    Plataforma.SHOPIFY: "{base}/search?q={termo}",
    Plataforma.NUVEMSHOP: "{base}/search?q={termo}",
    Plataforma.VTEX: "{base}/{termo}?map=ft",
}

# Texto que denuncia bloqueio. Página de desafio responde 200 e não
# parece erro nenhum — sem isto o site entraria no relatório como "não
# vende nada", que é a leitura mais cara possível.
MARCAS_DE_BLOQUEIO = (
    "acesso negado", "access denied", "forbidden", "captcha",
    "verificando seu navegador", "checking your browser",
    "attention required", "cf-browser-verification", "unusual traffic",
    "robot check", "bloqueado por seguran",
)

STATUS_BLOQUEIO = (401, 403, 407, 429)

# Como uma página de resultado se anuncia -- inclusive quando o resultado
# é zero. "0 Resultados da pesquisa encontrados" é uma busca que
# funcionou, e a loja que responde isso merece ser varrida nos outros
# 131 itens em vez de virar "não sei buscar aqui".
MARCAS_DE_BUSCA = ("resultado", "pesquis", "busca", "search results", "você buscou")

# E como ela se anuncia quando a rota não existe. Seis lojas Woo reais
# deram seis redações da mesma coisa -- "Página não encontrada", "Page
# Not Found", "404 Not Found", "A página não pode ser encontrada",
# "Parece que nada foi encontrado neste local" -- e todas respondem 200.
# Por isso a comparação é por pedaço de texto, e vem ANTES da de busca:
# quase todas contêm também a palavra "encontrado".
MARCAS_DE_404 = (
    "não encontrada", "nao encontrada", "não pode ser encontrada",
    "nao pode ser encontrada", "nada foi encontrado", "não existe",
    "404", "not found",
)

# Título que não é produto: banner, menu e botão viram <a> com texto.
TITULOS_INUTEIS = re.compile(
    r"^(ver (mais|todos|detalhes)|comprar|adicionar|saiba mais|leia mais|"
    r"promo[cç][aã]o|ofertas?|home|in[ií]cio|login|entrar|carrinho|"
    r"categorias?|todos os produtos|continuar|d[uú]vidas?\??|clique aqui|"
    r"fale conosco|consulte|consultar|or[cç]amento|ver produto|"
    r"d[uú]vidas?\?? clique aqui)$",
    re.IGNORECASE,
)

PRECO = re.compile(r"R\$\s*([\d.\s]+,\d{2})")

# Os primeiros caracteres visíveis, que dizem se a página é resultado de
# busca, 404 ou home. Script separado do de extração de propósito: é
# outra pergunta, feita antes, e barata.
TEXTO_DO_TOPO = """/* texto-do-topo */ () => (
  document.body ? document.body.innerText : ''
).slice(0, 400).replace(/\\s+/g, ' ')"""

# JavaScript de extração. Roda na página, com o DOM já montado.
#
# Duas fontes, nesta ordem: JSON-LD (quando a loja publica, é o dado
# limpo, sem adivinhação de seletor) e, se não houver, os links que
# parecem de produto. Devolve dicionário cru -- normalizar é trabalho do
# Python, onde dá para testar.
EXTRAIR = """() => {
  const limpo = (t) => (t || '').replace(/\\s+/g, ' ').trim();
  const saida = [];
  const vistos = new Set();

  const juntar = (titulo, url, preco, sku) => {
    titulo = limpo(titulo);
    if (!titulo || !url || vistos.has(url)) return;
    vistos.add(url);
    saida.push({titulo, url, preco: preco || '', sku: sku || ''});
  };

  // 1. JSON-LD
  for (const script of document.querySelectorAll('script[type="application/ld+json"]')) {
    let dados;
    try { dados = JSON.parse(script.textContent); } catch (e) { continue; }
    const fila = Array.isArray(dados) ? dados.slice() : [dados];
    while (fila.length) {
      const no = fila.shift();
      if (!no || typeof no !== 'object') continue;
      if (Array.isArray(no.itemListElement)) {
        for (const el of no.itemListElement) fila.push(el.item || el);
        continue;
      }
      const tipo = [].concat(no['@type'] || []);
      if (!tipo.includes('Product')) continue;
      const oferta = [].concat(no.offers || [])[0] || {};
      juntar(no.name, no.url || (oferta.url || ''), oferta.price, no.sku || no.mpn);
    }
  }
  if (saida.length) return saida;

  // 2. Links que parecem de produto
  // "categoria-produto/pet-shop" contém "produto/" e passava como
  // produto: numa loja real isso trouxe "Pet Shop" e "Raladores e
  // mixer" para dentro do catálogo. Categoria sai antes de qualquer
  // outra regra.
  const ehCategoria = (href) =>
    /\\/(categoria|categorias|category|collections|departamento|secao|linha|marcas?)[\\/\\-]/i
      .test(href);
  const ehProduto = (href) =>
    !ehCategoria(href) &&
    /\\/(produto|producto|product|item|prod)s?[\\/\\-?]|\\/p\\/|\\-p\\d+|\\/p$/i.test(href);
  const emCard = (a) =>
    a.closest('[class*="produto" i],[class*="product" i],[class*="item" i],' +
              '[class*="card" i],[class*="shelf" i],[class*="vitrine" i],li,article');
  // Menu, rodapé e breadcrumb têm <a> dentro de <li> igualzinho ao de um
  // card. Numa loja real isso trouxe "SOBRE NÓS" e "Talheres de Mesa"
  // como se fossem produtos -- ruído que o matching pontua a sério.
  const ehNavegacao = (a) =>
    a.closest('nav,header,footer,[role="navigation"],[class*="menu" i],' +
              '[class*="nav" i],[class*="breadcrumb" i],[class*="rodape" i]');

  for (const a of document.querySelectorAll('a[href]')) {
    const href = a.href || '';
    if (!href.startsWith('http')) continue;
    if (ehNavegacao(a)) continue;
    const card = emCard(a);
    if (!ehProduto(href) && !card) continue;

    const img = a.querySelector('img') || (card && card.querySelector('img'));
    const titulo = limpo(a.getAttribute('title')) || limpo(a.innerText) ||
                   (img && limpo(img.getAttribute('alt'))) || '';

    let preco = '';
    let no = a;
    for (let i = 0; i < 4 && no && !preco; i++, no = no.parentElement) {
      const achado = (no.innerText || '').match(/R\\$\\s*[\\d.\\s]+,\\d{2}/);
      if (achado) preco = achado[0];
    }
    if (!ehProduto(href) && !preco) continue;
    juntar(titulo, href, preco, a.getAttribute('data-sku'));
  }
  return saida;
}"""


class BuscaNaoEncontrada(FalhaDeRede):
    """Não achei como buscar nesta loja: nem campo, nem lupa, nem URL.

    É `FalhaDeRede` e não um retorno vazio porque "não sei buscar aqui"
    e "esta loja não vende o item" pedem coisas opostas de quem lê o
    resultado: a primeira é um seletor a escrever, a segunda é um item a
    procurar em outro lugar.
    """


class PlaywrightExecutor(Executor):
    """Um navegador por processo, uma página por site, uma busca por termo."""

    plataforma = "desconhecida"

    # Preencha numa subclasse quando a heurística não pegar a loja.
    # Descubra os seletores com o HTML renderizado na mão — nunca copie
    # de outra loja, nem quando as duas rodam na mesma plataforma.
    SEL_BUSCA = ""          # o campo de busca desta loja
    URL_BUSCA = ""          # "{base}/busca?q={termo}" — pula o campo
    SEL_RESULTADO = ""      # o que esperar aparecer depois da busca
    SEL_CAMPO_CEP = ""
    SEL_RESULTADO_FRETE = ""

    def __init__(self, fornecedor, cliente) -> None:
        super().__init__(fornecedor, cliente)
        self._contexto = None
        self._pagina = None
        # O que veio da planilha ganha da subclasse, que ganha da
        # heurística. Ordem deliberada: quem preencheu a planilha abriu
        # o site e viu a página; a heurística só chuta bem.
        self.url_busca = fornecedor.url_busca or self.URL_BUSCA
        self.sel_busca = fornecedor.seletor_busca or self.SEL_BUSCA
        # Como esta loja aceita ser buscada: ("campo", seletor) ou
        # ("url", molde). Descoberto uma vez, reusado em todos os itens.
        self._caminho: tuple[str, str] | None = None
        # (termo, urls) da última busca, para flagrar a loja que devolve
        # sempre a mesma vitrine mesmo passando na prova da descoberta.
        self._ultimo: tuple[str, frozenset[str]] | None = None
        self._avisou_vitrine = False

    # --- ciclo de vida ------------------------------------------------------

    def abrir(self) -> None:
        from src.export.captura import obter_navegador

        navegador = obter_navegador()
        self._contexto = navegador.new_context(
            viewport={"width": LARGURA, "height": ALTURA},
            locale="pt-BR",
        )
        self._pagina = self._contexto.new_page()
        log.info("%s: navegador aberto", self.fornecedor.dominio)

    def fechar(self) -> None:
        for recurso in (self._pagina, self._contexto):
            try:
                if recurso is not None:
                    recurso.close()
            except Exception:  # noqa: PERF203 - fechar não pode derrubar a varredura
                pass
        self._pagina = self._contexto = None

    # --- Etapa 2: varredura -------------------------------------------------

    def buscar(self, termo: str) -> list[ProdutoBruto]:
        """Digita o termo na loja e devolve o que a página de resultado traz.

        `termo` vem de `itens.csv` (coluna `termos_busca`) ou de
        `matching.gerar_termos()` — este executor não sabe nada de item,
        só de caixa de texto.
        """
        if self._pagina is None:
            self.abrir()

        self._respeitar_intervalo()

        if self._caminho is None and self.url_busca:
            log.info("%s: usando a URL de busca conferida à mão",
                     self.fornecedor.dominio)
            self._caminho = ("url", self.url_busca)
        elif self._caminho is None and self.sel_busca:
            log.info("%s: usando o seletor de busca conferido à mão (%s)",
                     self.fornecedor.dominio, self.sel_busca)
            self._caminho = ("campo", self.sel_busca)

        if self._caminho is None:
            self._caminho, brutos = self._descobrir_caminho(termo)
        else:
            self._percorrer(self._caminho, termo)
            brutos = self._extrair()

        produtos = produtos_da_pagina(brutos, self._pagina.url)
        self._conferir_repeticao(termo, produtos)
        log.info("%s: %r -> %d produtos (por %s)", self.fornecedor.dominio,
                 termo, len(produtos), self._caminho[0])
        return produtos

    def _conferir_repeticao(self, termo: str, produtos: list[ProdutoBruto]) -> None:
        """Dois termos diferentes, resultado idêntico: a loja não buscou.

        A prova da descoberta não pega todos os casos. Uma loja Magento
        real respondeu vazio ao termo de controle (passando na prova) e
        as mesmas 20 botinas para "panela" e "tabua de corte" — é o
        catálogo de consolação que alguns temas mostram quando a busca
        não acha nada.

        Aqui é aviso, não erro: loja pequena pode ter três produtos e
        devolver os três sempre, e quem separa botina de tábua é o
        matching. Mas isso precisa aparecer no log de quem lê o
        resultado da varredura.
        """
        urls = frozenset(p.url for p in produtos)
        anterior = self._ultimo
        self._ultimo = (termo, urls)

        if not urls or anterior is None or self._avisou_vitrine:
            return
        if anterior[0] != termo and anterior[1] == urls:
            self._avisou_vitrine = True
            log.warning(
                "%s: %r e %r devolveram os mesmos %d produtos -- a busca pode "
                "estar mostrando vitrine em vez de resultado",
                self.fornecedor.dominio, anterior[0], termo, len(urls),
            )

    # --- como esta loja aceita ser buscada ----------------------------------

    def _descobrir_caminho(self, termo: str) -> tuple[tuple[str, str], list[dict]]:
        """Campo, lupa ou URL — nesta ordem. Fixa o primeiro que PROVAR servir.

        Provar é trazer produto. Achar o campo não basta: numa loja Woo
        real o campo existia, buscava no blog e devolvia "Olá, mundo!";
        noutra, `/busca?q=` respondia a home inteira. Os dois casos dão
        caminho fixado, 132 itens varridos contra a página errada e um
        relatório que não denuncia nada.

        Devolve o caminho e o que ele trouxe, para não repetir a busca do
        primeiro item só porque a descoberta aconteceu nele.
        """
        self._ir_para(self.fornecedor.url_base)
        self._aceitar_cookies()

        seletor = self._achar_campo()
        if seletor is None and self._abrir_lupa():
            seletor = self._achar_campo()

        if seletor is not None:
            self._digitar(seletor, termo)
            brutos = self._extrair()
            if brutos:
                confirmados = self._confirmar(("campo", seletor), termo, brutos)
                if confirmados is not None:
                    return ("campo", seletor), confirmados
                # O campo responde, mas responde a mesma coisa sempre.
                # Voltar a ele no fim seria varrer 132 itens contra a
                # vitrine da loja.
                seletor = None
            log.info("%s: campo %r não trouxe produto para %r; conferindo URL montada",
                     self.fornecedor.dominio, seletor, termo)
        else:
            log.info("%s: sem campo de busca visível; tentando URL montada",
                     self.fornecedor.dominio)

        # Uma URL que responde "0 resultados" é uma busca que funciona: só
        # não tem ESTE item. Guarda-se a primeira dessas para o caso de
        # nenhuma outra trazer produto -- senão a loja seria descartada
        # por causa do primeiro termo da lista.
        sem_produto: str | None = None
        for molde in self._moldes_de_url():
            self._ir_para(self._montar(molde, termo))
            if not self._parece_busca(termo):
                continue
            brutos = self._extrair()
            if brutos:
                confirmados = self._confirmar(("url", molde), termo, brutos)
                if confirmados is not None:
                    return ("url", molde), confirmados
                continue
            sem_produto = sem_produto or molde

        if sem_produto:
            log.info("%s: %s responde busca, mas não tem %r",
                     self.fornecedor.dominio, sem_produto, termo)
            return ("url", sem_produto), []

        # O campo existe e funcionou; esta loja é que não tem o item.
        if seletor is not None:
            return ("campo", seletor), []

        raise BuscaNaoEncontrada(
            f"{self.fornecedor.dominio}: não achei campo de busca nem URL que "
            f"responda. Defina SEL_BUSCA ou URL_BUSCA numa subclasse.",
            self.fornecedor.url_base,
        )

    def _confirmar(
        self, caminho: tuple[str, str], termo: str, brutos: list[dict],
    ) -> list[dict] | None:
        """Este caminho busca de verdade, ou devolve sempre a mesma vitrine?

        Pergunta feita uma vez por site, com um termo que ninguém vende.
        Loja que responde a ele exatamente o mesmo que respondeu ao termo
        de verdade não está filtrando nada — e varrer 132 itens contra
        uma vitrine fixa enche o relatório de achado que não existe. Uma
        loja Magento real devolveu as mesmas 20 botinas para "panela" e
        para "tabua de corte".

        Devolve o resultado do termo de verdade, buscado de novo para a
        página não ficar parada no termo de controle, ou None se o
        caminho não serve. Custa duas requisições por site, na
        descoberta; errar aqui custa 132 buscas inúteis e a revisão
        humana atrás delas.
        """
        try:
            self._percorrer(caminho, TERMO_IMPOSSIVEL)
            controle = self._extrair()
        except FalhaDeRede:
            return brutos   # não deu para conferir; segue com o caminho

        if controle and {b.get("url") for b in controle} == {b.get("url") for b in brutos}:
            log.warning("%s: %r devolve o mesmo resultado para qualquer termo; "
                        "não é busca", self.fornecedor.dominio, caminho[1])
            return None

        try:
            self._percorrer(caminho, termo)
        except FalhaDeRede:
            return brutos
        return self._extrair()

    def _parece_busca(self, termo: str) -> bool:
        """A loja levou o termo a sério, devolveu a home ou devolveu 404?

        Três lojas Woo reais mostraram os três casos na mesma rodada:
        `/?s=termo` respondeu "0 Resultados da pesquisa encontrados",
        `/busca?q=termo` respondeu "404: página não encontrada" e uma
        terceira devolveu a home inteira com status 200. Só o primeiro é
        uma busca — e é busca mesmo tendo achado zero produtos.

        Sem isto, o menu do tema entrava como catálogo: "SOBRE NÓS" e
        "Talheres de Mesa" viraram produto numa loja de verdade.
        """
        url = (self._pagina.url or "").lower()
        if url.rstrip("/") == self._base().lower():
            return False   # redirecionou para a home
        if quote_plus(termo).lower() not in url and termo.split()[0].lower() not in url:
            return False   # o termo não sobreviveu à navegação

        # O título é o sinal mais limpo: "Você pesquisou por panela",
        # "panela - GP Inox", "Resultados da pesquisa por «panela»" de um
        # lado; "Página não encontrada", "Page Not Found", "404 Not
        # Found" do outro. O corpo tem o menu inteiro no meio.
        titulo = self._titulo().lower()
        texto = self._texto_do_topo()
        if any(marca in titulo for marca in MARCAS_DE_404):
            return False
        if any(marca in texto for marca in MARCAS_DE_404):
            return False

        primeira = termo.split()[0].lower()
        if primeira in titulo:
            return True
        return any(marca in titulo or marca in texto for marca in MARCAS_DE_BUSCA)

    def _titulo(self) -> str:
        try:
            return self._pagina.title() or ""
        except Exception:
            return ""

    def _texto_do_topo(self) -> str:
        """Os primeiros 400 caracteres visíveis, em minúsculas.

        Só o topo: é onde ficam o título da página e o aviso de
        resultado. O corpo inteiro traria "404" de dentro de um SKU.
        """
        try:
            texto = self._pagina.evaluate(TEXTO_DO_TOPO)
        except Exception:
            return ""
        return (texto or "").lower()

    def _percorrer(self, caminho: tuple[str, str], termo: str) -> None:
        tipo, valor = caminho
        if tipo == "url":
            self._ir_para(self._montar(valor, termo))
            return

        # Caminho por campo, mas o navegador ainda não abriu página
        # nenhuma: não há onde digitar antes de chegar na loja.
        if not self._pagina.url or self._pagina.url == "about:blank":
            self._ir_para(self.fornecedor.url_base)
            self._aceitar_cookies()

        # O campo vive no cabeçalho, que sobrevive à navegação: buscar de
        # novo a partir da página de resultado é o caminho normal. Se ele
        # sumiu (loja que troca o layout na busca), volta para a home.
        try:
            self._digitar(valor, termo)
        except FalhaDeRede:
            self._ir_para(self.fornecedor.url_base)
            self._digitar(valor, termo)

    def _montar(self, molde: str, termo: str) -> str:
        """Molde -> URL. Troca literal, não `format`.

        `str.format` explode em KeyError com qualquer `{` que a pessoa
        tenha digitado na planilha por engano, e o molde aqui vem de
        gente. Trocar os dois marcadores que existem é tudo o que
        precisa acontecer.
        """
        return (molde
                .replace("{base}", self._base())
                .replace("{termo}", quote_plus(termo)))

    def _moldes_de_url(self) -> list[str]:
        preferido = URL_POR_PLATAFORMA.get(self.fornecedor.plataforma)
        moldes = list(URLS_BUSCA)
        if preferido:
            moldes = [preferido] + [m for m in moldes if m != preferido]
        return moldes

    # --- navegador ----------------------------------------------------------

    def _ir_para(self, url: str) -> None:
        try:
            resposta = self._pagina.goto(
                url, wait_until="domcontentloaded", timeout=TEMPO_NAVEGACAO_MS,
            )
        except Exception as e:
            raise FalhaDeRede(f"{type(e).__name__}: {e}", url) from e

        status = getattr(resposta, "status", 200) if resposta is not None else 200
        if status in STATUS_BLOQUEIO:
            raise SiteBloqueado(f"status {status}", url)
        if status >= 500:
            raise FalhaDeRede(f"status {status}", url)

        self._conferir_bloqueio(url)

    def _conferir_bloqueio(self, url: str) -> None:
        """Desafio de bot responde 200 e não parece erro. O texto entrega."""
        try:
            titulo = (self._pagina.title() or "").lower()
        except Exception:
            return
        if any(marca in titulo for marca in MARCAS_DE_BLOQUEIO):
            raise SiteBloqueado(f"pagina de desafio: {titulo!r}", url)

    def _achar_campo(self) -> str | None:
        seletores = (self.sel_busca, *SELETORES_BUSCA) if self.sel_busca else SELETORES_BUSCA
        for seletor in seletores:
            try:
                campo = self._pagina.locator(seletor).first
                if campo.count() and campo.is_visible():
                    return seletor
            except Exception:  # noqa: PERF203 - seletor que não serve, tenta o próximo
                continue
        return None

    def _abrir_lupa(self) -> bool:
        for seletor in SELETORES_LUPA:
            try:
                botao = self._pagina.locator(seletor).first
                if not botao.count() or not botao.is_visible():
                    continue
                botao.click(timeout=2000)
                self._pagina.wait_for_timeout(600)
                return True
            except Exception:  # noqa: PERF203
                continue
        return False

    def _digitar(self, seletor: str, termo: str) -> None:
        """Preenche o campo, dá Enter e espera o resultado montar."""
        try:
            campo = self._pagina.locator(seletor).first
            campo.click(timeout=TEMPO_SELETOR_MS)
            campo.fill("", timeout=TEMPO_SELETOR_MS)
            campo.fill(termo, timeout=TEMPO_SELETOR_MS)
            campo.press("Enter")
        except Exception as e:
            # Seletor que veio da planilha é conferência humana que não
            # bateu: a saída é corrigir a célula, não tentar de novo. A
            # mensagem precisa dizer isso, senão vira caça a problema de
            # rede que não existe.
            de_onde = (" (conferido à mão na planilha)"
                       if seletor == self.fornecedor.seletor_busca else "")
            raise FalhaDeRede(
                f"campo {seletor!r}{de_onde} não aceitou o termo "
                f"({type(e).__name__})",
                self.fornecedor.url_base,
            ) from e

        self._esperar_resultado()
        self._conferir_bloqueio(self._pagina.url)

    def _esperar_resultado(self) -> None:
        """Busca por Enter ou monta a página nova, ou troca o DOM no lugar.

        Esperar navegação resolve o primeiro caso e falha no segundo, que
        é o de toda loja com busca em AJAX — por isso o timeout aqui não
        é erro, só o fim da espera.
        """
        alvo = self.SEL_RESULTADO
        try:
            if alvo:
                self._pagina.wait_for_selector(alvo, timeout=ESPERA_RESULTADO_MS)
            else:
                self._pagina.wait_for_load_state(
                    "networkidle", timeout=ESPERA_RESULTADO_MS
                )
        except Exception:
            self._pagina.wait_for_timeout(1200)

    def _extrair(self) -> list[dict]:
        try:
            brutos = self._pagina.evaluate(EXTRAIR)
        except Exception as e:
            raise FalhaDeRede(
                f"extração falhou ({type(e).__name__}: {e})", self._pagina.url,
            ) from e
        return brutos if isinstance(brutos, list) else []

    def _base(self) -> str:
        return self.fornecedor.url_base.rstrip("/")

    def _aceitar_cookies(self) -> None:
        """Banner cobre o campo de busca com a mesma facilidade que o preço."""
        from src.export.captura import _aceitar_cookies

        _aceitar_cookies(self._pagina)

    @staticmethod
    def _respeitar_intervalo() -> None:
        time.sleep(random.uniform(INTERVALO_MIN, INTERVALO_MAX))


# ---------------------------------------------------------------------------
# Normalização — função pura, é o que os testes exercitam
# ---------------------------------------------------------------------------

def produtos_da_pagina(brutos: list[dict], url_pagina: str) -> list[ProdutoBruto]:
    """Dicionários crus do JavaScript -> ProdutoBruto, limpos e sem repetição.

    Filtra o que o extrator inevitavelmente pega junto: link de menu,
    botão "Comprar" e título de uma palavra. Isso é ruído para o
    matching, que pontua texto contra a descrição do item.
    """
    produtos: list[ProdutoBruto] = []
    vistos: set[str] = set()

    for bruto in brutos:
        if not isinstance(bruto, dict):
            continue
        titulo = " ".join(str(bruto.get("titulo") or "").split())
        url = str(bruto.get("url") or "").strip()
        if not titulo or not url or TITULOS_INUTEIS.match(titulo):
            continue
        # Uma palavra curta é categoria ou marca, não título de produto.
        if len(titulo) < 6 or len(titulo.split()) < 2:
            continue

        url = urljoin(url_pagina, url)
        if url in vistos:
            continue
        vistos.add(url)

        produtos.append(ProdutoBruto(
            titulo=titulo[:300],
            url=url,
            preco=preco_em_real(bruto.get("preco")),
            disponivel=True,   # a listagem não é prova de estoque; a etapa 3 é
            sku=str(bruto.get("sku") or "") or None,
        ))
        if len(produtos) >= MAX_PRODUTOS:
            break

    return produtos


def preco_em_real(texto) -> float | None:
    """"R$ 1.234,56" -> 1234.56. Também aceita o número cru do JSON-LD.

    Preço daqui é indicativo: entra no achado para dar noção de faixa, e
    é a etapa 3, na página do produto, que coleta o que vale.
    """
    if texto in (None, ""):
        return None
    if isinstance(texto, (int, float)):
        return float(texto)

    achado = PRECO.search(str(texto))
    if achado:
        numero = achado.group(1).replace(".", "").replace(" ", "").replace(",", ".")
    else:
        # JSON-LD manda "129.90" (ponto decimal) ou "129,90".
        cru = str(texto).strip()
        numero = cru.replace(",", ".") if cru.count(",") == 1 and "." not in cru else cru
    try:
        valor = float(numero)
    except (TypeError, ValueError):
        return None
    return valor if valor > 0 else None
