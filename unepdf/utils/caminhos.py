"""Pastas do Windows onde o app guarda configurações e logs."""
import os
from pathlib import Path

from unepdf.constantes import APP_NOME


def _pasta_do_sistema(variavel: str, alternativa: str) -> Path:
    # As variáveis existem em qualquer Windows; a alternativa cobre ambientes sem elas
    valor = os.environ.get(variavel)
    return Path(valor) if valor else Path.home() / alternativa


def pasta_configuracoes() -> Path:
    """%APPDATA%\\UnePDF: acompanha o perfil do usuário em redes com perfil móvel."""
    return _pasta_do_sistema("APPDATA", "AppData/Roaming") / APP_NOME


def pasta_logs() -> Path:
    """%LOCALAPPDATA%\\UnePDF\\logs: fica só na máquina, para não pesar no perfil móvel."""
    return _pasta_do_sistema("LOCALAPPDATA", "AppData/Local") / APP_NOME / "logs"
