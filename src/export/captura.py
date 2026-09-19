"""Print da página do produto, com o CEP preenchido e o frete visível.

Por que isto não mora no adapter: o print é requisito de TODOS os
registros, inclusive dos sites de plataforma com API (VTEX responde
preço e frete em JSON, mas o solicitante não confere JSON). Sem um
capturador comum, cada adapter teria que subir o seu browser e a regra
de "uma sessão por site" morreria.

O navegador é um só por processo, criado na primeira chamada e
reaproveitado. Como o orquestrador roda um processo por domínio, isso já
significa um navegador por site — que é a regra do projeto.

O preenchimento de CEP é uma heurística: procura o campo pelos nomes
usuais e digita. Site que não responder a ela precisa sobrescrever
`SEL_CAMPO_CEP` no seu adapter — é para isso que o campo existe lá.
"""

from __future__ import annotations

import atexit
from pathlib import Path

from src.core.log import obter

log = obter(__name__)

# Ordem de tentativa. O primeiro que existir e for visível é usado.
SELETORES_CEP = (
    "input[name*='cep' i]",
    "input[id*='cep' i]",
    "input[placeholder*='cep' i]",
    "input[data-testid*='cep' i]",
    "input[name*='postal' i]",
)

ESPERA_APOS_CEP_MS = 4000
LARGURA, ALTURA = 1366, 900

_navegador = None
_playwright = None


class PrintIndisponivel(RuntimeError):
    """Não deu para tirar o print. O registro fica incompleto de propósito."""


def _obter_navegador():
    """Um browser por processo, aberto na primeira necessidade."""
    global _navegador, _playwright

    if _navegador is not None:
        return _navegador

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:  # pragma: no cover - depende do ambiente
        raise PrintIndisponivel(
            "playwright nao esta instalado. Rode: pip install playwright && "
            "playwright install chromium"
        ) from e

    _playwright = sync_playwright().start()
    try:
        _navegador = _playwright.chromium.launch(headless=True)
    except Exception as e:  # pragma: no cover - depende do ambiente
        raise PrintIndisponivel(
            f"nao consegui subir o chromium ({e}). Rode: playwright install chromium"
        ) from e

    atexit.register(fechar)
    return _navegador


def fechar() -> None:
    """Fecha browser e playwright. Chamado no fim do processo."""
    global _navegador, _playwright
    try:
        if _navegador is not None:
            _navegador.close()
    finally:
        _navegador = None
    try:
        if _playwright is not None:
            _playwright.stop()
    finally:
        _playwright = None


def capturar(
    url: str,
    cep: str,
    destino: str | Path,
    seletor_cep: str = "",
    seletor_resultado: str = "",
) -> Path:
    """Abre a página, preenche o CEP, espera o frete e salva o PNG.

    Devolve o caminho do arquivo. Levanta PrintIndisponivel se não deu —
    nunca devolve um caminho para um arquivo que não existe, porque a
    retomada usa a existência do arquivo como prova de que o registro
    ficou completo.
    """
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)

    navegador = _obter_navegador()
    contexto = navegador.new_context(
        viewport={"width": LARGURA, "height": ALTURA},
        locale="pt-BR",
    )
    pagina = contexto.new_page()

    try:
        pagina.goto(url, wait_until="domcontentloaded", timeout=45000)
        _aceitar_cookies(pagina)

        preenchido = _preencher_cep(pagina, cep, seletor_cep)
        if not preenchido:
            log.warning("nao achei campo de CEP em %s; print sai sem frete", url)

        if seletor_resultado:
            try:
                pagina.wait_for_selector(seletor_resultado, timeout=ESPERA_APOS_CEP_MS)
            except Exception:
                log.warning("resultado de frete nao apareceu em %s", url)
        elif preenchido:
            pagina.wait_for_timeout(ESPERA_APOS_CEP_MS)

        pagina.screenshot(path=str(destino), full_page=True)
    except PrintIndisponivel:
        raise
    except Exception as e:
        raise PrintIndisponivel(f"print falhou em {url}: {type(e).__name__}: {e}") from e
    finally:
        pagina.close()
        contexto.close()

    if not destino.exists() or destino.stat().st_size == 0:
        raise PrintIndisponivel(f"print saiu vazio: {destino}")

    return destino


def _preencher_cep(pagina, cep: str, seletor_cep: str = "") -> bool:
    seletores = (seletor_cep,) + SELETORES_CEP if seletor_cep else SELETORES_CEP
    for seletor in seletores:
        try:
            campo = pagina.locator(seletor).first
            if campo.count() == 0 or not campo.is_visible():
                continue
            campo.scroll_into_view_if_needed(timeout=3000)
            campo.fill(cep, timeout=5000)
            campo.press("Enter")
            return True
        except Exception:  # noqa: PERF203 - seletor que não serve, tenta o próximo
            continue
    return False


def _aceitar_cookies(pagina) -> None:
    """Banner de cookies costuma cobrir o preço. Tenta fechar, sem insistir."""
    for texto in ("Aceitar", "Aceito", "Concordo", "Entendi", "OK"):
        try:
            botao = pagina.get_by_role("button", name=texto, exact=False).first
            if botao.count() and botao.is_visible():
                botao.click(timeout=2000)
                return
        except Exception:  # noqa: PERF203
            continue
