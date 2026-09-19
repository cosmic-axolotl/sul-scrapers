"""Etapa 3 — preço, frete e print, site por site.

Não procura nada: recebe do plano de coleta a lista de itens que aquele
site tem, com as URLs já descobertas na varredura.

Saída: data/coletas/{dominio}.jsonl — uma linha por registro, gravada
conforme vai coletando. Se o site cair na metade, o rerun pula o que já
existe e continua.

O que conta como "já existe" é a parte delicada. Um registro sem preço e
sem print ocupa o lugar de (item, UF) e nunca mais é refeito: no fim do
prazo a planilha tem a linha, a linha não tem preço, e ninguém sabe por
quê. Aqui, retomar só pula registro COMPLETO — preço, frete resolvido e
print no disco. O resto é lixo de uma execução interrompida e vai ser
refeito.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from src.adapters.base import Executor
from src.core import frete
from src.core.http import ErroHTTP, SiteBloqueado
from src.core.log import obter
from src.export.captura import PrintIndisponivel
from src.models import CEPS_SUL, Coleta, Item
from src.runners.etapa2_varredura import ler_achados, registrar_bloqueio

log = obter(__name__)

DESTINO = Path("data/coletas")
PRINTS = Path("data/output/prints")


# ---------------------------------------------------------------------------
# Retomada
# ---------------------------------------------------------------------------

def registro_completo(r: dict) -> bool:
    """Um registro serve para a entrega? Preço, frete decidido e print.

    `valor_frete` pode ser None legitimamente (frete sob consulta), mas
    aí `obs_frete` tem que dizer o que houve. Preço nulo e print ausente
    não têm leitura legítima nenhuma.
    """
    if not r.get("id_item") or not r.get("uf"):
        return False
    if r.get("preco_final") in (None, "") and r.get("preco_produto") in (None, ""):
        return False
    if r.get("valor_frete") in (None, "") and not (r.get("obs_frete") or "").strip():
        return False
    caminho = (r.get("caminho_print") or "").strip()
    return bool(caminho) and Path(caminho).exists()


def ler_registros(caminho: Path) -> tuple[list[dict], int]:
    """Lê o .jsonl tolerando a última linha truncada.

    Um processo morto no meio de um write deixa meia linha de JSON. A
    versão anterior estourava ali e tratava tudo dali para a frente como
    inexistente -- o que, num arquivo com a linha quebrada no meio,
    escondia tudo que vinha depois.
    """
    if not caminho.exists():
        return [], 0

    registros: list[dict] = []
    descartadas = 0
    for numero, linha in enumerate(
        caminho.read_text(encoding="utf-8", errors="replace").splitlines(), 1
    ):
        if not linha.strip():
            continue
        try:
            registro = json.loads(linha)
        except ValueError:
            descartadas += 1
            log.warning("%s: linha %d ilegivel, descartada", caminho.name, numero)
            continue
        if isinstance(registro, dict):
            registros.append(registro)
        else:
            descartadas += 1
    return registros, descartadas


def sanear(caminho: Path) -> list[dict]:
    """Reescreve o arquivo só com o que presta, e devolve o que ficou.

    Precisa ser feito ANTES do primeiro append: abrir em modo "a" depois
    de uma linha truncada cola o registro novo no fim da linha quebrada e
    corrompe os dois.
    """
    registros, descartadas = ler_registros(caminho)
    completos = [r for r in registros if registro_completo(r)]
    incompletos = len(registros) - len(completos)

    if not descartadas and not incompletos:
        return completos

    temporario = caminho.with_suffix(".jsonl.tmp")
    with temporario.open("w", encoding="utf-8") as f:
        for r in completos:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    os.replace(temporario, caminho)

    log.warning("%s: %d linhas ilegiveis e %d registros incompletos removidos; "
                "serao coletados de novo", caminho.name, descartadas, incompletos)
    return completos


def ja_coletados(caminho: Path) -> set[tuple[str, str]]:
    """(id_item, uf) já gravados E completos, para o rerun não refazer."""
    registros, _ = ler_registros(caminho)
    return {
        (r["id_item"], r["uf"]) for r in registros if registro_completo(r)
    }


# ---------------------------------------------------------------------------
# Coleta
# ---------------------------------------------------------------------------

def coletar_site(executor: Executor, itens: list[Item]) -> dict:
    """Coleta UM site inteiro. O executor chega aberto, e é reaproveitado
    pelos N itens da loja — é aqui que está a economia do projeto.

    Dois níveis: uma passada por item (preço e desconto, que não mudam
    entre UFs) e três por item (frete e print, que mudam).
    """
    dominio = executor.fornecedor.dominio
    DESTINO.mkdir(parents=True, exist_ok=True)
    arquivo = DESTINO / f"{dominio}.jsonl"

    completos = sanear(arquivo)
    feitos = {(r["id_item"], r["uf"]) for r in completos}

    # A URL de cada item veio da varredura. Só "aceito" entra na coleta;
    # o que ficou em revisão espera decisão humana.
    achados = {
        a["id_item"]: a
        for a in ler_achados(dominio)
        if a.get("classificacao", "aceito") == "aceito"
    }

    gravados = falhas = sem_url = 0

    with arquivo.open("a", encoding="utf-8") as saida:
        for item in itens:
            achado = achados.get(item.id_item)
            if achado is None:
                sem_url = sem_url + 1
                log.warning("%s: item %s esta no plano mas nao tem URL nos achados",
                            dominio, item.id_item)
                continue

            pendentes = [uf for uf in CEPS_SUL if (item.id_item, uf) not in feitos]
            if not pendentes:
                continue

            url = achado["url_produto"]

            # Uma requisição de ficha por item, não uma por UF: preço e
            # desconto não mudam de estado para estado.
            try:
                produto = executor.detalhar(url)
            except SiteBloqueado as e:
                registrar_bloqueio(dominio, str(e))
                log.error("%s: bloqueado na coleta (%s)", dominio, e)
                return {"itens": len(itens), "gravados": gravados, "bloqueado": True}
            except (ErroHTTP, NotImplementedError) as e:
                falhas += 1
                log.warning("%s: nao consegui detalhar %s (%s: %s)",
                            dominio, item.id_item, type(e).__name__, e)
                continue

            for uf in pendentes:
                try:
                    registro = _coletar_uf(executor, item, produto, achado, uf, dominio)
                except SiteBloqueado as e:
                    registrar_bloqueio(dominio, str(e))
                    log.error("%s: bloqueado na coleta (%s)", dominio, e)
                    return {"itens": len(itens), "gravados": gravados, "bloqueado": True}
                except (ErroHTTP, PrintIndisponivel, NotImplementedError) as e:
                    # Sem print o registro não serve para a entrega, e não
                    # é gravado: a retomada tenta de novo na próxima rodada.
                    falhas += 1
                    log.warning("%s: item %s/%s falhou (%s: %s)",
                                dominio, item.id_item, uf, type(e).__name__, e)
                    continue

                saida.write(json.dumps(registro, ensure_ascii=False, default=str) + "\n")
                saida.flush()  # o rerun depende de o que está no disco ser verdade
                gravados += 1

    return {
        "itens": len(itens),
        "gravados": gravados,
        "falhas": falhas,
        "sem_url": sem_url,
    }


def _coletar_uf(executor, item: Item, produto, achado: dict, uf: str, dominio: str) -> dict:
    """Frete e print de uma UF. O print sai depois do frete, de propósito.

    A ordem não é detalhe: o print precisa mostrar preço e frete na mesma
    imagem, e o frete só aparece na página depois do CEP preenchido.
    """
    url = achado["url_produto"]
    valor_frete, obs_frete = frete.cotar_produto(executor, url, uf, produto)

    destino = caminho_print(item.categoria, item.id_item, dominio, uf)
    destino.parent.mkdir(parents=True, exist_ok=True)
    caminho = executor.capturar_print(url, CEPS_SUL[uf], str(destino))

    preco_final = produto.preco
    preco_produto = produto.preco_lista or produto.preco
    desconto = None
    obs_desconto = ""
    if produto.preco_lista and produto.preco and produto.preco_lista > produto.preco:
        desconto = round(produto.preco_lista - produto.preco, 2)
        obs_desconto = f"preco de {produto.preco_lista:.2f} por {produto.preco:.2f}"

    coleta = Coleta(
        id_item=item.id_item,
        dominio=dominio,
        uf=uf,
        url_produto=url,
        titulo_encontrado=produto.titulo,
        preco_produto=preco_produto,
        valor_desconto=desconto,
        obs_desconto=obs_desconto,
        preco_final=preco_final,
        valor_frete=valor_frete,
        obs_frete=obs_frete,
        caminho_print=str(caminho or destino),
        score_match=_numero(achado.get("score_match")),
        coletado_em=datetime.now(),
    )
    registro = asdict(coleta)
    registro["coletado_em"] = coleta.coletado_em.isoformat(timespec="seconds")
    registro["categoria"] = item.categoria  # o montador precisa, e sai de graça
    return registro


def _numero(valor) -> float:
    try:
        return float(str(valor).replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


def caminho_print(categoria: str, id_item: str, dominio: str, uf: str) -> Path:
    """O montador deriva este mesmo caminho das colunas da linha —
    nenhuma amarração manual entre imagem e planilha."""
    return PRINTS / categoria / f"{id_item}__{dominio}__{uf}.png"
