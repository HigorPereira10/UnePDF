"""Diálogos do app: mensagem de erro com detalhes para copiar e confirmação simples."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from unepdf.constantes import REPOSITORIO_GITHUB
from unepdf.core.erros import ErroUnePDF, detalhes_do_erro, mensagem_amigavel


class DialogoErro(QDialog):
    """Mostra a mensagem amigável e permite copiar os detalhes técnicos para relatar o problema."""

    def __init__(self, pai: QWidget | None, erro: BaseException, titulo: str = "Não foi possível concluir"):
        super().__init__(pai)
        self.setWindowTitle(titulo)
        self.setMinimumWidth(460)
        self.detalhes = detalhes_do_erro(erro)

        mensagem = mensagem_amigavel(erro)
        if not isinstance(erro, ErroUnePDF):
            mensagem += (
                "\n\nSe o problema continuar, use \"Copiar detalhes do erro\" e relate em "
                f"github.com/{REPOSITORIO_GITHUB}/issues."
            )

        icone = QLabel("!")
        icone.setObjectName("iconeErro")
        texto = QLabel(mensagem)
        texto.setObjectName("mensagemErro")
        texto.setWordWrap(True)
        texto.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.botao_copiar = QPushButton("Copiar detalhes do erro")
        self.botao_copiar.clicked.connect(self._copiar)
        fechar = QPushButton("Fechar")
        fechar.setObjectName("botaoPrincipal")
        fechar.setDefault(True)
        fechar.clicked.connect(self.accept)

        corpo = QHBoxLayout()
        corpo.setSpacing(14)
        corpo.addWidget(icone, 0, Qt.AlignmentFlag.AlignTop)
        corpo.addWidget(texto, 1)
        botoes = QHBoxLayout()
        botoes.addWidget(self.botao_copiar)
        botoes.addStretch()
        botoes.addWidget(fechar)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(18)
        layout.addLayout(corpo)
        layout.addLayout(botoes)

    def _copiar(self) -> None:
        QApplication.clipboard().setText(self.detalhes)
        self.botao_copiar.setText("Copiado!")
        # Ligado ao botão: se o diálogo for fechado antes, o temporizador é cancelado junto
        QTimer.singleShot(2000, self.botao_copiar, lambda: self.botao_copiar.setText("Copiar detalhes do erro"))


def mostrar_erro(pai: QWidget | None, erro: BaseException, titulo: str = "Não foi possível concluir") -> None:
    DialogoErro(pai, erro, titulo).exec()


def perguntar(pai: QWidget | None, titulo: str, mensagem: str, confirmar: str = "Sim", recusar: str = "Não") -> bool:
    """Pergunta de sim ou não, com textos de botão em português."""
    caixa = QMessageBox(QMessageBox.Icon.Question, titulo, mensagem, parent=pai)
    botao_sim = caixa.addButton(confirmar, QMessageBox.ButtonRole.AcceptRole)
    caixa.addButton(recusar, QMessageBox.ButtonRole.RejectRole)
    caixa.exec()
    return caixa.clickedButton() is botao_sim
