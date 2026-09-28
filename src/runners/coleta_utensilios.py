"""Coleta de UTENSILIOS pelo navegador: preço, frete e print, site por site.

Existe porque a etapa 3 não chega a 2 de cada 3 lojas de utensílios: o
`PlaywrightExecutor` — o executor de Tray, Magento e de toda loja sem
plataforma reconhecida — sabe buscar, mas não implementa `detalhar()`
nem `cotar_frete()`, e a coleta pula o item com NotImplementedError.
A primeira versão disto foi um script solto, com o título do produto
digitado à mão, seletor de preço por site e uma planilha própria; este
runner faz o mesmo trabalho em cima do que o pipeline já sabe.

O que ele lê, e de onde:

    sites   fornecedores_master.csv, só APROVADO, só quem veio da aba
            Utensílios de lista_sites.xlsx (campo `origem`)
    itens   data/interim/itens.csv, categoria UTENSILIOS
    URLs    data/interim/achados/{dominio}.csv -- os ACEITOS e os A
            REVISAR (os mesmos que achados_por_site.csv e
            achados_revisar.csv resumem). A URL é a da varredura: não
            há busca de novo, e o preço é o do produto que o matching viu.

O que ele grava é o formato da etapa 3, para o montador não precisar
saber que este runner existe:

    data/coletas/{dominio}.jsonl                   um registro por item x UF
    data/output/prints/UTENSILIOS/{id}__{dominio}__{uf}.png
    data/output/conferencia_UTENSILIOS.xlsx        uma linha por item x site

Cada registro leva também `classificacao` (aceito | revisar). Registro
"revisar" fica FORA da entrega até alguém conferir: o runner acrescenta
o par (site, item) em data/raw/revisao.csv com a `decisao` em branco,
quem confere escreve `aceito` ou `recusado`, e o montador só leva o
aceito. A conferência existe para isso — produto encontrado, pontuação,
motivo, preço, frete, link e print, lado a lado.

O frete é lido da própria página do produto, depois do CEP: o texto que
apareceu na área de frete. Quando a loja não tem campo de CEP, ou o
valor não aparece de forma legível, o registro sai com o valor vazio e
a observação dizendo isso — o print, tirado depois do CEP, é a prova.

    python -m src.runners.coleta_utensilios                  # todos os sites
    python -m src.runners.coleta_utensilios --site platinox.com.br --limite 2
    python -m src.runners.coleta_utensilios --varrer         # varre antes quem não tem achado
    python -m src.export.montar_entrega --categoria UTENSILIOS
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from unidecode import unidecode

from src.core import matching, tabelas
from src.core.frete import SEM_ENTREGA
from src.core.http import INTERVALO_MAX, INTERVALO_MIN, FalhaDeRede, SiteBloqueado
from src.core.log import obter
from src.models import CEPS_SUL, Coleta, Fornecedor, Item, ProdutoBruto, Status
from src.runners.etapa2_varredura import ler_achados, registrar_bloqueio
from src.runners.etapa3_coletar import (
    DESTINO,
    caminho_print,
    ler_registros,
    registro_completo,
    sanear,
)

# Nome fixo: rodando com -m, __name__ é "__main__" e o log sairia do
# logger "src", sem ir para logs/execucao.log.
log = obter("src.runners.coleta_utensilios")

CATEGORIA = "UTENSILIOS"
ABA = "utensilios"  # comparada sem acento e sem caixa: "lista_sites.xlsx :: Utensílios"
CONFERENCIA = Path("data/output/conferencia_UTENSILIOS.xlsx")

TEMPO_NAVEGACAO_MS = 45000
ESPERA_FRETE_MS = 5000
LARGURA, ALTURA = 1366, 900

# Área de frete da página do produto. É daqui, e só daqui, que o valor
# do frete é lido: o corpo inteiro tem o preço, as parcelas e a vitrine
# de "quem viu também viu", todos com "R$".
SELETORES_AREA_FRETE = (
    "[class*='frete' i]", "[id*='frete' i]",
    "[class*='shipping' i]", "[id*='shipping' i]",
    "[class*='entrega' i]", "[id*='entrega' i]",
    "[class*='calcul' i]", "[id*='calcul' i]",
    "[class*='cep' i]", "[id*='cep' i]",
)

# Campo de CEP: os mesmos da captura, mais os do carrinho-lateral de Tray.
SELETORES_CEP = (
    "input[name*='cep' i]",
    "input[id*='cep' i]",
    "input[placeholder*='cep' i]",
    "input[data-testid*='cep' i]",
    "input[name*='postal' i]",
    "input[name*='zip' i]",
    "input[id*='shipping' i]",
)

# Muita loja só cota no clique, e o Enter não faz nada.
BOTOES_CALCULAR = ("Calcular", "Consultar", "Simular", "OK", "Ok")

# Banner de cookies cobre a tabela de frete no print. Os textos da
# captura comum e mais os que as lojas de utensílios usam ("Continuar e
# Fechar" na Vencedor).
BOTOES_COOKIES = ("Aceitar", "Aceito", "Concordo", "Entendi", "Continuar",
                  "Prosseguir", "Permitir")
CSS_SEM_COOKIES = """
[class*='cookie' i], [id*='cookie' i], [class*='lgpd' i], [id*='lgpd' i],
[class*='consent' i], [id*='consent' i] { display: none !important; }
"""

RE_REAL = re.compile(r"R\$\s*([\d.]+,\d{2})")
RE_GRATIS = re.compile(r"\bgr[aá]tis\b|\bfrete\s+gr[aá]tis\b", re.IGNORECASE)
RE_RECUSA = re.compile(
    r"n[aã]o\s+(entregamos|realizamos\s+entregas?|atendemos|h[aá]\s+op[cç][oõ]es)"
    r"|indispon[ií]vel\s+para\s+(o\s+)?(seu\s+)?cep"
    r"|cep\s+(n[aã]o\s+atendido|fora\s+da\s+[aá]rea)",
    re.IGNORECASE,
)
# Linha de parcela: "12x de R$ 9,99". Preço de parcela não é preço.
RE_PARCELA = re.compile(r"\d+\s*x\s*(de\s*)?R\$", re.IGNORECASE)
# Preço de pagamento à vista: "R$ 12,99 no PIX", "R$ 169,90 PIX / Boleto",
# "PIX: R$ 12,99". Nos dois sentidos, porque as lojas escrevem dos dois.
RE_A_VISTA = re.compile(
    r"R\$\s*([\d.]+,\d{2})[^|R$]{0,30}?\b(pix|boleto|[àa] vista)\b"
    r"|\b(pix|boleto|[àa] vista)\b[^|R$]{0,20}R\$\s*([\d.]+,\d{2})",
    re.IGNORECASE,
)
RE_VALOR_PARCELA = re.compile(r"\d+\s*x\s*(de\s*)?R\$\s*[\d.]+,\d{2}", re.IGNORECASE)

MARCAS_DE_BLOQUEIO = (
    "acesso negado", "access denied", "forbidden", "captcha",
    "verificando seu navegador", "checking your browser",
    "attention required", "just a moment",
)

# Roda na página do produto. Devolve texto cru; interpretar é trabalho
# do Python (`interpretar_produto`), que os testes exercitam sem
# navegador.
EXTRAIR_PRODUTO = """() => {
  const limpo = (t) => (t || '').replace(/\\s+/g, ' ').trim();
  const visivel = (el) => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
  };
  const fora = (el) => el.closest('header,footer,nav,[class*="menu" i],' +
    '[class*="related" i],[class*="relacionad" i],[class*="vitrine" i],' +
    '[class*="shelf" i],[class*="carousel" i],[class*="upsell" i]');

  const out = {titulo: '', ld: [], meta: '', precos: [], riscados: [], sku: '',
               disponivel: null};

  const h1 = [...document.querySelectorAll('h1')].find(h => visivel(h) && !fora(h));
  const og = document.querySelector('meta[property="og:title"]');
  out.titulo = limpo(h1 ? h1.innerText : (og ? og.content : document.title));

  for (const script of document.querySelectorAll('script[type="application/ld+json"]')) {
    let dados;
    try { dados = JSON.parse(script.textContent); } catch (e) { continue; }
    const fila = Array.isArray(dados) ? dados.slice() : [dados];
    while (fila.length) {
      const no = fila.shift();
      if (!no || typeof no !== 'object') continue;
      if (Array.isArray(no['@graph'])) fila.push(...no['@graph']);
      const tipo = [].concat(no['@type'] || []);
      if (!tipo.includes('Product')) continue;
      for (const o of [].concat(no.offers || [])) {
        const ofertas = o && o['@type'] === 'AggregateOffer' && o.offers
          ? [].concat(o.offers) : [o];
        for (const of of ofertas) {
          if (!of) continue;
          out.ld.push({nome: limpo(no.name), preco: of.price ?? of.lowPrice ?? '',
                       disponibilidade: String(of.availability || ''),
                       sku: String(no.sku || of.sku || '')});
        }
      }
    }
  }

  const meta = document.querySelector(
    'meta[property="product:price:amount"],meta[itemprop="price"],[itemprop="price"]');
  if (meta) out.meta = meta.getAttribute('content') || limpo(meta.innerText);

  const alvo = '[class*="price" i],[class*="preco" i],[class*="valor" i],[id*="price" i],' +
               '[id*="preco" i],[class*="sale" i]';
  for (const el of document.querySelectorAll(alvo)) {
    if (!visivel(el) || fora(el)) continue;
    const texto = limpo(el.innerText);
    if (!/R\\$/.test(texto) || texto.length > 160) continue;
    const riscado = el.closest('del,s,strike,[class*="old" i],[class*="antigo" i],' +
      '[class*="list" i],[class*="from" i],[class*="regular" i],[class*="de-" i]');
    (riscado ? out.riscados : out.precos).push(texto);
    if (out.precos.length > 12) break;
  }
  for (const el of document.querySelectorAll('del,s,strike')) {
    if (visivel(el) && !fora(el) && /R\\$/.test(el.innerText)) out.riscados.push(limpo(el.innerText));
  }

  out.pix = [];
  for (const el of document.querySelectorAll(
      '[class*="pix" i],[class*="boleto" i],[class*="vista" i],' + alvo)) {
    if (!visivel(el) || fora(el)) continue;
    const t = limpo(el.innerText);
    if (/pix|boleto|vista/i.test(t) && /R\\$/.test(t) && t.length < 200) out.pix.push(t);
    if (out.pix.length > 8) break;
  }

  // Disponível = botão de compra visível na área do produto. O texto do
  // corpo não serve: "Avise-me" de produto relacionado e modal escondido
  // marcavam 22 de 50 produtos da Panan como indisponíveis, todos com o
  // botão COMPRAR na tela.
  const compra = [...document.querySelectorAll(
      'button,a,input[type="submit"],input[type="button"]')].some(b =>
    visivel(b) && !fora(b) &&
    /comprar|adicionar ao carrinho|add to cart/i.test(b.innerText || b.value || ''));
  const aviso = [...document.querySelectorAll('h1,h2,h3,h4,h5,p,span,div,strong,b')].some(el =>
    el.children.length === 0 && visivel(el) && !fora(el) &&
    /^(produto )?(indispon[ií]vel|esgotado|sem estoque|fora de estoque)/i.test(limpo(el.innerText)));
  out.disponivel = compra ? true : (aviso ? false : null);
  return out;
}"""

EXTRAIR_AREA_FRETE = """(seletores) => {
  const vistos = new Set();
  const partes = [];
  for (const sel of seletores) {
    for (const el of document.querySelectorAll(sel)) {
      if (vistos.has(el)) continue;
      // Guarda só o mais externo: o de dentro repetiria o mesmo texto.
      let pai = el.parentElement, dentro = false;
      while (pai) { if (vistos.has(pai)) { dentro = true; break; } pai = pai.parentElement; }
      vistos.add(el);
      if (dentro) continue;
      const r = el.getBoundingClientRect();
      if (r.width === 0 || r.height === 0) continue;
      const t = (el.innerText || '').replace(/\\s+/g, ' ').trim();
      if (t && t.length < 1500) partes.push(t);
    }
  }
  return partes.join(' | ');
}"""


# ---------------------------------------------------------------------------
# Quem e o quê -- funções puras
# ---------------------------------------------------------------------------

def _sem_acento(texto: str) -> str:
    return unidecode(str(texto or "")).lower()


def veio_da_aba(fornecedor: Fornecedor, aba: str = ABA) -> bool:
    """O site está na aba Utensílios da planilha inicial de sites?"""
    return any(_sem_acento(o).rsplit("::", 1)[-1].strip() == aba for o in fornecedor.origem)


# Cabeçalhos das abas de utensílios em lista_sites.ods. Uma aba pode ter
# mais de uma tabela (a "Utensílios" tem a de validação de seletores
# colada embaixo), então o cabeçalho é procurado linha a linha.
COLUNAS_URL = ("url validada", "url", "site informado", "site")
COLUNAS_SELETOR = ("seletor css principal",)


COLUNAS_NOME = ("nome fantasia", "empresa / nome fantasia", "empresa")


def linhas_planilha_sites(caminho: Path) -> list[dict]:
    """Uma linha por site das abas de utensílios de uma planilha.

    Lê toda aba cujo nome, sem acento, contém "utensilio" -- em
    lista_sites.ods são "Utensílios" e "utensilios_scrappaveis". Cada
    linha traz {aba, nome, url, dominio, seletor}; o seletor vem da
    coluna "Seletor CSS principal", validada no DOM, e fica vazio
    quando a tabela não tem essa coluna.
    """
    import pandas as pd

    from src.core.http import normalizar_dominio

    abas = pd.read_excel(caminho, sheet_name=None, header=None, dtype=str)
    linhas: list[dict] = []
    for aba, tabela in abas.items():
        if "utensilio" not in _sem_acento(aba):
            continue
        col_url = col_sel = col_nome = None
        for linha in tabela.itertuples(index=False):
            celulas = [" ".join(str(c).split()) if isinstance(c, str) else "" for c in linha]
            rotulos = [_sem_acento(c) for c in celulas]
            achou_url = next((rotulos.index(r) for r in COLUNAS_URL if r in rotulos), None)
            if achou_url is not None:  # linha de cabeçalho: nova tabela
                col_url = achou_url
                col_sel = next((rotulos.index(r) for r in COLUNAS_SELETOR if r in rotulos),
                               None)
                col_nome = next((rotulos.index(r) for r in COLUNAS_NOME if r in rotulos), 0)
                continue
            if col_url is None or col_url >= len(celulas):
                continue
            dominio = normalizar_dominio(celulas[col_url])
            if not dominio or "." not in dominio:
                continue
            linhas.append({
                "aba": aba,
                "nome": celulas[col_nome] if col_nome is not None else "",
                "url": celulas[col_url],
                "dominio": dominio,
                "seletor": celulas[col_sel].strip() if col_sel is not None else "",
            })
    return linhas


def ler_planilha_sites(caminho: Path) -> dict[str, str]:
    """{dominio: seletor de busca} das abas de utensílios de uma planilha."""
    sites: dict[str, str] = {}
    for linha in linhas_planilha_sites(caminho):
        dominio, seletor = linha["dominio"], linha["seletor"]
        if seletor or dominio not in sites:
            sites[dominio] = seletor or sites.get(dominio, "")
    return sites


SITES_CSV = Path("data/interim/sites_utensilios.csv")
COLUNAS_SITES = ["dominio", "nome", "url", "abas", "seletor_busca", "status_master",
                 "coletavel", "motivo", "achados_aceitos", "achados_revisar"]


def exportar_sites(planilha: Path, destino: Path = SITES_CSV) -> int:
    """Um CSV com os sites de utensílios da planilha, um por domínio.

    Junta o que a planilha diz (nome, URL, abas, seletor) com o que o
    pipeline sabe (status no master, se é coletável e por quê, achados).
    """
    fornecedores = tabelas.ler_fornecedores(apenas_aprovados=False)
    itens = tabelas.ler_itens([CATEGORIA])
    por_dominio: dict[str, dict] = {}
    for linha in linhas_planilha_sites(planilha):
        site = por_dominio.setdefault(linha["dominio"], {
            "dominio": linha["dominio"], "nome": linha["nome"], "url": linha["url"],
            "abas": [], "seletor_busca": "",
        })
        if linha["aba"] not in site["abas"]:
            site["abas"].append(linha["aba"])
        site["seletor_busca"] = site["seletor_busca"] or linha["seletor"]
        site["nome"] = site["nome"] or linha["nome"]

    coletaveis, fora = sites_da_aba(fornecedores, dominios=set(por_dominio))
    motivos = {f.dominio: m for f, m in fora}
    for dominio, site in por_dominio.items():
        forn = fornecedores.get(dominio)
        site["abas"] = " | ".join(site["abas"])
        site["status_master"] = str(forn.status) if forn else "fora do master"
        site["coletavel"] = "sim" if dominio in {f.dominio for f in coletaveis} else "nao"
        site["motivo"] = motivos.get(dominio, "" if forn else "rode a etapa 1")
        achados = [a for a in ler_achados(dominio) if a.get("id_item") in itens]
        site["achados_aceitos"] = sum(a.get("classificacao") == "aceito" for a in achados)
        site["achados_revisar"] = sum(a.get("classificacao") == "revisar" for a in achados)

    destino.parent.mkdir(parents=True, exist_ok=True)
    with destino.open("w", newline="", encoding="utf-8") as f:
        escritor = csv.DictWriter(f, fieldnames=COLUNAS_SITES)
        escritor.writeheader()
        escritor.writerows(sorted(por_dominio.values(),
                                  key=lambda s: (s["coletavel"] != "sim", s["dominio"])))
    return len(por_dominio)


def sites_da_aba(fornecedores: dict[str, Fornecedor], aba: str = ABA,
                 dominios: set[str] | None = None
                 ) -> tuple[list[Fornecedor], list[tuple[Fornecedor, str]]]:
    """(coletáveis, [(fora, motivo)]) entre os sites da aba.

    Regra inviolável 3: nada é coletado sem APROVADO no master. E quem
    só foi aprovado pela exceção de varejo (47.53-9/47.59-8 sem CNAE 46
    secundário) é só do canal --varejista -- o mesmo corte que a
    varredura padrão faz em `orquestrador.do_canal`. Quem fica de fora
    volta com o motivo, para o resumo não o deixar sumir calado.
    """
    from src.orquestrador import do_canal

    coletaveis, fora = [], []
    for f in sorted(fornecedores.values(), key=lambda f: f.dominio):
        if (f.dominio not in dominios) if dominios is not None else not veio_da_aba(f, aba):
            continue
        if f.status is not Status.APROVADO:
            fora.append((f, f"{f.status} -- {f.motivo or 'sem motivo no master'}"))
        elif not do_canal(f, varejista=False):
            fora.append((f, f"só canal --varejista ({f.motivo})"))
        else:
            coletaveis.append(f)
    return coletaveis, fora


def achados_do_site(dominio: str, itens: dict[str, Item],
                    incluir_revisar: bool = True) -> list[dict]:
    """Os achados deste site para itens da categoria, o melhor por item."""
    classes = ("aceito", "revisar") if incluir_revisar else ("aceito",)
    melhores: dict[str, dict] = {}
    for a in ler_achados(dominio):
        if a.get("id_item") not in itens or not (a.get("url_produto") or "").strip():
            continue
        if a.get("classificacao", "aceito") not in classes:
            continue
        atual = melhores.get(a["id_item"])
        if atual is None or _chave_achado(a) > _chave_achado(atual):
            melhores[a["id_item"]] = a
    return [melhores[i] for i in itens if i in melhores]


def _chave_achado(a: dict) -> tuple[int, float]:
    return (a.get("classificacao") == "aceito", _numero(a.get("score_match")))


# ---------------------------------------------------------------------------
# Página do produto -- funções puras
# ---------------------------------------------------------------------------

def valor_em_real(texto) -> float | None:
    """"R$ 1.234,56" -> 1234.56; "129.90" (JSON-LD) -> 129.9."""
    if texto in (None, ""):
        return None
    if isinstance(texto, (int, float)):
        return float(texto) if texto > 0 else None
    bruto = str(texto).strip()
    achado = RE_REAL.search(bruto)
    if achado:
        numero = achado.group(1).replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d+(\.\d+)?", bruto):
        numero = bruto
    elif re.fullmatch(r"[\d.]+,\d{1,2}", bruto):
        numero = bruto.replace(".", "").replace(",", ".")
    else:
        return None
    try:
        valor = float(numero)
    except ValueError:
        return None
    return valor if valor > 0 else None


def _primeiro_preco(textos: list[str]) -> float | None:
    """O primeiro "R$" de verdade de uma lista de textos de preço.

    Pula linha de parcela ("12x de R$ 9,99"); se o texto traz "de R$ X
    por R$ Y", o preço é o Y.
    """
    for texto in textos:
        if RE_PARCELA.search(texto) and len(RE_REAL.findall(texto)) < 2:
            continue
        sem_parcela = RE_PARCELA.split(texto)[0] if RE_PARCELA.search(texto) else texto
        valores = [valor_em_real(f"R$ {v}") for v in RE_REAL.findall(sem_parcela)]
        valores = [v for v in valores if v]
        if not valores:
            continue
        if re.search(r"\bpor\b", sem_parcela, re.IGNORECASE) and len(valores) >= 2:
            return valores[-1]
        return valores[0]
    return None


def _valores_visiveis(textos: list[str]) -> list[float]:
    """Todos os "R$" das caixas de preço, sem os valores de parcela."""
    valores = []
    for texto in textos:
        for v in RE_REAL.findall(RE_VALOR_PARCELA.sub(" ", texto)):
            if (valor := valor_em_real(f"R$ {v}")) is not None:
                valores.append(valor)
    return valores


def preco_a_vista(textos: list[str]) -> float | None:
    """O menor preço anunciado para PIX, boleto ou "à vista"."""
    valores = []
    for texto in textos:
        for m in RE_A_VISTA.finditer(texto):
            valor = valor_em_real(f"R$ {m.group(1) or m.group(4)}")
            if valor:
                valores.append(valor)
    return min(valores) if valores else None


def interpretar_produto(bruto: dict, url: str) -> tuple[ProdutoBruto, str]:
    """O que o JavaScript leu da página -> (ProdutoBruto, obs de desconto).

    Preço, nesta ordem: JSON-LD (o dado que a loja publica para o
    Google), meta `price`, e só então o texto visível das caixas de
    preço.

    Desconto de pagamento (PIX, boleto, à vista) entra como desconto, e
    do mesmo jeito em toda loja -- o JSON-LD não ajuda aqui, porque uma
    Tray publica o preço cheio (Vencedor: 14,12 cheio, 12,99 no PIX) e
    outra o do PIX (Platinox: 169,90 no PIX, 188,78 no cartão):

        preco_lista  preço cheio ("Preço PRODUTO"), o riscado se houver
        preco        o que se paga à vista ("PREÇO FINAL")
    """
    ld = [o for o in (bruto.get("ld") or []) if isinstance(o, dict)]
    preco = next((v for o in ld if (v := valor_em_real(o.get("preco")))), None)
    if preco is None:
        preco = valor_em_real(bruto.get("meta"))
    precos = list(bruto.get("precos") or [])
    if preco is None:
        preco = _primeiro_preco(precos)

    riscado = _primeiro_preco(list(bruto.get("riscados") or []))
    a_vista = preco_a_vista(list(bruto.get("pix") or []) + precos)

    cheio = preco
    obs = ""
    if preco is not None and a_vista is not None:
        if a_vista < preco:
            # O preço publicado é o cheio e o PIX é menor.
            cheio, preco = preco, a_vista
            obs = f"{a_vista:.2f} no PIX/boleto"
    if preco is not None and cheio == preco:
        # O preço publicado já é o com desconto: o cheio é o outro valor
        # da MESMA caixa de preço, logo acima dele (parcelas excluídas).
        # Na Platinox o rótulo "PIX / Boleto" é imagem e nem aparece no
        # texto -- a caixa diz só "R$ 188,78 R$ 169,90 ou 3x de R$ 62,93".
        caixas = [t for t in precos + list(bruto.get("pix") or [])
                  if preco in _valores_visiveis([t])]
        acima = [v for v in _valores_visiveis(caixas) if preco < v <= preco * 1.5]
        if acima:
            cheio = min(acima)
            obs = (f"{preco:.2f} no PIX/boleto" if a_vista == preco
                   else f"de {cheio:.2f} por {preco:.2f}")
    if riscado is not None and cheio is not None and riscado > cheio:
        obs = "; ".join(filter(None, [f"de {riscado:.2f} por {cheio:.2f}", obs]))
        cheio = riscado
    lista = cheio if cheio is not None and preco is not None and cheio > preco else None

    # Botão de compra na tela ganha de tudo; sem ele, vale o JSON-LD e
    # depois o aviso visível. Sem sinal nenhum, conta como disponível.
    disponivel = bruto.get("disponivel")
    if disponivel is not True and ld \
            and any("outofstock" in (o.get("disponibilidade") or "").lower() for o in ld) \
            and not any("instock" in (o.get("disponibilidade") or "").lower() for o in ld):
        disponivel = False

    # Nome do JSON-LD antes do <h1>: loja sem h1 no produto tem h1 em
    # outro lugar ("Confira nossas marcas", na Ingá Import).
    titulo = next((o["nome"] for o in ld if o.get("nome")), "") or \
        " ".join(str(bruto.get("titulo") or "").split())
    sku = next((o.get("sku") for o in ld if o.get("sku")), None) or bruto.get("sku") or None

    produto = ProdutoBruto(
        titulo=titulo[:300],
        url=url,
        preco=preco,
        disponivel=disponivel is not False,
        sku=sku,
        preco_lista=lista,
    )
    return produto, obs


def interpretar_frete(antes: str, depois: str, preco: float | None = None
                      ) -> tuple[float | None, str]:
    """(valor, observação) a partir da área de frete antes e depois do CEP.

    Só vale o que APARECEU depois do CEP. Valores que já estavam lá
    (o preço repetido, "frete grátis acima de R$ 299,00") não são
    cotação. Entre as opções, o frete é a mais barata, e a observação
    carrega o texto para quem confere.
    """
    depois = " ".join((depois or "").split())
    antes = " ".join((antes or "").split())
    if not depois or depois == antes:
        return None, ""

    novo = depois.replace(antes, " ") if antes and antes in depois else depois
    resumo = novo.strip(" |")[:200]

    if RE_RECUSA.search(novo):
        return None, f"{SEM_ENTREGA} ({resumo})"

    ja_havia = {v for v in RE_REAL.findall(antes)}
    valores = [valor_em_real(f"R$ {v}") for v in RE_REAL.findall(novo) if v not in ja_havia]
    valores = [v for v in valores if v and v != preco]
    if valores:
        return min(valores), f"cotado na página do produto: {resumo}"
    if RE_GRATIS.search(novo) and not RE_GRATIS.search(antes):
        return 0.0, f"frete grátis na cotação: {resumo}"
    return None, ""


# ---------------------------------------------------------------------------
# Navegador
# ---------------------------------------------------------------------------

class Pagina:
    """Uma aba de navegador para o site inteiro. Nunca uma por item."""

    def __init__(self, fornecedor: Fornecedor) -> None:
        from src.export.captura import obter_navegador

        self.fornecedor = fornecedor
        self._contexto = obter_navegador().new_context(
            viewport={"width": LARGURA, "height": ALTURA}, locale="pt-BR",
        )
        self.pagina = self._contexto.new_page()

    def fechar(self) -> None:
        for recurso in (self.pagina, self._contexto):
            try:
                recurso.close()
            except Exception:  # noqa: PERF203 - fechar não pode derrubar a coleta
                pass

    def abrir(self, url: str) -> None:
        time.sleep(random.uniform(INTERVALO_MIN, INTERVALO_MAX))
        try:
            resposta = self.pagina.goto(url, wait_until="domcontentloaded",
                                        timeout=TEMPO_NAVEGACAO_MS)
        except Exception as e:
            raise FalhaDeRede(f"{type(e).__name__}: {e}", url) from e
        status = getattr(resposta, "status", 200) if resposta is not None else 200
        if status in (401, 403, 407, 429):
            raise SiteBloqueado(f"status {status}", url)
        if status >= 400:
            raise FalhaDeRede(f"status {status}", url)
        try:
            self.pagina.wait_for_load_state("networkidle", timeout=6000)
        except Exception:
            pass  # loja com analytics eterno nunca fica ociosa; o DOM já está lá
        titulo = _sem_acento(self.pagina.title())
        if any(m in titulo for m in MARCAS_DE_BLOQUEIO):
            raise SiteBloqueado(f"pagina de desafio: {titulo!r}", url)
        self.fechar_cookies()

    def produto(self, url: str) -> tuple[ProdutoBruto, str]:
        """(produto, observação de desconto)."""
        bruto = self.pagina.evaluate(EXTRAIR_PRODUTO)
        return interpretar_produto(bruto if isinstance(bruto, dict) else {}, url)

    def fechar_cookies(self) -> None:
        """Clica no aceite; se não houver botão reconhecível, esconde o banner.

        Esconder não muda nada que o print prova: o banner é da LGPD,
        não do produto. Sem isso, o da Vencedor e o da Platinox (um <a>,
        não um <button>) cobriam a tabela de frete.
        """
        for texto in BOTOES_COOKIES:
            try:
                alvo = self.pagina.locator(
                    "button, a, [role='button'], input[type='button']"
                ).filter(has_text=re.compile(rf"^\s*{texto}", re.IGNORECASE)).first
                if alvo.count() and alvo.is_visible():
                    alvo.click(timeout=2000)
                    break
            except Exception:  # noqa: PERF203
                continue
        try:
            self.pagina.add_style_tag(content=CSS_SEM_COOKIES)
        except Exception:
            pass

    def area_frete(self) -> str:
        try:
            return self.pagina.evaluate(EXTRAIR_AREA_FRETE, list(SELETORES_AREA_FRETE)) or ""
        except Exception:
            return ""

    def preencher_cep(self, cep: str) -> bool:
        for seletor in SELETORES_CEP:
            try:
                campo = self.pagina.locator(seletor).first
                if campo.count() == 0 or not campo.is_visible():
                    continue
                campo.scroll_into_view_if_needed(timeout=3000)
                campo.fill("", timeout=3000)
                # Digitado, não colado: máscara de CEP em JS ignora fill().
                campo.type(cep, delay=40, timeout=5000)
                campo.press("Enter")
                self._clicar_calcular(campo)
                return True
            except Exception:  # noqa: PERF203 - seletor que não serve, tenta o próximo
                continue
        return False

    def _clicar_calcular(self, campo) -> None:
        """O botão ao lado do campo. Procura subindo até três níveis."""
        for nivel in range(1, 4):
            caixa = campo.locator("xpath=" + "/".join([".."] * nivel))
            for texto in BOTOES_CALCULAR:
                try:
                    botao = caixa.get_by_role("button", name=texto, exact=False).first
                    if botao.count() and botao.is_visible():
                        botao.click(timeout=2000)
                        return
                except Exception:  # noqa: PERF203
                    continue

    def print(self, destino: Path) -> Path:
        destino.parent.mkdir(parents=True, exist_ok=True)
        # O banner costuma aparecer atrasado, depois do primeiro fechamento.
        self.fechar_cookies()
        self.pagina.screenshot(path=str(destino), full_page=True)
        if not destino.exists() or destino.stat().st_size == 0:
            raise FalhaDeRede(f"print saiu vazio: {destino}", self.pagina.url)
        return destino


# ---------------------------------------------------------------------------
# Coleta
# ---------------------------------------------------------------------------

def coletar_site(dominio: str, ids_itens: list[str] | None = None,
                 incluir_revisar: bool = True, varrer: bool = False,
                 limite: int | None = None, seletor_busca: str = "") -> dict:
    """Coleta UM site. Ponto de entrada do worker: um processo por domínio.

    `seletor_busca` vem da planilha de sites e só vale para a varredura,
    quando o master não tem um conferido.
    """
    from src.core import log as log_projeto

    log_projeto.configurar()
    fornecedor = tabelas.ler_fornecedores()[dominio]
    if seletor_busca and not fornecedor.seletor_busca:
        fornecedor.seletor_busca = seletor_busca
    itens = tabelas.ler_itens([CATEGORIA])
    if ids_itens:
        itens = {i: itens[i] for i in ids_itens if i in itens}

    if varrer:
        _varrer_faltantes(fornecedor, itens)

    achados = achados_do_site(dominio, itens, incluir_revisar)
    if limite:
        achados = achados[:limite]
    resumo = {"site": dominio, "achados": len(achados), "gravados": 0,
              "falhas": 0, "sem_preco_ou_indisponivel": 0, "bloqueado": False}
    if not achados:
        return resumo

    DESTINO.mkdir(parents=True, exist_ok=True)
    arquivo = DESTINO / f"{dominio}.jsonl"
    feitos = {(r["id_item"], r["uf"]) for r in sanear(arquivo)}

    pagina = Pagina(fornecedor)
    rebusca = Rebusca(fornecedor)
    try:
        with arquivo.open("a", encoding="utf-8") as saida:
            for achado in achados:
                item = itens[achado["id_item"]]
                pendentes = [uf for uf in CEPS_SUL if (item.id_item, uf) not in feitos]
                if not pendentes:
                    continue
                try:
                    registros = _coletar_item(pagina, item, achado, pendentes, dominio,
                                              rebusca)
                except SiteBloqueado as e:
                    registrar_bloqueio(dominio, str(e))
                    log.error("%s: bloqueado na coleta (%s)", dominio, e)
                    resumo["bloqueado"] = True
                    break
                except Exception as e:  # noqa: BLE001 - um item não derruba o site
                    resumo["falhas"] += 1
                    log.warning("%s: item %s falhou (%s: %s)", dominio, item.id_item,
                                type(e).__name__, e)
                    continue
                if not registros:
                    resumo["sem_preco_ou_indisponivel"] += 1
                for r in registros:
                    saida.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
                    saida.flush()  # a retomada depende de o disco dizer a verdade
                    resumo["gravados"] += 1
    finally:
        pagina.fechar()
        rebusca.fechar()
    return resumo


class Rebusca:
    """Busca no site e clique no card, para achado cuja URL não é produto.

    Achado antigo guarda o href que a varredura extraiu, e às vezes ele é
    de categoria (ciatacado.com/produtos-de-limpeza/). Buscar o título
    que a varredura viu e clicar no card leva à página do produto. Usa o
    executor genérico -- a mesma busca da varredura, com o seletor
    conferido na planilha -- aberto só na primeira vez que precisar.
    """

    def __init__(self, fornecedor: Fornecedor) -> None:
        self.fornecedor = fornecedor
        self._executor = None

    def url(self, item: Item, titulo: str) -> str | None:
        from src.adapters.generico_playwright import PlaywrightExecutor

        termo = " ".join(re.sub(r"(?i)\b(promo[cç][aã]o|c[oó]digo:.*|ver produto)\b", " ",
                                titulo).split()[:8])
        if not termo:
            return None
        if self._executor is None:
            self._executor = PlaywrightExecutor(self.fornecedor, None)
            self._executor.abrir()
        produtos = self._executor.buscar(termo)
        if not produtos:
            return None
        melhor = max(produtos, key=lambda p: matching.avaliar(item.descricao, p.titulo).score)
        return self._executor.abrir_card(melhor)

    def fechar(self) -> None:
        if self._executor is not None:
            self._executor.fechar()


def _coletar_item(pagina: Pagina, item: Item, achado: dict, ufs: list[str],
                  dominio: str, rebusca: Rebusca | None = None) -> list[dict]:
    """Preço uma vez, frete e print uma vez por UF.

    A página é recarregada a cada UF: o print tem que mostrar o CEP
    daquela UF e só ele, não o resultado da anterior embaixo.
    """
    url = achado["url_produto"].strip()
    pagina.abrir(url)
    produto, obs_desconto = pagina.produto(url)
    if produto.preco is None and rebusca is not None:
        try:
            nova = rebusca.url(item, achado.get("titulo_encontrado", ""))
        except SiteBloqueado:
            raise
        except FalhaDeRede as e:
            log.info("%s: rebusca de %s falhou (%s)", dominio, item.id_item, e)
            nova = None
        if nova and nova != url:
            log.info("%s: %s sem preço em %s; card clicado levou a %s",
                     dominio, item.id_item, url, nova)
            url = nova
            pagina.abrir(url)
            produto, obs_desconto = pagina.produto(url)
    if produto.preco is None:
        log.warning("%s: %s sem preço legível em %s", dominio, item.id_item, url)
        return []
    if not produto.disponivel:
        # Preço de produto que não se pode comprar não é oferta: sem
        # registro, o item fica para outro fornecedor.
        log.warning("%s: %s indisponível em %s", dominio, item.id_item, url)
        return []

    # O matching roda de novo sobre o título da página: a varredura viu
    # o card da busca, e o produto aberto pode ser outra variação.
    titulo = produto.titulo or achado.get("titulo_encontrado", "")
    avaliacao = matching.avaliar(item.descricao, titulo)
    classificacao = achado.get("classificacao", "aceito")
    if avaliacao.classificacao == "revisar" or classificacao == "revisar":
        classificacao = "revisar"
    if avaliacao.classificacao == "descartado" and \
            avaliacao.score_normalizado < _numero(achado.get("score_match")):
        # Título da página pior que o da varredura: vale o da varredura,
        # mas ninguém deveria entregar isso sem olhar.
        classificacao = "revisar"
    score = max(avaliacao.score_normalizado, _numero(achado.get("score_match")))
    motivo = "; ".join(m for m in (achado.get("motivo_match", ""), avaliacao.motivo) if m)

    registros = []
    for n, uf in enumerate(ufs):
        if n:
            pagina.abrir(url)
        antes = pagina.area_frete()
        preenchido = pagina.preencher_cep(CEPS_SUL[uf])
        if preenchido:
            pagina.pagina.wait_for_timeout(ESPERA_FRETE_MS)
            valor, obs = interpretar_frete(antes, pagina.area_frete(), produto.preco)
            if not obs:
                obs = (f"CEP {CEPS_SUL[uf]} preenchido; valor do frete não lido "
                       "automaticamente -- conferir no print")
        else:
            valor, obs = None, "página do produto sem campo de CEP; frete sob consulta"

        destino = caminho_print(CATEGORIA, item.id_item, dominio, uf)
        pagina.print(destino)
        registros.append(_registro(item, produto, url, uf, dominio, valor, obs, destino,
                                   score, classificacao, motivo, obs_desconto))
    return registros


def _registro(item: Item, produto: ProdutoBruto, url: str, uf: str, dominio: str,
              valor_frete: float | None, obs_frete: str, destino: Path,
              score: float, classificacao: str, motivo: str,
              obs_desconto: str = "") -> dict:
    """Mesmo formato da etapa 3, mais o que a revisão precisa."""
    desconto = None
    if produto.preco_lista and produto.preco and produto.preco_lista > produto.preco:
        desconto = round(produto.preco_lista - produto.preco, 2)
        obs_desconto = obs_desconto or (
            f"preco de {produto.preco_lista:.2f} por {produto.preco:.2f}")

    coleta = Coleta(
        id_item=item.id_item,
        dominio=dominio,
        uf=uf,
        url_produto=url,
        titulo_encontrado=produto.titulo,
        preco_produto=produto.preco_lista or produto.preco,
        valor_desconto=desconto,
        obs_desconto=obs_desconto,
        preco_final=produto.preco,
        valor_frete=valor_frete,
        obs_frete=obs_frete,
        caminho_print=str(destino),
        score_match=score,
        coletado_em=datetime.now(),
    )
    registro = asdict(coleta)
    registro["coletado_em"] = coleta.coletado_em.isoformat(timespec="seconds")
    registro["categoria"] = item.categoria
    registro["classificacao"] = classificacao
    registro["motivo_match"] = motivo
    registro["disponivel"] = produto.disponivel
    registro["coletor"] = "coleta_utensilios"
    return registro


def _varrer_faltantes(fornecedor: Fornecedor, itens: dict[str, Item]) -> None:
    """Varredura normal da etapa 2, só dos itens que o site ainda não tem.

    Não há busca própria aqui: quem busca é o executor da pipeline, com
    a configuração conferida à mão (`url_busca`, `seletor_busca`), e o
    resultado vai para achados/{dominio}.csv como qualquer varredura.
    """
    from src.adapters.registro import criar
    from src.core.http import Cliente
    from src.runners.etapa2_varredura import varrer_site

    ja_tem = {a["id_item"] for a in ler_achados(fornecedor.dominio)}
    faltam = [item for i, item in itens.items() if i not in ja_tem]
    if not faltam:
        return
    log.info("%s: varrendo %d itens sem achado", fornecedor.dominio, len(faltam))
    cliente = Cliente.para_varredura()
    try:
        with cliente, criar(fornecedor, cliente) as executor:
            print(f"[{fornecedor.dominio}] varredura: {varrer_site(executor, faltam)}")
    except Exception as e:  # noqa: BLE001 - varredura que falha não impede a coleta
        log.warning("%s: varredura falhou (%s: %s)", fornecedor.dominio,
                    type(e).__name__, e)


# ---------------------------------------------------------------------------
# Conferência
# ---------------------------------------------------------------------------

COLUNAS_CONFERENCIA = [
    "classificacao", "id_item", "item", "site", "produto_encontrado", "score",
    "motivo", "preco_final", "frete_PR", "frete_SC", "frete_RS", "url_produto", "print",
]


def gravar_conferencia(dominios: list[str] | None = None,
                       caminho: Path = CONFERENCIA) -> int:
    """Uma linha por item x site, com o que decide se o achado serve.

    Sem `dominios`, junta todo site já coletado: rodar um site por vez
    (--site) não pode apagar da conferência os que rodaram antes.
    """
    if dominios is None:
        dominios = sorted(a.stem for a in DESTINO.glob("*.jsonl"))
    from src.export.achados_por_site import gravar_planilha

    itens = tabelas.ler_itens([CATEGORIA])
    linhas: dict[tuple[str, str], dict] = {}
    for dominio in dominios:
        registros, _ = ler_registros(DESTINO / f"{dominio}.jsonl")
        for r in registros:
            if r.get("coletor") != "coleta_utensilios" or not registro_completo(r):
                continue
            chave = (r["id_item"], dominio)
            item = itens.get(r["id_item"])
            linha = linhas.setdefault(chave, {
                "classificacao": r.get("classificacao", ""),
                "id_item": r["id_item"],
                "item": item.item_curto if item else "",
                "site": dominio,
                "produto_encontrado": r.get("titulo_encontrado", ""),
                "score": r.get("score_match"),
                "motivo": r.get("motivo_match", ""),
                "preco_final": r.get("preco_final"),
                "url_produto": r.get("url_produto", ""),
                "print": r.get("caminho_print", ""),
            })
            frete = r.get("valor_frete")
            linha[f"frete_{r['uf']}"] = frete if frete not in (None, "") else "ver print"

    ordenadas = sorted(linhas.values(),
                       key=lambda l: (l["classificacao"] != "revisar", l["id_item"], l["site"]))
    gravar_planilha(caminho, [(
        "Conferência", COLUNAS_CONFERENCIA,
        [11, 8, 40, 26, 50, 7, 40, 11, 10, 10, 10, 45, 45], ordenadas,
    )])
    return len(ordenadas)


COLUNAS_REVISAO = ["dominio", "id_item", "decisao", "item", "produto_encontrado",
                   "score", "preco_final", "url_produto", "print"]


def atualizar_revisao(dominios: list[str]) -> int:
    """Acrescenta a data/raw/revisao.csv os achados "revisar" que faltam.

    Nunca reescreve uma linha que já está lá: a decisão é de quem
    conferiu. Devolve quantas linhas entraram.
    """
    from src.export.montar_entrega import REVISAO

    existentes: set[tuple[str, str]] = set()
    if REVISAO.exists():
        with REVISAO.open(encoding="utf-8-sig", newline="") as f:
            existentes = {((l.get("dominio") or "").strip().lower(),
                           (l.get("id_item") or "").strip()) for l in csv.DictReader(f)}

    itens = tabelas.ler_itens([CATEGORIA])
    novas: dict[tuple[str, str], dict] = {}
    for dominio in dominios:
        for r in ler_registros(DESTINO / f"{dominio}.jsonl")[0]:
            chave = (dominio, r.get("id_item", ""))
            if (r.get("classificacao") != "revisar" or chave in existentes
                    or chave in novas or not registro_completo(r)):
                continue
            item = itens.get(chave[1])
            novas[chave] = {
                "dominio": dominio, "id_item": chave[1], "decisao": "",
                "item": item.item_curto if item else "",
                "produto_encontrado": r.get("titulo_encontrado", ""),
                "score": r.get("score_match"), "preco_final": r.get("preco_final"),
                "url_produto": r.get("url_produto", ""),
                "print": r.get("caminho_print", ""),
            }
    if not novas:
        return 0

    REVISAO.parent.mkdir(parents=True, exist_ok=True)
    cabecalho = not REVISAO.exists() or REVISAO.stat().st_size == 0
    with REVISAO.open("a", newline="", encoding="utf-8") as f:
        escritor = csv.DictWriter(f, fieldnames=COLUNAS_REVISAO, extrasaction="ignore")
        if cabecalho:
            escritor.writeheader()
        escritor.writerows(novas[c] for c in sorted(novas, key=lambda c: (c[1], c[0])))
    return len(novas)


# ---------------------------------------------------------------------------

def _numero(valor) -> float:
    try:
        return float(str(valor).replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


def main(sites: list[str] | None = None, ids_itens: list[str] | None = None,
         incluir_revisar: bool = True, varrer: bool = False,
         limite: int | None = None, paralelos: int = 4,
         planilha: Path | None = None) -> list[dict]:
    fornecedores = tabelas.ler_fornecedores(apenas_aprovados=False)
    seletores: dict[str, str] = {}
    if planilha:
        seletores = ler_planilha_sites(planilha)
        print(f"[planilha] {len(seletores)} site(s) nas abas de utensílios de {planilha}")
        for dominio in sorted(set(seletores) - set(fornecedores)):
            print(f"[fora] {dominio}: não está no master -- rode a etapa 1 antes")
    aprovados, fora = sites_da_aba(fornecedores,
                                   dominios=set(seletores) if planilha else None)

    for f, motivo in fora:
        print(f"[fora] {f.dominio}: {motivo}")

    alvo = aprovados
    if sites:
        pedidos = {s.lower().removeprefix("www.").strip("/") for s in sites}
        alvo = [f for f in aprovados if f.dominio in pedidos]
        for s in sorted(pedidos - {f.dominio for f in alvo}):
            print(f"[fora] {s}: não é site coletável da aba Utensílios")

    itens = tabelas.ler_itens([CATEGORIA])
    if not varrer:
        sem_achado = [f.dominio for f in alvo if not achados_do_site(f.dominio, itens,
                                                                      incluir_revisar)]
        if sem_achado:
            print(f"[sem achado] {len(sem_achado)} site(s) sem nenhum achado de "
                  f"{CATEGORIA}; rode com --varrer para buscar neles: "
                  + ", ".join(sem_achado))
        alvo = [f for f in alvo if f.dominio not in sem_achado]

    resumos: list[dict] = []
    with ProcessPoolExecutor(max_workers=max(1, paralelos)) as pool:
        futuros = {
            pool.submit(coletar_site, f.dominio, ids_itens, incluir_revisar, varrer, limite,
                        seletores.get(f.dominio, "")): f.dominio
            for f in alvo
        }
        for futuro in as_completed(futuros):
            dominio = futuros[futuro]
            try:
                resumo = futuro.result()
            except Exception as e:  # noqa: BLE001
                resumo = {"site": dominio, "erro": f"{type(e).__name__}: {e}"}
            resumos.append(resumo)
            print(f"[coleta] {resumo}")

    dominios = [f.dominio for f in alvo]
    total = gravar_conferencia()
    a_revisar = atualizar_revisao(dominios)
    gravados = sum(r.get("gravados", 0) for r in resumos)
    print(f"\n{len(alvo)} site(s), {gravados} registro(s) novos; "
          f"{total} item x site em {CONFERENCIA}")
    if a_revisar:
        print(f"{a_revisar} achado(s) novo(s) a revisar em data/raw/revisao.csv: "
              "preencha a coluna decisao com aceito ou recusado")
    print("Próximo passo: python -m src.export.montar_entrega --categoria UTENSILIOS")
    return resumos


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    p.add_argument("--site", action="append", dest="sites",
                   help="domínio da aba Utensílios; repita para vários")
    p.add_argument("--item", action="append", dest="itens", help="id_item, ex. U009")
    p.add_argument("--so-aceitos", action="store_true",
                   help="ignora os achados a revisar")
    p.add_argument("--varrer", action="store_true",
                   help="antes de coletar, varre os itens que o site ainda não tem")
    p.add_argument("--limite", type=int, help="só os N primeiros achados por site")
    p.add_argument("--paralelos", type=int, default=4, help="sites ao mesmo tempo")
    p.add_argument("--planilha", type=Path,
                   help="lista de sites (.ods/.xlsx): usa as abas de utensílios "
                        "no lugar da origem gravada no master")
    p.add_argument("--exportar-sites", action="store_true",
                   help=f"só grava {SITES_CSV} com os sites da --planilha e sai")
    a = p.parse_args()
    if a.exportar_sites:
        if not a.planilha:
            p.error("--exportar-sites precisa de --planilha")
        print(f"{exportar_sites(a.planilha)} site(s) em {SITES_CSV}")
    else:
        main(a.sites, a.itens, not a.so_aceitos, a.varrer, a.limite, a.paralelos,
             a.planilha)
