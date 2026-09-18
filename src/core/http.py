"""Sessão HTTP única do projeto: retry, timeout, rate limit e cache.

Ninguém chama httpx.get() direto. Tudo passa por aqui, senão o rate
limit por domínio não existe de verdade.
"""

from __future__ import annotations

import hashlib
import random
import time
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

import httpx

CACHE_DIR = Path("data/raw/http_cache")
TIMEOUT = 20.0
MAX_TENTATIVAS = 3
INTERVALO_MIN, INTERVALO_MAX = 1.0, 3.0

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def normalizar_dominio(url_ou_dominio: str) -> str:
    """Chave primária do projeto. 'https://WWW.GPInox.com.br/' -> 'gpinox.com.br'"""
    texto = url_ou_dominio.strip().lower()
    if "://" not in texto:
        texto = "https://" + texto
    host = urlparse(texto).netloc or urlparse(texto).path
    host = host.split(":")[0]
    return host.removeprefix("www.").strip("/")


class Cliente:
    """Wrapper de httpx.Client com espaçamento por domínio e cache em disco.

    O cache existe para o desenvolvimento: dá para reprocessar o parser
    vinte vezes sem tocar no site de novo.
    """

    def __init__(self, usar_cache: bool = True) -> None:
        self._http = httpx.Client(
            headers={"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9"},
            follow_redirects=True,
            timeout=TIMEOUT,
        )
        self._ultimo_acesso: dict[str, float] = defaultdict(float)
        self.usar_cache = usar_cache
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def _esperar(self, dominio: str) -> None:
        espera = random.uniform(INTERVALO_MIN, INTERVALO_MAX)
        decorrido = time.monotonic() - self._ultimo_acesso[dominio]
        if decorrido < espera:
            time.sleep(espera - decorrido)
        self._ultimo_acesso[dominio] = time.monotonic()

    def _caminho_cache(self, url: str) -> Path:
        chave = hashlib.sha256(url.encode()).hexdigest()[:24]
        return CACHE_DIR / f"{chave}.txt"

    def get(self, url: str, **kwargs) -> str:
        """GET com cache, espaçamento e retry. Devolve o corpo como texto.

        TODO: levantar exceção própria (ex. SiteBloqueado) em 403/429
        persistente, para o runner registrar em data/raw/bloqueadas.csv.
        """
        cache = self._caminho_cache(url)
        if self.usar_cache and cache.exists():
            return cache.read_text(encoding="utf-8")

        dominio = normalizar_dominio(url)
        ultimo_erro: Exception | None = None

        for tentativa in range(MAX_TENTATIVAS):
            self._esperar(dominio)
            try:
                r = self._http.get(url, **kwargs)
                if r.status_code in (429, 500, 502, 503, 504):
                    time.sleep(2**tentativa)
                    continue
                r.raise_for_status()
                if self.usar_cache:
                    cache.write_text(r.text, encoding="utf-8")
                return r.text
            except httpx.HTTPError as e:  # noqa: PERF203
                ultimo_erro = e
                time.sleep(2**tentativa)

        raise RuntimeError(f"falhou após {MAX_TENTATIVAS} tentativas: {url}") from ultimo_erro

    def get_json(self, url: str, **kwargs) -> dict | list:
        import json

        return json.loads(self.get(url, **kwargs))

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "Cliente":
        return self

    def __exit__(self, *_) -> None:
        self.close()
