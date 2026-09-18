"""Acha o CNPJ de uma loja no próprio site (rodapé, institucional, termos)."""

from __future__ import annotations

import re

from src.core.http import Cliente

PAGINAS = ("", "/institucional", "/quem-somos", "/sobre-nos",
           "/politica-de-privacidade", "/termos-de-uso", "/contato")

RE_CNPJ = re.compile(r"\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}")


def digitos(texto: str) -> str:
    return re.sub(r"\D", "", texto)


def cnpj_valido(cnpj: str) -> bool:
    """Valida os dois dígitos verificadores.

    Sem isso, a regex casa telefone e CEP colados por acidente. Este
    filtro sozinho limpa a maior parte do lixo.
    """
    c = digitos(cnpj)
    if len(c) != 14 or c == c[0] * 14:
        return False
    for tamanho in (12, 13):
        pesos = list(range(tamanho - 7, 1, -1)) + list(range(9, 1, -1))
        soma = sum(int(d) * p for d, p in zip(c[:tamanho], pesos))
        resto = soma % 11
        digito = 0 if resto < 2 else 11 - resto
        if int(c[tamanho]) != digito:
            return False
    return True


def extrair_do_html(html: str) -> list[str]:
    """Todos os CNPJs válidos e distintos presentes no HTML, em ordem."""
    vistos: list[str] = []
    for bruto in RE_CNPJ.findall(html):
        c = digitos(bruto)
        if cnpj_valido(c) and c not in vistos:
            vistos.append(c)
    return vistos


def extrair_do_site(url_base: str, cliente: Cliente) -> str | None:
    """Varre as páginas típicas e devolve o CNPJ mais provável.

    Heurística: o primeiro CNPJ válido encontrado na home costuma ser o
    da própria loja. Quando só aparece nos termos, pode ser da matriz.

    TODO: quando houver mais de um candidato, preferir o que aparecer
    perto das palavras "CNPJ", "inscrito" ou do nome da empresa.
    """
    for caminho in PAGINAS:
        try:
            html = cliente.get(url_base.rstrip("/") + caminho)
        except Exception:
            continue
        achados = extrair_do_html(html)
        if achados:
            return achados[0]
    return None
