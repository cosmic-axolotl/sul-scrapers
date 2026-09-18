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
"""

from __future__ import annotations

import csv
import hashlib
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from src.core.http import Cliente
from src.models import Fornecedor, Item

PLANO = Path("data/interim/plano_coleta.csv")
FORNECEDORES = Path("data/interim/fornecedores_master.csv")
ITENS = Path("data/interim/itens.csv")

MAX_SITES_PARALELOS = 8


# ---------------------------------------------------------------------------
# Planejamento
# ---------------------------------------------------------------------------

def carregar_itens(categorias: list[str] | None = None) -> dict[str, Item]:
    """TODO: ler itens.csv. Se `categorias` vier, filtra por elas."""
    raise NotImplementedError


def carregar_fornecedores(apenas_aprovados: bool = True) -> dict[str, Fornecedor]:
    """TODO: ler fornecedores_master.csv, indexado por domínio.

    Nenhum site entra na coleta sem estar aqui com status APROVADO.
    """
    raise NotImplementedError


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


def montar_lotes(
    categorias: list[str] | None = None,
    sites: list[str] | None = None,
    shard: int = 1,
    total_shards: int = 1,
    limite: int | None = None,
) -> dict[str, list[str]]:
    """O coração do orquestrador: {dominio: [id_item, ...]}.

    Lê o plano de coleta (que já diz quais itens existem em cada site),
    aplica os filtros de categoria e/ou site, e devolve o trabalho
    agrupado por domínio.

    Note que o filtro de categoria some depois desta função: daqui para
    baixo ninguém mais sabe o que é categoria, só site e lista de itens.
    """
    itens = carregar_itens(categorias)
    if limite:
        # Piloto: corta a lista para descobrir problema barato antes de
        # soltar a categoria inteira.
        itens = dict(list(itens.items())[:limite])

    lotes: dict[str, list[str]] = defaultdict(list)

    with PLANO.open(encoding="utf-8") as f:
        for linha in csv.DictReader(f):
            dominio = linha["dominio"]
            if sites and dominio not in sites:
                continue
            if not pertence_ao_shard(dominio, shard, total_shards):
                continue
            for id_bruto in linha["ids_itens"].split("|"):
                id_item = id_bruto.strip()
                if id_item in itens:
                    lotes[dominio].append(id_item)

    # Sites com mais itens primeiro: falha cedo onde dói mais.
    return dict(sorted(lotes.items(), key=lambda kv: -len(kv[1])))


# ---------------------------------------------------------------------------
# Execução
# ---------------------------------------------------------------------------

def rodar_site(dominio: str, ids_itens: list[str], fase: str) -> dict:
    """Roda UM site inteiro, em UM processo. Ponto de entrada do worker.

    Toda a economia do projeto está nestas linhas: a sessão é aberta
    uma vez e reaproveitada pelos N itens daquele site.
    """
    from src.adapters.registro import criar

    fornecedores = carregar_fornecedores()
    fornecedor = fornecedores[dominio]
    itens = carregar_itens()

    with Cliente() as cliente, criar(fornecedor, cliente) as executor:
        if fase == "varredura":
            from src.runners.etapa2_varredura import varrer_site

            return varrer_site(executor, [itens[i] for i in ids_itens])
        if fase == "coleta":
            from src.runners.etapa3_coletar import coletar_site

            return coletar_site(executor, [itens[i] for i in ids_itens])
        raise ValueError(f"fase desconhecida: {fase}")


def orquestrar(
    fase: str,
    categorias: list[str] | None = None,
    sites: list[str] | None = None,
    paralelos: int = MAX_SITES_PARALELOS,
    shard: int = 1,
    total_shards: int = 1,
    limite: int | None = None,
) -> None:
    """Dispara um processo por site, N sites ao mesmo tempo.

    Por ser um processo por domínio, o rate limit por domínio se
    resolve por construção: dois workers nunca tocam a mesma loja.
    """
    lotes = montar_lotes(categorias, sites, shard, total_shards, limite)
    print(
        f"[orquestrador] shard {shard}/{total_shards} — "
        f"{len(lotes)} sites, {sum(len(v) for v in lotes.values())} pares site-item"
    )

    with ProcessPoolExecutor(max_workers=paralelos) as pool:
        futuros = {
            pool.submit(rodar_site, dominio, ids, fase): dominio
            for dominio, ids in lotes.items()
        }
        for futuro in as_completed(futuros):
            dominio = futuros[futuro]
            try:
                resultado = futuro.result()
                print(f"[ok] {dominio}: {resultado}")
            except Exception as e:  # um site que quebra não derruba os outros
                print(f"[erro] {dominio}: {e}")
                # TODO: registrar em data/raw/bloqueadas.csv e avisar o grupo


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="Orquestrador do pipeline FNDE Sul")
    p.add_argument("fase", choices=["varredura", "coleta"])
    p.add_argument("--categoria", action="append", dest="categorias")
    p.add_argument("--site", action="append", dest="sites")
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
    orquestrar(a.fase, a.categorias, a.sites, a.paralelos, shard, total_shards, a.limite)
