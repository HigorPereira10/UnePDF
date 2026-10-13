"""Tema escuro do app, com a paleta tirada da logo.

As cores ficam todas aqui, e os componentes recebem o estilo pelo objectName,
para nenhuma tela precisar repetir valores de cor.
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication


@dataclass(frozen=True)
class Cores:
    fundo: str = "#15131D"
    lateral: str = "#1C1A26"
    cartao: str = "#232030"
    cartao_hover: str = "#2C283D"
    borda: str = "#34304A"
    texto: str = "#F2F1F7"
    texto_suave: str = "#A9A5BD"
    texto_desativado: str = "#6E6A82"
    destaque: str = "#FF4F87"
    destaque_2: str = "#FFA43A"
    texto_sobre_destaque: str = "#1C1A26"
    sucesso: str = "#3DD68C"
    aviso: str = "#FFC145"
    erro: str = "#FF6B6B"


CORES = Cores()
DEGRADE = (
    f"qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {CORES.destaque}, stop:1 {CORES.destaque_2})"
)


def folha_de_estilo(c: Cores = CORES) -> str:
    return f"""
    QWidget {{ color: {c.texto}; }}
    QMainWindow, QDialog, #areaConteudo {{ background: {c.fundo}; }}
    QToolTip {{ background: {c.cartao}; color: {c.texto}; border: 1px solid {c.borda}; padding: 6px; }}

    #barraLateral {{ background: {c.lateral}; border-right: 1px solid {c.borda}; }}
    #nomeApp {{ font-size: 17pt; font-weight: 600; }}
    #itemLateral {{
        text-align: left; padding: 10px 14px; border: none; border-radius: 8px;
        background: transparent; color: {c.texto_suave}; font-size: 10.5pt;
    }}
    #itemLateral:hover {{ background: {c.cartao}; color: {c.texto}; }}
    #itemLateral:checked {{ background: {c.cartao_hover}; color: {c.texto}; font-weight: 600; }}
    #rotuloSecao {{ color: {c.texto_desativado}; font-size: 8.5pt; font-weight: 600; padding: 12px 14px 4px; }}
    #versaoApp {{ color: {c.texto_desativado}; font-size: 8.5pt; }}

    #titulo {{ font-size: 20pt; font-weight: 600; }}
    #subtitulo {{ color: {c.texto_suave}; font-size: 10.5pt; }}

    #cartaoFerramenta {{ background: {c.cartao}; border: 1px solid {c.borda}; border-radius: 14px; }}
    #cartaoFerramenta:hover {{ background: {c.cartao_hover}; border-color: {c.destaque}; }}
    #cartaoFerramenta[disponivel="false"] {{ background: {c.lateral}; }}
    #cartaoFerramenta[disponivel="false"]:hover {{ border-color: {c.borda}; }}
    #nomeFerramenta {{ font-size: 11.5pt; font-weight: 600; }}
    #descricaoFerramenta {{ color: {c.texto_suave}; }}
    #motivoIndisponivel {{ color: {c.aviso}; font-size: 9pt; }}

    QPushButton {{
        background: {c.cartao}; border: 1px solid {c.borda}; border-radius: 8px;
        padding: 8px 16px; font-size: 10pt;
    }}
    QPushButton:hover {{ background: {c.cartao_hover}; }}
    QPushButton:disabled {{ color: {c.texto_desativado}; }}
    QPushButton#botaoPrincipal {{
        background: {DEGRADE}; color: {c.texto_sobre_destaque}; border: none;
        font-weight: 700; padding: 10px 22px;
    }}
    QPushButton#botaoPrincipal:hover {{ background: {c.destaque_2}; }}
    QPushButton#botaoPrincipal:disabled {{ background: {c.cartao}; color: {c.texto_desativado}; }}

    QProgressBar {{
        background: {c.cartao}; border: none; border-radius: 5px; height: 10px; text-align: center;
        color: transparent;
    }}
    QProgressBar::chunk {{ background: {DEGRADE}; border-radius: 5px; }}

    QScrollArea {{ border: none; background: transparent; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {c.borda}; border-radius: 4px; min-height: 30px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}

    #mensagemErro {{ font-size: 10.5pt; }}
    #iconeErro {{ color: {c.erro}; font-size: 22pt; font-weight: 700; }}
    """


def aplicar_tema(app: QApplication) -> None:
    """Aplica o tema escuro em todo o app, inclusive nos diálogos nativos do Qt."""
    app.setStyle("Fusion")
    # Também deixa escura a barra de título das janelas no Windows
    app.styleHints().setColorScheme(Qt.ColorScheme.Dark)

    paleta = QPalette()
    for papel, cor in (
        (QPalette.ColorRole.Window, CORES.fundo),
        (QPalette.ColorRole.WindowText, CORES.texto),
        (QPalette.ColorRole.Base, CORES.lateral),
        (QPalette.ColorRole.AlternateBase, CORES.cartao),
        (QPalette.ColorRole.Text, CORES.texto),
        (QPalette.ColorRole.Button, CORES.cartao),
        (QPalette.ColorRole.ButtonText, CORES.texto),
        (QPalette.ColorRole.Highlight, CORES.destaque),
        (QPalette.ColorRole.HighlightedText, CORES.texto_sobre_destaque),
        (QPalette.ColorRole.ToolTipBase, CORES.cartao),
        (QPalette.ColorRole.ToolTipText, CORES.texto),
        (QPalette.ColorRole.PlaceholderText, CORES.texto_desativado),
        (QPalette.ColorRole.Link, CORES.destaque_2),
    ):
        paleta.setColor(papel, QColor(cor))
    paleta.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(CORES.texto_desativado))
    paleta.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(CORES.texto_desativado))
    app.setPalette(paleta)

    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(folha_de_estilo())
