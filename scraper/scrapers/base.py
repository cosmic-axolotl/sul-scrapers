from abc import ABC, abstractmethod
from typing import Optional
from playwright.sync_api import Page
from database import Produto


class BaseScraper(ABC):
    nome_fornecedor: str = "base"

    def __init__(self, page: Page):
        self.page = page

    @abstractmethod
    def definir_cep(self, cep: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def extrair_produtos_da_pagina(
        self, categoria: str, url: str, palavras_chave: Optional[list[str]] = None
    ) -> list[Produto]:
        raise NotImplementedError
