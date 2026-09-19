# Guia da Equipe — Raspagem FNDE Região Sul

Criado em 17/09/2026. Conferido contra o código e corrigido em 19/09/2026.

## 1. Contexto, escopo e critérios de aceitação

A entrega de 25/09/2026 é uma planilha de preços dos 144 itens da Lista de Equipamentos FNDE, com 5 preços por item, coletados em lojas atacadistas que vendem para PR, SC e RS. O template final já está definido em FNDE_output.xlsx (15 colunas, aba única) — tudo o que fizermos até lá existe para preencher essas colunas.

### O volume e o que ele impõe

Confirmado com o solicitante: 5 preços por item e por estado, de 5 fornecedores distintos. São 144 × 5 × 3 = 2.160 linhas na planilha final.

Mas 2.160 linhas não são 2.160 raspagens. Um fornecedor que entrega nos três estados tem o mesmo preço de produto nos três — o que muda entre as linhas é o frete. Então o trabalho real se divide assim:

| O quê | Quantidade | Por quê |
|---|---|---|
| Raspagem de preço | 660 | 132 itens automáticos × 5 fornecedores, uma vez cada |
| Cotação de frete | até 1.980 | Uma por linha automática, salvo nos sites de frete grátis |
| Prints | até 1.980 | Um por linha, porque cada um prova um frete |
| Cotação manual | 180 | 12 itens × 5 fornecedores × 3 UFs, por telefone e e-mail |

A coluna do meio é onde o projeto pesa, e é o que justifica classificar o frete por site antes de sair cotando.

A consequência para a lista de fornecedores é direta: para um item ter 5 preços, ele precisa existir em 5 fornecedores aprovados diferentes. Um mesmo site cobre muitos itens de uma vez, e isso ajuda no volume total, mas não ajuda na profundidade: cada item precisa dos seus 5. Uma bacia plástica de 20 L que só aparece em duas lojas continua com dois preços por mais lojas que a gente aprove no geral.

E fornecedor que entrega nos três estados vale por três — mais um motivo para a cobertura de entrega ser critério de aprovação, e não uma informação anotada depois.

Por isso a lista de fornecedores aprovados deixa de ser um filtro de entrada e passa a ser a métrica principal do projeto.

### O que a equipe raspa e o que vai para o manual

A divisão não é por dificuldade, é por existência: duas categorias simplesmente não têm loja online com carrinho e preço público. Nenhum scraper resolve isso.

| Categoria | Itens | Como é coletado | Por quê |
|---|---|---|---|
| UTENSILIOS | 80 | Automático | Atacadistas de utensílios têm loja com catálogo e preço |
| EQUIPAMENTO | 34 | Automático | Lojas de cozinha industrial vendem online com preço à vista |
| EPI | 10 | Automático | Atacadistas de segurança do trabalho têm e-commerce próprio |
| UNIFORMES | 6 | Automático | Distribuidoras de vestuário profissional vendem por unidade |
| VEICULOS | 2 | Automático | Não é veículo: são 2 pneus com especificação fechada, vendidos por atacadista de autopeças |
| COMBUSTÍVEL (GLP) | 9 | Manual | Botijão não é vendido em e-commerce; preço é regional e regulado, e a revenda cota por telefone |
| SAÚDE OCUPACIONAL | 3 | Manual | ASO, audiometria e exames são serviço, não produto: clínica cota por convênio e volume |

São 132 itens automatizados e 12 manuais. Os 12 viram uma frente paralela que começa no mesmo dia que o resto — não no fim.

Os 12 manuais também precisam de 5 cotações por UF, o que dá 180 das 2.160 linhas. O caminho para eles é ligar ou mandar e-mail para 5 revendas por estado, pedir cotação por escrito, e o print vira o print do e-mail ou da proposta recebida. A coluna FONTE recebe o nome e o contato em vez de uma URL, e OBS FRETE explica que a cotação foi direta.

Atenção ao caso VEICULOS, que mudou: os dois itens são pneus (235/75R17.5 e 265/65R17), com especificação completa, e distribuidora de autopeças vende isso online normalmente. Ficam na coleta automática. A pendência que isso abre é de CNAE, não de scraper — ver a Etapa 1.

### Critérios de aceitação de um fornecedor

A ordem de prioridade é: loja da região Sul → loja de São Paulo que entrega no Sul. Em qualquer dos dois casos, valem as cinco regras abaixo, e a regra 1 é eliminatória.

- CNAE principal de atacado. O CNPJ precisa ter CNAE principal na divisão 46 (comércio por atacado). CNAE principal na divisão 47 (varejo) reprova.
- Atacarejo entra com flag. CNAE principal de varejo mas com CNAE secundário 46xx → aceita, com flag_atacarejo = SIM.
- CNPJ ativo. Situação cadastral diferente de ATIVA (baixada, suspensa, inapta) reprova, mesmo com CNAE certo.
- Entrega em PR, SC e RS. Confirmada por simulação de frete ou por política de entrega publicada no site.
- Site próprio com preço visível. Marketplace puro, catálogo em PDF ou "consulte um vendedor" não serve para raspagem de preço.

### Onde estamos hoje

base_fornecedores_regiao_sul.xlsx traz 102 empresas com site, mas sem coluna de CNPJ — nenhuma delas passou pela regra 1 ainda. fornecedores_atacadistas_utensilios_sul_consolidado_1.xlsx traz 114 empresas já com CNPJ e CNAE, das quais 13 aprovadas, 63 pendentes e 37 excluídas.

Unificando pelo domínio, que é a chave primária do projeto, sobram 131 candidatos com site — e 13 aprovados. O número costuma ser citado como "cerca de 200", e não é: das 114 linhas da planilha atacadista, 72 têm CNPJ e nenhum site. Sem domínio elas não entram no master, porque não há como raspar nem como juntar com o resto. A Etapa 1 grava essas 72 em data/interim/sem_site.csv, e achar o domínio delas é trabalho barato e de alto retorno para a frente de prospecção: o CNPJ e o CNAE já estão resolvidos.

Treze fornecedores só fechariam 5 preços por item se todos os treze vendessem quase tudo — o que não acontece nem dentro de uma categoria. A Etapa 1 não é triagem: é a etapa que decide se a entrega é possível, e ela não termina num dia, roda em paralelo com todo o resto.

## 2. Etapa 0 — Setup

Com 8 dias e 9 pessoas, a coisa mais cara que pode acontecer é duas pessoas escreverem o mesmo parser com formatos de saída diferentes. A Etapa 0 existe só para impedir isso. Ela termina quando o contrato de dados está congelado.

### O repositório

Fork de giuprofilo/mercados-scraper para a conta da equipe, e a partir daí vida própria — a estrutura de referência é voltada a alimentos e o nosso escopo é outro. O que aproveitamos dela: o padrão de organização de pastas, o jeito de guardar os prints e a forma de exportar para planilha.

Branch main protegida, trabalho em branches etapa1/validacao-cnpj, etapa2/adapter-vtex etc., PR com pelo menos uma revisão. Com 9 pessoas mexendo na mesma semana, commit direto na main custa mais tempo do que economiza.

O repositório não pertence a nenhuma ferramenta. Parte da equipe usa Claude, parte usa ChatGPT, parte usa Gemini, e alguém pode não usar assistente nenhum. Todos precisam trabalhar igual.

Na prática isso significa um arquivo de contexto que quase todas as ferramentas leem — AGENTS.md, formato aberto mantido pela Agentic AI Foundation — mais dois ponteiros de uma linha para as duas que insistem em outro nome:

| Arquivo | Quem lê | Regra |
|---|---|---|
| AGENTS.md | Codex, Jules, Gemini CLI, Copilot, Cursor e mais | O único que se edita |
| CLAUDE.md | Claude Code | Uma linha: @AGENTS.md |
| GEMINI.md | Gemini CLI | Aponta para o AGENTS.md |

Editar CLAUDE.md ou GEMINI.md cria uma divergência que ninguém percebe até os dois discordarem. Todo conteúdo novo vai para AGENTS.md.

Sobre trabalhar no repositório: Codex (dentro do ChatGPT) e Jules (do Google) conectam ao GitHub, trabalham em sandbox e devolvem pull request; Gemini CLI e Claude Code trabalham no clone local ou conectados. Ninguém fica de fora, e os quatro produzem PR para a mesma branch protegida.

