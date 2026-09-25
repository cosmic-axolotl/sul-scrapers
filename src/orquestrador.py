"""Orquestrador: decide QUEM roda O QUÊ, e em que agrupamento.

A decisão de projeto que este arquivo materializa:

    a categoria SELECIONA o trabalho; o site AGRUPA o trabalho.

Um orquestrador por categoria que chama o scraper do site item a item
funciona, mas paga o custo da sessão várias vezes. Uma loja com 61
itens espalhados por 3 categorias vira 3 sessões de navegador em vez
de 1 — e, pior, as 3 rodam em paralelo contra o mesmo domínio, furando
o rate limit sem ninguém perceber.

Aqui a categoria continua sendo como a equipe divide o trabalho
("hoje eu toco UTENSILIOS"), mas depois de selecionar os itens o
orquestrador reagrupa por domínio antes de instanciar qualquer
executor. Um processo por site, sempre.

## As duas fases têm planos diferentes, e é de propósito

A varredura existe para descobrir quem vende o quê. A coleta usa essa
descoberta. Fazer as duas lerem `plano_coleta.csv` criava uma volta
fechada: para varrer era preciso um plano que só existe depois de
varrer, e numa base nova nenhuma das duas rodava.

    varredura -> plano de BUSCA:  todo site aprovado x todo item da
                 categoria. Não depende de nada além do master.
    coleta    -> plano de COLETA: plano_coleta.csv, gerado pela etapa
                 2 a partir dos achados da varredura.

## Dois canais: atacado (padrão) e --varejista

    padrão       itens.csv (132)       x  todo APROVADO, menos quem só
                                          entrou pela exceção de varejo
    --varejista  itens_varejo.csv (31) x  só CNAE principal 47.53-9 ou
                                          47.59-8

O canal vale para as duas fases. O critério de site mora na regra de
CNAE (src/validacao/classificar_cnae.py), não aqui: quem decide o que é
varejo é quem decide o que é aprovado.
"""

from __future__ import annotations

import csv
import hashlib
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from src.core import tabelas
from src.core.http import Cliente
from src.core.log import obter
from src.models import Fornecedor, Item
from src.validacao.classificar_cnae import eh_varejista, so_varejista

log = obter(__name__)

PLANO = Path("data/interim/plano_coleta.csv")
FORNECEDORES = tabelas.FORNECEDORES
ITENS = tabelas.ITENS
ITENS_VAREJO = Path("data/interim/itens_varejo.csv")

MAX_SITES_PARALELOS = 8


# ---------------------------------------------------------------------------
# Planejamento
# ---------------------------------------------------------------------------

def carregar_itens(
    categorias: list[str] | None = None,
    varejista: bool = False,
) -> dict[str, Item]:
    """Lê itens.csv, ou itens_varejo.csv no canal varejista."""
    if not varejista:
        return tabelas.ler_itens(categorias)
    if not ITENS_VAREJO.exists():
        raise FileNotFoundError(
            f"{ITENS_VAREJO} nao existe. Gere com:\n"
            f"  python -m src.runners.etapa0_limpar_itens "
            f'--entrada "data/raw/Lista de Equipamentos_Varejo_Sul xlsx.xlsx" '
            f"--saida {ITENS_VAREJO}"
        )
    return tabelas.ler_itens(categorias, caminho=ITENS_VAREJO)


def carregar_fornecedores(apenas_aprovados: bool = True) -> dict[str, Fornecedor]:
    """Lê fornecedores_master.csv, indexado por domínio.

    Nenhum site entra na coleta sem estar aqui com status APROVADO.
    """
    return tabelas.ler_fornecedores(apenas_aprovados)


def do_canal(fornecedor: Fornecedor, varejista: bool) -> bool:
    """Este fornecedor APROVADO participa deste canal?

    padrão: todos, menos quem só foi aprovado pela exceção de varejo.
    Aprovado sem CNAE nenhum (decisão humana herdada da planilha) fica
    no padrão -- não há CNAE que o tire de lá.
    --varejista: só CNAE principal 47.53-9 ou 47.59-8.
    """
    if varejista:
        return eh_varejista(fornecedor.cnae_principal)
    return not so_varejista(fornecedor.cnae_principal, fornecedor.cnaes_secundarios)


def pertence_ao_shard(dominio: str, shard: int, total: int) -> bool:
    """Particiona a LISTA DE SITES, nunca a lista de itens.

    Fatiar por quantidade de itens faria as máquinas baterem nas mesmas
    lojas, já que os itens de uma categoria se espalham por todos os
    sites. Fatiando por domínio, cada máquina é dona exclusiva do seu
    conjunto e o limite por domínio continua valendo.

    O hash é determinístico e estável entre máquinas, então ninguém
    precisa combinar nada com ninguém.
    """
    if total <= 1:
        return True
    digest = hashlib.sha256(dominio.encode()).digest()
    return (int.from_bytes(digest[:4], "big") % total) == (shard - 1)


