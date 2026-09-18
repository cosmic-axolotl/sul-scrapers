"""Consulta cadastral do CNPJ em API pública, com cache em disco."""

from __future__ import annotations

import json
from pathlib import Path

from src.core.http import Cliente

CACHE = Path("data/raw/cnpj")

# Primária e fallback. Ambas públicas, sem chave.
FONTES = (
    "https://minhareceita.org/{cnpj}",
    "https://brasilapi.com.br/api/cnpj/v1/{cnpj}",
)


def consultar(cnpj: str, cliente: Cliente) -> dict | None:
    """Devolve a resposta bruta da Receita. Guarda em data/raw/cnpj/.

    O cache não é otimização, é necessidade: a BrasilAPI limita ~3
    req/min por IP e nós temos ~200 CNPJs para consultar várias vezes
    durante o desenvolvimento.
    """
    CACHE.mkdir(parents=True, exist_ok=True)
    arquivo = CACHE / f"{cnpj}.json"
    if arquivo.exists():
        return json.loads(arquivo.read_text(encoding="utf-8"))

    for molde in FONTES:
        try:
            dados = cliente.get_json(molde.format(cnpj=cnpj))
        except Exception:
            continue
        if isinstance(dados, dict) and dados:
            arquivo.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
            return dados
    return None


def normalizar(dados: dict) -> dict:
    """Achata os campos que o pipeline usa.

    As duas APIs nomeiam os campos de forma diferente. Esta função é o
    único lugar do projeto que sabe disso.

    TODO: conferir os nomes exatos contra uma resposta real de cada
    fonte antes de confiar (salve uma em tests/fixtures/).
    """
    return {
        "razao_social": dados.get("razao_social") or dados.get("nome_empresarial"),
        "uf": dados.get("uf"),
        "municipio": dados.get("municipio"),
        "cnae_principal": _codigo(dados.get("cnae_fiscal") or dados.get("codigo_cnae_fiscal")),
        "cnaes_secundarios": [
            _codigo(c.get("codigo") or c.get("cnae"))
            for c in (dados.get("cnaes_secundarios") or [])
        ],
        "situacao_cadastral": (dados.get("descricao_situacao_cadastral") or "").upper(),
    }


def _codigo(valor) -> str:
    """Normaliza '4649-4/99', '4649499' e 4649499 para '4649499'."""
    import re

    return re.sub(r"\D", "", str(valor or ""))
