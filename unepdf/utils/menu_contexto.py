"""Item "Unir com UnePDF" no botão direito do Explorer, para PDFs e pastas.

Fica só no registro do usuário (HKEY_CURRENT_USER), sem precisar de administrador. O instalador
cria o item; a versão portátil e quem roda pelo código-fonte ligam e desligam nas configurações.
No Windows 11, os itens desse tipo aparecem em "Mostrar mais opções".
"""
from __future__ import annotations

import sys
from pathlib import Path

from unepdf.utils.recursos import caminho_recurso

# (chave do registro, texto do item)
ITENS = (
    (r"Software\Classes\SystemFileAssociations\.pdf\shell\UnePDF.Unir", "Unir com UnePDF"),
    (r"Software\Classes\Directory\shell\UnePDF.Unir", "Unir PDFs com UnePDF"),
)


def comando() -> str:
    """Linha de comando que o Explorer executa para cada item selecionado."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --unir "%1"'
    # Pelo código-fonte: o Python sem janela de console, rodando o ponto de entrada do pacote
    python = Path(sys.executable)
    sem_console = python.with_name("pythonw.exe")
    entrada = Path(__file__).resolve().parents[1] / "__main__.py"
    return f'"{sem_console if sem_console.exists() else python}" "{entrada}" --unir "%1"'


def _icone() -> str:
    return sys.executable if getattr(sys, "frozen", False) else str(caminho_recurso("assets/icone.ico"))


def instalado() -> bool:
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, ITENS[0][0] + r"\command"):
            return True
    except (ImportError, OSError):
        return False


def instalar() -> None:
    import winreg

    for chave, texto in ITENS:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, chave) as item:
            winreg.SetValueEx(item, "MUIVerb", 0, winreg.REG_SZ, texto)
            winreg.SetValueEx(item, "Icon", 0, winreg.REG_SZ, _icone())
            # Permite usar o item com qualquer quantidade de arquivos selecionados
            winreg.SetValueEx(item, "MultiSelectModel", 0, winreg.REG_SZ, "Player")
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, chave + r"\command") as linha:
            winreg.SetValueEx(linha, "", 0, winreg.REG_SZ, comando())


def remover() -> None:
    import winreg

    for chave, _ in ITENS:
        for subchave in (chave + r"\command", chave):
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, subchave)
            except OSError:
                pass
