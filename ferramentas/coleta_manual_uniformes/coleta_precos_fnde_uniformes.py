"""
Coleta de precos FNDE - Categoria UNIFORMES
============================================

Por que este script substitui o coleta_precos_fnde_sul.py original
--------------------------------------------------------------------
O script original navegava sozinho com Selenium + Chrome. O ambiente onde esta
coleta foi feita nao tem Chrome nem chromedriver instalados, entao o Selenium
nunca chegou a rodar aqui. Os 22 precos desta rodada (categoria UNIFORMES) foram
encontrados por pesquisa manual (busca + navegacao pagina a pagina), seguindo as
mesmas regras de validacao do projeto (SKILL.md): CNAE atacadista Divisao 46,
sem marketplace, sem fornecedor so-varejo, preco nunca inventado.

Este script cobre as partes do fluxo que SAO automatizaveis e reproduziveis:

  1) VALIDACAO DE CNAE: para cada CNPJ usado, consulta a BrasilAPI ao vivo e
     confirma que o fornecedor tem CNAE de comercio atacadista (Divisao 46),
     principal ou secundario -- a mesma regra usada na pesquisa manual.
  2) CAPTURA DE PRINT: abre a URL de cada produto com Playwright (Chromium
     baixado pelo proprio Playwright, sem depender de instalacao previa de
     Chrome no sistema) e salva um print em
     output/prints/<ID_FGV>/print_NN_<fornecedor>.png
  3) GERACAO DA PLANILHA: escreve/recria output/FNDE_output.xlsx a partir dos
     registros abaixo (REGISTROS_UNIFORMES), no layout ja usado pelo projeto.

O que este script NAO faz (por decisao, nao por limitacao tecnica)
--------------------------------------------------------------------
- Nao descobre fornecedores novos sozinho. A descoberta de fornecedores e
  precos continua sendo feita por pesquisa (manual ou por um agente),
  registrada aqui em REGISTROS_UNIFORMES, e so entao processada pelo script.
- Nao preenche frete. VALOR FRETE / OBS FRETE ficam vazios nesta etapa,
  por decisao do usuario ("agora nao vamos nos preocupar com isso").

Como adicionar um preco novo
------------------------------
1. Adicione um dict a lista REGISTROS_UNIFORMES, com todos os campos
   preenchidos (nunca invente CNPJ, preco ou CNAE).
2. Rode `python coleta_precos_fnde_uniformes.py`.
3. O script valida o CNAE ao vivo, tira o print da pagina e regrava a
   planilha inteira a partir da lista (a lista e a fonte da verdade).

Como rodar
-----------
1. pip install -r requirements.txt
2. python -m playwright install chromium   (uma unica vez, baixa o Chromium)
3. python coleta_precos_fnde_uniformes.py
"""

from __future__ import annotations

import re
import json
import time
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from logging.handlers import RotatingFileHandler

try:
    # Em maquinas com um certificado raiz corporativo (proxy/antivirus) que nao
    # esta no bundle do certifi, o requests falha com SSLCertVerificationError
    # mesmo que o sistema operacional confie nesse certificado. Este pacote
    # redireciona a verificacao de certificados do requests para o repositorio
    # de certificados do proprio sistema operacional. Se nao estiver instalado,
    # seguimos com o comportamento padrao do requests/certifi.
    import pip_system_certs.wrapt_requests  # noqa: F401
except ImportError:
    pass

import requests
from openpyxl import Workbook
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
LOG_FILE = LOG_DIR / "coleta_fnde.log"
OUTPUT_DIR = BASE_DIR / "output"
PRINTS_DIR = OUTPUT_DIR / "prints"
PLANILHA_SAIDA = OUTPUT_DIR / "FNDE_output.xlsx"
CNAE_CACHE_FILE = LOG_DIR / "cnae_cache.json"


# ---------------------------------------------------------------------------
# 1) LOGGING (mesmo padrao documentado em LOGS.md: terminal + arquivo rotativo)
# ---------------------------------------------------------------------------

