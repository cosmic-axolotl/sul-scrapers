"""O executor de fallback: achar a barra de pesquisa e digitar o item.

É o caminho de 66 dos 89 sites aprovados — os 58 sem plataforma
reconhecida, mais Tray e Magento, que não têm adapter de API.

Nenhum teste aqui sobe navegador. `PaginaFalsa` implementa a parte da
API do Playwright que o executor usa, e é hostil nos pontos em que uma
loja real é: campo escondido atrás da lupa, busca que não navega, banner
de cookies, página de desafio que responde 200.
"""

from __future__ import annotations

import pytest

from src.adapters.generico_playwright import (
    TERMO_IMPOSSIVEL,
    URLS_BUSCA,
    BuscaNaoEncontrada,
    PlaywrightExecutor,
    preco_em_real,
    produtos_da_pagina,
)
from src.core.http import FalhaDeRede, SiteBloqueado
from src.models import Fornecedor, Plataforma, Status


# ---------------------------------------------------------------------------
# Dublês
# ---------------------------------------------------------------------------

class LocatorFalso:
    def __init__(self, pagina, seletor: str):
        self.pagina = pagina
        self.seletor = seletor

    @property
    def first(self):
        return self

    def count(self) -> int:
        return 1 if self.seletor in self.pagina.elementos else 0

    def is_visible(self) -> bool:
        return self.pagina.elementos.get(self.seletor) == "visivel"

    def click(self, **_):
        if self.seletor not in self.pagina.elementos:
            raise RuntimeError(f"{self.seletor} não existe")
        self.pagina.cliques.append(self.seletor)
        for seletor in self.pagina.revelado_por_clique.get(self.seletor, []):
            self.pagina.elementos[seletor] = "visivel"

    def fill(self, texto: str, **_):
        if not self.is_visible():
            raise RuntimeError(f"{self.seletor} não está visível")
        if texto:
            self.pagina.digitado.append((self.seletor, texto))

    def press(self, tecla: str):
        self.pagina.teclas.append(tecla)


class PaginaFalsa:
    """O mínimo da API do Playwright que o executor usa."""

    def __init__(self, elementos=None, produtos=None, titulo="Loja", status=200,
                 revelado_por_clique=None, produtos_por_url=None,
                 texto="Resultados da pesquisa", texto_por_url=None, filtra=True):
        self.elementos = dict(elementos or {})
        self.produtos = produtos if produtos is not None else []
        self.produtos_por_url = produtos_por_url or {}
        self._titulo = titulo
        self.status = status
        self.revelado_por_clique = revelado_por_clique or {}
        # O texto do topo da página: é por ele que o executor separa
        # "busca sem resultado" de "404" e de "voltei para a home".
        self.texto = texto
        self.texto_por_url = texto_por_url or {}
        # Loja que filtra devolve nada para um termo que ninguém vende.
        # `filtra=False` imita a loja Magento real que respondia as
        # mesmas 20 botinas para "panela" e para "tabua de corte".
        self.filtra = filtra

        self.url = ""
        self.visitadas: list[str] = []
        self.digitado: list[tuple[str, str]] = []
        self.teclas: list[str] = []
        self.cliques: list[str] = []

    def goto(self, url, **_):
        self.url = url
        self.visitadas.append(url)
        return type("Resposta", (), {"status": self.status})()

    def title(self):
        return self._titulo

    def locator(self, seletor):
        return LocatorFalso(self, seletor)

    def get_by_role(self, *_, **__):
        return LocatorFalso(self, "__sem_cookies__")

    def evaluate(self, script):
        if "texto-do-topo" in script:      # a leitura do texto do topo
            for pedaco, texto in self.texto_por_url.items():
                if pedaco in self.url:
                    return texto
            return self.texto
        if self.filtra and TERMO_IMPOSSIVEL in self._buscado():
            return []
        for pedaco, produtos in self.produtos_por_url.items():
            if pedaco in self.url:
                return produtos
        return self.produtos

    def _buscado(self) -> str:
        """O que a última busca procurou — pela URL ou pelo que foi digitado."""
        return self.url + (self.digitado[-1][1] if self.digitado else "")

    def wait_for_selector(self, *_, **__):
        pass

    def wait_for_load_state(self, *_, **__):
        pass

    def wait_for_timeout(self, *_):
        pass

    def close(self):
        pass


