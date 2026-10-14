"""Gravação segura dos arquivos gerados, usada por todas as ferramentas."""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import BinaryIO, Callable

from unepdf.core.erros import ErroUnePDF


def gravar_com_seguranca(destino: Path, escrever: Callable[[BinaryIO], None]) -> bool:
    """Grava em um arquivo temporário e só então troca pelo definitivo.

    Assim, se a gravação falhar no meio (rede caiu, disco cheio), o arquivo anterior
    continua intacto e nenhum arquivo pela metade fica na pasta.
    Retorna True se um arquivo anterior com o mesmo nome foi substituído.
    """

    def gerar(temporario: Path) -> None:
        with open(temporario, "wb") as arquivo:
            escrever(arquivo)

    return gravar_arquivo_gerado(destino, gerar)


def gravar_arquivo_gerado(destino: Path, gerar: Callable[[Path], None]) -> bool:
    """Como gravar_com_seguranca, para quando outro programa grava o arquivo (ex.: o Ghostscript).

    `gerar` recebe o caminho temporário onde o arquivo deve ser criado.
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
        gerar(temporario)
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


def gravar_pasta_com_seguranca(destino: Path, escrever: Callable[[Path], None]) -> bool:
    """Gera todos os arquivos em uma pasta temporária e só então troca pela pasta definitiva.

    Usada por ferramentas que geram vários arquivos (ex.: dividir). Uma pasta anterior com o
    mesmo nome é substituída por inteiro, para não misturar arquivos de execuções diferentes.
    Se algo falhar no meio, a pasta anterior continua intacta.
    Retorna True se uma pasta anterior foi substituída.
    """
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
    except OSError as erro:
        raise ErroUnePDF(
            f"Não foi possível criar a pasta de destino:\n{destino.parent}\n\n{erro.strerror or erro}"
        ) from erro

    temporaria = destino.with_name(destino.name + ".tmp")
    antiga = destino.with_name(destino.name + ".antiga")
    # Sobras de uma execução interrompida (ex.: o computador desligou no meio). Se ela parou entre
    # as duas trocas, a única cópia boa é a antiga, que volta para o lugar em vez de ser apagada.
    if antiga.exists() and not destino.exists():
        os.replace(antiga, destino)
    for sobra in (temporaria, antiga):
        shutil.rmtree(sobra, ignore_errors=True)

    substituiu = destino.exists()
    try:
        temporaria.mkdir()
        escrever(temporaria)
        if substituiu:
            os.replace(destino, antiga)
        os.replace(temporaria, destino)
    except BaseException as erro:
        shutil.rmtree(temporaria, ignore_errors=True)
        if antiga.exists() and not destino.exists():
            os.replace(antiga, destino)
        if isinstance(erro, PermissionError):
            raise ErroUnePDF(
                f"Não foi possível salvar a pasta:\n{destino}\n\n"
                "Se algum arquivo dela estiver aberto em outro programa, feche e tente novamente."
            ) from erro
        if isinstance(erro, OSError):
            raise ErroUnePDF(f"Erro ao salvar a pasta:\n{destino}\n\n{erro.strerror or erro}") from erro
        raise
    shutil.rmtree(antiga, ignore_errors=True)
    return substituiu
