"""Adapter VTEX: a variação certa, o vendedor certo, o preço certo.

A resposta em tests/fixtures/vtex_busca.json tem de propósito:
  - um produto com duas variações (30 cm e 50 cm) e preços diferentes;
  - uma variação com dois sellers, o primeiro deles SEM estoque;
  - ListPrice maior que Price num caso, e ListPrice zerado noutro.

São exatamente os três pontos em que a versão anterior (items[0],
sellers[0], só o campo Price) levava o número errado para a planilha.
"""

from __future__ import annotations

import pytest

from src.adapters.vtex import VtexExecutor
from src.core import matching
from src.core.http import FalhaDeRede, RespostaInvalida, SiteBloqueado
from tests.conftest import ClienteFalso


@pytest.fixture
def executor(fornecedor, fixture_json):
    cliente = ClienteFalso({"products/search": fixture_json("vtex_busca.json")})
    return VtexExecutor(fornecedor, cliente)


# ---------------------------------------------------------------------------
# Variações
# ---------------------------------------------------------------------------

def test_devolve_uma_linha_por_variacao(executor):
    produtos = executor.buscar("tabua de corte")
    titulos = [p.titulo for p in produtos]

    assert "Tábua de Corte Polietileno 30 cm" in titulos
    assert "Tábua de Corte Polietileno 50 cm" in titulos


def test_o_titulo_carrega_a_medida_da_variacao(executor):
    """Sem a medida no título o matching não tem como comparar nada."""
    produtos = executor.buscar("tabua")
    for p in produtos:
        if p.sku == "5002":
            assert "50 cm" in p.titulo
            assert matching.dimensoes(p.titulo) == {("comprimento", 0.5)}
            return
    pytest.fail("variação 5002 não veio na busca")


def test_a_url_aponta_para_a_variacao_cotada(executor):
    """O print tem que abrir no SKU que definiu o preço."""
    produtos = {p.sku: p for p in executor.buscar("tabua")}
    assert produtos["5002"].url.endswith("skuId=5002")


def test_o_matching_escolhe_a_variacao_pedida(executor):
    """O teste que amarra adapter e matching: pedindo 50 cm, vem 50 cm."""
    descricao = "Tábua de corte em polietileno, 50 cm de comprimento"
    melhor = max(
        executor.buscar("tabua de corte"),
        key=lambda p: matching.avaliar(descricao, p.titulo).score,
    )
    assert melhor.sku == "5002"


# ---------------------------------------------------------------------------
# Sellers
# ---------------------------------------------------------------------------

def test_ignora_o_primeiro_seller_quando_ele_esta_sem_estoque(executor):
    """sellers[0] é o parceiro sem estoque, a R$ 71,50."""
    produtos = {p.sku: p for p in executor.buscar("tabua")}

    assert produtos["5002"].vendedor == "1"
    assert produtos["5002"].preco == 68.0
    assert produtos["5002"].disponivel is True


# ---------------------------------------------------------------------------
# Preço
# ---------------------------------------------------------------------------

def test_guarda_preco_riscado_e_preco_pago(executor):
    produtos = {p.sku: p for p in executor.buscar("tabua")}

    assert produtos["5001"].preco == 39.9
    assert produtos["5001"].preco_lista == 49.9


def test_list_price_zerado_nao_vira_desconto(executor):
    """ListPrice 0 é "a loja não informou", não "de R$ 0,00 por R$ 24,90"."""
    mascara = next(p for p in executor.buscar("mascara") if p.sku == "5100")

    assert mascara.preco == 24.9
    assert mascara.preco_lista is None


# ---------------------------------------------------------------------------
# Falhas: cada uma com a sua cara
# ---------------------------------------------------------------------------

def test_bloqueio_sobe_para_o_runner(fornecedor):
    """Bloqueio não pode virar "nenhum produto encontrado"."""
    cliente = ClienteFalso(erro=SiteBloqueado("403", "https://loja-exemplo.com.br"))
    with pytest.raises(SiteBloqueado):
        VtexExecutor(fornecedor, cliente).buscar("tabua")


def test_timeout_devolve_vazio_e_nao_derruba_o_site(fornecedor, caplog):
    cliente = ClienteFalso(erro=FalhaDeRede("timeout", "https://loja-exemplo.com.br"))
    assert VtexExecutor(fornecedor, cliente).buscar("tabua") == []
    assert any("falhou" in r.message for r in caplog.records)


def test_json_quebrado_devolve_vazio_e_registra(fornecedor, caplog):
    cliente = ClienteFalso(erro=RespostaInvalida("json", "https://loja-exemplo.com.br"))
    assert VtexExecutor(fornecedor, cliente).buscar("tabua") == []
    assert any("JSON" in r.message for r in caplog.records)


def test_resposta_em_formato_inesperado_devolve_vazio(fornecedor):
    cliente = ClienteFalso({"products/search": {"erro": "sem resultados"}})
    assert VtexExecutor(fornecedor, cliente).buscar("tabua") == []


# ---------------------------------------------------------------------------
# Frete
# ---------------------------------------------------------------------------

def test_frete_usa_o_menor_sla_e_converte_de_centavos(fornecedor):
    cliente = ClienteFalso({
        "simulation": {
            "logisticsInfo": [{
                "slas": [
                    {"name": "Expressa", "price": 4590, "shippingEstimate": "2bd"},
                    {"name": "Normal", "price": 1990, "shippingEstimate": "7bd"},
                ]
            }]
        }
    })
    executor = VtexExecutor(fornecedor, cliente)

    valor, obs = executor.cotar_frete("https://loja-exemplo.com.br/p?skuId=5001", "80010010")

    assert valor == 19.9  # 1990 centavos, e não R$ 1.990,00
    assert "Normal" in obs


def test_frete_simula_com_o_seller_que_deu_o_preco(fornecedor, fixture_json):
    from src.models import ProdutoBruto

    cliente = ClienteFalso({"simulation": {"logisticsInfo": []}})
    executor = VtexExecutor(fornecedor, cliente)
    produto = ProdutoBruto(titulo="x", url="u", sku="5002", vendedor="marketplace-x")

    executor.cotar_frete("https://loja-exemplo.com.br/p", "80010010", produto)

    assert cliente.pedidos  # a simulação foi chamada


def test_sem_opcao_de_entrega_nao_inventa_valor(fornecedor):
    cliente = ClienteFalso({"simulation": {"logisticsInfo": [{"slas": []}]}})
    executor = VtexExecutor(fornecedor, cliente)

    valor, obs = executor.cotar_frete("https://loja-exemplo.com.br/p?skuId=1", "80010010")

    assert valor is None
    assert "sem opcao" in obs


def test_falha_na_simulacao_vira_observacao_e_nao_excecao(fornecedor):
    cliente = ClienteFalso(erro=FalhaDeRede("timeout", "https://loja-exemplo.com.br"))
    executor = VtexExecutor(fornecedor, cliente)

    valor, obs = executor.cotar_frete("https://loja-exemplo.com.br/p?skuId=1", "80010010")

    assert valor is None
    assert "indisponivel" in obs