def _selecionar_itens(
    categorias: list[str] | None,
    limite: int | None,
    varejista: bool = False,
) -> dict[str, Item]:
    itens = carregar_itens(categorias, varejista)
    if limite:
        # Piloto: corta a lista para descobrir problema barato antes de
        # soltar a categoria inteira.
        itens = dict(list(itens.items())[:limite])
    return itens


def montar_lotes_varredura(
    categorias: list[str] | None = None,
    sites: list[str] | None = None,
    shard: int = 1,
    total_shards: int = 1,
    limite: int | None = None,
    varejista: bool = False,
) -> dict[str, list[str]]:
    """Plano de BUSCA: {dominio: [id_item, ...]}, todo site x todo item.

    Não lê `plano_coleta.csv` — não pode, é ele quem produz o insumo
    desse arquivo. A única entrada é o master de fornecedores, que a
    etapa 1 já produziu.
    """
    itens = _selecionar_itens(categorias, limite, varejista)
    fornecedores = carregar_fornecedores(apenas_aprovados=True)

    lotes: dict[str, list[str]] = {}
    for dominio, fornecedor in fornecedores.items():
        if not do_canal(fornecedor, varejista):
            continue
        if sites and dominio not in sites:
            continue
        if not pertence_ao_shard(dominio, shard, total_shards):
            continue
        lotes[dominio] = list(itens)

    if not lotes:
        log.warning(
            "nenhum site aprovado nesta fatia (shard %d/%d, canal %s, filtro de site: %s)",
            shard, total_shards, "varejista" if varejista else "padrão",
            sites or "nenhum",
        )
    return lotes


def montar_lotes_coleta(
    categorias: list[str] | None = None,
    sites: list[str] | None = None,
    shard: int = 1,
    total_shards: int = 1,
    limite: int | None = None,
    varejista: bool = False,
) -> dict[str, list[str]]:
    """Plano de COLETA: {dominio: [id_item, ...]}, do plano_coleta.csv.

    O plano já diz quais itens existem em cada site, com a URL
    descoberta na varredura. Aqui só se aplicam os filtros.
    """
    if not PLANO.exists():
        raise FileNotFoundError(
            f"{PLANO} nao existe. A coleta depende da varredura: rode "
            "`python -m src.orquestrador varredura ...` e depois "
            "`python -m src.runners.etapa2_plano`."
        )

    itens = _selecionar_itens(categorias, limite, varejista)
    # O plano vem dos achados de TODAS as varreduras. O canal filtra de
    # novo aqui: sem isso, o achado de uma varredura --varejista entraria
    # na coleta padrão, e vice-versa.
    do_canal_aprovados = {
        d for d, f in carregar_fornecedores(apenas_aprovados=True).items()
        if do_canal(f, varejista)
    }
    lotes: dict[str, list[str]] = defaultdict(list)

    with PLANO.open(encoding="utf-8", newline="") as f:
        for linha in csv.DictReader(f):
            dominio = (linha.get("dominio") or "").strip()
            if not dominio or dominio not in do_canal_aprovados:
                continue
            if sites and dominio not in sites:
                continue
            if not pertence_ao_shard(dominio, shard, total_shards):
                continue
            for id_bruto in (linha.get("ids_itens") or "").split("|"):
                id_item = id_bruto.strip()
                if id_item in itens:
                    lotes[dominio].append(id_item)

    return {d: ids for d, ids in lotes.items() if ids}


def montar_lotes(
    fase: str,
    categorias: list[str] | None = None,
    sites: list[str] | None = None,
    shard: int = 1,
    total_shards: int = 1,
    limite: int | None = None,
    varejista: bool = False,
) -> dict[str, list[str]]:
    """O coração do orquestrador: {dominio: [id_item, ...]}.

    Note que o filtro de categoria some depois desta função: daqui para
    baixo ninguém mais sabe o que é categoria, só site e lista de itens.
    """
    montar = {
        "varredura": montar_lotes_varredura,
        "coleta": montar_lotes_coleta,
    }.get(fase)
    if montar is None:
        raise ValueError(f"fase desconhecida: {fase}")

    lotes = montar(categorias, sites, shard, total_shards, limite, varejista)
    # Sites com mais itens primeiro: falha cedo onde dói mais.
    return dict(sorted(lotes.items(), key=lambda kv: -len(kv[1])))


# ---------------------------------------------------------------------------
# Execução
# ---------------------------------------------------------------------------

