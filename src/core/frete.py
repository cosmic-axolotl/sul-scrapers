"""Classificação e cotação de frete. A parte mais trabalhosa do projeto.

Frete não é um valor, é um comportamento: o mesmo site pode entregar nos
três estados com preços diferentes, ter frete grátis nacional, ou grátis
acima de um valor que uma unidade nunca alcança.

Daí a separação em dois momentos:
  classificar_site()   uma vez por fornecedor, grava `modo_frete`
  cotar_produto()      só quando o modo exigir
"""

from __future__ import annotations

from src.models import CEPS_SUL, Fornecedor, ModoFrete


def classificar_site(fornecedor: Fornecedor, executor, url_produto_exemplo: str) -> ModoFrete:
    """Descobre como este site cobra frete, usando um produto representativo.

    TODO: testar os 3 CEPs de CEPS_SUL contra um produto e decidir:
      - todos zerados e sem mínimo          -> GRATIS_NACIONAL
      - zerados só em PR/SC/RS              -> GRATIS_REGIAO
      - página anuncia mínimo para grátis   -> GRATIS_ACIMA_DE
      - valores diferentes por CEP          -> TABELA_POR_CEP
      - sem cotação online                  -> SOB_CONSULTA
    """
    raise NotImplementedError


def cotar_produto(executor, url_produto: str, uf: str) -> tuple[float | None, str]:
    """Devolve (valor, observação) para 1 unidade naquela UF.

    Quantidade é sempre 1, então não é preciso montar carrinho: o campo
    de CEP da própria página do produto basta — e garante que preço e
    frete vieram da mesma página, que é o que o print precisa provar.
    """
    cep = CEPS_SUL[uf]
    return executor.cotar_frete(url_produto, cep)