A estrutura completa, com diagramas, está no documento Estrutura do Repositório, e a versão exportada dele vive em docs/ESTRUTURA.md.

### O contrato de dados (o entregável desta etapa)

Cinco dataclasses, num único arquivo, que ninguém altera sem avisar no grupo. A fonte real é src/models.py — em caso de divergência, vale o arquivo:

```
@dataclass
class Item:
    id_item: str              # ID FGV -- ALFANUMERICO: "1", "G008", "U029", "318N"
    categoria: str            # UTENSILIOS | EQUIPAMENTO | EPI | UNIFORMES | VEICULOS
    grupo_insumo: str         # BACIA, PANELA, FACA
    descricao: str
    termos_busca: list[str]
    item_curto: str           # rotulo curto para a coluna "Item" da entrega

@dataclass
class Fornecedor:
    nome: str
    dominio: str              # CHAVE PRIMARIA, normalizada: "gpinox.com.br"
    url_base: str
    uf: str                   # PR | SC | RS | SP
    cnpj: str | None          # so digitos, 14 chars
    cnae_principal: str | None
    cnaes_secundarios: list[str]
    situacao_cadastral: str | None
    eh_atacadista: bool | None
    flag_atacarejo: bool
    entrega_sul: dict[str, bool]   # {"PR": True, "SC": False, ...}
    plataforma: Plataforma    # vtex | woocommerce | nuvemshop | shopify | tray | magento | desconhecida
    modo_frete: ModoFrete | None
    status: Status            # APROVADO | REPROVADO | PENDENTE
    motivo: str

@dataclass
class ProdutoBruto:           # UMA VARIACAO, nao um produto
    titulo: str
    url: str
    preco: float | None       # o que se paga hoje
    disponivel: bool
    sku: str | None
    preco_lista: float | None # preco riscado; o desconto e a diferenca
    vendedor: str | None
    variacao: str | None

@dataclass
class Achado:
    id_item: str
    dominio: str
    url_produto: str          # ja com o SKU: o print prova ESTA variacao
    titulo_encontrado: str
    score_match: float        # 0..1
    preco_indicativo: float | None
    coletado_em: datetime
    classificacao: str        # aceito | revisar -- so "aceito" vai para a coleta
    motivo_match: str
    sku: str | None

@dataclass
class Coleta:                 # uma linha da entrega: item x fornecedor x UF
    id_item: str
    dominio: str
    uf: str
    url_produto: str
    titulo_encontrado: str
    preco_produto: float | None
    valor_desconto: float | None
    obs_desconto: str
    preco_final: float | None
    valor_frete: float | None
    obs_frete: str
    caminho_print: str
    score_match: float
    coletado_em: datetime
```

A chave que liga tudo é o domínio normalizado (minúsculo, sem www., sem barra final). Nome de empresa não serve como chave: "GP Inox" e "GP INOX LTDA" viram duas empresas e ninguém percebe.

Três pontos do contrato que já causaram erro e valem destaque:

- id_item é str, nunca int. O ID FGV mistura "1" e "33" com "G008", "U029", "E037" e "318N" — 96 dos 144 não são números. Converter para int perde dois terços da lista.
- ProdutoBruto é uma VARIAÇÃO, não um produto. A tábua de 30 cm e a de 50 cm são dois ProdutoBruto, porque têm preço diferente e só uma delas atende o item. Adapter que devolve só a primeira variação entrega o preço de um produto que não é o pedido.
- preco e preco_lista são coisas diferentes. preco é o que se paga; preco_lista é o riscado. A entrega tem coluna para os dois mais a diferença, e ler só um dos campos apaga o desconto.
Campos acrescentados depois do congelamento são sempre opcionais, com padrão: nada que já existia muda de nome ou de tipo.

### Combinados de trabalho

- Toda saída intermediária é CSV em data/interim/, versionado. Excel só no final, gerado por script.
- Nada de editar planilha na mão no meio do caminho: se precisou de correção manual, ela vira uma linha em data/raw/correcoes.csv que o script aplica.
- Daily de 15 minutos, mesmo horário, todos os dias até 25/09. Cada um diz: o que travou, o que precisa de alguém.
- Um canal só para "site X bloqueou" — essa informação precisa circular rápido. O pipeline também registra sozinho em data/raw/bloqueadas.csv.

## 3. Etapa 1 — Prospecção e validação de fornecedores

Esta etapa não é trabalho de pesquisa manual: 90% dela é código. A pesquisa manual entra só para achar candidatos novos e para resolver os casos em que o robô não conseguiu decidir.

A entrada são as duas planilhas (102 + 114 empresas) unificadas pelo domínio. A saída é um único data/interim/fornecedores_master.csv com todos os campos da dataclass Fornecedor preenchidos.

### O pipeline, em cinco passos

```
Unificar as 2 planilhas   ->  Achar CNPJ no site   ->  Consultar CNPJ
  chave = dominio               regex no rodape          API publica
                                                              |
fornecedores_master.csv  <-  Testar entrega       <-  Classificar CNAE
                               CEP de PR, SC, RS        46xx / 47xx / atacarejo
```

1. Unificar. Junta as duas bases pelo domínio normalizado, mais tudo que estiver em data/raw/leads/. Preserva o que a planilha do colega já resolveu (CNPJ, CNAE) e marca como PENDENTE o que vier da base de 102, que não tem CNPJ. Reprovação decidida por gente não se revisita em lote: "site possui fluxo de compra online" é um motivo que nenhuma consulta de CNPJ redescobre.

2. Achar o CNPJ. Quase toda loja brasileira põe o CNPJ no rodapé, por obrigação. Baixa a home, /institucional, /quem-somos, /politica-de-privacidade e /termos, e roda a regex \d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}. Valida o dígito verificador antes de aceitar — isso sozinho elimina telefone e CEP que casam por acidente. Taxa de acerto esperada: 70 a 85% dos sites.

3. Consultar o CNPJ. API pública, sem chave e sem cadastro:

| Serviço | Endpoint | Limite |
|---|---|---|
| Minha Receita | https://minhareceita.org/{cnpj} | Generoso, base da Receita Federal |
| BrasilAPI | https://brasilapi.com.br/api/cnpj/v1/{cnpj} | ~3 req/min por IP |

Use Minha Receita como primária e BrasilAPI como fallback. A resposta bruta fica em data/raw/cnpj/{cnpj}.json e nunca é reconsultada: 200 consultas é rápido, 200 consultas repetidas a cada debug é uma tarde perdida. Rodar a etapa de novo aproveita o que já foi consultado; --do-zero força a reconsulta.

4. Classificar. Regra em código, não no olho:

| CNAE principal | Decisão |
|---|---|
| Começa com 46 | APROVADO como atacadista |
| Começa com 47 e tem algum 46 nos secundários | APROVADO com flag_atacarejo = SIM |
| Começa com 47 sem nenhum 46 | REPROVADO |
| Começa com 4530-7 (autopeças) | PENDENTE — ver a nota sobre os pneus abaixo |
| Qualquer outra divisão | REPROVADO |

E, antes de tudo isso, situacao_cadastral != "ATIVA" reprova direto. A base atual já tem casos de CNPJ inapto e suspenso que passaram na triagem manual.

Para referência, o CNAE que domina os aprovados de hoje é 4649-4/99 (comércio atacadista de outros equipamentos e artigos de uso pessoal e doméstico), com 65 das 114 empresas. Ele é o alvo natural para EPI e utensílios.

A pendência dos pneus. Os 2 itens de VEICULOS precisam de distribuidora de autopeças, que costuma ter CNAE do grupo 4530-7 — divisão 45, fora da regra dos 46. Parte das subclasses de 4530-7 é atacado e parte é varejo. A lista SUBCLASSES_AUTOPECAS_ATACADO em validacao/classificar_cnae.py está vazia de propósito: alguém precisa conferir na tabela oficial do CNAE quais contam como atacado e preencher. Não chute os códigos — enquanto estiver vazia, esses fornecedores saem como PENDENTE e não entram na coleta.

