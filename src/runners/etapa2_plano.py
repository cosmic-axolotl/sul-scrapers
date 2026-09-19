"""Gera o plano de coleta: a planilha da Etapa 2 virada do avesso.

A planilha por categoria (item nas linhas, fornecedores nas colunas) é
para gente ler. O que a Etapa 3 consome é uma linha por site com a
lista de itens que ele tem — assim cada site recebe só o que já se
sabe que ele vende, com a URL pronta desde a varredura.

Entrada: data/interim/achados/*.csv + fornecedores_master.csv
Saída:   data/interim/plano_coleta.csv
         data/interim/revisar.csv            (o que precisa de olho humano)
         data/output/cobertura_{CATEGORIA}.xlsx (a visão por categoria)

Este arquivo é gerado, nunca editado à mão. Regere toda vez que a
cobertura mudar.

Só entra no plano o achado classificado como "aceito". O que ficou em
"revisar" — medida divergente, embalagem que o título não confirma — vai
para revisar.csv e só entra na coleta depois que alguém olhar. Mandar
"revisar" direto para a coleta é o mesmo que não ter revisão.
"""

from __future__ import annotations

import csv
import os
from collections import defaultdict
from pathlib import Path

from src.core import tabelas
from src.core.log import obter

log = obter(__name__)

ACHADOS = Path("data/interim/achados")
SAIDA = Path("data/interim/plano_coleta.csv")
REVISAR = Path("data/interim/revisar.csv")
COBERTURA = Path("data/output")
COLUNAS = ["dominio", "uf", "plataforma", "modo_frete", "qtd_itens", "ids_itens"]

ALVO_FONTES_POR_ITEM = 5


def consolidar_achados() -> list[dict]:
    """Todos os achados/*.csv, deduplicados por (id_item, dominio, url_produto).

    O mesmo produto pode casar com dois itens parecidos da lista, e a
    mesma varredura pode ter rodado duas vezes: fica o de maior score.
    """
    if not ACHADOS.exists():
        log.warning("%s nao existe -- a varredura ja rodou?", ACHADOS)
        return []

    melhores: dict[tuple[str, str, str], dict] = {}
    arquivos = sorted(ACHADOS.glob("*.csv"))

    for arquivo in arquivos:
        if arquivo.stat().st_size == 0:
            continue
        with arquivo.open(encoding="utf-8", newline="") as f:
            for linha in csv.DictReader(f):
                id_item = (linha.get("id_item") or "").strip()
                dominio = (linha.get("dominio") or "").strip()
                if not id_item or not dominio:
                    continue
                linha["score_match"] = _numero(linha.get("score_match"))
                linha["preco_indicativo"] = _numero(linha.get("preco_indicativo"))
                linha.setdefault("classificacao", "aceito")
                chave = (id_item, dominio, (linha.get("url_produto") or "").strip())
                atual = melhores.get(chave)
                if atual is None or linha["score_match"] > atual["score_match"]:
                    melhores[chave] = linha

    log.info("%d arquivos de achados, %d registros unicos", len(arquivos), len(melhores))
    return list(melhores.values())


def gerar_plano() -> None:
    """Agrupa os achados por domínio e cruza com fornecedores_master.csv."""
    achados = consolidar_achados()
    fornecedores = tabelas.ler_fornecedores(apenas_aprovados=True)

    aceitos = [a for a in achados if a.get("classificacao") == "aceito"]
    pendentes = [a for a in achados if a.get("classificacao") != "aceito"]

    # Regra inviolável 2: site que não está aprovado no master não é
    # coletado, mesmo que a varredura tenha achado produto nele.
    por_dominio: dict[str, set[str]] = defaultdict(set)
    fora = set()
    for a in aceitos:
        dominio = a["dominio"]
        if dominio not in fornecedores:
            fora.add(dominio)
            continue
        por_dominio[dominio].add(a["id_item"])

    if fora:
        log.warning("%d dominios com achados ficaram de fora por nao estarem "
                    "APROVADOS no master: %s", len(fora), ", ".join(sorted(fora)[:5]))

    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    temporario = SAIDA.with_suffix(".csv.tmp")
    with temporario.open("w", newline="", encoding="utf-8") as f:
        escritor = csv.DictWriter(f, fieldnames=COLUNAS)
        escritor.writeheader()
        for dominio, ids in sorted(por_dominio.items(), key=lambda kv: -len(kv[1])):
            forn = fornecedores[dominio]
            escritor.writerow({
                "dominio": dominio,
                "uf": forn.uf,
                "plataforma": str(forn.plataforma or ""),
                "modo_frete": str(forn.modo_frete or ""),
                "qtd_itens": len(ids),
                "ids_itens": "|".join(sorted(ids)),
            })
    os.replace(temporario, SAIDA)

    _gravar_revisar(pendentes)
    log.info("plano gravado: %d sites, %d pares site-item",
             len(por_dominio), sum(len(v) for v in por_dominio.values()))


