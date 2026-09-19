# docs/img/

Os diagramas do projeto. **São gerados por script, não desenhados à mão** — se
o código mudar, regere em vez de editar a imagem.

Cada um existe para responder uma pergunta que a prosa deixa em aberto. Se um
diagrama não fizer isso, ele não deveria estar aqui.

| Arquivo | Responde | Aparece em |
|---|---|---|
| `01-fluxo-de-dados` | Que script escreve qual arquivo, e em que ordem? | GUIA §2, ESTRUTURA §5 |
| `02-dois-planos` | Por que varredura e coleta não leem o mesmo arquivo? | ESTRUTURA §5 |
| `03-pipeline-etapa1` | Como um candidato vira APROVADO, REPROVADO ou PENDENTE? | GUIA §3 |
| `04-funil-matching` | Quando um produto é aceito, revisado ou descartado? | GUIA §4 |
| `05-escolha-dos-cinco` | Como se escolhe 5 fornecedores, e não 5 linhas? | GUIA §5 |
| `06-modulos-e-fronteiras` | Quem mexe em quê sem colidir com quem? | ESTRUTURA §6 |
| `07-arquivos-de-instrucao` | Por que só se edita o AGENTS.md? | ESTRUTURA §2 |

## Dois formatos, de propósito

- **`.svg`** — a fonte. Vetorial, nítido em qualquer zoom, e dá para editar num
  editor de texto se precisar mudar uma palavra.
- **`.png`** — o que vai embutido no `.docx` e no Markdown, em 2x. O Word só
  lida bem com SVG em versões recentes, e a entrega circula por máquinas
  diferentes.

## Regerar

Da raiz do repositório:

```bash
python docs/img/gerar_diagramas.py docs/img     # escreve os .svg
python docs/img/rasterizar.py docs/img          # converte para .png (usa o Chromium do Playwright)
```

A rasterização depende de `playwright install chromium`. Sem ele, os `.svg`
continuam sendo gerados normalmente.

Depois de regerar, os documentos que embutem as imagens precisam ser
reexportados — o `docs/LEIA-ME.md` explica de onde `GUIA.md` e `ESTRUTURA.md`
vêm.

## Paleta

Pensada para papel branco, não para tela escura, porque o destino é Word e
Markdown impresso:

| Cor | Uso |
|---|---|
| azul | processo — um script que roda |
| cinza | arquivo em disco |
| verde | o caminho que passa |
| âmbar | o que pede olho humano |
| vermelho | o que reprova ou descarta |
