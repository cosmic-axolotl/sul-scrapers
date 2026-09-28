"""Coleta de utensílios pelo navegador: só as partes puras, sem navegador."""

from __future__ import annotations

from src.core.frete import houve_recusa
from src.export.montar_entrega import escolher_cinco, ler_revisao
from src.models import Fornecedor, Status
from src.runners.coleta_utensilios import (
    interpretar_frete,
    interpretar_produto,
    preco_a_vista,
    sites_da_aba,
    valor_em_real,
    veio_da_aba,
)


def _forn(dominio, origem, status=Status.APROVADO, cnae=None, secundarios=()):
    return Fornecedor(nome=dominio, dominio=dominio, url_base=f"https://{dominio}",
                      uf="", origem=origem, status=status, cnae_principal=cnae,
                      cnaes_secundarios=list(secundarios))


def test_so_sites_aprovados_da_aba_utensilios():
    fornecedores = {
        "a.com": _forn("a.com", ["lista_sites.xlsx :: Utensílios"]),
        "b.com": _forn("b.com", ["lista_sites.xlsx :: EPI", "lista_sites.xlsx :: UNIFORME"]),
        "c.com": _forn("c.com", ["lista_sites.xlsx :: Utensílios"], Status.REPROVADO),
        "d.com": _forn("d.com", ["base.xlsx :: Plan1", "lista_sites.xlsx :: Utensilios"]),
        # Só aprovado pela exceção de varejo: canal --varejista, não este.
        "e.com": _forn("e.com", ["lista_sites.xlsx :: Utensílios"], cnae="4759899"),
        # Varejo com 46 secundário é atacarejo e fica.
        "f.com": _forn("f.com", ["lista_sites.xlsx :: Utensílios"], cnae="4759899",
                       secundarios=["4649499"]),
    }
    aprovados, fora = sites_da_aba(fornecedores)
    assert [f.dominio for f in aprovados] == ["a.com", "d.com", "f.com"]
    assert [f.dominio for f, _ in fora] == ["c.com", "e.com"]
    assert "varejista" in dict((f.dominio, m) for f, m in fora)["e.com"]
    assert not veio_da_aba(fornecedores["b.com"])


def test_valor_em_real():
    assert valor_em_real("R$ 1.234,56") == 1234.56
    assert valor_em_real("129.90") == 129.9
    assert valor_em_real("12,99") == 12.99
    assert valor_em_real("") is None
    assert valor_em_real("consulte") is None


def test_pix_menor_que_o_preco_publicado_vira_desconto():
    # Vencedor: JSON-LD publica o cheio, o PIX aparece no texto.
    bruto = {"titulo": "Colher de Servir 26cm",
             "ld": [{"nome": "Colher de Servir 26cm", "preco": "14.12"}],
             "precos": ["R$ 12,99 no PIX (8% OFF)", "R$ 14,12"],
             "pix": ["R$ 12,99 no PIX (8% OFF)"]}
    produto, obs = interpretar_produto(bruto, "https://x/p")
    assert (produto.preco_lista, produto.preco) == (14.12, 12.99)
    assert "PIX" in obs


def test_preco_publicado_ja_com_desconto_acha_o_cheio_na_mesma_caixa():
    # Platinox: JSON-LD publica o do PIX; o rótulo é imagem, não texto.
    bruto = {"ld": [{"nome": "Assadeira 60x40", "preco": "169.90"}],
             "precos": ["R$ 188,78 R$ 169,90 ou 3x de R$ 62,93 sem juros", "R$ 62,93"]}
    produto, obs = interpretar_produto(bruto, "https://x/p")
    assert (produto.preco_lista, produto.preco) == (188.78, 169.9)
    assert obs == "de 188.78 por 169.90"


def test_parcela_nao_e_preco():
    bruto = {"titulo": "Panela", "precos": ["10x de R$ 9,99 sem juros", "R$ 99,90"]}
    produto, _ = interpretar_produto(bruto, "https://x/p")
    assert produto.preco == 99.9
    assert produto.preco_lista is None


def test_riscado_menor_que_o_preco_e_ignorado():
    bruto = {"ld": [{"preco": "50.00"}], "riscados": ["R$ 45,00"]}
    produto, _ = interpretar_produto(bruto, "https://x/p")
    assert produto.preco == 50.0 and produto.preco_lista is None


def test_nome_do_json_ld_ganha_do_h1():
    bruto = {"titulo": "Confira nossas marcas", "ld": [{"nome": "Escorredor 26cm", "preco": 10}]}
    assert interpretar_produto(bruto, "https://x/p")[0].titulo == "Escorredor 26cm"


