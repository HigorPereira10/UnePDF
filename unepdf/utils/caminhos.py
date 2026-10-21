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


def pasta_atualizacao() -> Path:
    """Onde o instalador de uma versão nova é baixado antes de rodar."""
    return _pasta_do_sistema("LOCALAPPDATA", "AppData/Local") / APP_NOME / "atualizacao"


def pasta_separacoes() -> Path:
    """Registros das separações de notas, usados para desfazer."""
    return _pasta_do_sistema("LOCALAPPDATA", "AppData/Local") / APP_NOME / "separacoes"


def arquivo_registro_assinaturas() -> Path:
    """Planilha com o histórico das assinaturas feitas neste computador."""
    return pasta_logs() / "assinaturas.csv"
