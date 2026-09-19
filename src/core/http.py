"""Sessão HTTP única do projeto: retry, timeout, rate limit e cache.

Ninguém chama httpx.get() direto. Tudo passa por aqui, senão o rate
limit por domínio não existe de verdade.

Sobre o cache: ele tem VALIDADE, e a validade muda conforme a fase.

    varredura  -> cache longo. Reprocessar o parser vinte vezes sem
                  tocar no site é exatamente o que se quer.
    coleta     -> não reaproveita nada. Preço, estoque e frete entram na
                  entrega com a data de coleta ao lado, e um corpo
                  guardado semana passada faria a planilha discordar do
                  print tirado hoje.

A resposta continua sendo gravada em disco nos dois casos: ela é prova
do que o site respondeu naquele instante, não só economia de rede.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import time
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

import httpx

from src.core.log import obter

log = obter(__name__)

CACHE_DIR = Path("data/raw/http_cache")
TIMEOUT = 20.0
MAX_TENTATIVAS = 3
INTERVALO_MIN, INTERVALO_MAX = 1.0, 3.0

# Validade padrão do cache, em segundos. 7 dias serve ao desenvolvimento
# e não serve à coleta -- por isso a coleta usa Cliente.para_coleta().
TTL_PADRAO = 7 * 24 * 3600
TTL_SEM_REAPROVEITAMENTO = 0.0

STATUS_BLOQUEIO = (401, 403, 407, 429)
STATUS_TEMPORARIO = (500, 502, 503, 504)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


# ---------------------------------------------------------------------------
# Exceções -- o runner precisa distinguir "site me barrou" de "site caiu"
# ---------------------------------------------------------------------------

class ErroHTTP(Exception):
    """Base de tudo que sai daqui."""

    def __init__(self, mensagem: str, url: str = "") -> None:
        super().__init__(mensagem)
        self.url = url
        self.dominio = normalizar_dominio(url) if url else ""


class SiteBloqueado(ErroHTTP):
    """403/429 persistente: o site nos barrou. Vira linha em bloqueadas.csv."""


class FalhaDeRede(ErroHTTP):
    """Timeout, DNS, conexão recusada, 5xx persistente. Dá para tentar de novo."""


class RespostaInvalida(ErroHTTP):
    """Respondeu 200 mas o corpo não é o que se esperava (JSON quebrado)."""


def normalizar_dominio(url_ou_dominio: str) -> str:
    """Chave primária do projeto. 'https://WWW.GPInox.com.br/' -> 'gpinox.com.br'"""
    texto = url_ou_dominio.strip().lower()
    if "://" not in texto:
        texto = "https://" + texto
    host = urlparse(texto).netloc or urlparse(texto).path
    host = host.split(":")[0]
    return host.removeprefix("www.").strip("/")


def _ttl_do_ambiente(padrao: float | None) -> float | None:
    """SUL_SCRAPERS_CACHE_TTL sobrepõe o padrão. "nenhum" = sem validade."""
    bruto = os.getenv("SUL_SCRAPERS_CACHE_TTL")
    if bruto is None:
        return padrao
    if bruto.strip().lower() in ("nenhum", "infinito", "none"):
        return None
    try:
        return float(bruto)
    except ValueError:
        log.warning("SUL_SCRAPERS_CACHE_TTL invalido (%r); usando o padrao", bruto)
        return padrao


class Cliente:
    """Wrapper de httpx.Client com espaçamento por domínio e cache em disco.

    `ttl_segundos` é a idade máxima de uma resposta guardada:
        None -> sem validade (só para depuração; não use em coleta)
        0    -> nunca reaproveita, mas continua gravando
        N    -> reaproveita enquanto a resposta tiver menos de N segundos
    """

    def __init__(
        self,
        usar_cache: bool = True,
        ttl_segundos: float | None = TTL_PADRAO,
    ) -> None:
        self._http = httpx.Client(
            headers={"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9"},
            follow_redirects=True,
            timeout=TIMEOUT,
        )
        self._ultimo_acesso: dict[str, float] = defaultdict(float)
        self.usar_cache = usar_cache
        self.ttl_segundos = _ttl_do_ambiente(ttl_segundos)
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # --- construtores por fase ---------------------------------------------

    @classmethod
    def para_varredura(cls) -> "Cliente":
        """Cache longo: a varredura só quer saber se a loja tem o item."""
        return cls(usar_cache=True, ttl_segundos=TTL_PADRAO)

    @classmethod
    def para_coleta(cls) -> "Cliente":
        """Sempre busca de novo. Preço e frete da entrega são de hoje."""
        return cls(usar_cache=True, ttl_segundos=TTL_SEM_REAPROVEITAMENTO)

    # --- cache --------------------------------------------------------------

    def _caminho_cache(self, url: str) -> Path:
        chave = hashlib.sha256(url.encode()).hexdigest()[:24]
        return CACHE_DIR / f"{chave}.txt"

    @staticmethod
    def _caminho_meta(cache: Path) -> Path:
        return cache.with_suffix(".meta.json")

    def _idade(self, cache: Path) -> float:
        """Segundos desde que esta resposta foi gravada."""
        meta = self._caminho_meta(cache)
        try:
            gravado_em = json.loads(meta.read_text(encoding="utf-8"))["gravado_em"]
        except (OSError, ValueError, KeyError):
            # Cache de antes da validade existir: cai no mtime do arquivo.
            gravado_em = cache.stat().st_mtime
        return max(0.0, time.time() - float(gravado_em))

    def _ler_cache(self, url: str) -> str | None:
        if not self.usar_cache:
            return None
        cache = self._caminho_cache(url)
        if not cache.exists():
            return None
        if self.ttl_segundos is not None:
            if self.ttl_segundos <= 0:
                return None
            idade = self._idade(cache)
            if idade > self.ttl_segundos:
                log.debug("cache vencido (%.0fs) para %s", idade, url)
                return None
        return cache.read_text(encoding="utf-8")

    def _gravar_cache(self, url: str, corpo: str, status: int) -> None:
        if not self.usar_cache:
            return
        cache = self._caminho_cache(url)
        try:
            cache.write_text(corpo, encoding="utf-8")
            self._caminho_meta(cache).write_text(
                json.dumps(
                    {"url": url, "status": status, "gravado_em": time.time()},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        except OSError as e:
            log.warning("nao consegui gravar o cache de %s: %s", url, e)

    # --- rede ---------------------------------------------------------------

    def _esperar(self, dominio: str) -> None:
        espera = random.uniform(INTERVALO_MIN, INTERVALO_MAX)
        decorrido = time.monotonic() - self._ultimo_acesso[dominio]
        if decorrido < espera:
            time.sleep(espera - decorrido)
        self._ultimo_acesso[dominio] = time.monotonic()

    def get(self, url: str, **kwargs) -> str:
        """GET com cache, espaçamento e retry. Devolve o corpo como texto.

        Levanta SiteBloqueado, FalhaDeRede ou RespostaInvalida -- nunca
        um erro genérico, para o runner saber o que registrar.
        """
        guardado = self._ler_cache(url)
        if guardado is not None:
            log.debug("cache: %s", url)
            return guardado

        dominio = normalizar_dominio(url)
        ultimo_erro: Exception | None = None
        bloqueios = 0

        for tentativa in range(MAX_TENTATIVAS):
            self._esperar(dominio)
            try:
                r = self._http.get(url, **kwargs)
                if r.status_code in STATUS_BLOQUEIO:
                    bloqueios += 1
                    log.warning(
                        "%s respondeu %s (tentativa %d/%d) -- %s",
                        dominio, r.status_code, tentativa + 1, MAX_TENTATIVAS, url,
                    )
                    time.sleep(2**tentativa)
                    continue
                if r.status_code in STATUS_TEMPORARIO:
                    log.info(
                        "%s respondeu %s (tentativa %d/%d)",
                        dominio, r.status_code, tentativa + 1, MAX_TENTATIVAS,
                    )
                    time.sleep(2**tentativa)
                    continue
                r.raise_for_status()
                self._gravar_cache(url, r.text, r.status_code)
                return r.text
            except httpx.HTTPStatusError as e:  # noqa: PERF203
                ultimo_erro = e
                log.warning("%s status %s em %s", dominio, e.response.status_code, url)
                break  # 4xx que não é bloqueio não melhora com retry
            except httpx.TimeoutException as e:
                ultimo_erro = e
                log.warning(
                    "timeout em %s (tentativa %d/%d)", url, tentativa + 1, MAX_TENTATIVAS
                )
                time.sleep(2**tentativa)
            except httpx.HTTPError as e:
                ultimo_erro = e
                log.warning("erro de rede em %s: %s", url, type(e).__name__)
                time.sleep(2**tentativa)

        if bloqueios:
            raise SiteBloqueado(
                f"{dominio} barrou {bloqueios} de {MAX_TENTATIVAS} tentativas", url
            ) from ultimo_erro
        raise FalhaDeRede(
            f"falhou apos {MAX_TENTATIVAS} tentativas: {url} ({ultimo_erro})", url
        ) from ultimo_erro

    def get_json(self, url: str, **kwargs) -> dict | list:
        corpo = self.get(url, **kwargs)
        try:
            return json.loads(corpo)
        except ValueError as e:
            log.warning("resposta nao e JSON (%d bytes) em %s", len(corpo), url)
            raise RespostaInvalida(f"JSON invalido em {url}: {e}", url) from e

    def post_json(self, url: str, corpo: dict, **kwargs) -> dict | list:
        """POST de JSON. Nunca passa pelo cache.

        A simulação de frete é o caso: a resposta depende do CEP e do
        estoque no instante da consulta, e é justamente o que não pode
        ser reaproveitado de outro dia.
        """
        dominio = normalizar_dominio(url)
        ultimo_erro: Exception | None = None

        for tentativa in range(MAX_TENTATIVAS):
            self._esperar(dominio)
            try:
                r = self._http.post(url, json=corpo, **kwargs)
                if r.status_code in STATUS_BLOQUEIO:
                    log.warning("%s respondeu %s no POST %s", dominio, r.status_code, url)
                    raise SiteBloqueado(f"{dominio} barrou o POST {url}", url)
                if r.status_code in STATUS_TEMPORARIO:
                    time.sleep(2**tentativa)
                    continue
                r.raise_for_status()
                try:
                    return r.json()
                except ValueError as e:
                    raise RespostaInvalida(f"JSON invalido em {url}: {e}", url) from e
            except httpx.HTTPError as e:  # noqa: PERF203
                ultimo_erro = e
                log.warning("POST falhou em %s: %s", url, type(e).__name__)
                time.sleep(2**tentativa)

        raise FalhaDeRede(f"POST falhou apos {MAX_TENTATIVAS} tentativas: {url}", url) from ultimo_erro

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "Cliente":
        return self

    def __exit__(self, *_) -> None:
        self.close()
