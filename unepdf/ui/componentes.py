"""Componentes visuais reutilizáveis, já com o estilo do app aplicado."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QMimeData, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QDragEnterEvent,
    QDragLeaveEvent,
    QDropEvent,
    QFontMetrics,
    QIcon,
    QKeyEvent,
    QMouseEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from unepdf.core.modelos import ArquivoIgnorado
from unepdf.ui.dialogos import mostrar_erro
from unepdf.utils import sistema
from unepdf.utils.recursos import caminho_recurso
from unepdf.utils.texto import plural


def caminhos_locais(dados: QMimeData) -> list[Path]:
    """Arquivos e pastas do computador em um arrastar e soltar (links da web ficam de fora)."""
    if not dados.hasUrls():
        return []
    return [Path(url.toLocalFile()) for url in dados.urls() if url.isLocalFile()]


def _repintar(widget: QWidget) -> None:
    # O Qt só reaplica a folha de estilo depois de uma propriedade mudar se for avisado
    widget.style().unpolish(widget)
    widget.style().polish(widget)


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


class AreaSoltar(QFrame):
    """Área para arrastar arquivos ou pastas, com os botões de escolha ao lado."""

    caminhos_soltos = Signal(list)
    escolher_pasta = Signal()
    escolher_arquivos = Signal()

    def __init__(self, titulo: str, dica: str, com_pasta: bool = True, texto_arquivos: str = "Escolher arquivos"):
        super().__init__()
        self.setObjectName("areaSoltar")
        self.setAcceptDrops(True)
        self.setProperty("arrastando", False)

        rotulo_titulo = QLabel(titulo)
        rotulo_titulo.setObjectName("tituloSoltar")
        rotulo_titulo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rotulo_dica = QLabel(dica)
        rotulo_dica.setObjectName("subtitulo")
        rotulo_dica.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rotulo_dica.setWordWrap(True)

        self.botao_pasta = QPushButton("Escolher pasta")
        self.botao_pasta.setObjectName("botaoPrincipal")
        self.botao_pasta.clicked.connect(self.escolher_pasta)
        self.botao_arquivos = QPushButton(texto_arquivos)
        self.botao_arquivos.clicked.connect(self.escolher_arquivos)
        if not com_pasta:
            # Sem a escolha de pasta, o botão de arquivos passa a ser o principal
            self.botao_pasta.hide()
            self.botao_arquivos.setObjectName("botaoPrincipal")
        botoes = QHBoxLayout()
        botoes.addStretch()
        botoes.addWidget(self.botao_pasta)
        botoes.addWidget(self.botao_arquivos)
        botoes.addStretch()

        self.aviso = QLabel()
        self.aviso.setObjectName("aviso")
        self.aviso.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.aviso.setWordWrap(True)
        self.aviso.hide()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(10)
        layout.addStretch()
        layout.addWidget(rotulo_titulo)
        layout.addWidget(rotulo_dica)
        layout.addSpacing(14)
        layout.addLayout(botoes)
        layout.addSpacing(8)
        layout.addWidget(self.aviso)
        layout.addStretch()

    def mostrar_aviso(self, texto: str | None) -> None:
        self.aviso.setText(texto or "")
        self.aviso.setVisible(bool(texto))

    def _destacar(self, ativo: bool) -> None:
        self.setProperty("arrastando", ativo)
        _repintar(self)

    def dragEnterEvent(self, evento: QDragEnterEvent) -> None:
        if caminhos_locais(evento.mimeData()):
            evento.acceptProposedAction()
            self._destacar(True)

    def dragLeaveEvent(self, evento: QDragLeaveEvent) -> None:
        self._destacar(False)

    def dropEvent(self, evento: QDropEvent) -> None:
        self._destacar(False)
        caminhos = caminhos_locais(evento.mimeData())
        if caminhos:
            evento.acceptProposedAction()
            self.caminhos_soltos.emit(caminhos)


class PainelProgresso(QWidget):
    """Barra de progresso com o passo atual e o botão de cancelar."""

    cancelar = Signal()

    def __init__(self):
        super().__init__()
        self.titulo = QLabel()
        self.titulo.setObjectName("tituloResultado")
        self.barra = QProgressBar()
        self.barra.setTextVisible(False)
        self.detalhe = QLabel()
        self.detalhe.setObjectName("subtitulo")
        self.botao_cancelar = QPushButton("Cancelar")
        self.botao_cancelar.clicked.connect(self._pedir_cancelamento)

        linha = QHBoxLayout()
        linha.addWidget(self.detalhe, 1)
        linha.addWidget(self.botao_cancelar)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 24, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(self.titulo)
        layout.addWidget(self.barra)
        layout.addLayout(linha)
        layout.addStretch()

    def iniciar(self, titulo: str, cancelavel: bool = True) -> None:
        """Mostra a barra em modo "ocupado" até chegar o primeiro progresso."""
        self.titulo.setText(titulo)
        self.detalhe.setText("")
        self.barra.setRange(0, 0)
        self.botao_cancelar.setVisible(cancelavel)
        self.botao_cancelar.setEnabled(True)
        self.botao_cancelar.setText("Cancelar")

    def atualizar(self, atual: int, total: int, descricao: str) -> None:
        self.barra.setRange(0, total)
        self.barra.setValue(atual)
        # Nomes de arquivo longos são encurtados no meio, para não esticar a janela
        largura = max(100, self.detalhe.width())
        texto = f"{atual} de {total}: {descricao}"
        self.detalhe.setText(QFontMetrics(self.detalhe.font()).elidedText(texto, Qt.TextElideMode.ElideMiddle, largura))

    def _pedir_cancelamento(self) -> None:
        self.botao_cancelar.setEnabled(False)
        self.botao_cancelar.setText("Cancelando...")
        self.cancelar.emit()


class ListaIgnorados(QListWidget):
    """Arquivos que não entraram no resultado, cada um com o motivo."""

    def __init__(self):
        super().__init__()
        self.setObjectName("listaIgnorados")
        self.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        # Cresce com a quantidade de itens até um limite; a partir daí, rola
        self.setSizeAdjustPolicy(QListWidget.SizeAdjustPolicy.AdjustToContents)
        self.setMaximumHeight(260)
        self._ignorados: list[ArquivoIgnorado] = []

    def preencher(self, ignorados: list[ArquivoIgnorado]) -> None:
        self._ignorados = list(ignorados)
        self.clear()
        for ignorado in ignorados:
            item = QListWidgetItem(f"{ignorado.caminho.name}: {ignorado.motivo}")
            item.setToolTip(str(ignorado.caminho))
            self.addItem(item)

    def texto(self) -> str:
        """Lista com os caminhos completos, para o usuário colar em um e-mail ou planilha."""
        return "\n".join(f"{i.caminho}: {i.motivo}" for i in self._ignorados)


class PainelResultado(QWidget):
    """Resumo ao final de uma ação: o que foi gerado, onde está e o que ficou de fora."""

    novo = Signal()

    def __init__(self, texto_novo: str):
        super().__init__()
        self.destino: Path | None = None

        self.titulo = QLabel()
        self.titulo.setObjectName("tituloResultado")
        self.resumo = QLabel()
        self.resumo.setWordWrap(True)
        self.caminho = QLabel()
        self.caminho.setObjectName("subtitulo")
        self.caminho.setWordWrap(True)
        self.caminho.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.botao_abrir = QPushButton("Abrir arquivo")
        self.botao_abrir.setObjectName("botaoPrincipal")
        self.botao_abrir.clicked.connect(lambda: self._acao_sistema(sistema.abrir_arquivo))
        self.botao_pasta = QPushButton("Mostrar na pasta")
        self.botao_pasta.clicked.connect(lambda: self._acao_sistema(sistema.mostrar_na_pasta))
        self.botao_novo = QPushButton(texto_novo)
        self.botao_novo.clicked.connect(self.novo)
        botoes = QHBoxLayout()
        botoes.addWidget(self.botao_abrir)
        botoes.addWidget(self.botao_pasta)
        botoes.addStretch()
        botoes.addWidget(self.botao_novo)

        self.rotulo_ignorados = QLabel()
        self.rotulo_ignorados.setObjectName("aviso")
        self.lista_ignorados = ListaIgnorados()
        self.botao_copiar = QPushButton("Copiar lista")
        self.botao_copiar.clicked.connect(self._copiar_ignorados)
        cabecalho_ignorados = QHBoxLayout()
        cabecalho_ignorados.addWidget(self.rotulo_ignorados, 1)
        cabecalho_ignorados.addWidget(self.botao_copiar)
        self.secao_ignorados = QWidget()
        layout_ignorados = QVBoxLayout(self.secao_ignorados)
        layout_ignorados.setContentsMargins(0, 10, 0, 0)
        layout_ignorados.addLayout(cabecalho_ignorados)
        layout_ignorados.addWidget(self.lista_ignorados)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 24, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(self.titulo)
        layout.addWidget(self.resumo)
        layout.addWidget(self.caminho)
        layout.addSpacing(6)
        layout.addLayout(botoes)
        layout.addWidget(self.secao_ignorados)
        layout.addStretch(1)

    def mostrar_sucesso(
        self,
        titulo: str,
        resumo: str,
        destino: Path,
        ignorados: list[ArquivoIgnorado],
        texto_abrir: str = "Abrir arquivo",
    ) -> None:
        self.destino = destino
        self.botao_abrir.setText(texto_abrir)
        self._preencher(titulo, "sucesso", resumo, ignorados)
        self.caminho.setText(str(destino))
        for widget in (self.caminho, self.botao_abrir, self.botao_pasta):
            widget.show()

    def mostrar_falha(self, titulo: str, mensagem: str, ignorados: list[ArquivoIgnorado]) -> None:
        self.destino = None
        self._preencher(titulo, "falha", mensagem, ignorados)
        for widget in (self.caminho, self.botao_abrir, self.botao_pasta):
            widget.hide()

    def _preencher(self, titulo: str, estado: str, resumo: str, ignorados: list[ArquivoIgnorado]) -> None:
        self.titulo.setText(titulo)
        self.titulo.setProperty("estado", estado)
        _repintar(self.titulo)
        self.resumo.setText(resumo)
        self.lista_ignorados.preencher(ignorados)
        self.rotulo_ignorados.setText(
            f"{plural(len(ignorados), 'arquivo não entrou', 'arquivos não entraram')}:"
        )
        self.secao_ignorados.setVisible(bool(ignorados))

    def _acao_sistema(self, acao) -> None:
        try:
            acao(self.destino)
        except Exception as erro:
            mostrar_erro(self, erro, "Não foi possível abrir")

    def _copiar_ignorados(self) -> None:
        QApplication.clipboard().setText(self.lista_ignorados.texto())
        self.botao_copiar.setText("Copiado!")
        # Ligado ao botão: se o painel for destruído antes, o temporizador é cancelado junto
        QTimer.singleShot(2000, self.botao_copiar, lambda: self.botao_copiar.setText("Copiar lista"))


class GrupoLateral(QWidget):
    """Grupo da barra lateral: um título clicável que mostra ou esconde as ferramentas do grupo."""

    def __init__(self, nome: str):
        super().__init__()
        self.nome = nome
        self.titulo = QPushButton()
        self.titulo.setObjectName("grupoLateral")
        self.titulo.setProperty("ativo", False)
        self.titulo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.titulo.clicked.connect(lambda: self.expandir(not self.expandido))
        self._rotulo = QLabel(nome)
        self._seta = QLabel()
        for rotulo in (self._rotulo, self._seta):
            # Os rótulos só desenham: o clique passa direto para o botão
            rotulo.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        dentro = QHBoxLayout(self.titulo)
        dentro.setContentsMargins(14, 0, 12, 0)
        dentro.addWidget(self._rotulo)
        dentro.addStretch()
        dentro.addWidget(self._seta)

        self.itens = QWidget()
        self._layout_itens = QVBoxLayout(self.itens)
        self._layout_itens.setContentsMargins(10, 0, 0, 4)
        self._layout_itens.setSpacing(2)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(self.titulo)
        layout.addWidget(self.itens)
        self.expandir(False)

    @property
    def expandido(self) -> bool:
        return not self.itens.isHidden()

    def adicionar(self, item: QWidget) -> None:
        self._layout_itens.addWidget(item)

    def expandir(self, expandir: bool) -> None:
        self.itens.setVisible(expandir)
        self._seta.setText("▾" if expandir else "▸")

    def marcar_ativo(self, ativo: bool) -> None:
        """Destaca o título quando a ferramenta aberta pertence a este grupo."""
        self.titulo.setProperty("ativo", ativo)
        _repintar(self.titulo)
