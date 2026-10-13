"""Registro em arquivo, com rotação, para investigar problemas relatados pelos usuários."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from unepdf.utils.caminhos import pasta_logs

NOME_ARQUIVO = "unepdf.log"
_NOME_HANDLER = "unepdf-arquivo"


def configurar_logs(
    pasta: Path | None = None,
    tamanho_maximo: int = 1024 * 1024,
    copias: int = 5,
) -> Path | None:
    """Passa a gravar o log em `pasta` (padrão: %LOCALAPPDATA%\\UnePDF\\logs).

    Guarda até `copias` arquivos antigos de `tamanho_maximo` bytes. Retorna o caminho do log,
    ou None se não foi possível criá-lo: o app funciona normalmente sem log.
    """
    pasta = pasta or pasta_logs()
    raiz = logging.getLogger()

    # Chamar de novo troca o arquivo em vez de duplicar as linhas
    for antigo in [h for h in raiz.handlers if h.get_name() == _NOME_HANDLER]:
        raiz.removeHandler(antigo)
        antigo.close()

    caminho = pasta / NOME_ARQUIVO
    try:
        pasta.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(caminho, maxBytes=tamanho_maximo, backupCount=copias, encoding="utf-8")
    except OSError:
        return None

    handler.set_name(_NOME_HANDLER)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s"))
    raiz.addHandler(handler)
    raiz.setLevel(logging.INFO)
    return caminho
