"""Entrega no Sul como critério — o filtro que substituiu a geografia.

Enquanto só entravam lojas do Sul e de SP, a geografia fazia esse
trabalho de graça. Abrindo a lista para o país inteiro, o que separa um
atacadista útil de um inútil é se ele coloca a caixa em Curitiba, e isso
passou a ser verificado de verdade em dois lugares: na aprovação do
fornecedor e na hora de deixar a linha entrar na planilha.

A regra que amarra os dois: recusa reprova, silêncio não. Um site fora
do ar não pode virar "não entrega no Sul".
"""

from __future__ import annotations

import pytest

from src.core.frete import SEM_ENTREGA, houve_recusa
from src.export.montar_entrega import problema
from src.models import Fornecedor, Status
from src.runners.etapa1_validar import decidir_entrega


def fornecedor(uf: str = "AM", **extra) -> Fornecedor:
    base = dict(
        nome="Atacado Exemplo", dominio="exemplo.com.br",
        url_base="https://exemplo.com.br", uf=uf,
        cnpj="61340901000117", cnae_principal="4649499",
        situacao_cadastral="ATIVA", status=Status.APROVADO,
        motivo="CNAE principal 4649499 (atacado)",
    )
    base.update(extra)
    return Fornecedor(**base)


# ---------------------------------------------------------------------------
# A UF da sede não é critério
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("uf", ["AM", "BA", "SP", "PR", "GO", ""])
def test_fornecedor_de_qualquer_uf_entra_se_entrega_no_sul(uf):
    forn = decidir_entrega(fornecedor(uf, entrega_sul={"PR": True, "SC": True, "RS": True}))
    assert forn.status is Status.APROVADO


def test_fornecedor_do_sul_sai_se_nao_entrega_no_sul():
    """A recíproca: estar no Sul não basta, e nunca bastou."""
    forn = decidir_entrega(
        fornecedor("PR", entrega_sul={"PR": False, "SC": False, "RS": False})
    )
    assert forn.status is Status.REPROVADO


# ---------------------------------------------------------------------------
# Recusa reprova, silêncio não
# ---------------------------------------------------------------------------

def test_recusa_nas_tres_ufs_reprova():
    forn = decidir_entrega(
        fornecedor(entrega_sul={"PR": False, "SC": False, "RS": False})
    )
    assert forn.status is Status.REPROVADO
    assert forn.motivo == "não entrega em PR, SC nem RS"


def test_atender_uma_uf_basta_para_seguir():
    """Cada linha da entrega é item x fornecedor x UF: quem atende só o
    PR ainda rende as linhas do PR."""
    forn = decidir_entrega(
        fornecedor(entrega_sul={"PR": True, "SC": False, "RS": False})
    )
    assert forn.status is Status.APROVADO
    assert "entrega em PR" in forn.motivo


def test_sem_resposta_nenhuma_fica_pendente_e_nao_reprovado():
    """Site fora do ar não pode sumir da lista."""
    forn = decidir_entrega(fornecedor(entrega_sul={}))
    assert forn.status is Status.PENDENTE
    assert "não confirmada" in forn.motivo


def test_resposta_parcial_fica_pendente():
    """Duas recusas e um timeout ainda não são prova de que não entrega."""
    forn = decidir_entrega(fornecedor(entrega_sul={"PR": False, "SC": False}))
    assert forn.status is Status.PENDENTE
    assert "RS" in forn.motivo


# ---------------------------------------------------------------------------
# O marcador de recusa
# ---------------------------------------------------------------------------

def test_reconhece_a_recusa_com_e_sem_acento():
    assert houve_recusa(f"{SEM_ENTREGA} para este CEP")
    assert houve_recusa("Sem Opção de Entrega para este CEP")


def test_nao_confunde_sob_consulta_com_recusa():
    assert not houve_recusa("sob consulta: cotação só por telefone")
    assert not houve_recusa("cotacao indisponivel (FalhaDeRede)")


# ---------------------------------------------------------------------------
# A linha não entra na planilha
# ---------------------------------------------------------------------------

@pytest.fixture
def registro(tmp_path):
    png = tmp_path / "p.png"
    png.write_bytes(b"png falso")
    return {
        "id_item": "294", "dominio": "exemplo.com.br", "uf": "PR",
        "preco_produto": 24.9, "preco_final": 24.9,
        "valor_frete": None, "obs_frete": "",
        "caminho_print": str(png), "score_match": 0.92,
    }


def test_linha_sem_entrega_nao_vai_para_a_planilha(registro):
    """Era o furo: a linha entrava com frete vazio e parecia coletada."""
    registro["obs_frete"] = f"{SEM_ENTREGA} para este CEP"
    assert problema(registro) == "fornecedor não entrega nesta UF"


def test_frete_sob_consulta_continua_entrando(registro):
    registro["obs_frete"] = "sob consulta: cotação só por telefone"
    assert problema(registro) == ""


def test_frete_em_branco_continua_reprovando(registro):
    assert problema(registro) == "frete não resolvido"


def test_frete_com_valor_entra_normalmente(registro):
    registro["valor_frete"] = 24.9
    registro["obs_frete"] = "Normal 7bd"
    assert problema(registro) == ""
