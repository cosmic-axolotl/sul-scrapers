"""Etapa 1 — transforma candidatos em fornecedores aprovados ou reprovados.

Entrada:  data/raw/*.xlsx (as duas planilhas) + leads da prospecção
Saída:    data/interim/fornecedores_master.csv

Roda em lote, é rápida em máquina, e não termina num dia: a frente de
prospecção continua alimentando a entrada até o fim do projeto.
"""

from __future__ import annotations

from pathlib import Path

from src.core.http import Cliente, normalizar_dominio
from src.core.plataforma import detectar
from src.models import Fornecedor, Status
from src.validacao.classificar_cnae import decidir
from src.validacao.consultar_cnpj import consultar, normalizar
from src.validacao.extrair_cnpj import extrair_do_site

SAIDA = Path("data/interim/fornecedores_master.csv")

# A planilha do colega tem 37 valores livres em "Status atual".
# Isso é impossível de filtrar em código: mapeie para os três do enum
# e jogue o texto original para a coluna `motivo`.
MAPA_STATUS_LEGADO = {
    "APROVADO": Status.APROVADO,
    "APROVADO ESTRITO": Status.APROVADO,
    "EXCLUÍDO": Status.REPROVADO,
    "PENDENTE": Status.PENDENTE,
}


def unificar_planilhas() -> list[Fornecedor]:
    """Junta as duas bases pelo domínio normalizado.

    base_fornecedores_regiao_sul.xlsx     -> 102 empresas, SEM CNPJ
    fornecedores_atacadistas_...xlsx      -> 114 empresas, com CNPJ e CNAE

    TODO: ler com pandas, normalizar domínio, deduplicar, preservar o
    que a segunda planilha já resolveu e marcar o resto como PENDENTE.
    """
    raise NotImplementedError


def validar(fornecedor: Fornecedor, cliente: Cliente) -> Fornecedor:
    """Aplica o pipeline de validação a um fornecedor. Idempotente."""
    if not fornecedor.cnpj:
        fornecedor.cnpj = extrair_do_site(fornecedor.url_base, cliente)

    if not fornecedor.cnpj:
        fornecedor.status = Status.PENDENTE
        fornecedor.motivo = "CNPJ não encontrado no site"
        return fornecedor

    dados = consultar(fornecedor.cnpj, cliente)
    if not dados:
        fornecedor.status = Status.PENDENTE
        fornecedor.motivo = "consulta de CNPJ falhou"
        return fornecedor

    campos = normalizar(dados)
    fornecedor.cnae_principal = campos["cnae_principal"]
    fornecedor.cnaes_secundarios = campos["cnaes_secundarios"]
    fornecedor.situacao_cadastral = campos["situacao_cadastral"]

    status, atacarejo, motivo = decidir(
        fornecedor.cnae_principal,
        fornecedor.cnaes_secundarios,
        fornecedor.situacao_cadastral,
    )
    fornecedor.status = status
    fornecedor.flag_atacarejo = atacarejo
    fornecedor.motivo = motivo
    fornecedor.eh_atacadista = status is Status.APROVADO and not atacarejo

    # A detecção de plataforma só roda em quem passou: ela custa uma
    # requisição e não adianta saber a plataforma de um reprovado.
    if status is Status.APROVADO:
        fornecedor.plataforma = detectar(fornecedor.url_base, cliente)

    return fornecedor


def testar_entrega(fornecedor: Fornecedor, cliente: Cliente) -> Fornecedor:
    """Confirma entrega em PR, SC e RS e classifica o modo de frete.

    É o passo mais lento da etapa, por isso vem por último, rodando só
    sobre quem já passou no filtro de CNAE.

    TODO: usar o executor da plataforma (frete via API onde houver) e
    gravar `entrega_sul` e `modo_frete`.
    """
    raise NotImplementedError


def main() -> None:
    fornecedores = unificar_planilhas()
    with Cliente() as cliente:
        for f in fornecedores:
            f.dominio = normalizar_dominio(f.url_base)
            validar(f, cliente)
    # TODO: gravar SAIDA com csv.DictWriter
    print(f"{sum(1 for f in fornecedores if f.status is Status.APROVADO)} aprovados")


if __name__ == "__main__":
    main()