5. Testar entrega no Sul. Três CEPs representativos, um por estado, batidos contra a calculadora de frete da loja: Curitiba/PR 80010-010, Florianópolis/SC 88010-400, Porto Alegre/RS 90010-150. Em plataforma conhecida isso é uma chamada de API (ver Etapa 2). Este é o ponto mais lento da Etapa 1 — por isso vem depois do filtro de CNAE, rodando só sobre quem já passou, e só quando se pede: python -m src.runners.etapa1_validar --com-frete.

### O problema dos status livres

A planilha do colega tem 37 valores diferentes na coluna "Status atual" — PENDENTE SITE, PENDENTE - SEM SITE, REVALIDAR VÍNCULO SITE-CNPJ e assim por diante. Isso é impossível de filtrar em código. O unificador mapeia tudo para três valores (APROVADO, REPROVADO, PENDENTE) pelo prefixo e joga o texto original para a coluna motivo.

### Prospecção de candidatos novos

Rodando em paralelo ao pipeline, duas pessoas buscando ampliar a lista. Termos que funcionam: distribuidora utensílios cozinha industrial atacado {cidade}, atacadista EPI {estado}, distribuidor uniforme profissional atacado sul. Vale também pegar a lista de expositores de feiras do setor e associações comerciais estaduais.

O output delas é só isso: nome + domínio numa linha de CSV. O CNPJ, o CNAE e a entrega quem resolve é o pipeline.

O atalho de maior retorno hoje é data/interim/sem_site.csv: 72 empresas com CNPJ e CNAE já resolvidos, esperando só alguém achar o domínio. Cada uma que ganhar site entra no master sem passar por nenhuma consulta.

### Onde largar o que achou, e a única exigência de formato

Salve em data/raw/leads/. Pode ser .csv ou .xlsx, quantos arquivos quiser, com o nome que quiser — a Etapa 1 lê a pasta inteira e junta tudo pelo domínio. Não existe um modelo de planilha para preencher, e isso é de propósito: a prospecção não deveria ter que aprender um layout.

A única exigência é UMA coluna com o site. O nome dela pode variar, porque o código procura por sinônimo, comparando palavra a palavra e ignorando acento e maiúscula:

| Campo | Nomes de coluna que o código reconhece | Obrigatório? |
|---|---|---|
| site | site, url, dominio, link, endereco, pagina, website, webpage, portal, ecommerce | SIM |
| nome | nome, empresa, fornecedor, razao, estabelecimento | não |
| uf | uf, estado | não |
| cnpj | cnpj | não |

Basta a palavra aparecer no nome da coluna. Então "Site", "Site Oficial", "URL", "URL do site", "Link (clicável)", "Site / domínio", "Página" e "Endereço do site" funcionam todos — assim como "Empresa", "Nome da Empresa" e "Razão Social" na coluna de nome. Se a planilha tiver duas colunas parecidas, como "Site" e "Site do fabricante", ganha a de nome exato.

Se nenhuma coluna for reconhecida como site, a Etapa 1 PARA e diz qual arquivo, quais colunas ele tem e quais ela esperava. É erro, não aviso, e de propósito: antes, uma planilha com a coluna chamada "URL" em vez de "Site Oficial" produzia zero fornecedores sem erro nenhum — e a pessoa ia procurar defeito no CNPJ ou na rede. Quando houver mais de um arquivo com problema, a mensagem lista todos de uma vez, para não descobrir um por rodada.

```
$ python -m src.runners.etapa1_validar
[etapa1] nao consegui usar 1 arquivo(s) de data\raw\leads:
  - leads_outubro.csv: nenhuma coluna de site. Colunas encontradas:
    ['Empresa', 'Telefone']. Esperava alguma com: dominio, ecommerce,
    endereco, link, pagina, portal, site, url, webpage, website
```

Linha sem site é pulada sem derrubar o arquivo, e o log diz quantas foram. Arquivo temporário do Excel (aqueles que começam com ~$) é ignorado. E o lead nunca sobrescreve o que as duas bases já resolveram: ele só preenche buraco (nome ou UF em branco) e acrescenta domínio novo. Mandar a mesma loja duas vezes não faz mal nenhum.

### Quando parar de prospectar

Não é uma data, é um número. A regra de parada é a cobertura por item: a fração dos itens de uma categoria que já tem 5 ou mais fornecedores com o produto.

A primeira varredura devolve essa métrica de graça: python -m src.runners.etapa2_plano imprime a cobertura por categoria e gera data/output/cobertura_{CATEGORIA}.xlsx. A partir daí a prospecção deixa de ser genérica e vira dirigida: em vez de "achar mais atacadistas", passa a ser "achar quem vende cuscuzeiro industrial", porque a planilha diz exatamente quais itens estão com 1 ou 2 fontes.

Metas de partida, para calibrar o esforço por categoria:

| Categoria | Itens | Aprovados que provavelmente bastam |
|---|---|---|
| UTENSILIOS | 80 | 20 a 25 |
| EQUIPAMENTO | 34 | 15 a 20 (mercado mais concentrado) |
| EPI | 10 | 8 a 10 |
| UNIFORMES | 6 | 6 a 8 |
| VEICULOS | 2 | 5 a 6 distribuidoras de autopeças, depois de resolvido o CNAE |

Esses números partem da premissa de que uma loja qualquer carrega entre 30% e 50% dos itens da sua categoria. A primeira varredura confirma ou desmente isso em poucas horas, e aí os números se ajustam com dado real em vez de chute.

A lista fecha quando a cobertura parar de subir de forma útil, não quando o calendário mandar.

## 4. Etapa 2 — Scraper de varredura

A varredura responde uma pergunta só: a loja X tem algo parecido com o item Y? Sem preço, sem frete, sem detalhe. Guardar o link e seguir. Preço é Etapa 3.

Separar as duas coisas é o que permite rodar a varredura inteira em poucas horas e descobrir cedo quais itens ninguém vende — informação que muda o planejamento do resto da semana.

### Antes: limpar a Lista de Equipamentos

A planilha tem 13 colunas e a maioria não serve. EAN está 100% vazia — não dá para casar por código de barras, o match tem que ser textual. Embalagem só tem "-" e Prioridade está inteira em branco. Código do Insumo e ID FGV têm valores idênticos. Descrição_Resumida está corrompida em 4 linhas e foi substituída por item_curto, derivado da Descrição.

O que fica, em data/interim/itens.csv (132 linhas) e data/interim/itens_manuais.csv (12 linhas):

| Coluna | Uso |
|---|---|
| id_item | ID FGV, chave de tudo. Texto, nunca int |
| categoria | Vira o nome do arquivo e o parâmetro de execução |
| grupo_insumo | BACIA, PANELA, FACA — é o termo de busca base |
| item_curto | Rótulo curto para a coluna Item da entrega |
| descricao | Texto completo, usado para pontuar o match |
| termos_busca | 2 a 4 consultas por item, separadas por | |

Marca e fabricante saem do pipeline inteiro, não só desta fase. O template FNDE_output.xlsx não tem coluna para eles, e o critério não é qual marca o produto é — é se ele atende a descrição solicitada. A marca do que foi encontrado fica registrada de qualquer forma dentro da coluna PRODUTO PESQUISADO, que guarda o título do produto na loja.

Isso desloca o peso da conferência para o matching: sem marca para ancorar, quem garante a aderência é o score e a revisão humana dos casos duvidosos. Vale a pena ser rigoroso ali.

Sobre termos_busca: a descrição do FNDE é um texto de licitação de 300 caracteres — jogar isso inteiro num campo de busca de loja não retorna nada. "Batedeira planetária industrial, capacidade de 12 litros..." vira ["batedeira planetaria 12 l", "batedeira planetaria industrial", "batedeira industrial"], do mais específico para o mais genérico. Quando o item é um pacote, a quantidade entra no termo ("mascara 100 unidades"): é assim que a loja indexa o produto, e é o que separa o pacote da peça avulsa já na busca.

### O atalho: detectar a plataforma

Não vamos escrever 50 scrapers. A esmagadora maioria das lojas brasileiras roda numa de meia dúzia de plataformas, e todas elas expõem busca por URL ou por JSON. Detecta-se a plataforma lendo o HTML da home uma vez e procurando marcadores:

