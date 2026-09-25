"""O validador acha sozinho a forma do endereço que conecta: com ou sem www.

Nove fornecedores aprovados estavam na planilha sem www e só respondem
com ele -- 0 de 3 tentativas como estavam, 3 de 3 com www. A varredura
batia num endereço morto e o site saía como "loja vazia".

O perigo simétrico é trocar o que estava certo. Por isso metade dos
testes aqui é sobre quando a troca NÃO pode acontecer.
"""

from __future__ import annotations

import httpx
import pytest

from src.core.http import FalhaDeRede, SiteBloqueado
from src.models import Fornecedor, Status
from src.runners.etapa1_validar import _trocar_www, resolver_www, validar


def morto(url):
    """O que o Cliente levanta quando o host não conecta."""
    try:
        raise httpx.ConnectError("conexão recusada")
    except httpx.ConnectError as causa:
        raise FalhaDeRede(f"falhou: {url}", url) from causa


def erro_http(url, status):
    """O que o Cliente levanta quando o host responde com 4xx."""
    pedido = httpx.Request("GET", url)
    resposta = httpx.Response(status, request=pedido)
    try:
        raise httpx.HTTPStatusError("erro", request=pedido, response=resposta)
    except httpx.HTTPStatusError as causa:
        raise FalhaDeRede(f"falhou: {url}", url) from causa


class ClientePorEndereco:
    """Cada endereço tem seu comportamento: 'ok', 'morto', 404, 'bloqueado'."""

    def __init__(self, respostas: dict[str, object]):
        self.respostas = respostas
        self.pedidos: list[str] = []

    def get(self, url, **_):
        self.pedidos.append(url)
        comportamento = self.respostas.get(url.rstrip("/"), "morto")
        if comportamento == "ok":
            return "<html></html>"
        if comportamento == "bloqueado":
            raise SiteBloqueado("403", url)
        if isinstance(comportamento, int):
            erro_http(url, comportamento)
        morto(url)


def loja(url="https://frigo.com.br"):
    return Fornecedor(nome="Frigo", dominio="frigo.com.br", url_base=url, uf="SC",
                      status=Status.PENDENTE)


# ---------------------------------------------------------------------------
# Quando troca
# ---------------------------------------------------------------------------

def test_acrescenta_www_quando_so_ele_conecta():
    """O caso de frigo, primoequipamentos, satoatacado e mais seis."""
    forn = loja("https://frigo.com.br")
    cliente = ClientePorEndereco({"https://www.frigo.com.br": "ok"})

    assert resolver_www(forn, cliente) is True
    assert forn.url_base == "https://www.frigo.com.br"


def test_tira_www_quando_so_sem_ele_conecta():
    forn = loja("https://www.frigo.com.br")
    cliente = ClientePorEndereco({"https://frigo.com.br": "ok"})

    assert resolver_www(forn, cliente) is True
    assert forn.url_base == "https://frigo.com.br"


def test_a_chave_do_fornecedor_nao_muda():
    """O domínio já é guardado sem www: achados e master continuam casando."""
    forn = loja("https://frigo.com.br")
    resolver_www(forn, ClientePorEndereco({"https://www.frigo.com.br": "ok"}))

    assert forn.dominio == "frigo.com.br"


def test_funciona_com_subdominio():
    """loja.bhzepi.com.br só responde como www.loja.bhzepi.com.br."""
    forn = loja("https://loja.bhzepi.com.br")
    resolver_www(forn, ClientePorEndereco({"https://www.loja.bhzepi.com.br": "ok"}))

    assert forn.url_base == "https://www.loja.bhzepi.com.br"


# ---------------------------------------------------------------------------
# Quando NÃO troca
# ---------------------------------------------------------------------------

def test_endereco_que_conecta_fica_como_esta():
    forn = loja("https://frigo.com.br")
    cliente = ClientePorEndereco({"https://frigo.com.br": "ok",
                                  "https://www.frigo.com.br": "ok"})

    assert resolver_www(forn, cliente) is False
    assert forn.url_base == "https://frigo.com.br"
    assert cliente.pedidos == ["https://frigo.com.br"]    # nem testou o outro


@pytest.mark.parametrize("resposta", [404, 410, "bloqueado"])
def test_erro_http_sem_www_e_pagina_com_www_troca(resposta):
    """Cinco dos nove reais: sem www o host responde com erro, com www
    entrega a loja. Erro HTTP não serve para raspar -- troca."""
    forn = loja("https://frigo.com.br")
    cliente = ClientePorEndereco({"https://frigo.com.br": resposta,
                                  "https://www.frigo.com.br": "ok"})

    assert resolver_www(forn, cliente) is True
    assert forn.url_base == "https://www.frigo.com.br"


