"""Limpa a Lista de Equipamentos FNDE para a Etapa 2.

Saídas:
  data/interim/itens.csv            130 itens da coleta automática
  data/interim/itens_manuais.csv     14 itens da coleta manual
  data/output/itens_limpos.xlsx      as duas listas, para a equipe ler
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
from unidecode import unidecode

ENTRADA = Path("data/raw/Lista_Equipamentos_FNDE_-_SUL.xlsx")

# Categorias sem loja online com carrinho: cotação por telefone/e-mail.
# VEICULOS não é veículo: são 2 pneus, vendidos normalmente por
# atacadista de autopeças. Fica na coleta automática.
CATEGORIAS_MANUAIS = ["COMBUSTÍVEL", "SAÚDE OCUPACIONAL"]

# Colunas descartadas e por quê:
#   Prioridade        100% vazia
#   EAN               100% vazia -> não há match por código de barras
#   Embalagem         só contém "-"
#   Marca/Fabricante  o critério é aderência à descrição, não marca
#   Código do Insumo  idêntico a ID FGV nas 144 linhas (conferido)
#   Quantidade        constante = 1 (é a premissa do frete: 1 unidade)
#   Unidade de Medida constante = UN depois de tirar COMBUSTÍVEL (KG só no GLP)
#   Descrição_Resumida truncada à mão e CORROMPIDA: 4 linhas perderam os
#                      primeiros caracteres (a 311 virou "UVA ANTICORTE"),
#                      1 vazia, 19 idênticas à completa. Substituída por
#                      item_curto, derivado da Descrição.
COLUNAS_FORA = ["Prioridade", "EAN", "Embalagem", "Marca", "Fabricante",
                "Código do Insumo", "Quantidade", "Unidade de Medida",
                "Descrição_Resumida"]

STOPWORDS = {
    "de", "da", "do", "com", "para", "em", "e", "a", "o", "ou", "tipo", "cor",
    "aproximadamente", "aproximada", "aproximado", "minima", "minimo", "maxima",
    "maximo", "conforme", "possui", "confeccionado", "proprio", "alta", "uso",
    "capacidade", "estrutura", "acabamento", "alimentacao", "eletrica", "modelo",
}

# "12 litros", "1500 mm", "30 kg", "500 ml", "6 l"
RE_MEDIDA = re.compile(r"(\d+(?:[.,]\d+)?)\s?(l|litros?|ml|mm|cm|kg|g|un)\b")

MATERIAIS = ["inox", "inoxidavel", "aluminio", "polipropileno", "policarbonato",
             "plastico", "aco carbono", "vidro", "silicone", "nylon", "madeira"]


def normalizar(texto: str) -> str:
    t = unidecode(str(texto or "")).lower()
    t = re.sub(r"[^a-z0-9,.\s]", " ", t)
    return " ".join(p for p in t.split() if p not in STOPWORDS)


def medidas(texto: str) -> list[tuple[float, str]]:
    achados = []
    for valor, unidade in RE_MEDIDA.findall(normalizar(texto)):
        u = unidade.rstrip("s")
        u = "l" if u in ("litro", "l") else u
        achados.append((float(valor.replace(",", ".")), u))
    return achados


def material(texto: str) -> str | None:
    t = normalizar(texto)
    return next((m for m in MATERIAIS if m in t), None)


def gerar_termos(grupo: str, descricao: str) -> list[str]:
    """Do texto de licitação para 2-4 buscas que uma loja entende.

    Do mais específico ao mais genérico: a varredura para no primeiro
    que der match bom, então a ordem importa.
    """
    g = normalizar(grupo)
    termos: list[str] = []

    med = medidas(descricao)
    if med:
        valor, unidade = med[0]
        termos.append(f"{g} {valor:g} {unidade}")

    mat = material(descricao)
    if mat:
        termos.append(f"{g} {mat}")

    # Âncora de contexto: as 3 primeiras palavras úteis da descrição.
    inicio = " ".join(normalizar(descricao).split()[:3])
    if inicio:
        termos.append(inicio)

    termos.append(g)

    vistos, saida = set(), []
    for t in termos:
        t = t.strip()
        if t and t not in vistos:
            vistos.add(t)
            saida.append(t)
    return saida[:4]


def item_curto(descricao: str, limite: int = 90) -> str:
    """Rótulo curto para a coluna Item da entrega, derivado da Descrição.

    A primeira cláusula da descrição costuma ser o nome comercial do
    produto. Determinístico, sem os buracos da Descrição_Resumida.
    """
    texto = re.sub(r"\s+", " ", str(descricao or "").replace("\\n", " ")).strip()
    corte = texto.split(",")[0].strip(" .,;")
    if len(corte) < 12:
        corte = texto[:limite]
    if len(corte) > limite:
        corte = corte[:limite].rsplit(" ", 1)[0]
    return corte[:1].upper() + corte[1:].lower() if corte.isupper() else corte


def main() -> None:
    df = pd.read_excel(ENTRADA)
    df = df.drop(columns=[c for c in COLUNAS_FORA if c in df.columns])

    df = df.rename(columns={
        "ID FGV": "id_item",
        "Categoria": "categoria",
        "Grupo de Insumo": "grupo_insumo",
        "Descrição": "descricao",
    })

    # ID FGV é ALFANUMÉRICO: "1", "G008", "U029", "E037", "318N".
    # Tratar como int perde 96 dos 144. É string, sempre.
    df["id_item"] = df["id_item"].astype(str).str.strip()
    assert df["id_item"].is_unique, "ID FGV duplicado"
    # A planilha traz "\n" literal dentro de algumas descrições (os pneus).
    df["descricao"] = (df["descricao"].astype(str)
                       .str.replace(r"\\n", " ", regex=True)
                       .str.replace(r"\s+", " ", regex=True).str.strip())
    df["item_curto"] = df["descricao"].map(item_curto)
    df["termos_busca"] = [
        " | ".join(gerar_termos(g, d))
        for g, d in zip(df["grupo_insumo"], df["descricao"])
    ]

    colunas = ["id_item", "categoria", "grupo_insumo", "item_curto",
               "descricao", "termos_busca"]
    df = df[colunas].sort_values(["categoria", "grupo_insumo", "id_item"])

    manuais = df[df["categoria"].isin(CATEGORIAS_MANUAIS)].copy()
    automaticos = df[~df["categoria"].isin(CATEGORIAS_MANUAIS)].copy()

    # Os manuais não passam pelo scraper: termo de busca não faz sentido.
    manuais = manuais.drop(columns=["termos_busca"])

    for pasta in ("data/interim", "data/output"):
        Path(pasta).mkdir(parents=True, exist_ok=True)

    automaticos.to_csv("data/interim/itens.csv", index=False, encoding="utf-8")
    manuais.to_csv("data/interim/itens_manuais.csv", index=False, encoding="utf-8")

    print(f"automáticos: {len(automaticos)}  manuais: {len(manuais)}")
    print(automaticos["categoria"].value_counts().to_string())
    return automaticos, manuais


if __name__ == "__main__":
    main()
