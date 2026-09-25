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
   **Exceção decidida pelo grupo em 23/09/2026:** as classes **47.53-9** (eletrodomésticos e equipamentos de áudio e vídeo) e **47.59-8** (artigos de uso doméstico n.e.) entram mesmo **sem** CNAE 46 secundário, também com `flag_atacarejo = SIM`. O motivo é a categoria EQUIPAMENTO — fogão industrial, freezer e balança são vendidos por loja registrada nessas classes, e reprová-las deixava a categoria sem fornecedor para os 5 preços por item. A lista está em `CLASSES_VAREJO_ACEITAS`, comparada por classe (5 dígitos), então pega 4759-8/01 e 4759-8/99 de uma vez.
   **Quem só entrou pela exceção só é varrido no canal `--varejista`** (ver "Dois canais" abaixo): uma loja de eletrodoméstico não é fonte de EPI nem de uniforme.
2. **A UF da sede não é critério; entregar no Sul é.** Fornecedor de qualquer estado entra, desde que entregue em PR, SC ou RS e passe no CNAE/CNPJ. Quem decide é `entrega_sul`, e reprovação exige **recusa** da loja nas três UFs — timeout ou site fora do ar deixa PENDENTE, não reprova.
3. **Nenhum site é coletado sem estar em `data/interim/fornecedores_master.csv` com status APROVADO.**
4. **O site é a unidade de execução**, não o item nem a categoria. Um processo por domínio, sempre.
5. **Coleta e montagem são programas separados.** O coletor não conhece o template do FNDE; o montador não abre navegador.
6. **Marca e fabricante não entram no pipeline.** O critério é aderência à descrição, medida por score.
7. **Print é requisito**, tirado depois de preencher o CEP, com o frete visível na mesma imagem.

## Contrato de dados

Não altere `src/models.py` sem avisar — 9 pessoas dependem dele.

O texto abaixo é um resumo. **A fonte real é `src/models.py`** — em caso de
divergência, vale o arquivo.

```python
@dataclass
class Fornecedor:
    nome: str
    dominio: str              # CHAVE PRIMÁRIA, normalizada: "gpinox.com.br"
    url_base: str
    uf: str                   # UF da SEDE, referência -- não é critério
    cnpj: str | None          # só dígitos, 14 chars
    cnae_principal: str | None
    cnaes_secundarios: list[str]
    situacao_cadastral: str | None
    eh_atacadista: bool | None
    flag_atacarejo: bool
    entrega_sul: dict[str, bool]   # UF ausente = não deu para saber, != não entrega
    plataforma: Plataforma    # vtex|woocommerce|nuvemshop|shopify|tray|magento|desconhecida
    modo_frete: ModoFrete | None
    status: Status            # APROVADO | REPROVADO | PENDENTE
    motivo: str
    origem: list[str]         # ["lista_sites.xlsx :: EPI"] -- arquivo/aba de onde veio
    url_busca: str            # "{base}/busca?q={termo}" -- conferido à mão, opcional
    seletor_busca: str        # "#campo-busca" -- conferido à mão, opcional

@dataclass
class ProdutoBruto:           # UMA VARIAÇÃO, não um produto
    titulo: str
    url: str
    preco: float | None       # o que se paga hoje
    disponivel: bool
    sku: str | None
    preco_lista: float | None # preço riscado; "VALOR DESCONTO" é a diferença
    vendedor: str | None      # seller, quando a plataforma tem vários
    variacao: str | None

@dataclass
class Achado:
    id_item: str              # ID FGV -- ALFANUMERICO: "1", "G008", "U029"
    dominio: str
    url_produto: str          # já com o SKU: o print prova ESTA variação
    titulo_encontrado: str
    score_match: float        # 0..1
    preco_indicativo: float | None
    coletado_em: datetime
    classificacao: str        # aceito | revisar -- só "aceito" vai para a coleta
    motivo_match: str
    sku: str | None
```

Chave de junção em todo lugar: **domínio normalizado** (minúsculo, sem `www.`, sem barra final). Nunca nome de empresa.

`url_base` é a **raiz do site** (`https://www.loja.com.br`), com o `www.`
que a loja usa e sem caminho nenhum. A prospecção cola o link que tem na
mão, e às vezes ele é fundo — `https://consigaz.com.br/p13/`. Tudo o que
o pipeline monta depois pendura caminho em cima disso: a busca vira
`.../p13/busca?q=panela` e a API vira `.../p13/wp-json/...`, as duas 404.
Seis fornecedores aprovados entraram assim na primeira varredura.