def configurar_logging() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("coleta_fnde")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if logger.handlers:
        return logger

    formato_terminal = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s", datefmt="%H:%M:%S"
    )
    formato_arquivo = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    handler_terminal = logging.StreamHandler()
    handler_terminal.setFormatter(formato_terminal)

    handler_arquivo = RotatingFileHandler(
        LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8", delay=True
    )
    handler_arquivo.setFormatter(formato_arquivo)

    logger.addHandler(handler_terminal)
    logger.addHandler(handler_arquivo)
    return logger


log = configurar_logging()


# ---------------------------------------------------------------------------
# 2) VALIDACAO DE CNAE ATACADISTA (Divisao 46) -- mesma regra do SKILL.md
# ---------------------------------------------------------------------------

CNAE_DIVISAO_ATACADISTA = "46"

MARKETPLACE_DOMAINS = [
    "mercadolivre.com", "mercadolibre.com", "amazon.com", "shopee.com",
    "americanas.com", "magazineluiza.com.br", "magalu.com", "aliexpress.com",
    "olx.com.br", "submarino.com.br", "shoptime.com.br", "casasbahia.com.br",
    "extra.com.br", "carrefour.com.br", "netshoes.com.br", "kabum.com.br",
]


def eh_marketplace(url: str) -> bool:
    from urllib.parse import urlparse
    dominio = urlparse(url).netloc.lower()
    return any(mp in dominio for mp in MARKETPLACE_DOMAINS)


def cnae_eh_atacadista(codigo_cnae: str) -> bool:
    digitos = re.sub(r"\D", "", str(codigo_cnae))
    return digitos[:2] == CNAE_DIVISAO_ATACADISTA


