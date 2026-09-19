"""Retomada da coleta: o que conta como "já coletado".

Dois defeitos confirmados na versão anterior, ambos silenciosos:
  - registro sem preço e sem print marcava (item, UF) como pronto e
    nunca mais era refeito;
  - uma última linha de JSON truncada interrompia a leitura do arquivo.
"""

from __future__ import annotations

import json

import pytest

from src.runners.etapa3_coletar import (
    ja_coletados,
    ler_registros,
    registro_completo,
    sanear,
)


@pytest.fixture
def print_no_disco(tmp_path):
    caminho = tmp_path / "294__loja.com.br__PR.png"
    caminho.write_bytes(b"png falso")
    return str(caminho)


def registro(print_no_disco, **extra):
    base = {
        "id_item": "294",
        "dominio": "loja.com.br",
        "uf": "PR",
        "preco_produto": 24.9,
        "preco_final": 24.9,
        "valor_frete": 18.0,
        "obs_frete": "tabela",
        "caminho_print": print_no_disco,
    }
    base.update(extra)
    return base


def escrever(caminho, registros, cru: str = ""):
    with caminho.open("w", encoding="utf-8") as f:
        for r in registros:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
        if cru:
            f.write(cru)
    return caminho


# ---------------------------------------------------------------------------

def test_registro_completo_precisa_de_preco_frete_e_print(print_no_disco):
    assert registro_completo(registro(print_no_disco))


def test_registro_sem_preco_nao_conta_como_feito(print_no_disco):
    assert not registro_completo(
        registro(print_no_disco, preco_produto=None, preco_final=None)
    )


def test_registro_sem_print_nao_conta_como_feito(print_no_disco):
    assert not registro_completo(registro(print_no_disco, caminho_print=""))


def test_registro_com_print_que_sumiu_nao_conta_como_feito(print_no_disco):
    assert not registro_completo(
        registro(print_no_disco, caminho_print="/nao/existe/print.png")
    )


def test_ja_coletados_ignora_registro_incompleto(tmp_path, print_no_disco):
    arquivo = escrever(tmp_path / "loja.jsonl", [
        registro(print_no_disco, uf="PR"),
        registro(print_no_disco, uf="SC", preco_final=None, preco_produto=None),
    ])
    assert ja_coletados(arquivo) == {("294", "PR")}


def test_linha_truncada_nao_esconde_o_resto_do_arquivo(tmp_path, print_no_disco):
    """A linha quebrada é descartada; as boas continuam valendo."""
    arquivo = escrever(
        tmp_path / "loja.jsonl",
        [registro(print_no_disco, uf="PR"), registro(print_no_disco, uf="SC")],
        cru='{"id_item": "294", "uf": "RS", "preco_fi',
    )

    registros, descartadas = ler_registros(arquivo)

    assert descartadas == 1
    assert len(registros) == 2
    assert ja_coletados(arquivo) == {("294", "PR"), ("294", "SC")}


def test_sanear_reescreve_o_arquivo_sem_o_lixo(tmp_path, print_no_disco):
    """Precisa acontecer antes do append: senão o registro novo cola na
    linha truncada e corrompe os dois."""
    arquivo = escrever(
        tmp_path / "loja.jsonl",
        [
            registro(print_no_disco, uf="PR"),
            registro(print_no_disco, uf="SC", preco_final=None, preco_produto=None),
        ],
        cru='{"id_item": "294", "uf": "RS"',
    )

    completos = sanear(arquivo)

    assert [r["uf"] for r in completos] == ["PR"]
    linhas = arquivo.read_text(encoding="utf-8").strip().splitlines()
    assert len(linhas) == 1
    assert json.loads(linhas[0])["uf"] == "PR"  # o arquivo ficou legível


def test_sanear_nao_mexe_no_arquivo_quando_esta_tudo_certo(tmp_path, print_no_disco):
    arquivo = escrever(tmp_path / "loja.jsonl", [registro(print_no_disco)])
    antes = arquivo.read_text(encoding="utf-8")

    sanear(arquivo)

    assert arquivo.read_text(encoding="utf-8") == antes


def test_arquivo_inexistente_devolve_conjunto_vazio(tmp_path):
    assert ja_coletados(tmp_path / "nao_existe.jsonl") == set()
