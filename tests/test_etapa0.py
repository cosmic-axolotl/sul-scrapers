"""Termos de busca que a etapa 0 gera a partir da descrição FNDE.

A varredura usa primeiro o termo mais específico. Um termo errado no
topo não dá erro nenhum: ele busca uma coisa que não existe, volta vazio
e o item passa por "loja não vende" em todas as lojas. Cada caso abaixo
saiu de um item real da lista, com o termo que ele gerava antes.
"""

from __future__ import annotations

import pytest

from src.runners.etapa0_limpar_itens import (
    contagem,
    gerar_termos,
    material,
    medidas,
    numero_ptbr,
)


# ---------------------------------------------------------------------------
# Números em pt-BR
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(("texto", "esperado"), [
    ("1.500", 1500.0),      # coifa 7: virava 1,5 mm
    ("1.044", 1044.0),      # refrigerador 29
    ("2,3", 2.3),           # purificador 28: vírgula é decimal
    ("12", 12.0),
    ("0,8", 0.8),
    ("1.500,5", 1500.5),
])
def test_numero_em_ptbr(texto, esperado):
    assert numero_ptbr(texto) == esperado


def test_ponto_de_milhar_nao_vira_decimal():
    """Coifa 7: "coifa 1.5 mm" é uma busca que não acha nada."""
    termos = gerar_termos("COIFA", "compatível com chapa bifeteira de 1.500 mm")
    assert termos[0] == "coifa 1500 mm"


def test_decimal_sai_com_virgula_para_a_loja():
    termos = gerar_termos("PURIFICADOR", "armazenamento interno de 2,3 litros")
    assert termos[0] == "purificador 2,3 l"


# ---------------------------------------------------------------------------
# Medidas que não são do equipamento
# ---------------------------------------------------------------------------

def test_taxa_por_hora_nao_e_tamanho():
    """Processador 27: "250 kg/h" é produção, e virava "processador 250 kg"."""
    assert medidas("capacidade de produção de 250 kg/h, inox") == []


@pytest.mark.parametrize("descricao", [
    "Forno turbo com capacidade para 10 esteiras de 580 × 680 mm",           # 19
    "grelhas removíveis em ferro fundido (300 × 300 mm ou 400 × 400 mm)",   # 15
    "trempes em ferro fundido de aproximadamente 400 × 400 mm",             # 17
    "Equipado com 7 discos de corte com diâmetro aproximado de 203 mm",     # 27
])
def test_medida_de_acessorio_fica_de_fora(descricao):
    assert medidas(descricao) == []


def test_medida_do_proprio_equipamento_continua():
    """A regra do acessório não pode apagar a capacidade de verdade."""
    assert medidas("Freezer horizontal com capacidade de 417 litros") == [(417.0, "l")]


def test_acessorio_em_outra_clausula_nao_contamina():
    """A vírgula fecha a cláusula: a esteira de lá não é o forno de cá."""
    texto = "acompanha 2 esteiras, capacidade de 70 litros"
    assert medidas(texto) == [(70.0, "l")]


# ---------------------------------------------------------------------------
# Contagens: só as peças do próprio equipamento
# ---------------------------------------------------------------------------

def test_fogao_e_buscado_pelo_numero_de_queimadores():
    """Fogões 15-18: antes, "fogao 400 mm" -- a medida da trempe."""
    termos = gerar_termos("FOGÃO", "Fogão industrial com 6 queimadores, "
                                   "trempes de 400 × 400 mm, estrutura em inox")
    assert termos[0] == "fogao 6 queimadores"


def test_forno_e_buscado_pelo_numero_de_esteiras():
    termos = gerar_termos("FORNO", "Forno turbo para 10 esteiras de 580 × 680 mm")
    assert termos[0] == "forno 10 esteiras"


@pytest.mark.parametrize(("grupo", "descricao"), [
    ("COIFA", "Coifa de parede, compatível com fogão industrial de 6 queimadores"),
    ("FORNO", "Forno integrado ao fogão industrial de 5 queimadores"),
])
def test_contagem_de_outro_equipamento_nao_vale(grupo, descricao):
    """Os queimadores são do fogão. "coifa 6 queimadores" não se vende."""
    assert contagem(grupo, descricao) is None


# ---------------------------------------------------------------------------
# Material
# ---------------------------------------------------------------------------

def test_madeira_nao_e_achada_dentro_de_mamadeira():
    """Esterilizador E036 virava "esterilizador madeira"."""
    assert material("Esterilizador elétrico de mamadeiras a vapor") is None


def test_inoxidavel_vira_inox_na_busca():
    """A loja escreve "inox"; "inoxidavel" só é reconhecido, não buscado."""
    assert material("prato em aço inoxidável") == "inox"
    assert material("estrutura em inox") == "inox"


# ---------------------------------------------------------------------------
# Forma do termo
# ---------------------------------------------------------------------------

def test_termo_nao_termina_em_virgula():
    """Balança 1: "balanca digital precisao," ia assim para a busca."""
    termos = gerar_termos("BALANÇA", "Balança digital de precisão, capacidade de 30 kg")
    assert not any(t.endswith((",", ".")) for t in termos)


def test_ancora_nao_para_em_preposicao():
    """Forno 34: "forno integrado ao", cortado no meio da frase."""
    termos = gerar_termos("FORNO", "Forno integrado ao fogão industrial")
    assert "forno integrado fogao" in termos


def test_o_nome_do_grupo_e_sempre_o_ultimo_termo():
    """Com medida, contagem, material e âncora, são quatro específicos --
    e cortar em quatro jogaria fora o recurso genérico da varredura."""
    termos = gerar_termos(
        "REFRIGERADOR",
        "Refrigerador comercial vertical de 4 portas, 1.044 litros, em inox",
    )
    assert termos[-1] == "refrigerador"
    assert len(termos) == 4
