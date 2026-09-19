"""Decide se um produto encontrado atende a descrição solicitada.

Sem EAN e sem marca, isto aqui é o único controle de aderência que
existe no projeto. Vale ser rigoroso.

Duas coisas que a versão anterior deixava passar, e que esta trata:

1. **Embalagem.** O item 294 pede 100 máscaras, o 313 pede 50 pares de
   protetores, o U053 pede um kit com 5 tábuas. A expressão de medidas
   não reconhecia "unidades" nem "par", então "100UNIDADE" não era medida
   nenhuma e uma máscara avulsa competia de igual para igual com o pacote
   de 100 -- com o preço de uma máscara.

2. **Divergência.** Medida batida dava bônus; medida diferente não
   custava nada. Uma panela de 50 L entrava no lugar de uma de 20 L
   perdendo só os 25 pontos de bônus, e o fuzzy textual sozinho
   frequentemente cobria a diferença.

Agora a divergência tem efeito. A escala de efeitos é deliberada:

    embalagem exigida e divergente   -> descartado
    embalagem exigida e ausente      -> no máximo "revisar"
    item avulso e produto em pacote  -> no máximo "revisar"
    dimensão divergente              -> no máximo "revisar"
    dimensão ausente                 -> só perde o bônus

Dimensão divergente não descarta porque a lista usa "mínimo", "máximo" e
"aproximadamente" o tempo todo (o item 318N pede comprimento mínimo de
1,00 m): um avental de 1,20 m atende, e descartar perderia candidato
legítimo. Embalagem divergente descarta porque não existe leitura em que
um pacote de 50 atenda quem pediu 100.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from rapidfuzz import fuzz
from unidecode import unidecode

STOPWORDS = {"de", "da", "do", "com", "para", "em", "e", "a", "o", "tipo", "cor",
             "aproximadamente", "aproximada", "minima", "maxima", "conforme"}

MATERIAIS = ("inox", "inoxidavel", "aluminio", "plastico", "polipropileno",
             "aco carbono", "vidro", "silicone", "nylon")

# --- dimensões -------------------------------------------------------------
# Cada unidade vira (família, fator para a unidade canônica da família).
# Comparar 1 m com 100 cm exige isso; comparar 1 m com 1 kg não pode
# acontecer, daí a família.
DIMENSOES: dict[str, tuple[str, float]] = {
    "mm": ("comprimento", 0.001),
    "milimetro": ("comprimento", 0.001),
    "cm": ("comprimento", 0.01),
    "centimetro": ("comprimento", 0.01),
    "m": ("comprimento", 1.0),
    "metro": ("comprimento", 1.0),
    "pol": ("comprimento", 0.0254),
    "polegada": ("comprimento", 0.0254),
    '"': ("comprimento", 0.0254),
    "ml": ("volume", 0.001),
    "l": ("volume", 1.0),
    "litro": ("volume", 1.0),
    "g": ("massa", 0.001),
    "grama": ("massa", 0.001),
    "kg": ("massa", 1.0),
    "quilo": ("massa", 1.0),
    "w": ("potencia", 1.0),
    "kw": ("potencia", 1000.0),
}

# Ordem importa: as maiores primeiro, senão "mm" é lido como "m".
_UNIDADES_DIM = "|".join(
    sorted((re.escape(u) for u in DIMENSOES), key=len, reverse=True)
)
RE_DIMENSAO = re.compile(
    rf"(\d+(?:[.,]\d+)?)\s*({_UNIDADES_DIM})s?(?![a-z0-9])"
)

# "50 x 30 x 0,8 cm": a unidade vem uma vez só, no fim, e vale para os
# três números. É a forma que a lista do FNDE usa para dar dimensões, e
# sem isto só a espessura era lida.
RE_CADEIA = re.compile(
    rf"(\d+(?:[.,]\d+)?(?:\s*[x*]\s*\d+(?:[.,]\d+)?)+)\s*({_UNIDADES_DIM})s?(?![a-z0-9])"
)

# --- embalagem -------------------------------------------------------------
# "100 unidades", "100unidade", "50 pares", "12 pcs".
PECAS: dict[str, str] = {
    "unidades": "un", "unidade": "un", "unid": "un", "und": "un", "un": "un",
    "pecas": "un", "peca": "un", "pcs": "un", "pc": "un",
    "pares": "par", "par": "par",
}
_UNIDADES_PECA = "|".join(sorted(PECAS, key=len, reverse=True))
RE_QUANTIDADE = re.compile(rf"(\d+)\s*({_UNIDADES_PECA})(?![a-z0-9])")

# "pacote com 100", "kit c/ 5", "caixa contendo 50", "kit composto por 5".
RECIPIENTES = ("pacote", "pct", "caixa", "cx", "kit", "conjunto", "jogo",
               "fardo", "cartela", "embalagem", "display", "blister")
_RECIPIENTES = "|".join(RECIPIENTES)
# O conectivo é opcional ("kit 5 tábuas" conta tanto quanto "kit com 5
# tábuas"), mas o número não pode ser seguido de unidade de dimensão:
# senão "caixa 20 l" -- uma caixa de vinte litros -- viraria uma caixa
# com vinte peças.
RE_RECIPIENTE_QTD = re.compile(
    rf"({_RECIPIENTES})\s*(?:com|c/|contendo|composto\s+por|de)?\s*(\d+)"
    rf"(?!\s*(?:{_UNIDADES_DIM})s?(?![a-z0-9]))"
)
RE_RECIPIENTE = re.compile(rf"(?<![a-z]){_RECIPIENTES}(?![a-z])")

BONUS_MEDIDA = 25.0
BONUS_MATERIAL = 10.0
BONUS_EMBALAGEM = 25.0
LIMITE_ACEITE = 80.0
LIMITE_REVISAO = 60.0

# Duas medidas são a mesma medida com 2% de folga: cobre 0,8 vs 0,80,
# arredondamento de polegada e a diferença entre 1 m e 100 cm.
TOLERANCIA = 0.02


def normalizar(texto: str) -> str:
    t = unidecode(texto or "").lower()
    t = re.sub(r"[^a-z0-9,.\"\s]", " ", t)
    palavras = [p for p in t.split() if p not in STOPWORDS]
    return " ".join(palavras)


def _texto_medidas(texto: str) -> str:
    """Como `normalizar`, mas SEM tirar stopword.

    "pacote com 100" vira "pacote 100" se as stopwords saírem, e aí
    "caixa 20 l" (uma caixa de 20 litros) fica indistinguível de "caixa
    com 20" (vinte peças). O conectivo é o que separa os dois casos, e
    por isso ele precisa sobreviver até a extração.
    """
    t = unidecode(texto or "").lower()
    return re.sub(r"[^a-z0-9,./\"\s]", " ", t)


# ---------------------------------------------------------------------------
# Extração
# ---------------------------------------------------------------------------

def dimensoes(texto: str) -> set[tuple[str, float]]:
    """(família, valor na unidade canônica). 100 cm e 1 m dão o mesmo par."""
    t = _texto_medidas(texto)
    achados: set[tuple[str, float]] = set()

    for cadeia, unidade in RE_CADEIA.findall(t):
        familia, fator = DIMENSOES[unidade]
        for numero in re.split(r"[x*]", cadeia):
            achados.add((familia, float(numero.strip().replace(",", ".")) * fator))

    for valor, unidade in RE_DIMENSAO.findall(t):
        familia, fator = DIMENSOES[unidade]
        achados.add((familia, float(valor.replace(",", ".")) * fator))
    return achados


def medidas(texto: str) -> set[tuple[float, str]]:
    """Compatibilidade com quem já usava (valor, unidade)."""
    return {(valor, familia) for familia, valor in dimensoes(texto)}


@dataclass(frozen=True)
class Embalagem:
    """Quantas peças vêm na embalagem, e em que recipiente."""

    quantidades: frozenset[tuple[str, int]] = frozenset()  # ("un", 100)
    recipiente: str | None = None

    @property
    def avulso(self) -> bool:
        """Uma peça só: nada a exigir do outro lado."""
        return all(q <= 1 for _, q in self.quantidades)

    @property
    def numeros(self) -> set[int]:
        return {q for _, q in self.quantidades}

    def __bool__(self) -> bool:
        return bool(self.quantidades) or self.recipiente is not None


def embalagem(texto: str) -> Embalagem:
    t = _texto_medidas(texto)

    quantidades: set[tuple[str, int]] = set()
    for valor, unidade in RE_QUANTIDADE.findall(t):
        quantidades.add((PECAS[unidade], int(valor)))
    for _recipiente, valor in RE_RECIPIENTE_QTD.findall(t):
        quantidades.add(("un", int(valor)))

    encontrado = RE_RECIPIENTE.search(t)
    return Embalagem(
        quantidades=frozenset(quantidades),
        recipiente=encontrado.group(0) if encontrado else None,
    )


def materiais(texto: str) -> set[str]:
    t = normalizar(texto)
    return {m for m in MATERIAIS if m in t}


# ---------------------------------------------------------------------------
# Comparação
# ---------------------------------------------------------------------------

def _mesmo_valor(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=TOLERANCIA, abs_tol=1e-9)


def comparar_dimensoes(item: str, produto: str) -> tuple[str, str]:
    """'bate' | 'diverge' | 'ausente', com o motivo em texto."""
    do_item = dimensoes(item)
    do_produto = dimensoes(produto)
    if not do_item or not do_produto:
        return "ausente", ""

    familias = {f for f, _ in do_item} & {f for f, _ in do_produto}
    if not familias:
        return "ausente", ""

    for familia in familias:
        valores_item = [v for f, v in do_item if f == familia]
        valores_produto = [v for f, v in do_produto if f == familia]
        if any(_mesmo_valor(a, b) for a in valores_item for b in valores_produto):
            return "bate", f"{familia} confere"

    familia = sorted(familias)[0]
    pedido = sorted(v for f, v in do_item if f == familia)
    oferta = sorted(v for f, v in do_produto if f == familia)
    return "diverge", f"{familia} pedida {pedido} e o produto traz {oferta}"


def comparar_embalagem(item: str, produto: str) -> tuple[str, str]:
    """'bate' | 'diverge' | 'ausente' | 'avulso_virou_pacote' | 'irrelevante'."""
    do_item = embalagem(item)
    do_produto = embalagem(produto)

    exigidas = {q for q in do_item.numeros if q > 1}
    oferecidas = {q for q in do_produto.numeros if q > 1}

    if not exigidas:
        # O item é vendido por unidade. Um pacote tem o preço do pacote,
        # que não é o preço que a planilha pede.
        if oferecidas:
            return "avulso_virou_pacote", (
                f"item avulso, mas o produto vem em {sorted(oferecidas)} peças"
            )
        return "irrelevante", ""

    if not oferecidas:
        return "ausente", (
            f"item exige {sorted(exigidas)} peças e o título do produto não diz "
            "quantas vêm"
        )

    if exigidas & oferecidas:
        return "bate", f"embalagem de {sorted(exigidas & oferecidas)} peças confere"

    return "diverge", (
        f"item exige {sorted(exigidas)} peças e o produto traz {sorted(oferecidas)}"
    )


# ---------------------------------------------------------------------------
# Pontuação
# ---------------------------------------------------------------------------

@dataclass
class Avaliacao:
    """O veredito completo. É isto que a varredura grava e revisa."""

    score: float
    classificacao: str  # aceito | revisar | descartado
    motivos: list[str] = field(default_factory=list)
    dimensao: str = "ausente"
    embalagem: str = "irrelevante"

    @property
    def motivo(self) -> str:
        return "; ".join(m for m in self.motivos if m)

    @property
    def score_normalizado(self) -> float:
        """0..1, que é como o Achado guarda."""
        return round(min(self.score, 125.0) / 125.0, 3)


def pontuar(descricao_item: str, titulo_produto: str) -> float:
    """Score 0..100+. Fuzzy textual mais bônus por medida, material e embalagem.

    A medida numérica é o sinal mais forte que existe neste domínio:
    "panela 20 L" e "panela 50 L" são produtos diferentes com o mesmo
    nome, e o fuzzy sozinho não distingue os dois.

    O score não carrega a reprovação por divergência -- isso é trabalho
    de `avaliar()`, porque reprovar é uma decisão e não um número.
    """
    return avaliar(descricao_item, titulo_produto).score


def avaliar(descricao_item: str, titulo_produto: str) -> Avaliacao:
    """Score + decisão. Use esta função, não `pontuar` sozinha."""
    base = fuzz.token_set_ratio(normalizar(descricao_item), normalizar(titulo_produto))
    motivos: list[str] = []
    teto: str | None = None

    dim, motivo_dim = comparar_dimensoes(descricao_item, titulo_produto)
    if dim == "bate":
        base += BONUS_MEDIDA
    elif dim == "diverge":
        motivos.append(motivo_dim)
        teto = "revisar"

    emb, motivo_emb = comparar_embalagem(descricao_item, titulo_produto)
    if emb == "bate":
        base += BONUS_EMBALAGEM
    elif emb == "diverge":
        motivos.append(motivo_emb)
        return Avaliacao(base, "descartado", motivos, dim, emb)
    elif emb in ("ausente", "avulso_virou_pacote"):
        motivos.append(motivo_emb)
        teto = "revisar"

    if materiais(descricao_item) & materiais(titulo_produto):
        base += BONUS_MATERIAL

    decisao = classificar(base)
    if teto == "revisar" and decisao == "aceito":
        decisao = "revisar"

    return Avaliacao(base, decisao, motivos, dim, emb)


def classificar(score: float) -> str:
    """'aceito' | 'revisar' | 'descartado'"""
    if score >= LIMITE_ACEITE:
        return "aceito"
    if score >= LIMITE_REVISAO:
        return "revisar"
    return "descartado"


def gerar_termos(item) -> list[str]:
    """Do texto de licitação para 2-4 buscas que uma loja entende.

    A descrição do FNDE tem ~300 caracteres. Jogar isso inteiro num
    campo de busca não retorna nada.

    Do mais específico ao mais genérico: a varredura para no primeiro que
    der match bom, então a ordem importa. Quando o item é um pacote, a
    quantidade entra no termo -- é assim que a loja indexa o produto
    ("máscara descartável 100 unidades") e é o que separa o pacote da
    peça avulsa já na busca, antes do matching.
    """
    grupo = normalizar(item.grupo_insumo)
    primeiras = " ".join(normalizar(item.descricao).split()[:4])
    termos = [primeiras, grupo]

    # A maior dimensão, não a primeira: "tábua corte 50 cm" é uma busca
    # que a loja responde; "tábua corte 0,8 cm" (a espessura) não é.
    for familia, valor in sorted(dimensoes(item.descricao), key=lambda d: -d[1]):
        termos.insert(0, f"{grupo} {_legivel(familia, valor)}")
        break

    emb = embalagem(item.descricao)
    exigidas = sorted(q for q in emb.numeros if q > 1)
    if exigidas:
        unidade = "pares" if ("par", exigidas[0]) in emb.quantidades else "unidades"
        termos.insert(0, f"{grupo} {exigidas[-1]} {unidade}")

    vistos, saida = set(), []
    for t in termos:
        if t and t not in vistos:
            vistos.add(t)
            saida.append(t)
    return saida[:4]


def _legivel(familia: str, valor: float) -> str:
    """Valor canônico de volta para a unidade em que a loja anuncia.

    0,008 m é espessura de tábua; ninguém procura assim. Vira "0,8 cm".
    """
    escalas = {
        "comprimento": ((1.0, "m"), (0.01, "cm"), (0.001, "mm")),
        "volume": ((1.0, "l"), (0.001, "ml")),
        "massa": ((1.0, "kg"), (0.001, "g")),
        "potencia": ((1000.0, "kw"), (1.0, "w")),
    }
    for fator, sufixo in escalas.get(familia, ((1.0, ""),)):
        if valor >= fator:
            return f"{valor / fator:g} {sufixo}".strip()
    fator, sufixo = escalas.get(familia, ((1.0, ""),))[-1]
    return f"{valor / fator:g} {sufixo}".strip()
