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

from src.core.http import Cliente, ErroHTTP, normalizar_dominio
from src.core.log import obter
from src.core.plataforma import detectar
from src.core.tabelas import gravar_fornecedores, ler_fornecedores
from src.export import validacao_por_aba
from src.models import Fornecedor, Status
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

            coluna_site = achar_coluna(df.columns, SINONIMOS_SITE)
            if coluna_site is None:
                problemas.append(
                    f"{origem}: nenhuma coluna de site. "
                    f"Colunas encontradas: {list(df.columns)}. "
                    f"Esperava alguma com: {', '.join(sorted(SINONIMOS_SITE))}"
                )
                continue

            coluna_nome = achar_coluna(df.columns, SINONIMOS_NOME)
            coluna_uf = achar_coluna(df.columns, SINONIMOS_UF)
            coluna_cnpj = achar_coluna(df.columns, SINONIMOS_CNPJ)

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
                    url_base=url if url.startswith("http") else f"https://{dominio}",
                    uf=(_sigla_uf(_texto(linha.get(coluna_uf))) if coluna_uf else ""),
                    cnpj=(_digitos(_texto(linha.get(coluna_cnpj))) or None
                          if coluna_cnpj else None),
                    status=Status.PENDENTE,
                    motivo=f"lead de {origem}",
                    origem=[origem],
                ))
                lidos += 1

            log.info("%s: %d leads pela coluna %r%s", origem, lidos, coluna_site,
                     f" ({sem_dominio} linhas sem site)" if sem_dominio else "")

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
                url_base=url if url.startswith("http") else f"https://{dominio}",
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
                url_base=url if url.startswith("http") else f"https://{dominio}",
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


def _digitos(texto: str) -> str:
    return "".join(c for c in texto if c.isdigit())


def validar(fornecedor: Fornecedor, cliente: Cliente) -> Fornecedor:
    """Aplica o pipeline de validação a um fornecedor. Idempotente."""
    # Reprovação decidida por gente não se revisita em lote.
    if fornecedor.status is Status.REPROVADO:
        return fornecedor

    if not fornecedor.cnpj:
        try:
            fornecedor.cnpj = extrair_do_site(fornecedor.url_base, cliente)
        except ErroHTTP as e:
            log.warning("%s: nao deu para ler o site (%s)",
                        fornecedor.dominio, type(e).__name__)

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
        fornecedor.plataforma = detectar(fornecedor.url_base, cliente)

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


def main(com_frete: bool = False, retomar: bool = True,
         por_aba: bool = True) -> list[Fornecedor]:
    fornecedores = unificar_planilhas()

    # Retomar aproveita CNPJ e CNAE já resolvidos numa execução anterior:
    # a BrasilAPI limita ~3 req/min e refazer tudo custa horas.
    if retomar and SAIDA.exists():
        anteriores = ler_fornecedores(apenas_aprovados=False, caminho=SAIDA)
        for f in fornecedores:
            antigo = anteriores.get(f.dominio)
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
                validar(f, cliente)
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
                   help="ignora o master anterior e reconsulta todos os CNPJ")
    p.add_argument("--sem-planilhas", action="store_true",
                   help="não gera as planilhas de conferência por aba")
    a = p.parse_args()
    try:
        main(com_frete=a.com_frete, retomar=not a.do_zero,
             por_aba=not a.sem_planilhas)
    except PlanilhaSemColunaDeSite as e:
        # Problema de arquivo de entrada, não defeito de código: a
        # mensagem já diz qual planilha e quais colunas ela tem.
        raise SystemExit(f"[etapa1] {e}") from None