def montar(pagina, plataforma=Plataforma.DESCONHECIDA, **campos) -> PlaywrightExecutor:
    fornecedor = Fornecedor(
        nome="Loja Exemplo",
        dominio="loja-exemplo.com.br",
        url_base="https://loja-exemplo.com.br",
        uf="PR",
        plataforma=plataforma,
        status=Status.APROVADO,
    )
    classe = type("ExecutorDeTeste", (PlaywrightExecutor,), campos) if campos \
        else PlaywrightExecutor
    executor = classe(fornecedor, cliente=None)
    executor._pagina = pagina
    executor._respeitar_intervalo = staticmethod(lambda: None)
    return executor


PRODUTO = {"titulo": "Tabua de Corte Polietileno 50 cm", "url": "/produto/tabua-50",
           "preco": "R$ 189,90", "sku": "TAB50"}


# ---------------------------------------------------------------------------
# Achar a barra de pesquisa
# ---------------------------------------------------------------------------

def test_acha_o_campo_de_busca_e_digita_o_termo():
    pagina = PaginaFalsa({"input[type='search']": "visivel"}, produtos=[PRODUTO])
    executor = montar(pagina)

    produtos = executor.buscar("tabua de corte 50 cm")

    assert pagina.digitado[0] == ("input[type='search']", "tabua de corte 50 cm")
    assert pagina.teclas[0] == "Enter"
    assert [p.titulo for p in produtos] == ["Tabua de Corte Polietileno 50 cm"]


def test_campo_invisivel_nao_conta():
    """Muita loja tem um <input> de busca oculto no HTML do mobile."""
    pagina = PaginaFalsa({"input[type='search']": "oculto",
                          "input[name='q']": "visivel"}, produtos=[PRODUTO])
    executor = montar(pagina)

    executor.buscar("tabua")

    assert pagina.digitado[0] == ("input[name='q']", "tabua")


def test_clica_na_lupa_quando_o_campo_so_aparece_depois():
    pagina = PaginaFalsa(
        {"[aria-label*='busca' i]": "visivel"},
        produtos=[PRODUTO],
        revelado_por_clique={"[aria-label*='busca' i]": ["input[type='search']"]},
    )
    executor = montar(pagina)

    executor.buscar("tabua")

    assert pagina.cliques[0] == "[aria-label*='busca' i]"   # a lupa, antes do campo
    assert pagina.digitado[0] == ("input[type='search']", "tabua")


def test_sem_campo_cai_para_a_url_de_busca():
    pagina = PaginaFalsa({}, produtos_por_url={"/busca?q=": [PRODUTO]})
    executor = montar(pagina)

    produtos = executor.buscar("tabua de corte")

    assert "/busca?q=tabua+de+corte" in pagina.url
    assert len(produtos) == 1


def test_a_plataforma_detectada_escolhe_a_primeira_url():
    """Magento responde em /catalogsearch/result/; tentar /busca antes é rodeio."""
    pagina = PaginaFalsa({}, produtos_por_url={"catalogsearch": [PRODUTO]})
    executor = montar(pagina, plataforma=Plataforma.MAGENTO)

    executor.buscar("tabua")

    assert "catalogsearch" in pagina.visitadas[1]


def test_url_montada_a_mao_pula_a_descoberta():
    pagina = PaginaFalsa({"input[type='search']": "visivel"}, produtos=[PRODUTO])
    executor = montar(pagina, URL_BUSCA="{base}/achar?termo={termo}")

    executor.buscar("tabua")

    assert pagina.url == "https://loja-exemplo.com.br/achar?termo=tabua"
    assert pagina.digitado == []   # nem tentou o campo


def test_seletor_proprio_tem_prioridade_sobre_a_heuristica():
    pagina = PaginaFalsa({"#minha-busca": "visivel", "input[type='search']": "visivel"},
                         produtos=[PRODUTO])
    executor = montar(pagina, SEL_BUSCA="#minha-busca")

    executor.buscar("tabua")

    assert pagina.digitado[0] == ("#minha-busca", "tabua")


def test_campo_que_nao_traz_produto_nao_fixa_o_caminho():
    """Loja Woo real: o campo existia, buscava no blog e devolvia "Olá, mundo!"."""
    pagina = PaginaFalsa(
        {"input[type='search']": "visivel"},
        produtos=[],
        produtos_por_url={"?s=": [PRODUTO]},
    )
    executor = montar(pagina)

    produtos = executor.buscar("tabua")

    assert executor._caminho[0] == "url"
    assert len(produtos) == 1


def test_url_que_devolve_a_home_e_recusada():
    """WordPress sem a rota responde 200 com a home inteira, e o menu
    inteiro viraria catálogo."""
    pagina = PaginaFalsa({}, produtos=[PRODUTO])
    pagina.goto = lambda url, **_: (
        setattr(pagina, "url", "https://loja-exemplo.com.br"),   # redirecionou
        pagina.visitadas.append(url),
        type("Resposta", (), {"status": 200})(),
    )[-1]
    executor = montar(pagina)

    with pytest.raises(BuscaNaoEncontrada):
        executor.buscar("tabua")


