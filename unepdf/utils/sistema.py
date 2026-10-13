"""Integração com o Windows: abrir arquivos, pastas e identificar o app na barra de tarefas."""
import ctypes
import os
import subprocess
from pathlib import Path


def abrir_arquivo(caminho: Path) -> None:
    """Abre o arquivo no programa padrão do Windows (ex.: leitor de PDF)."""
    os.startfile(caminho)


def mostrar_na_pasta(caminho: Path) -> None:
    """Abre o Explorador de Arquivos com o arquivo já selecionado."""
    # O explorer exige o formato exato /select,"caminho", por isso a linha é montada como texto
    subprocess.Popen(f'explorer /select,"{caminho}"')


def configurar_id_app(identificador: str) -> None:
    """Faz a barra de tarefas mostrar o ícone do app, e não o ícone genérico do Python."""
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(identificador)
    except (AttributeError, OSError):
        # Fora do Windows ou em versões sem suporte: apenas mantém o ícone padrão
        pass
