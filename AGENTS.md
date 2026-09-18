# AGENTS.md — sul-scrapers

Contexto operativo do projeto, para qualquer assistente de código.

Este arquivo é a fonte única. `CLAUDE.md` e `GEMINI.md` apenas apontam para ele —
edite aqui, nunca lá. O guia completo para humanos está em `docs/GUIA.md`, e a
estrutura do repositório em `docs/ESTRUTURA.md`.

## O que este projeto entrega

Planilha de preços de 144 itens da Lista de Equipamentos FNDE, com **5 preços por item e por UF** (PR, SC, RS), de **5 fornecedores distintos** por item. Total: 2.160 linhas. Prazo: 25/09/2026.

Template de saída: `data/raw/FNDE_output.xlsx` (15 colunas) + uma 16ª coluna `PRINT`.

## Regras invioláveis

1. **Só entra fornecedor com CNAE principal na divisão 46** (atacado). Divisão 47 com 46 secundário entra com `flag_atacarejo = SIM`. Situação cadastral diferente de ATIVA reprova.
2. **Nenhum site é coletado sem estar em `data/interim/fornecedores_master.csv` com status APROVADO.**
3. **O site é a unidade de execução**, não o item nem a categoria. Um processo por domínio, sempre.
4. **Coleta e montagem são programas separados.** O coletor não conhece o template do FNDE; o montador não abre navegador.
5. **Marca e fabricante não entram no pipeline.** O critério é aderência à descrição, medida por score.
6. **Print é requisito**, tirado depois de preencher o CEP, com o frete visível na mesma imagem.

## Contrato de dados

Não altere `src/models.py` sem avisar — 9 pessoas dependem dele.

```python
@dataclass
class Fornecedor:
    nome: str
    cnpj: str | None          # só dígitos, 14 chars
    uf: str                   # PR | SC | RS | SP
    dominio: str              # CHAVE PRIMÁRIA, normalizada: "gpinox.com.br"
    url_base: str
    cnae_principal: str | None
    situacao_cadastral: str | None
    eh_atacadista: bool | None
    flag_atacarejo: bool
    entrega_sul: bool | None
    plataforma: str | None    # vtex|woocommerce|nuvemshop|shopify|tray|magento|desconhecida
    modo_frete: str | None    # GRATIS_NACIONAL|GRATIS_REGIAO|GRATIS_ACIMA_DE|TABELA_POR_CEP|SOB_CONSULTA
    status: str               # APROVADO | REPROVADO | PENDENTE
    motivo: str

@dataclass
class Achado:
    id_item: str              # ID FGV -- ALFANUMERICO: "1", "G008", "U029"
    dominio: str
    url_produto: str
    titulo_encontrado: str
    preco: float | None
    score_match: float        # 0..1
    coletado_em: datetime
```

Chave de junção em todo lugar: **domínio normalizado** (minúsculo, sem `www.`, sem barra final). Nunca nome de empresa.

## Fluxo de arquivos

```
planilhas originais  -> data/raw/
etapa1_validar       -> data/interim/fornecedores_master.csv
etapa2_varredura     -> data/interim/achados/{dominio}.csv     (--site ou --categoria)
etapa2_plano         -> data/interim/plano_coleta.csv          (site -> itens que ele tem)
etapa3_coletar       -> data/coletas/{dominio}.jsonl           (--site)
montar_entrega       -> data/output/{CATEGORIA}.xlsx + prints/
```

Um arquivo por site na entrada e na saída. Nenhum arquivo único escrito por vários processos.

## Convenções de código

- Python 3.11+. `httpx`/`requests` primeiro; Playwright só quando o conteúdo depende de JS, tem desafio de bot, ou o CEP não tem endpoint.
- Detectar plataforma antes de escrever scraper. VTEX, WooCommerce, Shopify e Nuvemshop têm busca em JSON — usar a API, não o HTML.
- Adapters implementam `LojaAdapter` (`buscar(termo) -> list[ProdutoBruto]`, `detectar(html_home, url) -> bool`). Quem escreve adapter não mexe em matching e vice-versa.
- Rate limit: máximo 3 requisições concorrentes por domínio, `sleep(random.uniform(1,3))` entre elas. Cache em disco de toda resposta HTTP bruta.
- Saídas intermediárias em CSV versionado. Excel só no final, gerado por script. Nunca editar planilha na mão — correções viram linha em `data/raw/correcoes.csv`.
- Playwright: `async_playwright` com contexto reaproveitado. Nunca subir browser novo por item.

## Matching

`rapidfuzz.fuzz.token_set_ratio` sobre texto normalizado (minúsculas, `unidecode`, sem stopwords). Bônus: +25 se bate a medida numérica (12 L, 1500 mm, 30 kg), +10 se bate o material (inox, alumínio, plástico).

Score ≥ 80 registra. 60–80 registra e marca para revisão humana. < 60 descarta.

`EAN` está 100% vazia na lista de origem — não existe match por código de barras.

**`id_item` é string, não int.** O ID FGV mistura numéricos ("1", "33") com
alfanuméricos ("G008", "U029", "E037", "318N") — 96 dos 144 não são números.
Converter para int perde dois terços da lista.

## Padrão de nome dos prints

```
data/output/prints/{CATEGORIA}/{id_item}__{dominio}__{uf}.png
```

O montador deriva o caminho das próprias colunas da linha. Miniatura JPEG ~600px q70 em `data/output/miniaturas/` para embutir; PNG original fica intocado como prova.

## Fora do escopo automatizado

12 itens não têm loja online com carrinho e são coletados à mão:
COMBUSTÍVEL/GLP (9) e SAÚDE OCUPACIONAL/exames (3).

A categoria VEICULOS **não** é veículo: são 2 pneus com especificação
completa (235/75R17.5 e 265/65R17), vendidos normalmente por atacadista de
autopeças. Ficam na coleta automática — 132 itens no total.

Isso abre uma pendência no CNAE: distribuidora de pneus costuma ter CNAE do
grupo **4530-7** (divisão 45, veículos automotores), e a regra atual reprova
qualquer coisa fora da divisão 46. Antes de rodar a Etapa 1 para os pneus,
decidir quais subclasses de 4530-7 contam como atacado e conferir os códigos
na tabela oficial do CNAE. Não chute os códigos.

## Herança do fork

Este repo é fork de `giuprofilo/mercados-scraper`, que era voltado a alimentos. Aproveitar de lá:

- `setup_sessao.py` — salva sessão/CEP por site com `launch_persistent_context`. Resolve o problema de CEP sem disparar anti-bot; serve direto para a classificação de frete.
- `debug_inspecionar.py` — salva HTML renderizado + screenshot de uma URL. Use antes de escrever qualquer seletor novo.
- A estrutura modular de `scrapers/` (base + um arquivo por site + registro em `__init__.py`).

Não aproveitar: SQLite como store principal, sync com Google Sheets, `data/produtos.py` com tarefas de alimentos.

Aviso do README original que continua valendo: mesma plataforma **não** garante mesmos seletores. Confirme com HTML real sempre.