def test_url_que_responde_404_e_recusada_mesmo_com_status_200():
    """Loja Woo real: /busca?q= devolve "404: página não encontrada" em 200."""
    pagina = PaginaFalsa(
        {},
        produtos=[PRODUTO],
        texto_por_url={"/busca?q=": "404: página não encontrada",
                       "?s=": "0 Resultados da pesquisa encontrados"},
        produtos_por_url={"?s=": [PRODUTO]},
    )
    executor = montar(pagina)

    executor.buscar("tabua")

    assert executor._caminho[1].startswith("{base}/?s=")


def test_vitrine_fixa_nao_conta_como_busca():
    """Loja Magento real: as mesmas 20 botinas para "panela" e "tabua"."""
    pagina = PaginaFalsa({"input[type='search']": "visivel"}, produtos=[PRODUTO],
                         filtra=False)
    executor = montar(pagina)

    with pytest.raises(BuscaNaoEncontrada):
        executor.buscar("tabua")


def test_a_prova_de_filtro_custa_uma_busca_por_site():
    pagina = PaginaFalsa({"input[type='search']": "visivel"}, produtos=[PRODUTO])
    executor = montar(pagina)

    executor.buscar("tabua")
    executor.buscar("panela")

    termos = [t for _, t in pagina.digitado]
    assert termos == ["tabua", TERMO_IMPOSSIVEL, "tabua", "panela"]
    assert pagina.visitadas == ["https://loja-exemplo.com.br"]   # home uma vez só


def test_avisa_quando_dois_termos_devolvem_o_mesmo(caplog):
    """A loja Magento real passou na prova e ainda assim mostrava vitrine."""
    import logging

    pagina = PaginaFalsa({"input[type='search']": "visivel"}, produtos=[PRODUTO])
    executor = montar(pagina)

    with caplog.at_level(logging.WARNING):
        executor.buscar("tabua")
        executor.buscar("panela")

    assert "vitrine" in caplog.text


def test_nao_avisa_quando_o_resultado_muda(caplog):
    import logging

    pagina = PaginaFalsa(
        {}, produtos_por_url={"tabua": [PRODUTO],
                              "panela": [{"titulo": "Panela de Pressao 4,5 L",
                                          "url": "/produto/panela"}]},
    )
    executor = montar(pagina)

    with caplog.at_level(logging.WARNING):
        executor.buscar("tabua")
        executor.buscar("panela")

    assert "vitrine" not in caplog.text


def test_titulo_de_404_recusa_a_url_mesmo_com_corpo_plausivel():
    """"Página não encontrada | Cia Atacado" com o menu inteiro no corpo."""
    pagina = PaginaFalsa({}, produtos=[PRODUTO], titulo="Página não encontrada | Loja")
    executor = montar(pagina)

    with pytest.raises(BuscaNaoEncontrada):
        executor.buscar("tabua")


def test_titulo_com_o_termo_basta_para_ser_busca():
    """Tema que titula só "panela - GP Inox", sem a palavra "resultado"."""
    pagina = PaginaFalsa({}, produtos=[PRODUTO], titulo="tabua - Loja Exemplo",
                         texto="Inicio Sobre nos Produtos Contato")
    executor = montar(pagina)

    assert len(executor.buscar("tabua")) == 1


def test_busca_sem_resultado_vale_como_caminho():
    """"0 Resultados da pesquisa" é busca que funciona; só não tem o item."""
    pagina = PaginaFalsa({}, produtos=[], texto="0 Resultados da pesquisa encontrados")
    executor = montar(pagina)

    produtos = executor.buscar("tabua")

    assert produtos == []
    assert executor._caminho[0] == "url"     # a loja pode ser varrida nos outros itens


def test_campo_sem_resultado_continua_valendo_quando_nenhuma_url_serve():
    """Loja que de fato não vende o item: 0 achados é a resposta certa."""
    pagina = PaginaFalsa({"input[type='search']": "visivel"}, produtos=[],
                         texto="404 não encontrada")
    executor = montar(pagina)

    produtos = executor.buscar("tabua")

    assert produtos == []
    assert executor._caminho == ("campo", "input[type='search']")


def test_loja_sem_busca_nenhuma_levanta_erro_em_vez_de_lista_vazia():
    """"Não sei buscar aqui" e "a loja não vende" pedem ações opostas."""
    pagina = PaginaFalsa({}, produtos=[], texto="404 não encontrada")
    executor = montar(pagina)

    with pytest.raises(BuscaNaoEncontrada) as erro:
        executor.buscar("tabua")

    assert "SEL_BUSCA" in str(erro.value)          # diz o que fazer
    assert len(pagina.visitadas) == 1 + len(URLS_BUSCA)   # tentou todas


