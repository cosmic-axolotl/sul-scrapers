"""Gera os diagramas do projeto em SVG e PNG.

Cada diagrama mostra um mecanismo que o texto explica devagar: o caminho
real dos dados, o ponto em que uma decisao e tomada, a fronteira que
separa duas frentes de trabalho. Nada de enfeite -- se a figura nao
responde uma pergunta que a prosa deixa em aberto, ela nao entra.

Paleta pensada para papel branco (Word e Markdown), nao para tela escura.
"""

from __future__ import annotations

import sys
from pathlib import Path

# --- paleta -----------------------------------------------------------------
TINTA = "#111827"       # texto principal
FRACO = "#6b7280"       # texto secundario
LINHA = "#9ca3af"       # setas e bordas neutras
PROC = "#1d4ed8"        # processo (script que roda)
PROC_BG = "#eff6ff"
DADO_BG = "#f3f4f6"     # arquivo em disco
DADO_BORDA = "#d1d5db"
OK = "#047857"          # caminho que passa
OK_BG = "#ecfdf5"
NAO = "#b91c1c"         # caminho que reprova
NAO_BG = "#fef2f2"
ATENCAO = "#b45309"     # caminho que pede olho humano
ATENCAO_BG = "#fffbeb"

FONTE = "'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
MONO = "Consolas,'Courier New',monospace"


def _esc(t: str) -> str:
    return (t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def texto(x, y, t, *, tam=13, cor=TINTA, peso="400", anc="start", mono=False,
          op=1.0):
    fam = MONO if mono else FONTE
    return (f'<text x="{x}" y="{y}" font-family="{fam}" font-size="{tam}" '
            f'fill="{cor}" font-weight="{peso}" text-anchor="{anc}" '
            f'opacity="{op}">{_esc(t)}</text>')


def caixa(x, y, w, h, *, borda=DADO_BORDA, fundo="#ffffff", r=6, traco=1.5,
          tracejado=False):
    dash = ' stroke-dasharray="5 4"' if tracejado else ""
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" '
            f'fill="{fundo}" stroke="{borda}" stroke-width="{traco}"{dash}/>')


def proc(x, y, w, h, titulo, sub=""):
    """Caixa de processo: um script que roda."""
    s = [caixa(x, y, w, h, borda=PROC, fundo=PROC_BG, traco=1.8)]
    cy = y + (h / 2 + 5 if not sub else h / 2 - 3)
    s.append(texto(x + w / 2, cy, titulo, tam=13.5, peso="600", cor=PROC, anc="middle"))
    if sub:
        s.append(texto(x + w / 2, cy + 16, sub, tam=11, cor=FRACO, anc="middle"))
    return "".join(s)


def dado(x, y, w, h, titulo, sub="", *, cor=TINTA, fundo=DADO_BG, borda=DADO_BORDA):
    """Caixa de arquivo em disco."""
    s = [caixa(x, y, w, h, borda=borda, fundo=fundo)]
    cy = y + (h / 2 + 4 if not sub else h / 2 - 4)
    s.append(texto(x + w / 2, cy, titulo, tam=12, mono=True, cor=cor, anc="middle"))
    if sub:
        s.append(texto(x + w / 2, cy + 15, sub, tam=10.5, cor=FRACO, anc="middle"))
    return "".join(s)


def seta(x1, y1, x2, y2, *, cor=LINHA, rotulo="", larg=1.8, tracejado=False,
         rot_lado="cima", rot_cor=None):
    dash = ' stroke-dasharray="6 4"' if tracejado else ""
    s = [f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{cor}" '
         f'stroke-width="{larg}" marker-end="url(#ponta)"{dash}/>']
    if rotulo:
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        dy = -7 if rot_lado == "cima" else 15
        s.append(texto(mx, my + dy, rotulo, tam=10.5, cor=rot_cor or FRACO,
                       anc="middle"))
    return "".join(s)


def svg(largura, altura, corpo, titulo=""):
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {largura} {altura}"
 width="{largura}" height="{altura}" font-family="{FONTE}">
