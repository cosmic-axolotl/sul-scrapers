"""Uma planilha de conferência por aba de origem.

O master é um CSV só, com tudo junto. Quem prospectou EPI não confere
121 linhas de seis categorias para achar as 12 dele — e é ele quem sabe
dizer se o CNPJ da linha está errado.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.export.validacao_por_aba import SEM_ORIGEM, gerar
from src.models import Fornecedor, Plataforma, Status


def fornecedor(dominio: str, origem: list[str], **campos) -> Fornecedor:
    padrao = {
        "nome": dominio.split(".")[0].upper(),
        "dominio": dominio,
        "url_base": f"https://{dominio}",
        "uf": "PR",
        "origem": origem,
    }
    return Fornecedor(**(padrao | campos))


def ler(caminho):
    return pd.read_excel(caminho, dtype=str).fillna("")


def test_uma_planilha_por_aba(tmp_path):
    gerados = gerar([
        fornecedor("alfa.com.br", ["lista_sites.xlsx :: EPI"]),
        fornecedor("beta.com.br", ["lista_sites.xlsx :: UNIFORME"]),
    ], tmp_path)

    assert {c.name for c in gerados} == {
        "validacao_lista_sites_EPI.xlsx",
        "validacao_lista_sites_UNIFORME.xlsx",
    }


def test_nome_do_arquivo_perde_acento_e_espaco(tmp_path):
    [caminho] = gerar(
        [fornecedor("alfa.com.br", ["lista de sites.xlsx :: Utensílios"])],
        tmp_path,
    )

    assert caminho.name == "validacao_lista_de_sites_Utensilios.xlsx"


def test_o_nome_do_arquivo_de_origem_entra_no_nome_da_planilha(tmp_path):
    """Duas prospecções com uma aba "EPI" cada não podem colidir."""
    gerados = gerar([
        fornecedor("alfa.com.br", ["prospeccao_a.xlsx :: EPI"]),
        fornecedor("beta.com.br", ["prospeccao_b.xlsx :: EPI"]),
    ], tmp_path)

    assert len(gerados) == 2
    assert len({c.name for c in gerados}) == 2


def test_site_de_duas_abas_sai_nas_duas_planilhas(tmp_path):
    """astrodistribuidora.com está em EPI e em UNIFORME; as duas abas
    têm que fechar sozinhas com o que a pessoa mandou."""
    gerar([fornecedor("astro.com.br", [
        "lista_sites.xlsx :: EPI", "lista_sites.xlsx :: UNIFORME",
    ])], tmp_path)

    epi = ler(tmp_path / "validacao_lista_sites_EPI.xlsx")
    uniforme = ler(tmp_path / "validacao_lista_sites_UNIFORME.xlsx")

    assert epi["Site"].tolist() == ["https://astro.com.br"]
    assert uniforme["Site"].tolist() == ["https://astro.com.br"]
    assert epi["Também em"].tolist() == ["UNIFORME"]   # e diz de onde mais veio


def test_traz_o_resultado_da_validacao(tmp_path):
    [caminho] = gerar([fornecedor(
        "alfa.com.br", ["leads.csv"],
        cnpj="61340901000117",
        cnae_principal="4642702",
        cnaes_secundarios=["4781400"],
        situacao_cadastral="ATIVA",
        flag_atacarejo=True,
        plataforma=Plataforma.WOOCOMMERCE,
        status=Status.APROVADO,
        motivo="CNAE principal 4642702 (atacado)",
    )], tmp_path)

    [linha] = ler(caminho).to_dict("records")

    assert linha["CNPJ"] == "61.340.901/0001-17"   # com máscara, para conferir
    assert linha["Status"] == "APROVADO"
    assert linha["CNAE principal"] == "4642702"
    assert linha["CNAEs secundários"] == "4781400"
    assert linha["Situação cadastral"] == "ATIVA"
    assert linha["Atacarejo"] == "SIM"
    assert linha["Plataforma"] == "woocommerce"
    assert linha["Motivo"] == "CNAE principal 4642702 (atacado)"


@pytest.mark.parametrize(("digitos", "esperado"), [
    ("61340901000117", "61.340.901/0001-17"),
    ("6134090100011", "6134090100011"),    # 13 dígitos: sai cru, para saltar aos olhos
    (None, ""),
])
def test_cnpj_so_ganha_mascara_se_tiver_14_digitos(tmp_path, digitos, esperado):
    [caminho] = gerar(
        [fornecedor("alfa.com.br", ["leads.csv"], cnpj=digitos)], tmp_path,
    )

    assert ler(caminho)["CNPJ"].tolist() == [esperado]


def test_aprovado_vem_antes_de_pendente_e_de_reprovado(tmp_path):
    [caminho] = gerar([
        fornecedor("c.com.br", ["leads.csv"], status=Status.REPROVADO),
        fornecedor("a.com.br", ["leads.csv"], status=Status.PENDENTE),
        fornecedor("b.com.br", ["leads.csv"], status=Status.APROVADO),
    ], tmp_path)

    assert ler(caminho)["Status"].tolist() == ["APROVADO", "PENDENTE", "REPROVADO"]


def test_fornecedor_sem_origem_nao_some(tmp_path):
    """Os que entraram antes do campo `origem` existir."""
    [caminho] = gerar([fornecedor("antigo.com.br", [])], tmp_path)

    assert SEM_ORIGEM.split()[0] in caminho.name.lower()
    assert len(ler(caminho)) == 1
