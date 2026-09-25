"""Busca conferida à mão: da planilha até a varredura.

A heurística acerta a maioria das lojas e erra nas que respondem 200
para tudo. Quem abre o site, busca e vê o resultado sabe mais do que
ela — e precisa de um lugar para escrever isso que sobreviva às
rodadas seguintes.

Duas colunas, em qualquer planilha de `data/raw/leads/`:

    URL de busca      https://loja.com.br/busca?q={termo}
    Seletor de busca  #campo-busca

Preenchido é ordem, não sugestão: a varredura usa e não procura mais
nada.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.adapters.generico_playwright import PlaywrightExecutor
from src.adapters.registro import criar
from src.adapters.woocommerce import WooExecutor
from src.core.tabelas import gravar_fornecedores, ler_fornecedores
from src.models import Fornecedor, Plataforma, Status
from src.runners.etapa1_validar import (
    achar_coluna_composta,
    ler_leads,
    unificar_planilhas,
)
from tests.test_generico_playwright import PRODUTO, PaginaFalsa, montar


@pytest.fixture
def pasta(tmp_path):
    destino = tmp_path / "leads"
    destino.mkdir()
    return destino


def escrever(pasta, nome, dados):
    pd.DataFrame(dados).to_excel(pasta / nome, index=False)
    return pasta / nome


# ---------------------------------------------------------------------------
# Achar as colunas sem atrapalhar as que já existiam
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("coluna", [
    "URL de busca", "url busca", "Link de busca", "URL da pesquisa",
    "Endereço de busca", "URL DE PESQUISA", "url_busca",
])
def test_reconhece_os_nomes_da_coluna_de_url(pasta, coluna):
    escrever(pasta, "leads.xlsx", {
        "Site": ["alfa.com.br"], coluna: ["https://alfa.com.br/busca?q={termo}"],
    })

    [lead] = ler_leads(pasta)

    assert lead.url_busca == "https://alfa.com.br/busca?q={termo}"


@pytest.mark.parametrize("coluna", [
    "Seletor de busca", "seletor busca", "Campo de busca",
    "CSS da busca", "Seletor do campo de pesquisa", "input de busca",
])
def test_reconhece_os_nomes_da_coluna_de_seletor(pasta, coluna):
    escrever(pasta, "leads.xlsx", {"Site": ["alfa.com.br"], coluna: ["#busca"]})

    [lead] = ler_leads(pasta)

    assert lead.seletor_busca == "#busca"


def test_url_de_busca_nao_rouba_a_coluna_do_site(pasta):
    """"URL de busca" tem a palavra "url" e seria confundida com o site."""
    escrever(pasta, "leads.xlsx", {
        "URL de busca": ["https://alfa.com.br/busca?q={termo}"],
        "Site": ["https://alfa.com.br"],
    })

    [lead] = ler_leads(pasta)

    assert lead.dominio == "alfa.com.br"
    assert lead.url_base == "https://alfa.com.br"


def test_planilha_sem_as_colunas_novas_continua_lendo(pasta):
    """Ninguém é obrigado a preencher: a heurística segue existindo."""
    escrever(pasta, "leads.xlsx", {"Site": ["alfa.com.br"], "Empresa": ["Alfa"]})

    [lead] = ler_leads(pasta)

    assert lead.url_busca == ""
    assert lead.seletor_busca == ""


def test_coluna_composta_exige_palavra_de_cada_grupo():
    assert achar_coluna_composta(["Site"], {"url"}, {"busca"}) is None
    assert achar_coluna_composta(["URL de busca"], {"url"}, {"busca"}) == "URL de busca"


# ---------------------------------------------------------------------------
# O que a pessoa cola vira molde
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(("colado", "esperado"), [
    # já veio pronto
    ("https://alfa.com.br/busca?q={termo}", "https://alfa.com.br/busca?q={termo}"),
    # a URL de teste que funcionou, com o termo dentro
    ("https://alfa.com.br/busca?q=panela", "https://alfa.com.br/busca?q={termo}"),
    ("https://alfa.com.br/?s=panela", "https://alfa.com.br/?s={termo}"),
    ("https://alfa.com.br/catalogsearch/result/?q=panela",
     "https://alfa.com.br/catalogsearch/result/?q={termo}"),
    # só o caminho, sem o termo
    ("/busca?q=", "{base}/busca?q={termo}"),
    ("busca?q=", "{base}/busca?q={termo}"),
    ("  ", ""),
])
def test_normaliza_o_que_foi_colado(pasta, colado, esperado):
    escrever(pasta, "leads.xlsx", {"Site": ["alfa.com.br"], "URL de busca": [colado]})

    [lead] = ler_leads(pasta)

    assert lead.url_busca == esperado


def test_url_sem_lugar_para_o_termo_e_recusada_com_aviso(pasta, caplog):
    """Usá-la como está repetiria a mesma busca nos 132 itens."""
    import logging

    escrever(pasta, "leads.xlsx", {
        "Site": ["alfa.com.br"], "URL de busca": ["https://alfa.com.br/produtos"],
    })

    with caplog.at_level(logging.WARNING):
        [lead] = ler_leads(pasta)

    assert lead.url_busca == ""
    assert "{termo}" in caplog.text        # diz exatamente o que escrever


# ---------------------------------------------------------------------------
# A configuração sobrevive ao pipeline
# ---------------------------------------------------------------------------

def test_configuracao_sobrescreve_o_que_ja_estava(tmp_path, pasta):
    """Ao contrário do resto, esta coluna do lead GANHA: é a mais nova."""
    escrever(pasta, "novo.xlsx", {
        "Site": ["alfa.com.br"], "URL de busca": ["/busca-nova?q={termo}"],
    })

    [forn] = unificar_planilhas(
        base_sul=tmp_path / "x.xlsx",
        base_atacadistas=tmp_path / "y.xlsx",
        pasta_leads=pasta,
    )

    assert forn.url_busca == "{base}/busca-nova?q={termo}"


def test_vai_e_volta_pelo_master(tmp_path):
    master = tmp_path / "fornecedores_master.csv"
    gravar_fornecedores([Fornecedor(
        nome="Alfa", dominio="alfa.com.br", url_base="https://alfa.com.br", uf="PR",
        status=Status.APROVADO,
        url_busca="{base}/busca?q={termo}", seletor_busca="#busca",
    )], master)

    [forn] = list(ler_fornecedores(apenas_aprovados=False, caminho=master).values())

    assert forn.url_busca == "{base}/busca?q={termo}"
    assert forn.seletor_busca == "#busca"


# ---------------------------------------------------------------------------
# O master editado à mão
# ---------------------------------------------------------------------------

def test_master_editado_a_mao_e_normalizado_na_leitura(tmp_path):
    """Conferir 89 lojas numa tarde leva a editar o CSV direto, e uma URL
    sem {termo} buscaria a mesma coisa nos 132 itens sem dar erro."""
    master = tmp_path / "master.csv"
    master.write_text(
        "dominio,nome,url_base,uf,cnpj,cnae_principal,cnaes_secundarios,"
        "situacao_cadastral,eh_atacadista,flag_atacarejo,entrega_sul,plataforma,"
        "modo_frete,status,motivo,origem,url_busca,seletor_busca\n"
        "alfa.com.br,Alfa,https://alfa.com.br,PR,,,,ATIVA,,,,desconhecida,,"
        "APROVADO,,,https://alfa.com.br/busca?q=,#busca\n"
        "beta.com.br,Beta,https://beta.com.br,SC,,,,ATIVA,,,,desconhecida,,"
        "APROVADO,,,https://beta.com.br/?s=panela,\n",
        encoding="utf-8",
    )

    forn = ler_fornecedores(apenas_aprovados=False, caminho=master)

    assert forn["alfa.com.br"].url_busca == "https://alfa.com.br/busca?q={termo}"
    assert forn["beta.com.br"].url_busca == "https://beta.com.br/?s={termo}"


def test_colunas_trocadas_no_master_nao_passam(tmp_path, caplog):
    """URL no campo do seletor custaria a varredura inteira do site."""
    import logging

    master = tmp_path / "master.csv"
    master.write_text(
        "dominio,nome,url_base,uf,cnpj,cnae_principal,cnaes_secundarios,"
        "situacao_cadastral,eh_atacadista,flag_atacarejo,entrega_sul,plataforma,"
        "modo_frete,status,motivo,origem,url_busca,seletor_busca\n"
        "alfa.com.br,Alfa,https://alfa.com.br,PR,,,,ATIVA,,,,desconhecida,,"
        "APROVADO,,,,https://alfa.com.br/busca?q=x\n",
        encoding="utf-8",
    )

    with caplog.at_level(logging.WARNING):
        forn = ler_fornecedores(apenas_aprovados=False, caminho=master)

    assert forn["alfa.com.br"].seletor_busca == ""
    assert "trocadas" in caplog.text


# ---------------------------------------------------------------------------
# A varredura obedece
# ---------------------------------------------------------------------------

def loja(**campos) -> Fornecedor:
    padrao = {
        "nome": "Loja Exemplo", "dominio": "loja-exemplo.com.br",
        "url_base": "https://loja-exemplo.com.br", "uf": "PR",
        "status": Status.APROVADO,
    }
    return Fornecedor(**(padrao | campos))


def test_url_da_planilha_pula_a_descoberta():
    pagina = PaginaFalsa({"input[type='search']": "visivel"}, produtos=[PRODUTO])
    executor = PlaywrightExecutor(
        loja(url_busca="{base}/achar?termo={termo}"), cliente=None)
    executor._pagina = pagina
    executor._respeitar_intervalo = staticmethod(lambda: None)

    executor.buscar("tabua")

    assert pagina.url == "https://loja-exemplo.com.br/achar?termo=tabua"
    assert pagina.digitado == []          # nem olhou para o campo
    assert pagina.visitadas == ["https://loja-exemplo.com.br/achar?termo=tabua"]


def test_seletor_da_planilha_pula_a_descoberta():
    pagina = PaginaFalsa({"#meu-campo": "visivel", "input[type='search']": "visivel"},
                         produtos=[PRODUTO])
    executor = PlaywrightExecutor(loja(seletor_busca="#meu-campo"), cliente=None)
    executor._pagina = pagina
    executor._respeitar_intervalo = staticmethod(lambda: None)

    executor.buscar("tabua")

    assert pagina.digitado == [("#meu-campo", "tabua")]
    assert pagina.visitadas == ["https://loja-exemplo.com.br"]   # só a home


def test_chaves_digitadas_a_mais_nao_derrubam_a_montagem():
    """`str.format` explodiria com qualquer '{' digitado por engano."""
    pagina = PaginaFalsa({}, produtos=[PRODUTO])
    executor = PlaywrightExecutor(
        loja(url_busca="{base}/busca?q={termo}&filtro={preco}"), cliente=None)
    executor._pagina = pagina
    executor._respeitar_intervalo = staticmethod(lambda: None)

    executor.buscar("tabua")

    assert pagina.url.endswith("/busca?q=tabua&filtro={preco}")


def test_planilha_configurada_manda_o_site_para_o_navegador(cliente_falso):
    """Mesmo com plataforma de API detectada: quem conferiu viu a página."""
    cliente = cliente_falso({"wp-json/wc/store": [{"name": "Panela"}]})
    fornecedor = loja(plataforma=Plataforma.WOOCOMMERCE,
                      url_busca="{base}/busca?q={termo}")

    assert isinstance(criar(fornecedor, cliente), PlaywrightExecutor)
    assert cliente.pedidos == []          # nem sondou


def test_sem_configuracao_o_adapter_de_plataforma_continua_valendo(cliente_falso):
    cliente = cliente_falso({"wp-json/wc/store": [{"name": "Panela"}]})

    executor = criar(loja(plataforma=Plataforma.WOOCOMMERCE), cliente)

    assert isinstance(executor, WooExecutor)
