"""Ferramentas de conversão: imagens para PDF, PDF para imagens e PDF para texto."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from unepdf.core.converter import FormatoImagem, pdf_para_imagens, pdf_para_texto
from unepdf.core.erros import ErroUnePDF, OperacaoCancelada
from unepdf.core.imagens import TamanhoPagina, imagens_para_pdf
from unepdf.core.leitor_pdf import abrir_pdf_ou_erro
from unepdf.core.localizador import IMAGEM, Selecao, montar_selecao
from unepdf.core.modelos import Resultado
from unepdf.core.nomenclatura import destino_derivado, limpar_nome, pasta_resultado
from unepdf.core.paginas import interpretar_paginas
from unepdf.core.pdfa import FormatoSaida
from unepdf.core.pdfa import converter as converter_pdfa
from unepdf.ui.componentes import AreaSoltar, PainelProgresso, PainelResultado
from unepdf.ui.contexto import ContextoApp
from unepdf.ui.dialogos import mostrar_erro
from unepdf.ui.executor import Tarefa
from unepdf.ui.ferramentas.arquivo_unico import ATRASO_PROGRESSO_MS, TelaArquivoUnico
from unepdf.ui.ferramentas.base import TelaFerramenta
from unepdf.utils.texto import plural

if TYPE_CHECKING:
    from unepdf.ui.ferramentas import Ferramenta

PAPEL_CAMINHO = Qt.ItemDataRole.UserRole


def _ajuda(texto: str = "") -> QLabel:
    rotulo = QLabel(texto)
    rotulo.setObjectName("subtitulo")
    rotulo.setWordWrap(True)
    return rotulo


def _rotulo_campo(texto: str) -> QLabel:
    rotulo = QLabel(texto)
    rotulo.setObjectName("rotuloCampo")
    return rotulo


# Imagens para PDF

class TelaImagensParaPdf(TelaFerramenta):
    """Várias imagens viram um PDF, uma por página, na ordem da lista (que pode ser ajustada arrastando)."""

    aceita_arquivos = True

    def __init__(self, ferramenta: Ferramenta, contexto: ContextoApp):
        super().__init__(ferramenta, contexto)
        self._selecao: Selecao | None = None

        self.area = AreaSoltar(
            "Arraste imagens ou uma pasta para cá",
            "JPG, PNG, TIFF, BMP e WEBP. O JPG entra no PDF sem perder qualidade.",
            texto_arquivos="Escolher imagens",
        )
        self.area.caminhos_soltos.connect(self.receber_caminhos)
        self.area.escolher_pasta.connect(self._escolher_pasta)
        self.area.escolher_arquivos.connect(self._escolher_arquivos)
        self.progresso = PainelProgresso()
        self.progresso.cancelar.connect(self.executor.cancelar)
        self.executor.progresso.connect(self.progresso.atualizar)
        self.resultado = PainelResultado("Converter outras imagens")
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
        self.lista.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.lista.setDefaultDropAction(Qt.DropAction.MoveAction)

        self.opcao_a4 = QRadioButton("Folha A4 (a imagem é ajustada à folha, em pé ou deitada)")
        self.opcao_original = QRadioButton("Tamanho original da imagem")
        self._tamanhos = QButtonGroup(self)
        self._tamanhos.addButton(self.opcao_a4)
        self._tamanhos.addButton(self.opcao_original)
        self.opcao_a4.setChecked(True)

        self.destino_selecao = QLabel()
        self.destino_selecao.setWordWrap(True)
        self.aviso_selecao = QLabel()
        self.aviso_selecao.setObjectName("aviso")
        self.aviso_selecao.setWordWrap(True)
        self.botao_converter = QPushButton("Converter para PDF")
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
        layout.addWidget(_ajuda("Arraste os nomes para mudar a ordem das páginas."))
        layout.addWidget(self.lista, 1)
        layout.addWidget(_rotulo_campo("TAMANHO DA PÁGINA"))
        layout.addWidget(self.opcao_a4)
        layout.addWidget(self.opcao_original)
        layout.addSpacing(4)
        layout.addWidget(_rotulo_campo("SERÁ SALVO EM"))
        layout.addWidget(self.destino_selecao)
        layout.addLayout(rodape)
        self.painel_selecao = painel
        return painel

    def _pasta_para_dialogo(self) -> str:
        for candidata in (self.contexto.config.ultima_pasta, self.contexto.config.pasta_inicial):
            if candidata and Path(candidata).is_dir():
                return candidata
        return ""

    def _escolher_pasta(self) -> None:
        pasta = QFileDialog.getExistingDirectory(self, "Escolha a pasta com as imagens", self._pasta_para_dialogo())
        if pasta:
            self.receber_caminhos([Path(pasta)])

    def _escolher_arquivos(self) -> None:
        filtro = "Imagens (" + " ".join(f"*{e}" for e in IMAGEM.extensoes) + ")"
        arquivos, _ = QFileDialog.getOpenFileNames(self, "Escolha as imagens", self._pasta_para_dialogo(), filtro)
        if arquivos:
            self.receber_caminhos([Path(a) for a in arquivos])

    def receber_caminhos(self, caminhos: list[Path]) -> None:
        if self.executor.em_execucao:
            return
        self.area.mostrar_aviso(None)
        pasta_saida = self.contexto.config.pasta_saida
        self.progresso.iniciar("Lendo os arquivos...", cancelavel=False)
        self._timer_progresso.start(ATRASO_PROGRESSO_MS)
        self.executar(
            lambda progresso, cancelamento: montar_selecao(caminhos, pasta_saida, IMAGEM),
            self._mostrar_selecao,
            self._ao_falhar_selecao,
        )

    def _mostrar_selecao(self, selecao: Selecao) -> None:
        self._timer_progresso.stop()
        self._selecao = selecao
        if self.contexto.config.ultima_pasta != str(selecao.base):
            self.contexto.config.ultima_pasta = str(selecao.base)
            self.contexto.salvar_config()
        self.resumo_selecao.setText(plural(len(selecao.arquivos), "imagem selecionada", "imagens selecionadas"))
        self.origem_selecao.setText(f"Da pasta {selecao.pasta}" if selecao.pasta else f"Arquivos de {selecao.base}")
        self.lista.clear()
        for caminho in selecao.arquivos:
            item = QListWidgetItem(caminho.name)
            item.setData(PAPEL_CAMINHO, caminho)
            self.lista.addItem(item)
        self.destino_selecao.setText(str(self.destino()))
        avisos = []
        if selecao.descartados:
            avisos.append(
                f"{plural(selecao.descartados, 'item ficou', 'itens ficaram')} de fora: "
                "não são imagens, estão repetidos ou estão na pasta de saída."
            )
        if self.destino().exists():
            avisos.append("Já existe um arquivo com esse nome. Ele será substituído.")
        self.aviso_selecao.setText("\n".join(avisos))
        self.estados.setCurrentWidget(self.painel_selecao)

    def _ao_falhar_selecao(self, erro: BaseException) -> None:
        self._timer_progresso.stop()
        self.limpar()
        if isinstance(erro, ErroUnePDF):
            self.area.mostrar_aviso(str(erro))
        else:
            mostrar_erro(self, erro)

    def destino(self) -> Path:
        selecao = self._selecao
        if len(selecao.arquivos) == 1 and selecao.pasta is None:
            nome = f"{selecao.arquivos[0].stem}.pdf"
        else:
            nome = f"{limpar_nome(selecao.base.name) or 'imagens'} - imagens.pdf"
        return selecao.base / self.contexto.config.pasta_saida / nome

    def _converter(self) -> None:
        if not self._selecao or self.executor.em_execucao:
            return
        arquivos = [self.lista.item(i).data(PAPEL_CAMINHO) for i in range(self.lista.count())]
        destino = self.destino()
        tamanho = TamanhoPagina.A4 if self.opcao_a4.isChecked() else TamanhoPagina.IMAGEM
        self.progresso.iniciar("Convertendo as imagens...")
        self.estados.setCurrentWidget(self.progresso)
        self.executar(
            lambda progresso, cancelamento: imagens_para_pdf(arquivos, destino, tamanho, progresso, cancelamento),
            self._ao_converter,
            self._ao_falhar_conversao,
        )

    def _ao_converter(self, resultado: Resultado) -> None:
        resumo = (
            f"{plural(resultado.arquivos, 'imagem convertida', 'imagens convertidas')} em um PDF de "
            f"{plural(resultado.paginas, 'página', 'páginas')}."
        )
        if resultado.substituiu_anterior:
            resumo += " O arquivo anterior com o mesmo nome foi substituído."
        self.resultado.mostrar_sucesso("PDF criado!", resumo, resultado.destino, resultado.ignorados)
        self.estados.setCurrentWidget(self.resultado)

    def _ao_falhar_conversao(self, erro: BaseException) -> None:
        if isinstance(erro, ErroUnePDF) and erro.ignorados:
            self.resultado.mostrar_falha("Nenhuma imagem foi convertida", str(erro), erro.ignorados)
            self.estados.setCurrentWidget(self.resultado)
            return
        self.estados.setCurrentWidget(self.painel_selecao)
        if isinstance(erro, OperacaoCancelada):
            self.aviso_selecao.setText(str(erro))
        else:
            mostrar_erro(self, erro)

    def limpar(self) -> None:
        self._selecao = None
        self.area.mostrar_aviso(None)
        self.estados.setCurrentWidget(self.area)


# PDF para imagens

@dataclass
class InfoPdf:
    paginas: int


class TelaPdfParaImagens(TelaArquivoUnico):
    dica_area = "Cada página vira uma imagem PNG ou JPG."
    texto_botao = "Converter em imagens"
    titulo_progresso = "Convertendo as páginas..."
    titulo_sucesso = "Imagens criadas!"
    texto_novo = "Converter outro PDF"
    texto_abrir = "Abrir pasta"

    RESOLUCOES = (
        (72, "72 dpi: para ver na tela, arquivos pequenos"),
        (150, "150 dpi: uso geral"),
        (300, "300 dpi: para imprimir"),
    )

    def carregar(self, origem: Path) -> InfoPdf:
        return InfoPdf(len(abrir_pdf_ou_erro(origem).pages))

    def montar_opcoes(self) -> QWidget:
        self.opcao_png = QRadioButton("PNG: sem perda, melhor para documentos com texto")
        self.opcao_jpg = QRadioButton("JPG: arquivos menores, melhor para fotos")
        self._formatos = QButtonGroup(self)
        self._formatos.addButton(self.opcao_png)
        self._formatos.addButton(self.opcao_jpg)
        self.opcao_png.setChecked(True)

        self.campo_resolucao = QComboBox()
        for dpi, texto in self.RESOLUCOES:
            self.campo_resolucao.addItem(texto, dpi)
        self.campo_resolucao.setCurrentIndex(1)
        self.campo_resolucao.setMaximumWidth(360)

        self.opcao_todas = QRadioButton("Todas as páginas")
        self.opcao_algumas = QRadioButton("Só as páginas:")
        self._paginas = QButtonGroup(self)
        self._paginas.addButton(self.opcao_todas)
        self._paginas.addButton(self.opcao_algumas)
        self._paginas.buttonClicked.connect(self._ao_mudar)
        self.opcao_todas.setChecked(True)
        self.campo_paginas = QLineEdit()
        self.campo_paginas.setPlaceholderText("Ex.: 1-3, 5")
        self.campo_paginas.setMaximumWidth(240)
        self.campo_paginas.textChanged.connect(self._ao_mudar)
        linha_paginas = QHBoxLayout()
        linha_paginas.addWidget(self.opcao_algumas)
        linha_paginas.addWidget(self.campo_paginas)
        linha_paginas.addStretch()

        painel = QWidget()
        layout = QVBoxLayout(painel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(_rotulo_campo("FORMATO"))
        layout.addWidget(self.opcao_png)
        layout.addWidget(self.opcao_jpg)
        layout.addSpacing(8)
        layout.addWidget(_rotulo_campo("RESOLUÇÃO"))
        layout.addWidget(self.campo_resolucao)
        layout.addSpacing(8)
        layout.addWidget(_rotulo_campo("PÁGINAS"))
        layout.addWidget(self.opcao_todas)
        layout.addLayout(linha_paginas)
        layout.addStretch()
        return painel

    def preencher_opcoes(self, info: InfoPdf) -> None:
        self.opcao_todas.setChecked(True)
        self.campo_paginas.clear()

    def descrever(self, info: InfoPdf) -> str:
        return plural(info.paginas, "página", "páginas")

    def _ao_mudar(self, *_) -> None:
        self.atualizar_estado()

    def atualizar_estado(self, aviso: str = "") -> None:
        if self.info is not None:
            self.campo_paginas.setEnabled(self.opcao_algumas.isChecked())
        super().atualizar_estado(aviso)

    def _paginas_escolhidas(self) -> list[int] | None:
        if not self.opcao_algumas.isChecked():
            return None
        return interpretar_paginas(self.campo_paginas.text(), self.info.paginas)

    def destino(self) -> Path:
        return pasta_resultado(self.origem, self.contexto.config.pasta_saida) / f"{self.origem.stem} - imagens"

    def validar(self) -> str | None:
        if self.opcao_algumas.isChecked():
            if not self.campo_paginas.text().strip():
                return ""
            try:
                self._paginas_escolhidas()
            except ErroUnePDF as erro:
                return str(erro)
        return None

    def tarefa(self) -> Tarefa:
        origem, destino, paginas = self.origem, self.destino(), self._paginas_escolhidas()
        formato = FormatoImagem.PNG if self.opcao_png.isChecked() else FormatoImagem.JPG
        dpi = self.campo_resolucao.currentData()
        return lambda p, c: pdf_para_imagens(origem, destino, formato, dpi, paginas, p, c)

    def resumo(self, resultado: Resultado) -> str:
        return f"{plural(resultado.arquivos, 'imagem criada', 'imagens criadas')}, uma por página."


# PDF para texto

class TelaPdfParaTexto(TelaArquivoUnico):
    dica_area = "O texto do PDF é salvo em um arquivo .txt, que abre no Bloco de Notas."
    texto_botao = "Extrair texto"
    titulo_progresso = "Lendo o texto..."
    titulo_sucesso = "Texto extraído!"
    texto_novo = "Extrair de outro PDF"

    def carregar(self, origem: Path) -> InfoPdf:
        return InfoPdf(len(abrir_pdf_ou_erro(origem).pages))

    def montar_opcoes(self) -> QWidget:
        self.marcar_paginas = QCheckBox("Marcar o início de cada página no texto")
        self.marcar_paginas.setChecked(True)
        painel = QWidget()
        layout = QVBoxLayout(painel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(_rotulo_campo("OPÇÕES"))
        layout.addWidget(self.marcar_paginas)
        layout.addWidget(_ajuda(
            "Só é extraído o texto que pode ser selecionado no PDF. PDFs escaneados guardam apenas a "
            "imagem das páginas e não têm texto para extrair."
        ))
        layout.addStretch()
        return painel

    def descrever(self, info: InfoPdf) -> str:
        return plural(info.paginas, "página", "páginas")

    def destino(self) -> Path:
        return destino_derivado(self.origem, "texto", self.contexto.config.pasta_saida, extensao=".txt")

    def tarefa(self) -> Tarefa:
        origem, destino, separar = self.origem, self.destino(), self.marcar_paginas.isChecked()
        return lambda p, c: pdf_para_texto(origem, destino, separar, p, c)

    def resumo(self, resultado: Resultado) -> str:
        return f"Texto de {plural(resultado.paginas, 'página', 'páginas')} salvo."


# PDF para PDF/A

class TelaPdfA(TelaArquivoUnico):
    dica_area = "Converta para PDF/A, o formato exigido para arquivamento de longo prazo."
    texto_botao = "Converter"
    titulo_progresso = "Convertendo..."
    titulo_sucesso = "Conversão concluída!"
    texto_novo = "Converter outro PDF"

    FORMATOS = (
        (FormatoSaida.PDFA_2B, "PDF/A-2b", "O mais usado hoje e o recomendado na maioria dos casos."),
        (FormatoSaida.PDFA_1B, "PDF/A-1b", "O mais antigo, para sistemas que só aceitam a primeira versão."),
        (FormatoSaida.PDFA_3B, "PDF/A-3b", "Igual ao 2b, mas permite anexos dentro do PDF."),
        (FormatoSaida.PDF_14, "PDF 1.4 comum (sem PDF/A)", "Para sistemas antigos que recusam versões novas do PDF."),
    )

    def carregar(self, origem: Path) -> InfoPdf:
        return InfoPdf(len(abrir_pdf_ou_erro(origem).pages))

    def montar_opcoes(self) -> QWidget:
        self._formatos = QButtonGroup(self)
        self.opcoes_formato: dict[FormatoSaida, QRadioButton] = {}
        painel = QWidget()
        layout = QVBoxLayout(painel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(_rotulo_campo("FORMATO"))
        for formato, nome, explicacao in self.FORMATOS:
            opcao = QRadioButton(nome)
            self._formatos.addButton(opcao)
            self.opcoes_formato[formato] = opcao
            layout.addWidget(opcao)
            layout.addWidget(_ajuda(explicacao))
            layout.addSpacing(4)
        self.opcoes_formato[FormatoSaida.PDFA_2B].setChecked(True)
        self._formatos.buttonClicked.connect(lambda *_: self.atualizar_estado())
        layout.addSpacing(6)
        layout.addWidget(_ajuda(
            "A conversão é feita pelo Ghostscript: as fontes e o perfil de cores passam a ir dentro do "
            "arquivo, como o padrão exige. Para uma validação oficial, use um validador como o veraPDF."
        ))
        layout.addStretch()
        return painel

    def descrever(self, info: InfoPdf) -> str:
        return plural(info.paginas, "página", "páginas")

    def _formato(self) -> FormatoSaida:
        return next(f for f, opcao in self.opcoes_formato.items() if opcao.isChecked())

    def destino(self) -> Path:
        sufixo = self._formato().value.replace("/", "").replace(" ", "-")  # "PDFA-2b", "PDF-1.4"
        return destino_derivado(self.origem, sufixo, self.contexto.config.pasta_saida)

    def tarefa(self) -> Tarefa:
        origem, destino, formato = self.origem, self.destino(), self._formato()
        return lambda p, c: converter_pdfa(origem, destino, formato, p, c)

    def resumo(self, resultado: Resultado) -> str:
        paginas = plural(resultado.paginas, "página", "páginas")
        return f"Arquivo convertido para {self._formato().value}, com {paginas}."
