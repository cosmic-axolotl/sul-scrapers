"""Classificação e cotação de frete. A parte mais trabalhosa do projeto.

Frete não é um valor, é um comportamento: o mesmo site pode entregar nos
três estados com preços diferentes, ter frete grátis nacional, ou grátis
acima de um valor que uma unidade nunca alcança.

Daí a separação em dois momentos:
  classificar_site()   uma vez por fornecedor, grava `modo_frete`
  cotar_produto()      só quando o modo exigir
"""

from __future__ import annotations

from src.core.log import obter
from src.models import CEPS_SUL, Fornecedor, ModoFrete

log = obter(__name__)

# Um CEP fora do Sul (Av. Paulista). Sem ele não dá para distinguir
# "frete grátis para o Brasil inteiro" de "frete grátis só na região":
# nos dois casos os três CEPs do Sul dão zero.
CEP_FORA_DO_SUL = "01310100"

# Pistas de "grátis acima de X" no texto que o site devolve junto da
# cotação. Não é o valor: é o sinal de que existe um mínimo.
PISTAS_MINIMO = ("acima de", "a partir de", "compras acima", "minimo", "mínimo")


def classificar_site(
    fornecedor: Fornecedor,
    executor,
    url_produto_exemplo: str,
) -> tuple[ModoFrete, dict[str, bool]]:
    """Descobre como este site cobra frete, usando um produto representativo.

    Devolve (modo, entrega_sul). A regra:
      - todos zerados, inclusive fora do Sul  -> GRATIS_NACIONAL
      - zerados só em PR/SC/RS                -> GRATIS_REGIAO
      - cotação menciona mínimo para grátis   -> GRATIS_ACIMA_DE
      - valores diferentes por CEP            -> TABELA_POR_CEP
      - sem cotação online                    -> SOB_CONSULTA

    Uma unidade só é o que a entrega pede, então GRATIS_ACIMA_DE é, na
    prática, frete cobrado: o mínimo nunca é alcançado por 1 item.
    """
    cotacoes: dict[str, tuple[float | None, str]] = {}
    for uf, cep in CEPS_SUL.items():
        cotacoes[uf] = _cotar(executor, url_produto_exemplo, cep)

    entrega_sul = {uf: valor is not None for uf, (valor, _) in cotacoes.items()}
    valores = [valor for valor, _ in cotacoes.values() if valor is not None]
    observacoes = " ".join(obs.lower() for _, obs in cotacoes.values())

    if not valores:
        log.info("%s: nenhuma cotacao online -> SOB_CONSULTA", fornecedor.dominio)
        return ModoFrete.SOB_CONSULTA, entrega_sul

    if any(pista in observacoes for pista in PISTAS_MINIMO):
        return ModoFrete.GRATIS_ACIMA_DE, entrega_sul

    if all(v == 0 for v in valores) and len(valores) == len(CEPS_SUL):
        fora, _ = _cotar(executor, url_produto_exemplo, CEP_FORA_DO_SUL)
        if fora == 0:
            return ModoFrete.GRATIS_NACIONAL, entrega_sul
        return ModoFrete.GRATIS_REGIAO, entrega_sul

    return ModoFrete.TABELA_POR_CEP, entrega_sul


def _cotar(executor, url: str, cep: str) -> tuple[float | None, str]:
    try:
        return executor.cotar_frete(url, cep)
    except Exception as e:
        # Classificar frete é diagnóstico: um site que não coopera vira
        # SOB_CONSULTA, não uma exceção que derruba a validação inteira.
        log.debug("cotacao falhou para %s: %s", cep, type(e).__name__)
        return None, f"cotacao indisponivel ({type(e).__name__})"


def cotar_produto(
    executor,
    url_produto: str,
    uf: str,
    produto=None,
) -> tuple[float | None, str]:
    """Devolve (valor, observação) para 1 unidade naquela UF.

    Quantidade é sempre 1, então não é preciso montar carrinho: o campo
    de CEP da própria página do produto basta — e garante que preço e
    frete vieram da mesma página, que é o que o print precisa provar.
    """
    cep = CEPS_SUL[uf]
    return executor.cotar_frete(url_produto, cep, produto)
