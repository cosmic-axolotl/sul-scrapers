# sul-scrapers

Coleta de preços para o projeto FNDE — Região Sul.

Entrega: **5 preços por item e por UF** (PR, SC, RS), de 5 fornecedores
atacadistas distintos, para os itens da Lista de Equipamentos FNDE.
São 2.160 linhas, em planilhas separadas por categoria.

## Comece por aqui

| Se você é… | Leia |
|---|---|
| novo no projeto | `docs/GUIA.md` — o guia da equipe, com as etapas e o combinado |
| indo mexer no código | `docs/ESTRUTURA.md` e depois `src/models.py` |
| um assistente de IA | `AGENTS.md` |
| encaixando isto no fork | `LEIA-ME-ANTES.md` |

## Instalação

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium        # só quem for mexer em adapter genérico
```

## Os comandos

```bash
# Etapa 0 — limpar a lista de itens (já rodada; o resultado está versionado)
python -m src.runners.etapa0_limpar_itens

# Etapa 1 — validar fornecedores (CNPJ, CNAE, entrega no Sul)
# Antes: jogue o que a prospecção achou em data/raw/leads/ (.csv ou .xlsx,
# formato livre — só precisa de uma coluna de site/url/domínio/link)
python -m src.runners.etapa1_validar              # reaproveita CNPJ já consultado
python -m src.runners.etapa1_validar --com-frete  # também testa os 3 CEPs (lento)
python -m src.runners.etapa1_validar --do-zero    # reconsulta tudo

# Etapa 2 — varredura: quais sites têm quais itens
python -m src.orquestrador varredura --categoria UTENSILIOS --limite 10   # piloto
python -m src.orquestrador varredura --categoria UTENSILIOS --shard 1/3   # máquina 1
python -m src.runners.etapa2_plano                                        # gera o plano

# Etapa 3 — coleta de preço, frete e print
python -m src.orquestrador coleta --categoria UTENSILIOS --shard 1/3

# Montar a entrega
python -m src.export.montar_entrega --entrada data/coletas/ --saida data/output/

# Testes
pytest -m "not lento"    # segundos
pytest                   # inclui o fluxo completo com navegador (~2 min)
```

As etapas são uma fila: cada comando avisa qual rodar antes se faltar
arquivo. A varredura precisa só do `fornecedores_master.csv`; a coleta
precisa do `plano_coleta.csv`, que nasce da varredura.

**Sempre rode `--limite 10` antes de disparar uma categoria inteira.** Dez itens
levam minutos e já revelam adapter quebrado ou termo de busca ruim.

## Regras que não se quebram

1. Só entra fornecedor com CNAE principal de atacado e CNPJ ativo.
2. Nenhum site é coletado sem estar aprovado em `fornecedores_master.csv`.
3. O **site** é a unidade de execução — um processo por domínio, sempre.
4. Coleta e montagem são programas separados.
5. `id_item` é **texto**, nunca int (`U001`, `G008`, `318N`).
6. Máximo 3 requisições simultâneas por domínio.
7. Cinco linhas não são cinco fornecedores: a entrega pede 5 **domínios
   distintos**, cada um com preço e print. Quem não tem os dois vai para
   `data/interim/reserva.csv` com o motivo.
8. A embalagem faz parte do item. Uma máscara avulsa não atende quem pediu
   pacote com 100, e o preço de um kit não vale numa linha de 1 unidade.

## Como contribuir

`main` é protegida. Branch por frente (`etapa2/adapter-vtex`), PR com uma
revisão. Commits em português, no imperativo.

Se você usa Codex, Jules, Claude Code ou Gemini CLI, todos leem o mesmo
`AGENTS.md`. PR aberto por agente deve dizer isso no corpo, e quem pediu a
tarefa é quem revisa.
