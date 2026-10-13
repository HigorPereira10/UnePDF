"""Modelo único de erro do app e conversão de qualquer falha em mensagem para o usuário."""
from __future__ import annotations

import platform
import sys
import traceback

from unepdf import __version__


class ErroUnePDF(Exception):
    """Falha que impede concluir a operação. A mensagem já vem pronta para exibir ao usuário.

    Todas as exceções previstas do core herdam desta. A causa técnica, quando existir,
    vai encadeada com `raise ... from erro` e aparece só nos detalhes do erro.
    """

    @property
    def mensagem(self) -> str:
        return str(self)


def mensagem_amigavel(erro: BaseException) -> str:
    """Texto em português para exibir ao usuário, para qualquer exceção."""
    if isinstance(erro, ErroUnePDF):
        return erro.mensagem
    if isinstance(erro, PermissionError):
        return (
            "O Windows bloqueou o acesso ao arquivo.\n\n"
            "Se ele estiver aberto em outro programa, feche e tente novamente."
        )
    if isinstance(erro, FileNotFoundError):
        return f"Arquivo ou pasta não encontrado:\n{erro.filename or erro}"
    if isinstance(erro, OSError):
        return f"Erro ao acessar o arquivo ou a pasta:\n{erro.strerror or erro}"
    if isinstance(erro, MemoryError):
        return "Memória insuficiente para concluir a operação. Tente com menos arquivos de uma vez."
    return "Ocorreu um erro inesperado e a operação não foi concluída."


def detalhes_do_erro(erro: BaseException) -> str:
    """Texto técnico para o usuário copiar e relatar o problema: versões e traceback completo."""
    rastro = "".join(traceback.format_exception(type(erro), erro, erro.__traceback__))
    return (
        f"UnePDF {__version__}\n"
        f"Python {platform.python_version()} ({'executável' if getattr(sys, 'frozen', False) else 'código-fonte'})\n"
        f"{platform.platform()}\n\n"
        f"{rastro}"
    )
