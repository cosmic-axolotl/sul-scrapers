"""Log único do projeto.

Existe por um motivo específico: sem isto, um timeout, um bloqueio e um
JSON quebrado viram todos a mesma coisa — "nenhum produto encontrado".
Quem olha o resultado da varredura precisa distinguir os três, senão
tenta consertar o termo de busca quando o problema era o site barrando.

Uso:
    from src.core.log import obter
    log = obter(__name__)
    log.warning("...")

O nível vem de SUL_SCRAPERS_LOG (padrão INFO). Cada processo do
orquestrador configura o seu na entrada.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

FORMATO = "%(asctime)s %(levelname)-7s %(name)s | %(message)s"
DATA = "%H:%M:%S"
# logs/ já está no .gitignore; data/raw/ não está, e log de execução não
# é dado do projeto.
ARQUIVO = Path("logs/execucao.log")

_configurado = False


def configurar(nivel: str | int | None = None, arquivo: Path | None = ARQUIVO) -> None:
    """Idempotente: chamar de novo não duplica handler.

    Grava em arquivo além do console porque o orquestrador roda N
    processos em paralelo e a saída deles se embaralha no terminal.
    """
    global _configurado
    if _configurado:
        return

    nivel = nivel or os.getenv("SUL_SCRAPERS_LOG", "INFO")
    raiz = logging.getLogger("src")
    raiz.setLevel(nivel)

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(logging.Formatter(FORMATO, DATA))
    raiz.addHandler(console)

    if arquivo is not None:
        try:
            arquivo.parent.mkdir(parents=True, exist_ok=True)
            disco = logging.FileHandler(arquivo, encoding="utf-8")
            disco.setFormatter(logging.Formatter(FORMATO, DATA))
            raiz.addHandler(disco)
        except OSError:
            # Sem disco para log é problema menor do que não rodar.
            pass

    _configurado = True


def obter(nome: str) -> logging.Logger:
    configurar()
    return logging.getLogger(nome)