O `www` vem da planilha, mas **o validador corrige quando ele está
errado** (`resolver_www` em `etapa1_validar.py`): se o endereço não
entrega a página e a outra forma — com ou sem `www` — entrega, a
`url_base` troca. Nove aprovados estavam na planilha sem `www` e só
funcionavam com ele (0 de 3 tentativas como estavam, 3 de 3 com `www`).
"Entregar a página" é 2xx: host que responde 403 ou 404 à home existe,
mas não serve para raspar — cinco dos nove eram assim. Se as duas formas
entregam, ou nenhuma, fica a da planilha: a troca não é palpite. O
domínio (a chave) não muda, porque já é guardado sem `www`.

Campos acrescentados depois do congelamento são sempre **opcionais, com
padrão**. Nada que já existia mudou de nome ou de tipo — código antigo
continua construindo estes objetos do mesmo jeito.

## Fluxo de arquivos

```
planilhas originais  -> data/raw/
leads da prospecção  -> data/raw/leads/*.csv|xlsx             (formato livre, TODAS as abas)
etapa1_validar       -> data/interim/fornecedores_master.csv
                        data/interim/sem_site.csv              (CNPJ sem domínio)
                        data/output/validacao_{arquivo}_{aba}.xlsx  (conferência humana)
etapa2_varredura     -> data/interim/achados/{dominio}.csv     (--site ou --categoria)
etapa2_plano         -> data/interim/plano_coleta.csv          (site -> itens que ele tem)
                        data/interim/revisar.csv               (match duvidoso)
                        data/output/cobertura_{CATEGORIA}.xlsx (painel, para humanos)
etapa3_coletar       -> data/coletas/{dominio}.jsonl           (--site)
                        data/output/prints/{CATEGORIA}/...png
montar_entrega       -> data/output/{CATEGORIA}.xlsx           (A ENTREGA)
                        data/interim/reserva.csv               (quem não entrou, e por quê)
                        data/interim/pendencias.csv            (item/UF sem 5 fornecedores)
falhas de execução   -> data/raw/bloqueadas.csv, data/raw/falhas.csv, logs/execucao.log
```

Um arquivo por site na entrada e na saída. Nenhum arquivo único escrito por vários processos.

`cobertura_{CATEGORIA}.xlsx` leva prefixo porque `{CATEGORIA}.xlsx` é a
entrega final. São dois arquivos diferentes; com o mesmo nome, um
sobrescreveria o outro no meio do prazo.

`data/interim/achados/` é **saída** da varredura, nunca entrada. Loja
prospectada não entra por ali: entra por `data/raw/leads/`, vira linha no
`fornecedores_master.csv` e só é varrida depois de sair APROVADA.

## Leads: formato livre, uma coluna obrigatória

A prospecção larga `.csv` ou `.xlsx` em `data/raw/leads/`, quantos
arquivos quiser, com as colunas no nome que preferir. `ler_leads()`
descobre as colunas por sinônimo, comparando palavra a palavra sem
acento:

| Campo | Sinônimos aceitos | Obrigatório |
|---|---|---|
| site | site, url, dominio, link, endereco, pagina, website, webpage, portal, ecommerce | **sim** |
| nome | nome, empresa, fornecedor, razao, estabelecimento | não |
| uf | uf, estado | não |
| cnpj | cnpj | não |
| url de busca | uma palavra de (url, link, endereco) **e** uma de (busca, pesquisa, search) | não |
| seletor de busca | uma palavra de (seletor, css, campo, input) **e** uma de (busca, pesquisa, search) | não |

Basta a palavra aparecer no nome da coluna: `Site Oficial`, `Link
(clicável)`, `URL do site` e `Site / domínio` casam todos. Nome idêntico
a um sinônimo ganha de nome que apenas o contém, para que `Site` e `Site
do fabricante` não dependam da ordem das colunas.

Arquivo sem nenhuma coluna de site **levanta `PlanilhaSemColunaDeSite`**,
nomeando o arquivo, as colunas que ele tem e as que se esperava. Isso é
deliberado: antes, coluna com outro nome dava zero fornecedores sem erro
nenhum, e a pessoa ia procurar defeito no CNPJ ou na rede.