| Plataforma | Marcador no HTML | Busca | Adapter |
|---|---|---|---|
| VTEX | vtexassets, vteximg, vtex.com.br | /api/catalog_system/pub/products/search?ft= → JSON | Completo |
| WooCommerce | wp-content, woocommerce | /wp-json/wc/store/v1/products?search= → JSON | Busca pronta |
| Shopify | cdn.shopify.com | /search/suggest.json?q= + /products/{handle}.js → JSON | Busca pronta |
| Nuvemshop | nuvemshop, tiendanube | /search?q= → HTML com JSON-LD | Busca pronta |
| Tray | tray.com.br, traycdn | /loja/busca.php?palavra_busca= → HTML | NÃO EXISTE |
| Magento | catalogsearch, Mage.Cookies | /catalogsearch/result/?q= → HTML | NÃO EXISTE |

Atenção à última coluna, que é uma lacuna real e não estava neste guia: Tray e Magento são detectados, mas não têm executor. Quem cair nessas duas vai para o PlaywrightExecutor, cujo abrir() e buscar() ainda levantam NotImplementedError. Na prática, loja Tray ou Magento hoje não é raspável. Se aparecerem fornecedores aprovados nessas plataformas, escrever esses dois adapters vira prioridade.

Nas quatro primeiras a resposta é estruturada: nome, preço, URL e disponibilidade vêm prontos, sem navegador, em milissegundos. Isso cobre a maior parte das lojas e resolve de quebra o teste de entrega da Etapa 1.

Os três adapters não-VTEX foram escritos contra a documentação das plataformas, não contra uma loja nossa. Antes de confiar nos nomes de campo, salve uma resposta real em tests/fixtures/ — é a regra do projeto, e o VTEX é o único que já passou por ela.

### O padrão adapter

Todo executor herda da mesma classe abstrata. É isso que permite 9 pessoas trabalharem em paralelo sem colidir:

```
class Executor(ABC):
    plataforma: str
    def buscar(self, termo: str) -> list[ProdutoBruto]: ...   # obrigatorio
    def detalhar(self, url_produto: str) -> ProdutoBruto: ...
    def cotar_frete(self, url, cep, produto=None) -> tuple[float | None, str]: ...
    def capturar_print(self, url, cep, destino) -> str: ...   # ja vem pronto
    def abrir(self) -> None: ...
    def fechar(self) -> None: ...
```

Quem escreve o adapter de VTEX não precisa saber nada de matching. Quem escreve o matching não precisa saber nada de VTEX. Ambos testam contra o mesmo ProdutoBruto.

Duas coisas que NÃO são responsabilidade do adapter, e que o guia antigo colocava lá: detectar a plataforma (isso é core/plataforma.py, e quem escolhe a classe é adapters/registro.py) e tirar o print (isso é export/captura.py, e Executor.capturar_print() já usa por padrão, inclusive nos adapters de API — o solicitante confere imagem, não JSON). Adapter cujo campo de CEP a heurística não acha sobrescreve SEL_CAMPO_CEP e SEL_RESULTADO_FRETE, e nada mais.

### Matching: quando aceitar que achou

Normaliza os dois lados (minúsculas, sem acento via unidecode, sem stopwords) e pontua com rapidfuzz.fuzz.token_set_ratio. Depois aplica os bônus:

- Bate a medida numérica da descrição (12 L, 1500 mm, 30 kg)? +25 pontos. É o sinal mais forte que existe nesse domínio — panela de 20 L e panela de 50 L são produtos diferentes com o mesmo nome.
- Bate a embalagem (100 unidades, 50 pares, kit de 5)? +25 pontos.
- Bate o material quando a descrição especifica (inox, alumínio, plástico)? +10 pontos.
Score ≥ 80 → registra. Entre 60 e 80 → registra e alguém revisa. Abaixo de 60 → descarta.

Bônus sozinho não basta, e essa é a correção mais importante desta revisão. Antes, divergir só custava o bônus: uma panela de 50 L perdia 25 pontos e ainda entrava no lugar de uma de 20 L, porque o fuzzy textual cobria a diferença. Pior, a expressão de medidas não reconhecia "unidades" nem "par", então o item 294 (100 máscaras) aceitava uma máscara avulsa — com o preço de uma máscara. Hoje a escala de efeitos é esta:

| Situação | Efeito |
|---|---|
| Embalagem exigida e divergente (pede 100, produto traz 50) | DESCARTADO |
| Embalagem exigida e o título não diz quantas vêm | no máximo "revisar" |
| Item avulso e produto em pacote (preço de pacote numa linha de 1 un) | no máximo "revisar" |
| Dimensão divergente | no máximo "revisar" |
| Dimensão ausente no título | só perde o bônus |

Embalagem divergente descarta porque não existe leitura em que um pacote de 50 atenda quem pediu 100. Dimensão divergente não descarta porque a lista usa "mínimo", "máximo" e "aproximadamente" o tempo todo — o item 318N pede comprimento mínimo de 1,00 m, e um avental de 1,20 m atende.

Na prática: use matching.avaliar(), que devolve score E decisão. matching.pontuar() devolve só o número, e reprovar é decisão, não é um número. A classificação fica gravada no Achado, e só o que for "aceito" entra no plano de coleta — o que ficou em "revisar" vai para data/interim/revisar.csv e espera uma pessoa. Mandar "revisar" direto para a coleta é o mesmo que não ter revisão.

Guardar o score na planilha importa: no fim da semana, quando faltar tempo, ele diz onde olhar primeiro.

### A saída da Etapa 2

Dois arquivos, um para gente ler e um para a máquina consumir.

Para gente: data/output/cobertura_{CATEGORIA}.xlsx, uma planilha por categoria, uma linha por item:

| Código FGV | Item | Fontes aceitas | Falta para 5 | Em revisão | Fornecedores |
|---|---|---|---|---|---|
| 23 | Bacia plástica 20 L | 2 | 3 | 1 | gpinox.com.br, ingaimport.com.br |
| 24 | Bacia inox 30 cm | 1 | 4 | 0 | casacristalina.com.br |

A coluna "Falta para 5" é o painel de controle do projeto. Ela diz, a qualquer momento, quanto falta para a entrega existir, e diz para a frente de prospecção exatamente o que procurar. O prefixo cobertura_ existe porque data/output/{CATEGORIA}.xlsx é a entrega final: são coisas diferentes, e com o mesmo nome uma sobrescreveria a outra no meio do prazo.

### A segunda saída: o plano de coleta

O que a Etapa 3 consome é a mesma informação virada do avesso: uma linha por site, com a lista dos itens que ele tem.

| dominio | uf | plataforma | modo_frete | qtd_itens | ids_itens |
|---|---|---|---|---|---|
| gpinox.com.br | PR | vtex | TABELA_POR_CEP | 34 | 23|31|47|... |
| casacristalina.com.br | SC | nuvemshop | GRATIS_REGIAO | 61 | 24|25|31|... |

É a transposta da planilha de cobertura, e é ela que torna a coleta viável. Sem ela, a Etapa 3 teria que perguntar a cada site sobre cada item — 132 buscas por loja, a maioria retornando nada. Com ela, cada site recebe só a lista do que já se sabe que ele tem. A URL do produto não vai no plano: ela já está em achados/{dominio}.csv desde a varredura, e é de lá que a coleta a lê.

É aqui que o "um site serve para vários itens" vira economia concreta: uma loja com 61 itens é uma sessão de navegador que rende 61 coletas. Quanto mais itens por site, menos sessões.