def test_o_caminho_descoberto_e_reusado_no_proximo_item():
    """Redescobrir a cada item multiplicaria por 132 o custo da varredura."""
    pagina = PaginaFalsa({"input[name='q']": "visivel"}, produtos=[PRODUTO])
    executor = montar(pagina)

    executor.buscar("tabua")
    executor.buscar("panela")

    assert executor._caminho == ("campo", "input[name='q']")
    assert pagina.visitadas == ["https://loja-exemplo.com.br"]   # home uma vez só
    assert [t for _, t in pagina.digitado] == [
        "tabua", TERMO_IMPOSSIVEL, "tabua", "panela",   # a prova no meio
    ]


# ---------------------------------------------------------------------------
# Bloqueio: nunca confundir com "não achei nada"
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("status", [401, 403, 429])
def test_status_de_bloqueio_sobe_como_site_bloqueado(status):
    pagina = PaginaFalsa({"input[type='search']": "visivel"}, status=status)
    executor = montar(pagina)

    with pytest.raises(SiteBloqueado):
        executor.buscar("tabua")


def test_pagina_de_desafio_que_responde_200_tambem_e_bloqueio():
    pagina = PaginaFalsa({"input[type='search']": "visivel"},
                         titulo="Attention Required! | Cloudflare")
    executor = montar(pagina)

    with pytest.raises(SiteBloqueado):
        executor.buscar("tabua")


def test_erro_de_navegacao_vira_falha_de_rede():
    pagina = PaginaFalsa({"input[type='search']": "visivel"})
    pagina.goto = lambda *a, **k: (_ for _ in ()).throw(TimeoutError("timeout"))
    executor = montar(pagina)

    with pytest.raises(FalhaDeRede):
        executor.buscar("tabua")


# ---------------------------------------------------------------------------
# Normalização do que a página devolveu
# ---------------------------------------------------------------------------

def test_url_relativa_vira_absoluta():
    [produto] = produtos_da_pagina(
        [{"titulo": "Tabua de Corte 50 cm", "url": "/produto/tabua"}],
        "https://loja.com.br/busca?q=tabua",
    )
    assert produto.url == "https://loja.com.br/produto/tabua"


def test_descarta_link_que_nao_e_produto():
    """O extrator pega menu e botão junto; matching não pode recebê-los."""
    brutos = [
        {"titulo": "Comprar", "url": "/produto/x"},
        {"titulo": "Ver mais", "url": "/produto/y"},
        {"titulo": "Panelas", "url": "/categoria/panelas"},     # uma palavra
        {"titulo": "", "url": "/produto/z"},
        {"titulo": "Panela de Pressao 4,5 L", "url": "/produto/panela"},
    ]
    assert [p.titulo for p in produtos_da_pagina(brutos, "https://loja.com.br")] == [
        "Panela de Pressao 4,5 L"
    ]


def test_mesma_url_nao_entra_duas_vezes():
    brutos = [
        {"titulo": "Tabua de Corte 50 cm", "url": "https://loja.com.br/p/tabua"},
        {"titulo": "Tabua de Corte 50 cm - foto", "url": "/p/tabua"},
    ]
    assert len(produtos_da_pagina(brutos, "https://loja.com.br")) == 1


def test_estoque_da_listagem_nao_e_prova():
    """Disponibilidade quem confere é a etapa 3, na página do produto."""
    [produto] = produtos_da_pagina([{"titulo": "Panela de Pressao", "url": "/p/1"}],
                                   "https://loja.com.br")
    assert produto.disponivel is True


@pytest.mark.parametrize(("texto", "esperado"), [
    ("R$ 189,90", 189.90),
    ("R$ 1.234,56", 1234.56),
    ("De R$ 229,90 por R$ 189,90", 229.90),   # o primeiro da página
    ("189.90", 189.90),                        # JSON-LD
    ("189,90", 189.90),
    (189.9, 189.90),
    ("", None),
    (None, None),
    ("sob consulta", None),
    ("R$ 0,00", None),
])
def test_preco_em_real(texto, esperado):
    assert preco_em_real(texto) == esperado


def test_corta_em_trinta_produtos():
    brutos = [{"titulo": f"Panela de Pressao {n} L", "url": f"/p/{n}"}
              for n in range(50)]
    assert len(produtos_da_pagina(brutos, "https://loja.com.br")) == 30