**Todas as abas de um `.xlsx` são lidas, não só a primeira.** Ler só a
primeira escondia 122 dos 134 fornecedores de `lista_sites.xlsx` (seis
abas: EPI, UNIFORME, COMBUSTIVEL, VEÍCULOS, Utensílios, Equipamentos)
sem erro nenhum — o mesmo prejuízo que `PlanilhaSemColunaDeSite` existe
para impedir. Cada aba escolhe suas colunas sozinha: em `lista_sites.xlsx`
a aba Utensílios usa `URL` e as outras usam `Site`. Aba **vazia** é
ignorada em silêncio (capa, legenda, rascunho); aba **com linhas e sem
coluna de site** levanta a exceção, nomeando arquivo e aba.

Cada fornecedor guarda em `origem` de que arquivo e aba veio, e um site
que aparece em duas abas guarda as duas. É o que permite devolver uma
planilha de conferência por aba em `data/output/validacao_*.xlsx`
(`src/export/validacao_por_aba.py`, que a etapa 1 chama no fim e também
roda sozinho sobre o master).

A coluna de UF costuma vir como `Cidade / UF` — o campo guarda só a
sigla (`São José / SC` -> `SC`). Texto sem sigla reconhecível (`Paraná`)
passa como está.

Mesmo domínio com CNPJ diferente (as cinco linhas de `consigaz.com.br`
são cinco revendas) **não** vira cinco fornecedores: a chave é o
domínio, só o primeiro CNPJ é consultado, e a etapa avisa no log.

Lead nunca sobrescreve o que as duas bases já resolveram — ele só
preenche buraco (nome ou UF em branco) e acrescenta domínio novo. Todo
lead entra como PENDENTE; quem decide é o pipeline de CNPJ.

## Qual executor cada loja recebe

A plataforma detectada indica o adapter; uma **sonda** confirma que a
loja responde por ele. Não é a mesma pergunta: a detecção lê marcador no
HTML da home, a busca precisa do endpoint ligado. Das 20 lojas
WooCommerce aprovadas, **15 respondem 404** em `/wp-json/wc/store/v1` —
sem a sonda, essas 15 varrem 132 itens contra um 404 e saem do relatório
como "não vende nada", indistinguíveis de uma loja varrida de verdade.

Quem não responde cai no `PlaywrightExecutor`, que é também o executor
de Tray, Magento e de toda loja sem plataforma reconhecida — 66 dos 89
sites aprovados hoje. Adapter novo define `SONDA` e ganha a confirmação
de graça (`Executor.api_responde()`).

### Busca conferida à mão ganha da heurística

Duas colunas opcionais, em **qualquer planilha de `data/raw/leads/`**:

| Coluna | Exemplo | O que faz |
|---|---|---|
| `URL de busca` | `https://loja.com.br/busca?q={termo}` | a varredura vai direto nela |
| `Seletor de busca` | `#campo-busca` | o campo que a varredura preenche |

Os nomes são reconhecidos por regra **composta** — o nome da coluna
precisa de uma palavra de endereço (`url`, `link`, `endereço`) **e** uma
de busca (`busca`, `pesquisa`, `search`). Sinônimo solto não serve:
"URL de busca" tem a palavra "url" e seria confundida com a coluna do
site, o que faria a varredura buscar na home de todo mundo.

Vale colar a URL de teste que funcionou (`/busca?q=panela`): o valor do
parâmetro vira `{termo}` sozinho. URL sem lugar reconhecível para o
termo é **recusada com aviso** — usá-la como está repetiria a mesma
busca nos 132 itens e registraria o mesmo resultado para todos.

Preenchido é ordem, não sugestão: o site vai para o navegador mesmo
tendo plataforma com API, sem sonda e sem descoberta. Quem preencheu
abriu a loja, buscou e viu o resultado; a heurística só chuta bem.

As planilhas de `data/output/validacao_*.xlsx` trazem as duas colunas de
volta, mostrando o que já está configurado. Preencher e salvar uma cópia
em `data/raw/leads/` fecha o círculo — elas têm coluna de site, de
empresa e de CNPJ, então são lidas como lead sem ninguém aprender
formato novo.

```bash
python -m src.runners.etapa1_validar --so-busca            # relê só a config, sem rede
python -m src.runners.etapa1_validar --so-busca --do-zero  # zera antes de reler
```

`--so-busca` existe por causa do ritmo: conferir 89 lojas é uma tarde de
idas e vindas, e se cada salvamento custasse uma revalidação de 122
CNPJs ninguém usaria as colunas. Ele **não apaga nada** sem `--do-zero`,
porque coluna ausente e célula vazia chegam ao código iguais, e quem
larga só a planilha de EPI na pasta apagaria as outras cinco abas sem
perceber.

### O executor genérico acha a barra de pesquisa sozinho