def rodar_site(dominio: str, ids_itens: list[str], fase: str,
               varejista: bool = False) -> dict:
    """Roda UM site inteiro, em UM processo. Ponto de entrada do worker.

    Toda a economia do projeto está nestas linhas: a sessão é aberta
    uma vez e reaproveitada pelos N itens daquele site.

    `varejista` tem que atravessar a fronteira do processo: o worker
    recarrega os itens do disco, e sem o canal leria o itens.csv padrão.
    Hoje os 31 itens de varejo são linhas idênticas às de lá, então daria
    certo por coincidência -- até alguém mudar uma descrição de um lado só.
    """
    from src.adapters.registro import criar

    fornecedores = carregar_fornecedores()
    fornecedor = fornecedores[dominio]
    itens = carregar_itens(varejista=varejista)
    lote = [itens[i] for i in ids_itens if i in itens]

    # O cache serve à varredura e atrapalha a coleta: preço e frete da
    # entrega são de hoje, não da semana passada.
    cliente = Cliente.para_varredura() if fase == "varredura" else Cliente.para_coleta()

    with cliente, criar(fornecedor, cliente) as executor:
        if fase == "varredura":
            from src.runners.etapa2_varredura import varrer_site

            return varrer_site(executor, lote)
        if fase == "coleta":
            from src.runners.etapa3_coletar import coletar_site

            return coletar_site(executor, lote)
        raise ValueError(f"fase desconhecida: {fase}")


def orquestrar(
    fase: str,
    categorias: list[str] | None = None,
    sites: list[str] | None = None,
    paralelos: int = MAX_SITES_PARALELOS,
    shard: int = 1,
    total_shards: int = 1,
    limite: int | None = None,
    varejista: bool = False,
) -> dict:
    """Dispara um processo por site, N sites ao mesmo tempo.

    Por ser um processo por domínio, o rate limit por domínio se
    resolve por construção: dois workers nunca tocam a mesma loja.
    """
    lotes = montar_lotes(fase, categorias, sites, shard, total_shards, limite,
                         varejista)
    print(
        f"[orquestrador] {fase}{' --varejista' if varejista else ''} — "
        f"shard {shard}/{total_shards} — "
        f"{len(lotes)} sites, {sum(len(v) for v in lotes.values())} pares site-item"
    )

    resumo = {"sites": len(lotes), "ok": 0, "erro": 0}
    if not lotes:
        return resumo

    with ProcessPoolExecutor(max_workers=paralelos) as pool:
        futuros = {
            pool.submit(rodar_site, dominio, ids, fase, varejista): dominio
            for dominio, ids in lotes.items()
        }
        for futuro in as_completed(futuros):
            dominio = futuros[futuro]
            try:
                resultado = futuro.result()
                resumo["ok"] += 1
                print(f"[ok] {dominio}: {resultado}")
            except Exception as e:  # um site que quebra não derruba os outros
                resumo["erro"] += 1
                log.exception("%s quebrou na fase %s", dominio, fase)
                print(f"[erro] {dominio}: {type(e).__name__}: {e}")
                _registrar_falha(dominio, fase, e)

    print(f"[orquestrador] {resumo['ok']} sites ok, {resumo['erro']} com erro")
    return resumo


def _registrar_falha(dominio: str, fase: str, erro: Exception) -> None:
    """Site que quebrou vira linha em data/raw/falhas.csv, não só log."""
    from datetime import datetime

    caminho = Path("data/raw/falhas.csv")
    caminho.parent.mkdir(parents=True, exist_ok=True)
    novo = not caminho.exists()
    with caminho.open("a", newline="", encoding="utf-8") as f:
        escritor = csv.writer(f)
        if novo:
            escritor.writerow(["dominio", "fase", "quando", "erro", "mensagem"])
        escritor.writerow([
            dominio, fase, datetime.now().isoformat(timespec="seconds"),
            type(erro).__name__, str(erro)[:300],
        ])


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="Orquestrador do pipeline FNDE Sul")
    p.add_argument("fase", choices=["varredura", "coleta"])
    p.add_argument("--categoria", action="append", dest="categorias")
    p.add_argument("--site", action="append", dest="sites")
    p.add_argument(
        "--varejista",
        action="store_true",
        help="canal varejista: só itens de itens_varejo.csv e só sites com "
             "CNAE principal 47.53-9 ou 47.59-8",
    )
    p.add_argument("--paralelos", type=int, default=MAX_SITES_PARALELOS)
    p.add_argument(
        "--shard",
        default="1/1",
        help="fatia desta máquina, ex. 2/3. Particiona os SITES, não os itens.",
    )
    p.add_argument(
        "--limite",
        type=int,
        help="roda só os N primeiros itens. Para pilotar antes de disparar tudo.",
    )
    a = p.parse_args()

    shard, total_shards = (int(x) for x in a.shard.split("/"))
    try:
        orquestrar(a.fase, a.categorias, a.sites, a.paralelos, shard, total_shards,
                   a.limite, a.varejista)
    except FileNotFoundError as e:
        # Falta de arquivo é erro de ordem das etapas, não defeito de
        # código: a mensagem já diz o que rodar, o traceback só atrapalha.
        raise SystemExit(f"[orquestrador] {e}") from None
