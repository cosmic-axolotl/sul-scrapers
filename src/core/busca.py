"""Como se escreve uma busca de loja. Um lugar só, para as duas entradas.

A configuração de busca chega por dois caminhos, e os dois são normais:

    planilha em data/raw/leads/   -> a prospecção preenche duas colunas
    fornecedores_master.csv       -> alguém abre o CSV e digita direto

O segundo é o que acontece quando se confere 89 lojas numa tarde: é mais
rápido editar a tabela final do que voltar à planilha e reprocessar. Só
que ele pula toda a normalização do primeiro — e o defeito que isso
produz é silencioso. Uma URL sem `{termo}` não dá erro nenhum: ela busca
a mesma coisa 132 vezes e registra o mesmo resultado para todos os
itens, como se a loja vendesse tudo.

Por isso a normalização mora aqui e roda na LEITURA, não na escrita.
Quem digitar `/busca?q=` no CSV recebe o mesmo tratamento de quem
digitou na planilha.
"""

from __future__ import annotations

import re

from src.core.log import obter

log = obter(__name__)

# Nomes de parâmetro que carregam o termo numa URL de busca. Servem para
# entender o que a pessoa colou: quem confere à mão cola a URL que
# funcionou, com o termo de teste dentro dela.
CHAVES_DE_BUSCA = ("q", "s", "ft", "busca", "search", "termo", "query",
                   "palavra", "keyword", "text", "pesquisa")


def molde_de_busca(texto: str, dominio: str = "") -> str:
    """O que a pessoa escreveu -> molde com {termo}, pronto para a varredura.

    Aceita as três formas que aparecem quando alguém confere um site na
    mão e anota o resultado:

        https://loja.com.br/busca?q={termo}   já veio pronto
        https://loja.com.br/busca?q=panela    a URL de teste que funcionou
        /busca?q=                             só o caminho, sem o termo

    No segundo caso o valor do parâmetro de busca é trocado por {termo} --
    é o que "panela" está fazendo ali. Sem parâmetro reconhecível e sem
    {termo}, a configuração é RECUSADA com aviso, porque usá-la como
    está é pior do que não ter nenhuma: a varredura repetiria a mesma
    busca em todos os itens e nada no resultado denunciaria isso.
    """
    bruto = (texto or "").strip()
    if not bruto:
        return ""

    molde = bruto if bruto.startswith(("http", "{base}")) else \
        "{base}/" + bruto.lstrip("/")
    if "{termo}" in molde:
        return molde

    chaves = "|".join(CHAVES_DE_BUSCA)
    trocado = re.sub(rf"([?&](?:{chaves})=)[^&]*", r"\1{termo}", molde,
                     count=1, flags=re.IGNORECASE)
    if trocado != molde:
        return trocado
    if molde.endswith("="):
        return molde + "{termo}"

    log.warning(
        "%s: não sei onde entra o termo em %r; a URL de busca foi ignorada. "
        "Escreva {termo} onde vai a palavra buscada, ex.: /busca?q={termo}",
        dominio or "(sem domínio)", bruto,
    )
    return ""


def seletor_de_busca(texto: str, dominio: str = "") -> str:
    """Confere que o seletor é seletor, e não uma URL no campo errado.

    As duas colunas ficam lado a lado na planilha e no CSV, e trocá-las
    custa uma varredura inteira: o seletor vira URL de busca inválida e
    a URL vira um seletor que não casa com nada.
    """
    limpo = (texto or "").strip()
    if not limpo:
        return ""
    if limpo.startswith(("http://", "https://", "{base}")):
        log.warning(
            "%s: %r parece uma URL, não um seletor CSS -- as duas colunas "
            "estão trocadas? O seletor foi ignorado.", dominio or "(sem domínio)",
            limpo[:60],
        )
        return ""
    return limpo