Três tentativas, e a primeira que **provar** servir vira o caminho fixo
da sessão: o campo na home (`SELETORES_BUSCA`), o botão de lupa que
monta o campo depois do clique, e a URL montada (`/busca?q=`, `/?s=`,
`/catalogsearch/result/?q=`…, na ordem que a plataforma sugere).

Provar é o que separa este executor de um que inventa resultado. Quatro
lojas reais mostraram quatro maneiras de enganá-lo, e cada uma virou uma
regra:

| O que a loja faz | Como ela é pega |
|---|---|
| `/busca?q=` responde **200 com a home** | a URL final não carrega mais o termo |
| responde 200 com **"Página não encontrada"** | o título, antes do corpo (o corpo tem o menu inteiro) |
| o campo busca no **blog** e acha "Olá, mundo!" | o caminho só é fixado se trouxer produto |
| devolve a **mesma vitrine** para qualquer termo | uma busca de controle com um termo que ninguém vende |

"0 Resultados da pesquisa" **é** busca que funciona — a loja só não tem
aquele item, e continua valendo para os outros 131. Loja em que nada
funciona levanta `BuscaNaoEncontrada`, nunca lista vazia: "não sei
buscar aqui" é seletor a escrever, "não vende" é item a procurar em
outro lugar.

A extração roda como JavaScript na página, porque só lá o DOM está
montado, e ignora `nav`, `header`, `footer` e link de categoria — numa
loja real "SOBRE NÓS" e "Talheres de Mesa" entraram como produto. A
conversão para `ProdutoBruto` é função pura e é o que os testes
exercitam; nenhum teste sobe navegador.

Loja que a heurística não pega **não é bug do genérico**: sobrescreva
`SEL_BUSCA` ou `URL_BUSCA` numa subclasse. É para isso que os dois
existem.

## Dois canais: padrão e `--varejista`

```bash
python -m src.orquestrador varredura --categoria EQUIPAMENTO              # padrão
python -m src.orquestrador varredura --varejista                          # varejo
python -m src.orquestrador coleta --varejista                             # idem, coleta
```

| | Itens | Sites |
|---|---|---|
| padrão | `data/interim/itens.csv` (132) | todo APROVADO, **menos** quem só entrou pela exceção de varejo |
| `--varejista` | `data/interim/itens_varejo.csv` (31) | **só** CNAE principal 47.53-9 ou 47.59-8 |

Hoje isso dá 89 sites no padrão e 8 no varejista. Cinco estão nos dois:
são 47.59-8 **com** CNAE 46 secundário, aprovados como atacarejo antes
da exceção existir (frigo, multibar, balancassaoroque, realequipamentos,
renovacaoporcelanas). Três estão só no varejista, porque só existem por
causa da exceção (lujao, agourmetutilidades, ipecozinhas).

Aprovado **sem CNAE** (decisão humana herdada da planilha, sem consulta)
fica no padrão: não há CNAE que o tire de lá, e excluir por falta de dado
seria perder fornecedor.

O canal é **derivado do CNAE**, não guardado no master — um campo a mais
sairia de sincronia na primeira edição à mão. A regra mora em
`classificar_cnae.py` (`eh_varejista`, `so_varejista`), junto com a de
aprovação, e as planilhas `validacao_*.xlsx` mostram o canal de cada
site na coluna **Canal**.

`itens_varejo.csv` sai da etapa 0 com a mesma limpeza da lista principal:

```bash
python -m src.runners.etapa0_limpar_itens \
    --entrada "data/raw/Lista de Equipamentos_Varejo_Sul xlsx.xlsx" \
    --saida data/interim/itens_varejo.csv
```

## As duas fases têm planos diferentes

A varredura descobre quem vende o quê; a coleta usa essa descoberta. Elas
não podem ler o mesmo arquivo, senão nenhuma roda numa base nova:

```
varredura -> plano de BUSCA:   todo site APROVADO x todo item da categoria.
                               Lê só o fornecedores_master.csv.
coleta    -> plano de COLETA:  plano_coleta.csv, que a etapa2_plano gera
                               a partir dos achados da varredura.
```

O `montar_lotes(fase, ...)` do orquestrador é quem escolhe entre os dois.
Nunca faça a varredura depender de `plano_coleta.csv`.

## Cache: a validade muda com a fase

O cache HTTP tem prazo, e o prazo é diferente em cada fase:

| fase | construtor | validade |
|---|---|---|
| varredura | `Cliente.para_varredura()` | 7 dias — reprocessar parser é barato |
| coleta | `Cliente.para_coleta()` | nenhuma — sempre busca de novo |

