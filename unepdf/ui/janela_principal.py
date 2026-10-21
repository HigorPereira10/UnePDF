"""Janela principal: barra lateral de navegação e área com a tela atual."""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QCloseEvent, QDesktopServices, QDragEnterEvent, QDropEvent, QGuiApplication, QIcon
from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QDialog,
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
from unepdf.ui.atualizacao import DialogoAtualizacao, FaixaNovaVersao
from unepdf.ui.componentes import GrupoLateral, caminhos_locais
from unepdf.ui.contexto import ContextoApp
from unepdf.ui.dialogos import mostrar_erro, perguntar
from unepdf.ui.ferramentas import FERRAMENTAS, TelaFerramenta, buscar, por_categoria
from unepdf.ui.tela_configuracoes import TelaConfiguracoes
from unepdf.ui.tela_inicial import TelaInicial
from unepdf.ui.tema import CORES
from unepdf.utils import atualizacao
from unepdf.utils.atualizacao import NovaVersao
from unepdf.utils.caminhos import pasta_logs
from unepdf.utils.recursos import caminho_recurso

log = logging.getLogger(__name__)

CHAVE_INICIO = "inicio"
CHAVE_UNIR = "unir"
CHAVE_CONFIGURACOES = "configuracoes"
# Espera depois do último arquivo vindo do Explorer: ele abre uma cópia do app por arquivo, em sequência
ESPERA_ARQUIVOS_EXTERNOS_MS = 600


class JanelaPrincipal(QMainWindow):
    # Podem ser emitidos de outras threads: o Qt entrega na thread da interface
    arquivos_externos = Signal(list, str)  # caminhos e a chave da ferramenta que os recebe
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

        self._nova_versao: NovaVersao | None = None
        self.faixa_versao = FaixaNovaVersao()
        self.faixa_versao.atualizar.connect(self._atualizar)
        self.faixa_versao.ver_pagina.connect(self._abrir_pagina_nova_versao)
        conteudo = QWidget()
        layout_conteudo = QVBoxLayout(conteudo)
        layout_conteudo.setContentsMargins(0, 0, 0, 0)
        layout_conteudo.setSpacing(0)
        layout_conteudo.addWidget(self.faixa_versao)
        layout_conteudo.addWidget(self.pilha, 1)

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._montar_barra_lateral())
        layout.addWidget(conteudo, 1)
        self.setCentralWidget(central)

        self.abrir(CHAVE_INICIO)
        self._centralizar_na_tela()
        self.setAcceptDrops(True)

        self._externos: dict[str, list[Path]] = {}
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
        self.aviso_versao.clicked.connect(self._atualizar)

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
                item = self._criar_item(ferramenta.chave, ferramenta.nome_lateral, ferramenta.icone)
                item.setToolTip(ferramenta.nome if ferramenta.nome_curto else "")
                grupo.adicionar(item)
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
                self.telas[chave].abrir_ferramenta.connect(self._abrir_com_caminhos)
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

    def _abrir_com_caminhos(self, chave: str, caminhos: list) -> None:
        self.abrir(chave)
        if not self.telas[chave].executor.em_execucao:
            self.telas[chave].receber_caminhos(caminhos)

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

    def receber_externos(self, caminhos: list, ferramenta: str = CHAVE_UNIR) -> None:
        """Junta os arquivos que chegam quase ao mesmo tempo e entrega todos de uma vez à ferramenta
        (o Unir PDFs, ou a separação de notas pelo item do Explorer)."""
        self._externos.setdefault(ferramenta, []).extend(Path(c) for c in caminhos)
        self._timer_externos.start(ESPERA_ARQUIVOS_EXTERNOS_MS)

    def _entregar_externos(self) -> None:
        for ferramenta in list(self._externos):
            tela = self.telas.get(ferramenta)
            if tela and tela.executor.em_execucao:
                # A ferramenta está trabalhando: os arquivos esperam ela terminar
                self._timer_externos.start(1000)
                continue
            caminhos = list(dict.fromkeys(self._externos.pop(ferramenta)))
            log.info("%d arquivo(s) recebidos de fora do app para %s", len(caminhos), ferramenta)
            self._para_frente()
            if caminhos:
                self.abrir(ferramenta)
                self.telas[ferramenta].receber_caminhos(caminhos)

    def _para_frente(self) -> None:
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()

    def mostrar_nova_versao(self, nova: NovaVersao | None) -> None:
        if nova is None:
            return
        self._nova_versao = nova
        pelo_app = self._atualiza_pelo_app()
        self.aviso_versao.setText(f"Nova versão {nova.versao} disponível")
        self.aviso_versao.setToolTip("Atualiza o UnePDF" if pelo_app else "Abre a página de download no navegador")
        self.aviso_versao.show()
        self.faixa_versao.mostrar(nova, pelo_app)

    def _atualiza_pelo_app(self) -> bool:
        return bool(self._nova_versao and self._nova_versao.instalador and atualizacao.pode_atualizar_pelo_app())

    def _abrir_pagina_nova_versao(self) -> None:
        if self._nova_versao:
            QDesktopServices.openUrl(QUrl(self._nova_versao.pagina))

    def _atualizar(self) -> None:
        if not self._nova_versao:
            return
        if not self._atualiza_pelo_app():
            self._abrir_pagina_nova_versao()
            return
        if any(tela.executor.em_execucao for tela in self.telas.values()):
            self.faixa_versao.texto.setText(
                "Uma ferramenta ainda está trabalhando. Espere ela terminar e clique em Atualizar agora de novo."
            )
            self.faixa_versao.show()
            return
        instalador = self._baixar_atualizacao(self._nova_versao)
        if instalador is None:
            return
        try:
            atualizacao.instalar_depois_de_fechar(instalador, pasta_logs() / "atualizacao.log")
        except OSError as erro:
            log.exception("Não foi possível iniciar a atualização")
            mostrar_erro(self, erro, "Não foi possível atualizar")
            return
        self._fechar_para_atualizar()

    def _baixar_atualizacao(self, nova: NovaVersao) -> Path | None:
        """Mostra o download com progresso. Os testes substituem este método."""
        dialogo = DialogoAtualizacao(self, nova)
        return dialogo.instalador if dialogo.exec() == QDialog.DialogCode.Accepted else None

    def _fechar_para_atualizar(self) -> None:
        log.info("Fechando para atualizar para a versão %s", self._nova_versao.versao if self._nova_versao else "?")
        self.close()
        QApplication.quit()

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
