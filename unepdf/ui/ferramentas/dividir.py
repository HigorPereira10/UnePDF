"""Ferramenta Dividir PDF: por intervalos, a cada N páginas ou um arquivo por marcador."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QGridLayout,
    QLabel,
    QLineEdit,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from unepdf.core import dividir
from unepdf.core.erros import ErroUnePDF
from unepdf.core.leitor_pdf import abrir_pdf_ou_erro
from unepdf.core.modelos import Resultado
from unepdf.core.nomenclatura import pasta_resultado
from unepdf.ui.executor import Tarefa
from unepdf.ui.ferramentas.arquivo_unico import TelaArquivoUnico
from unepdf.utils.texto import plural


@dataclass
class InfoDivisao:
    paginas: int
    marcadores: int


def _ajuda(texto: str = "") -> QLabel:
    rotulo = QLabel(texto)
    rotulo.setObjectName("subtitulo")
    rotulo.setWordWrap(True)
    return rotulo


class TelaDividir(TelaArquivoUnico):
    dica_area = "Divida por intervalos de páginas, a cada N páginas ou em um arquivo por marcador."
    texto_botao = "Dividir PDF"
    titulo_progresso = "Dividindo o PDF..."
    titulo_sucesso = "PDF dividido!"
    texto_novo = "Dividir outro PDF"
    texto_abrir = "Abrir pasta"

    def carregar(self, origem: Path) -> InfoDivisao:
        leitor = abrir_pdf_ou_erro(origem)
        return InfoDivisao(len(leitor.pages), len(dividir.marcadores(leitor)))

    def montar_opcoes(self) -> QWidget:
        self.opcao_intervalos = QRadioButton("Por intervalos de páginas")
        self.campo_intervalos = QLineEdit()
        self.campo_intervalos.setPlaceholderText("Ex.: 1-3, 5, 8-10")
        self.campo_intervalos.setMaximumWidth(360)
        self.campo_intervalos.textChanged.connect(self._ao_mudar)

        self.opcao_a_cada = QRadioButton("A cada")
        self.campo_a_cada = QSpinBox()
        self.campo_a_cada.setRange(1, 99_999)
        self.campo_a_cada.setSuffix(" página(s)")
        self.campo_a_cada.setMaximumWidth(160)
        self.campo_a_cada.valueChanged.connect(self._ao_mudar)
        self.ajuda_a_cada = _ajuda()

        self.opcao_marcadores = QRadioButton("Um arquivo por marcador")
        self.ajuda_marcadores = _ajuda()

        self._modos = QButtonGroup(self)
        for opcao in (self.opcao_intervalos, self.opcao_a_cada, self.opcao_marcadores):
            self._modos.addButton(opcao)
        self._modos.buttonClicked.connect(self._ao_mudar)

        grade = QGridLayout()
        grade.setColumnMinimumWidth(0, 26)
        grade.setColumnStretch(1, 1)
        grade.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        grade.setVerticalSpacing(6)
        grade.addWidget(self.opcao_intervalos, 0, 0, 1, 2)
        grade.addWidget(self.campo_intervalos, 1, 1)
        grade.addWidget(_ajuda("Cada intervalo vira um arquivo. Use 8- para ir da página 8 até o fim."), 2, 1)
        grade.setRowMinimumHeight(3, 10)
        grade.addWidget(self.opcao_a_cada, 4, 0, 1, 2)
        grade.addWidget(self.campo_a_cada, 5, 1)
        grade.addWidget(self.ajuda_a_cada, 6, 1)
        grade.setRowMinimumHeight(7, 10)
        grade.addWidget(self.opcao_marcadores, 8, 0, 1, 2)
        grade.addWidget(self.ajuda_marcadores, 9, 1)

        rotulo = QLabel("COMO DIVIDIR")
        rotulo.setObjectName("rotuloCampo")
        painel = QWidget()
        layout = QVBoxLayout(painel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(rotulo)
        layout.addLayout(grade)
        layout.addStretch()
        return painel

    def preencher_opcoes(self, info: InfoDivisao) -> None:
        self.campo_intervalos.clear()
        self.campo_a_cada.setValue(1)
        if info.marcadores:
            self.ajuda_marcadores.setText(
                f"{plural(info.marcadores, 'marcador encontrado', 'marcadores encontrados')}. "
                "Dividir um PDF criado pelo Unir PDFs devolve os arquivos originais."
            )
        else:
            self.ajuda_marcadores.setText("Este PDF não tem marcadores.")
        self.opcao_marcadores.setEnabled(bool(info.marcadores))
        (self.opcao_marcadores if info.marcadores else self.opcao_intervalos).setChecked(True)

    def descrever(self, info: InfoDivisao) -> str:
        return plural(info.paginas, "página", "páginas")

    def _ao_mudar(self, *_) -> None:
        self.atualizar_estado()

    def atualizar_estado(self, aviso: str = "") -> None:
        if self.info is not None:
            self.campo_intervalos.setEnabled(self.opcao_intervalos.isChecked())
            self.campo_a_cada.setEnabled(self.opcao_a_cada.isChecked())
            arquivos = -(-self.info.paginas // self.campo_a_cada.value())  # divisão arredondando para cima
            self.ajuda_a_cada.setText(f"Vai gerar {plural(arquivos, 'arquivo', 'arquivos')}.")
        super().atualizar_estado(aviso)

    def destino(self) -> Path:
        return pasta_resultado(self.origem, self.contexto.config.pasta_saida) / dividir.nome_pasta_divisao(self.origem)

    def validar(self) -> str | None:
        if self.opcao_intervalos.isChecked():
            if not self.campo_intervalos.text().strip():
                return ""  # campo ainda vazio: desativa o botão sem mostrar erro
            try:
                dividir.partes_por_intervalos(self.campo_intervalos.text(), self.info.paginas, "")
            except ErroUnePDF as erro:
                return str(erro)
        return None

    def tarefa(self) -> Tarefa:
        origem, destino = self.origem, self.destino()
        if self.opcao_intervalos.isChecked():
            texto = self.campo_intervalos.text()
            return lambda p, c: dividir.dividir_por_intervalos(origem, texto, destino, p, c)
        if self.opcao_a_cada.isChecked():
            n = self.campo_a_cada.value()
            return lambda p, c: dividir.dividir_a_cada(origem, n, destino, p, c)
        return lambda p, c: dividir.dividir_por_marcadores(origem, destino, p, c)

    def resumo(self, resultado: Resultado) -> str:
        return (
            f"{plural(resultado.arquivos, 'arquivo criado', 'arquivos criados')} com "
            f"{plural(resultado.paginas, 'página', 'páginas')} no total."
        )
