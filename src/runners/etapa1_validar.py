"""Etapa 1 — transforma candidatos em fornecedores aprovados ou reprovados.

Entrada:  data/raw/*.xlsx (as duas planilhas) + leads da prospecção
          (todo .csv/.xlsx de data/raw/leads/, TODAS as abas de cada um)
Saída:    data/interim/fornecedores_master.csv
          data/output/validacao_{arquivo}_{aba}.xlsx  (uma por aba de origem)

Roda em lote, é rápida em máquina, e não termina num dia: a frente de
prospecção continua alimentando a entrada até o fim do projeto.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from src.core.http import Cliente, ErroHTTP, SiteBloqueado, normalizar_dominio
from src.core.log import obter
from src.core.plataforma import detectar
from src.core.busca import molde_de_busca, seletor_de_busca
from src.core.tabelas import gravar_fornecedores, ler_fornecedores
from src.export import validacao_por_aba
from src.models import Fornecedor, Plataforma, Status
from src.validacao.classificar_cnae import decidir
from src.validacao.consultar_cnpj import consultar, normalizar
from src.validacao.extrair_cnpj import extrair_do_site

log = obter(__name__)

SAIDA = Path("data/interim/fornecedores_master.csv")
# Empresa pesquisada, com CNPJ, que não tem site conhecido. Não entra no
# master (a chave primária é o domínio), mas não pode se perder.
SEM_SITE = Path("data/interim/sem_site.csv")

BASE_SUL = Path("data/raw/base_fornecedores_regiao_sul.xlsx")
BASE_ATACADISTAS = Path(
    "data/raw/fornecedores_atacadistas_utensilios_sul_consolidado_1.xlsx"
)

# Onde a prospecção larga o que achar. Qualquer .csv ou .xlsx, quantos
# arquivos quiser, com as colunas no nome que a pessoa preferir.
LEADS = Path("data/raw/leads")

# Sinônimos aceitos para cada campo, já normalizados (minúsculo, sem
# acento). A comparação é por palavra: "Site Oficial" casa com "site",
# "Link (clicável)" casa com "link", "Razão Social" casa com "razao".
SINONIMOS_SITE = {"site", "url", "dominio", "link", "endereco", "pagina",
                  "website", "webpage", "portal", "ecommerce"}
SINONIMOS_NOME = {"nome", "empresa", "fornecedor", "razao", "estabelecimento"}
SINONIMOS_UF = {"uf", "estado"}
SINONIMOS_CNPJ = {"cnpj"}
SINONIMOS_CIDADE = {"cidade", "municipio"}

# Configuração de busca conferida à mão, uma linha por site. Estas duas
# NÃO são reconhecidas por sinônimo solto: "URL de busca" tem a palavra
# "url" e seria confundida com a coluna do site. A regra é composta --
# o nome da coluna precisa ter uma palavra de cada grupo.
PALAVRAS_BUSCA = {"busca", "buscar", "pesquisa", "pesquisar", "search"}
PALAVRAS_ENDERECO = {"url", "link", "endereco", "rota", "caminho"}
PALAVRAS_SELETOR = {"seletor", "selector", "css", "campo", "input"}

# A planilha do colega tem 37 valores livres em "Status atual".
# Isso é impossível de filtrar em código: mapeie para os três do enum
# e jogue o texto original para a coluna `motivo`.
MAPA_STATUS_LEGADO = {
    "APROVADO": Status.APROVADO,
    "APROVADO ESTRITO": Status.APROVADO,
    "EXCLUÍDO": Status.REPROVADO,
    "PENDENTE": Status.PENDENTE,
}

UFS_SUL = ("PR", "SC", "RS")

UFS_BR = frozenset((
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS",
    "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC",
    "SP", "SE", "TO",
))


def _status_legado(texto: str) -> Status:
    """"EXCLUÍDO - ECOMMERCE", "PENDENTE SITE", "APROVADO ESTRITO"...

    Os 37 valores livres não cabem num dicionário exato. O prefixo
    resolve todos, e o texto original vai inteiro para `motivo`.
    """
    t = (texto or "").strip().upper()
    if t in MAPA_STATUS_LEGADO:
        return MAPA_STATUS_LEGADO[t]
    if t.startswith("APROVADO"):
        return Status.APROVADO
    if t.startswith(("EXCLU", "REPROV")):
        return Status.REPROVADO
    return Status.PENDENTE


def _texto(valor) -> str:
    import pandas as pd

    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return ""
    texto = str(valor).strip()
    return "" if texto.lower() in ("nan", "nat", "none") else texto


def _sim(valor) -> bool | None:
    t = _texto(valor).upper()
    if t.startswith("SIM"):
        return True
    if t.startswith(("NAO", "NÃO", "N/A")):
        return False
    return None


class PlanilhaSemColunaDeSite(ValueError):
    """Aba de lead com linhas, mas sem nenhuma coluna de site.

    É exceção, e não um aviso, de propósito. Antes desta classe existir,
    uma planilha com a coluna chamada "URL" em vez de "Site Oficial"
    produzia zero fornecedores sem erro nenhum: a pessoa rodava a etapa,
    via "0 aprovados" e ia procurar defeito no CNPJ ou na rede.

    Vale por ABA, não por arquivo: numa planilha de seis abas, cinco
    lidas e uma ignorada em silêncio dão o mesmo tipo de prejuízo. Aba
    vazia não conta -- ela não tem lead para perder.
    """


def _chave(texto: str) -> str:
    """Nome de coluna normalizado para comparação."""
    from unidecode import unidecode

    return re.sub(r"\s+", " ", unidecode(str(texto or "")).strip().lower())


def achar_coluna(colunas, sinonimos: set[str]) -> str | None:
    """A primeira coluna cujo nome bate com algum sinônimo.

    Duas passadas: nome idêntico a um sinônimo ganha de nome que apenas
    contém um. Sem isso, numa planilha com "Site" e "Site do fabricante"
    a escolha dependeria da ordem das colunas.
    """
    normalizadas = [(c, _chave(c)) for c in colunas]

    for coluna, nome in normalizadas:
        if nome in sinonimos:
            return coluna

    for coluna, nome in normalizadas:
        palavras = {p for p in re.split(r"[^a-z0-9]+", nome) if p}
        if palavras & sinonimos:
            return coluna

    return None


def achar_coluna_composta(colunas, *grupos: set[str]) -> str | None:
    """A coluna cujo nome tem uma palavra de CADA grupo.

    "URL de busca" precisa casar com endereço E com busca; "Site" não
    pode casar com nada disso. Sinônimo solto não serve aqui: a palavra
    "url" sozinha é a coluna do site, e trocar as duas faria a varredura
    tentar buscar na home de todo mundo.
    """
    for coluna in colunas:
        palavras = {p for p in re.split(r"[^a-z0-9]+", _chave(coluna)) if p}
        if all(palavras & grupo for grupo in grupos):
            return coluna
    return None


def nome_origem(arquivo: Path, aba: str = "") -> str:
    """Rótulo estável de onde a linha veio: "lista_sites.xlsx :: EPI".

    É o que liga o fornecedor no master à aba que o trouxe, e o que a
    planilha de conferência usa para se nomear. CSV não tem aba, então
    fica só o nome do arquivo.
    """
    return f"{arquivo.name} :: {aba}" if aba else arquivo.name


def _sigla_uf(texto: str) -> str:
    """Tira a UF de um texto livre: "São José / SC" -> "SC".

    A coluna da prospecção costuma ser "Cidade / UF", e o sinônimo "uf"
    casa com ela -- sem isto o campo virava "SÃO JOSÉ/SC" e a planilha
    de conferência saía com cidade dentro da coluna de estado.

    Texto sem sigla reconhecível volta como estava (em maiúsculas): é o
    comportamento antigo, e "Paraná" por extenso ainda diz algo a quem
    lê. A última sigla ganha, porque "Cidade / UF" termina na UF.
    """
    limpo = texto.strip().upper()
    encontradas = [p for p in re.split(r"[^A-Za-zÀ-Ü]+", limpo) if p in UFS_BR]
    return encontradas[-1] if encontradas else limpo


def _ler_csv(arquivo: Path):
    """CSV com o separador que vier: ',' , ';' (Excel pt-BR) ou tab."""
    import pandas as pd

    for separador in (",", ";", "\t"):
        try:
            df = pd.read_csv(arquivo, sep=separador, dtype=str)
        except Exception:  # noqa: PERF203
            continue
        if len(df.columns) > 1 or separador == "\t":
            return df
    return pd.read_csv(arquivo, dtype=str)


def _ler_tabelas(arquivo: Path) -> list[tuple[str, object]]:
    """[(nome da aba, tabela)] -- TODAS as abas, tudo como texto.

    Ler só a primeira aba era silêncio caro: `lista_sites.xlsx` tem seis
    (EPI, UNIFORME, COMBUSTIVEL, VEÍCULOS, Utensílios, Equipamentos) e o
    pipeline enxergava 12 das 134 empresas, sem erro nenhum -- o mesmo
    defeito que `PlanilhaSemColunaDeSite` existe para impedir, só que uma
    camada abaixo.

    O nome da aba não é decoração: ele vira a `origem` do fornecedor e o
    nome da planilha de conferência que a etapa devolve no fim.
    """
    import pandas as pd

    if arquivo.suffix.lower() == ".csv":
        return [("", _ler_csv(arquivo))]

    return list(pd.read_excel(arquivo, sheet_name=None, dtype=str).items())


def ler_leads(pasta: Path = LEADS) -> list[Fornecedor]:
    """Lê todo .csv/.xlsx de data/raw/leads/, no formato que vier.

    A prospecção não deveria ter que aprender um layout: o que o
    pipeline precisa de verdade é UMA coluna com o site. O resto (nome,
    UF, CNPJ, cidade) entra se estiver lá e é ignorado se não estiver.

    Todo lead entra como PENDENTE — quem decide é o pipeline de CNPJ.
    """
    if not pasta.exists():
        return []

    arquivos = sorted(
        a for a in pasta.iterdir()
        if a.is_file()
        and a.suffix.lower() in (".csv", ".xlsx", ".xls")
        and not a.name.startswith(("~$", "."))
    )
    if not arquivos:
        return []

    leads: list[Fornecedor] = []
    problemas: list[str] = []

    for arquivo in arquivos:
        try:
            tabelas = _ler_tabelas(arquivo)
        except Exception as e:
            problemas.append(f"{arquivo.name}: não consegui ler ({type(e).__name__}: {e})")
            continue

        for aba, df in tabelas:
            origem = nome_origem(arquivo, aba)

            # Aba vazia é capa, rascunho ou sobra do Excel -- não é lead
            # perdido, e transformar isso em erro pararia a etapa inteira
            # por causa de uma planilha em branco.
            if df.empty:
                continue

            # As colunas de configuração saem do bolo ANTES de procurar a
            # do site: "URL de busca" não pode virar a coluna de site.
            coluna_url_busca = achar_coluna_composta(
                df.columns, PALAVRAS_ENDERECO, PALAVRAS_BUSCA)
            coluna_seletor = achar_coluna_composta(
                df.columns, PALAVRAS_SELETOR, PALAVRAS_BUSCA)
            restantes = [c for c in df.columns
                         if c not in (coluna_url_busca, coluna_seletor)]

            coluna_site = achar_coluna(restantes, SINONIMOS_SITE)
            if coluna_site is None:
                problemas.append(
                    f"{origem}: nenhuma coluna de site. "
                    f"Colunas encontradas: {list(df.columns)}. "
                    f"Esperava alguma com: {', '.join(sorted(SINONIMOS_SITE))}"
                )
                continue

            coluna_nome = achar_coluna(restantes, SINONIMOS_NOME)
            coluna_uf = achar_coluna(restantes, SINONIMOS_UF)
            coluna_cnpj = achar_coluna(restantes, SINONIMOS_CNPJ)

            lidos = sem_dominio = 0
            for _, linha in df.iterrows():
                url = _texto(linha.get(coluna_site))
                dominio = normalizar_dominio(url)
                if not dominio:
                    sem_dominio += 1
                    continue
                leads.append(Fornecedor(
                    nome=_texto(linha.get(coluna_nome)) if coluna_nome else "",
                    dominio=dominio,
                    url_base=_raiz(url, dominio),
                    uf=(_sigla_uf(_texto(linha.get(coluna_uf))) if coluna_uf else ""),
                    cnpj=(_digitos(_texto(linha.get(coluna_cnpj))) or None
                          if coluna_cnpj else None),
                    status=Status.PENDENTE,
                    motivo=f"lead de {origem}",
                    origem=[origem],
                    url_busca=(molde_de_busca(_texto(linha.get(coluna_url_busca)),
                                              dominio)
                               if coluna_url_busca else ""),
                    seletor_busca=(seletor_de_busca(
                        _texto(linha.get(coluna_seletor)), dominio)
                        if coluna_seletor else ""),
                ))
                lidos += 1

            configurados = sum(
                1 for c in (coluna_url_busca, coluna_seletor) if c is not None)
            log.info("%s: %d leads pela coluna %r%s%s", origem, lidos, coluna_site,
                     f" ({sem_dominio} linhas sem site)" if sem_dominio else "",
                     f"; busca configurada por {configurados} coluna(s)"
                     if configurados else "")

    if problemas:
        raise PlanilhaSemColunaDeSite(
            "não consegui usar {} entrada(s) de {}:\n  - {}".format(
                len(problemas), pasta, "\n  - ".join(problemas)
            )
        )

    return leads


def unificar_planilhas(
    base_sul: Path = BASE_SUL,
    base_atacadistas: Path = BASE_ATACADISTAS,
    pasta_leads: Path = LEADS,
) -> list[Fornecedor]:
    """Junta as duas bases pelo domínio normalizado.

    base_fornecedores_regiao_sul.xlsx     -> 102 empresas, SEM CNPJ
    fornecedores_atacadistas_...xlsx      -> 114 empresas, com CNPJ e CNAE

    A segunda ganha nos campos que ela resolveu (CNPJ, CNAE, status
    decidido por gente). A primeira entra como lead: domínio, nome, UF e
    status PENDENTE, para a validação automática decidir depois.

    O que veio REPROVADO da mão humana continua reprovado. "Site possui
    fluxo de compra online" é um motivo que nenhuma consulta de CNPJ
    redescobre, e reprocessar apagaria a decisão.
    """
    import pandas as pd

    por_dominio: dict[str, Fornecedor] = {}

    # --- leads da base regional (sem CNPJ) ---------------------------------
    if base_sul.exists():
        df = pd.read_excel(base_sul, sheet_name="Base de Empresas")
        for _, linha in df.iterrows():
            url = _texto(linha.get("Link (clicável)")) or _texto(linha.get("Site Oficial"))
            dominio = normalizar_dominio(url)
            if not dominio:
                continue
            por_dominio[dominio] = Fornecedor(
                nome=_texto(linha.get("Nome da Empresa")),
                dominio=dominio,
                url_base=_raiz(url, dominio),
                uf=_texto(linha.get("Estado")).upper(),
                status=Status.PENDENTE,
                motivo="lead da base regional; falta CNPJ",
                origem=[nome_origem(base_sul)],
            )
    else:
        log.warning("%s nao encontrada", base_sul)

    # --- base atacadista (com CNPJ e CNAE) ---------------------------------
    sem_site: list[dict] = []
    if base_atacadistas.exists():
        df = pd.read_excel(base_atacadistas, sheet_name="Todos_encontrados")
        for _, linha in df.iterrows():
            url = _texto(linha.get("Site / domínio")) or _texto(linha.get("Fonte/site"))
            dominio = normalizar_dominio(url)
            if not dominio:
                # 72 das 114 linhas têm CNPJ, mas só 42 têm site. O
                # domínio é a chave primária do projeto, então estas não
                # entram no master -- e sumir com elas em silêncio faria
                # a prospecção procurar de novo empresa já pesquisada.
                sem_site.append({
                    "empresa": _texto(linha.get("Empresa")),
                    "uf": _texto(linha.get("UF")),
                    "cidade": _texto(linha.get("Cidade")),
                    "cnpj": _digitos(_texto(linha.get("CNPJ"))),
                    "cnae_principal": _digitos(_texto(linha.get("CNAE principal"))),
                    "status_planilha": _texto(linha.get("Status atual")),
                })
                continue

            legado = _texto(linha.get("Status atual"))
            entrega = _sim(linha.get("Entrega PR+SC+RS"))
            existente = por_dominio.get(dominio)

            forn = Fornecedor(
                nome=_texto(linha.get("Empresa")) or (existente.nome if existente else ""),
                dominio=dominio,
                url_base=_raiz(url, dominio),
                uf=_texto(linha.get("UF")).upper() or (existente.uf if existente else ""),
                cnpj=_digitos(_texto(linha.get("CNPJ"))) or None,
                cnae_principal=_digitos(_texto(linha.get("CNAE principal"))) or None,
                entrega_sul={uf: True for uf in UFS_SUL} if entrega else {},
                status=_status_legado(legado),
                motivo=" | ".join(
                    p for p in (legado, _texto(linha.get("Motivo / observação"))) if p
                ),
                origem=sorted({nome_origem(base_atacadistas),
                               *(existente.origem if existente else [])}),
            )
            por_dominio[dominio] = forn
    else:
        log.warning("%s nao encontrada", base_atacadistas)

    if sem_site:
        _gravar_sem_site(sem_site)
        log.warning(
            "%d empresas com CNPJ mas SEM site ficaram fora do master; "
            "a lista esta em %s, para a prospeccao achar o domínio",
            len(sem_site), SEM_SITE,
        )

    # --- leads da prospecção (formato livre) -------------------------------
    # Vêm por último e nunca sobrescrevem: o que as duas bases já
    # resolveram vale mais do que uma linha de "nome + site". O lead só
    # preenche buraco (nome ou UF em branco) e acrescenta domínio novo.
    novos = 0
    for lead in ler_leads(pasta_leads):
        existente = por_dominio.get(lead.dominio)
        if existente is None:
            por_dominio[lead.dominio] = lead
            novos += 1
            continue
        existente.nome = existente.nome or lead.nome
        existente.uf = existente.uf or lead.uf
        if existente.cnpj and lead.cnpj and existente.cnpj != lead.cnpj:
            # Mesmo site, CNPJ diferente: são filiais do mesmo grupo (as
            # cinco linhas de consigaz.com.br em COMBUSTIVEL são cinco
            # revendas). A chave do projeto é o domínio, então só o
            # primeiro CNPJ é consultado -- o aviso existe para que isso
            # não apareça como surpresa na conferência.
            log.warning("%s tambem chegou com o CNPJ %s; so o %s foi consultado",
                        lead.dominio, lead.cnpj, existente.cnpj)
        existente.cnpj = existente.cnpj or lead.cnpj
        for origem in lead.origem:
            if origem not in existente.origem:
                existente.origem.append(origem)
        # Estas duas o lead SOBRESCREVE, ao contrário de todo o resto:
        # quem preencheu abriu o site e conferiu, e é a informação mais
        # nova que existe sobre como buscar ali.
        existente.url_busca = lead.url_busca or existente.url_busca
        existente.seletor_busca = lead.seletor_busca or existente.seletor_busca

    if novos:
        log.info("%d dominios novos vieram de %s", novos, pasta_leads)

    fornecedores = list(por_dominio.values())
    log.info("%d fornecedores unicos depois da juncao por dominio", len(fornecedores))
    return fornecedores


def _gravar_sem_site(linhas: list[dict]) -> None:
    import csv

    SEM_SITE.parent.mkdir(parents=True, exist_ok=True)
    with SEM_SITE.open("w", newline="", encoding="utf-8") as f:
        escritor = csv.DictWriter(f, fieldnames=list(linhas[0]))
        escritor.writeheader()
        escritor.writerows(linhas)


def _raiz(url: str, dominio: str) -> str:
    """A raiz do site, não a página onde alguém achou o produto.

    A prospecção cola o link que tinha na mão, e às vezes ele é fundo:
    `https://consigaz.com.br/p13/`, `.../supergasbras/botijao-de-gas-p13`.
    Tudo o que o pipeline monta depois pendura caminho em cima disso --
    a busca vira `.../p13/busca?q=panela` e a API vira
    `.../p13/wp-json/...`, as duas 404. Seis fornecedores aprovados
    entraram assim na primeira varredura.

    Mantém esquema e host como vieram, inclusive o `www.`, porque site
    que redireciona para www responde 301 a mais sem ele, e hospedagem
    que não tem o host sem www responde erro.
    """
    from urllib.parse import urlsplit

    partes = urlsplit(url if url.startswith("http") else f"https://{dominio}")
    if not partes.netloc:
        return f"https://{dominio}"
    return f"{partes.scheme}://{partes.netloc}"


def _digitos(texto: str) -> str:
    return "".join(c for c in texto if c.isdigit())


def _trocar_www(url: str) -> str:
    """https://loja.com.br -> https://www.loja.com.br, e o contrário."""
    from urllib.parse import urlsplit, urlunsplit

    partes = urlsplit(url)
    host = partes.netloc
    outro = host[4:] if host.startswith("www.") else f"www.{host}"
    return urlunsplit(partes._replace(netloc=outro))


