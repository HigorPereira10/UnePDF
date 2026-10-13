"""Grade de miniaturas das páginas de um PDF: reordenar arrastando, girar, remover e selecionar.

As miniaturas são desenhadas em segundo plano e vão aparecendo conforme ficam prontas;
até lá, cada página mostra um espaço vazio do mesmo tamanho.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import QModelIndex, QRect, QSize, Qt, QThread, Signal, Slot
from PySide6.QtGui import QColor, QImage, QKeyEvent, QPainter, QPen, QPixmap, QTransform
from PySide6.QtWidgets import QAbstractItemView, QListView, QListWidget, QListWidgetItem, QStyle, QStyledItemDelegate

from unepdf.core.renderizacao import DocumentoRenderizavel
from unepdf.ui.tema import CORES

log = logging.getLogger(__name__)

PAPEL_INDICE = Qt.ItemDataRole.UserRole
PAPEL_ROTACAO = Qt.ItemDataRole.UserRole + 1

LARGURA_MINIATURA = 120
ALTURA_MINIATURA = 160
ALTURA_LEGENDA = 24
MARGEM = 10


class _GeradorMiniaturas(QThread):
    pronta = Signal(int, QImage)

    def __init__(self, dados: bytes, largura: int):
        super().__init__()
        self._dados = dados
        self._largura = largura
        self._parar = False

    def parar(self) -> None:
        self._parar = True

    def run(self) -> None:
        try:
            with DocumentoRenderizavel(self._dados) as documento:
                for indice in range(documento.total):
                    if self._parar:
                        return
                    imagem = documento.renderizar(indice, largura=self._largura)
                    # copy() desvincula a imagem dos bytes, que deixam de existir ao fim do laço
                    qimagem = QImage(
                        imagem.dados, imagem.largura, imagem.altura, imagem.bytes_por_linha, QImage.Format.Format_RGB32
                    ).copy()
                    self.pronta.emit(indice, qimagem)
        except Exception:
            # Miniaturas são só visuais: uma falha aqui não pode impedir o uso da ferramenta
            log.exception("Falha ao gerar as miniaturas")


class _DesenhoMiniatura(QStyledItemDelegate):
    """Desenha cada página: a miniatura (já girada), o número e o destaque da seleção."""

    def __init__(self, grade: GradeMiniaturas):
        super().__init__(grade)
        self._grade = grade

    def sizeHint(self, opcao, indice: QModelIndex) -> QSize:
        return QSize(LARGURA_MINIATURA + 2 * MARGEM, ALTURA_MINIATURA + ALTURA_LEGENDA + 2 * MARGEM)

    def paint(self, pintor: QPainter, opcao, indice: QModelIndex) -> None:
        pintor.save()
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        celula = opcao.rect.adjusted(3, 3, -3, -3)
        selecionada = bool(opcao.state & QStyle.StateFlag.State_Selected)
        if selecionada:
            pintor.setPen(QPen(QColor(CORES.destaque), 2))
            pintor.setBrush(QColor(CORES.cartao_hover))
            pintor.drawRoundedRect(celula, 10, 10)

        caixa = QRect(celula.x() + MARGEM - 3, celula.y() + MARGEM - 3, LARGURA_MINIATURA, ALTURA_MINIATURA)
        pagina = indice.data(PAPEL_INDICE)
        rotacao = indice.data(PAPEL_ROTACAO) or 0
        imagem = self._grade.imagem(pagina, rotacao)
        if imagem is None:
            pintor.setPen(Qt.PenStyle.NoPen)
            pintor.setBrush(QColor(CORES.borda))
            pintor.drawRoundedRect(caixa.adjusted(16, 8, -16, -8), 4, 4)
        else:
            escalada = imagem.scaled(caixa.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            x = caixa.x() + (caixa.width() - escalada.width()) // 2
            y = caixa.y() + (caixa.height() - escalada.height()) // 2
            pintor.drawPixmap(x, y, escalada)

        legenda = f"Página {pagina + 1}" + (f"  ↻ {rotacao}°" if rotacao else "")
        pintor.setPen(QColor(CORES.texto if selecionada else CORES.texto_suave))
        area_legenda = QRect(celula.x(), caixa.bottom() + 4, celula.width(), ALTURA_LEGENDA)
        pintor.drawText(area_legenda, Qt.AlignmentFlag.AlignCenter, legenda)
        pintor.restore()


class GradeMiniaturas(QListWidget):
    """Miniaturas de um PDF. Cada item guarda a página original e a rotação aplicada."""

    alterado = Signal()

    def __init__(self, editavel: bool):
        super().__init__()
        self.setObjectName("gradeMiniaturas")
        self.editavel = editavel
        self._imagens: dict[int, QPixmap] = {}
        self._giradas: dict[tuple[int, int], QPixmap] = {}
        self._gerador: _GeradorMiniaturas | None = None
        # Guarda os geradores até terminarem de verdade: destruir uma QThread ativa derruba o app
        self._geradores: set[_GeradorMiniaturas] = set()
        self._total = 0

        # O modo lista com quebra de linha reordena de verdade ao arrastar (o modo ícone só
        # muda a posição na tela, sem mudar a ordem dos itens)
        self.setViewMode(QListView.ViewMode.ListMode)
        self.setFlow(QListView.Flow.LeftToRight)
        self.setWrapping(True)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setUniformItemSizes(True)
        self.setSpacing(4)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setItemDelegate(_DesenhoMiniatura(self))
        if editavel:
            self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
            self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.model().rowsMoved.connect(self.alterado)

    def carregar(self, dados: bytes, total: int) -> None:
        """Mostra as páginas do PDF e começa a desenhar as miniaturas em segundo plano."""
        self.parar()
        self._imagens.clear()
        self._giradas.clear()
        self._total = total
        self._preencher_itens()

        largura = round(LARGURA_MINIATURA * max(1.0, self.devicePixelRatioF()))
        self._gerador = _GeradorMiniaturas(dados, largura)
        self._gerador.pronta.connect(self._ao_ficar_pronta)
        self._gerador.finished.connect(self._ao_terminar_gerador)
        self._geradores.add(self._gerador)
        self._gerador.start()

    def parar(self, aguardar: bool = False) -> None:
        """Interrompe a geração de miniaturas (ex.: ao trocar de arquivo ou fechar o app)."""
        for gerador in list(self._geradores):
            gerador.parar()
            if aguardar:
                gerador.wait()
        self._gerador = None

    @Slot(int, QImage)
    def _ao_ficar_pronta(self, indice: int, imagem: QImage) -> None:
        if self.sender() is not self._gerador:  # sobra de um arquivo anterior
            return
        self._imagens[indice] = QPixmap.fromImage(imagem)
        self.viewport().update()

    @Slot()
    def _ao_terminar_gerador(self) -> None:
        gerador = self.sender()
        gerador.wait()
        self._geradores.discard(gerador)
        gerador.deleteLater()

    def imagem(self, indice: int, rotacao: int) -> QPixmap | None:
        base = self._imagens.get(indice)
        if base is None or not rotacao:
            return base
        if (indice, rotacao) not in self._giradas:
            self._giradas[(indice, rotacao)] = base.transformed(QTransform().rotate(rotacao))
        return self._giradas[(indice, rotacao)]

    # Leitura do estado

    def itens(self) -> list[QListWidgetItem]:
        return [self.item(linha) for linha in range(self.count())]

    def plano(self) -> list[tuple[int, int]]:
        """Páginas na ordem atual, com a rotação de cada uma, no formato do core."""
        return [(item.data(PAPEL_INDICE), item.data(PAPEL_ROTACAO)) for item in self.itens()]

    def foi_alterada(self) -> bool:
        return self.plano() != [(indice, 0) for indice in range(self._total)]

    def indices_selecionados(self) -> list[int]:
        """Páginas selecionadas (numeração original a partir de 0), em ordem crescente."""
        return sorted(item.data(PAPEL_INDICE) for item in self.selectedItems())

    def selecionar_indices(self, indices: list[int]) -> None:
        alvo = set(indices)
        self.blockSignals(True)
        for item in self.itens():
            item.setSelected(item.data(PAPEL_INDICE) in alvo)
        self.blockSignals(False)
        self.viewport().update()

    # Edição

    def girar_selecionadas(self, graus: int) -> None:
        for item in self.selectedItems():
            item.setData(PAPEL_ROTACAO, (item.data(PAPEL_ROTACAO) + graus) % 360)
        self.alterado.emit()

    def remover_selecionadas(self) -> None:
        for item in self.selectedItems():
            self.takeItem(self.row(item))
        self.alterado.emit()

    def mover_selecionadas(self, deslocamento: int) -> None:
        """Move as páginas selecionadas uma posição para trás (-1) ou para frente (+1)."""
        linhas = sorted(self.row(i) for i in self.selectedItems())
        if not linhas or (deslocamento < 0 and linhas[0] == 0) or (deslocamento > 0 and linhas[-1] == self.count() - 1):
            return
        for linha in (linhas if deslocamento < 0 else reversed(linhas)):
            item = self.takeItem(linha)
            self.insertItem(linha + deslocamento, item)
            item.setSelected(True)
        self.alterado.emit()

    def restaurar(self) -> None:
        """Volta à ordem original, sem rotações e com todas as páginas."""
        self._preencher_itens()
        self.alterado.emit()

    def _preencher_itens(self) -> None:
        self.clear()
        for indice in range(self._total):
            item = QListWidgetItem()
            item.setData(PAPEL_INDICE, indice)
            item.setData(PAPEL_ROTACAO, 0)
            self.addItem(item)

    def keyPressEvent(self, evento: QKeyEvent) -> None:
        # Alternativas de teclado ao mouse: Delete remove, Ctrl+setas move as páginas
        if self.editavel and evento.key() == Qt.Key.Key_Delete:
            self.remover_selecionadas()
        elif self.editavel and evento.modifiers() & Qt.KeyboardModifier.ControlModifier and evento.key() in (
            Qt.Key.Key_Left, Qt.Key.Key_Right
        ):
            self.mover_selecionadas(-1 if evento.key() == Qt.Key.Key_Left else 1)
        else:
            super().keyPressEvent(evento)
