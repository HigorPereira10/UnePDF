"""Ferramentas de edição: marca d'água e numeração de páginas."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QRadioButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from unepdf.core.carimbo import (
    FormatoNumero,
    Posicao,
    TamanhoMarca,
    aplicar_marca_dagua,
    numerar_paginas,
    texto_suportado,
)
from unepdf.core.leitor_pdf import abrir_pdf_ou_erro
from unepdf.core.modelos import Resultado
from unepdf.core.nomenclatura import destino_derivado
from unepdf.ui.executor import Tarefa
from unepdf.ui.ferramentas.arquivo_unico import TelaArquivoUnico
from unepdf.utils.texto import plural


def _rotulo(texto: str) -> QLabel:
    rotulo = QLabel(texto)
    rotulo.setObjectName("rotuloCampo")
    return rotulo


@dataclass
class InfoPdf:
    paginas: int


class _TelaEdicao(TelaArquivoUnico):
    def carregar(self, origem: Path) -> InfoPdf:
        return InfoPdf(len(abrir_pdf_ou_erro(origem).pages))

    def descrever(self, info: InfoPdf) -> str:
        return plural(info.paginas, "página", "páginas")

    def _ao_mudar(self, *_) -> None:
        self.atualizar_estado()


class TelaMarcaDagua(_TelaEdicao):
    dica_area = "Escreva um texto, como CONFIDENCIAL ou CÓPIA, sobre todas as páginas."
    texto_botao = "Aplicar marca d'água"
    titulo_progresso = "Aplicando a marca d'água..."
    titulo_sucesso = "Marca d'água aplicada!"
    texto_novo = "Escolher outro PDF"

    def montar_opcoes(self) -> QWidget:
        self.campo_texto = QLineEdit("CONFIDENCIAL")
        self.campo_texto.setMaximumWidth(420)
        self.campo_texto.textChanged.connect(self._ao_mudar)

        self.campo_tamanho = QComboBox()
        for tamanho, texto in (
            (TamanhoMarca.PEQUENO, "Pequeno"),
            (TamanhoMarca.MEDIO, "Médio"),
            (TamanhoMarca.GRANDE, "Grande"),
        ):
            self.campo_tamanho.addItem(texto, tamanho)
        self.campo_tamanho.setCurrentIndex(1)
        self.campo_tamanho.setMaximumWidth(200)

        self.opcao_diagonal = QRadioButton("Na diagonal")
        self.opcao_horizontal = QRadioButton("Na horizontal")
        self._direcoes = QButtonGroup(self)
        self._direcoes.addButton(self.opcao_diagonal)
        self._direcoes.addButton(self.opcao_horizontal)
        self.opcao_diagonal.setChecked(True)
        direcoes = QHBoxLayout()
        direcoes.addWidget(self.opcao_diagonal)
        direcoes.addWidget(self.opcao_horizontal)
        direcoes.addStretch()

        self.campo_opacidade = QSlider(Qt.Orientation.Horizontal)
        self.campo_opacidade.setRange(5, 100)
        self.campo_opacidade.setValue(25)
        self.campo_opacidade.setMaximumWidth(300)
        self.rotulo_opacidade = QLabel()
        self.campo_opacidade.valueChanged.connect(lambda v: self.rotulo_opacidade.setText(f"{v}%"))
        self.rotulo_opacidade.setText("25%")
        opacidade = QHBoxLayout()
        opacidade.addWidget(self.campo_opacidade)
        opacidade.addWidget(self.rotulo_opacidade)
        opacidade.addStretch()

        painel = QWidget()
        layout = QVBoxLayout(painel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(_rotulo("TEXTO"))
        layout.addWidget(self.campo_texto)
        layout.addSpacing(6)
        layout.addWidget(_rotulo("TAMANHO"))
        layout.addWidget(self.campo_tamanho)
        layout.addSpacing(6)
        layout.addWidget(_rotulo("POSIÇÃO"))
        layout.addLayout(direcoes)
        layout.addSpacing(6)
        layout.addWidget(_rotulo("OPACIDADE (QUANTO MAIOR, MAIS FORTE)"))
        layout.addLayout(opacidade)
        layout.addStretch()
        return painel

    def destino(self) -> Path:
        return destino_derivado(self.origem, "marca d'água", self.contexto.config.pasta_saida)

    def validar(self) -> str | None:
        texto = self.campo_texto.text().strip()
        if not texto:
            return ""
        if not texto_suportado(texto):
            return (
                "O texto tem caracteres que não existem na fonte do PDF (como emojis). "
                "Use letras, números e símbolos comuns."
            )
        return None

    def tarefa(self) -> Tarefa:
        origem, destino = self.origem, self.destino()
        texto = self.campo_texto.text()
        opacidade = self.campo_opacidade.value() / 100
        tamanho = self.campo_tamanho.currentData()
        diagonal = self.opcao_diagonal.isChecked()
        return lambda p, c: aplicar_marca_dagua(origem, destino, texto, opacidade, tamanho, diagonal, p, c)

    def resumo(self, resultado: Resultado) -> str:
        return f"Marca d'água aplicada em {plural(resultado.paginas, 'página', 'páginas')}."


class TelaNumerar(_TelaEdicao):
    dica_area = "Escreva o número em cada página, no rodapé ou no topo."
    texto_botao = "Numerar páginas"
    titulo_progresso = "Numerando as páginas..."
    titulo_sucesso = "Páginas numeradas!"
    texto_novo = "Numerar outro PDF"

    FORMATOS = (
        (FormatoNumero.PAGINA_DE_TOTAL, "Página 1 de 10"),
        (FormatoNumero.PAGINA, "Página 1"),
        (FormatoNumero.BARRA, "1 / 10"),
        (FormatoNumero.NUMERO, "1"),
    )
    POSICOES = (
        (Posicao.RODAPE_CENTRO, "Rodapé, no centro"),
        (Posicao.RODAPE_DIREITA, "Rodapé, à direita"),
        (Posicao.RODAPE_ESQUERDA, "Rodapé, à esquerda"),
        (Posicao.TOPO_CENTRO, "Topo, no centro"),
        (Posicao.TOPO_DIREITA, "Topo, à direita"),
        (Posicao.TOPO_ESQUERDA, "Topo, à esquerda"),
    )

    def montar_opcoes(self) -> QWidget:
        self.campo_formato = QComboBox()
        for formato, exemplo in self.FORMATOS:
            self.campo_formato.addItem(exemplo, formato)
        self.campo_formato.setMaximumWidth(260)
        self.campo_posicao = QComboBox()
        for posicao, texto in self.POSICOES:
            self.campo_posicao.addItem(texto, posicao)
        self.campo_posicao.setMaximumWidth(260)
        self.pular_capa = QCheckBox("Não numerar a primeira página (capa)")
        ajuda = QLabel("As demais páginas mantêm a numeração do documento: a segunda recebe o número 2.")
        ajuda.setObjectName("subtitulo")
        ajuda.setWordWrap(True)

        painel = QWidget()
        layout = QVBoxLayout(painel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(_rotulo("FORMATO"))
        layout.addWidget(self.campo_formato)
        layout.addSpacing(6)
        layout.addWidget(_rotulo("POSIÇÃO"))
        layout.addWidget(self.campo_posicao)
        layout.addSpacing(6)
        layout.addWidget(self.pular_capa)
        layout.addWidget(ajuda)
        layout.addStretch()
        return painel

    def destino(self) -> Path:
        return destino_derivado(self.origem, "numerado", self.contexto.config.pasta_saida)

    def tarefa(self) -> Tarefa:
        origem, destino = self.origem, self.destino()
        formato, posicao = self.campo_formato.currentData(), self.campo_posicao.currentData()
        pular = self.pular_capa.isChecked()
        return lambda p, c: numerar_paginas(origem, destino, formato, posicao, pular, progresso=p, cancelamento=c)

    def resumo(self, resultado: Resultado) -> str:
        return f"PDF com {plural(resultado.paginas, 'página numerada', 'páginas numeradas')} salvo."
