import os
import re
import logging
from typing import Optional
from bs4 import BeautifulSoup
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

import config as config
from database import Produto
from scrapers.base import BaseScraper
from utils.parsers import (
    parse_preco,
    extrair_quantidade_e_unidade,
    extrair_marca,
)

logger = logging.getLogger(__name__)


class StockScraper(BaseScraper):
    nome_fornecedor = "stock"

    SEL_INPUT_CEP = "input[placeholder*='CEP' i], input[name*='cep' i]"
    SEL_BOTAO_CONFIRMAR_CEP = "button:has-text('Buscar'), button:has-text('Confirmar')"
    SEL_BOTAO_ESCOLHER_LOJA = (
        "button:has-text('Selecionar'), button:has-text('Escolher')"
    )

    SEL_CARD_PRODUTO = ".vip-card-produto"
    SEL_NOME_PRODUTO = "[data-cy='vip-card-produto-descricao']"
    SEL_LINK_PRODUTO = "a[title]"
    SEL_PRECO = "[data-cy='preco']"

    def definir_cep(self, cep: str) -> None:
        if (
            config.USAR_SESSAO_SALVA
            and os.path.isdir(config.PERFIL_NAVEGADOR_DIR)
            and os.listdir(config.PERFIL_NAVEGADOR_DIR)
        ):
            logger.info("Perfil persistente detectado — pulando modal de CEP.")
            return

        logger.info("Abrindo StokOnline para definir CEP...")
        self.page.goto("https://www.stokonline.com.br", timeout=config.NAV_TIMEOUT_MS)

        try:
            self.page.wait_for_selector(self.SEL_INPUT_CEP, timeout=8000)
            self.page.fill(self.SEL_INPUT_CEP, cep)
            self.page.click(self.SEL_BOTAO_CONFIRMAR_CEP)
            self.page.wait_for_timeout(2000)

            if self.page.locator(self.SEL_BOTAO_ESCOLHER_LOJA).count() > 0:
                self.page.locator(self.SEL_BOTAO_ESCOLHER_LOJA).first.click()
                self.page.wait_for_timeout(1500)

            logger.info("CEP definido: %s", cep)
        except PlaywrightTimeoutError:
            logger.warning("Modal de CEP não apareceu (timeout).")

    def _extrair_precos_e_atacado(self, card) -> dict:
        resultado = {
            "preco_varejo": None,
            "preco_atacado": None,
            "qtd_minima_atacado": None,
            "desconto": None,
        }
        preco_el = card.select_one(self.SEL_PRECO)
        if preco_el:
            resultado["preco_varejo"] = parse_preco(preco_el.get_text(strip=True))
        else:
            textos_rs = card.find_all(string=re.compile(r"R\$"))
            for t in textos_rs:
                val = parse_preco(str(t))
                if val is not None:
                    resultado["preco_varejo"] = val
                    break
        return resultado

    def _rolar_scroll_infinito(self) -> None:
        logger.info("Iniciando scroll infinito...")
        scroll_count = 0
        max_scrolls = 30
        last_height = self.page.evaluate("document.body.scrollHeight")

        while scroll_count < max_scrolls:
            self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            self.page.wait_for_timeout(2500)
            new_height = self.page.evaluate("document.body.scrollHeight")

            if new_height == last_height:
                self.page.mouse.wheel(0, -500)
                self.page.wait_for_timeout(500)
                self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                self.page.wait_for_timeout(2000)
                new_height = self.page.evaluate("document.body.scrollHeight")
                if new_height == last_height:
                    break

            last_height = new_height
            scroll_count += 1

    def extrair_produtos_da_pagina(
        self, categoria: str, url: str, palavras_chave: Optional[list[str]] = None
    ) -> list[Produto]:
        logger.info("Coletando categoria '%s' -> %s", categoria, url)
        self.page.goto(url, timeout=config.NAV_TIMEOUT_MS)
        self.page.wait_for_timeout(3000)

        self._rolar_scroll_infinito()

        soup = BeautifulSoup(self.page.content(), "html.parser")
        produtos: list[Produto] = []
        cards = soup.select(self.SEL_CARD_PRODUTO)

        for i, card in enumerate(cards):
            nome_el = card.select_one(self.SEL_NOME_PRODUTO)
            if not nome_el:
                continue

            nome = nome_el.get("title") or nome_el.get_text(strip=True)

            if palavras_chave and not any(
                pk.lower() in nome.lower() for pk in palavras_chave
            ):
                continue

            dados_preco = self._extrair_precos_e_atacado(card)
            preco_varejo = dados_preco["preco_varejo"]
            if preco_varejo is None:
                continue

            quantidade, unidade = extrair_quantidade_e_unidade(nome)
            marca = extrair_marca(nome)

            link_el = card.select_one(self.SEL_LINK_PRODUTO)
            url_produto = None
            if link_el and link_el.get("href"):
                href = link_el["href"]
                url_produto = (
                    href
                    if href.startswith("http")
                    else f"https://www.stokonline.com.br{href}"
                )

            caminho_print = None
            if getattr(config, "SALVAR_PRINTS_ITENS", False):
                try:
                    os.makedirs(config.PRINTS_DIR, exist_ok=True)
                    nome_seguro = re.sub(r'[\\/*?:"<>|]', "", nome).replace(" ", "_")[
                        :60
                    ]
                    caminho_print = os.path.join(
                        config.PRINTS_DIR, f"idx_{i}_{nome_seguro}.png"
                    )

                    card_locator = self.page.locator(self.SEL_CARD_PRODUTO).nth(i)
                    card_locator.evaluate(
                        "el => el.scrollIntoView({block: 'center', inline: 'center'})"
                    )
                    self.page.wait_for_timeout(100)
                    card_locator.screenshot(path=caminho_print)
                except Exception as e:
                    logger.warning("Falha ao salvar print de '%s': %s", nome, e)

            produtos.append(
                Produto(
                    fornecedor=self.nome_fornecedor,
                    categoria=categoria,
                    nome=nome,
                    marca=marca,
                    preco=preco_varejo,
                    quantidade=quantidade,
                    unidade=unidade,
                    preco_atacado=dados_preco["preco_atacado"],
                    qtd_minima_atacado=dados_preco["qtd_minima_atacado"],
                    desconto=dados_preco["desconto"],
                    url_produto=url_produto,
                    imagem_print=caminho_print,
                )
            )

        return produtos
