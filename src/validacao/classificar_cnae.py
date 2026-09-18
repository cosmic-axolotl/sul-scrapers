"""Regra de aprovação por CNAE. É regra em código, não critério no olho."""

from __future__ import annotations

from src.models import Status

SITUACAO_OK = "ATIVA"

DIV_ATACADO = "46"  # comércio por atacado
DIV_VAREJO = "47"  # comércio varejista

# PENDÊNCIA: os 2 itens de PNEU precisam de distribuidora de autopeças, que
# costuma ter CNAE do grupo 4530-7 (divisão 45) e hoje é reprovada aqui.
# Parte das subclasses de 4530-7 é atacado e parte é varejo. Conferir na
# tabela oficial do CNAE quais são atacado e listar abaixo — não chutar.
GRUPO_AUTOPECAS = "45307"
SUBCLASSES_AUTOPECAS_ATACADO: set[str] = set()  # preencher após conferir


def decidir(
    cnae_principal: str | None,
    cnaes_secundarios: list[str] | None,
    situacao_cadastral: str | None,
) -> tuple[Status, bool, str]:
    """Devolve (status, flag_atacarejo, motivo).

    Ordem das regras:
      1. situação diferente de ATIVA reprova, mesmo com CNAE certo;
      2. divisão 46 no principal aprova;
      3. divisão 47 no principal com algum 46 nos secundários = atacarejo;
      4. o resto reprova.
    """
    situacao = (situacao_cadastral or "").strip().upper()
    if not situacao:
        return Status.PENDENTE, False, "situação cadastral desconhecida"
    if situacao != SITUACAO_OK:
        return Status.REPROVADO, False, f"CNPJ {situacao.lower()}"

    principal = (cnae_principal or "").strip()
    if not principal:
        return Status.PENDENTE, False, "CNAE principal desconhecido"

    secundarios = cnaes_secundarios or []

    if principal.startswith(DIV_ATACADO):
        return Status.APROVADO, False, f"CNAE principal {principal} (atacado)"

    if principal.startswith(GRUPO_AUTOPECAS):
        if principal in SUBCLASSES_AUTOPECAS_ATACADO:
            return Status.APROVADO, False, f"CNAE {principal} (autopeças, atacado)"
        return Status.PENDENTE, False, (
            f"CNAE {principal} é autopeças — conferir se a subclasse é atacado "
            "antes de aprovar (ver SUBCLASSES_AUTOPECAS_ATACADO)"
        )

    if principal.startswith(DIV_VAREJO):
        if any(c.startswith(DIV_ATACADO) for c in secundarios):
            return Status.APROVADO, True, f"varejo {principal} com CNAE 46 secundário (atacarejo)"
        return Status.REPROVADO, False, f"CNAE principal {principal} é varejo puro"

    return Status.REPROVADO, False, f"CNAE principal {principal} fora do comércio"
