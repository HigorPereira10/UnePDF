"""Execução do Ghostscript, usado para compressão forte e conversão para PDF/A.

O Ghostscript é um programa separado (licença AGPL), chamado por linha de comando: ele não faz
parte do código do UnePDF. Sem ele instalado, só as ferramentas que dependem dele ficam indisponíveis.
"""
from __future__ import annotations

import logging
import queue
import re
import subprocess
import sys
import threading
from pathlib import Path

from unepdf.core.erros import ErroUnePDF, OperacaoCancelada
from unepdf.core.progresso import CallbackProgresso, Cancelamento
from unepdf.utils.programas import localizar_ghostscript

log = logging.getLogger(__name__)

MENSAGEM_AUSENTE = (
    "Esta ferramenta precisa do Ghostscript, que não foi encontrado neste computador.\n\n"
    "Ele é gratuito: instale pelo site ghostscript.com e abra esta ferramenta de novo."
)
_PAGINA = re.compile(r"^Page (\d+)")


def disponivel() -> str | None:
    """None quando o Ghostscript está instalado; senão, o motivo para mostrar ao usuário."""
    return None if localizar_ghostscript() else MENSAGEM_AUSENTE


def executar(
    argumentos: list[str],
    total_paginas: int | None = None,
    progresso: CallbackProgresso | None = None,
    cancelamento: Cancelamento | None = None,
) -> str:
    """Roda o Ghostscript e devolve tudo o que ele escreveu (avisos incluídos).

    O progresso vem das linhas "Page N" que ele escreve a cada página processada.
    """
    executavel = localizar_ghostscript()
    if executavel is None:
        raise ErroUnePDF(MENSAGEM_AUSENTE)

    comando = [str(executavel), "-dBATCH", "-dNOPAUSE", "-dSAFER", *argumentos]
    # Sem isso, uma janela de console pisca na tela a cada execução, no app instalado
    sem_janela = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        processo = subprocess.Popen(
            comando, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace", creationflags=sem_janela,
        )
    except OSError as erro:
        raise ErroUnePDF(f"Não foi possível iniciar o Ghostscript:\n{executavel}\n\n{erro.strerror or erro}") from erro

    # A saída é lida em outra thread para o cancelamento ser atendido mesmo durante uma página demorada
    linhas: queue.Queue[str | None] = queue.Queue()

    def ler_saida() -> None:
        for linha in processo.stdout:
            linhas.put(linha.rstrip())
        linhas.put(None)

    threading.Thread(target=ler_saida, daemon=True).start()
    saida = []
    while True:
        if cancelamento and cancelamento.cancelado:
            processo.kill()
            processo.wait()
            raise OperacaoCancelada()
        try:
            linha = linhas.get(timeout=0.2)
        except queue.Empty:
            continue
        if linha is None:
            break
        saida.append(linha)
        if progresso and (pagina := _PAGINA.match(linha)):
            numero = int(pagina[1])
            progresso(numero, max(total_paginas or numero, numero), f"Página {numero}")

    texto = "\n".join(saida)
    if processo.wait() != 0:
        log.error("Ghostscript terminou com o código %s:\n%s", processo.returncode, texto)
        raise ErroUnePDF(
            "O Ghostscript não conseguiu processar este PDF. O arquivo pode estar danificado.\n\n"
            "Os detalhes técnicos ficaram no registro de atividades."
        )
    return texto


def pasta_do_ghostscript() -> Path | None:
    """Pasta raiz da instalação (a que contém bin, lib e iccprofiles)."""
    executavel = localizar_ghostscript()
    return executavel.parent.parent if executavel else None
