"""Miniatura e hyperlink na coluna PRINT.

A conta que decide tudo: 2.160 prints a 400 KB dariam um .xlsx de ~860 MB,
que não abre. Comprimido a ~50 KB e dividido por categoria, a maior
planilha fica em ~60 MB — abre em qualquer máquina.

Por isso o PNG original fica intocado em data/output/prints/ como prova, e
o que entra na planilha é um JPEG reduzido em data/output/miniaturas/.
"""

from __future__ import annotations

from pathlib import Path

LARGURA_MINIATURA = 600
QUALIDADE = 70
ALTURA_LINHA = 110


def gerar_miniatura(origem: Path, destino: Path) -> Path:
    """TODO: PIL, redimensionar para LARGURA_MINIATURA e salvar JPEG.
    Nunca sobrescrever o PNG original — ele é a prova."""
    raise NotImplementedError


def embutir(ws, linha: int, coluna: int, miniatura: Path, original: Path) -> None:
    """TODO: openpyxl.drawing.image.Image ancorada na célula, altura da
    linha em ALTURA_LINHA, e =HYPERLINK() para o original na célula ao lado."""
    raise NotImplementedError
