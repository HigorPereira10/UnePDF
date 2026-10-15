"""Janela principal: barra lateral de navegação e área com a tela atual."""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QCloseEvent, QDesktopServices, QDragEnterEvent, QDropEvent, QGuiApplication, QIcon
from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from unepdf import __version__
from unepdf.constantes import APP_NOME
from unepdf.ui.componentes import GrupoLateral, caminhos_locais
from unepdf.ui.contexto import ContextoApp
from unepdf.ui.dialogos import perguntar
from unepdf.ui.ferramentas import FERRAMENTAS, TelaFerramenta, buscar, por_categoria
from unepdf.ui.tela_configuracoes import TelaConfiguracoes
from unepdf.ui.tela_inicial import TelaInicial
from unepdf.ui.tema import CORES
from unepdf.utils.atualizacao import NovaVersao
from unepdf.utils.recursos import caminho_recurso

log = logging.getLogger(__name__)

CHAVE_INICIO = "inicio"
CHAVE_UNIR = "unir"
CHAVE_CONFIGURACOES = "configuracoes"
# Espera depois do último arquivo vindo do Explorer: ele abre uma cópia do app por arquivo, em sequência
ESPERA_ARQUIVOS_EXTERNOS_MS = 600


class JanelaPrincipal(QMainWindow):
    # Podem ser emitidos de outras threads: o Qt entrega na thread da interface
    arquivos_externos = Signal(list)
    nova_versao = Signal(object)
    trazer_para_frente = Signal()

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
        self.tela_configuracoes = TelaConfiguracoes(contexto)
        self.pilha.addWidget(self.tela_inicial)
        self.pilha.addWidget(self.tela_configuracoes)
        # As telas das ferramentas são criadas só quando abertas pela primeira vez
        self.telas: dict[str, TelaFerramenta] = {}

        self._botoes = QButtonGroup(self)
        self._botoes.setExclusive(True)
        self._botoes_por_chave: dict[str, QPushButton] = {}
        self._grupos: dict[str, GrupoLateral] = {}

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._montar_barra_lateral())
        layout.addWidget(self.pilha, 1)
        self.setCentralWidget(central)

        self.abrir(CHAVE_INICIO)
        self._centralizar_na_tela()
        self.setAcceptDrops(True)

        self._externos: list[Path] = []
        self._timer_externos = QTimer(self)
        self._timer_externos.setSingleShot(True)
        self._timer_externos.timeout.connect(self._entregar_externos)
        self.arquivos_externos.connect(self.receber_externos)
        self.nova_versao.connect(self.mostrar_nova_versao)
        self.trazer_para_frente.connect(self._para_frente)

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

        versao = QLabel(f"Versão {__version__}")
        versao.setObjectName("versaoApp")
        self.aviso_versao = QPushButton()
        self.aviso_versao.setObjectName("avisoVersao")
        self.aviso_versao.setCursor(Qt.CursorShape.PointingHandCursor)
        self.aviso_versao.hide()
        self._pagina_nova_versao = ""
        self.aviso_versao.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(self._pagina_nova_versao)))

        # A lista de ferramentas rola quando a janela é baixa; logo e configurações ficam sempre visíveis
        lista = QWidget()
        lista.setObjectName("listaLateral")
        layout_lista = QVBoxLayout(lista)
        layout_lista.setContentsMargins(0, 0, 0, 0)
        layout_lista.setSpacing(2)
        layout_lista.addWidget(self._criar_item(CHAVE_INICIO, "Início", "assets/icones/inicio.svg"))
        layout_lista.addSpacing(6)
        for categoria, ferramentas in por_categoria():
            grupo = GrupoLateral(categoria)
            for ferramenta in ferramentas:
                grupo.adicionar(self._criar_item(ferramenta.chave, ferramenta.nome, ferramenta.icone))
            self._grupos[categoria] = grupo
            layout_lista.addWidget(grupo)
        layout_lista.addStretch()
        rolagem = QScrollArea()
        rolagem.setObjectName("rolagemLateral")
        rolagem.setWidgetResizable(True)
        rolagem.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        rolagem.setWidget(lista)

        layout = QVBoxLayout(barra)
        layout.setContentsMargins(12, 20, 12, 16)
        layout.setSpacing(2)
        layout.addLayout(marca)
        layout.addSpacing(18)
        layout.addWidget(rolagem, 1)
        layout.addSpacing(6)
        layout.addWidget(self._criar_item(CHAVE_CONFIGURACOES, "Configurações", "assets/icones/configuracoes.svg"))
        layout.addSpacing(10)
        layout.addWidget(self.aviso_versao)
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
        """Mostra a tela inicial, as configurações ou a tela da ferramenta indicada."""
        if chave == CHAVE_INICIO:
            tela = self.tela_inicial
        elif chave == CHAVE_CONFIGURACOES:
            tela = self.tela_configuracoes
        else:
            if chave not in self.telas:
                ferramenta = buscar(chave)
                self.telas[chave] = ferramenta.tela(ferramenta, self.contexto)
                self.pilha.addWidget(self.telas[chave])
            tela = self.telas[chave]
        self.pilha.setCurrentWidget(tela)
        self._botoes_por_chave[chave].setChecked(True)

        # Abre o grupo da ferramenta, para o item selecionado nunca ficar escondido
        categoria = buscar(chave).categoria if chave in self.telas else None
        for nome, grupo in self._grupos.items():
            grupo.marcar_ativo(nome == categoria)
            if nome == categoria:
                grupo.expandir(True)

    def _tela_para_arquivos(self) -> TelaFerramenta | None:
        """Tela que recebe arquivos soltos na janela. Na tela inicial, eles vão para Unir PDFs."""
        atual = self.pilha.currentWidget()
        if atual is self.tela_inicial:
            return None if self.telas.get(CHAVE_UNIR) and self.telas[CHAVE_UNIR].executor.em_execucao else atual
        if isinstance(atual, TelaFerramenta) and atual.aceita_arquivos and not atual.executor.em_execucao:
            return atual
        return None

    def dragEnterEvent(self, evento: QDragEnterEvent) -> None:
        if caminhos_locais(evento.mimeData()) and self._tela_para_arquivos():
            evento.acceptProposedAction()

    def dropEvent(self, evento: QDropEvent) -> None:
        caminhos = caminhos_locais(evento.mimeData())
        tela = self._tela_para_arquivos()
        if not caminhos or not tela:
            return
        evento.acceptProposedAction()
        if tela is self.tela_inicial:
            self.abrir(CHAVE_UNIR)
            tela = self.telas[CHAVE_UNIR]
        tela.receber_caminhos(caminhos)

    # Arquivos vindos de fora (Explorer, ícone do programa) e aviso de nova versão

    def receber_externos(self, caminhos: list) -> None:
        """Junta os arquivos que chegam quase ao mesmo tempo e entrega todos de uma vez ao Unir PDFs."""
        self._externos.extend(Path(c) for c in caminhos)
        self._timer_externos.start(ESPERA_ARQUIVOS_EXTERNOS_MS)

    def _entregar_externos(self) -> None:
        unir = self.telas.get(CHAVE_UNIR)
        if unir and unir.executor.em_execucao:
            # Uma união já está em andamento: os arquivos esperam ela terminar
            self._timer_externos.start(1000)
            return
        caminhos = list(dict.fromkeys(self._externos))
        self._externos.clear()
        log.info("%d arquivo(s) recebidos de fora do app", len(caminhos))
        self._para_frente()
        if caminhos:
            self.abrir(CHAVE_UNIR)
            self.telas[CHAVE_UNIR].receber_caminhos(caminhos)

    def _para_frente(self) -> None:
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()

    def mostrar_nova_versao(self, nova: NovaVersao | None) -> None:
        if nova is None:
            return
        self._pagina_nova_versao = nova.pagina
        self.aviso_versao.setText(f"Nova versão {nova.versao} disponível")
        self.aviso_versao.setToolTip("Abre a página de download no navegador")
        self.aviso_versao.show()

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
        for tela in self.telas.values():
            tela.encerrar()
        evento.accept()
