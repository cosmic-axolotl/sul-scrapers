# Coleta manual — categoria UNIFORMES

Ferramenta complementar ao pipeline automático descrito em `AGENTS.md`, **não**
um adapter de `src/`. Não faz varredura nem descoberta de fornecedores.

Usada quando o ambiente de coleta não tem Chrome/chromedriver disponível para
o Selenium do pipeline padrão. O fluxo aqui é manual: os preços são
encontrados por pesquisa (busca + navegação página a página) seguindo as
mesmas regras de validação do projeto (CNAE atacadista Divisão 46, sem
marketplace, sem fornecedor só-varejo, preço nunca inventado), e registrados
em `REGISTROS_UNIFORMES` dentro do script.

O que o script automatiza:

1. Validação ao vivo do CNAE de cada CNPJ via BrasilAPI (Divisão 46, principal
   ou secundário).
2. Print de cada página de produto via Playwright.
3. Geração da planilha de saída a partir de `REGISTROS_UNIFORMES`.

O que não faz: descoberta de fornecedores/preços (isso é pesquisa manual,
registrada aqui) e frete (fora do escopo desta rodada).

## Como rodar

```bash
pip install -r requirements.txt
python -m playwright install chromium
python coleta_precos_fnde_uniformes.py
```

## Como adicionar um preço novo

Adicione um dict a `REGISTROS_UNIFORMES`, com todos os campos preenchidos
(nunca inventar CNPJ, preço ou CNAE), e rode o script novamente — ele valida
o CNAE ao vivo, tira o print e regrava a planilha inteira a partir da lista.
