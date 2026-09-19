"""Leitura e escrita dos CSV intermediários. Um único lugar por formato.

Antes, quem gravava `fornecedores_master.csv` (etapa 1) e quem o lia (o
orquestrador) eram arquivos diferentes, sem nada em comum além da
esperança de escreverem as mesmas colunas. Este módulo é o contrato: se
o formato mudar, muda aqui e os dois lados acompanham.

Os CSV guardam texto. `Fornecedor` guarda lista, dicionário, bool e
enum. A tradução entre os dois mora aqui e em nenhum outro lugar.
"""

from __future__ import annotations

import csv
import os
from pathlib import Path

from src.core.http import normalizar_dominio
from src.core.log import obter
from src.models import Fornecedor, Item, ModoFrete, Plataforma, Status

log = obter(__name__)

ITENS = Path("data/interim/itens.csv")
FORNECEDORES = Path("data/interim/fornecedores_master.csv")

COLUNAS_FORNECEDOR = [
    "dominio", "nome", "url_base", "uf", "cnpj", "cnae_principal",
    "cnaes_secundarios", "situacao_cadastral", "eh_atacadista",
    "flag_atacarejo", "entrega_sul", "plataforma", "modo_frete",
    "status", "motivo",
]



# ---------------------------------------------------------------------------
# Conversões
# ---------------------------------------------------------------------------

def _texto_bool(valor: bool | None) -> str:
    return "" if valor is None else ("sim" if valor else "nao")


def _bool_do_texto(texto: str) -> bool | None:
    t = (texto or "").strip().lower()
    if t in ("sim", "s", "true", "1", "verdadeiro"):
        return True
    if t in ("nao", "não", "n", "false", "0", "falso"):
        return False
    return None


def _texto_entrega(entrega: dict[str, bool]) -> str:
    """{'PR': True, 'SC': False} -> 'PR:sim|SC:nao'"""
    return "|".join(f"{uf}:{_texto_bool(v)}" for uf, v in sorted(entrega.items()))


def _entrega_do_texto(texto: str) -> dict[str, bool]:
    entrega: dict[str, bool] = {}
    for parte in (texto or "").split("|"):
        if ":" not in parte:
            continue
        uf, valor = parte.split(":", 1)
        convertido = _bool_do_texto(valor)
        if convertido is not None:
            entrega[uf.strip().upper()] = convertido
    return entrega


# ---------------------------------------------------------------------------
# Itens
# ---------------------------------------------------------------------------

def ler_itens(
    categorias: list[str] | None = None,
    caminho: Path = ITENS,
) -> dict[str, Item]:
    """itens.csv -> {id_item: Item}, na ordem do arquivo.

    `id_item` é string sempre. Converter para int perderia 96 dos 144.
    """
    if not caminho.exists():
        raise FileNotFoundError(
            f"{caminho} nao existe. Rode: python -m src.runners.etapa0_limpar_itens"
        )

    alvo = {c.strip().upper() for c in categorias} if categorias else None
    itens: dict[str, Item] = {}

    with caminho.open(encoding="utf-8", newline="") as f:
        for linha in csv.DictReader(f):
            id_item = (linha.get("id_item") or "").strip()
            if not id_item:
                continue
            categoria = (linha.get("categoria") or "").strip()
            if alvo and categoria.upper() not in alvo:
                continue
            itens[id_item] = Item(
                id_item=id_item,
                categoria=categoria,
                grupo_insumo=(linha.get("grupo_insumo") or "").strip(),
                descricao=(linha.get("descricao") or "").strip(),
                termos_busca=[
                    t.strip() for t in (linha.get("termos_busca") or "").split("|")
                    if t.strip()
                ],
                item_curto=(linha.get("item_curto") or "").strip(),
            )

    if alvo and not itens:
        log.warning("nenhum item nas categorias %s em %s", sorted(alvo), caminho)
    return itens


def categorias_conhecidas(caminho: Path = ITENS) -> set[str]:
    return {i.categoria for i in ler_itens(caminho=caminho).values()}