def _serve_pagina(url: str, cliente: Cliente) -> bool:
    """O endereço entrega a página? (2xx, depois de seguir redirects.)

    Erro HTTP também conta como NÃO: um host que responde 403 ou 404 à
    home existe, mas não serve para raspar. Cinco dos nove fornecedores
    com o problema do www eram assim -- o endereço sem www respondia com
    erro, e o com www entregava a loja. A primeira versão desta função
    tratava "respondeu com erro" como "está certo, não mexa", e deixava
    os cinco batendo na porta errada.
    """
    try:
        cliente.get(url)
        return True
    except ErroHTTP:
        return False


def resolver_www(fornecedor: Fornecedor, cliente: Cliente) -> bool:
    """Se o site não entrega a página, tenta a outra forma: com ou sem www.

    Nove fornecedores aprovados estavam na planilha sem www e só
    respondem com ele (frigo, primoequipamentos, satoatacado, ...): 0 de
    3 tentativas como estavam, 3 de 3 com www. A varredura batia num
    endereço que não servia e o site saía como "loja vazia".

    Troca só quando o endereço atual NÃO entrega a página e o outro
    entrega. Se os dois entregam, fica o da planilha; se nenhum entrega,
    fica o da planilha também -- a troca não é palpite.

    O domínio (a chave do projeto) não muda: ele já é guardado sem www.
    Página boa fica em cache, então a detecção de plataforma logo depois
    não paga a requisição de novo. Devolve True se trocou.
    """
    if _serve_pagina(fornecedor.url_base, cliente):
        return False

    alternativa = _trocar_www(fornecedor.url_base)
    if not _serve_pagina(alternativa, cliente):
        return False

    log.warning("%s: %s nao entrega a pagina; usando %s",
                fornecedor.dominio, fornecedor.url_base, alternativa)
    fornecedor.url_base = alternativa
    return True


