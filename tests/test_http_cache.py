"""Validade do cache HTTP.

Antes, qualquer resposta guardada era reaproveitada para sempre, com
cache ligado por padrão — inclusive na coleta. O efeito: preço e estoque
de semanas atrás entravam na planilha com a data de hoje ao lado, e o
print (tirado na hora) mostrava outro número.
"""

from __future__ import annotations

import json
import time

import pytest

from src.core import http
from src.core.http import Cliente, normalizar_dominio


@pytest.fixture(autouse=True)
def cache_temporario(tmp_path, monkeypatch):
    monkeypatch.setattr(http, "CACHE_DIR", tmp_path / "http_cache")
    monkeypatch.delenv("SUL_SCRAPERS_CACHE_TTL", raising=False)
    return tmp_path / "http_cache"


def semear(cliente: Cliente, url: str, corpo: str, idade_segundos: float = 0.0) -> None:
    """Escreve no cache como se a resposta tivesse chegado há N segundos."""
    cliente._gravar_cache(url, corpo, 200)
    if idade_segundos:
        caminho = cliente._caminho_meta(cliente._caminho_cache(url))
        meta = json.loads(caminho.read_text(encoding="utf-8"))
        meta["gravado_em"] = time.time() - idade_segundos
        caminho.write_text(json.dumps(meta), encoding="utf-8")


URL = "https://loja.com.br/api/produto"


def test_normalizar_dominio():
    assert normalizar_dominio("https://WWW.GPInox.com.br/") == "gpinox.com.br"
    assert normalizar_dominio("gpinox.com.br") == "gpinox.com.br"
    assert normalizar_dominio("https://loja.com.br:443/busca") == "loja.com.br"


def test_resposta_recente_e_reaproveitada():
    c = Cliente(ttl_segundos=3600)
    semear(c, URL, "corpo", idade_segundos=10)
    assert c._ler_cache(URL) == "corpo"


def test_resposta_vencida_nao_e_reaproveitada():
    c = Cliente(ttl_segundos=3600)
    semear(c, URL, "corpo", idade_segundos=7200)
    assert c._ler_cache(URL) is None


def test_cliente_de_coleta_nunca_reaproveita():
    """Preço e frete da entrega são de hoje. Sempre."""
    c = Cliente.para_coleta()
    semear(c, URL, "corpo", idade_segundos=1)
    assert c._ler_cache(URL) is None


def test_cliente_de_coleta_continua_gravando(cache_temporario):
    """A resposta guardada é prova do que o site disse, não só economia."""
    c = Cliente.para_coleta()
    c._gravar_cache(URL, "corpo", 200)
    assert c._caminho_cache(URL).exists()


def test_cliente_de_varredura_reaproveita_dentro_do_prazo():
    c = Cliente.para_varredura()
    semear(c, URL, "corpo", idade_segundos=60)
    assert c._ler_cache(URL) == "corpo"


def test_cache_sem_metadado_usa_a_data_do_arquivo(cache_temporario):
    """Cache gravado antes desta mudança não pode quebrar a leitura."""
    c = Cliente(ttl_segundos=3600)
    caminho = c._caminho_cache(URL)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text("antigo", encoding="utf-8")

    assert c._ler_cache(URL) == "antigo"


def test_variavel_de_ambiente_sobrepoe_o_ttl(monkeypatch):
    monkeypatch.setenv("SUL_SCRAPERS_CACHE_TTL", "5")
    c = Cliente(ttl_segundos=3600)
    assert c.ttl_segundos == 5


def test_ttl_nenhum_desliga_a_validade(monkeypatch):
    monkeypatch.setenv("SUL_SCRAPERS_CACHE_TTL", "nenhum")
    c = Cliente()
    semear(c, URL, "corpo", idade_segundos=10**7)
    assert c._ler_cache(URL) == "corpo"


def test_cache_desligado_ignora_o_que_esta_no_disco():
    gravador = Cliente(ttl_segundos=3600)
    semear(gravador, URL, "corpo")

    assert Cliente(usar_cache=False)._ler_cache(URL) is None
