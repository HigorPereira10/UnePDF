"""UnePDF: ferramentas de PDF para Windows, 100% locais.

Pacote organizado em camadas:
    core   regras de negócio (ler, validar e gravar PDFs), sem nenhuma dependência de interface,
           para servir tanto à interface gráfica quanto à linha de comando
    ui     interface gráfica (PySide6), que apenas consome o core
    utils  funções de apoio ao sistema operacional e ao empacotamento
"""
from unepdf.constantes import APP_NOME

__version__ = "2.4.1"

__all__ = ["APP_NOME", "__version__"]