def validar(fornecedor: Fornecedor, cliente: Cliente,
            buscar_cnpj_no_site: bool = True) -> Fornecedor:
    """Aplica o pipeline de validação a um fornecedor. Idempotente.

    `buscar_cnpj_no_site=False` desliga a garimpagem de CNPJ no site e
    deixa PENDENTE quem chegou sem o número. É o passo mais caro da
    etapa: sem CNPJ na planilha, o código abre a home e mais quatro
    páginas institucionais atrás dele, com retry, e são ~40 s por
    empresa. A base regional tem 102 empresas assim -- só elas custam
    mais de uma hora, para um resultado que a prospecção consegue em
    minutos abrindo o site.
    """
    # Reprovação decidida por gente não se revisita em lote.
    if fornecedor.status is Status.REPROVADO:
        return fornecedor

    if not fornecedor.cnpj and buscar_cnpj_no_site:
        resolver_www(fornecedor, cliente)
        try:
            fornecedor.cnpj = extrair_do_site(fornecedor.url_base, cliente)
        except ErroHTTP as e:
            log.warning("%s: nao deu para ler o site (%s)",
                        fornecedor.dominio, type(e).__name__)

    if not fornecedor.cnpj:
        fornecedor.status = Status.PENDENTE
        # Continua no master, e não some: fornecedor que desaparece em
        # silêncio é fornecedor que a prospecção vai pesquisar de novo.
        # PENDENTE já o mantém fora da varredura, que só varre APROVADO.
        fornecedor.motivo = ("sem CNPJ na planilha; não foi consultado"
                             if not buscar_cnpj_no_site
                             else "CNPJ não encontrado no site")
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
    if campos.get("razao_social") and not fornecedor.nome:
        fornecedor.nome = campos["razao_social"]

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
        # É este endereço que vai para o master e que a varredura visita.
        # Resposta boa fica em cache, então a detecção logo abaixo não
        # paga a requisição de novo.
        resolver_www(fornecedor, cliente)
        detectada = detectar(fornecedor.url_base, cliente)
        # "desconhecida" também é o que detectar() devolve quando a home
        # não abre -- e rede instável não pode apagar o que já se sabia.
        # A revalidação de 23/09 rodou com ReadError em metade dos sites e
        # derrubou 28 plataformas detectadas (20 WooCommerce, 5 Tray...)
        # para desconhecida. Plataforma velha errada não faz estrago: a
        # sonda do registro confere a API antes de usar o adapter.
        if detectada is not Plataforma.DESCONHECIDA:
            fornecedor.plataforma = detectada

    return fornecedor


