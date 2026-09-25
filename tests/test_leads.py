"""Ingestão dos leads da prospecção, em formato livre.

A frente C entrega "nome + domínio" no formato que preferir. O que o
pipeline exige é uma coluna só: a do site. O resto entra se estiver lá.

O defeito que motivou estes testes: uma planilha com a coluna chamada
"URL" em vez de "Site Oficial" produzia ZERO fornecedores sem erro
nenhum — e a pessoa ia procurar defeito no CNPJ ou na rede.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.models import Status
from src.runners.etapa1_validar import (
    SINONIMOS_SITE,
    PlanilhaSemColunaDeSite,
    achar_coluna,
    ler_leads,
    unificar_planilhas,
)


@pytest.fixture
def pasta(tmp_path):
    destino = tmp_path / "leads"
    destino.mkdir()
    return destino


def escrever(pasta, nome: str, dados: dict):
    caminho = pasta / nome
    df = pd.DataFrame(dados)
    if caminho.suffix == ".csv":
        df.to_csv(caminho, index=False)
    else:
        df.to_excel(caminho, index=False)
    return caminho


# ---------------------------------------------------------------------------
# Detecção de coluna
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "coluna",
    ["Site", "site", "URL", "url", "Domínio", "dominio", "Link",
     "Site Oficial", "Link (clicável)", "Site / domínio", "Fonte/site",
     "Página", "Website", "Endereço", "ENDERECO DO SITE", "Portal"],
)
def test_reconhece_os_nomes_usuais_de_coluna_de_site(coluna):
    assert achar_coluna([coluna], SINONIMOS_SITE) == coluna


def test_nome_exato_ganha_de_nome_que_so_contem(pasta):
    """Com 'Site' e 'Site do fabricante', a escolha não pode depender da ordem."""
    colunas = ["Site do fabricante", "Site"]
    assert achar_coluna(colunas, SINONIMOS_SITE) == "Site"


def test_coluna_irreconhecivel_devolve_none():
    assert achar_coluna(["Telefone", "Observações"], SINONIMOS_SITE) is None


# ---------------------------------------------------------------------------
# Leitura
# ---------------------------------------------------------------------------

def test_le_csv_com_coluna_url(pasta):
    escrever(pasta, "prospeccao.csv", {
        "Empresa": ["Atacado Alfa"],
        "URL": ["https://alfa.com.br"],
        "Estado": ["PR"],
    })

    leads = ler_leads(pasta)

    assert len(leads) == 1
    assert leads[0].dominio == "alfa.com.br"
    assert leads[0].nome == "Atacado Alfa"
    assert leads[0].uf == "PR"
    assert leads[0].status is Status.PENDENTE


def test_le_xlsx_com_outros_nomes_de_coluna(pasta):
    escrever(pasta, "leads.xlsx", {
        "Razão Social": ["Distribuidora Beta"],
        "Página": ["beta.com.br"],
        "UF": ["sc"],
    })

    [lead] = ler_leads(pasta)

    assert lead.dominio == "beta.com.br"
    assert lead.nome == "Distribuidora Beta"
    assert lead.uf == "SC"


def test_url_sem_esquema_vira_https(pasta):
    escrever(pasta, "leads.csv", {"Site": ["gama.com.br"]})
    [lead] = ler_leads(pasta)
    assert lead.url_base == "https://gama.com.br"


@pytest.mark.parametrize(("colado", "esperado"), [
    ("https://consigaz.com.br/p13/", "https://consigaz.com.br"),
    ("https://www.supergasbras.com.br/supergasbras/botijao-de-gas-p13",
     "https://www.supergasbras.com.br"),
    ("https://www.macropampa.com/empresa.php", "https://www.macropampa.com"),
    ("http://loja.com.br/busca?q=x", "http://loja.com.br"),
])
def test_link_fundo_vira_a_raiz_do_site(pasta, colado, esperado):
    """A busca e a API são penduradas na url_base: com o caminho do
    produto dentro, as duas viram 404. Seis fornecedores aprovados
    entraram assim na primeira varredura."""
    escrever(pasta, "leads.csv", {"Site": [colado]})

    [lead] = ler_leads(pasta)

    assert lead.url_base == esperado


def test_a_raiz_preserva_o_www(pasta):
    """Site que redireciona para www custa um 301 a cada busca sem ele."""
    escrever(pasta, "leads.csv", {"Site": ["https://www.alfa.com.br/produtos"]})

    [lead] = ler_leads(pasta)

    assert lead.url_base == "https://www.alfa.com.br"
    assert lead.dominio == "alfa.com.br"          # a chave continua sem www


def test_so_a_coluna_de_site_e_obrigatoria(pasta):
    """Sem nome, sem UF, sem CNPJ: ainda assim é um lead utilizável."""
    escrever(pasta, "minimo.csv", {"site": ["delta.com.br"]})

    [lead] = ler_leads(pasta)

    assert lead.dominio == "delta.com.br"
    assert lead.nome == ""
    assert lead.uf == ""


def test_pega_cnpj_quando_a_planilha_traz(pasta):
    escrever(pasta, "com_cnpj.csv", {
        "site": ["epsilon.com.br"],
        "CNPJ": ["61.340.901/0001-17"],
    })

    [lead] = ler_leads(pasta)

    assert lead.cnpj == "61340901000117"


def test_le_varios_arquivos_de_uma_vez(pasta):
    escrever(pasta, "pr.csv", {"site": ["um.com.br"]})
    escrever(pasta, "sc.xlsx", {"URL": ["dois.com.br"]})

    assert {l.dominio for l in ler_leads(pasta)} == {"um.com.br", "dois.com.br"}


def test_csv_com_ponto_e_virgula(pasta):
    """Excel em pt-BR salva CSV com ';'. É o caso mais comum da equipe."""
    caminho = pasta / "excel_ptbr.csv"
    caminho.write_text("Empresa;Site\nAlfa;alfa.com.br\n", encoding="utf-8")

    [lead] = ler_leads(pasta)

    assert lead.dominio == "alfa.com.br"
    assert lead.nome == "Alfa"


def test_linha_sem_site_e_pulada_sem_derrubar_o_arquivo(pasta):
    escrever(pasta, "leads.csv", {"site": ["ok.com.br", None, ""]})
    assert [l.dominio for l in ler_leads(pasta)] == ["ok.com.br"]


def test_ignora_arquivo_temporario_do_excel(pasta):
    escrever(pasta, "leads.csv", {"site": ["ok.com.br"]})
    (pasta / "~$leads.xlsx").write_bytes(b"lixo")

    assert len(ler_leads(pasta)) == 1


def test_pasta_inexistente_nao_e_erro(tmp_path):
    assert ler_leads(tmp_path / "nao_existe") == []


def test_pasta_vazia_nao_e_erro(pasta):
    assert ler_leads(pasta) == []


# ---------------------------------------------------------------------------
# Abas: o segundo erro silencioso
# ---------------------------------------------------------------------------

def escrever_abas(pasta, nome: str, abas: dict[str, dict]):
    """Um .xlsx com várias abas, como a prospecção entrega de verdade."""
    caminho = pasta / nome
    with pd.ExcelWriter(caminho) as escritor:
        for aba, dados in abas.items():
            pd.DataFrame(dados).to_excel(escritor, sheet_name=aba, index=False)
    return caminho


def test_le_todas_as_abas_nao_so_a_primeira(pasta):
    """O defeito: lista_sites.xlsx tinha 6 abas e o pipeline via 1."""
    escrever_abas(pasta, "lista_sites.xlsx", {
        "EPI": {"Site": ["epi.com.br"]},
        "UNIFORME": {"Site": ["uniforme.com.br"]},
        "Utensílios": {"URL": ["utensilios.com.br"]},
    })

    leads = ler_leads(pasta)

    assert {l.dominio for l in leads} == {
        "epi.com.br", "uniforme.com.br", "utensilios.com.br",
    }


def test_cada_aba_pode_ter_nome_de_coluna_proprio(pasta):
    """Em lista_sites.xlsx a aba Utensílios usa "URL"; as outras, "Site"."""
    escrever_abas(pasta, "leads.xlsx", {
        "A": {"Empresa": ["Alfa"], "Site": ["alfa.com.br"]},
        "B": {"Nome fantasia": ["Beta"], "URL": ["beta.com.br"]},
    })

    leads = {l.dominio: l for l in ler_leads(pasta)}

    assert leads["alfa.com.br"].nome == "Alfa"
    assert leads["beta.com.br"].nome == "Beta"


def test_lead_carrega_o_arquivo_e_a_aba_de_onde_veio(pasta):
    escrever_abas(pasta, "lista_sites.xlsx", {"EPI": {"Site": ["alfa.com.br"]}})

    [lead] = ler_leads(pasta)

    assert lead.origem == ["lista_sites.xlsx :: EPI"]


def test_csv_tem_origem_sem_aba(pasta):
    escrever(pasta, "prospeccao.csv", {"site": ["alfa.com.br"]})

    [lead] = ler_leads(pasta)

    assert lead.origem == ["prospeccao.csv"]


def test_aba_vazia_nao_derruba_a_leitura(pasta):
    """Capa, legenda e rascunho são comuns e não têm lead a perder."""
    escrever_abas(pasta, "leads.xlsx", {
        "EPI": {"Site": ["alfa.com.br"]},
        "Rascunho": {},
    })

    assert [l.dominio for l in ler_leads(pasta)] == ["alfa.com.br"]


def test_aba_com_linhas_e_sem_coluna_de_site_levanta_erro(pasta):
    """Uma aba ignorada em silêncio custa o mesmo que um arquivo inteiro."""
    escrever_abas(pasta, "leads.xlsx", {
        "EPI": {"Site": ["alfa.com.br"]},
        "UNIFORME": {"Empresa": ["Beta"], "Telefone": ["41 3333-3333"]},
    })

    with pytest.raises(PlanilhaSemColunaDeSite) as erro:
        ler_leads(pasta)

    assert "leads.xlsx :: UNIFORME" in str(erro.value)
    assert "Telefone" in str(erro.value)


def test_site_em_duas_abas_guarda_as_duas_origens(pasta, tmp_path):
    """astrodistribuidora.com está em EPI e em UNIFORME."""
    escrever_abas(pasta, "lista_sites.xlsx", {
        "EPI": {"Site": ["astro.com.br"]},
        "UNIFORME": {"Site": ["https://www.astro.com.br/"]},
    })

    [forn] = unificar_planilhas(
        base_sul=tmp_path / "x.xlsx",
        base_atacadistas=tmp_path / "y.xlsx",
        pasta_leads=pasta,
    )

    assert forn.origem == [
        "lista_sites.xlsx :: EPI", "lista_sites.xlsx :: UNIFORME",
    ]


# ---------------------------------------------------------------------------
# UF
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(("valor", "esperado"), [
    ("São José/SC", "SC"),
    ("BLUMENAU - SC", "SC"),
    ("Novo Hamburgo / RS", "RS"),
    ("pr", "PR"),
    ("SP", "SP"),
])
def test_coluna_cidade_uf_devolve_so_a_sigla(pasta, valor, esperado):
    """O sinônimo "uf" casa com "Cidade / UF" -- e trazia a cidade junto."""
    escrever(pasta, "leads.csv", {"Site": ["alfa.com.br"], "Cidade / UF": [valor]})

    [lead] = ler_leads(pasta)

    assert lead.uf == esperado


def test_estado_por_extenso_continua_passando_como_estava(pasta):
    """Não reconhecer não é motivo para apagar: o texto ainda informa."""
    escrever(pasta, "leads.csv", {"Site": ["alfa.com.br"], "Estado": ["Paraná"]})

    [lead] = ler_leads(pasta)

    assert lead.uf == "PARANÁ"


# ---------------------------------------------------------------------------
# O erro que antes era silencioso
# ---------------------------------------------------------------------------

def test_planilha_sem_coluna_de_site_levanta_erro(pasta):
    escrever(pasta, "sem_site.csv", {
        "Empresa": ["Alfa"], "Telefone": ["41 3333-3333"],
    })

    with pytest.raises(PlanilhaSemColunaDeSite) as erro:
        ler_leads(pasta)

    mensagem = str(erro.value)
    assert "sem_site.csv" in mensagem
    assert "Telefone" in mensagem   # diz quais colunas o arquivo tem
    assert "site" in mensagem       # e quais ele esperava


def test_erro_junta_todos_os_arquivos_problematicos(pasta):
    """Melhor listar os três de uma vez do que descobrir um por rodada."""
    escrever(pasta, "a.csv", {"Empresa": ["X"]})
    escrever(pasta, "b.csv", {"Telefone": ["1"]})
    escrever(pasta, "c.csv", {"site": ["ok.com.br"]})

    with pytest.raises(PlanilhaSemColunaDeSite) as erro:
        ler_leads(pasta)

    assert "a.csv" in str(erro.value)
    assert "b.csv" in str(erro.value)


# ---------------------------------------------------------------------------
# Integração com as duas bases
# ---------------------------------------------------------------------------

def test_lead_acrescenta_dominio_novo(tmp_path, pasta):
    escrever(pasta, "novos.csv", {"site": ["novo.com.br"], "Empresa": ["Novo"]})

    fornecedores = unificar_planilhas(
        base_sul=tmp_path / "nao_existe.xlsx",
        base_atacadistas=tmp_path / "nao_existe2.xlsx",
        pasta_leads=pasta,
    )

    assert [f.dominio for f in fornecedores] == ["novo.com.br"]


def test_lead_nao_sobrescreve_o_que_a_base_ja_resolveu(tmp_path, pasta):
    """A base atacadista tem CNPJ e decisão humana; o lead tem nome e site."""
    base = tmp_path / "atacadistas.xlsx"
    pd.DataFrame({
        "Empresa": ["Casa Cristalina"],
        "UF": ["SC"],
        "CNPJ": ["61.340.901/0001-17"],
        "CNAE principal": ["4641-9/02"],
        "Site / domínio": ["https://casacristalina.com.br/"],
        "Status atual": ["EXCLUÍDO - ECOMMERCE"],
        "Motivo / observação": ["site possui fluxo de compra online"],
    }).to_excel(base, sheet_name="Todos_encontrados", index=False)

    escrever(pasta, "leads.csv", {
        "site": ["casacristalina.com.br"], "Empresa": ["Nome Errado"],
    })

    [forn] = unificar_planilhas(
        base_sul=tmp_path / "nao_existe.xlsx",
        base_atacadistas=base,
        pasta_leads=pasta,
    )

    assert forn.status is Status.REPROVADO       # a decisão humana sobrevive
    assert forn.nome == "Casa Cristalina"        # e o nome da base também
    assert forn.cnpj == "61340901000117"


def test_lead_preenche_buraco_sem_apagar_nada(tmp_path, pasta):
    base = tmp_path / "regional.xlsx"
    pd.DataFrame({
        "Nome da Empresa": [""],          # a base regional não tem o nome
        "Site Oficial": ["alfa.com.br"],
        "Estado": [""],
    }).to_excel(base, sheet_name="Base de Empresas", index=False)

    escrever(pasta, "leads.csv", {
        "site": ["alfa.com.br"], "Empresa": ["Atacado Alfa"], "UF": ["PR"],
    })

    [forn] = unificar_planilhas(
        base_sul=base,
        base_atacadistas=tmp_path / "nao_existe.xlsx",
        pasta_leads=pasta,
    )

    assert forn.nome == "Atacado Alfa"
    assert forn.uf == "PR"


def test_dois_leads_do_mesmo_dominio_viram_um(pasta, tmp_path):
    escrever(pasta, "a.csv", {"site": ["alfa.com.br"], "Empresa": ["Alfa"]})
    escrever(pasta, "b.csv", {"site": ["https://www.alfa.com.br/"], "Empresa": ["Alfa"]})

    fornecedores = unificar_planilhas(
        base_sul=tmp_path / "x.xlsx",
        base_atacadistas=tmp_path / "y.xlsx",
        pasta_leads=pasta,
    )

    assert len(fornecedores) == 1