Preço, estoque e frete entram na entrega com a data da coleta ao lado e um
print tirado na hora. Corpo guardado de outro dia faz a planilha discordar
da própria prova. A resposta continua sendo **gravada** nas duas fases: ela
é evidência, não só economia de rede. `SUL_SCRAPERS_CACHE_TTL` sobrepõe.

## Convenções de código

- Python 3.11+. `httpx`/`requests` primeiro; Playwright só quando o conteúdo depende de JS, tem desafio de bot, ou o CEP não tem endpoint.
- Detectar plataforma antes de escrever scraper. VTEX, WooCommerce, Shopify e Nuvemshop têm busca em JSON — usar a API, não o HTML, e confirmar com a `SONDA` que a loja responde por ela.
- Adapters implementam `LojaAdapter` (`buscar(termo) -> list[ProdutoBruto]`, `detectar(html_home, url) -> bool`). Quem escreve adapter não mexe em matching e vice-versa.
- Rate limit: máximo 3 requisições concorrentes por domínio, `sleep(random.uniform(1,3))` entre elas. Cache em disco de toda resposta HTTP bruta.
- Saídas intermediárias em CSV versionado. Excel só no final, gerado por script. Nunca editar planilha na mão — correções viram linha em `data/raw/correcoes.csv`.
- Playwright: contexto reaproveitado. Nunca subir browser novo por item. O print
  comum vive em `src/export/captura.py` e serve a todos os adapters, inclusive
  os de API — um navegador por processo, e o orquestrador já dá um processo por
  domínio.
- Nada de `except Exception: return []`. `src/core/http.py` levanta `SiteBloqueado`,
  `FalhaDeRede` ou `RespostaInvalida`, e o adapter registra qual foi. Timeout,
  bloqueio e JSON quebrado com a mesma cara de "nenhum produto encontrado" fazem
  a pessoa reescrever o termo de busca quando o problema era outro.
- Bloqueio (`SiteBloqueado`) **sobe** até o runner, que grava em
  `data/raw/bloqueadas.csv` e para de insistir naquele domínio.

## Testes

```bash
pytest -m "not lento"   # a suíte inteira em segundos
pytest                  # inclui o fluxo completo com navegador (~2 min)
pytest -m lento         # só o fluxo completo
```

`tests/loja_falsa.py` é uma loja VTEX servida em localhost, hostil de
propósito nos pontos em que o pipeline já errou: o primeiro SKU é a unidade
avulsa quando o item pede o kit, o primeiro seller está sem estoque e mais
caro, o preço tem riscado, e o frete muda nos três CEPs. Nenhum teste toca a
rede de verdade.

## Matching

`rapidfuzz.fuzz.token_set_ratio` sobre texto normalizado (minúsculas, `unidecode`, sem stopwords). Bônus: +25 se bate a medida numérica (12 L, 1500 mm, 30 kg), +25 se bate a embalagem (100 unidades, 50 pares, kit de 5), +10 se bate o material (inox, alumínio, plástico).

Score ≥ 80 registra. 60–80 registra e marca para revisão humana. < 60 descarta.

**Divergir custa, não só deixar de ganhar.** Bônus sozinho não basta: uma
panela de 50 L perdia os 25 pontos e ainda entrava no lugar de uma de 20 L,
porque o fuzzy textual cobria a diferença. A escala de efeitos hoje:

| situação | efeito |
|---|---|
| embalagem exigida e divergente (pede 100, produto traz 50) | **descartado** |
| embalagem exigida e o título não diz quantas vêm | no máximo `revisar` |
| item avulso e produto em pacote (preço de pacote na linha de 1 un) | no máximo `revisar` |
| dimensão divergente | no máximo `revisar` |
| dimensão ausente no título | só perde o bônus |

Embalagem divergente descarta porque não há leitura em que um pacote de 50
atenda quem pediu 100. Dimensão divergente não descarta porque a lista usa
"mínimo", "máximo" e "aproximadamente" o tempo todo — o item 318N pede
comprimento mínimo de 1,00 m, e um avental de 1,20 m atende.

`matching.avaliar()` devolve score **e** decisão; `pontuar()` devolve só o
número. Use `avaliar()`: reprovar é decisão, não é um número.

Reconhece `unidade(s)`, `un`, `und`, `pç`, `peça(s)`, `par(es)` e recipiente
com quantidade (`pacote com 100`, `kit 5 tábuas`, `caixa contendo 50`).
Cadeia de dimensão herda a unidade do fim: `50 x 30 x 0,8 cm` são três
medidas, não só a espessura.

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