def decidir_entrega(fornecedor: Fornecedor) -> Fornecedor:
    """Entrega no Sul é critério de aprovação, não anotação.

    Passou a ser o filtro que de fato importa. Enquanto só entravam
    lojas do Sul e de SP, a geografia fazia esse trabalho de graça;
    abrindo para o país inteiro, o que separa um atacadista útil de um
    inútil é exatamente se ele coloca a caixa em Curitiba.

    Reprova só com prova: é preciso ter havido recusa nas três UFs.
    Timeout, bloqueio e site fora do ar deixam a pergunta em aberto, e
    fornecedor não some da lista por causa de uma tarde ruim de rede.
    """
    respostas = fornecedor.entrega_sul

    if any(respostas.values()):
        atendidas = sorted(uf for uf, atende in respostas.items() if atende)
        fornecedor.motivo = f"{fornecedor.motivo} | entrega em {', '.join(atendidas)}".strip(" |")
        return fornecedor

    if len(respostas) == len(UFS_SUL):  # as três responderam, e todas recusaram
        fornecedor.status = Status.REPROVADO
        fornecedor.motivo = "não entrega em PR, SC nem RS"
        return fornecedor

    fornecedor.status = Status.PENDENTE
    faltam = [uf for uf in UFS_SUL if uf not in respostas]
    fornecedor.motivo = (
        f"entrega no Sul não confirmada (sem resposta para {', '.join(faltam)})"
    )
    return fornecedor


