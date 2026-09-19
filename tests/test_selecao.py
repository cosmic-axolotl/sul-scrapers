"""escolher_cinco(): cinco REGISTROS nunca foram cinco FORNECEDORES.

O caso que motivou estes testes foi reproduzido localmente: a função
ordenava e cortava em cinco, e devolveu cinco linhas do mesmo domínio,
todas sem preço, deixando na reserva um candidato que tinha preço.
"""

from __future__ import annotations

import pytest

from src.export.montar_entrega import ALVO_POR_ITEM, escolher_cinco, problema


@pytest.fixture
def print_valido(tmp_path):
    caminho = tmp_path / "print.png"
    caminho.write_bytes(b"png falso")
    return str(caminho)


def candidato(print_valido, dominio, preco=100.0, score=0.9, **extra):
    base = {
        "id_item": "294",
        "dominio": dominio,
        "uf": "PR",
        "preco_final": preco,
        "preco_produto": preco,
        "valor_frete": 20.0,
        "obs_frete": "tabela",
        "caminho_print": print_valido,
        "score_match": score,
    }
    base.update(extra)
    return base


# ---------------------------------------------------------------------------
# Validade de um registro
# ---------------------------------------------------------------------------

def test_registro_sem_preco_nao_serve(print_valido):
    c = candidato(print_valido, "a.com.br", preco=None)
    assert problema(c) == "sem preço"


def test_registro_com_preco_zero_nao_serve(print_valido):
    assert problema(candidato(print_valido, "a.com.br", preco=0)) == "sem preço"


def test_registro_sem_print_nao_serve(print_valido):
    c = candidato(print_valido, "a.com.br", caminho_print="")
    assert problema(c) == "sem print"


def test_print_que_nao_esta_no_disco_nao_serve(print_valido):
    c = candidato(print_valido, "a.com.br", caminho_print="data/output/prints/nao_existe.png")
    assert problema(c) == "print não está no disco"


def test_registro_com_frete_em_aberto_nao_serve(print_valido):
    c = candidato(print_valido, "a.com.br", valor_frete=None, obs_frete="")
    assert problema(c) == "frete não resolvido"


def test_frete_nulo_com_observacao_serve(print_valido):
    """Frete sob consulta é um resultado legítimo, desde que registrado."""
    c = candidato(print_valido, "a.com.br", valor_frete=None,
                  obs_frete="sob consulta: só por telefone")
    assert problema(c) == ""


def test_score_baixo_nao_serve(print_valido):
    assert "score" in problema(candidato(print_valido, "a.com.br", score=0.2))


# ---------------------------------------------------------------------------
# A escolha
# ---------------------------------------------------------------------------

def test_nao_escolhe_dois_registros_do_mesmo_fornecedor(print_valido):
    candidatos = [candidato(print_valido, "mesmaloja.com.br", score=0.9 - i / 100)
                  for i in range(5)]
    escolhidos, reserva = escolher_cinco(candidatos)

    assert len(escolhidos) == 1
    assert len(reserva) == 4
    assert all(r["motivo_reserva"] == "já há registro deste fornecedor" for r in reserva)


def test_o_caso_reproduzido_cinco_sem_preco_e_um_com_preco(print_valido):
    """Cinco do mesmo domínio sem preço não podem ganhar de um válido."""
    candidatos = [
        candidato(print_valido, "mesmaloja.com.br", preco=None, score=0.99)
        for _ in range(5)
    ]
    candidatos.append(candidato(print_valido, "outraloja.com.br", preco=80.0, score=0.7))

    escolhidos, _ = escolher_cinco(candidatos)

    assert [c["dominio"] for c in escolhidos] == ["outraloja.com.br"]


def test_escolhe_cinco_dominios_distintos(print_valido):
    candidatos = [candidato(print_valido, f"loja{i}.com.br", score=0.9) for i in range(8)]
    escolhidos, reserva = escolher_cinco(candidatos)

    assert len(escolhidos) == ALVO_POR_ITEM
    assert len({c["dominio"] for c in escolhidos}) == ALVO_POR_ITEM
    assert len(reserva) == 3


def test_ordena_por_score_e_depois_por_preco(print_valido):
    candidatos = [
        candidato(print_valido, "caro.com.br", preco=300.0, score=0.9),
        candidato(print_valido, "barato.com.br", preco=100.0, score=0.9),
        candidato(print_valido, "melhorscore.com.br", preco=999.0, score=0.95),
    ]
    escolhidos, _ = escolher_cinco(candidatos)

    assert [c["dominio"] for c in escolhidos] == [
        "melhorscore.com.br", "barato.com.br", "caro.com.br",
    ]


def test_reserva_diz_por_que_cada_um_ficou_de_fora(print_valido):
    candidatos = [
        candidato(print_valido, "sempreco.com.br", preco=None),
        candidato(print_valido, "ok.com.br"),
    ]
    _, reserva = escolher_cinco(candidatos)

    assert [r["motivo_reserva"] for r in reserva] == ["sem preço"]


def test_lista_vazia_nao_quebra():
    assert escolher_cinco([]) == ([], [])
