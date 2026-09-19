"""O matching é o único controle de aderência do projeto. Testado como tal.

Cada caso aqui corresponde a um jeito conhecido de a planilha final sair
errada: a peça avulsa cotada como se fosse o pacote de 100, a panela de
50 L no lugar da de 20 L, a caixa de 50 vendida como a de 100.
"""

from __future__ import annotations

import pytest

from src.core import matching


# ---------------------------------------------------------------------------
# Extração
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "texto,esperado",
    [
        ("100UNIDADE COMERCIALIZADO EM PACOTE", {("un", 100)}),
        ("Pacote com 100 unidades", {("un", 100)}),
        ("50PAR COMERCIALIZADO EM PACOTE", {("par", 50)}),
        ("Protetor auricular - 50 pares", {("par", 50)}),
        ("Kit 5 tábuas de corte", {("un", 5)}),
        ("Kit composto por 5 unidades", {("un", 5)}),
        ("caixa com 12 pcs", {("un", 12)}),
    ],
)
def test_extrai_quantidade_de_embalagem(texto, esperado):
    assert set(matching.embalagem(texto).quantidades) == esperado


def test_caixa_de_20_litros_nao_e_caixa_com_20_pecas():
    """O contraexemplo que obriga o conectivo a ser opcional com cuidado."""
    assert matching.embalagem("caixa térmica 20 l").numeros == set()
    assert matching.embalagem("caixa com 20 unidades").numeros == {20}


def test_unidade_avulsa_nao_conta_como_embalagem():
    emb = matching.embalagem("1UNIDADE COMERCIALIZADO EM UNIDADE")
    assert emb.avulso


@pytest.mark.parametrize(
    "texto,esperado",
    [
        ("12 litros", {("volume", 12.0)}),
        ("1500 mm", {("comprimento", 1.5)}),
        ("100 cm", {("comprimento", 1.0)}),
        ("30 kg", {("massa", 30.0)}),
    ],
)
def test_extrai_dimensoes_na_unidade_canonica(texto, esperado):
    assert matching.dimensoes(texto) == esperado


def test_cadeia_de_dimensoes_herda_a_unidade_do_fim():
    """'50 x 30 x 0,8 cm' são três medidas, não só a espessura."""
    achadas = matching.dimensoes("50 x 30 x 0,8 cm")
    assert achadas == {
        ("comprimento", 0.5),
        ("comprimento", 0.3),
        ("comprimento", 0.008),
    }


def test_metro_e_centimetro_sao_comparaveis():
    assert matching.dimensoes("1 m") == matching.dimensoes("100 cm")


# ---------------------------------------------------------------------------
# Decisão
# ---------------------------------------------------------------------------

def test_unidade_avulsa_nao_e_aceita_no_lugar_do_pacote(item_mascara):
    """O buraco que existia: a máscara avulsa competindo com o pacote de 100."""
    avaliacao = matching.avaliar(
        item_mascara.descricao, "Mascara Descartavel TNT Branca - 1 unidade"
    )
    assert avaliacao.classificacao != "aceito"
    assert "100" in avaliacao.motivo


def test_pacote_com_a_quantidade_certa_e_aceito(item_mascara):
    avaliacao = matching.avaliar(
        item_mascara.descricao,
        "Mascara Descartavel TNT Polipropileno Branca - Pacote com 100 unidades",
    )
    assert avaliacao.classificacao == "aceito"


def test_pacote_com_quantidade_errada_e_descartado(item_mascara):
    """Não existe leitura em que um pacote de 50 atenda quem pediu 100."""
    avaliacao = matching.avaliar(
        item_mascara.descricao, "Mascara Descartavel TNT - Caixa com 50 unidades"
    )
    assert avaliacao.classificacao == "descartado"


def test_titulo_sem_quantidade_vai_para_revisao(item_mascara):
    avaliacao = matching.avaliar(
        item_mascara.descricao, "Mascara Descartavel TNT Polipropileno Branca"
    )
    assert avaliacao.classificacao == "revisar"


def test_par_e_reconhecido_como_embalagem():
    descricao = (
        "PROTETOR AURICULAR PLUGUE SILICONE CORDAO DE POLIESTER 17DB 800228 "
        "CAMPER 50PAR COMERCIALIZADO EM PACOTE"
    )
    avulso = matching.avaliar(descricao, "Protetor Auricular Plug Silicone 17dB - 1 par")
    pacote = matching.avaliar(
        descricao, "Protetor Auricular Plug Silicone com Cordao 17dB - Pacote 50 pares"
    )
    assert avulso.classificacao != "aceito"
    assert pacote.classificacao == "aceito"


def test_kit_com_a_quantidade_certa_e_aceito(item_tabua):
    avaliacao = matching.avaliar(
        item_tabua.descricao,
        "Kit 5 Tabuas de Corte Polietileno 50 x 30 x 0,8 cm coloridas",
    )
    assert avaliacao.classificacao == "aceito"


def test_tabua_avulsa_nao_passa_como_kit(item_tabua):
    avaliacao = matching.avaliar(
        item_tabua.descricao, "Tabua de Corte Polietileno 50x30 cm"
    )
    assert avaliacao.classificacao != "aceito"


def test_medida_divergente_impede_aprovacao_automatica():
    """Era o segundo buraco: divergir só custava o bônus."""
    descricao = "Panela de pressão industrial em aluminio, capacidade de 20 litros"
    certa = matching.avaliar(descricao, "Panela de Pressao Industrial Aluminio 20 L")
    errada = matching.avaliar(descricao, "Panela de Pressao Industrial Aluminio 50 L")

    assert certa.classificacao == "aceito"
    assert errada.classificacao != "aceito"
    assert errada.score < certa.score


def test_produto_em_pacote_nao_entra_no_lugar_da_unidade():
    """Preço de pacote numa linha que pede 1 unidade é preço errado."""
    descricao = (
        "AVENTAL PVC IMPERMEAVEL COM FORRO 120 CM X 65 CM BRANCO 1UNIDADE "
        "COMERCIALIZADO EM UNIDADE"
    )
    avaliacao = matching.avaliar(
        descricao, "Avental PVC Impermeavel 120 cm x 65 cm - Pacote com 10 unidades"
    )
    assert avaliacao.classificacao != "aceito"


def test_classificar_respeita_os_limites():
    assert matching.classificar(matching.LIMITE_ACEITE) == "aceito"
    assert matching.classificar(matching.LIMITE_REVISAO) == "revisar"
    assert matching.classificar(matching.LIMITE_REVISAO - 0.1) == "descartado"


def test_score_normalizado_cabe_em_zero_a_um(item_mascara):
    avaliacao = matching.avaliar(
        item_mascara.descricao,
        "Mascara Descartavel TNT Polipropileno Branca - Pacote com 100 unidades",
    )
    assert 0.0 <= avaliacao.score_normalizado <= 1.0


# ---------------------------------------------------------------------------
# Termos de busca
# ---------------------------------------------------------------------------

def test_termo_de_busca_leva_a_embalagem(item_mascara):
    termos = matching.gerar_termos(item_mascara)
    assert any("100" in t for t in termos), termos


def test_termo_de_busca_usa_a_maior_dimensao_em_unidade_legivel(item_tabua):
    """'tabua corte 0.008 m' é a espessura em metros: ninguém busca assim."""
    termos = matching.gerar_termos(item_tabua)
    assert any("50 cm" in t for t in termos), termos
    assert not any("0.008" in t for t in termos), termos