def _gravar_revisar(pendentes: list[dict]) -> None:
    """O que o matching não aprovou sozinho. Uma pessoa decide."""
    REVISAR.parent.mkdir(parents=True, exist_ok=True)
    colunas = ["id_item", "dominio", "url_produto", "titulo_encontrado",
               "score_match", "classificacao", "motivo_match"]
    temporario = REVISAR.with_suffix(".csv.tmp")
    with temporario.open("w", newline="", encoding="utf-8") as f:
        escritor = csv.DictWriter(f, fieldnames=colunas, extrasaction="ignore")
        escritor.writeheader()
        for linha in sorted(pendentes, key=lambda a: (a["id_item"], a["dominio"])):
            escritor.writerow(linha)
    os.replace(temporario, REVISAR)
    if pendentes:
        log.info("%d achados foram para %s", len(pendentes), REVISAR)


def medir_cobertura() -> dict[str, dict]:
    """Quantos itens de cada categoria já têm 5+ fontes, e quais faltam.

    É a regra de parada da prospecção e o painel de controle do
    projeto: diz quanto falta para a entrega existir e diz para a
    frente de prospecção exatamente o que procurar.
    """
    itens = tabelas.ler_itens()
    achados = consolidar_achados()
    aprovados = set(tabelas.ler_fornecedores(apenas_aprovados=True))

    fontes: dict[str, set[str]] = defaultdict(set)
    em_revisao: dict[str, set[str]] = defaultdict(set)
    for a in achados:
        if a["dominio"] not in aprovados:
            continue
        alvo = fontes if a.get("classificacao") == "aceito" else em_revisao
        alvo[a["id_item"]].add(a["dominio"])

    resumo: dict[str, dict] = {}
    for id_item, item in itens.items():
        dados = resumo.setdefault(
            item.categoria,
            {"total": 0, "completos": 0, "faltando": [], "em_revisao": 0},
        )
        dados["total"] += 1
        n = len(fontes.get(id_item, ()))
        if n >= ALVO_FONTES_POR_ITEM:
            dados["completos"] += 1
        else:
            dados["faltando"].append((id_item, n))
        if em_revisao.get(id_item):
            dados["em_revisao"] += 1

    for dados in resumo.values():
        dados["faltando"].sort(key=lambda par: par[1])
    return resumo


def exportar_cobertura(resumo: dict[str, dict] | None = None) -> list[Path]:
    """A visão por categoria, para humanos: um .xlsx por categoria.

    O nome leva o prefixo `cobertura_` de propósito: `data/output/
    {CATEGORIA}.xlsx` é a entrega final, gerada por montar_entrega, e
    duas coisas diferentes com o mesmo nome acabam com uma sobrescrevendo
    a outra no meio do prazo.
    """
    import pandas as pd

    resumo = resumo or medir_cobertura()
    itens = tabelas.ler_itens()
    achados = consolidar_achados()
    aprovados = set(tabelas.ler_fornecedores(apenas_aprovados=True))

    por_item: dict[str, list[dict]] = defaultdict(list)
    for a in achados:
        if a["dominio"] in aprovados:
            por_item[a["id_item"]].append(a)

    COBERTURA.mkdir(parents=True, exist_ok=True)
    gerados: list[Path] = []

    for categoria in sorted(resumo):
        linhas = []
        for id_item, item in itens.items():
            if item.categoria != categoria:
                continue
            desta = por_item.get(id_item, [])
            aceitos = sorted({a["dominio"] for a in desta
                              if a.get("classificacao") == "aceito"})
            revisar = sorted({a["dominio"] for a in desta
                              if a.get("classificacao") != "aceito"})
            linhas.append({
                "Código FGV": id_item,
                "Item": item.item_curto or item.descricao[:90],
                "Fontes aceitas": len(aceitos),
                "Falta para 5": max(0, ALVO_FONTES_POR_ITEM - len(aceitos)),
                "Em revisão": len(revisar),
                "Fornecedores": ", ".join(aceitos),
                "A revisar": ", ".join(revisar),
            })

        caminho = COBERTURA / f"cobertura_{_arquivo(categoria)}.xlsx"
        pd.DataFrame(linhas).to_excel(caminho, index=False)
        gerados.append(caminho)

    return gerados


def _arquivo(texto: str) -> str:
    from unidecode import unidecode

    limpo = unidecode(texto).upper()
    return "".join(c if c.isalnum() else "_" for c in limpo).strip("_")


def _numero(valor) -> float:
    try:
        return float(str(valor).replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


if __name__ == "__main__":
    gerar_plano()
    resumo = medir_cobertura()
    for categoria, dados in sorted(resumo.items()):
        print(f"{categoria}: {dados['completos']}/{dados['total']} com "
              f"{ALVO_FONTES_POR_ITEM}+ fontes, {dados['em_revisao']} com item em revisão")
        if dados["faltando"]:
            piores = ", ".join(f"{i}({n})" for i, n in dados["faltando"][:10])
            print(f"   faltando: {piores}")
    for caminho in exportar_cobertura(resumo):
        print(f"   {caminho}")