Esse arquivo é gerado, nunca editado à mão. Ele sai de data/interim/achados/*.csv cruzado com fornecedores_master.csv, e é regerado toda vez que a cobertura muda. Site que tem achado mas não está APROVADO no master fica de fora — é a regra inviolável 2, verificada onde importa.

### Execução: o site é a unidade, a categoria é o filtro

A varredura roda um processo por site, e a categoria entra como parâmetro de quem quer se concentrar numa parte. Quem dispara é o orquestrador, sempre:

```
python -m src.orquestrador varredura --site gpinox.com.br
python -m src.orquestrador varredura --categoria UTENSILIOS   # todos os sites, so esses itens
python -m src.runners.etapa2_plano                            # gera o plano e a cobertura
```

Não existe python -m src.runners.etapa2_varredura. Chamar o runner direto não funciona, e é de propósito: fora do orquestrador não existe a garantia de um processo por domínio, que é o que sustenta o rate limit. O mesmo vale para a etapa3_coletar.

Cada processo escreve data/interim/achados/{dominio}.csv. Um arquivo por site, ninguém disputa nada, e um site que falhou é reprocessado sozinho sem refazer o resto.

O arquivo é acumulado, não sobrescrito. Uma loja de utensílios costuma vender EPI também, e as duas categorias são varridas em dias diferentes por pessoas diferentes: gravar o arquivo inteiro a cada rodada fazia a segunda apagar o resultado da primeira sem aviso nenhum. A regra do acúmulo é: sai quem foi varrido agora, fica quem não foi.

Essa escolha resolve de graça um problema que apareceria com execução por categoria: se quatro categorias rodassem em paralelo, todas bateriam nos mesmos domínios ao mesmo tempo e o limite de 3 requisições por domínio viraria 12. Com um processo por site, dois processos nunca tocam a mesma loja.

Uma diferença importante entre as duas fases: a varredura NÃO lê o plano_coleta.csv. Ela monta o trabalho a partir do fornecedores_master.csv — todo site aprovado × todo item da categoria. Fazer as duas lerem o mesmo arquivo criava uma volta fechada, em que varrer exigia um plano que só existe depois de varrer, e numa base nova nenhuma das duas rodava.

## 5. Etapa 3 — Coleta final

A Etapa 3 não sai procurando nada. Ela recebe o plano de coleta da Etapa 2 — site por site, com a lista de itens — e só vai buscar preço, frete e print do que já se sabe que existe.

Nenhum site entra aqui sem estar no banco de fornecedores aprovados. Os 5 fornecedores de um item podem variar de uma UF para outra, mas todos saem da mesma lista validada.

O destino é o template FNDE_output.xlsx. Mapeando cada coluna para sua origem:

| Coluna do template | De onde vem |
|---|---|
| Categoria, Código FGV, Item | itens.csv (Etapa 0) |
| UF, Nome Empresa, CNPJ | fornecedores_master.csv (Etapa 1) |
| FONTE | URL do produto, salva na varredura, já com o SKU da variação |
| PRODUTO PESQUISADO | Título do produto na loja, com a variação |
| Data coleta | Timestamp do scraper |
| Preço PRODUTO | preco_lista da página (o riscado), ou o preço pago se não houver |
| VALOR DESCONTO, OBS Desconto | Diferença entre preco_lista e preco |
| PREÇO FINAL | preco: o que se paga hoje |
| VALOR FRETE, OBS FRETE | Cotação na página do produto, conforme o modo_frete do site |
| PRINT | A 16ª coluna: miniatura embutida, com hyperlink para o PNG original |

O template tem 15 colunas e nenhuma delas é o print. Ele entra como uma 16ª coluna, PRINT, no fim. E a entrega deixa de ser um arquivo: são sete .xlsx, um por categoria, mais a pasta prints/.

### Granularidade: uma linha por item × fornecedor × UF

Decidido. Cada linha é uma combinação de item, fornecedor e UF. São 5 fornecedores distintos por item, repetidos nas três UFs: 144 × 5 × 3 = 2.160 linhas. Ter muitas linhas não é problema — a planilha é feita para ser filtrada, não lida.

Na prática o coletor roda em dois níveis. Uma vez por par item-fornecedor: abre a página, lê preço e desconto, registra FONTE e PRODUTO PESQUISADO. Depois, três vezes sobre esse mesmo resultado: cota o frete de cada UF e tira o print correspondente. Preço e desconto são copiados; só frete, print e UF mudam.

A contagem de linhas vira a medida de progresso: linhas_preenchidas / 2.160. Item que não fechar 5 fornecedores aparece em data/interim/pendencias.csv, com quantos faltam e quantos candidatos foram descartados.

### Coletar por site, montar depois

A coleta e a montagem da entrega são dois programas separados, e é importante que continuem sendo. O coletor não sabe o que é o template do FNDE; o montador não sabe o que é um site.

O coletor. Um processo por site. Abre o navegador uma vez, e para cada item da lista daquele site: vai direto na URL do produto, lê preço e desconto, cota o frete das três UFs, tira os prints. Escreve tudo em data/coletas/{dominio}.jsonl, uma linha por registro, conforme vai coletando.

```
python -m src.orquestrador coleta --site gpinox.com.br
```

Três ganhos vêm de graça desse desenho. A sessão do navegador é reaproveitada pelos 34 ou 61 itens da loja, em vez de subir uma por coleta. O rate limit por domínio se resolve sozinho, porque só existe um processo por domínio. E se o site cair na metade, o .jsonl já tem o que deu certo: o rerun pula o que existe e continua de onde parou.

Sobre "o que existe": só conta registro COMPLETO — com preço, com frete resolvido e com o print no disco. Um registro sem preço e sem print ocupava o lugar de (item, UF) e nunca mais era refeito; no fim do prazo a planilha tinha a linha, a linha não tinha preço, e ninguém sabia por quê. Linha de JSON truncada por uma interrupção é descartada e recoletada, em vez de esconder o resto do arquivo.

O montador. Um script que não raspa nada. Lê tudo que estiver em data/coletas/, junta com itens.csv e fornecedores_master.csv, corta nos 5 fornecedores por item e UF, e escreve os .xlsx mais as miniaturas.

```
python -m src.export.montar_entrega --entrada data/coletas/ --saida data/output/
```

Por ser independente, ele pode rodar a qualquer momento, inclusive com a coleta pela metade — e é assim que se descobre cedo que uma coluna está saindo errada. Rodar o montador no primeiro site coletado, antes de disparar os outros quarenta, é meia hora que economiza um dia.

Quando sobram mais de 5. Cinco registros não são cinco fornecedores, e essa distinção custou uma correção: ordenar e cortar em cinco entregava, com facilidade, cinco linhas do mesmo domínio, todas sem preço, enquanto um candidato com preço ficava na reserva. O corte hoje é em três tempos: descarta o que não serve (sem preço, sem print, print fora do disco, frete em aberto, score abaixo do mínimo), garante um registro por domínio, e só então ordena por maior score_match e menor preço final.

O resto vai para data/interim/reserva.csv com o motivo de cada exclusão — sem o motivo, "por que este fornecedor não entrou?" só se responde reprocessando tudo. A reserva é ferramenta interna: quando uma linha for reprovada na revisão, ela dá o substituto imediato, com URL e tudo, sem voltar ao site.

### Dividir uma categoria entre várias máquinas

UTENSILIOS sozinho tem 80 itens espalhados por dezenas de sites — é a categoria que demora. Dividir esse trabalho entre as máquinas da equipe é a forma mais direta de ganhar tempo. Mas a divisão tem que ser por site, não por quantidade de itens.

Se você fatiar os 80 itens em 4 blocos de 20 e mandar um bloco para cada máquina, as quatro vão bater nos mesmos sites, porque os itens de uma categoria se espalham por todas as lojas. Quatro máquinas × 3 requisições por domínio = 12 simultâneas na mesma loja. É bloqueio na certa, e ninguém percebe até o site parar de responder.

```
# maquina 1
python -m src.orquestrador varredura --categoria UTENSILIOS --shard 1/3
# maquina 2
python -m src.orquestrador varredura --categoria UTENSILIOS --shard 2/3
# maquina 3
python -m src.orquestrador varredura --categoria UTENSILIOS --shard 3/3
```

O orquestrador seleciona os itens da categoria, reagrupa por domínio, e fica só com os sites cujo hash(dominio) % 3 bate com o número do shard. Como o hash é determinístico, as máquinas não precisam combinar nada entre si — ninguém coordena, ninguém repete, ninguém colide.

### O limitador, para pilotar antes de disparar

Separado do shard, um --limite N que corta a lista nos N primeiros itens:

```
python -m src.orquestrador varredura --categoria UTENSILIOS --limite 10
```

O uso dele não é acelerar a execução final, é descobrir problema barato. Rodar 10 itens leva minutos e já revela adapter quebrado, termo de busca ruim ou matching mal calibrado. Descobrir isso depois de 80 itens custa a tarde inteira.

Regra prática: ninguém dispara uma categoria inteira sem ter rodado --limite 10 antes e olhado o resultado.

### Frete: classificar o site antes de cotar o produto

Esta é a parte mais trabalhosa do projeto, e a razão é que frete não é um valor, é um comportamento. O mesmo site pode entregar nos três estados com preços diferentes, ou ter frete grátis para o Brasil inteiro, ou grátis acima de um valor que uma unidade nunca alcança.

A saída é separar em dois momentos: classificar o site uma vez, cotar o produto só quando a classificação exigir.

| Modo | O que significa | Cotação por produto? |
|---|---|---|
| GRATIS_NACIONAL | Grátis para todo o país | Não — frete = 0 |
| GRATIS_REGIAO | Grátis para PR, SC e/ou RS | Não — frete = 0 nas UFs cobertas |
| GRATIS_ACIMA_DE | Grátis a partir de um valor mínimo | Sim — 1 unidade quase nunca alcança o mínimo |
| TABELA_POR_CEP | Valor varia por CEP e por produto | Sim, sempre |
| SOB_CONSULTA | Não cota online | Não — vai como observação em OBS FRETE |

A classificação usa os três CEPs do Sul mais um de fora (Av. Paulista, 01310-100): sem o quarto, não há como distinguir "grátis para o Brasil inteiro" de "grátis só na região", porque nos dois casos os três CEPs do Sul dão zero.

Passo 2 — cotar na página do produto. Como a quantidade é sempre 1, não é preciso montar carrinho: quase todo site tem o campo de CEP na própria página do produto. É o caminho mais barato e o único que garante que preço e frete vieram da mesma página — o que importa para o print.

Em VTEX existe atalho melhor ainda, um endpoint de simulação que aceita item e CEP e devolve as opções de entrega em JSON, sem navegador. Dois cuidados que já custaram bug: o preço vem em CENTAVOS nessa API (1990 é R$ 19,90, não R$ 1.990,00), e a simulação precisa usar o mesmo seller que definiu o preço — cotar frete do seller A com preço do seller B monta uma linha que não existe na loja.

Sobre as três UFs. Se o modo for TABELA_POR_CEP, são 3 cotações por produto. É aqui que o volume explode, e é o argumento mais forte para classificar antes: cada site que cair em GRATIS_NACIONAL corta 3 cotações por item que ele vende.

### Print: requisito de validação

O print é o que prova que aquele preço e aquele frete existiam naquela data. Por isso ele precisa ser tirado depois de preencher o CEP, com o resultado do frete visível na mesma imagem. Print só do produto não valida entrega, que é justamente o que o solicitante quer conferir.

Quem tira o print é src/export/captura.py, não cada adapter: ele abre a página, procura o campo de CEP pelos nomes usuais, preenche, espera o frete carregar e fotografa a página inteira com page.screenshot(). Vale para todos os sites, inclusive os de plataforma com API — ninguém confere JSON. É um navegador por processo, e como o orquestrador dá um processo por domínio, isso já significa um navegador por site.

Padrão de nome. Precisa ser único por linha da planilha final, ou seja, carregar item, fornecedor e UF:

```
data/output/prints/{CATEGORIA}/{id_item}__{dominio}__{uf}.png
ex: data/output/prints/UTENSILIOS/U053__gpinox.com.br__PR.png
```

Com esse padrão, o script de export monta o caminho a partir das próprias colunas da linha — nenhuma amarração manual entre imagem e linha. E, do outro lado, a existência do arquivo é o que prova que o registro ficou completo: sem print, a linha não entra na entrega e é recoletada no rerun.

Ingestão na planilha. A miniatura é embutida com openpyxl.drawing.image.Image, ancorada na célula da coluna PRINT, com a altura da linha ajustada. O hyperlink para o PNG original fica na própria célula PRINT, e não numa coluna a mais: o template tem 15 colunas e a PRINT é a 16ª combinada — acrescentar uma 17ª quebraria o acordo com o solicitante.

O que decide se funciona é o tamanho do arquivo. Um print de página inteira em PNG dá uns 400 KB. Redimensionado para 600 px de largura e salvo em JPEG qualidade 70, cai para 40 a 60 KB. Com 50 KB por imagem:

| Planilha | Linhas | Embutido a 50 KB | Embutido a 400 KB |
|---|---|---|---|
| UTENSILIOS | 1.200 | ~60 MB | ~480 MB |
| EQUIPAMENTO | 510 | ~26 MB | ~204 MB |
| EPI | 150 | ~8 MB | ~60 MB |
| COMBUSTÍVEL | 135 | ~7 MB | ~54 MB |
| UNIFORMES | 90 | ~5 MB | ~36 MB |
| SAÚDE OCUPACIONAL | 45 | ~2 MB | ~18 MB |
| VEICULOS | 30 | ~2 MB | ~12 MB |
| Tudo num arquivo só | 2.160 | ~108 MB | ~864 MB |

A coluna da direita não abre em lugar nenhum. A da esquerda, dividida por categoria, abre em qualquer máquina.

Mantenha o PNG original intocado em prints/ e gere o JPEG comprimido em miniaturas/, senão a prova se perde na primeira execução. E conte que rolar 1.200 imagens no Excel é lento mesmo assim — vale avisar quem for receber.

Formato de entrega: confirmado. Sete arquivos, um por categoria, com a miniatura embutida. A decisão não foi só técnica — 100 e poucas linhas por planilha são legíveis, 2.160 linhas num arquivo só não são, nem para nós nem para quem recebe. Os 12 itens manuais entram nas planilhas das suas próprias categorias — COMBUSTIVEL.xlsx e SAUDE_OCUPACIONAL.xlsx — pelo mesmo montador, lendo um CSV preenchido à mão em vez de data/coletas/.

O detalhe que costuma quebrar essa opção: hyperlink relativo só funciona se a pasta prints/ estiver ao lado do arquivo, com os mesmos nomes. Se a entrega for por e-mail ou Drive, tem que ir zipada inteira, ou os links apontam para o nada.

Uma economia que vale codar: nos fornecedores classificados como GRATIS_NACIONAL, o print é o mesmo nas três UFs. Nesses casos, uma captura só serve as três linhas.

Seja qual for a escolha, os prints precisam ser gerados desde a primeira coleta. Recapturar tudo no fim significa refazer a coleta inteira, porque preço e frete mudam.

## 6. Arquitetura do repositório e padrões técnicos

### Estrutura de pastas

```
sul-scrapers/
  AGENTS.md  CLAUDE.md  GEMINI.md  .gemini/settings.json
  README.md  LEIA-ME-ANTES.md  pytest.ini  requirements.txt
  docs/
    LEIA-ME.md  ESTRUTURA.md  GUIA.md
  data/
    raw/            # planilhas originais, JSONs de CNPJ, cache HTTP
      leads/*.csv|xlsx            o que a prospeccao acha (formato livre)
      bloqueadas.csv              site que nos barrou
      falhas.csv                  site que quebrou na execucao
    interim/
      itens.csv                   132 itens da coleta automatica
      itens_manuais.csv           12 itens da coleta manual
      fornecedores_master.csv     o banco de sites
      sem_site.csv                empresa com CNPJ e sem dominio
      achados/{dominio}.csv       saida da varredura, um por site
      plano_coleta.csv            site -> itens que ele tem
      revisar.csv                 match que precisa de olho humano
      reserva.csv                 fornecedores alem dos 5, com o motivo
      pendencias.csv              item/UF que nao fechou 5 fornecedores
    coletas/{dominio}.jsonl       saida da coleta, um por site
    output/
      {CATEGORIA}.xlsx            A ENTREGA
      cobertura_{CATEGORIA}.xlsx  o painel de cobertura
      prints/{CATEGORIA}/{id_item}__{dominio}__{uf}.png
      miniaturas/                 jpeg comprimido para embutir
  logs/execucao.log
  src/
    models.py         # Item, Fornecedor, ProdutoBruto, Achado, Coleta
    orquestrador.py   # varredura|coleta --categoria --site --shard --limite
    core/
      http.py         # sessao unica: retry, rate limit, cache COM VALIDADE
      log.py          # log unico: console + logs/execucao.log
      tabelas.py      # le e grava os CSV intermediarios
      plataforma.py   # detecta VTEX/Woo/Shopify/...
      matching.py     # normalizacao, medida, embalagem e score
      frete.py        # classificar_site() e cotar_produto()
    adapters/
      base.py         # Executor (ABC) -- o contrato
      registro.py     # escolhe o executor pela plataforma
      vtex.py  woocommerce.py  shopify.py  nuvemshop.py
      generico_playwright.py
    validacao/        # extrair_cnpj.py, consultar_cnpj.py, classificar_cnae.py
    runners/
      etapa0_limpar_itens.py  # gera itens.csv e itens_manuais.csv
      etapa1_validar.py       # --com-frete  --do-zero
      etapa2_varredura.py     # roda pelo orquestrador, nao sozinho
      etapa2_plano.py         # gera plano_coleta.csv e a cobertura
      etapa3_coletar.py       # roda pelo orquestrador, nao sozinho
    export/
      montar_entrega.py       # le data/coletas/, escreve data/output/
      prints.py               # miniatura + hyperlink na coluna PRINT
      captura.py              # abre a pagina, preenche o CEP, fotografa
  tests/
    conftest.py  loja_falsa.py  fixtures/  test_*.py
```

A lógica é a mesma em todos os níveis: um arquivo por site na entrada, um arquivo por site na saída, e scripts de junção que leem pastas inteiras. Nada de arquivo único sendo escrito por vários processos.

Nem todo runner é executável sozinho. etapa0, etapa1 e etapa2_plano rodam pela linha de comando; a varredura e a coleta rodam pelo orquestrador, que é quem agrupa o trabalho por domínio. Ninguém importa runner de dentro de runner.

O detalhamento completo, com o estado de cada adapter e a tabela de quem mexe em quê, está no documento Estrutura do Repositório.

### Escolha de ferramenta

A regra é a mesma que já usamos no dia a dia, e a ordem importa: httpx ou requests primeiro, Playwright só quando não tem jeito. Uma busca em VTEX via JSON leva ~200 ms; a mesma busca via navegador leva 4 segundos. Multiplicado por 132 itens × 40 lojas, a diferença é a entrega sair na quarta ou não sair.

Playwright quando: o conteúdo só aparece depois do JS, tem desafio de bot, ou o formulário de CEP não tem endpoint acessível. E sempre com contexto reaproveitado — subir browser novo a cada loja é o erro clássico que faz a varredura levar horas.

Selenium só se alguém já tiver algo pronto que funcione. Para código novo, Playwright é mais rápido de escrever e não depende de driver.

### Não ser bloqueado

- Um httpx.Client com User-Agent de navegador real, follow_redirects=True, timeout de 20 s.
- time.sleep(random.uniform(1, 3)) entre requisições ao mesmo domínio. Lojas diferentes podem ir em paralelo à vontade.
- Concorrência máxima de 3 por domínio. Não vale correr atrás de 1 segundo e levar um bloqueio que custa meio dia.
- Retry com backoff exponencial em 429 e 5xx, 3 tentativas, depois desiste e loga.
- Loja que bloquear entra em data/raw/bloqueadas.csv com data e motivo, e o grupo é avisado na hora. O pipeline faz isso sozinho: o bloqueio sobe como exceção até o runner, que registra e para de insistir naquele domínio.
Nada de except Exception: return []. O core/http.py levanta SiteBloqueado, FalhaDeRede ou RespostaInvalida, e o adapter registra qual foi. Timeout, bloqueio e JSON quebrado com a mesma cara de "nenhum produto encontrado" fazem a pessoa reescrever o termo de busca quando o problema era outro.

### O cache tem validade, e a validade muda com a fase

Toda resposta HTTP é gravada em disco — ela é prova do que o site respondeu naquele instante, não só economia de rede. O que muda é por quanto tempo ela pode ser reaproveitada:

| Fase | Construtor | Validade |
|---|---|---|
| varredura | Cliente.para_varredura() | 7 dias — reprocessar o parser é barato |
| coleta | Cliente.para_coleta() | nenhuma — sempre busca de novo |

O motivo: preço, estoque e frete entram na entrega com a data da coleta ao lado e um print tirado na hora. Um corpo guardado de outro dia faria a planilha discordar da própria prova. A variável SUL_SCRAPERS_CACHE_TTL sobrepõe os dois.

### Qualidade sob pressão

São 154 testes, e nenhum deles toca a rede de verdade:

```
pytest -m "not lento"   # 145 testes, ~4 s
pytest                  # inclui o fluxo completo com navegador (~2 min)
```

tests/loja_falsa.py é uma loja VTEX servida em localhost, hostil de propósito nos pontos em que o pipeline já errou: o primeiro SKU é a unidade avulsa quando o item pede o kit, o primeiro seller está sem estoque e mais caro, o preço tem riscado, e o frete muda nos três CEPs. É contra ela que roda o teste de ponta a ponta — varredura, plano, coleta nas três UFs, Excel e prints.

O que ainda falta: os 20 pares item-produto rotulados à mão para calibrar o matching. Os testes de hoje usam casos derivados dos itens reais 294 (100 máscaras), 313 (50 pares), 306 (avental avulso) e U053 (kit de 5 tábuas), que cobrem as armadilhas conhecidas — mas 20 pares rotulados por alguém que conhece a lista continuam sendo o que evita entregar uma planilha cheia de match errado sem ninguém perceber.

E cada adapter novo precisa do seu teste contra uma resposta real salva em tests/fixtures/. Hoje só o VTEX tem.

## 7. Divisão dos 9 integrantes

O princípio: cada frente entrega um arquivo com formato acordado e não depende de ninguém para começar. Quem depende de outro só consegue trabalhar metade do tempo.

| # | Frente | Pessoas | Entrega concreta |
|---|---|---|---|
| A | Integração e revisão | 1 | Repo, models.py, core/, orquestrador, revisão dos PRs, consolidação final |
| B | Validação de CNPJ | 2 | fornecedores_master.csv com CNAE e situação resolvidos |
| C | Prospecção contínua | 2 | Arquivos em data/raw/leads/ (nome + domínio), alimentando a frente B sem parar |
| D | Adapters de plataforma | 2 | vtex.py, woocommerce.py, shopify.py, nuvemshop.py — e Tray/Magento se aparecerem |
| E | Itens e matching | 1 | itens.csv com termos_busca, e matching.py calibrado |
| F | Frete, print e export | 1 | frete.py, captura.py, prints.py, montar_entrega.py + os 12 itens manuais |

A frente F é a mais subdimensionada da tabela, e de propósito: ela começa com uma pessoa e cresce. Frete é a parte mais trabalhosa do projeto, e assim que a frente B entregar a lista validada, essas duas pessoas migram para F. Mesma coisa com a C, que vira prospecção dirigida e ocupa menos gente conforme a cobertura sobe.

A frente C é a única que não escreve código, e por isso é onde encaixam melhor as pessoas com menos familiaridade com scraping. Ela também é a que muda mais de natureza no meio do caminho: sai de "achar atacadistas" e vira "achar quem vende este item específico", guiada pela coluna "Falta para 5" da cobertura. O sem_site.csv é o primeiro lugar para ela olhar.

## 8. Sequência de trabalho

Este guia não traz calendário. O que ele traz é ordem: o que precisa existir antes do quê, e o que cada frente está esperando. Duas datas existem e são só duas. A entrega é 25/09/2026. E a expectativa da equipe é estar varrendo sites em 22/09/2026 — não como prazo, mas como o sinal de que estamos no ritmo certo.

```
Fase 0                Fase 1                  Fase 2
Repo e contrato  ->   Validar fornecedores -> Varredura por categoria
      |                        ^                        |
      v                        |                        v
Itens limpos e           (cobertura < 5)   <--  Cobertura chegou a 5?
termos de busca  -------------------------------------> |  sim
                                                        v
                                         Fase 3: preco, frete e print
                                                        |
                                                        v
                                                 Planilha final
```

- Fase 0 — o contrato. Repo forkado, models.py escrito, requirements.txt congelado. Termina quando todo mundo consegue rodar um script do repo na própria máquina.
- Fase 1 — validar fornecedores. Extrair CNPJ, consultar API, classificar CNAE. Roda em lote e é rápida em máquina; o que demora é achar os candidatos novos, e essa parte não para nunca.
- Itens limpos. Paralela e independente: itens.csv com os 132 itens automáticos e os termos de busca. Já está rodada e versionada.
- Fase 2 — varredura. Começa assim que houver uma leva de fornecedores aprovados, mesmo que pequena. Não precisa da lista completa — com 5 lojas já dá para calibrar o matching e descobrir problema de adapter.
- Volta à Fase 1. A varredura devolve a cobertura. Enquanto houver item com menos de 5 fontes, a prospecção continua, agora dirigida. Esse laço é o coração do projeto.
- Fase 3 — coleta final. Só depende de um item ter suas 5 fontes — ou seja, dá para começar pelos itens que fecharam primeiro, sem esperar a cobertura inteira.

### Onde olhar quando parecer que travou

| Sintoma | O que geralmente é | Saída |
|---|---|---|
| Etapa 1 para com erro citando um arquivo de leads | Planilha sem coluna de site reconhecível | Renomear a coluna para conter site, url, domínio ou link — a mensagem lista o que o arquivo tem |
| Poucos CNPJs encontrados | Rodapé fora do padrão ou site com JS | Ampliar a lista de páginas raspadas antes de partir para o manual |
| Muitos itens com 1 ou 2 fontes | Termo de busca genérico demais | Ajustar termos_busca antes de prospectar mais lojas |
| Adapter devolvendo vazio | Loja mudou o endpoint, ou bloqueio | Olhar logs/execucao.log: timeout, bloqueio e JSON quebrado agora aparecem com nomes diferentes |
| Muitos itens em revisar.csv | Título da loja não diz a embalagem | Conferir o motivo_match: se for "não diz quantas vêm", é caso de olho humano mesmo |
| Frete não carrega | Campo de CEP em iframe ou AJAX lento | Sobrescrever SEL_CAMPO_CEP no adapter do site |
| Coleta não avança no rerun | Registros incompletos sendo descartados | É o esperado: sem preço ou sem print, a linha é recoletada |

### Se o escopo precisar encolher

Corta por categoria, nunca por qualidade. UTENSILIOS (80) e EQUIPAMENTO (34) somam 114 dos 144 itens e são a espinha. EPI e UNIFORMES (16 itens) passam para coleta manual distribuída — menos de 2 itens por pessoa.

Outra alavanca, menos óbvia: reduzir de 5 preços para 3 nos itens que ninguém achou em 5 lugares, documentando quais foram. O pendencias.csv já é exatamente essa lista. Uma planilha honesta com a lacuna marcada vale mais que uma planilha completa com match inventado.

## 9. Definição de pronto

Uma etapa só está pronta quando o próximo consegue começar sem perguntar nada. Checklist por etapa:

Etapa 0

- Fork criado, main protegida, todos com acesso
- requirements.txt congelado e .venv rodando na máquina de cada um
- models.py no repo e lido por todos
- pytest -m "not lento" passando na máquina de cada um
Etapa 1

- Todo aprovado tem CNPJ com dígito válido, CNAE e situação ATIVA
- flag_atacarejo preenchida em todas as linhas
- Entrega para PR, SC e RS testada com os três CEPs
- Coluna plataforma preenchida
- Coluna modo_frete classificada
- SUBCLASSES_AUTOPECAS_ATACADO preenchida, ou os 2 pneus declarados fora do escopo automático
- sem_site.csv trabalhado: cada empresa com CNPJ ou ganhou domínio ou foi descartada com motivo
- Tudo que a prospecção achou está em data/raw/leads/ e a Etapa 1 roda sem erro de coluna
Etapa 2

- itens.csv com 132 linhas e termos_busca em todas
- Cada adapter com teste contra fixture salva de uma loja real
- Matching validado contra os 20 pares rotulados
- cobertura_{CATEGORIA}.xlsx gerada, com Fontes aceitas e Falta para 5
- plano_coleta.csv gerado
- revisar.csv revisado: cada linha vira aceite ou descarte
Etapa 3

- 2.160 linhas: uma por item × fornecedor × UF, 5 fornecedores DISTINTOS por item
- Todas as 15 colunas do template preenchidas ou justificadamente vazias, mais a 16ª (PRINT)
- Todo print mostra preço e frete da UF correspondente na mesma imagem
- Sete .xlsx, um por categoria, cada um abrindo em menos de um minuto
- Tudo zipado junto com prints/, caminhos batendo com os hyperlinks
- Matches de score entre 60 e 80 revisados a olho
- Os 12 itens manuais (GLP, exames) incluídos
- reserva.csv e pendencias.csv gerados no repositório, fora do pacote de entrega

### Decisões fechadas

Nada está pendente com o solicitante. Para referência rápida:

| Questão | Decisão |
|---|---|
| Volume | 5 preços por item e por UF, de 5 fornecedores distintos — 2.160 linhas |
| Granularidade | Uma linha por item × fornecedor × UF |
| Entrega | Sete .xlsx, um por categoria, zipados com a pasta prints/ |
| Print | Requisito, com preço e frete da UF na mesma imagem, miniatura embutida |
| Marca e fabricante | Fora do pipeline; o critério é aderência à descrição |
| Coleta automática | UTENSILIOS, EQUIPAMENTO, EPI, UNIFORMES, VEICULOS — 132 itens |
| Coleta manual | COMBUSTÍVEL, SAÚDE OCUPACIONAL — 12 itens, 180 linhas |
| Embalagem | Faz parte do item: pacote de 100 não é atendido por unidade avulsa |
| Reserva de fornecedores | Fica no repositório, fora da entrega |

## 10. Registro de alterações e imprevistos

Este guia é a fonte da verdade do projeto, e vai mudar durante a execução. Toda alteração de escopo, decisão nova ou imprevisto que afete o plano entra aqui, com data e uma linha de contexto — para que ninguém precise reconstruir depois por que algo mudou.

O documento é somente leitura para a equipe e editado por uma pessoa só. Quem identificar um problema comenta no ponto do documento em vez de editar; o comentário vira uma linha nesta tabela quando a decisão for tomada.

| Data | O que mudou | Por quê |
|---|---|---|
| 17/09 | Guia criado com as três etapas acordadas | Ponto de partida da equipe |
| 17/09 | Volume revisado para 5 preços por item e por UF | Solicitante confirmou 2.160 linhas |
| 17/09 | Cronograma por data substituído por sequência de fases | Datas fixas pesam sobre parte da equipe; a ordem importa mais que o calendário |
| 17/09 | Site vira a unidade de execução, categoria vira filtro | Evita reabrir a mesma loja a cada item e resolve o rate limit por construção |
| 18/09 | Entrega confirmada como um arquivo por categoria | Mais legível para quem recebe, e viabiliza a miniatura embutida |
| 18/09 | Execução por categoria, com --shard por site e --limite para piloto | Divide uma categoria entre máquinas sem colisão de domínio |
| 18/09 | Repositório neutro de ferramenta: AGENTS.md como fonte única | Parte da equipe usa ChatGPT ou Gemini; ninguém pode ficar sem contexto |
| 19/09 | Guia conferido linha a linha contra o código e corrigido em 17 pontos: contrato de dados (id_item é str, cinco dataclasses), comandos de varredura e coleta (rodam pelo orquestrador, não pelo runner), VEICULOS é automático (132 itens e 12 manuais, não 130 e 14), regras de matching por embalagem e divergência, critério da reserva, validade do cache e a lacuna de Tray/Magento | O código mudou na correção dos 8 pontos críticos levantados na análise do repositório, e o guia passou a contradizê-lo. Guia que contradiz o código em silêncio é pior que guia nenhum |
| 19/09 | Prospecção passa a entregar em data/raw/leads/, em formato livre: qualquer .csv ou .xlsx, exigindo só uma coluna de site — reconhecida por sinônimo (site, url, dominio, link, endereco, pagina, website, portal). Planilha sem essa coluna agora derruba a Etapa 1 com mensagem nomeando arquivo e colunas | O guia já prometia que a frente C entregaria "nome + domínio numa linha de CSV", mas não havia código que lesse esse arquivo: as duas planilhas originais estavam fixas no código, com nome de aba e de coluna. Pior, coluna com outro nome devolvia zero fornecedores em silêncio |

### O que registrar aqui

- Site que bloqueou de vez e saiu da lista
- Item que não fechou 5 fornecedores e o que foi feito
- Mudança de critério de aprovação de fornecedor
- Qualquer coisa que o solicitante pedir diferente do combinado
- Decisão técnica que a equipe tomou no meio do caminho e que contradiz algo escrito acima
O último item é o mais importante. Guia que contradiz o código em silêncio é pior que guia nenhum.

