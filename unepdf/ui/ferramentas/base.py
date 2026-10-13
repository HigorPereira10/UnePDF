"""Tela-base das ferramentas: cabeçalho com ícone, nome e descrição, e área de conteúdo."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Callable

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from unepdf.ui.contexto import ContextoApp
from unepdf.ui.executor import Executor, Tarefa
from unepdf.utils.recursos import caminho_recurso

if TYPE_CHECKING:
    from unepdf.ui.ferramentas import Ferramenta


class TelaFerramenta(QWidget):
    """Cada ferramenta herda desta classe e monta a sua interface em `self.corpo`."""

    # Ferramentas que recebem arquivos arrastados para qualquer ponto da janela
    aceita_arquivos = False

    def __init__(self, ferramenta: Ferramenta, contexto: ContextoApp):
        super().__init__()
        self.ferramenta = ferramenta
        self.contexto = contexto
        self.executor = Executor(self)
        self._resposta_ok: Callable[[object], None] | None = None
        self._resposta_erro: Callable[[BaseException], None] | None = None
        self.executor.concluido.connect(lambda resultado: self._resposta_ok and self._resposta_ok(resultado))
        self.executor.falhou.connect(lambda erro: self._resposta_erro and self._resposta_erro(erro))

        icone = QLabel()
        icone.setPixmap(QIcon(str(caminho_recurso(ferramenta.icone))).pixmap(QSize(48, 48)))
        titulo = QLabel(ferramenta.nome)
        titulo.setObjectName("titulo")
        descricao = QLabel(ferramenta.descricao)
        descricao.setObjectName("subtitulo")
        descricao.setWordWrap(True)

        textos = QVBoxLayout()
        textos.setSpacing(2)
        textos.addWidget(titulo)
        textos.addWidget(descricao)
        cabecalho = QWidget()
        cabecalho.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        layout_cabecalho = QHBoxLayout(cabecalho)
        layout_cabecalho.setContentsMargins(0, 0, 0, 0)
        layout_cabecalho.setSpacing(16)
        layout_cabecalho.addWidget(icone, 0, Qt.AlignmentFlag.AlignTop)
        layout_cabecalho.addLayout(textos, 1)

        self.corpo = QVBoxLayout()
        self.corpo.setSpacing(14)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 32, 36, 28)
        layout.setSpacing(24)
        layout.addWidget(cabecalho)
        layout.addLayout(self.corpo, 1)
        # Ocupa a sobra só quando o corpo está vazio: com conteúdo, o corpo (fator 1) tem prioridade
        layout.addStretch(0)

    def executar(
        self,
        tarefa: Tarefa,
        ao_concluir: Callable[[object], None],
        ao_falhar: Callable[[BaseException], None],
    ) -> None:
        """Roda a tarefa em segundo plano; a resposta chega em `ao_concluir` ou `ao_falhar`, na thread da interface."""
        self._resposta_ok, self._resposta_erro = ao_concluir, ao_falhar
        self.executor.executar(tarefa)

    def receber_caminhos(self, caminhos: list[Path]) -> None:
        """Recebe arquivos ou pastas soltos na janela. Só é chamado se `aceita_arquivos` for True."""
        raise NotImplementedError
