"""Ferramenta Office para PDF: documentos do Word, Excel e PowerPoint em lote."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer
from PySide6.QtGui import QBrush, QColor, QShowEvent
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

from unepdf.core import ghostscript, office
from unepdf.core.erros import ErroUnePDF
from unepdf.core.localizador import Selecao, montar_selecao
from unepdf.core.nomenclatura import nome_saida
from unepdf.ui.componentes import AreaSoltar, PainelProgresso, PainelResultado
from unepdf.ui.contexto import ContextoApp
from unepdf.ui.dialogos import mostrar_erro
from unepdf.ui.ferramentas.arquivo_unico import ATRASO_PROGRESSO_MS
from unepdf.ui.ferramentas.base import TelaFerramenta
from unepdf.ui.tema import CORES
from unepdf.utils.texto import plural

if TYPE_CHECKING:
    from unepdf.ui.ferramentas import Ferramenta


@dataclass
class _Preparo:
    selecao: Selecao
    preparo: office.Preparo


def _ajuda(texto: str = "") -> QLabel:
    rotulo = QLabel(texto)
    rotulo.setObjectName("subtitulo")
    rotulo.setWordWrap(True)
    return rotulo


class TelaOfficeParaPdf(TelaFerramenta):
    aceita_arquivos = True

    def __init__(self, ferramenta: Ferramenta, contexto: ContextoApp):
        super().__init__(ferramenta, contexto)
        self._preparo: _Preparo | None = None
        self._aviso_era_indisponivel = False

        self.area = AreaSoltar(
            "Arraste documentos ou uma pasta para cá",
            "Word, Excel e PowerPoint (também RTF, CSV e os formatos do LibreOffice).",
            texto_arquivos="Escolher documentos",
        )
        self.area.caminhos_soltos.connect(self.receber_caminhos)
        self.area.escolher_pasta.connect(self._escolher_pasta)
        self.area.escolher_arquivos.connect(self._escolher_arquivos)
        self.progresso = PainelProgresso()
        self.progresso.cancelar.connect(self.executor.cancelar)
        self.executor.progresso.connect(self.progresso.atualizar)
        self.resultado = PainelResultado("Converter outros documentos")
        self.resultado.novo.connect(self.limpar)

        self.estados = QStackedWidget()
        for painel in (self.area, self._montar_painel_selecao(), self.progresso, self.resultado):
            self.estados.addWidget(painel)
        self.corpo.addWidget(self.estados)

        self._timer_progresso = QTimer(self)
        self._timer_progresso.setSingleShot(True)
        self._timer_progresso.timeout.connect(lambda: self.estados.setCurrentWidget(self.progresso))

    def _montar_painel_selecao(self) -> QWidget:
        self.resumo_selecao = QLabel()
        self.resumo_selecao.setObjectName("tituloResultado")
        self.tipos_selecao = _ajuda()
        self.origem_selecao = _ajuda()
        trocar = QPushButton("Trocar seleção")
        trocar.clicked.connect(self.limpar)
        textos = QVBoxLayout()
        textos.setSpacing(2)
        for rotulo in (self.resumo_selecao, self.tipos_selecao, self.origem_selecao):
            textos.addWidget(rotulo)
        cabecalho = QHBoxLayout()
        cabecalho.addLayout(textos, 1)
        cabecalho.addWidget(trocar)

        self.lista = QListWidget()
        self.lista.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.motor_selecao = _ajuda()

        config = self.contexto.config
        self.check_pdfa = QCheckBox("Salvar em PDF/A-2b, o formato de arquivamento de longo prazo")
        self.check_pdfa.setChecked(config.office_pdfa)
        self.check_pdfa.toggled.connect(self._salvar_opcoes)
        self.ajuda_pdfa = _ajuda()
        self.check_juntar = QCheckBox("Também juntar tudo em um PDF, com um marcador por documento")
        self.check_juntar.setChecked(config.office_juntar)
        self.check_juntar.toggled.connect(self._salvar_opcoes)

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
        layout.addWidget(self.motor_selecao)
        layout.addWidget(self.check_pdfa)
        layout.addWidget(self.ajuda_pdfa)
        layout.addWidget(self.check_juntar)
        layout.addSpacing(4)
        layout.addWidget(rotulo_destino)
        layout.addWidget(self.destino_selecao)
        layout.addLayout(rodape)
        self.painel_selecao = painel
        return painel

    # Disponibilidade

    def _verificar_disponibilidade(self) -> str | None:
        """Sem Office nem LibreOffice, explica o que falta e bloqueia a escolha de arquivos."""
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
        if self.estados.currentWidget() is self.painel_selecao:
            self._ajustar_pdfa()

    def _ajustar_pdfa(self) -> None:
        motivo = ghostscript.disponivel()
        self.check_pdfa.setEnabled(motivo is None)
        if motivo:
            self.check_pdfa.setChecked(False)
            self.ajuda_pdfa.setText("O PDF/A precisa do Ghostscript, que é gratuito (ghostscript.com).")
        else:
            self.ajuda_pdfa.setText("Fontes e cores ficam dentro do arquivo. A conversão fica um pouco mais lenta.")

    # Escolha dos arquivos

    def _pasta_para_dialogo(self) -> str:
        for candidata in (self.contexto.config.ultima_pasta, self.contexto.config.pasta_inicial):
            if candidata and Path(candidata).is_dir():
                return candidata
        return ""

    def _escolher_pasta(self) -> None:
        pasta = QFileDialog.getExistingDirectory(self, "Escolha a pasta com os documentos", self._pasta_para_dialogo())
        if pasta:
            self.receber_caminhos([Path(pasta)])

    def _escolher_arquivos(self) -> None:
        filtro = "Documentos do Office (" + " ".join(f"*{e}" for e in office.OFFICE.extensoes) + ")"
        arquivos, _ = QFileDialog.getOpenFileNames(self, "Escolha os documentos", self._pasta_para_dialogo(), filtro)
        if arquivos:
            self.receber_caminhos([Path(a) for a in arquivos])

    def receber_caminhos(self, caminhos: list[Path]) -> None:
        if self.executor.em_execucao or self._verificar_disponibilidade():
            return
        self.area.mostrar_aviso(None)
        pasta_saida = self.contexto.config.pasta_saida

        def preparar(progresso, cancelamento) -> _Preparo:
            selecao = montar_selecao(caminhos, pasta_saida, office.OFFICE)
            return _Preparo(selecao, office.preparar(selecao.arquivos))

        self.progresso.iniciar("Lendo os arquivos...", cancelavel=False)
        self._timer_progresso.start(ATRASO_PROGRESSO_MS)
        self.executar(preparar, self._mostrar_selecao, self._ao_falhar_preparo)

    def _ao_falhar_preparo(self, erro: BaseException) -> None:
        self._timer_progresso.stop()
        self.limpar()
        if isinstance(erro, ErroUnePDF):
            self.area.mostrar_aviso(str(erro))
        else:
            mostrar_erro(self, erro)

    def _mostrar_selecao(self, preparo: _Preparo) -> None:
        self._timer_progresso.stop()
        self._preparo = preparo
        selecao, arquivos = preparo.selecao, preparo.preparo.arquivos
        if self.contexto.config.ultima_pasta != str(selecao.base):
            self.contexto.config.ultima_pasta = str(selecao.base)
            self.contexto.salvar_config()

        self.resumo_selecao.setText(plural(len(arquivos), "documento selecionado", "documentos selecionados"))
        tipos = Counter(app for _, app, _ in arquivos)
        self.tipos_selecao.setText(", ".join(f"{tipos[app]} {app.value}" for app in office.Aplicativo if tipos[app]))
        self.origem_selecao.setText(f"Da pasta {selecao.pasta}" if selecao.pasta else f"Arquivos de {selecao.base}")

        self.lista.clear()
        for caminho, app, _ in arquivos:
            item = QListWidgetItem(caminho.name)
            item.setToolTip(str(caminho))
            self.lista.addItem(item)
        aviso = QBrush(QColor(CORES.aviso))
        for ignorado in preparo.preparo.ignorados:
            item = QListWidgetItem(f"{ignorado.caminho.name}: {ignorado.motivo}")
            item.setForeground(aviso)
            item.setToolTip(str(ignorado.caminho))
            self.lista.addItem(item)

        motores = sorted({motor.value for _, _, motor in arquivos})
        self.motor_selecao.setText(f"A conversão usa o {' e o '.join(motores)} instalado neste computador." if motores else "")
        self._ajustar_pdfa()
        avisos = []
        if preparo.preparo.ignorados:
            avisos.append(plural(
                len(preparo.preparo.ignorados),
                "arquivo não será convertido (em amarelo na lista).",
                "arquivos não serão convertidos (em amarelo na lista).",
            ))
        if selecao.descartados:
            avisos.append(
                f"{plural(selecao.descartados, 'item ficou', 'itens ficaram')} de fora: "
                "não são documentos do Office ou estão na pasta de saída."
            )
        self.aviso_selecao.setText("\n".join(avisos))
        self.botao_converter.setText("Converter " + plural(len(arquivos), "documento", "documentos"))
        self.botao_converter.setEnabled(bool(arquivos))
        self._mostrar_destino()
        self.estados.setCurrentWidget(self.painel_selecao)

    def _pasta_destino(self) -> Path:
        return self._preparo.selecao.base / self.contexto.config.pasta_saida

    def _destino_juntado(self) -> Path:
        nome = nome_saida(self._preparo.selecao.base, self.contexto.config.perfil_nomenclatura).removesuffix(".pdf")
        return self._pasta_destino() / f"{nome} (Office).pdf"

    def _mostrar_destino(self) -> None:
        texto = str(self._pasta_destino())
        if self.check_juntar.isChecked():
            texto += f"\nPDF com todos: {self._destino_juntado().name}"
        self.destino_selecao.setText(texto)

    def _salvar_opcoes(self) -> None:
        config = self.contexto.config
        novo = (self.check_pdfa.isChecked(), self.check_juntar.isChecked())
        if novo != (config.office_pdfa, config.office_juntar):
            config.office_pdfa, config.office_juntar = novo
            self.contexto.salvar_config()
        if self._preparo:
            self._mostrar_destino()

    def limpar(self) -> None:
        self._preparo = None
        self.area.mostrar_aviso(None)
        self.estados.setCurrentWidget(self.area)

    # Conversão

    def _converter(self) -> None:
        if not self._preparo or self.executor.em_execucao:
            return
        preparo, pasta = self._preparo.preparo, self._pasta_destino()
        pdfa = self.check_pdfa.isChecked() and self.check_pdfa.isEnabled()
        juntar_em = self._destino_juntado() if self.check_juntar.isChecked() else None
        self.progresso.iniciar("Convertendo os documentos...")
        self.estados.setCurrentWidget(self.progresso)
        self.executar(
            lambda progresso, cancelamento: office.converter_documentos(
                preparo, pasta, pdfa, juntar_em, progresso, cancelamento
            ),
            self._ao_converter,
            self._ao_falhar_conversao,
        )

    def _ao_converter(self, resultado: office.ResultadoOffice) -> None:
        partes = [plural(len(resultado.gerados), "PDF gerado", "PDFs gerados") + "."]
        if resultado.substituidos:
            partes.append(plural(
                resultado.substituidos,
                "substituiu um arquivo anterior com o mesmo nome.",
                "substituíram arquivos anteriores com o mesmo nome.",
            ))
        if resultado.juntado:
            partes.append(f"O PDF com todos tem {plural(resultado.paginas_juntado, 'página', 'páginas')}.")
        if resultado.cancelado:
            titulo = "Conversão interrompida"
            partes.append(f"{plural(resultado.pendentes, 'documento ficou', 'documentos ficaram')} sem converter.")
        else:
            titulo = "PDFs criados!"
        if resultado.juntado:
            destino, texto_abrir = resultado.juntado, "Abrir PDF com todos"
        elif len(resultado.gerados) == 1:
            destino, texto_abrir = resultado.gerados[0], "Abrir arquivo"
        else:
            destino, texto_abrir = resultado.pasta, "Abrir pasta"
        self.resultado.mostrar_sucesso(titulo, " ".join(partes), destino, resultado.ignorados, texto_abrir)
        self.estados.setCurrentWidget(self.resultado)

    def _ao_falhar_conversao(self, erro: BaseException) -> None:
        if isinstance(erro, ErroUnePDF) and erro.ignorados:
            self.resultado.mostrar_falha("Nenhum PDF foi gerado", str(erro), erro.ignorados)
            self.estados.setCurrentWidget(self.resultado)
            return
        self.estados.setCurrentWidget(self.painel_selecao)
        mostrar_erro(self, erro)
