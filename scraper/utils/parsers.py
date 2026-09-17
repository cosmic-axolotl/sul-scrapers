import re
from typing import Optional
from data.marcas import MARCAS_CONHECIDAS

_UNIDADES_PADRONIZADAS = {
    "kg": "kg",
    "kgs": "kg",
    "quilo": "kg",
    "quilos": "kg",
    "g": "g",
    "gr": "g",
    "gramas": "g",
    "l": "L",
    "lt": "L",
    "litro": "L",
    "litros": "L",
    "ml": "ml",
    "un": "un",
    "und": "un",
    "unid": "un",
    "unidade": "un",
    "unidades": "un",
    "cx": "cx",
    "caixa": "cx",
    "pct": "pct",
    "pacote": "pct",
    "dz": "dz",
    "duzia": "dz",
    "dúzia": "dz",
}

_REGEX_QUANTIDADE = re.compile(
    r"(?P<qtd>\d+[.,]?\d*)\s*(?P<unid>kg|kgs|g|gr|gramas|l|lt|litros?|ml|un|und|unid|unidades?|dz|d[uú]zia)\b",
    re.IGNORECASE,
)
_REGEX_CAIXA = re.compile(r"(?:cx|caixa)\s*(?:c/|com)?\s*(?P<qtd>\d+)", re.IGNORECASE)


def parse_preco(texto_preco: str) -> Optional[float]:
    if not texto_preco:
        return None
    limpo = re.sub(r"[^\d,.]", "", texto_preco)
    if not limpo:
        return None
    limpo = limpo.replace(".", "").replace(",", ".")
    try:
        return round(float(limpo), 2)
    except ValueError:
        return None


def extrair_quantidade_e_unidade(titulo: str) -> tuple[Optional[float], Optional[str]]:
    if not titulo:
        return None, None

    m_caixa = _REGEX_CAIXA.search(titulo)
    if m_caixa:
        return float(m_caixa.group("qtd")), "cx"

    m = _REGEX_QUANTIDADE.search(titulo)
    if not m:
        return None, None

    qtd_str = m.group("qtd").replace(",", ".")
    unid_raw = m.group("unid").lower()
    unidade = _UNIDADES_PADRONIZADAS.get(unid_raw, unid_raw)
    try:
        return float(qtd_str), unidade
    except ValueError:
        return None, unidade


def calcular_preco_por_unidade(
    preco: float, quantidade: Optional[float], unidade: Optional[str]
) -> Optional[float]:
    if preco is None or quantidade in (None, 0) or not unidade:
        return None

    if unidade in ("g", "ml"):
        return round(preco / (quantidade / 1000), 2)
    return round(preco / quantidade, 2)


def extrair_marca(
    titulo: str, marcas_conhecidas: Optional[list[str]] = None
) -> Optional[str]:
    if not titulo:
        return None
    marcas = marcas_conhecidas or MARCAS_CONHECIDAS
    for marca in marcas:
        if marca.lower() in titulo.lower():
            return marca
    return None