def testar_entrega(fornecedor: Fornecedor, cliente: Cliente) -> Fornecedor:
    """Confirma entrega em PR, SC e RS e classifica o modo de frete.

    É o passo mais lento da etapa, por isso vem por último, rodando só
    sobre quem já passou no filtro de CNAE. Precisa de um produto de
    exemplo da loja: sem produto não há CEP para simular.
    """
    from src.adapters.registro import criar
    from src.core.frete import classificar_site

    if fornecedor.status is not Status.APROVADO:
        return fornecedor

    try:
        with criar(fornecedor, cliente) as executor:
            exemplos = executor.buscar(fornecedor.nome.split()[0] if fornecedor.nome else "a")
            if not exemplos:
                fornecedor.motivo += " | sem produto de exemplo para testar frete"
                return fornecedor
            fornecedor.modo_frete, fornecedor.entrega_sul = classificar_site(
                fornecedor, executor, exemplos[0].url
            )
    except (ErroHTTP, NotImplementedError) as e:
        log.warning("%s: teste de entrega falhou (%s)", fornecedor.dominio, type(e).__name__)
        return fornecedor

    return decidir_entrega(fornecedor)


def atualizar_busca(pasta_leads: Path = LEADS, caminho: Path = SAIDA,
                    limpar: bool = False,
                    destino: Path = validacao_por_aba.SAIDA) -> tuple[int, int]:
    """Só relê a configuração de busca das planilhas. Não toca na rede.

    Existe por causa do ritmo do trabalho: conferir a busca de 89 lojas
    é uma tarde de idas e vindas, e se cada salvamento custasse uma
    revalidação de 122 CNPJs ninguém usaria as duas colunas.

    Mexe em `url_busca` e `seletor_busca` e em mais nada: status, CNAE e
    situação cadastral continuam sendo assunto da validação.

    **Nada é apagado sem pedido.** Célula em branco não desconfigura o
    site, porque coluna ausente e célula vazia chegam aqui iguais — e
    quem larga só a planilha de EPI na pasta apagaria a configuração das
    outras cinco abas sem perceber. Para zerar de propósito existe
    `limpar=True` (`--so-busca --do-zero`).
    """
    if not caminho.exists():
        raise FileNotFoundError(
            f"{caminho} nao existe. Rode antes: python -m src.runners.etapa1_validar"
        )

    fornecedores = ler_fornecedores(apenas_aprovados=False, caminho=caminho)
    if limpar:
        for forn in fornecedores.values():
            forn.url_busca = forn.seletor_busca = ""

    configurados = 0
    desconhecidos: list[str] = []

    for lead in ler_leads(pasta_leads):
        if not (lead.url_busca or lead.seletor_busca):
            continue
        forn = fornecedores.get(lead.dominio)
        if forn is None:
            # Domínio que não está no master: ou é site novo (e a
            # validação precisa rodar antes), ou é erro de digitação na
            # coluna do site. Os dois merecem aparecer.
            desconhecidos.append(lead.dominio)
            continue
        forn.url_busca = lead.url_busca or forn.url_busca
        forn.seletor_busca = lead.seletor_busca or forn.seletor_busca
        configurados += 1

    gravar_fornecedores(list(fornecedores.values()), caminho)
    validacao_por_aba.gerar(list(fornecedores.values()), destino)

    if desconhecidos:
        log.warning("%d dominio(s) com busca configurada nao estao no master: %s",
                    len(desconhecidos), ", ".join(sorted(desconhecidos)[:10]))
    return configurados, len(desconhecidos)