<defs>
  <marker id="ponta" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6"
          markerHeight="6" orient="auto-start-reverse">
    <path d="M 0 0 L 10 5 L 0 10 z" fill="{LINHA}"/>
  </marker>
  <marker id="ponta-nao" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6"
          markerHeight="6" orient="auto-start-reverse">
    <path d="M 0 0 L 10 5 L 0 10 z" fill="{NAO}"/>
  </marker>
  <marker id="ponta-ok" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6"
          markerHeight="6" orient="auto-start-reverse">
    <path d="M 0 0 L 10 5 L 0 10 z" fill="{OK}"/>
  </marker>
</defs>
<rect width="{largura}" height="{altura}" fill="#ffffff"/>
{corpo}
</svg>'''


def quebrar(t: str, largura: int) -> list[str]:
    """Quebra por palavra, nunca no meio dela."""
    linhas, atual = [], ""
    for p in t.split():
        if atual and len(atual) + 1 + len(p) > largura:
            linhas.append(atual)
            atual = p
        else:
            atual = f"{atual} {p}".strip()
    if atual:
        linhas.append(atual)
    return linhas


def cabecalho(x, y, t, sub=""):
    s = [texto(x, y, t, tam=17, peso="700")]
    if sub:
        s.append(texto(x, y + 19, sub, tam=12, cor=FRACO))
    return "".join(s)


# ===========================================================================
# 01 — fluxo de dados entre as pastas
# ===========================================================================

def d01():
    L, A = 1430, 600
    s = [cabecalho(40, 44, "Fluxo de dados — do que a equipe encontra até a entrega",
                   "Linha de cima: o script que roda.  Linha de baixo: o que ele "
                   "escreve em disco.  Um arquivo por site, sempre.")]

    y_proc, h_proc = 130, 64
    y_dado, h_dado = 272, 58

    # --- coluna de entrada humana, numa faixa só dela ---
    s.append(texto(40, 112, "ENTRADA HUMANA", tam=10.5, peso="700", cor=FRACO))
    s.append(dado(40, 124, 214, 54, "data/raw/*.xlsx", "planilhas originais"))
    s.append(dado(40, 190, 214, 54, "data/raw/leads/", "prospecção, formato livre"))

    passos = [
        (310, 180, "etapa1_validar", "CNPJ · CNAE · entrega",
         ("fornecedores_master.csv", "o banco de sites"),
         [("sem_site.csv", "CNPJ sem domínio")]),
        (524, 210, "orquestrador varredura", "um processo por site",
         ("achados/{dominio}.csv", "item × loja"), []),
        (768, 170, "etapa2_plano", "consolida e cruza",
         ("plano_coleta.csv", "site → itens"),
         [("revisar.csv", "match duvidoso"), ("cobertura_*.xlsx", "o painel")]),
        (972, 190, "orquestrador coleta", "preço · frete · print",
         ("coletas/{dominio}.jsonl", "uma linha por registro"),
         [("prints/…png", "a prova")]),
        (1198, 180, "montar_entrega", "escolhe os 5",
         ("{CATEGORIA}.xlsx", "A ENTREGA"),
         [("reserva.csv", "quem não entrou"), ("pendencias.csv", "sem 5 fontes")]),
    ]

    for i, (x, w, nome, sub, saida, extras) in enumerate(passos):
        s.append(proc(x, y_proc, w, h_proc, nome, sub))
        s.append(seta(x + w / 2, y_proc + h_proc, x + w / 2, y_dado - 4))
        destaque = i == len(passos) - 1
        s.append(dado(x, y_dado, w, h_dado, saida[0], saida[1],
                      fundo=OK_BG if destaque else DADO_BG,
                      borda=OK if destaque else DADO_BORDA))
        yy = y_dado + h_dado + 14
        for t, st in extras:
            s.append(dado(x, yy, w, 46, t, st))
            yy += 58

    # entradas -> etapa 1
    s.append(seta(254, 151, 306, 156))
    s.append(seta(254, 217, 306, 180))

    # zigue-zague: o arquivo alimenta o PROXIMO script, nao o proximo arquivo
    for i in range(len(passos) - 1):
        x1 = passos[i][0] + passos[i][1] + 4
        x2 = passos[i + 1][0] + 34
        s.append(seta(x1, y_dado + 29, x2, y_proc + h_proc + 6))

    # nota sobre os dois planos
    s.append(caixa(500, 470, 900, 76, borda=PROC, fundo=PROC_BG, tracejado=True))
    s.append(texto(522, 496, "A varredura NÃO lê o plano_coleta.csv.",
                   tam=12.5, peso="700", cor=PROC))
    s.append(texto(522, 516,
                   "Ela monta o trabalho a partir do fornecedores_master.csv: todo site "
                   "APROVADO × todo item da categoria. Fazer as duas fases", tam=11.5))
    s.append(texto(522, 533,
                   "lerem o mesmo arquivo criava uma volta fechada — varrer exigia um "
                   "plano que só existe depois de varrer.", tam=11.5))
    s.append(seta(560, 470, 560, 344, tracejado=True, cor=PROC))
    return svg(L, A, "".join(s))


# ===========================================================================
# 02 — os dois planos
# ===========================================================================

def d02():
    L, A = 1000, 430
    s = [cabecalho(40, 44, "As duas fases leem planos diferentes",
                   "A dependência circular que isto resolve foi um bug real do projeto.")]

    s.append(dado(40, 120, 230, 58, "fornecedores_master.csv", "só os APROVADOS"))
    s.append(proc(330, 112, 210, 72, "varredura", "todo site × todo item"))
    s.append(dado(600, 120, 210, 58, "achados/{dominio}.csv", "quem tem o quê"))

    s.append(seta(270, 149, 330, 149, rotulo="plano de BUSCA", rot_cor=PROC))
    s.append(seta(540, 149, 600, 149))

    s.append(proc(600, 250, 210, 62, "etapa2_plano", "consolida"))
    s.append(seta(705, 178, 705, 250))

    s.append(dado(330, 258, 210, 54, "plano_coleta.csv", "site → itens"))
    s.append(seta(600, 285, 540, 285))

    s.append(proc(40, 250, 230, 62, "coleta", "preço · frete · print"))
    s.append(seta(330, 285, 270, 285, rotulo="plano de COLETA", rot_cor=PROC))

    # a seta proibida
    s.append(seta(390, 258, 390, 190, cor=NAO, tracejado=True))
    s.append(f'<g stroke="{NAO}" stroke-width="3">'
             f'<line x1="368" y1="212" x2="412" y2="236"/>'
             f'<line x1="412" y1="212" x2="368" y2="236"/></g>')
    s.append(texto(430, 228, "a varredura nunca lê o plano de coleta", tam=11.5,
                   cor=NAO, peso="600"))

    s.append(caixa(40, 348, 920, 50, borda=LINHA, fundo=DADO_BG, tracejado=True))
    s.append(texto(60, 370, "Quem escolhe entre os dois é montar_lotes(fase, …), "
                            "no orquestrador.", tam=12, peso="600"))
    s.append(texto(60, 388, "Numa base nova, só a varredura consegue começar — e é "
                            "exatamente essa a ordem correta das etapas.", tam=11.5,
                   cor=FRACO))
    return svg(L, A, "".join(s))


# ===========================================================================
# 03 — pipeline da etapa 1
# ===========================================================================

def d03():
    L, A = 1120, 470
    s = [cabecalho(40, 44, "Etapa 1 — como um candidato vira fornecedor aprovado",
                   "90% desta etapa é código. A pesquisa manual entra só para achar "
                   "candidatos novos.")]

    y, h, w = 110, 64, 176
    passos = [
        ("unificar", "2 bases + leads"),
        ("achar CNPJ", "regex no rodapé"),
        ("consultar", "Receita / BrasilAPI"),
        ("classificar", "CNAE 46 / 47"),
        ("testar entrega", "3 CEPs do Sul"),
    ]
    xs = []
    for i, (t, sub) in enumerate(passos):
        x = 40 + i * (w + 36)
        xs.append(x)
        s.append(proc(x, y, w, h, t, sub))
        if i:
            s.append(seta(x - 32, y + h / 2, x - 4, y + h / 2))

    s.append(dado(40, 212, w, 50, "data/raw/leads/", "formato livre"))
    s.append(seta(128, 212, 128, 178))

    # saidas de decisao
    dec_y = 236
    s.append(caixa(636, dec_y, 444, 160, borda=DADO_BORDA, fundo="#ffffff",
                   tracejado=True))
    s.append(texto(656, dec_y + 24, "O que decide o status", tam=12.5, peso="700"))

    regras = [
        (OK, OK_BG, "APROVADO", "CNAE 46 no principal, CNPJ ATIVO, e a loja "
                                "entrega em ao menos uma UF do Sul"),
        (NAO, NAO_BG, "REPROVADO", "CNAE de varejo puro, CNPJ não-ativo, ou "
                                   "RECUSA de entrega nas três UFs"),
        (ATENCAO, ATENCAO_BG, "PENDENTE", "faltou CNPJ, a consulta falhou, ou a "
                                          "entrega não deu para confirmar"),
    ]
    yy = dec_y + 40
    for cor, bg, rotulo, desc in regras:
        s.append(caixa(656, yy, 96, 26, borda=cor, fundo=bg, r=4, traco=1.4))
        s.append(texto(704, yy + 18, rotulo, tam=11, peso="700", cor=cor, anc="middle"))
        for i, linha in enumerate(quebrar(desc, 44)):
            s.append(texto(766, yy + 12 + i * 14, linha, tam=10.5, cor=TINTA))
        yy += 40

    s.append(seta(790, 174, 790, dec_y - 4))

    # o master e a saida da ETAPA INTEIRA, entao a seta vem da decisao
    s.append(dado(40, 320, 340, 56, "data/interim/fornecedores_master.csv",
                  "o banco de sites — regra inviolável 3", fundo=OK_BG, borda=OK))
    s.append(seta(632, 330, 386, 344, cor=OK))

    s.append(dado(40, 396, 340, 44, "data/interim/sem_site.csv",
                  "72 empresas com CNPJ e sem domínio"))
    return svg(L, A, "".join(s))


# ===========================================================================
# 04 — funil do matching
# ===========================================================================

def d04():
    L, A = 1080, 560
    s = [cabecalho(40, 44, "Matching — como um produto é aceito, revisado ou descartado",
                   "Sem EAN e sem marca, isto é o único controle de aderência que "
                   "existe no projeto.")]

    s.append(dado(40, 100, 250, 52, "descrição do item", "texto de licitação, ~300 car."))
    s.append(dado(40, 164, 250, 52, "título do produto", "o que a loja anuncia"))
    s.append(proc(340, 120, 220, 76, "token_set_ratio", "fuzzy sobre texto normalizado"))
    s.append(seta(290, 126, 340, 150))
    s.append(seta(290, 190, 340, 168))

    s.append(caixa(610, 106, 430, 104, borda=DADO_BORDA, fundo=DADO_BG))
    s.append(texto(630, 128, "bônus somados ao score", tam=12, peso="700"))
    for i, (b, t) in enumerate([("+25", "medida numérica bate (12 L, 1500 mm)"),
                                ("+25", "embalagem bate (100 un, 50 pares, kit 5)"),
                                ("+10", "material bate (inox, alumínio)")]):
        s.append(texto(630, 150 + i * 19, b, tam=11.5, peso="700", cor=PROC, mono=True))
        s.append(texto(670, 150 + i * 19, t, tam=11.5))
    s.append(seta(560, 158, 610, 158))

    # vetos
    s.append(caixa(40, 262, 1000, 128, borda=NAO, fundo=NAO_BG, tracejado=True))
    s.append(texto(60, 286, "Divergir custa — não basta deixar de ganhar bônus",
                   tam=13, peso="700", cor=NAO))
    s.append(texto(60, 306, "Era o buraco: uma panela de 50 L perdia 25 pontos e ainda "
                            "entrava no lugar de uma de 20 L, porque o fuzzy cobria a "
                            "diferença.", tam=11.5))
    linhas = [
        (NAO, "embalagem divergente", "pede 100, produto traz 50", "DESCARTADO"),
        (ATENCAO, "embalagem não confirmada", "o título não diz quantas vêm", "no máx. REVISAR"),
        (ATENCAO, "item avulso, produto em pacote", "preço de pacote na linha de 1 un", "no máx. REVISAR"),
        (ATENCAO, "dimensão divergente", "a lista usa 'mínimo' o tempo todo", "no máx. REVISAR"),
    ]
    for i, (cor, o_que, por_que, efeito) in enumerate(linhas):
        yy = 330 + i * 15
        s.append(texto(60, yy, "•", tam=11, cor=cor, peso="700"))
        s.append(texto(74, yy, o_que, tam=11, peso="600"))
        s.append(texto(266, yy, por_que, tam=10.5, cor=FRACO))
        s.append(texto(560, yy, "→ " + efeito, tam=11, peso="700", cor=cor))

    # saidas
    saidas = [
        (40, OK, OK_BG, "aceito", "score ≥ 80", "entra no plano_coleta.csv"),
        (390, ATENCAO, ATENCAO_BG, "revisar", "60 – 80", "vai para revisar.csv, espera uma pessoa"),
        (740, NAO, NAO_BG, "descartado", "< 60", "não vira Achado"),
    ]
    for x, cor, bg, t, faixa, dest in saidas:
        s.append(caixa(x, 424, 300, 72, borda=cor, fundo=bg))
        s.append(texto(x + 20, 450, t.upper(), tam=14, peso="700", cor=cor))
        s.append(texto(x + 20, 468, faixa, tam=11.5, mono=True, cor=TINTA))
        s.append(texto(x + 20, 486, dest, tam=10.5, cor=FRACO))
        s.append(seta(x + 150, 390, x + 150, 420, cor=cor))

    s.append(texto(40, 528, "Use matching.avaliar(), que devolve score E decisão. "
                            "matching.pontuar() devolve só o número — e reprovar é "
                            "decisão, não é um número.", tam=11.5, cor=FRACO))
    return svg(L, A, "".join(s))


# ===========================================================================
# 05 — escolha dos cinco
# ===========================================================================

def d05():
    L, A = 1080, 400
    s = [cabecalho(40, 44, "A escolha dos 5 — cinco registros não são cinco fornecedores",
                   "Ordenar e cortar em cinco entregava cinco linhas do mesmo domínio, "
                   "todas sem preço.")]

    s.append(dado(40, 120, 180, 100, "candidatos", "todas as coletas de\n(item, UF)"))
    etapas = [
        (270, "1. descarta o que não serve", ["sem preço", "sem print no disco",
                                              "frete em aberto", "não entrega nesta UF",
                                              "score abaixo do mínimo"]),
        (545, "2. um registro por domínio", ["a entrega pede 5 fornecedores",
                                             "DISTINTOS, não 5 linhas"]),
        (820, "3. ordena e corta", ["maior score_match", "depois menor preço final"]),
    ]
    for x, titulo, itens in etapas:
        s.append(caixa(x, 120, 230, 100, borda=PROC, fundo=PROC_BG))
        s.append(texto(x + 16, 144, titulo, tam=12, peso="700", cor=PROC))
        for i, it in enumerate(itens):
            s.append(texto(x + 16, 164 + i * 14, "· " + it, tam=10.5, cor=TINTA))
        s.append(seta(x - 46, 170, x - 4, 170))

    s.append(caixa(40, 268, 490, 78, borda=OK, fundo=OK_BG))
    s.append(texto(60, 294, "5 linhas na entrega", tam=14, peso="700", cor=OK))
    s.append(texto(60, 314, "5 domínios distintos, cada um com preço e print",
                   tam=11.5))
    s.append(texto(60, 332, "Menos de 5? a combinação item/UF vai para pendencias.csv",
                   tam=10.5, cor=FRACO))

    s.append(caixa(560, 268, 490, 78, borda=DADO_BORDA, fundo=DADO_BG))
    s.append(texto(580, 294, "reserva.csv", tam=14, peso="700", mono=True))
    s.append(texto(580, 314, "todo o resto, COM O MOTIVO de cada exclusão", tam=11.5))
    s.append(texto(580, 332, "sem o motivo, \"por que este não entrou?\" só se responde "
                             "reprocessando tudo", tam=10.5, cor=FRACO))

    s.append(seta(700, 220, 380, 264, cor=OK))
    s.append(seta(900, 220, 800, 264))
    return svg(L, A, "".join(s))


# ===========================================================================
# 06 — módulos e fronteiras
# ===========================================================================

def d06():
    L, A = 1120, 520
    s = [cabecalho(40, 44, "Os módulos e as fronteiras entre as frentes",
                   "A estrutura existe para que 9 pessoas trabalhem em paralelo sem "
                   "colidir nos mesmos arquivos.")]

    grupos = [
        (40, 100, 240, "src/core/", "Frente A",
         ["http.py — sessão, cache, erros", "log.py — o diagnóstico",
          "tabelas.py — os CSV", "matching.py — Frente E", "frete.py — Frente F",
          "plataforma.py — detecção"]),
        (320, 100, 240, "src/adapters/", "Frente D",
         ["base.py — Executor (ABC)", "registro.py — escolhe a classe",
          "vtex.py ✔ completo", "woocommerce · shopify", "nuvemshop — busca pronta",
          "generico_playwright ✖"]),
        (600, 100, 240, "src/runners/", "Frentes A e B",
         ["etapa0_limpar_itens", "etapa1_validar — Frente B",
          "etapa2_varredura", "etapa2_plano", "etapa3_coletar"]),
        (880, 100, 200, "src/export/", "Frente F",
         ["montar_entrega.py", "prints.py", "captura.py"]),
    ]
    for x, y, w, titulo, frente, itens in grupos:
        h = 46 + len(itens) * 17
        s.append(caixa(x, y, w, h, borda=LINHA))
        s.append(texto(x + 14, y + 24, titulo, tam=13, peso="700", mono=True))
        s.append(texto(x + w - 14, y + 24, frente, tam=10.5, cor=PROC, anc="end",
                       peso="600"))
        for i, it in enumerate(itens):
            s.append(texto(x + 14, y + 46 + i * 17, it, tam=10.5, cor=TINTA))

    s.append(caixa(40, 262, 240, 60, borda=LINHA))
    s.append(texto(54, 286, "src/validacao/", tam=13, peso="700", mono=True))
    s.append(texto(266, 286, "Frente B", tam=10.5, cor=PROC, anc="end", peso="600"))
    s.append(texto(54, 306, "extrair · consultar · classificar CNPJ", tam=10.5))

    s.append(caixa(40, 340, 1040, 54, borda=PROC, fundo=PROC_BG))
    s.append(texto(60, 364, "src/models.py — O CONTRATO", tam=13.5, peso="700",
                   cor=PROC, mono=True))
    s.append(texto(60, 382, "Item · Fornecedor · ProdutoBruto · Achado · Coleta. "
                            "É o único ponto onde 9 pessoas colidem de verdade: "
                            "ninguém altera sozinho.", tam=11.5))

    # fronteiras
    s.append(caixa(40, 416, 510, 76, borda=OK, fundo=OK_BG, tracejado=True))
    s.append(texto(60, 440, "Fronteira 1 — adapter ⟷ matching", tam=12, peso="700",
                   cor=OK))
    s.append(texto(60, 458, "O adapter recebe um termo e devolve ProdutoBruto. "
                            "Não pontua,", tam=11))
    s.append(texto(60, 474, "não filtra, não decide. Quem faz matching nunca abre "
                            "um site.", tam=11))

    s.append(caixa(570, 416, 510, 76, borda=OK, fundo=OK_BG, tracejado=True))
    s.append(texto(590, 440, "Fronteira 2 — coletor ⟷ montador", tam=12, peso="700",
                   cor=OK))
    s.append(texto(590, 458, "O coletor escreve .jsonl cru e não conhece o template "
                             "do FNDE.", tam=11))
    s.append(texto(590, 474, "Trocar o formato da entrega não toca em uma linha de "
                             "scraper.", tam=11))
    return svg(L, A, "".join(s))


# ===========================================================================
# 07 — arquivos de instrução
# ===========================================================================

def d07():
    L, A = 1000, 400
    s = [cabecalho(40, 44, "Os arquivos de instrução — uma fonte, dois ponteiros",
                   "O repositório não pertence a nenhuma ferramenta de IA.")]

    s.append(caixa(370, 110, 260, 92, borda=PROC, fundo=PROC_BG, traco=2.2))
    s.append(texto(500, 142, "AGENTS.md", tam=18, peso="700", cor=PROC, anc="middle",
                   mono=True))
    s.append(texto(500, 164, "a fonte única", tam=12, cor=TINTA, anc="middle"))
    s.append(texto(500, 184, "o único que se edita", tam=11, cor=FRACO, anc="middle"))

    s.append(dado(40, 120, 230, 72, "CLAUDE.md", "uma linha: @AGENTS.md"))
    s.append(texto(155, 176, "Claude Code lê este nome", tam=10, cor=FRACO,
                   anc="middle"))
    s.append(seta(270, 156, 366, 156, rotulo="aponta"))

    s.append(dado(730, 120, 230, 72, "GEMINI.md", "aponta para o AGENTS.md"))
    s.append(texto(845, 176, "Gemini CLI lê este nome", tam=10, cor=FRACO,
                   anc="middle"))
    s.append(seta(726, 156, 634, 156, rotulo="aponta"))

    s.append(dado(730, 214, 230, 56, ".gemini/settings.json",
                  "faz o Gemini ler direto"))
    s.append(seta(726, 242, 634, 190, tracejado=True))

    s.append(caixa(40, 232, 640, 56, borda=DADO_BORDA, fundo=DADO_BG))
    s.append(texto(60, 254, "Leem AGENTS.md nativamente:", tam=11.5, peso="700"))
    s.append(texto(60, 274, "Codex · Jules · Gemini CLI · Copilot · Cursor · Aider · "
                            "Zed — e mais de trinta outras", tam=11.5))

    s.append(caixa(40, 312, 920, 56, borda=NAO, fundo=NAO_BG, tracejado=True))
    s.append(texto(60, 334, "Editar CLAUDE.md ou GEMINI.md cria uma divergência",
                   tam=12.5, peso="700", cor=NAO))
    s.append(texto(60, 354, "Em uma semana os arquivos discordam e ninguém sabe qual "
                            "está certo. Todo conteúdo novo vai para o AGENTS.md.",
                   tam=11.5))
    return svg(L, A, "".join(s))


DIAGRAMAS = {
    "01-fluxo-de-dados": d01,
    "02-dois-planos": d02,
    "03-pipeline-etapa1": d03,
    "04-funil-matching": d04,
    "05-escolha-dos-cinco": d05,
    "06-modulos-e-fronteiras": d06,
    "07-arquivos-de-instrucao": d07,
}


def main(destino: Path):
    destino.mkdir(parents=True, exist_ok=True)
    gerados = []
    for nome, fn in DIAGRAMAS.items():
        caminho = destino / f"{nome}.svg"
        caminho.write_text(fn(), encoding="utf-8")
        gerados.append(caminho)
        print(f"  svg  {caminho.name}")
    return gerados


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "docs/img"))
