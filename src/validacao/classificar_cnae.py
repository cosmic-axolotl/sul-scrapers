"""Regra de aprovação por CNAE. É regra em código, não critério no olho."""

from __future__ import annotations

from src.models import Status

SITUACAO_OK = "ATIVA"

DIV_ATACADO = "46"  # comércio por atacado
DIV_VAREJO = "47"  # comércio varejista

# Classes de VAREJO aceitas mesmo sem CNAE 46 nos secundários. São
# exceção à regra 1 do projeto, decidida pelo grupo em 23/09/2026:
#
#   47.53-9  eletrodomésticos e equipamentos de áudio e vídeo
#   47.59-8  artigos de uso doméstico não especificados anteriormente
#
# O motivo é a categoria EQUIPAMENTO: fogão industrial, freezer e balança
# são vendidos por loja que se registra em 47.53-9/47.59-8 e atende
# empresa do mesmo jeito. Reprovar por causa do registro deixava a
# categoria sem fornecedor suficiente para os 5 preços por item.
#
# A comparação é por CLASSE (5 dígitos), não por subclasse, para pegar
# 4759-8/01 e 4759-8/99 de uma vez.
#
# Continuam entrando pela regra da divisão 46, sem precisar de lista:
# 46.63-0, 46.65-6 e 46.69-9 (máquinas e equipamentos para uso
# industrial, comercial e não especificados).
CLASSES_VAREJO_ACEITAS = {"47539", "47598"}

# Onde cada fornecedor é varrido, derivado do CNAE e não guardado: um
# campo a mais no master sairia de sincronia na primeira edição à mão.
#
#   padrão       todo APROVADO, menos quem só entrou pela exceção de varejo
#   --varejista  só CNAE principal numa classe de CLASSES_VAREJO_ACEITAS,
#                e só os itens de data/interim/itens_varejo.csv
#
# Um site pode estar nos dois: frigo.com.br é 47.59-8 com CNAE 46
# secundário, aprovado pela regra do atacarejo desde antes da exceção.
# Já lujao.com.br (47.53-9 sem 46) só existe por causa dela -- e uma loja
# de eletrodoméstico não é fonte de EPI nem de uniforme, que são 101 dos
# 132 itens da varredura padrão.

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
      4. divisão 47 nas classes de CLASSES_VAREJO_ACEITAS também entra,
         mesmo sem 46 secundário — e também como atacarejo;
      5. o resto reprova.

    Varejo aceito sai com `flag_atacarejo = True` de propósito: ele não
    vira atacadista por decisão nossa, e a entrega precisa conseguir
    distinguir os dois depois.
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
        if principal[:5] in CLASSES_VAREJO_ACEITAS:
            return Status.APROVADO, True, (
                f"varejo {principal} aceito por decisão do grupo "
                f"(classe {principal[:5]}); só na varredura --varejista"
            )
        return Status.REPROVADO, False, f"CNAE principal {principal} é varejo puro"

    return Status.REPROVADO, False, f"CNAE principal {principal} fora do comércio"


def eh_varejista(cnae_principal: str | None) -> bool:
    """CNAE principal numa das classes de varejo aceitas (47.53-9, 47.59-8).

    É o critério do modo --varejista: entra quem é loja de varejo, tenha
    ou não CNAE 46 secundário.
    """
    return (cnae_principal or "").strip()[:5] in CLASSES_VAREJO_ACEITAS


def so_varejista(cnae_principal: str | None, cnaes_secundarios: list[str] | None) -> bool:
    """Aprovado SÓ pela exceção de varejo: classe varejista, sem 46 secundário.

    É quem fica de fora da varredura padrão. Quem tem 46 secundário já
    era aprovado como atacarejo antes da exceção existir, e continua nas
    duas varreduras.
    """
    return eh_varejista(cnae_principal) and not any(
        (c or "").startswith(DIV_ATACADO) for c in (cnaes_secundarios or [])
    )
