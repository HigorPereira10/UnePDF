"""Gravação segura dos arquivos gerados, usada por todas as ferramentas."""
from __future__ import annotations

import os
from pathlib import Path
from typing import BinaryIO, Callable

from unepdf.core.erros import ErroUnePDF


def gravar_com_seguranca(destino: Path, escrever: Callable[[BinaryIO], None]) -> bool:
    """Grava em um arquivo temporário e só então troca pelo definitivo.

    Assim, se a gravação falhar no meio (rede caiu, disco cheio), o arquivo anterior
    continua intacto e nenhum arquivo pela metade fica na pasta.
    Retorna True se um arquivo anterior com o mesmo nome foi substituído.
    """
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
    except OSError as erro:
        raise ErroUnePDF(
            f"Não foi possível criar a pasta de destino:\n{destino.parent}\n\n{erro.strerror or erro}"
        ) from erro

    substituiu = destino.exists()
    temporario = destino.with_name(destino.name + ".tmp")
    try:
        with open(temporario, "wb") as arquivo:
            escrever(arquivo)
        os.replace(temporario, destino)
    except PermissionError as erro:
        temporario.unlink(missing_ok=True)
        raise ErroUnePDF(
            f"Não foi possível salvar o arquivo:\n{destino}\n\n"
            "Se ele estiver aberto em outro programa (ex.: leitor de PDF), feche e tente novamente."
        ) from erro
    except OSError as erro:
        temporario.unlink(missing_ok=True)
        raise ErroUnePDF(f"Erro ao salvar o arquivo:\n{destino}\n\n{erro.strerror or erro}") from erro
    except BaseException:
        temporario.unlink(missing_ok=True)
        raise
    return substituiu