def test_preco_a_vista_nos_dois_sentidos():
    assert preco_a_vista(["R$ 169,90 PIX / Boleto"]) == 169.9
    assert preco_a_vista(["À vista no PIX: R$ 12,99"]) == 12.99
    assert preco_a_vista(["R$ 99,90 em 3x"]) is None


def test_frete_so_vale_o_que_apareceu_depois_do_cep():
    antes = "Frete e prazo de entrega Calcular Frete grátis acima de R$ 299,00"
    depois = antes + " | J&T NORMAL R$ 9,69 de 1 a 13 dias | CORREIOS PAC R$ 18,95"
    valor, obs = interpretar_frete(antes, depois, preco=14.12)
    assert valor == 9.69
    assert "cotado" in obs


def test_frete_sem_mudanca_nao_inventa_valor():
    assert interpretar_frete("Calcular frete", "Calcular frete") == (None, "")


def test_frete_gratis_e_recusa():
    assert interpretar_frete("Calcular", "Calcular | Frete grátis para seu CEP")[0] == 0.0
    valor, obs = interpretar_frete("Calcular", "Calcular | Não entregamos neste CEP")
    assert valor is None and houve_recusa(obs)


def _coleta(dominio, classificacao, score):
    return {"dominio": dominio, "id_item": "U001", "preco_final": 10.0, "valor_frete": 5.0,
            "caminho_print": __file__, "score_match": score, "classificacao": classificacao}


def test_montador_so_leva_revisar_decidido_como_aceito():
    candidatos = [_coleta("a.com", "aceito", 0.7), _coleta("b.com", "revisar", 0.5),
                  _coleta("c.com", "revisar", 0.9)]
    escolhidos, reserva = escolher_cinco(candidatos)
    assert [c["dominio"] for c in escolhidos] == ["a.com"]
    assert all("revisar" in r["motivo_reserva"] for r in reserva)

    revisao = {("b.com", "U001"): "aceito", ("c.com", "U001"): "recusado"}
    escolhidos, reserva = escolher_cinco(candidatos, revisao)
    # Aceito na revisão entra mesmo abaixo do score mínimo, depois do aceito.
    assert [c["dominio"] for c in escolhidos] == ["a.com", "b.com"]
    assert reserva[0]["motivo_reserva"] == "recusado na revisão"


def test_ler_revisao_ignora_linha_sem_decisao(tmp_path):
    arquivo = tmp_path / "revisao.csv"
    arquivo.write_text("dominio,id_item,decisao\nb.com,U001,Aceito\nc.com,U002,\n"
                       "d.com,U003,não\n", encoding="utf-8")
    assert ler_revisao(arquivo) == {("b.com", "U001"): "aceito",
                                    ("d.com", "U003"): "recusado"}


def test_planilha_le_as_duas_abas_de_utensilios_e_o_seletor(tmp_path):
    from openpyxl import Workbook

    from src.runners.coleta_utensilios import ler_planilha_sites

    wb = Workbook()
    ws = wb.active
    ws.title = "Utensílios"
    ws.append(["Nome fantasia", "CNPJ", "URL", "Análise"])
    ws.append(["Loja A", "1", "https://www.loja-a.com.br/", "fazer orçamento"])
    ws.append([])
    # Segunda tabela colada embaixo, com outro cabeçalho.
    ws.append(["Empresa", "Site informado", "URL validada", "Seletor CSS principal"])
    ws.append(["Loja B", "https://loja-b.com/", "https://www.loja-b.com/", "#busca"])
    scrap = wb.create_sheet("utensilios_scrappaveis")
    scrap.append(["Empresa", "Site informado", "URL validada", "Seletor CSS principal"])
    scrap.append(["Loja A", "https://loja-a.com.br/", "https://loja-a.com.br/", "input[name='q']"])
    epi = wb.create_sheet("EPI")
    epi.append(["Nome", "Site"])
    epi.append(["Loja EPI", "https://epi.com.br"])
    caminho = tmp_path / "lista.xlsx"
    wb.save(caminho)

    assert ler_planilha_sites(caminho) == {"loja-a.com.br": "input[name='q']",
                                           "loja-b.com": "#busca"}


def test_disponibilidade():
    base = {"ld": [{"preco": "10", "disponibilidade": "https://schema.org/OutOfStock"}]}
    assert interpretar_produto(base, "u")[0].disponivel is False
    # Botão de compra na tela ganha do JSON-LD desatualizado.
    assert interpretar_produto({**base, "disponivel": True}, "u")[0].disponivel is True
    assert interpretar_produto({"ld": [{"preco": "10"}]}, "u")[0].disponivel is True


def test_montador_descarta_indisponivel():
    c = {**_coleta("a.com", "aceito", 0.9), "disponivel": False}
    escolhidos, reserva = escolher_cinco([c])
    assert not escolhidos and reserva[0]["motivo_reserva"] == "produto indisponível"
