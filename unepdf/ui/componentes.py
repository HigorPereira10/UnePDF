"""Componentes visuais reutilizáveis, já com o estilo do app aplicado."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon, QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QFrame, QLabel, QSizePolicy, QVBoxLayout

from unepdf.utils.recursos import caminho_recurso


class CartaoFerramenta(QFrame):
    """Cartão clicável da grade da tela inicial: ícone, nome e descrição curta.

    Quando a ferramenta está indisponível, o cartão fica apagado e mostra o motivo,
    mas continua clicável para a tela da ferramenta explicar o que falta.
    """

    clicado = Signal(str)
    LARGURA = 250

    def __init__(self, chave: str, nome: str, descricao: str, icone: str, motivo_indisponivel: str | None = None):
        super().__init__()
        self.chave = chave
        self.setObjectName("cartaoFerramenta")
        self.setProperty("disponivel", motivo_indisponivel is None)
        self.setFixedWidth(self.LARGURA)
        self.setMinimumHeight(170)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(nome)
        self.setToolTip(motivo_indisponivel or descricao)

        rotulo_icone = QLabel()
        rotulo_icone.setPixmap(QIcon(str(caminho_recurso(icone))).pixmap(QSize(44, 44)))
        rotulo_nome = QLabel(nome)
        rotulo_nome.setObjectName("nomeFerramenta")
        rotulo_descricao = QLabel(descricao)
        rotulo_descricao.setObjectName("descricaoFerramenta")
        rotulo_descricao.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 18)
        layout.setSpacing(8)
        layout.addWidget(rotulo_icone)
        layout.addSpacing(4)
        layout.addWidget(rotulo_nome)
        layout.addWidget(rotulo_descricao)
        if motivo_indisponivel:
            rotulo_motivo = QLabel(motivo_indisponivel)
            rotulo_motivo.setObjectName("motivoIndisponivel")
            rotulo_motivo.setWordWrap(True)
            layout.addWidget(rotulo_motivo)
            rotulo_icone.setEnabled(False)
        layout.addStretch()

    def mouseReleaseEvent(self, evento: QMouseEvent) -> None:
        if evento.button() == Qt.MouseButton.LeftButton and self.rect().contains(evento.position().toPoint()):
            self.clicado.emit(self.chave)
        super().mouseReleaseEvent(evento)

    def keyPressEvent(self, evento: QKeyEvent) -> None:
        # Permite usar o app só pelo teclado: Tab até o cartão e Enter ou espaço para abrir
        if evento.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.clicado.emit(self.chave)
        else:
            super().keyPressEvent(evento)
