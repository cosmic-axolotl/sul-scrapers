"""Fallback para lojas sem plataforma reconhecida.

Só use quando o conteúdo depende de JavaScript, existe desafio de bot
ou o campo de CEP não tem endpoint acessível. Uma busca via navegador
custa ~4 s contra ~200 ms de uma chamada JSON.
"""

from __future__ import annotations

from src.adapters.base import Executor
from src.models import ProdutoBruto


class PlaywrightExecutor(Executor):
    plataforma = "desconhecida"

    # Preencher por site. Descubra com debug_inspecionar.py do repo de
    # referência — nunca copie seletor de outro site sem confirmar, nem
    # quando as duas lojas rodam na mesma plataforma.
    SEL_BUSCA_URL = "{base}/busca?q={termo}"
    SEL_CARD = ""
    SEL_TITULO = ""
    SEL_PRECO = ""
    SEL_CAMPO_CEP = ""
    SEL_RESULTADO_FRETE = ""

    def abrir(self) -> None:
        """TODO: subir async_playwright com launch_persistent_context,
        reaproveitando o perfil salvo em credentials/perfil_{dominio}/.

        O repo de referência já faz isso em setup_sessao.py — o CEP é
        configurado uma vez, à mão, e a sessão é reutilizada. Copiar de
        lá em vez de reescrever.
        """
        raise NotImplementedError

    def buscar(self, termo: str) -> list[ProdutoBruto]:
        raise NotImplementedError

    def fechar(self) -> None:
        """TODO: fechar contexto e browser."""
