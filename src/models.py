"""Contrato de dados do projeto. NÃO altere sem avisar o grupo.

Todo módulo do pipeline fala nestes tipos. A chave de junção em todo
lugar é `dominio` normalizado — nunca nome de empresa.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class Status(StrEnum):
    APROVADO = "APROVADO"
    REPROVADO = "REPROVADO"
    PENDENTE = "PENDENTE"


class Plataforma(StrEnum):
    VTEX = "vtex"
    WOOCOMMERCE = "woocommerce"
    NUVEMSHOP = "nuvemshop"
    SHOPIFY = "shopify"
    TRAY = "tray"
    MAGENTO = "magento"
    DESCONHECIDA = "desconhecida"


class ModoFrete(StrEnum):
    GRATIS_NACIONAL = "GRATIS_NACIONAL"
    GRATIS_REGIAO = "GRATIS_REGIAO"
    GRATIS_ACIMA_DE = "GRATIS_ACIMA_DE"
    TABELA_POR_CEP = "TABELA_POR_CEP"
    SOB_CONSULTA = "SOB_CONSULTA"


# CEPs de referência, um por estado do Sul.
CEPS_SUL: dict[str, str] = {
    "PR": "80010010",
    "SC": "88010400",
    "RS": "90010150",
}


@dataclass
class Item:
    """Uma linha da Lista de Equipamentos FNDE, já limpa."""

    id_item: str  # ID FGV -- ALFANUMERICO ("1", "G008", "U029", "E037")
    categoria: str  # UTENSILIOS | EQUIPAMENTO | EPI | UNIFORMES | ...
    grupo_insumo: str  # BACIA, PANELA, FACA
    descricao: str
    termos_busca: list[str] = field(default_factory=list)
    # Rótulo curto derivado da descrição na etapa 0. É o que vai para a
    # coluna "Item" da entrega -- a descrição inteira tem ~300 caracteres
    # e não cabe na planilha.
    item_curto: str = ""


@dataclass
class Fornecedor:
    nome: str
    dominio: str  # CHAVE PRIMÁRIA — normalizada
    url_base: str
    # UF da SEDE, para referência — não é critério. Fornecedor de
    # qualquer estado entra, desde que entregue no Sul e passe no
    # CNAE/CNPJ. Quem decide é `entrega_sul`, não este campo.
    uf: str
    cnpj: str | None = None  # só dígitos, 14 chars
    cnae_principal: str | None = None
    cnaes_secundarios: list[str] = field(default_factory=list)
    situacao_cadastral: str | None = None
    eh_atacadista: bool | None = None
    flag_atacarejo: bool = False
    # {"PR": True, "SC": False}. Só traz a UF sobre a qual houve
    # resposta: UF ausente é "não deu para saber", não é "não entrega".
    # É este campo, e não a UF da sede, que aprova ou reprova.
    entrega_sul: dict[str, bool] = field(default_factory=dict)
    plataforma: Plataforma = Plataforma.DESCONHECIDA
    modo_frete: ModoFrete | None = None
    status: Status = Status.PENDENTE
    motivo: str = ""


@dataclass
class ProdutoBruto:
    """O que um adapter devolve. Ainda não passou pelo matching.

    Um ProdutoBruto é UMA VARIAÇÃO, não um produto: a tábua de 30 cm e a
    de 50 cm são dois ProdutoBruto, porque têm preço diferente e só uma
    delas atende o item. Adapter que devolve só a primeira variação
    entrega preço de um produto que não é o pedido.
    """

    titulo: str
    url: str
    preco: float | None = None  # o que se paga hoje (já com desconto)
    disponivel: bool = True
    sku: str | None = None
    # Campos acrescentados depois, todos opcionais: nada que já existia
    # precisou mudar. `preco_lista` é o preço riscado/"de", e é ele que
    # alimenta a coluna "Preço PRODUTO" da entrega -- a coluna "VALOR
    # DESCONTO" é a diferença para `preco`.
    preco_lista: float | None = None
    vendedor: str | None = None  # seller VTEX/marketplace
    variacao: str | None = None  # nome da variação, quando difere do título


@dataclass
class Achado:
    """Resultado da varredura: este site tem algo parecido com este item."""

    id_item: str
    dominio: str
    url_produto: str
    titulo_encontrado: str
    score_match: float  # 0..1
    preco_indicativo: float | None = None
    coletado_em: datetime = field(default_factory=datetime.now)
    # Acrescentados depois, opcionais. Sem `classificacao` gravada, o
    # plano de coleta não consegue separar o que foi aceito do que ficou
    # para revisão humana -- e mandaria os dois para a coleta.
    classificacao: str = "aceito"  # aceito | revisar
    motivo_match: str = ""
    sku: str | None = None


@dataclass
class Coleta:
    """Uma linha da entrega final: item × fornecedor × UF."""

    id_item: str
    dominio: str
    uf: str
    url_produto: str
    titulo_encontrado: str
    preco_produto: float | None = None
    valor_desconto: float | None = None
    obs_desconto: str = ""
    preco_final: float | None = None
    valor_frete: float | None = None
    obs_frete: str = ""
    caminho_print: str = ""
    score_match: float = 0.0
    coletado_em: datetime = field(default_factory=datetime.now)