def main(com_frete: bool = False, retomar: bool = True,
         por_aba: bool = True, so_com_cnpj: bool = False) -> list[Fornecedor]:
    fornecedores = unificar_planilhas()

    # Retomar aproveita CNPJ e CNAE já resolvidos numa execução anterior:
    # a BrasilAPI limita ~3 req/min e refazer tudo custa horas.
    if retomar and SAIDA.exists():
        anteriores = ler_fornecedores(apenas_aprovados=False, caminho=SAIDA)
        for f in fornecedores:
            antigo = anteriores.get(f.dominio)
            if antigo:
                # Fora do `if` de situação cadastral de propósito: a
                # configuração de busca é trabalho humano, não resultado
                # de validação. Um site PENDENTE (os de pneu esperando a
                # decisão de CNAE) perderia o seletor conferido à mão na
                # primeira revalidação, sem aviso.
                f.url_busca = f.url_busca or antigo.url_busca
                f.seletor_busca = f.seletor_busca or antigo.seletor_busca
            if antigo and antigo.situacao_cadastral:
                f.cnpj = f.cnpj or antigo.cnpj
                f.cnae_principal = antigo.cnae_principal
                f.cnaes_secundarios = antigo.cnaes_secundarios
                f.situacao_cadastral = antigo.situacao_cadastral
                f.plataforma = antigo.plataforma
                f.modo_frete = antigo.modo_frete or f.modo_frete
                f.entrega_sul = antigo.entrega_sul or f.entrega_sul

    with Cliente() as cliente:
        for f in fornecedores:
            f.dominio = normalizar_dominio(f.url_base)
            try:
                validar(f, cliente, buscar_cnpj_no_site=not so_com_cnpj)
                if com_frete:
                    testar_entrega(f, cliente)
            except Exception:
                log.exception("%s quebrou na validacao", f.dominio)
                f.status = Status.PENDENTE
                f.motivo = "erro na validação; ver logs/execucao.log"

    gravar_fornecedores(fornecedores, SAIDA)

    contagem = {s: sum(1 for f in fornecedores if f.status is s) for s in Status}
    print(f"{contagem[Status.APROVADO]} aprovados, "
          f"{contagem[Status.PENDENTE]} pendentes, "
          f"{contagem[Status.REPROVADO]} reprovados -> {SAIDA}")

    if so_com_cnpj:
        ignorados = sum(1 for f in fornecedores if not f.cnpj)
        print(f"{ignorados} sem CNPJ na planilha foram ignorados "
              f"(ficaram PENDENTE, fora da varredura)")

    # O master é para o pipeline; quem prospectou confere na própria aba.
    if por_aba:
        for caminho in validacao_por_aba.gerar(fornecedores):
            print(f"  conferência: {caminho}")

    return fornecedores


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Etapa 1 — validação de fornecedores")
    p.add_argument("--com-frete", action="store_true",
                   help="também testa entrega nos 3 CEPs (lento)")
    p.add_argument("--do-zero", action="store_true",
                   help="ignora o master anterior e reconsulta todos os CNPJ; "
                        "com --so-busca, zera a configuração antes de reler")
    p.add_argument("--sem-planilhas", action="store_true",
                   help="não gera as planilhas de conferência por aba")
    p.add_argument("--so-busca", action="store_true",
                   help="só relê a URL/seletor de busca das planilhas; sem rede")
    p.add_argument("--so-com-cnpj", action="store_true",
                   help="ignora quem chegou sem CNPJ, em vez de garimpar no site "
                        "(é o passo mais caro: ~40 s por empresa)")
    a = p.parse_args()
    try:
        if a.so_busca:
            configurados, fora = atualizar_busca(limpar=a.do_zero)
            print(f"{configurados} site(s) com busca configurada -> {SAIDA}")
            if fora:
                print(f"{fora} dominio(s) da planilha nao estao no master; "
                      f"rode a validacao completa para inclui-los")
            raise SystemExit(0)
        main(com_frete=a.com_frete, retomar=not a.do_zero,
             por_aba=not a.sem_planilhas, so_com_cnpj=a.so_com_cnpj)
    except PlanilhaSemColunaDeSite as e:
        # Problema de arquivo de entrada, não defeito de código: a
        # mensagem já diz qual planilha e quais colunas ela tem.
        raise SystemExit(f"[etapa1] {e}") from None
