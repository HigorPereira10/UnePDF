"""Janela principal: barra lateral de navegação e área com a tela atual."""
from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtGui import QCloseEvent, QGuiApplication, QIcon
from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from unepdf import __version__
from unepdf.constantes import APP_NOME
from unepdf.ui.contexto import ContextoApp
from unepdf.ui.dialogos import perguntar
from unepdf.ui.ferramentas import FERRAMENTAS, TelaFerramenta, buscar
from unepdf.ui.tela_inicial import TelaInicial
from unepdf.ui.tema import CORES
from unepdf.utils.recursos import caminho_recurso

CHAVE_INICIO = "inicio"


class JanelaPrincipal(QMainWindow):
    def __init__(self, contexto: ContextoApp):
        super().__init__()
        self.contexto = contexto
        self.setWindowTitle(APP_NOME)
        self.setWindowIcon(QIcon(str(caminho_recurso("assets/icone.ico"))))
        self.setMinimumSize(880, 580)
        self.resize(1120, 720)

        self.pilha = QStackedWidget()
        self.tela_inicial = TelaInicial(FERRAMENTAS)
        self.tela_inicial.ferramenta_escolhida.connect(self.abrir)
        self.pilha.addWidget(self.tela_inicial)
        # As telas das ferramentas são criadas só quando abertas pela primeira vez
        self.telas: dict[str, TelaFerramenta] = {}

        self._botoes = QButtonGroup(self)
        self._botoes.setExclusive(True)
        self._botoes_por_chave: dict[str, QPushButton] = {}

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._montar_barra_lateral())
        layout.addWidget(self.pilha, 1)
        self.setCentralWidget(central)

        self.abrir(CHAVE_INICIO)
        self._centralizar_na_tela()

    def _montar_barra_lateral(self) -> QFrame:
        barra = QFrame()
        barra.setObjectName("barraLateral")
        barra.setFixedWidth(230)

        logo = QSvgWidget(str(caminho_recurso("assets/logo_pequena.svg")))
        logo.setFixedSize(36, 36)
        # "PDF" com as cores do degradê da logo, letra por letra
        nome = QLabel(
            f'Une<span style="color:{CORES.destaque}">P</span>'
            f'<span style="color:#FF7A60">D</span><span style="color:{CORES.destaque_2}">F</span>'
        )
        nome.setObjectName("nomeApp")
        marca = QHBoxLayout()
        marca.setSpacing(10)
        marca.addWidget(logo)
        marca.addWidget(nome, 1)

        rotulo = QLabel("FERRAMENTAS")
        rotulo.setObjectName("rotuloSecao")
        versao = QLabel(f"Versão {__version__}")
        versao.setObjectName("versaoApp")

        layout = QVBoxLayout(barra)
        layout.setContentsMargins(12, 20, 12, 16)
        layout.setSpacing(2)
        layout.addLayout(marca)
        layout.addSpacing(18)
        layout.addWidget(self._criar_item(CHAVE_INICIO, "Início", "assets/icones/inicio.svg"))
        layout.addWidget(rotulo)
        for ferramenta in FERRAMENTAS:
            layout.addWidget(self._criar_item(ferramenta.chave, ferramenta.nome, ferramenta.icone))
        layout.addStretch()
        layout.addWidget(versao)
        return barra

    def _criar_item(self, chave: str, texto: str, icone: str) -> QPushButton:
        botao = QPushButton(texto)
        botao.setObjectName("itemLateral")
        botao.setCheckable(True)
        botao.setIcon(QIcon(str(caminho_recurso(icone))))
        botao.setIconSize(QSize(20, 20))
        botao.clicked.connect(lambda: self.abrir(chave))
        self._botoes.addButton(botao)
        self._botoes_por_chave[chave] = botao
        return botao

    def abrir(self, chave: str) -> None:
        """Mostra a tela inicial ou a tela da ferramenta indicada."""
        if chave == CHAVE_INICIO:
            tela = self.tela_inicial
        else:
            if chave not in self.telas:
                ferramenta = buscar(chave)
                self.telas[chave] = ferramenta.tela(ferramenta, self.contexto)
                self.pilha.addWidget(self.telas[chave])
            tela = self.telas[chave]
        self.pilha.setCurrentWidget(tela)
        self._botoes_por_chave[chave].setChecked(True)

    def _centralizar_na_tela(self) -> None:
        tela = self.screen() or QGuiApplication.primaryScreen()
        if tela:
            area = tela.availableGeometry()
            self.move(area.center() - self.rect().center())

    def closeEvent(self, evento: QCloseEvent) -> None:
        ocupadas = [t for t in self.telas.values() if t.executor.em_execucao]
        if ocupadas and not perguntar(
            self,
            "Operação em andamento",
            "Uma operação ainda está em andamento. Deseja cancelá-la e fechar o UnePDF?",
            confirmar="Cancelar e fechar",
            recusar="Continuar",
        ):
            evento.ignore()
            return
        for tela in ocupadas:
            tela.executor.cancelar()
            tela.executor.aguardar()
        evento.accept()
