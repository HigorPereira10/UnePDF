"""Tela inicial: grade com as ferramentas disponíveis, agrupadas por categoria."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import QGridLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from unepdf.ui.componentes import CartaoFerramenta
from unepdf.ui.ferramentas import Ferramenta, por_categoria

ESPACO_GRADE = 16


class TelaInicial(QWidget):
    ferramenta_escolhida = Signal(str)

    def __init__(self, ferramentas: list[Ferramenta]):
        super().__init__()
        titulo = QLabel("Ferramentas de PDF")
        titulo.setObjectName("titulo")
        subtitulo = QLabel("Tudo acontece no seu computador: seus arquivos nunca são enviados para a internet.")
        subtitulo.setObjectName("subtitulo")
        subtitulo.setWordWrap(True)

        conteudo = QWidget()
        conteudo.setObjectName("areaConteudo")
        layout_conteudo = QVBoxLayout(conteudo)
        layout_conteudo.setContentsMargins(36, 32, 36, 28)
        layout_conteudo.setSpacing(6)
        layout_conteudo.addWidget(titulo)
        layout_conteudo.addWidget(subtitulo)

        self.cartoes: list[CartaoFerramenta] = []
        # Uma grade por categoria, cada uma com os seus cartões
        self._grades: list[tuple[QGridLayout, list[CartaoFerramenta]]] = []
        for categoria, lista in por_categoria(ferramentas):
            rotulo = QLabel(categoria)
            rotulo.setObjectName("tituloCategoria")
            cartoes = [CartaoFerramenta(f.chave, f.nome, f.descricao, f.icone, f.motivo_indisponivel()) for f in lista]
            for cartao in cartoes:
                cartao.clicado.connect(self.ferramenta_escolhida)
            grade = QGridLayout()
            grade.setSpacing(ESPACO_GRADE)
            grade.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            layout_conteudo.addSpacing(18)
            layout_conteudo.addWidget(rotulo)
            layout_conteudo.addSpacing(6)
            layout_conteudo.addLayout(grade)
            self.cartoes += cartoes
            self._grades.append((grade, cartoes))
        layout_conteudo.addStretch()

        self._colunas = 0
        rolagem = QScrollArea()
        rolagem.setWidgetResizable(True)
        rolagem.setWidget(conteudo)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(rolagem)
        self._organizar(3)

    def _organizar(self, colunas: int) -> None:
        """Redistribui os cartões nas grades, para a quantidade de colunas acompanhar a largura da janela."""
        if colunas == self._colunas:
            return
        self._colunas = colunas
        for grade, cartoes in self._grades:
            for cartao in cartoes:
                grade.removeWidget(cartao)
            for indice, cartao in enumerate(cartoes):
                grade.addWidget(cartao, indice // colunas, indice % colunas)

    def resizeEvent(self, evento: QResizeEvent) -> None:
        super().resizeEvent(evento)
        util = evento.size().width() - 72  # margens laterais do conteúdo
        self._organizar(max(1, (util + ESPACO_GRADE) // (CartaoFerramenta.LARGURA + ESPACO_GRADE)))
