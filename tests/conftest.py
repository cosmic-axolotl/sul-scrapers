"""Peças compartilhadas dos testes.

Nenhum teste aqui toca a rede. O que precisa de resposta de loja usa
fixture salva em tests/fixtures/ — que é a regra do projeto: nada de
confiar em nome de campo sem uma resposta real gravada.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

FIXTURES = Path(__file__).parent / "fixtures"

from src.models import Fornecedor, Item, Plataforma, Status  # noqa: E402


@pytest.fixture
def fixture_json():
    def ler(nome: str):
        return json.loads((FIXTURES / nome).read_text(encoding="utf-8"))

    return ler


@pytest.fixture
def fornecedor() -> Fornecedor:
    return Fornecedor(
        nome="Loja Exemplo",
        dominio="loja-exemplo.com.br",
        url_base="https://loja-exemplo.com.br",
        uf="PR",
        cnpj="61340901000117",
        plataforma=Plataforma.VTEX,
        status=Status.APROVADO,
    )


@pytest.fixture
def item_mascara() -> Item:
    """Item 294 da lista real: pacote com 100."""
    return Item(
        id_item="294",
        categoria="EPI",
        grupo_insumo="MASCARA",
        item_curto="Mascara descartavel TNT",
        descricao=(
            "MASCARA DESCARTAVEL TNT POLIPROPILENO COM ELASTICO BRANCA BRASMO "
            "100UNIDADE COMERCIALIZADO EM PACOTE"
        ),
    )


@pytest.fixture
def item_tabua() -> Item:
    """Item U053 da lista real: kit com 5 tábuas."""
    return Item(
        id_item="U053",
        categoria="UTENSILIOS",
        grupo_insumo="TABUA DE CORTE",
        item_curto="Kit de tábuas profissionais",
        descricao=(
            "Kit de tábuas profissionais para corte de alimentos, composto por 5 "
            "unidades em cores distintas, confeccionadas em polietileno de alta "
            "densidade (PEAD) atóxico. Possuem dimensões aproximadas de 50 x 30 x "
            "0,8 cm (comprimento x largura x espessura)"
        ),
    )


class ClienteFalso:
    """Substitui src.core.http.Cliente nos testes de adapter.

    Guarda as URLs pedidas: vários testes afirmam justamente qual
    endpoint foi chamado.
    """

    def __init__(self, respostas: dict | None = None, erro: Exception | None = None):
        self.respostas = respostas or {}
        self.erro = erro
        self.pedidos: list[str] = []

    def get(self, url: str, **kwargs):
        self.pedidos.append(url)
        if self.erro:
            raise self.erro
        for chave, valor in self.respostas.items():
            if chave in url:
                return valor if isinstance(valor, str) else json.dumps(valor)
        return ""

    def get_json(self, url: str, **kwargs):
        self.pedidos.append(url)
        if self.erro:
            raise self.erro
        for chave, valor in self.respostas.items():
            if chave in url:
                return valor
        return []

    def post_json(self, url: str, corpo: dict, **kwargs):
        self.pedidos.append(url)
        if self.erro:
            raise self.erro
        for chave, valor in self.respostas.items():
            if chave in url:
                return valor
        return {}


@pytest.fixture
def cliente_falso():
    return ClienteFalso
