"""Etapa 2 — a loja X tem algo parecido com o item Y?

Sem preço, sem frete, sem detalhe: guarda o link e segue. Separar isso
da coleta é o que permite rodar a varredura inteira em poucas horas e
descobrir cedo quais itens ninguém vende.

Saída: data/interim/achados/{dominio}.csv — um arquivo por site.

O arquivo é acumulado, não sobrescrito. Uma loja de utensílios costuma
vender EPI também, e as duas categorias são varridas em dias diferentes
por pessoas diferentes: gravar o arquivo inteiro a cada rodada fazia a
segunda apagar o resultado da primeira sem aviso nenhum.

A regra do acúmulo: sai quem foi varrido agora, fica quem não foi. Item
varrido de novo tem o resultado novo; item que não entrou nesta rodada
continua como estava.
"""

from __future__ import annotations

import csv
import os
from dataclasses import asdict, fields
from datetime import datetime
from pathlib import Path

from src.adapters.base import Executor
from src.core import matching
from src.core.http import ErroHTTP, SiteBloqueado
from src.core.log import obter
from src.models import Achado, Item

log = obter(__name__)

DESTINO = Path("data/interim/achados")
BLOQUEADAS = Path("data/raw/bloqueadas.csv")

COLUNAS = [c.name for c in fields(Achado)]


def varrer_site(executor: Executor, itens: list[Item]) -> dict:
    """Varre UM site atrás de TODOS os itens do seu lote.

    O executor já chegou aqui aberto, instanciado uma vez pelo
    orquestrador. Esta função nunca abre sessão.
    """
    achados: list[Achado] = []
    dominio = executor.fornecedor.dominio
    varridos: list[str] = []
    revisar = falhas = 0

    for item in itens:
        melhor: tuple[matching.Avaliacao, object] | None = None

        try:
            for termo in item.termos_busca or matching.gerar_termos(item):
                for produto in executor.buscar(termo):
                    avaliacao = matching.avaliar(item.descricao, produto.titulo)
                    if melhor is None or avaliacao.score > melhor[0].score:
                        melhor = (avaliacao, produto)
                # Termos vão do mais específico ao mais genérico: se o
                # específico já deu match bom, não precisa dos outros.
                if melhor and melhor[0].classificacao == "aceito":
                    break
        except SiteBloqueado as e:
            # O site inteiro nos barrou. Insistir nos outros itens só
            # queima IP: grava o que já achou e sai.
            registrar_bloqueio(dominio, str(e))
            log.error("%s: bloqueado durante a varredura (%s)", dominio, e)
            gravar(dominio, achados, varridos)
            return {
                "itens_buscados": len(varridos),
                "achados": len(achados),
                "bloqueado": True,
            }
        except ErroHTTP as e:
            falhas += 1
            log.warning("%s: item %s falhou (%s)", dominio, item.id_item, type(e).__name__)
            continue

        varridos.append(item.id_item)

        if melhor and melhor[0].classificacao != "descartado":
            avaliacao, produto = melhor
            if avaliacao.classificacao == "revisar":
                revisar += 1
                log.info("%s: item %s vai para revisao -- %s",
                         dominio, item.id_item, avaliacao.motivo)
            achados.append(
                Achado(
                    id_item=item.id_item,
                    dominio=dominio,
                    url_produto=produto.url,
                    titulo_encontrado=produto.titulo,
                    score_match=avaliacao.score_normalizado,
                    preco_indicativo=produto.preco,
                    classificacao=avaliacao.classificacao,
                    motivo_match=avaliacao.motivo,
                    sku=produto.sku,
                )
            )

    gravar(dominio, achados, varridos)
    return {
        "itens_buscados": len(varridos),
        "achados": len(achados),
        "revisar": revisar,
        "falhas": falhas,
    }


def ler_achados(dominio: str) -> list[dict]:
    """O que já estava gravado para este site. Lista vazia se não há nada."""
    caminho = DESTINO / f"{dominio}.csv"
    if not caminho.exists() or caminho.stat().st_size == 0:
        return []
    with caminho.open(encoding="utf-8", newline="") as f:
        return [linha for linha in csv.DictReader(f) if linha.get("id_item")]


def gravar(dominio: str, achados: list[Achado], itens_varridos: list[str]) -> None:
    """Funde o resultado desta rodada com o que já havia no arquivo.

    `itens_varridos` é o que dá sentido à fusão: sem essa lista não há
    como distinguir "este item não foi procurado agora" de "este item
    foi procurado e não existe mais", e os dois casos pedem coisas
    opostas (preservar e apagar, respectivamente).
    """
    DESTINO.mkdir(parents=True, exist_ok=True)
    caminho = DESTINO / f"{dominio}.csv"

    varridos = set(itens_varridos)
    preservados = [a for a in ler_achados(dominio) if a["id_item"] not in varridos]
    novos = [{k: _texto(v) for k, v in asdict(a).items()} for a in achados]

    linhas = preservados + novos
    linhas.sort(key=lambda a: (a.get("id_item", ""), a.get("url_produto", "")))

    # Grava em arquivo temporário e troca no fim: uma interrupção no meio
    # da escrita não deixa o arquivo pela metade.
    temporario = caminho.with_suffix(".csv.tmp")
    with temporario.open("w", newline="", encoding="utf-8") as f:
        escritor = csv.DictWriter(f, fieldnames=COLUNAS, extrasaction="ignore")
        escritor.writeheader()  # sempre, mesmo sem achado: cabeçalho é o
        escritor.writerows(linhas)  # que diz "varri este site e não achei"
    os.replace(temporario, caminho)

    log.info("%s: %d achados nesta rodada, %d preservados, %d no arquivo",
             dominio, len(novos), len(preservados), len(linhas))


def registrar_bloqueio(dominio: str, motivo: str) -> None:
    """Uma linha em data/raw/bloqueadas.csv. O grupo lê e decide o que fazer."""
    BLOQUEADAS.parent.mkdir(parents=True, exist_ok=True)
    novo = not BLOQUEADAS.exists()
    with BLOQUEADAS.open("a", newline="", encoding="utf-8") as f:
        escritor = csv.writer(f)
        if novo:
            escritor.writerow(["dominio", "quando", "motivo"])
        escritor.writerow([dominio, datetime.now().isoformat(timespec="seconds"), motivo])


def _texto(valor) -> str:
    if isinstance(valor, datetime):
        return valor.isoformat(timespec="seconds")
    return "" if valor is None else str(valor)