def _carregar_cache_cnae() -> dict:
    if not CNAE_CACHE_FILE.exists():
        return {}
    try:
        return json.loads(CNAE_CACHE_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning(f"Cache de CNAE corrompido, ignorando ({CNAE_CACHE_FILE}): {e}")
        return {}


def _salvar_cache_cnae(cache: dict) -> None:
    CNAE_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CNAE_CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def consultar_cnae_por_cnpj(cnpj: str, tentativas: int = 4, usar_cache: bool = True) -> tuple[list[str], str, str]:
    """Consulta CNAEs e UF de um CNPJ na BrasilAPI. Nunca inventa: se a API
    nao responder (mesmo apos retentativas), devolve listas vazias.

    A BrasilAPI aplica rate limit (HTTP 429) em rajadas de requisicoes; por
    isso as tentativas usam backoff exponencial (2s, 4s, 8s...), e o
    resultado de uma consulta bem-sucedida fica em cache local
    (logs/cnae_cache.json) para nao martelar a API a cada nova execucao do
    script com os mesmos CNPJs.
    """
    cnpj_limpo = re.sub(r"\D", "", cnpj)
    if len(cnpj_limpo) != 14:
        return [], "", ""

    cache = _carregar_cache_cnae() if usar_cache else {}
    if usar_cache and cnpj_limpo in cache:
        entrada = cache[cnpj_limpo]
        log.info(f"  (cache de {entrada['consultado_em']}) usando resultado ja validado para {cnpj}")
        return entrada["cnaes"], entrada["uf"], f"BrasilAPI (cache de {entrada['consultado_em']})"

    espera = 2.0
    for tentativa in range(1, tentativas + 1):
        try:
            resp = requests.get(
                f"https://brasilapi.com.br/api/cnpj/v1/{cnpj_limpo}", timeout=12
            )
            if resp.status_code == 200:
                dados = resp.json()
                cnaes = [str(dados.get("cnae_fiscal", ""))]
                cnaes += [str(c.get("codigo", "")) for c in dados.get("cnaes_secundarios", [])]
                cnaes = [c for c in cnaes if c]
                uf = str(dados.get("uf", "") or "")
                if usar_cache and cnaes:
                    cache[cnpj_limpo] = {
                        "cnaes": cnaes, "uf": uf,
                        "consultado_em": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    }
                    _salvar_cache_cnae(cache)
                return cnaes, uf, "BrasilAPI"
            if resp.status_code == 429 and tentativa < tentativas:
                log.warning(f"  Rate limit (429) da BrasilAPI para {cnpj}; aguardando {espera:.0f}s (tentativa {tentativa}/{tentativas})")
                time.sleep(espera)
                espera *= 2
                continue
            log.warning(f"Falha ao consultar BrasilAPI para {cnpj}: HTTP {resp.status_code}")
            return [], "", ""
        except Exception as e:
            if tentativa < tentativas:
                log.warning(f"  Erro de conexao para {cnpj} (tentativa {tentativa}/{tentativas}): {e}; aguardando {espera:.0f}s")
                time.sleep(espera)
                espera *= 2
                continue
            log.warning(f"Falha ao consultar BrasilAPI para {cnpj}: {e}")
    return [], "", ""


def validar_fornecedor(nome: str, cnpj: str, url: str) -> bool:
    """Revalida ao vivo: nao e marketplace + tem CNAE atacadista (Divisao 46,
    principal ou secundario). Loga o resultado. Retorna True/False."""
    if eh_marketplace(url):
        log.warning(f"  REPROVADO (marketplace): {nome} -> {url}")
        return False

    cnaes, uf_cnpj, fonte = consultar_cnae_por_cnpj(cnpj)
    if not cnaes:
        log.warning(f"  PENDENTE (API nao respondeu): {nome} ({cnpj})")
        return False

    if not any(cnae_eh_atacadista(c) for c in cnaes):
        log.warning(f"  REPROVADO (sem CNAE atacadista): {nome} ({cnpj}) -> CNAEs: {', '.join(cnaes)}")
        return False

    log.info(f"  APROVADO: {nome} ({cnpj}) -- CNAE atacadista confirmado via {fonte}, UF cadastral {uf_cnpj}")
    return True


# ---------------------------------------------------------------------------
# 3) REGISTROS COLETADOS -- fonte da verdade (preencher manualmente por rodada)
# ---------------------------------------------------------------------------

@dataclass
class RegistroPreco:
    categoria: str
    codigo_fgv: int
    item: str
    uf: str
    data_coleta: str
    empresa: str
    cnpj: str
    fonte: str
    produto_pesquisado: str
    preco_produto: float
    valor_final: float
    obs_desconto: str
    valor_desconto: float | None = None
    valor_frete: float | None = None
    obs_frete: str = ""
    scroll_y: int = 0  # pixels para rolar antes do print, se o preco nao estiver visivel no topo da pagina


REGISTROS_UNIFORMES: list[RegistroPreco] = [
    RegistroPreco("UNIFORMES ROUPAS E CALCADOS", 307,
        "BOTA CANO CURTO CANO EXTRA CURTO PVC FORRO RAPIDA SECAGEM TAMANHO 40 PRETO 16 CM INNPRO",
        "SC", "20/09/2026", "Zeus do Brasil Ltda (loja EPI Zeus)", "82.699.588/0001-88",
        "https://www.epizeus.com.br/bota-pvc-italbotas-calfor-preta-forrada-cano-curto",
        "Bota PVC Italbotas Calfor preta, forrada, cano curto - CA 18472",
        49.90, 43.61, "Preco a vista no PIX (site); CNAE atacadista 4642-7-02 confirmado (principal)",
        6.29),
    RegistroPreco("UNIFORMES ROUPAS E CALCADOS", 300,
        "CALCA DE UNIFORME BRIM PESADO UNISSEX ALGODAO BOLSOS LATERAIS E TRASEIROS",
        "SC", "20/09/2026", "Zeus do Brasil Ltda (loja EPI Zeus)", "82.699.588/0001-88",
        "https://www.epizeus.com.br/calca-brim-pesado-azul-royal",
        "Calca brim pesado Azul royal",
        89.90, 85.41, "Preco a vista no PIX (site); cor/bolsos nao detalhados na pagina, aderencia parcial",
        4.49),
    RegistroPreco("UNIFORMES ROUPAS E CALCADOS", 300,
        "CALCA DE UNIFORME BRIM PESADO UNISSEX ALGODAO BOLSOS LATERAIS E TRASEIROS",
        "PR", "20/09/2026", "Agil Confeccoes e Comercio de Uniformes Ltda (Agil Uniformes)",
        "62.783.106/0001-66", "https://agiluniformes.com.br/uniformes-araucaria-pr/",
        "Calca Brim Lisa",
        65.00, 65.00, "A partir de - preco-piso publico reconfirmado ao vivo nesta rodada; CNAE atacadista 4642702 (secundario)"),
    RegistroPreco("UNIFORMES ROUPAS E CALCADOS", 301,
        "CAMISA MANGA CURTA GOLA CARECA. TECIDO: MALHA ALGODAO BRANCO ORIGINAL EPI",
        "SC", "20/09/2026", "Zeus do Brasil Ltda (loja EPI Zeus)", "82.699.588/0001-88",
        "https://www.epizeus.com.br/camisa-de-malha-branca",
        "Camisa de malha Branca (100% algodao, manga curta, branca)",
        35.90, 28.41, "Preco a vista no PIX; site descreve gola em V (spec pede gola careca) - aderencia parcial na gola",
        7.49),
    RegistroPreco("UNIFORMES ROUPAS E CALCADOS", 301,
        "CAMISA MANGA CURTA GOLA CARECA. TECIDO: MALHA ALGODAO BRANCO ORIGINAL EPI",
        "PR", "20/09/2026", "Agil Confeccoes e Comercio de Uniformes Ltda (Agil Uniformes)",
        "62.783.106/0001-66", "https://agiluniformes.com.br/uniformes-araucaria-pr/",
        "Camiseta Basica / Dry-fit",
        28.00, 28.00, "A partir de - preco-piso publico reconfirmado ao vivo; cor/gola/composicao nao detalhadas na pagina"),
    RegistroPreco("UNIFORMES ROUPAS E CALCADOS", 302,
        "JALECO DE SERVICO BRIM UNISSEX ALGODAO MANGA CURTA 3 BOLSOS GOLA ESPORTE",
        "SC", "20/09/2026", "Zeus do Brasil Ltda (loja EPI Zeus)", "82.699.588/0001-88",
        "https://www.epizeus.com.br/jaleco-curto-brim-leve-cinza",
        "Jaleco curto brim leve cinza (brim, manga curta, 3 bolsos frontais)",
        79.90, 61.66, "Preco a vista no PIX; boa aderencia (brim, manga curta, 3 bolsos); gola esporte nao confirmada na pagina",
        18.24),
    RegistroPreco("UNIFORMES ROUPAS E CALCADOS", 309,
        "TENIS DE SEGURANCA COURO VAQUETA TAMANHO 41 PRETO COM CADARCO BIQUEIRA EM PVC SP700 BOMPEL",
        "SP", "20/09/2026", "Seguranca Total EPIs Ltda", "39.268.527/0001-37",
        "https://www.segurancatotal.com.br/sapato-de-seguranca-bico-de-pvc-bompel-ca-33791",
        "Tenis Bompel Vaqueta Preto PRI3005, biqueira PVC, cadarco - CA 33791",
        209.90, 197.27,
        "CNAE atacadista 4642702 e secundario (principal e varejo, mas secundario atacadista vale pela regra do projeto); "
        "modelo PRI3005 (nao SP700 exato) - aderencia alta, mesma marca/linha Bompel",
        12.63, obs_frete="Fornecedor de SP - atendendo cesta nacional (sem cobertura Sul p/ este item nesta rodada)"),
    RegistroPreco("UNIFORMES ROUPAS E CALCADOS", 300,
        "CALCA DE UNIFORME BRIM PESADO UNISSEX ALGODAO BOLSOS LATERAIS E TRASEIROS",
        "PR", "20/09/2026", "Zen Uniformes Ltda (Zengo Uniformes)", "22.692.670/0001-59",
        "https://www.zengouniformes.com.br/calcas-",
        "Calca Brim Pesado Profissional - Cargo - Branco e Cinza",
        53.40, 49.66, "Preco a vista no PIX (7% desc.); 100% algodao confirmado no texto do site; modelo cargo, nao especifica bolsos laterais+traseiros",
        3.74),
    RegistroPreco("UNIFORMES ROUPAS E CALCADOS", 301,
        "CAMISA MANGA CURTA GOLA CARECA. TECIDO: MALHA ALGODAO BRANCO ORIGINAL EPI",
        "PR", "20/09/2026", "Zen Uniformes Ltda (Zengo Uniformes)", "22.692.670/0001-59",
        "https://www.zengouniformes.com.br/camisetas",
        "Camiseta PV - Gola Redonda - Manga Curta",
        27.00, 25.11, "Preco a vista no PIX (7% desc.); gola redonda = gola careca (boa aderencia), mas tecido e poliviscose (PV), nao malha 100% algodao",
        1.89),
    RegistroPreco("UNIFORMES ROUPAS E CALCADOS", 307,
        "BOTA CANO CURTO CANO EXTRA CURTO PVC FORRO RAPIDA SECAGEM TAMANHO 40 PRETO 16 CM INNPRO",
        "SC", "20/09/2026", "Super-Pro Comercio de Equipamentos e Ferramentas Ltda (Super Pro Atacado)",
        "08.858.579/0015-35", "https://www.superproatacado.com.br/epi/bota-de-pvc/bota-de-pvc-cano-curto",
        "Bota PVC Preto/Amarelo N41 Cano Curto SEM FORRO Grendene",
        37.99, 37.99, "Preco a vista; PVC preto cano curto confere, mas produto e SEM FORRO (spec pede COM forro) - aderencia parcial"),
    RegistroPreco("UNIFORMES ROUPAS E CALCADOS", 302,
        "JALECO DE SERVICO BRIM UNISSEX ALGODAO MANGA CURTA 3 BOLSOS GOLA ESPORTE",
        "SC", "20/09/2026", "Multiseg Comercio de Equipamentos de Seguranca Ltda", "10.498.304/0001-84",
        "https://www.multiseg.com.br/1329/jaleco-brim-manga-curta-azul-royal-c-3-bolsos",
        "Jaleco Brim Manga Curta Azul Royal com 3 Bolsos",
        86.52, 83.92, "Preco a vista com 3% desc. (base = 2x de R$43,26 sem juros); brim 100% algodao, manga curta, 3 bolsos - boa aderencia; gola esporte nao especificada",
        2.60),
    RegistroPreco("UNIFORMES ROUPAS E CALCADOS", 307,
        "BOTA CANO CURTO CANO EXTRA CURTO PVC FORRO RAPIDA SECAGEM TAMANHO 40 PRETO 16 CM INNPRO",
        "SC", "20/09/2026", "Multiseg Comercio de Equipamentos de Seguranca Ltda", "10.498.304/0001-84",
        "https://www.multiseg.com.br/156/bota-de-pvc-cano-16cm-branca-ca-40681-c-forro-innpro",
        "Bota de Pvc Cano 16 CM Branca - Innpro - CA 40681",
        42.49, 42.49, "Mesma marca (Innpro) e mesma altura de cano (16cm) da especificacao FGV; cor branca, spec pede preto - aderencia parcial so na cor"),
    RegistroPreco("UNIFORMES ROUPAS E CALCADOS", 300,
        "CALCA DE UNIFORME BRIM PESADO UNISSEX ALGODAO BOLSOS LATERAIS E TRASEIROS",
        "SC", "20/09/2026", "Multiseg Comercio de Equipamentos de Seguranca Ltda", "10.498.304/0001-84",
        "https://www.multiseg.com.br/759/cala-de-brim-cinza-c-bolsos-profissional",
        "Calca de Brim Cinza C/Bolsos Profissional",
        86.50, 83.91, "Preco a vista (base 2x de R$43,25); brim com bolsos confirmado, composicao/lateral+traseiro nao detalhados na listagem",
        2.59),
    RegistroPreco("UNIFORMES ROUPAS E CALCADOS", 307,
        "BOTA CANO CURTO CANO EXTRA CURTO PVC FORRO RAPIDA SECAGEM TAMANHO 40 PRETO 16 CM INNPRO",
        "SC", "20/09/2026", "Astro Distribuidora Ltda", "18.597.685/0001-60",
        "https://www.astrodistribuidora.com/bota-de-pvc-cano-curto-16cm-preta-innpro-ca-40681",
        "Bota de PVC Cano Curto 16cm Preta - Innpro - CA 40681",
        32.54, 30.91, "Preco a vista no boleto (5% desc.); match quase perfeito - mesma marca Innpro, 16cm, preta, forro rapida secagem (membrana easily-dried), tamanho 40 disponivel",
        1.63),
    RegistroPreco("UNIFORMES ROUPAS E CALCADOS", 307,
        "BOTA CANO CURTO CANO EXTRA CURTO PVC FORRO RAPIDA SECAGEM TAMANHO 40 PRETO 16 CM INNPRO",
        "SP", "20/09/2026", "Art Limp Brasil - Distribuicao - Gestao e Logistica Ltda", "13.186.075/0001-50",
        "https://www.artlimpbrasil.com.br/bota-de-seguranca-cano-curto-preta-n-38.html",
        "Bota de Seguranca Cano Curto Preta N38 (SKU 11611)",
        62.00, 58.90, "Preco a vista (5% desc.); PVC preta forrada confere, mas cano tem 26cm (spec pede EXTRA curto 16cm) - aderencia parcial na altura",
        3.10),
    RegistroPreco("UNIFORMES ROUPAS E CALCADOS", 301,
        "CAMISA MANGA CURTA GOLA CARECA. TECIDO: MALHA ALGODAO BRANCO ORIGINAL EPI",
        "MG", "20/09/2026", "BHZ EPI Distribuidora Ltda", "31.893.116/0001-20",
        "https://www.loja.bhzepi.com.br/produto/uniforme-camisa-de-malha",
        "Uniforme Camisa Camiseta de Malha Manga Curta (Fortline)",
        27.98, 27.98, "Gola redonda e manga curta confere; composicao e 100% poliester (spec pede algodao) e nao ha cor branca disponivel (so cinza/azul royal) - aderencia parcial"),
    RegistroPreco("UNIFORMES ROUPAS E CALCADOS", 300,
        "CALCA DE UNIFORME BRIM PESADO UNISSEX ALGODAO BOLSOS LATERAIS E TRASEIROS",
        "MG", "20/09/2026", "BHZ EPI Distribuidora Ltda", "31.893.116/0001-20",
        "https://www.loja.bhzepi.com.br/calca-brim-4-bolsos-cinza",
        "Calca Brim Seguranca 4 Bolsos (Fortiline)",
        79.80, 79.80, "Brim confirmado, 4 bolsos funcionais (cobre laterais+traseiros); composicao exata (algodao) nao detalhada na pagina"),
    RegistroPreco("UNIFORMES ROUPAS E CALCADOS", 302,
        "JALECO DE SERVICO BRIM UNISSEX ALGODAO MANGA CURTA 3 BOLSOS GOLA ESPORTE",
        "SP", "20/09/2026", "Livpro Ltda", "60.147.971/0001-90",
        "https://livpro.com.br/products/jaleco-manga-curta-3-bolsos-100-algodao",
        "Jaleco Manga Curta 3 Bolsos Operacional (100% algodao)",
        71.90, 71.90, "Otima aderencia: manga curta, 3 bolsos (2 inferiores + 1 superior), 100% algodao confirmado; gola esporte nao especificada"),
    RegistroPreco("UNIFORMES ROUPAS E CALCADOS", 301,
        "CAMISA MANGA CURTA GOLA CARECA. TECIDO: MALHA ALGODAO BRANCO ORIGINAL EPI",
        "SP", "20/09/2026", "Livpro Ltda", "60.147.971/0001-90",
        "https://livpro.com.br/products/kit-5-camisas-masc-gola-redonda-caimento-e-conforto-premium",
        "Kit 5 Camiseta Masculina Malha PV Gola Redonda (preco por unidade = kit/5)",
        169.00, 33.80, "Preco de kit com 5 unidades (R$169,00), dividido por 5 = R$33,80/unidade; gola redonda confere, mas tecido e malha PV (poliester+viscose), nao algodao - aderencia parcial",
        obs_frete="Preco por unidade calculado a partir do kit de 5 (R$169,00 / 5) - venda so em kit fechado"),
    RegistroPreco("UNIFORMES ROUPAS E CALCADOS", 302,
        "JALECO DE SERVICO BRIM UNISSEX ALGODAO MANGA CURTA 3 BOLSOS GOLA ESPORTE",
        "SP", "20/09/2026", "Brasbord (ACB Confeccoes de Uniformes Ltda)", "08.305.131/0001-99",
        "https://www.brasbord.com/jaleco-guarda-po-em-brim-algodao",
        "Jaleco Guarda Po em Brim (P/M/G) - preco de ATACADO",
        78.90, 69.90, "Preco explicitamente rotulado ATACADO (vs varejo R$78,90) na propria pagina, minimo 6 pecas; manga curta, 3 bolsos, 100% algodao - otima aderencia",
        9.00, scroll_y=1350),  # pagina tem banner promocional e galeria de cores no topo; preco so aparece depois de rolar
    RegistroPreco("UNIFORMES ROUPAS E CALCADOS", 309,
        "TENIS DE SEGURANCA COURO VAQUETA TAMANHO 41 PRETO COM CADARCO BIQUEIRA EM PVC SP700 BOMPEL",
        "SP", "20/09/2026", "Dimensional Brasil Solucoes Ltda", "06.913.480/0001-68",
        "https://www.dimensional.com.br/tenis-cadarco-bi-bico-plastico-pt-n42-4090httb4400lg-fujiwara/p",
        "Tenis Vaqueta Cadarco Biqueira Plastico Preta - Fujiwara 4041HTTB4400LG",
        172.99, 155.69, "Couro vaqueta e cadarco conferem (preto); biqueira e generica 'plastico', spec pede PVC - aderencia parcial; marca Fujiwara (nao Bompel/SP700 exato)",
        17.30),
    RegistroPreco("UNIFORMES ROUPAS E CALCADOS", 309,
        "TENIS DE SEGURANCA COURO VAQUETA TAMANHO 41 PRETO COM CADARCO BIQUEIRA EM PVC SP700 BOMPEL",
        "SC", "20/09/2026", "Prosul Equipamentos Ltda", "48.815.919/0001-60",
        "https://prosuldistribuidora.com.br/produto/tenis-bompel-preto-ca-33791/",
        "Tenis Bompel Preto CA 33791 - Modelo SP700, Vaqueta, Biqueira PVC",
        179.10, 170.15, "MATCH EXATO com a especificacao: modelo SP700, marca Bompel, couro vaqueta, cadarco, biqueira PVC, preto (confirmado na ficha tecnica do produto). Preco a vista no pix (5% desc)",
        8.95),
]

COLUNAS_FNDE_OUTPUT = [
    "Categoria", "Código FGV", "Item", "UF", "Data coleta", "Nome Empresa",
    "CNPJ", "FONTE", "PRODUTO PESQUISADO", "Preço PRODUTO", "VALOR DESCONTO",
    "OBS Desconto", "PREÇO FINAL", "VALOR FRETE", "OBS FRETE",
]


# ---------------------------------------------------------------------------
# 4) GERACAO DA PLANILHA output/FNDE_output.xlsx
# ---------------------------------------------------------------------------

def gerar_planilha(registros: list[RegistroPreco]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "Plan1"
    ws.append(COLUNAS_FNDE_OUTPUT)

    for r in registros:
        ws.append([
            r.categoria, r.codigo_fgv, r.item, r.uf, r.data_coleta, r.empresa,
            r.cnpj, r.fonte, r.produto_pesquisado, r.preco_produto,
            r.valor_desconto, r.obs_desconto, r.valor_final, r.valor_frete,
            r.obs_frete,
        ])

    wb.save(PLANILHA_SAIDA)
    log.info(f"Planilha gerada: {PLANILHA_SAIDA} ({len(registros)} linhas)")


# ---------------------------------------------------------------------------
# 5) CAPTURA DE PRINTS (Playwright + Chromium baixado pelo proprio Playwright)
# ---------------------------------------------------------------------------

def slug_fornecedor(nome: str) -> str:
    texto = re.sub(r"[^a-zA-Z0-9]+", "_", nome).strip("_").lower()
    return texto[:40]


def capturar_prints(registros: list[RegistroPreco]) -> None:
    PRINTS_DIR.mkdir(parents=True, exist_ok=True)

    por_item: dict[int, list[RegistroPreco]] = {}
    for r in registros:
        por_item.setdefault(r.codigo_fgv, []).append(r)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})

        for codigo_fgv, itens in sorted(por_item.items()):
            pasta_item = PRINTS_DIR / str(codigo_fgv)
            pasta_item.mkdir(parents=True, exist_ok=True)
            log.info(f"\n### Capturando prints do item {codigo_fgv} ({len(itens)} precos) -> {pasta_item}")

            for idx, r in enumerate(itens, start=1):
                nome_arquivo = f"print_{idx:02d}_{slug_fornecedor(r.empresa)}.png"
                caminho = pasta_item / nome_arquivo
                try:
                    page.goto(r.fonte, timeout=30000, wait_until="domcontentloaded")
                    page.wait_for_timeout(2000)
                    if r.scroll_y:
                        page.mouse.wheel(0, r.scroll_y)
                        page.wait_for_timeout(1000)
                    page.screenshot(path=str(caminho), full_page=False)
                    log.info(f"  OK: {r.empresa} -> {nome_arquivo}")
                except PlaywrightTimeoutError:
                    log.error(f"  TIMEOUT ao abrir {r.fonte} ({r.empresa}) -- print nao capturado")
                except Exception as e:
                    log.exception(f"  ERRO ao capturar print de {r.empresa} ({r.fonte}): {e}")

        browser.close()


