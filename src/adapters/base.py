"""O contrato que todo executor de site implementa.

Quem escreve adapter não precisa saber nada de matching.
Quem escreve matching não precisa saber nada de VTEX.
Ambos conversam pelo ProdutoBruto.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.core.http import Cliente
from src.models import Fornecedor, ProdutoBruto


class Executor(ABC):
    """Um executor é instanciado UMA VEZ por site e reutilizado.

    Isso é deliberado: a sessão (HTTP ou navegador) é o recurso caro.
    Nunca instancie um executor por item.
    """

    plataforma: str = "desconhecida"

    def __init__(self, fornecedor: Fornecedor, cliente: Cliente) -> None:
        self.fornecedor = fornecedor
        self.cliente = cliente

    # --- Etapa 2: varredura -------------------------------------------------

    @abstractmethod
    def buscar(self, termo: str) -> list[ProdutoBruto]:
        """Busca um termo na loja e devolve os produtos encontrados.

        Não filtra nem pontua nada: isso é trabalho do matching.
        """

    # --- Etapa 3: coleta ----------------------------------------------------

    def detalhar(self, url_produto: str) -> ProdutoBruto:
        """Preço e desconto na página do produto.

        O padrão serve para plataformas cuja busca já devolve preço
        confiável. Sobrescreva onde a listagem mente.
        """
        raise NotImplementedError

    def cotar_frete(self, url_produto: str, cep: str) -> tuple[float | None, str]:
        """Devolve (valor, observação) para 1 unidade naquele CEP.

        Quantidade é sempre 1, então não é preciso montar carrinho: o
        campo de CEP da própria página do produto basta.
        """
        raise NotImplementedError

    def capturar_print(self, url_produto: str, cep: str, destino: str) -> str:
        """Print DEPOIS do frete carregar, com preço e frete na mesma imagem.

        Print só do produto não valida entrega, que é o que o
        solicitante quer conferir.
        """
        raise NotImplementedError

    # --- ciclo de vida ------------------------------------------------------

    def abrir(self) -> None:
        """Sessão, CEP, cookies. Chamado uma vez antes do lote."""

    def fechar(self) -> None:
        """Chamado uma vez depois do lote, mesmo se houve erro."""

    def __enter__(self):
        self.abrir()
        return self

    def __exit__(self, *_):
        self.fechar()
