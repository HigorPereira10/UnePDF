"""Ferramenta OCR: deixa pesquisáveis os PDFs escaneados e as imagens de documentos."""
from __future__ import annotations

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

from unepdf.core import ocr
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
    preparo: ocr.PreparoOcr


def _ajuda(texto: str = "") -> QLabel:
    rotulo = QLabel(texto)
    rotulo.setObjectName("subtitulo")
    rotulo.setWordWrap(True)
    return rotulo


class TelaOcr(TelaFerramenta):
    aceita_arquivos = True

    def __init__(self, ferramenta: Ferramenta, contexto: ContextoApp):
        super().__init__(ferramenta, contexto)
        self._preparo: _Preparo | None = None
        self._aviso_era_indisponivel = False

        self.area = AreaSoltar(
            "Arraste PDFs escaneados ou uma pasta para cá",
            "Também aceita imagens (JPG, PNG, TIFF). O texto passa a ser pesquisável e copiável.",
            texto_arquivos="Escolher arquivos",
        )
        self.area.caminhos_soltos.connect(self.receber_caminhos)
        self.area.escolher_pasta.connect(self._escolher_pasta)
        self.area.escolher_arquivos.connect(self._escolher_arquivos)
        self.progresso = PainelProgresso()
        self.progresso.cancelar.connect(self.executor.cancelar)
        self.executor.progresso.connect(self.progresso.atualizar)
        self.resultado = PainelResultado("Fazer OCR em outros arquivos")
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
        self.detalhe_selecao = _ajuda()
        self.origem_selecao = _ajuda()
        trocar = QPushButton("Trocar seleção")
        trocar.clicked.connect(self.limpar)
        textos = QVBoxLayout()
        textos.setSpacing(2)
        for rotulo in (self.resumo_selecao, self.detalhe_selecao, self.origem_selecao):
            textos.addWidget(rotulo)
        cabecalho = QHBoxLayout()
        cabecalho.addLayout(textos, 1)
        cabecalho.addWidget(trocar)

        self.lista = QListWidget()
        self.lista.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        explicacao = _ajuda(
            "A aparência das páginas não muda: o texto reconhecido fica numa camada invisível por cima da imagem. "
            "Páginas que já têm texto ficam como estão. Leva alguns segundos por página."
        )
        self.check_juntar = QCheckBox("Também juntar tudo em um PDF, com um marcador por arquivo")
        self.check_juntar.setChecked(self.contexto.config.ocr_juntar)
        self.check_juntar.toggled.connect(self._ao_mudar_juntar)

        rotulo_destino = QLabel("SERÁ SALVO EM")
        rotulo_destino.setObjectName("rotuloCampo")
        self.destino_selecao = QLabel()
        self.destino_selecao.setWordWrap(True)
        self.aviso_selecao = QLabel()
        self.aviso_selecao.setObjectName("aviso")
        self.aviso_selecao.setWordWrap(True)
        self.botao_ocr = QPushButton("Fazer OCR")
        self.botao_ocr.setObjectName("botaoPrincipal")
        self.botao_ocr.clicked.connect(self._fazer_ocr)
        rodape = QHBoxLayout()
        rodape.addWidget(self.aviso_selecao, 1)
        rodape.addWidget(self.botao_ocr)

        painel = QWidget()
        layout = QVBoxLayout(painel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addLayout(cabecalho)
        layout.addWidget(self.lista, 1)
        layout.addWidget(explicacao)
        layout.addWidget(self.check_juntar)
        layout.addSpacing(4)
        layout.addWidget(rotulo_destino)
        layout.addWidget(self.destino_selecao)
        layout.addLayout(rodape)
        self.painel_selecao = painel
        return painel

    # Disponibilidade

    def _verificar_disponibilidade(self) -> str | None:
        """Sem o Tesseract (ou sem o português), explica o que falta e bloqueia a escolha de arquivos."""
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
        pasta = QFileDialog.getExistingDirectory(self, "Escolha a pasta com os arquivos", self._pasta_para_dialogo())
        if pasta:
            self.receber_caminhos([Path(pasta)])

    def _escolher_arquivos(self) -> None:
        filtro = "PDFs e imagens (" + " ".join(f"*{e}" for e in ocr.PDF_OU_IMAGEM.extensoes) + ")"
        arquivos, _ = QFileDialog.getOpenFileNames(self, "Escolha os arquivos", self._pasta_para_dialogo(), filtro)
        if arquivos:
            self.receber_caminhos([Path(a) for a in arquivos])

    def receber_caminhos(self, caminhos: list[Path]) -> None:
        if self.executor.em_execucao or self._verificar_disponibilidade():
            return
        self.area.mostrar_aviso(None)
        pasta_saida = self.contexto.config.pasta_saida

        def preparar(progresso, cancelamento) -> _Preparo:
            selecao = montar_selecao(caminhos, pasta_saida, ocr.PDF_OU_IMAGEM)
            return _Preparo(selecao, ocr.preparar(selecao.arquivos))

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
        selecao, itens = preparo.selecao, preparo.preparo.itens
        if self.contexto.config.ultima_pasta != str(selecao.base):
            self.contexto.config.ultima_pasta = str(selecao.base)
            self.contexto.salvar_config()

        self.resumo_selecao.setText(plural(len(itens), "arquivo selecionado", "arquivos selecionados"))
        self.detalhe_selecao.setText(f"{plural(preparo.preparo.total_paginas, 'página', 'páginas')} no total")
        self.origem_selecao.setText(f"Da pasta {selecao.pasta}" if selecao.pasta else f"Arquivos de {selecao.base}")
        self.lista.clear()
        for item in itens:
            texto = f"{item.caminho.name} ({plural(item.paginas, 'página', 'páginas')})"
            elemento = QListWidgetItem(texto)
            elemento.setToolTip(str(item.caminho))
            self.lista.addItem(elemento)
        aviso = QBrush(QColor(CORES.aviso))
        for ignorado in preparo.preparo.ignorados:
            elemento = QListWidgetItem(f"{ignorado.caminho.name}: {ignorado.motivo}")
            elemento.setForeground(aviso)
            elemento.setToolTip(str(ignorado.caminho))
            self.lista.addItem(elemento)

        avisos = []
        if preparo.preparo.ignorados:
            avisos.append(plural(
                len(preparo.preparo.ignorados),
                "arquivo não pode passar pelo OCR (em amarelo na lista).",
                "arquivos não podem passar pelo OCR (em amarelo na lista).",
            ))
        if selecao.descartados:
            avisos.append(
                f"{plural(selecao.descartados, 'item ficou', 'itens ficaram')} de fora: "
                "não são PDF nem imagem, ou estão na pasta de saída."
            )
        self.aviso_selecao.setText("\n".join(avisos))
        self.botao_ocr.setText("Fazer OCR em " + plural(len(itens), "arquivo", "arquivos"))
        self.botao_ocr.setEnabled(bool(itens))
        self._mostrar_destino()
        self.estados.setCurrentWidget(self.painel_selecao)

    def _pasta_destino(self) -> Path:
        return self._preparo.selecao.base / self.contexto.config.pasta_saida

    def _destino_juntado(self) -> Path:
        nome = nome_saida(self._preparo.selecao.base, self.contexto.config.perfil_nomenclatura).removesuffix(".pdf")
        return self._pasta_destino() / f"{nome} (OCR).pdf"

    def _mostrar_destino(self) -> None:
        texto = str(self._pasta_destino())
        if self.check_juntar.isChecked():
            texto += f"\nPDF com todos: {self._destino_juntado().name}"
        self.destino_selecao.setText(texto)

    def _ao_mudar_juntar(self, marcado: bool) -> None:
        if self.contexto.config.ocr_juntar != marcado:
            self.contexto.config.ocr_juntar = marcado
            self.contexto.salvar_config()
        if self._preparo:
            self._mostrar_destino()

    def limpar(self) -> None:
        self._preparo = None
        self.area.mostrar_aviso(None)
        self.estados.setCurrentWidget(self.area)

    # OCR

    def _fazer_ocr(self) -> None:
        if not self._preparo or self.executor.em_execucao:
            return
        preparo, pasta = self._preparo.preparo, self._pasta_destino()
        juntar_em = self._destino_juntado() if self.check_juntar.isChecked() else None
        self.progresso.iniciar("Reconhecendo o texto...")
        self.estados.setCurrentWidget(self.progresso)
        self.executar(
            lambda progresso, cancelamento: ocr.ocr_documentos(preparo, pasta, juntar_em, progresso, cancelamento),
            self._ao_concluir,
            self._ao_falhar,
        )

    def _ao_concluir(self, resultado: ocr.ResultadoOcr) -> None:
        partes = [
            f"{plural(len(resultado.gerados), 'arquivo ficou pesquisável', 'arquivos ficaram pesquisáveis')} "
            f"({plural(resultado.paginas_reconhecidas, 'página lida', 'páginas lidas')} com OCR)."
        ]
        if resultado.paginas_com_texto:
            partes.append(plural(
                resultado.paginas_com_texto,
                "página já tinha texto e ficou como estava.",
                "páginas já tinham texto e ficaram como estavam.",
            ))
        if resultado.substituidos:
            partes.append(plural(
                resultado.substituidos,
                "substituiu um arquivo anterior com o mesmo nome.",
                "substituíram arquivos anteriores com o mesmo nome.",
            ))
        if resultado.juntado:
            partes.append(f"O PDF com todos tem {plural(resultado.paginas_juntado, 'página', 'páginas')}.")
        if resultado.cancelado:
            titulo = "OCR interrompido"
            partes.append(f"{plural(resultado.pendentes, 'arquivo ficou', 'arquivos ficaram')} sem OCR.")
        else:
            titulo = "OCR concluído!"
        if resultado.juntado:
            destino, texto_abrir = resultado.juntado, "Abrir PDF com todos"
        elif len(resultado.gerados) == 1:
            destino, texto_abrir = resultado.gerados[0], "Abrir arquivo"
        else:
            destino, texto_abrir = resultado.pasta, "Abrir pasta"
        self.resultado.mostrar_sucesso(titulo, " ".join(partes), destino, resultado.ignorados, texto_abrir)
        self.estados.setCurrentWidget(self.resultado)

    def _ao_falhar(self, erro: BaseException) -> None:
        if isinstance(erro, ErroUnePDF) and erro.ignorados:
            self.resultado.mostrar_falha("Nenhum arquivo passou pelo OCR", str(erro), erro.ignorados)
            self.estados.setCurrentWidget(self.resultado)
            return
        self.estados.setCurrentWidget(self.painel_selecao)
        mostrar_erro(self, erro)