# ---------------------------------------------------------------------------
# 6) EXECUCAO
# ---------------------------------------------------------------------------

def main() -> None:
    log.info("Inicio da execucao -- coleta_precos_fnde_uniformes.py")

    log.info(f"\n=== 1) Validando CNAE de {len(REGISTROS_UNIFORMES)} registros (fornecedores unicos) ===")
    cnpjs_ja_validados: set[str] = set()
    for r in REGISTROS_UNIFORMES:
        if r.cnpj in cnpjs_ja_validados:
            continue
        cnpjs_ja_validados.add(r.cnpj)
        validar_fornecedor(r.empresa, r.cnpj, r.fonte)
        time.sleep(1.0)  # evita rate limit (429) da BrasilAPI em rajada

    log.info("\n=== 2) Gerando planilha de saida ===")
    gerar_planilha(REGISTROS_UNIFORMES)

    log.info("\n=== 3) Capturando prints de cada produto/preco ===")
    capturar_prints(REGISTROS_UNIFORMES)

    log.info("\nExecucao finalizada. Verifique output/FNDE_output.xlsx e output/prints/.")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log.exception("Execucao encerrada por erro nao tratado")
        raise
    else:
        log.info("Execucao da coleta FNDE (UNIFORMES) finalizada com sucesso")
