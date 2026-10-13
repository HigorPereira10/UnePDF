"""Localização de arquivos de recurso (logo, ícones), tanto no código-fonte quanto no executável."""
import sys
from pathlib import Path

# No executável gerado pelo PyInstaller, os recursos ficam na pasta indicada em sys._MEIPASS.
# Rodando pelo código-fonte, a base é a raiz do projeto.
_BASE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))


def caminho_recurso(relativo: str) -> Path:
    """Caminho absoluto de um recurso, a partir do caminho relativo à raiz do projeto."""
    return _BASE / relativo