# ---------------------------------------------------------------------------
# Fornecedores
# ---------------------------------------------------------------------------

def ler_fornecedores(
    apenas_aprovados: bool = True,
    caminho: Path = FORNECEDORES,
) -> dict[str, Fornecedor]:
    """fornecedores_master.csv -> {dominio: Fornecedor}.

    Regra inviolável 2 do projeto: nenhum site é coletado sem estar aqui
    com status APROVADO. `apenas_aprovados=True` é o padrão por isso.
    """
    if not caminho.exists():
        raise FileNotFoundError(
            f"{caminho} nao existe. Rode: python -m src.runners.etapa1_validar"
        )

    fornecedores: dict[str, Fornecedor] = {}
    with caminho.open(encoding="utf-8", newline="") as f:
        for linha in csv.DictReader(f):
            dominio = normalizar_dominio(linha.get("dominio") or linha.get("url_base") or "")
            if not dominio:
                continue
            status = _status(linha.get("status"))
            if apenas_aprovados and status is not Status.APROVADO:
                continue
            fornecedores[dominio] = Fornecedor(
                nome=(linha.get("nome") or "").strip(),
                dominio=dominio,
                url_base=(linha.get("url_base") or f"https://{dominio}").strip(),
                uf=(linha.get("uf") or "").strip().upper(),
                cnpj=(linha.get("cnpj") or "").strip() or None,
                cnae_principal=(linha.get("cnae_principal") or "").strip() or None,
                cnaes_secundarios=[
                    c.strip() for c in (linha.get("cnaes_secundarios") or "").split("|")
                    if c.strip()
                ],
                situacao_cadastral=(linha.get("situacao_cadastral") or "").strip() or None,
                eh_atacadista=_bool_do_texto(linha.get("eh_atacadista", "")),
                flag_atacarejo=bool(_bool_do_texto(linha.get("flag_atacarejo", ""))),
                entrega_sul=_entrega_do_texto(linha.get("entrega_sul", "")),
                plataforma=_plataforma(linha.get("plataforma")),
                modo_frete=_modo_frete(linha.get("modo_frete")),
                status=status,
                motivo=(linha.get("motivo") or "").strip(),
            )
    return fornecedores


def gravar_fornecedores(
    fornecedores: list[Fornecedor],
    caminho: Path = FORNECEDORES,
) -> None:
    """Grava o master inteiro, de forma atômica."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = caminho.with_suffix(".csv.tmp")

    with temporario.open("w", newline="", encoding="utf-8") as f:
        escritor = csv.DictWriter(f, fieldnames=COLUNAS_FORNECEDOR)
        escritor.writeheader()
        for forn in sorted(fornecedores, key=lambda x: x.dominio):
            escritor.writerow({
                "dominio": forn.dominio,
                "nome": forn.nome,
                "url_base": forn.url_base,
                "uf": forn.uf,
                "cnpj": forn.cnpj or "",
                "cnae_principal": forn.cnae_principal or "",
                "cnaes_secundarios": "|".join(forn.cnaes_secundarios),
                "situacao_cadastral": forn.situacao_cadastral or "",
                "eh_atacadista": _texto_bool(forn.eh_atacadista),
                "flag_atacarejo": _texto_bool(forn.flag_atacarejo),
                "entrega_sul": _texto_entrega(forn.entrega_sul),
                "plataforma": str(forn.plataforma or ""),
                "modo_frete": str(forn.modo_frete or ""),
                "status": str(forn.status),
                "motivo": forn.motivo,
            })

    os.replace(temporario, caminho)
    log.info("%d fornecedores gravados em %s", len(fornecedores), caminho)


def _status(texto: str | None) -> Status:
    try:
        return Status((texto or "").strip().upper())
    except ValueError:
        return Status.PENDENTE


def _plataforma(texto: str | None) -> Plataforma:
    try:
        return Plataforma((texto or "").strip().lower())
    except ValueError:
        return Plataforma.DESCONHECIDA


def _modo_frete(texto: str | None) -> ModoFrete | None:
    try:
        return ModoFrete((texto or "").strip().upper())
    except ValueError:
        return None
