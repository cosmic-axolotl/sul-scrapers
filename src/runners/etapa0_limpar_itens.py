"""Limpa a Lista de Equipamentos FNDE para a Etapa 2.

Saídas:
  data/interim/itens.csv            130 itens da coleta automática
  data/interim/itens_manuais.csv     14 itens da coleta manual
  data/output/itens_limpos.xlsx      as duas listas, para a equipe ler

Outra lista no mesmo formato passa pela mesma limpeza com --entrada e
--saida. É o caso da lista de varejo (31 itens de EQUIPAMENTO que podem
ser comprados em loja de varejo):

  python -m src.runners.etapa0_limpar_itens \\
      --entrada "data/raw/Lista de Equipamentos_Varejo_Sul xlsx.xlsx" \\
      --saida data/interim/itens_varejo.csv

--saida é obrigatório nesse caso na prática: sem ele a lista nova
SOBRESCREVE o itens.csv principal, e a varredura perde os outros 101
itens sem aviso nenhum.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
from unidecode import unidecode

ENTRADA = Path("data/raw/Lista_Equipamentos_FNDE_-_SUL.xlsx")
SAIDA = Path("data/interim/itens.csv")

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
    # Sem estas, a âncora de 3 palavras saía cortada no meio da frase:
    # "forno integrado ao" (item 34), de "integrado ao fogão".
    "ao", "aos", "as", "os", "no", "na", "nos", "nas", "um", "uma", "por",
    "pela", "pelo", "sem", "que", "se", "seu", "sua", "entre", "sobre",
}

# "12 litros", "1500 mm", "30 kg", "500 ml", "6 l", "1.500 mm", "2,3 litros".
#
# O número é lido em pt-BR: ponto seguido de exatamente três dígitos é
# separador de MILHAR, vírgula é decimal. Ler "1.500 mm" como 1,5 fazia a
# coifa do item 7 virar "coifa 1.5 mm", uma busca que não acha nada.
#
# `(?!\s+h\b)` descarta taxa por hora: "250 kg/h" é produção, não peso.
# (normalizar() já trocou a barra por espaço, então chega "250 kg h".)
RE_MEDIDA = re.compile(
    r"(\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?)"
    r"\s?(l|litros?|ml|mm|cm|kg|g|un)\b(?!\s+h\b)"
)

MATERIAIS = ["inox", "inoxidavel", "aluminio", "polipropileno", "policarbonato",
             "plastico", "aco carbono", "vidro", "silicone", "nylon", "madeira"]

# Acessórios cuja medida aparece na descrição e NÃO é a do equipamento:
# "10 esteiras de 580 × 680 mm" (forno 19), "grelhas em ferro fundido
# (300 × 300 mm)" (fogão 15), "trempes de 400 × 400 mm" (fogões 17 e 18).
# Buscar "fogao 400 mm" numa loja devolve qualquer coisa de 40 cm.
ACESSORIOS = ("grelha", "trempe", "esteira", "assadeira", "cuba", "bandeja",
              "gaveta", "prateleira", "grade", "disco")
# "disco": "7 discos de corte com diâmetro de 203 mm" (processador 27).

# Contagens que são como a loja nomeia o equipamento: "Forno Turbo 10
# Esteiras", "Fogão Industrial 6 Queimadores", "Refrigerador 4 Portas".
# Viram termo de busca -- são mais específicas que o nome sozinho.
#
# Cada contagem só vale para o grupo que TEM aquela peça. A coifa 11 é
# "compatível com fogão de 6 queimadores" e o forno 34 é "integrado ao
# fogão de 5 queimadores": o número é do fogão, e "coifa 6 queimadores"
# é uma busca por um produto que não se vende assim.
CONTAVEIS = {
    "queimadores": ("fogao",),
    "bocas": ("fogao",),
    "esteiras": ("forno",),
    "portas": ("refrigerador", "freezer"),
}

# Até onde olhar para trás, a partir da medida, atrás de um acessório.
# Para na vírgula e no ponto-e-vírgula (outra cláusula, outro assunto),
# mas não no parêntese: "grelhas removíveis (300 × 300 mm)".
JANELA_ACESSORIO = 60


def normalizar(texto: str) -> str:
    t = unidecode(str(texto or "")).lower()
    t = re.sub(r"[^a-z0-9,.\s]", " ", t)
    return " ".join(p for p in t.split() if p not in STOPWORDS)


def numero_ptbr(texto: str) -> float:
    """"1.500" -> 1500.0, "1.044" -> 1044.0, "2,3" -> 2.3, "12" -> 12.0."""
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?", texto):
        texto = texto.replace(".", "")
    return float(texto.replace(",", "."))


def _de_acessorio(texto: str, inicio: int) -> bool:
    """A medida em `inicio` é tamanho de um acessório, não do equipamento?"""
    antes = texto[max(0, inicio - JANELA_ACESSORIO):inicio]
    # Só a cláusula corrente: depois da última vírgula ou ponto-e-vírgula.
    # O ponto não conta, porque também é separador de milhar.
    clausula = re.split(r"[,;]", antes)[-1]
    return any(a in clausula for a in ACESSORIOS)


def medidas(texto: str) -> list[tuple[float, str]]:
    """Medidas do EQUIPAMENTO, na ordem em que aparecem.

    Ficam de fora a taxa por hora ("250 kg/h") e a medida de acessório
    ("10 esteiras de 580 × 680 mm"). Nas duas, o número é verdadeiro e o
    termo de busca que sai dele é mentira.
    """
    t = normalizar(texto)
    achados = []
    for m in RE_MEDIDA.finditer(t):
        if _de_acessorio(t, m.start()):
            continue
        u = m.group(2).rstrip("s")
        u = "l" if u in ("litro", "l") else u
        achados.append((numero_ptbr(m.group(1)), u))
    return achados


def contagem(grupo: str, texto: str) -> tuple[int, str] | None:
    """"fogão ... com 6 queimadores" -> (6, "queimadores").

    Só as peças do próprio grupo -- ver CONTAVEIS.
    """
    g = normalizar(grupo)
    pecas = [p for p, donos in CONTAVEIS.items() if any(d in g for d in donos)]
    if not pecas:
        return None
    m = re.search(rf"\b(\d+)\s+({'|'.join(pecas)})\b", normalizar(texto))
    return (int(m.group(1)), m.group(2)) if m else None


def material(texto: str) -> str | None:
    """O primeiro material citado, como PALAVRA inteira.

    Comparar por pedaço de texto achava "madeira" dentro de "mamadeiras"
    e fazia o esterilizador de mamadeiras (E036) virar "esterilizador
    madeira" -- uma busca que devolve tábua de corte.
    """
    t = normalizar(texto)
    achado = next((m for m in MATERIAIS if re.search(rf"\b{m}\b", t)), None)
    # "inoxidavel" só entra na lista para ser reconhecido como palavra
    # inteira; a loja escreve "inox", e é isso que vai para a busca.
    return "inox" if achado == "inoxidavel" else achado


def _formatar(valor: float) -> str:
    """1500.0 -> "1500", 2.3 -> "2,3". Vírgula, porque a busca é de loja brasileira."""
    return f"{valor:g}".replace(".", ",")


def _sem_pontuacao(palavras: list[str]) -> list[str]:
    """Tira vírgula e ponto das pontas -- "precisao," virava parte do termo."""
    return [p.strip(",.") for p in palavras if p.strip(",.")]


def gerar_termos(grupo: str, descricao: str) -> list[str]:
    """Do texto de licitação para 2-4 buscas que uma loja entende.

    Do mais específico ao mais genérico: a varredura para no primeiro
    que der match bom, então a ordem importa.
    """
    g = " ".join(_sem_pontuacao(normalizar(grupo).split()))
    especificos: list[str] = []

    med = medidas(descricao)
    if med:
        valor, unidade = med[0]
        especificos.append(f"{g} {_formatar(valor)} {unidade}")

    cont = contagem(grupo, descricao)
    if cont:
        especificos.append(f"{g} {cont[0]} {cont[1]}")

    mat = material(descricao)
    if mat:
        especificos.append(f"{g} {mat}")

    # Âncora de contexto: as 3 primeiras palavras úteis da descrição.
    inicio = " ".join(_sem_pontuacao(normalizar(descricao).split())[:3])
    if inicio:
        especificos.append(inicio)

    vistos, saida = set(), []
    for t in especificos:
        t = t.strip()
        if t and t != g and t not in vistos:
            vistos.add(t)
            saida.append(t)

    # O nome do grupo sozinho é o último recurso da varredura e nunca
    # pode ser cortado: com a contagem, os específicos passaram a ser
    # quatro, e o corte em quatro jogaria fora justamente ele.
    return saida[:3] + [g]


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


def caminho_manuais(saida: Path) -> Path:
    """itens.csv -> itens_manuais.csv; itens_varejo.csv -> itens_varejo_manuais.csv."""
    return saida.with_name(f"{saida.stem}_manuais{saida.suffix}")


def main(entrada: Path = ENTRADA, saida: Path = SAIDA):
    df = pd.read_excel(entrada)
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

    saida = Path(saida)
    saida.parent.mkdir(parents=True, exist_ok=True)

    # Os dois arquivos são gravados sempre, mesmo vazios: só o cabeçalho
    # já diz "rodei e não havia nenhum", e um arquivo velho esquecido de
    # outra rodada diria o contrário.
    automaticos.to_csv(saida, index=False, encoding="utf-8")
    manuais.to_csv(caminho_manuais(saida), index=False, encoding="utf-8")

    print(f"{entrada.name}")
    print(f"automáticos: {len(automaticos)} -> {saida}")
    print(f"manuais:     {len(manuais)} -> {caminho_manuais(saida)}")
    print(automaticos["categoria"].value_counts().to_string())
    return automaticos, manuais


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="Etapa 0 — limpa uma lista de itens FNDE")
    p.add_argument("--entrada", type=Path, default=ENTRADA,
                   help=f"planilha de itens (padrão: {ENTRADA})")
    p.add_argument("--saida", type=Path, default=SAIDA,
                   help=f"CSV limpo (padrão: {SAIDA}); os manuais vão ao lado, "
                        f"com _manuais no nome")
    a = p.parse_args()
    main(a.entrada, a.saida)
