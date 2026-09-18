# Como encaixar este esqueleto no fork

Este `src/` é **novo**, não é uma refatoração do `scraper/` que veio do fork.
O código herdado é voltado a alimentos e a outro fluxo (SQLite + Google Sheets).

## Ordem sugerida

1. Copie `src/`, `tests/`, `data/`, `docs/`, `.gitignore`, `AGENTS.md`, `CLAUDE.md`,
   `GEMINI.md` e `.gemini/` para a raiz do fork.
2. **Não apague `scraper/` ainda.** Dois arquivos de lá são reaproveitáveis:
   - `scraper/setup_sessao.py` — salva sessão e CEP por site com
     `launch_persistent_context`. É o que a classificação de frete precisa.
   - `scraper/debug_inspecionar.py` — salva o HTML renderizado de uma URL.
     Use antes de escrever qualquer seletor novo.
3. Junte os `requirements.txt` à mão: o do fork tem `gspread` e
   `google-auth` (do Sheets), que nós não usamos. O nosso acrescenta
   `rapidfuzz`, `Unidecode` e `httpx`.
4. Quando os dois arquivos acima estiverem portados para `src/`, aí sim
   apague `scraper/` e `exports/`.

## Antes do primeiro commit

- Coloque as três planilhas e o `FNDE_output.xlsx` em `data/raw/`.
- Rode uma consulta real de CNPJ e salve a resposta em `tests/fixtures/`
  antes de confiar em `consultar_cnpj.normalizar()` — os nomes de campo
  estão chutados.
- Congele `src/models.py` e avise o grupo. É o único ponto onde 9 pessoas
  conseguem colidir de verdade.

## Sobre os arquivos de instrução

`AGENTS.md` é a fonte única — é o formato que Codex, Jules, Gemini CLI,
Copilot e Cursor leem nativamente. `CLAUDE.md` e `GEMINI.md` são ponteiros
de uma linha, porque essas duas ferramentas leem outro nome.

**Só edite `AGENTS.md`.** Editar os ponteiros cria uma divergência que
ninguém percebe até os arquivos discordarem entre si.
