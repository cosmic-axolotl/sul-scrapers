"""Decide se um produto encontrado atende a descrição solicitada.

Sem EAN e sem marca, isto aqui é o único controle de aderência que
existe no projeto. Vale ser rigoroso.
"""

from __future__ import annotations

import re

from rapidfuzz import fuzz
from unidecode import unidecode

STOPWORDS = {"de", "da", "do", "com", "para", "em", "e", "a", "o", "tipo", "cor",
             "aproximadamente", "aproximada", "minima", "maxima", "conforme"}

MATERIAIS = ("inox", "inoxidavel", "aluminio", "plastico", "polipropileno",
             "aco carbono", "vidro", "silicone", "nylon")

# "12 litros", "1500 mm", "30 kg", "6 l"
RE_MEDIDA = re.compile(
    r"(\d+(?:[.,]\d+)?)\s?(l|litros?|ml|mm|cm|m|kg|g|un|pol|\")\b"
)

BONUS_MEDIDA = 25.0
BONUS_MATERIAL = 10.0
LIMITE_ACEITE = 80.0
LIMITE_REVISAO = 60.0


def normalizar(texto: str) -> str:
    t = unidecode(texto or "").lower()
    t = re.sub(r"[^a-z0-9,.\"\s]", " ", t)
    palavras = [p for p in t.split() if p not in STOPWORDS]
    return " ".join(palavras)


def medidas(texto: str) -> set[tuple[float, str]]:
    """Extrai pares (valor, unidade) normalizados para comparação."""
    achados = set()
    for valor, unidade in RE_MEDIDA.findall(normalizar(texto)):
        v = float(valor.replace(",", "."))
        u = unidade.rstrip("s")
        if u in ("litro", "l"):
            u = "l"
        achados.add((v, u))
    return achados


def materiais(texto: str) -> set[str]:
    t = normalizar(texto)
    return {m for m in MATERIAIS if m in t}


def pontuar(descricao_item: str, titulo_produto: str) -> float:
    """Score 0..100+. Fuzzy textual mais bônus por medida e material.

    A medida numérica é o sinal mais forte que existe neste domínio:
    "panela 20 L" e "panela 50 L" são produtos diferentes com o mesmo
    nome, e o fuzzy sozinho não distingue os dois.
    """
    base = fuzz.token_set_ratio(normalizar(descricao_item), normalizar(titulo_produto))

    if medidas(descricao_item) & medidas(titulo_produto):
        base += BONUS_MEDIDA
    if materiais(descricao_item) & materiais(titulo_produto):
        base += BONUS_MATERIAL

    return base


def classificar(score: float) -> str:
    """'aceito' | 'revisar' | 'descartado'"""
    if score >= LIMITE_ACEITE:
        return "aceito"
    if score >= LIMITE_REVISAO:
        return "revisar"
    return "descartado"


def gerar_termos(item) -> list[str]:
    """Do texto de licitação para 2-4 buscas que uma loja entende.

    A descrição do FNDE tem ~300 caracteres. Jogar isso inteiro num
    campo de busca não retorna nada.

    TODO: calibrar contra os 20 pares rotulados em tests/fixtures/.
    """
    grupo = normalizar(item.grupo_insumo)
    primeiras = " ".join(normalizar(item.descricao).split()[:4])
    termos = [primeiras, grupo]

    for valor, unidade in sorted(medidas(item.descricao)):
        termos.insert(0, f"{grupo} {valor:g} {unidade}")
        break

    vistos, saida = set(), []
    for t in termos:
        if t and t not in vistos:
            vistos.add(t)
            saida.append(t)
    return saida[:4]
