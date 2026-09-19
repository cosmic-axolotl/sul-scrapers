"""Converte os SVG em PNG com o Chromium do Playwright, em 2x.

PNG porque o Word so lida bem com SVG em versoes recentes, e a planilha
vai circular por maquinas diferentes. O SVG fica ao lado, para quem
quiser editar ou ampliar sem perder nitidez.
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ESCALA = 2


def rasterizar(pasta: Path) -> None:
    svgs = sorted(pasta.glob("*.svg"))
    if not svgs:
        print("nenhum .svg em", pasta)
        return

    with sync_playwright() as p:
        navegador = p.chromium.launch()
        for svg in svgs:
            conteudo = svg.read_text(encoding="utf-8")
            # largura/altura declarados no proprio svg
            import re
            m = re.search(r'viewBox="0 0 (\d+) (\d+)"', conteudo)
            larg, alt = (int(m.group(1)), int(m.group(2))) if m else (1000, 600)

            pagina = navegador.new_page(
                viewport={"width": larg, "height": alt},
                device_scale_factor=ESCALA,
            )
            pagina.set_content(
                f'<body style="margin:0;background:#fff">{conteudo}</body>',
                wait_until="load",
            )
            destino = svg.with_suffix(".png")
            pagina.screenshot(path=str(destino), omit_background=False)
            pagina.close()
            kb = destino.stat().st_size / 1024
            print(f"  png  {destino.name:34} {larg}x{alt} @{ESCALA}x  ({kb:.0f} KB)")
        navegador.close()


if __name__ == "__main__":
    rasterizar(Path(sys.argv[1] if len(sys.argv) > 1 else "docs/img"))
