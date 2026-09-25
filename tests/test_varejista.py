"""O canal --varejista: itens, sites e CNAEs de varejo, e nada mais.

Três tipos de fornecedor aprovado convivem no master, e cada um vai para
um lugar diferente:

    atacadista   46.65-6              só na varredura padrão
    atacarejo    47.59-8 + 46 sec.    nas duas (aprovado antes da exceção)
    só varejo    47.53-9, sem 46      só na --varejista

O terceiro só existe por causa da exceção de 23/09: uma loja de
eletrodoméstico entrando na varredura padrão seria procurada por EPI,
uniforme e pneu -- 101 dos 132 itens.
"""

from __future__ import annotations

import csv

import pytest

from src.core import tabelas
from src.export.validacao_por_aba import canal
from src.models import Fornecedor, Plataforma, Status
from src.orquestrador import carregar_itens, do_canal, montar_lotes
from src.validacao.classificar_cnae import eh_varejista, so_varejista

CABECALHO = ["id_item", "categoria", "grupo_insumo", "item_curto", "descricao",
             "termos_busca"]


def gravar_itens(caminho, linhas):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with caminho.open("w", newline="", encoding="utf-8") as f:
        escritor = csv.writer(f)
        escritor.writerow(CABECALHO)
        escritor.writerows(linhas)


FOGAO = ["15", "EQUIPAMENTO", "FOGÃO", "Fogão industrial", "Fogão industrial 6 queimadores",
         "fogao 6 queimadores | fogao"]
MASCARA = ["294", "EPI", "MASCARA", "Máscara", "Mascara descartavel TNT",
           "mascara 100 unidades | mascara"]


def fornecedor(dominio, cnae, secundarios=(), status=Status.APROVADO):
    return Fornecedor(
        nome=dominio, dominio=dominio, url_base=f"https://{dominio}", uf="PR",
        cnpj="61340901000117", cnae_principal=cnae,
        cnaes_secundarios=list(secundarios), situacao_cadastral="ATIVA",
        plataforma=Plataforma.DESCONHECIDA, status=status,
    )


ATACADISTA = fornecedor("atacado.com.br", "4665600")
ATACAREJO = fornecedor("frigo.com.br", "4759899", ["4649499"])
SO_VAREJO = fornecedor("lujao.com.br", "4753900")
REPROVADO = fornecedor("mundopelc.com.br", "4789004", status=Status.REPROVADO)
SEM_CNAE = fornecedor("herdado.com.br", None)   # aprovado à mão, sem consulta


@pytest.fixture
def projeto(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    gravar_itens(tmp_path / "data/interim/itens.csv", [FOGAO, MASCARA])
    gravar_itens(tmp_path / "data/interim/itens_varejo.csv", [FOGAO])
    tabelas.gravar_fornecedores(
        [ATACADISTA, ATACAREJO, SO_VAREJO, REPROVADO, SEM_CNAE],
        tmp_path / "data/interim/fornecedores_master.csv",
    )
    return tmp_path


# ---------------------------------------------------------------------------
# A regra, no módulo do validador
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(("cnae", "esperado"), [
    ("4753900", True), ("4759899", True), ("4759801", True),
    ("4665600", False), ("4789004", False), (None, False), ("", False),
])
def test_eh_varejista_pela_classe_do_cnae_principal(cnae, esperado):
    assert eh_varejista(cnae) is esperado


def test_so_varejista_e_quem_nao_tem_46_secundario():
    assert so_varejista("4753900", []) is True
    assert so_varejista("4759899", ["4649499"]) is False   # atacarejo
    assert so_varejista("4665600", []) is False             # atacadista


# ---------------------------------------------------------------------------
# Varredura: cada fornecedor no seu canal
# ---------------------------------------------------------------------------

def test_varredura_padrao_deixa_de_fora_so_quem_e_so_varejo(projeto):
    lotes = montar_lotes("varredura")

    assert set(lotes) == {"atacado.com.br", "frigo.com.br", "herdado.com.br"}


def test_varredura_varejista_so_tem_cnae_de_varejo(projeto):
    lotes = montar_lotes("varredura", varejista=True)

    assert set(lotes) == {"frigo.com.br", "lujao.com.br"}


def test_varredura_varejista_so_busca_os_itens_de_varejo(projeto):
    lotes = montar_lotes("varredura", varejista=True)

    assert all(ids == ["15"] for ids in lotes.values())   # sem a máscara


def test_varredura_padrao_continua_com_todos_os_itens(projeto):
    lotes = montar_lotes("varredura")

    assert all(set(ids) == {"15", "294"} for ids in lotes.values())


def test_aprovado_sem_cnae_nao_some_da_varredura_padrao(projeto):
    """Aprovação humana herdada da planilha, sem consulta: não há CNAE que
    o tire do padrão, e excluir por falta de dado seria perder fornecedor."""
    assert "herdado.com.br" in montar_lotes("varredura")
    assert "herdado.com.br" not in montar_lotes("varredura", varejista=True)


def test_reprovado_nao_entra_em_canal_nenhum(projeto):
    assert "mundopelc.com.br" not in montar_lotes("varredura")
    assert "mundopelc.com.br" not in montar_lotes("varredura", varejista=True)


# ---------------------------------------------------------------------------
# Coleta: o plano mistura as duas varreduras, o canal separa de novo
# ---------------------------------------------------------------------------

def test_coleta_respeita_o_canal(projeto):
    plano = projeto / "data/interim/plano_coleta.csv"
    with plano.open("w", newline="", encoding="utf-8") as f:
        escritor = csv.writer(f)
        escritor.writerow(["dominio", "ids_itens"])
        escritor.writerow(["lujao.com.br", "15"])
        escritor.writerow(["atacado.com.br", "15|294"])

    assert set(montar_lotes("coleta")) == {"atacado.com.br"}
    assert montar_lotes("coleta", varejista=True) == {"lujao.com.br": ["15"]}


# ---------------------------------------------------------------------------
# Itens
# ---------------------------------------------------------------------------

def test_worker_le_a_lista_de_varejo_no_canal_varejista(projeto):
    """rodar_site recarrega os itens em outro processo; o canal tem de ir junto."""
    assert set(carregar_itens(varejista=True)) == {"15"}
    assert set(carregar_itens()) == {"15", "294"}


def test_sem_a_lista_de_varejo_o_erro_diz_como_gerar(projeto):
    (projeto / "data/interim/itens_varejo.csv").unlink()

    with pytest.raises(FileNotFoundError) as erro:
        montar_lotes("varredura", varejista=True)

    assert "etapa0_limpar_itens" in str(erro.value)
    assert "--saida" in str(erro.value)


# ---------------------------------------------------------------------------
# O que a planilha de conferência mostra
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(("forn", "esperado"), [
    (ATACADISTA, "padrão"),
    (ATACAREJO, "padrão + varejista"),
    (SO_VAREJO, "varejista"),
    (REPROVADO, ""),
])
def test_coluna_canal_na_conferencia(forn, esperado):
    assert canal(forn) == esperado


def test_do_canal_e_canal_da_planilha_concordam():
    """A planilha não pode dizer um canal e o orquestrador varrer outro."""
    for forn in (ATACADISTA, ATACAREJO, SO_VAREJO):
        rotulo = canal(forn)
        assert do_canal(forn, varejista=False) == ("padrão" in rotulo)
        assert do_canal(forn, varejista=True) == ("varejista" in rotulo)
