"""Aviso de nova versão no topo da janela e o download da atualização, com progresso."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from unepdf.core.erros import OperacaoCancelada, mensagem_amigavel
from unepdf.ui.executor import Executor
from unepdf.utils import atualizacao
from unepdf.utils.atualizacao import NovaVersao
from unepdf.utils.caminhos import pasta_atualizacao


class FaixaNovaVersao(QFrame):
    """Faixa com a versão nova. "Depois" só esconde até a próxima abertura do app (ou a próxima consulta)."""

    atualizar = Signal()
    ver_pagina = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("faixaVersao")
        self.texto = QLabel()
        self.texto.setWordWrap(True)
        self.botao_atualizar = QPushButton("Atualizar agora")
        self.botao_atualizar.setObjectName("botaoPrincipal")
        self.botao_atualizar.clicked.connect(self.atualizar)
        self.botao_pagina = QPushButton("Ver novidades")
        self.botao_pagina.clicked.connect(self.ver_pagina)
        self.botao_depois = QPushButton("Depois")
        self.botao_depois.clicked.connect(self.hide)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 10, 20, 10)
        layout.setSpacing(10)
        layout.addWidget(self.texto, 1)
        layout.addWidget(self.botao_pagina)
        layout.addWidget(self.botao_atualizar)
        layout.addWidget(self.botao_depois)
        self.hide()

    def mostrar(self, nova: NovaVersao, pelo_app: bool) -> None:
        if pelo_app:
            self.texto.setText(f"A versão {nova.versao} do UnePDF está disponível. A atualização leva cerca de um minuto.")
            self.botao_atualizar.setText("Atualizar agora")
            self.botao_pagina.show()
        else:
            # Versão portátil (ou sem instalador conferível): o download é pela página
            self.texto.setText(f"A versão {nova.versao} do UnePDF está disponível.")
            self.botao_atualizar.setText("Baixar")
            self.botao_pagina.hide()
        self.show()


class DialogoAtualizacao(QDialog):
    """Baixa e confere o instalador. Termina aceito com `instalador` preenchido, ou rejeitado."""

    def __init__(self, pai: QWidget | None, nova: NovaVersao):
        super().__init__(pai)
        self.setWindowTitle("Atualizar o UnePDF")
        self.setMinimumWidth(460)
        self.nova = nova
        self.instalador: Path | None = None

        self.titulo = QLabel(f"Baixando a versão {nova.versao}...")
        self.titulo.setObjectName("nomeFerramenta")
        self.barra = QProgressBar()
        self.barra.setRange(0, 0)
        self.detalhe = QLabel("O UnePDF fecha sozinho no fim e abre de novo já atualizado.")
        self.detalhe.setObjectName("subtitulo")
        self.detalhe.setWordWrap(True)
        self.erro = QLabel()
        self.erro.setObjectName("aviso")
        self.erro.setWordWrap(True)
        self.erro.hide()
        self.botao = QPushButton("Cancelar")
        self.botao.clicked.connect(self._cancelar)
        linha = QHBoxLayout()
        linha.addStretch()
        linha.addWidget(self.botao)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.addWidget(self.titulo)
        layout.addWidget(self.barra)
        layout.addWidget(self.detalhe)
        layout.addWidget(self.erro)
        layout.addLayout(linha)

        self.executor = Executor(self)
        self.executor.progresso.connect(self._progresso)
        self.executor.concluido.connect(self._concluido)
        self.executor.falhou.connect(self._falhou)

    def iniciar(self) -> None:
        instalador = self.nova.instalador
        self.executor.executar(
            lambda progresso, cancelamento: atualizacao.baixar(instalador, pasta_atualizacao(), progresso, cancelamento)
        )

    def exec(self) -> int:
        self.iniciar()
        return super().exec()

    def _progresso(self, atual: int, total: int, descricao: str) -> None:
        if total:
            self.barra.setRange(0, 1000)
            self.barra.setValue(int(atual * 1000 / total))
        self.detalhe.setText(f"{descricao}. O UnePDF fecha sozinho no fim e abre de novo já atualizado.")

    def _concluido(self, caminho: Path) -> None:
        self.instalador = caminho
        self.accept()

    def _falhou(self, erro: BaseException) -> None:
        if isinstance(erro, OperacaoCancelada):
            self.reject()
            return
        self.titulo.setText("Não foi possível atualizar")
        self.barra.hide()
        self.detalhe.hide()
        self.erro.setText(mensagem_amigavel(erro))
        self.erro.show()
        self.botao.setText("Fechar")

    def _cancelar(self) -> None:
        if self.executor.em_execucao:
            self.executor.cancelar()
        else:
            self.reject()

    def done(self, resultado: int) -> None:
        # A thread do download termina antes de a janela sumir: destruir uma QThread ativa derruba o app
        self.executor.cancelar()
        self.executor.aguardar()
        super().done(resultado)
