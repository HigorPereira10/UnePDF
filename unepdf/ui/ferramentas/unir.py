"""Ferramenta Unir PDFs: escolha por pasta ou arquivos, progresso, resumo e arquivos ignorados."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QKeyEvent, QShowEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from unepdf.core.erros import ErroUnePDF, OperacaoCancelada
from unepdf.core.localizador import (
    OrdemArquivos,
    Selecao,
    SoEmSubpastas,
    datas_modificacao,
    montar_selecao,
    ordenar,
)
from unepdf.core.modelos import Resultado
from unepdf.core.nomenclatura import destino_padrao
from unepdf.core.unir import unir
from unepdf.ui.componentes import AreaSoltar, PainelProgresso, PainelResultado
from unepdf.ui.contexto import ContextoApp
from unepdf.ui.dialogos import mostrar_erro
from unepdf.ui.ferramentas.base import TelaFerramenta
from unepdf.utils.texto import plural

if TYPE_CHECKING:
    from unepdf.ui.ferramentas import Ferramenta

# Tempo antes de mostrar o "Lendo a pasta...": em pastas locais a leitura é quase instantânea
# e a troca rápida de tela só piscaria
ATRASO_PROGRESSO_MS = 300


ORDEM_MANUAL = "manual"


@dataclass
class _Preparo:
    selecao: Selecao
    destino: Path
    destino_existe: bool
    datas: dict[Path, float]


class OpcoesUniao(QWidget):
    """Ordem dos arquivos, arquivos repetidos e capa. As escolhas ficam salvas para a próxima vez."""

    alterado = Signal()

    def __init__(self, contexto: ContextoApp, com_manual: bool):
        super().__init__()
        self.contexto = contexto
        config = contexto.config

        self.combo_ordem = QComboBox()
        self.combo_ordem.addItem("Nome do arquivo", OrdemArquivos.NOME)
        self.combo_ordem.addItem("Data de modificação (mais antigo primeiro)", OrdemArquivos.DATA)
        if com_manual:
            self.combo_ordem.addItem("Manual (arraste na lista)", ORDEM_MANUAL)
        self.combo_ordem.setCurrentIndex(self.combo_ordem.findData(config.unir_ordem))
        self.combo_ordem.currentIndexChanged.connect(self._ao_mudar)

        self.check_repetidos = QCheckBox("Pular arquivos repetidos (mesmo conteúdo, ainda que com outro nome)")
        self.check_repetidos.setChecked(config.unir_pular_repetidos)
        self.check_repetidos.toggled.connect(self._ao_mudar)
        self.check_capa = QCheckBox("Começar com uma capa que lista os arquivos e a página de cada um")
        self.check_capa.setChecked(config.unir_capa)
        self.check_capa.toggled.connect(self._ao_mudar)

        linha_ordem = QHBoxLayout()
        linha_ordem.addWidget(QLabel("Ordem:"))
        linha_ordem.addWidget(self.combo_ordem)
        linha_ordem.addStretch()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addLayout(linha_ordem)
        layout.addWidget(self.check_repetidos)
        layout.addWidget(self.check_capa)

    @property
    def ordem(self) -> OrdemArquivos | None:
        """Ordem escolhida, ou None quando é a ordem manual da lista."""
        dado = self.combo_ordem.currentData()
        return None if dado == ORDEM_MANUAL else OrdemArquivos(dado)

    @property
    def pular_repetidos(self) -> bool:
        return self.check_repetidos.isChecked()

    @property
    def capa(self) -> bool:
        return self.check_capa.isChecked()

    def usar_ordem_manual(self) -> None:
        self.combo_ordem.setCurrentIndex(self.combo_ordem.findData(ORDEM_MANUAL))

    def _ao_mudar(self) -> None:
        config = self.contexto.config
        # A ordem manual vale só para a seleção atual; a salva continua sendo a última automática
        novo = (self.ordem or config.unir_ordem, self.pular_repetidos, self.capa)
        if novo != (config.unir_ordem, config.unir_pular_repetidos, config.unir_capa):
            config.unir_ordem, config.unir_pular_repetidos, config.unir_capa = novo
            self.contexto.salvar_config()
        self.alterado.emit()


class ListaArquivos(QListWidget):
    """Lista da seleção: reordena arrastando e remove com a tecla Delete."""

    removidos = Signal()

    def __init__(self):
        super().__init__()
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)

    def preencher(self, arquivos: list[Path]) -> None:
        self.clear()
        for caminho in arquivos:
            item = QListWidgetItem(caminho.name)
            item.setData(Qt.ItemDataRole.UserRole, caminho)
            item.setToolTip(str(caminho))
            self.addItem(item)

    def arquivos(self) -> list[Path]:
        return [self.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.count())]

    def remover_selecionados(self) -> None:
        for item in self.selectedItems():
            self.takeItem(self.row(item))
        self.removidos.emit()

    def keyPressEvent(self, evento: QKeyEvent) -> None:
        if evento.key() == Qt.Key.Key_Delete and self.selectedItems():
            self.remover_selecionados()
        else:
            super().keyPressEvent(evento)


class TelaUnir(TelaFerramenta):
    aceita_arquivos = True

    def __init__(self, ferramenta: Ferramenta, contexto: ContextoApp):
        super().__init__(ferramenta, contexto)
        self._preparo: _Preparo | None = None
        self._ultimos_caminhos: list[Path] = []
        self._config_usada: tuple = ()

        self.area = AreaSoltar(
            "Arraste PDFs ou uma pasta para cá",
            "Cada arquivo começa em uma página nova e vira um marcador no PDF final.",
        )
        self.area.caminhos_soltos.connect(self.receber_caminhos)
        self.area.escolher_pasta.connect(self._escolher_pasta)
        self.area.escolher_arquivos.connect(self._escolher_arquivos)

        self.progresso = PainelProgresso()
        self.progresso.cancelar.connect(self.executor.cancelar)
        self.resultado = PainelResultado("Unir outros arquivos")
        self.resultado.novo.connect(self.limpar)

        self.estados = QStackedWidget()
        for painel in (self.area, self._montar_painel_selecao(), self.progresso, self.resultado):
            self.estados.addWidget(painel)
        self.corpo.addWidget(self.estados)

        self._timer_progresso = QTimer(self)
        self._timer_progresso.setSingleShot(True)
        self._timer_progresso.timeout.connect(lambda: self.estados.setCurrentWidget(self.progresso))

        self.executor.progresso.connect(self.progresso.atualizar)

    def _montar_painel_selecao(self) -> QWidget:
        self.resumo_selecao = QLabel()
        self.resumo_selecao.setObjectName("tituloResultado")
        self.origem_selecao = QLabel()
        self.origem_selecao.setObjectName("subtitulo")
        self.origem_selecao.setWordWrap(True)
        trocar = QPushButton("Trocar seleção")
        trocar.clicked.connect(self.limpar)

        textos = QVBoxLayout()
        textos.setSpacing(2)
        textos.addWidget(self.resumo_selecao)
        textos.addWidget(self.origem_selecao)
        cabecalho = QHBoxLayout()
        cabecalho.addLayout(textos, 1)
        cabecalho.addWidget(trocar)

        self.lista_arquivos = ListaArquivos()
        self.opcoes = OpcoesUniao(self.contexto, com_manual=True)
        self.opcoes.alterado.connect(self._reordenar)
        # Arrastar um arquivo na lista passa a ordem para manual
        self.lista_arquivos.model().rowsMoved.connect(lambda *_: self.opcoes.usar_ordem_manual())
        self.lista_arquivos.removidos.connect(self._atualizar_contagem)
        self.botao_remover = QPushButton("Remover da lista")
        self.botao_remover.setEnabled(False)
        self.botao_remover.clicked.connect(self.lista_arquivos.remover_selecionados)
        self.lista_arquivos.itemSelectionChanged.connect(
            lambda: self.botao_remover.setEnabled(bool(self.lista_arquivos.selectedItems()))
        )
        linha_opcoes = QHBoxLayout()
        linha_opcoes.addWidget(self.opcoes, 1)
        linha_opcoes.addWidget(self.botao_remover, 0, Qt.AlignmentFlag.AlignTop)

        rotulo_destino = QLabel("SERÁ SALVO EM")
        rotulo_destino.setObjectName("rotuloCampo")
        self.destino_selecao = QLabel()
        self.destino_selecao.setWordWrap(True)
        self.aviso_selecao = QLabel()
        self.aviso_selecao.setObjectName("aviso")
        self.aviso_selecao.setWordWrap(True)

        self.botao_unir = QPushButton("Unir PDFs")
        self.botao_unir.setObjectName("botaoPrincipal")
        self.botao_unir.clicked.connect(self._unir)
        rodape = QHBoxLayout()
        rodape.addWidget(self.aviso_selecao, 1)
        rodape.addWidget(self.botao_unir)

        painel = QWidget()
        layout = QVBoxLayout(painel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addLayout(cabecalho)
        layout.addWidget(self.lista_arquivos, 1)
        layout.addLayout(linha_opcoes)
        layout.addSpacing(4)
        layout.addWidget(rotulo_destino)
        layout.addWidget(self.destino_selecao)
        layout.addSpacing(4)
        layout.addLayout(rodape)
        self.painel_selecao = painel
        return painel

    # Escolha dos arquivos

    def _pasta_para_dialogo(self) -> str:
        """Abre os diálogos na última pasta usada; sem ela, na pasta inicial das configurações."""
        for candidata in (self.contexto.config.ultima_pasta, self.contexto.config.pasta_inicial):
            if candidata and Path(candidata).is_dir():
                return candidata
        return ""

    def _escolher_pasta(self) -> None:
        pasta = QFileDialog.getExistingDirectory(self, "Escolha a pasta com os PDFs", self._pasta_para_dialogo())
        if pasta:
            self.receber_caminhos([Path(pasta)])

    def _escolher_arquivos(self) -> None:
        arquivos, _ = QFileDialog.getOpenFileNames(
            self, "Escolha os PDFs", self._pasta_para_dialogo(), "Arquivos PDF (*.pdf)"
        )
        if arquivos:
            self.receber_caminhos([Path(a) for a in arquivos])

    def receber_caminhos(self, caminhos: list[Path]) -> None:
        if self.executor.em_execucao:
            return
        self.area.mostrar_aviso(None)
        perfil = self.contexto.config.perfil_nomenclatura
        pasta_saida = self.contexto.config.pasta_saida
        self._ultimos_caminhos = caminhos
        self._config_usada = (perfil, pasta_saida)

        # Roda em segundo plano porque listar uma pasta de rede grande pode demorar
        def preparar(progresso, cancelamento) -> _Preparo:
            selecao = montar_selecao(caminhos, pasta_saida)
            destino = destino_padrao(selecao.base, perfil, pasta_saida)
            # As datas já ficam prontas para a ordem por data, sem consultar a rede de novo depois
            return _Preparo(selecao, destino, destino.exists(), datas_modificacao(selecao.arquivos))

        self.progresso.iniciar("Lendo os arquivos...", cancelavel=False)
        self._timer_progresso.start(ATRASO_PROGRESSO_MS)
        self.executar(preparar, self._ao_preparar, self._ao_falhar_preparo)

    def _ao_preparar(self, preparo: _Preparo) -> None:
        self._timer_progresso.stop()
        self._lembrar_pasta(preparo.selecao.base)
        self._mostrar_selecao(preparo)

    def _ao_falhar_preparo(self, erro: BaseException) -> None:
        self._timer_progresso.stop()
        self.estados.setCurrentWidget(self.area)
        if isinstance(erro, SoEmSubpastas):
            # Ex.: notas já separadas em emitidas e recebidas. O Unir em lote gera um unificado para cada subpasta
            self.abrir_ferramenta.emit("unir_lote", [erro.pasta])
        elif isinstance(erro, ErroUnePDF):
            self.area.mostrar_aviso(str(erro))
        else:
            mostrar_erro(self, erro)

    def _mostrar_selecao(self, preparo: _Preparo, aviso: str = "", manter_lista: bool = False) -> None:
        self._preparo = preparo
        selecao = preparo.selecao
        if selecao.pasta:
            self.origem_selecao.setText(f"Da pasta {selecao.pasta}")
        else:
            self.origem_selecao.setText(f"Arquivos escolhidos em {selecao.base}")
        if not manter_lista:
            ordem = self.opcoes.ordem or self.contexto.config.unir_ordem
            self.lista_arquivos.preencher(ordenar(selecao.arquivos, ordem, preparo.datas))
        self._atualizar_contagem()
        self.destino_selecao.setText(str(preparo.destino))

        avisos = [aviso] if aviso else []
        if selecao.descartados:
            avisos.append(
                f"{plural(selecao.descartados, 'item ficou', 'itens ficaram')} de fora: "
                "não são PDF, estão repetidos ou estão na pasta de saída."
            )
        if preparo.destino_existe:
            avisos.append("Já existe um arquivo com esse nome. Ele será substituído.")
        self.aviso_selecao.setText("\n".join(avisos))
        self.estados.setCurrentWidget(self.painel_selecao)

    def _reordenar(self) -> None:
        ordem = self.opcoes.ordem
        if self._preparo and ordem is not None:
            self.lista_arquivos.preencher(ordenar(self.lista_arquivos.arquivos(), ordem, self._preparo.datas))

    def _atualizar_contagem(self) -> None:
        quantidade = self.lista_arquivos.count()
        self.resumo_selecao.setText(plural(quantidade, "PDF selecionado", "PDFs selecionados"))
        self.botao_unir.setEnabled(quantidade > 0)

    def showEvent(self, evento: QShowEvent) -> None:
        super().showEvent(evento)
        # Se o perfil ou a subpasta de saída mudaram nas configurações, o destino mostrado ficou velho
        config = self.contexto.config
        mudou = self._config_usada != (config.perfil_nomenclatura, config.pasta_saida)
        if mudou and self.estados.currentWidget() is self.painel_selecao and not self.executor.em_execucao:
            self.receber_caminhos(self._ultimos_caminhos)

    def limpar(self) -> None:
        self._preparo = None
        self.area.mostrar_aviso(None)
        self.estados.setCurrentWidget(self.area)

    # União

    def _unir(self) -> None:
        if not self._preparo or self.executor.em_execucao:
            return
        arquivos, destino = self.lista_arquivos.arquivos(), self._preparo.destino
        if not arquivos:
            return
        pular_repetidos, capa = self.opcoes.pular_repetidos, self.opcoes.capa
        self.progresso.iniciar("Unindo PDFs...")
        self.estados.setCurrentWidget(self.progresso)
        self.executar(
            lambda progresso, cancelamento: unir(
                arquivos, destino, progresso, cancelamento, pular_repetidos=pular_repetidos, capa=capa
            ),
            self._ao_unir,
            self._ao_falhar_uniao,
        )

    def _ao_unir(self, resultado: Resultado) -> None:
        resumo = (
            f"{plural(resultado.arquivos, 'arquivo unido', 'arquivos unidos')} em "
            f"{plural(resultado.paginas, 'página', 'páginas')}."
        )
        if resultado.substituiu_anterior:
            resumo += " O arquivo anterior com o mesmo nome foi substituído."
        if resultado.observacao:
            resumo += f" {resultado.observacao}"
        self.resultado.mostrar_sucesso("PDF criado!", resumo, resultado.destino, resultado.ignorados)
        self.estados.setCurrentWidget(self.resultado)

    def _ao_falhar_uniao(self, erro: BaseException) -> None:
        if isinstance(erro, OperacaoCancelada):
            self._voltar_para_selecao(str(erro))
        elif isinstance(erro, ErroUnePDF) and erro.ignorados:
            self.resultado.mostrar_falha("Nenhum PDF foi unido", str(erro), erro.ignorados)
            self.estados.setCurrentWidget(self.resultado)
        else:
            self._voltar_para_selecao()
            mostrar_erro(self, erro)

    def _voltar_para_selecao(self, aviso: str = "") -> None:
        if self._preparo:
            # A lista mantém a ordem e as remoções que o usuário já fez
            self._mostrar_selecao(self._preparo, aviso, manter_lista=True)
        else:
            self.limpar()
            self.area.mostrar_aviso(aviso)

    def _lembrar_pasta(self, pasta: Path) -> None:
        if self.contexto.config.ultima_pasta != str(pasta):
            self.contexto.config.ultima_pasta = str(pasta)
            self.contexto.salvar_config()
