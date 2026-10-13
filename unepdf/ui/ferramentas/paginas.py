"""Ferramentas que mostram as miniaturas das páginas: Organizar páginas e Extrair páginas."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from unepdf.core import dividir
from unepdf.core.erros import ErroUnePDF
from unepdf.core.leitor_pdf import ler_pdf_ou_erro
from unepdf.core.modelos import Resultado
from unepdf.core.nomenclatura import destino_derivado, pasta_resultado
from unepdf.core.paginas import descrever_intervalos, extrair, interpretar_paginas, reorganizar
from unepdf.ui.executor import Tarefa
from unepdf.ui.ferramentas.arquivo_unico import TelaArquivoUnico
from unepdf.ui.miniaturas import GradeMiniaturas
from unepdf.utils.texto import plural


@dataclass
class InfoPaginas:
    total: int
    dados: bytes  # o PDF já lido, para as miniaturas não lerem o arquivo de novo


def _ajuda(texto: str) -> QLabel:
    rotulo = QLabel(texto)
    rotulo.setObjectName("subtitulo")
    rotulo.setWordWrap(True)
    return rotulo


class _TelaComMiniaturas(TelaArquivoUnico):
    """Parte comum: carrega o PDF e mostra a grade de miniaturas."""

    editavel = False

    def carregar(self, origem: Path) -> InfoPaginas:
        leitor, dados = ler_pdf_ou_erro(origem)
        return InfoPaginas(len(leitor.pages), dados)

    def criar_grade(self) -> GradeMiniaturas:
        self.grade = GradeMiniaturas(self.editavel)
        self.grade.alterado.connect(self._ao_mudar)
        self.grade.itemSelectionChanged.connect(self._ao_mudar_selecao)
        return self.grade

    def preencher_opcoes(self, info: InfoPaginas) -> None:
        self.grade.carregar(info.dados, info.total)

    def descrever(self, info: InfoPaginas) -> str:
        return plural(info.total, "página", "páginas")

    def _ao_mudar(self, *_) -> None:
        self.atualizar_estado()

    def _ao_mudar_selecao(self) -> None:
        self.atualizar_estado()

    def limpar(self) -> None:
        self.grade.parar()
        super().limpar()

    def encerrar(self) -> None:
        self.grade.parar(aguardar=True)
        super().encerrar()


class TelaOrganizar(_TelaComMiniaturas):
    dica_area = "Reordene arrastando as miniaturas, gire e remova páginas."
    texto_botao = "Salvar PDF"
    titulo_progresso = "Salvando o PDF..."
    titulo_sucesso = "PDF organizado!"
    texto_novo = "Organizar outro PDF"
    editavel = True

    def montar_opcoes(self) -> QWidget:
        self.botao_girar_esquerda = QPushButton("↺  Girar à esquerda")
        self.botao_girar_esquerda.clicked.connect(lambda: self.grade.girar_selecionadas(-90))
        self.botao_girar_direita = QPushButton("↻  Girar à direita")
        self.botao_girar_direita.clicked.connect(lambda: self.grade.girar_selecionadas(90))
        self.botao_remover = QPushButton("Remover")
        self.botao_remover.clicked.connect(lambda: self.grade.remover_selecionadas())
        self.botao_restaurar = QPushButton("Desfazer tudo")
        self.botao_restaurar.clicked.connect(lambda: self.grade.restaurar())

        barra = QHBoxLayout()
        for botao in (self.botao_girar_esquerda, self.botao_girar_direita, self.botao_remover):
            barra.addWidget(botao)
        barra.addStretch()
        barra.addWidget(self.botao_restaurar)

        painel = QWidget()
        layout = QVBoxLayout(painel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(_ajuda(
            "Arraste as miniaturas para mudar a ordem. Selecione páginas (Ctrl ou Shift para várias) "
            "para girar ou remover. Pelo teclado: Delete remove e Ctrl+setas move."
        ))
        layout.addLayout(barra)
        layout.addWidget(self.criar_grade(), 1)
        return painel

    def atualizar_estado(self, aviso: str = "") -> None:
        if self.info is not None:
            tem_selecao = bool(self.grade.selectedItems())
            for botao in (self.botao_girar_esquerda, self.botao_girar_direita, self.botao_remover):
                botao.setEnabled(tem_selecao)
            self.botao_restaurar.setEnabled(self.grade.foi_alterada())
        super().atualizar_estado(aviso)

    def destino(self) -> Path:
        return destino_derivado(self.origem, "organizado", self.contexto.config.pasta_saida)

    def validar(self) -> str | None:
        if self.grade.count() == 0:
            return "Todas as páginas foram removidas. Deixe pelo menos uma."
        if not self.grade.foi_alterada():
            return ""  # nada para salvar ainda
        return None

    def tarefa(self) -> Tarefa:
        origem, destino, plano = self.origem, self.destino(), self.grade.plano()
        return lambda p, c: reorganizar(origem, plano, destino, p, c)

    def resumo(self, resultado: Resultado) -> str:
        return f"PDF salvo com {plural(resultado.paginas, 'página', 'páginas')}."


class TelaExtrair(_TelaComMiniaturas):
    dica_area = "Escolha as páginas que quer tirar do PDF clicando nas miniaturas ou digitando os números."
    texto_botao = "Extrair páginas"
    titulo_progresso = "Extraindo as páginas..."
    titulo_sucesso = "Páginas extraídas!"
    texto_novo = "Extrair de outro PDF"

    def montar_opcoes(self) -> QWidget:
        rotulo_paginas = QLabel("PÁGINAS")
        rotulo_paginas.setObjectName("rotuloCampo")
        self.campo_paginas = QLineEdit()
        self.campo_paginas.setPlaceholderText("Clique nas miniaturas ou digite, ex.: 1-3, 5")
        self.campo_paginas.setMaximumWidth(360)
        self.campo_paginas.textEdited.connect(self._ao_digitar)
        self._erro_digitacao: str | None = None

        self.opcao_um_pdf = QRadioButton("Um PDF com todas as páginas escolhidas")
        self.opcao_separadas = QRadioButton("Um PDF para cada página")
        self._modos = QButtonGroup(self)
        self._modos.addButton(self.opcao_um_pdf)
        self._modos.addButton(self.opcao_separadas)
        self._modos.buttonClicked.connect(self._ao_mudar)
        self.opcao_um_pdf.setChecked(True)

        linha = QHBoxLayout()
        linha.addWidget(self.campo_paginas)
        linha.addSpacing(20)
        linha.addWidget(self.opcao_um_pdf)
        linha.addWidget(self.opcao_separadas)
        linha.addStretch()

        painel = QWidget()
        layout = QVBoxLayout(painel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(rotulo_paginas)
        layout.addLayout(linha)
        layout.addWidget(_ajuda("As páginas são extraídas na ordem do documento."))
        layout.addWidget(self.criar_grade(), 1)
        return painel

    def preencher_opcoes(self, info: InfoPaginas) -> None:
        self.campo_paginas.clear()
        self._erro_digitacao = None
        super().preencher_opcoes(info)

    def _ao_digitar(self, texto: str) -> None:
        # Digitar seleciona as miniaturas; um texto incompleto ou errado só gera aviso
        self._erro_digitacao = None
        if texto.strip():
            try:
                self.grade.selecionar_indices(interpretar_paginas(texto, self.info.total))
            except ErroUnePDF as erro:
                self._erro_digitacao = str(erro)
        else:
            self.grade.selecionar_indices([])
        self.atualizar_estado()

    def _ao_mudar_selecao(self) -> None:
        # Clicar nas miniaturas atualiza o texto (o inverso de _ao_digitar)
        self._erro_digitacao = None
        self.campo_paginas.setText(descrever_intervalos(self.grade.indices_selecionados()))
        self.atualizar_estado()

    def destino(self) -> Path:
        pasta_saida = self.contexto.config.pasta_saida
        if self.opcao_separadas.isChecked():
            return pasta_resultado(self.origem, pasta_saida) / f"{self.origem.stem} - páginas extraídas"
        return destino_derivado(self.origem, "páginas extraídas", pasta_saida)

    def validar(self) -> str | None:
        if self._erro_digitacao:
            return self._erro_digitacao
        if not self.grade.indices_selecionados():
            return ""  # nenhuma página escolhida ainda
        return None

    def tarefa(self) -> Tarefa:
        origem, destino, paginas = self.origem, self.destino(), self.grade.indices_selecionados()
        if self.opcao_separadas.isChecked():
            self.texto_abrir = "Abrir pasta"
            return lambda p, c: dividir.separar_paginas(origem, paginas, destino, p, c)
        self.texto_abrir = "Abrir arquivo"
        return lambda p, c: extrair(origem, paginas, destino, p, c)

    def resumo(self, resultado: Resultado) -> str:
        if self.opcao_separadas.isChecked():
            return f"{plural(resultado.arquivos, 'arquivo criado', 'arquivos criados')}, um para cada página."
        return f"{plural(resultado.paginas, 'página extraída', 'páginas extraídas')} para um novo PDF."
