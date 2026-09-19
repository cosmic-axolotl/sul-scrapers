"""O formato dos CSV intermediários, que dois programas diferentes leem.

`fornecedores_master.csv` é escrito pela etapa 1 e lido pelo orquestrador
e pelo montador. Um campo que não sobrevive à ida e volta vira um dado
perdido no meio do pipeline, sem erro nenhum aparecendo.
"""

from __future__ import annotations

import pytest

from src.core import tabelas
from src.models import Fornecedor, ModoFrete, Plataforma, Status
from src.validacao.classificar_cnae import decidir


@pytest.fixture
def master(tmp_path):
    return tmp_path / "fornecedores_master.csv"


def test_fornecedor_sobrevive_a_ida_e_volta(master):
    original = Fornecedor(
        nome="Casa Cristalina",
        dominio="casacristalina.com.br",
        url_base="https://casacristalina.com.br",
        uf="SC",
        cnpj="61340901000117",
        cnae_principal="4641902",
        cnaes_secundarios=["4649499", "4672900"],
        situacao_cadastral="ATIVA",
        eh_atacadista=True,
        flag_atacarejo=False,
        entrega_sul={"PR": True, "SC": True, "RS": False},
        plataforma=Plataforma.VTEX,
        modo_frete=ModoFrete.TABELA_POR_CEP,
        status=Status.APROVADO,
        motivo="CNAE principal 4641902 (atacado)",
    )

    tabelas.gravar_fornecedores([original], master)
    lido = tabelas.ler_fornecedores(apenas_aprovados=False, caminho=master)["casacristalina.com.br"]

    assert lido == original


def test_lista_de_cnaes_secundarios_nao_se_perde(master):
    tabelas.gravar_fornecedores([Fornecedor(
        nome="X", dominio="x.com.br", url_base="https://x.com.br", uf="PR",
        cnaes_secundarios=["4649499", "4672900"], status=Status.APROVADO,
    )], master)

    lido = tabelas.ler_fornecedores(caminho=master)["x.com.br"]
    assert lido.cnaes_secundarios == ["4649499", "4672900"]


def test_entrega_por_uf_nao_se_perde(master):
    tabelas.gravar_fornecedores([Fornecedor(
        nome="X", dominio="x.com.br", url_base="https://x.com.br", uf="PR",
        entrega_sul={"PR": True, "SC": False}, status=Status.APROVADO,
    )], master)

    lido = tabelas.ler_fornecedores(caminho=master)["x.com.br"]
    assert lido.entrega_sul == {"PR": True, "SC": False}


def test_apenas_aprovados_e_o_padrao(master):
    tabelas.gravar_fornecedores([
        Fornecedor(nome="A", dominio="a.com.br", url_base="https://a.com.br",
                   uf="PR", status=Status.APROVADO),
        Fornecedor(nome="B", dominio="b.com.br", url_base="https://b.com.br",
                   uf="PR", status=Status.PENDENTE),
        Fornecedor(nome="C", dominio="c.com.br", url_base="https://c.com.br",
                   uf="PR", status=Status.REPROVADO),
    ], master)

    assert set(tabelas.ler_fornecedores(caminho=master)) == {"a.com.br"}
    assert len(tabelas.ler_fornecedores(apenas_aprovados=False, caminho=master)) == 3


def test_master_inexistente_diz_qual_etapa_rodar(tmp_path):
    with pytest.raises(FileNotFoundError, match="etapa1_validar"):
        tabelas.ler_fornecedores(caminho=tmp_path / "nao_existe.csv")


def test_id_item_alfanumerico_continua_texto(tmp_path):
    """Converter para int perde 96 dos 144 itens."""
    import csv

    caminho = tmp_path / "itens.csv"
    with caminho.open("w", newline="", encoding="utf-8") as f:
        escritor = csv.writer(f)
        escritor.writerow(["id_item", "categoria", "grupo_insumo", "item_curto",
                           "descricao", "termos_busca"])
        for id_item in ("1", "G008", "U029", "318N"):
            escritor.writerow([id_item, "EPI", "X", "curto", "descricao", "a|b"])

    itens = tabelas.ler_itens(caminho=caminho)

    assert set(itens) == {"1", "G008", "U029", "318N"}
    assert itens["1"].termos_busca == ["a", "b"]


# ---------------------------------------------------------------------------
# Regra de CNAE — regra em código, não critério no olho
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "principal,secundarios,situacao,esperado,atacarejo",
    [
        ("4641902", [], "ATIVA", Status.APROVADO, False),
        ("4759899", ["4649499"], "ATIVA", Status.APROVADO, True),
        ("4759899", [], "ATIVA", Status.REPROVADO, False),
        ("4641902", [], "BAIXADA", Status.REPROVADO, False),
        ("1091102", [], "ATIVA", Status.REPROVADO, False),
        ("4530703", [], "ATIVA", Status.PENDENTE, False),
        (None, [], "ATIVA", Status.PENDENTE, False),
        ("4641902", [], "", Status.PENDENTE, False),
    ],
)
def test_decisao_por_cnae(principal, secundarios, situacao, esperado, atacarejo):
    status, flag, motivo = decidir(principal, secundarios, situacao)
    assert status is esperado
    assert flag is atacarejo
    assert motivo
