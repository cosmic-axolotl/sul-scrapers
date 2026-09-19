"""Gravação da varredura: acumular sem apagar o que já havia.

O defeito anterior: o arquivo do domínio era reescrito inteiro a cada
rodada, então varrer EPI depois de UTENSILIOS apagava os achados de
UTENSILIOS. E, quando nada era encontrado, `touch()` deixava o conteúdo
antigo intacto — o oposto do que "não achei nada" significa.
"""

from __future__ import annotations

import csv

import pytest

from src.models import Achado
from src.runners import etapa2_varredura


@pytest.fixture(autouse=True)
def destino_temporario(tmp_path, monkeypatch):
    monkeypatch.setattr(etapa2_varredura, "DESTINO", tmp_path / "achados")
    monkeypatch.setattr(etapa2_varredura, "BLOQUEADAS", tmp_path / "bloqueadas.csv")
    return tmp_path / "achados"


def achado(id_item: str, url: str = "https://loja.com.br/p") -> Achado:
    return Achado(
        id_item=id_item,
        dominio="loja.com.br",
        url_produto=url,
        titulo_encontrado=f"Produto {id_item}",
        score_match=0.9,
    )


def linhas_gravadas(destino):
    caminho = destino / "loja.com.br.csv"
    with caminho.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------------------

def test_grava_os_achados_da_rodada(destino_temporario):
    etapa2_varredura.gravar("loja.com.br", [achado("U001")], ["U001"])

    linhas = linhas_gravadas(destino_temporario)
    assert [l["id_item"] for l in linhas] == ["U001"]


def test_segunda_categoria_nao_apaga_a_primeira(destino_temporario):
    """O caso real: varrer EPI depois de UTENSILIOS na mesma loja."""
    etapa2_varredura.gravar("loja.com.br", [achado("U001")], ["U001"])
    etapa2_varredura.gravar("loja.com.br", [achado("294")], ["294"])

    ids = {l["id_item"] for l in linhas_gravadas(destino_temporario)}
    assert ids == {"U001", "294"}


def test_reprocessar_o_mesmo_item_substitui_o_resultado(destino_temporario):
    etapa2_varredura.gravar(
        "loja.com.br", [achado("U001", "https://loja.com.br/antigo")], ["U001"]
    )
    etapa2_varredura.gravar(
        "loja.com.br", [achado("U001", "https://loja.com.br/novo")], ["U001"]
    )

    linhas = linhas_gravadas(destino_temporario)
    assert len(linhas) == 1
    assert linhas[0]["url_produto"] == "https://loja.com.br/novo"


def test_item_varrido_sem_achado_perde_o_registro_antigo(destino_temporario):
    """Se o item foi procurado agora e não existe mais, sai do arquivo."""
    etapa2_varredura.gravar("loja.com.br", [achado("U001")], ["U001"])
    etapa2_varredura.gravar("loja.com.br", [], ["U001"])

    assert linhas_gravadas(destino_temporario) == []


def test_nada_encontrado_grava_cabecalho_e_nao_um_arquivo_vazio(destino_temporario):
    """Arquivo com cabeçalho diz "varri e não achei"; vazio não diz nada."""
    etapa2_varredura.gravar("loja.com.br", [], ["U001"])

    caminho = destino_temporario / "loja.com.br.csv"
    assert caminho.exists()
    conteudo = caminho.read_text(encoding="utf-8")
    assert conteudo.startswith("id_item,")
    assert linhas_gravadas(destino_temporario) == []


def test_ler_achados_devolve_lista_vazia_sem_arquivo(destino_temporario):
    assert etapa2_varredura.ler_achados("inexistente.com.br") == []


def test_grava_a_classificacao_do_matching(destino_temporario):
    """O plano de coleta precisa separar "aceito" de "revisar"."""
    a = achado("U001")
    a.classificacao = "revisar"
    a.motivo_match = "embalagem não confirmada"
    etapa2_varredura.gravar("loja.com.br", [a], ["U001"])

    linha = linhas_gravadas(destino_temporario)[0]
    assert linha["classificacao"] == "revisar"
    assert linha["motivo_match"] == "embalagem não confirmada"


def test_registrar_bloqueio_cria_a_planilha_de_bloqueadas(tmp_path, monkeypatch):
    monkeypatch.setattr(etapa2_varredura, "BLOQUEADAS", tmp_path / "bloqueadas.csv")

    etapa2_varredura.registrar_bloqueio("loja.com.br", "403 em 3 tentativas")

    linhas = (tmp_path / "bloqueadas.csv").read_text(encoding="utf-8").splitlines()
    assert linhas[0] == "dominio,quando,motivo"
    assert "loja.com.br" in linhas[1]