@pytest.mark.parametrize("resposta", [404, "bloqueado"])
def test_erro_http_nos_dois_fica_o_da_planilha(resposta):
    """Sem prova de que o outro é melhor, não troca."""
    forn = loja("https://frigo.com.br")
    cliente = ClientePorEndereco({"https://frigo.com.br": resposta,
                                  "https://www.frigo.com.br": resposta})

    assert resolver_www(forn, cliente) is False
    assert forn.url_base == "https://frigo.com.br"


def test_se_nenhum_conecta_fica_o_da_planilha():
    """A troca não é palpite: sem prova de que o outro funciona, não troca."""
    forn = loja("https://frigo.com.br")

    assert resolver_www(forn, ClientePorEndereco({})) is False
    assert forn.url_base == "https://frigo.com.br"


def test_preserva_esquema_e_caminho():
    assert _trocar_www("http://loja.com.br") == "http://www.loja.com.br"
    assert _trocar_www("https://www.loja.com.br/") == "https://loja.com.br/"


# ---------------------------------------------------------------------------
# Dentro da validação
# ---------------------------------------------------------------------------

def test_o_master_recebe_o_endereco_que_conecta(tmp_path, monkeypatch):
    """O aprovado sai da validação com o endereço que a varredura vai visitar."""
    monkeypatch.setattr("src.validacao.consultar_cnpj.CACHE", tmp_path / "cnpj")

    class Cliente(ClientePorEndereco):
        def get_json(self, url, **_):
            return {"razao_social": "FRIGO LTDA", "cnae_fiscal": 4642702,
                    "descricao_situacao_cadastral": "ATIVA",
                    "cnaes_secundarios": []}

    forn = loja("https://frigo.com.br")
    forn.cnpj = "61340901000117"

    validar(forn, Cliente({"https://www.frigo.com.br": "ok"}))

    assert forn.status is Status.APROVADO
    assert forn.url_base == "https://www.frigo.com.br"


def test_reprovado_nao_gasta_requisicao():
    """Reprovação decidida por gente não se revisita -- nem o endereço."""
    forn = loja("https://frigo.com.br")
    forn.status = Status.REPROVADO
    cliente = ClientePorEndereco({})

    validar(forn, cliente)

    assert cliente.pedidos == []


def test_sem_cnpj_e_sem_garimpo_nao_toca_no_site():
    """--so-com-cnpj promete zero requisição para quem chegou sem CNPJ."""
    forn = loja("https://frigo.com.br")
    cliente = ClientePorEndereco({})

    validar(forn, cliente, buscar_cnpj_no_site=False)

    assert cliente.pedidos == []


# ---------------------------------------------------------------------------
# Plataforma: rede ruim não apaga o que já se sabia
# ---------------------------------------------------------------------------

def _cliente_cnpj_ok(respostas):
    class Cliente(ClientePorEndereco):
        def get_json(self, url, **_):
            return {"razao_social": "FRIGO LTDA", "cnae_fiscal": 4642702,
                    "descricao_situacao_cadastral": "ATIVA",
                    "cnaes_secundarios": []}
    return Cliente(respostas)


def test_home_que_nao_abre_nao_apaga_a_plataforma(tmp_path, monkeypatch):
    """A revalidação de 23/09 derrubou 28 plataformas para desconhecida
    porque metade das homes deu ReadError naquela tarde."""
    from src.models import Plataforma

    monkeypatch.setattr("src.validacao.consultar_cnpj.CACHE", tmp_path / "cnpj")
    forn = loja("https://frigo.com.br")
    forn.cnpj = "61340901000117"
    forn.plataforma = Plataforma.WOOCOMMERCE        # detectada numa rodada anterior

    validar(forn, _cliente_cnpj_ok({}))             # nenhuma home abre

    assert forn.plataforma is Plataforma.WOOCOMMERCE


def test_deteccao_que_funciona_continua_atualizando(tmp_path, monkeypatch):
    from src.models import Plataforma

    monkeypatch.setattr("src.validacao.consultar_cnpj.CACHE", tmp_path / "cnpj")
    forn = loja("https://frigo.com.br")
    forn.cnpj = "61340901000117"
    forn.plataforma = Plataforma.WOOCOMMERCE

    class ComHtml(ClientePorEndereco):
        def get(self, url, **kw):
            super().get(url, **kw)
            return '<script src="https://cdn.shopify.com/x.js"></script>'

    cliente = ComHtml({"https://frigo.com.br": "ok"})
    cliente.get_json = _cliente_cnpj_ok({}).get_json

    validar(forn, cliente)

    assert forn.plataforma is Plataforma.SHOPIFY     # a loja migrou: vale a nova
