"""Gera o plano de coleta: a planilha da Etapa 2 virada do avesso.

A planilha por categoria (item nas linhas, fornecedores nas colunas) é
para gente ler. O que a Etapa 3 consome é uma linha por site com a
lista de itens que ele tem — assim cada site recebe só o que já se
sabe que ele vende, com a URL pronta desde a varredura.

Entrada: data/interim/achados/*.csv + fornecedores_master.csv
Saída:   data/interim/plano_coleta.csv
         data/output/{CATEGORIA}.xlsx (a visão por categoria, para humanos)

Este arquivo é gerado, nunca editado à mão. Regere toda vez que a
cobertura mudar.
"""

from __future__ import annotations

from pathlib import Path

SAIDA = Path("data/interim/plano_coleta.csv")
COLUNAS = ["dominio", "uf", "plataforma", "modo_frete", "qtd_itens", "ids_itens"]

ALVO_FONTES_POR_ITEM = 5


def consolidar_achados() -> list[dict]:
    """TODO: ler todos os achados/*.csv e deduplicar por
    (id_item, dominio, url_produto) — o mesmo produto pode casar com
    dois itens parecidos da lista."""
    raise NotImplementedError


def gerar_plano() -> None:
    """TODO: agrupar os achados por domínio, cruzar com
    fornecedores_master.csv, gravar SAIDA com ids_itens separados por '|'."""
    raise NotImplementedError


def medir_cobertura() -> dict[str, dict]:
    """Quantos itens de cada categoria já têm 5+ fontes, e quais faltam.

    É a regra de parada da prospecção e o painel de controle do
    projeto: diz quanto falta para a entrega existir e diz para a
    frente de prospecção exatamente o que procurar.

    TODO: devolver {categoria: {"completos": n, "faltando": [(id, n_fontes)]}}
    """
    raise NotImplementedError


if __name__ == "__main__":
    gerar_plano()
    for categoria, dados in medir_cobertura().items():
        print(categoria, dados)
