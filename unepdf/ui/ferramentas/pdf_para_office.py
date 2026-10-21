"""Ferramentas PDF para Word e PDF para Excel, em lote."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import (
    QCheckBox,
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

from unepdf.core import pdf_office
from unepdf.core.erros import ErroUnePDF
from unepdf.core.localizador import Selecao, montar_selecao
from unepdf.ui.componentes import AreaSoltar, PainelProgresso, PainelResultado
from unepdf.ui.contexto import ContextoApp
from unepdf.ui.dialogos import mostrar_erro
from unepdf.ui.ferramentas.arquivo_unico import ATRASO_PROGRESSO_MS
from unepdf.ui.ferramentas.base import TelaFerramenta
from unepdf.utils.texto import plural

if TYPE_CHECKING:
    from unepdf.ui.ferramentas import Ferramenta


def _ajuda(texto: str = "") -> QLabel:
    rotulo = QLabel(texto)
    rotulo.setObjectName("subtitulo")
    rotulo.setWordWrap(True)
    return rotulo


class _TelaPdfParaOffice(TelaFerramenta):
    """Base das duas ferramentas: escolhe os PDFs, mostra a lista e converte um arquivo por PDF."""

    aceita_arquivos = True
    extensao = ""
    nome_formato = ""
    explicacao = ""

    def __init__(self, ferramenta: Ferramenta, contexto: ContextoApp):
        super().__init__(ferramenta, contexto)
        self._selecao: Selecao | None = None
        self._aviso_era_indisponivel = False

        self.area = AreaSoltar("Arraste PDFs ou uma pasta para cá", self.explicacao)
        self.area.caminhos_soltos.connect(self.receber_caminhos)
        self.area.escolher_pasta.connect(self._escolher_pasta)
        self.area.escolher_arquivos.connect(self._escolher_arquivos)
        self.progresso = PainelProgresso()
        self.progresso.cancelar.connect(self.executor.cancelar)
        self.executor.progresso.connect(self.progresso.atualizar)
        self.resultado = PainelResultado("Converter outros PDFs")
        self.resultado.novo.connect(self.limpar)

        self.estados = QStackedWidget()
        for painel in (self.area, self._montar_painel_selecao(), self.progresso, self.resultado):
            self.estados.addWidget(painel)
        self.corpo.addWidget(self.estados)

        self._timer_progresso = QTimer(self)
        self._timer_progresso.setSingleShot(True)
        self._timer_progresso.timeout.connect(lambda: self.estados.setCurrentWidget(self.progresso))

    def _montar_opcoes(self, layout: QVBoxLayout) -> None:
        """Opções próprias de cada ferramenta, abaixo da lista."""

    def _montar_painel_selecao(self) -> QWidget:
        self.resumo_selecao = QLabel()
        self.resumo_selecao.setObjectName("tituloResultado")
        self.origem_selecao = _ajuda()
        trocar = QPushButton("Trocar seleção")
        trocar.clicked.connect(self.limpar)
        textos = QVBoxLayout()
        textos.setSpacing(2)
        textos.addWidget(self.resumo_selecao)
        textos.addWidget(self.origem_selecao)
        cabecalho = QHBoxLayout()
        cabecalho.addLayout(textos, 1)
        cabecalho.addWidget(trocar)

        self.lista = QListWidget()
        self.lista.setSelectionMode(QListWidget.SelectionMode.NoSelection)

        rotulo_destino = QLabel("SERÁ SALVO EM")
        rotulo_destino.setObjectName("rotuloCampo")
        self.destino_selecao = QLabel()
        self.destino_selecao.setWordWrap(True)
        self.aviso_selecao = QLabel()
        self.aviso_selecao.setObjectName("aviso")
        self.aviso_selecao.setWordWrap(True)
        self.botao_converter = QPushButton("Converter")
        self.botao_converter.setObjectName("botaoPrincipal")
        self.botao_converter.clicked.connect(self._converter)
        rodape = QHBoxLayout()
        rodape.addWidget(self.aviso_selecao, 1)
        rodape.addWidget(self.botao_converter)

        painel = QWidget()
        layout = QVBoxLayout(painel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addLayout(cabecalho)
        layout.addWidget(self.lista, 1)
        self._montar_opcoes(layout)
        layout.addSpacing(4)
        layout.addWidget(rotulo_destino)
        layout.addWidget(self.destino_selecao)
        layout.addLayout(rodape)
        self.painel_selecao = painel
        return painel

    # Disponibilidade

    def _verificar_disponibilidade(self) -> str | None:
        motivo = self.ferramenta.motivo_indisponivel()
        self.area.botao_arquivos.setEnabled(motivo is None)
        self.area.botao_pasta.setEnabled(motivo is None)
        if motivo:
            self.limpar()
            self.area.mostrar_aviso(motivo)
        elif self.estados.currentWidget() is self.area and self._aviso_era_indisponivel:
            self.area.mostrar_aviso(None)
        self._aviso_era_indisponivel = motivo is not None
        return motivo

    def showEvent(self, evento: QShowEvent) -> None:
        super().showEvent(evento)
        self._verificar_disponibilidade()

    # Escolha dos arquivos

    def _pasta_para_dialogo(self) -> str:
        for candidata in (self.contexto.config.ultima_pasta, self.contexto.config.pasta_inicial):
            if candidata and Path(candidata).is_dir():
                return candidata
        return ""

    def _escolher_pasta(self) -> None:
        pasta = QFileDialog.getExistingDirectory(self, "Escolha a pasta com os PDFs", self._pasta_para_dialogo())
        if pasta:
            self.receber_caminhos([Path(pasta)])

    def _escolher_arquivos(self) -> None:
        arquivos, _ = QFileDialog.getOpenFileNames(self, "Escolha os PDFs", self._pasta_para_dialogo(), "PDF (*.pdf)")
        if arquivos:
            self.receber_caminhos([Path(a) for a in arquivos])

    def receber_caminhos(self, caminhos: list[Path]) -> None:
        if self.executor.em_execucao or self._verificar_disponibilidade():
            return
        self.area.mostrar_aviso(None)
        pasta_saida = self.contexto.config.pasta_saida
        self.progresso.iniciar("Lendo os arquivos...", cancelavel=False)
        self._timer_progresso.start(ATRASO_PROGRESSO_MS)
        self.executar(
            lambda progresso, cancelamento: montar_selecao(caminhos, pasta_saida),
            self._mostrar_selecao,
            self._ao_falhar_preparo,
        )

    def _ao_falhar_preparo(self, erro: BaseException) -> None:
        self._timer_progresso.stop()
        self.limpar()
        if isinstance(erro, ErroUnePDF):
            self.area.mostrar_aviso(str(erro))
        else:
            mostrar_erro(self, erro)

    def _mostrar_selecao(self, selecao: Selecao) -> None:
        self._timer_progresso.stop()
        self._selecao = selecao
        if self.contexto.config.ultima_pasta != str(selecao.base):
            self.contexto.config.ultima_pasta = str(selecao.base)
            self.contexto.salvar_config()
        self.resumo_selecao.setText(plural(len(selecao.arquivos), "PDF selecionado", "PDFs selecionados"))
        self.origem_selecao.setText(f"Da pasta {selecao.pasta}" if selecao.pasta else f"Arquivos de {selecao.base}")
        self.lista.clear()
        for caminho in selecao.arquivos:
            item = QListWidgetItem(f"{caminho.name}  >  {caminho.stem}{self.extensao}")
            item.setToolTip(str(caminho))
            self.lista.addItem(item)
        self.aviso_selecao.setText(
            f"{plural(selecao.descartados, 'item ficou', 'itens ficaram')} de fora: "
            "não são PDFs ou estão na pasta de saída." if selecao.descartados else ""
        )
        self.destino_selecao.setText(str(self._pasta_destino()))
        self.botao_converter.setText("Converter " + plural(len(selecao.arquivos), "PDF", "PDFs"))
        self.estados.setCurrentWidget(self.painel_selecao)

    def _pasta_destino(self) -> Path:
        return self._selecao.base / self.contexto.config.pasta_saida

    def limpar(self) -> None:
        self._selecao = None
        self.area.mostrar_aviso(None)
        self.estados.setCurrentWidget(self.area)

    # Conversão

    def _tarefa(self, arquivos: list[Path], pasta: Path):
        raise NotImplementedError

    def _converter(self) -> None:
        if not self._selecao or self.executor.em_execucao:
            return
        tarefa = self._tarefa(list(self._selecao.arquivos), self._pasta_destino())
        self.progresso.iniciar(f"Convertendo para {self.nome_formato}...")
        self.estados.setCurrentWidget(self.progresso)
        self.executar(tarefa, self._ao_converter, self._ao_falhar_conversao)

    def _observacao(self, resultado: pdf_office.ResultadoConversao) -> str:
        return ""

    def _ao_converter(self, resultado: pdf_office.ResultadoConversao) -> None:
        partes = [plural(len(resultado.gerados), "arquivo gerado", "arquivos gerados") + "."]
        if resultado.substituidos:
            partes.append(plural(
                resultado.substituidos,
                "substituiu um arquivo anterior com o mesmo nome.",
                "substituíram arquivos anteriores com o mesmo nome.",
            ))
        observacao = self._observacao(resultado)
        if observacao:
            partes.append(observacao)
        if resultado.cancelado:
            titulo = "Conversão interrompida"
            partes.append(f"{plural(resultado.pendentes, 'PDF ficou', 'PDFs ficaram')} sem converter.")
        else:
            titulo = f"Arquivos do {self.nome_formato} criados!"
        if len(resultado.gerados) == 1:
            destino, texto_abrir = resultado.gerados[0], "Abrir arquivo"
        else:
            destino, texto_abrir = resultado.pasta, "Abrir pasta"
        self.resultado.mostrar_sucesso(titulo, " ".join(partes), destino, resultado.ignorados, texto_abrir)
        self.estados.setCurrentWidget(self.resultado)

    def _ao_falhar_conversao(self, erro: BaseException) -> None:
        if isinstance(erro, ErroUnePDF) and erro.ignorados:
            self.resultado.mostrar_falha("Nenhum arquivo foi gerado", str(erro), erro.ignorados)
            self.estados.setCurrentWidget(self.resultado)
            return
        self.estados.setCurrentWidget(self.painel_selecao)
        mostrar_erro(self, erro)


class TelaPdfParaWord(_TelaPdfParaOffice):
    extensao = ".docx"
    nome_formato = "Word"
    explicacao = "Usa o Word instalado. Fica melhor em documentos de texto, como contratos e procurações."

    def _montar_opcoes(self, layout: QVBoxLayout) -> None:
        layout.addWidget(_ajuda(
            "O texto fica editável. Layouts com várias colunas, tabelas complexas e muitos gráficos podem "
            "mudar um pouco. PDFs escaneados precisam passar pelo OCR antes."
        ))

    def _tarefa(self, arquivos: list[Path], pasta: Path):
        return lambda progresso, cancelamento: pdf_office.pdf_para_word(arquivos, pasta, progresso, cancelamento)


class TelaPdfParaExcel(_TelaPdfParaOffice):
    extensao = ".xlsx"
    nome_formato = "Excel"
    explicacao = "As tabelas de cada página viram planilha. Fica melhor em relatórios e extratos gerados por sistema."

    def _montar_opcoes(self, layout: QVBoxLayout) -> None:
        self.check_uma_aba = QCheckBox("Todas as tabelas em uma aba só (bom para relatórios que continuam de uma página para outra)")
        self.check_uma_aba.setChecked(self.contexto.config.excel_uma_aba)
        self.check_uma_aba.toggled.connect(self._salvar_opcao)
        layout.addWidget(self.check_uma_aba)
        layout.addWidget(_ajuda(
            'Valores como "1.234,56" viram números, prontos para somar. Códigos com zero à esquerda, CNPJ e '
            "datas continuam como texto. PDFs escaneados precisam passar pelo OCR antes."
        ))

    def _salvar_opcao(self, marcado: bool) -> None:
        if self.contexto.config.excel_uma_aba != marcado:
            self.contexto.config.excel_uma_aba = marcado
            self.contexto.salvar_config()

    def _tarefa(self, arquivos: list[Path], pasta: Path):
        uma_aba = self.check_uma_aba.isChecked()
        return lambda progresso, cancelamento: pdf_office.pdf_para_excel(arquivos, pasta, uma_aba, progresso, cancelamento)

    def _observacao(self, resultado: pdf_office.ResultadoConversao) -> str:
        if not resultado.paginas_sem_tabela:
            return ""
        return plural(resultado.paginas_sem_tabela, "página não tinha tabela e ficou de fora.", "páginas não tinham tabela e ficaram de fora.")
