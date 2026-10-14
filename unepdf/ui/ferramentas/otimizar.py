"""Ferramenta de otimização: comprimir PDF."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtWidgets import QButtonGroup, QLabel, QRadioButton, QVBoxLayout, QWidget

from unepdf.core import ghostscript
from unepdf.core.comprimir import NivelCompressao, comprimir
from unepdf.core.leitor_pdf import abrir_pdf_ou_erro
from unepdf.core.modelos import Resultado
from unepdf.core.nomenclatura import destino_derivado
from unepdf.ui.executor import Tarefa
from unepdf.ui.ferramentas.arquivo_unico import TelaArquivoUnico
from unepdf.utils.texto import plural, tamanho_legivel


@dataclass
class InfoCompressao:
    paginas: int
    tamanho: int


def _ajuda(texto: str = "") -> QLabel:
    rotulo = QLabel(texto)
    rotulo.setObjectName("subtitulo")
    rotulo.setWordWrap(True)
    return rotulo


class TelaComprimir(TelaArquivoUnico):
    dica_area = "Reduza o tamanho do PDF para enviar por e-mail ou guardar."
    texto_botao = "Comprimir PDF"
    titulo_progresso = "Comprimindo o PDF..."
    titulo_sucesso = "PDF comprimido!"
    texto_novo = "Comprimir outro PDF"

    def carregar(self, origem: Path) -> InfoCompressao:
        return InfoCompressao(len(abrir_pdf_ou_erro(origem).pages), origem.stat().st_size)

    def montar_opcoes(self) -> QWidget:
        self.opcao_sem_perda = QRadioButton("Sem perda de qualidade")
        self.opcao_recomendada = QRadioButton("Recomendada")
        self.opcao_forte = QRadioButton("Forte")
        self._niveis = QButtonGroup(self)
        for opcao in (self.opcao_sem_perda, self.opcao_recomendada, self.opcao_forte):
            self._niveis.addButton(opcao)
        self.opcao_recomendada.setChecked(True)
        self.ajuda_forte = _ajuda()

        painel = QWidget()
        layout = QVBoxLayout(painel)
        layout.setContentsMargins(0, 0, 0, 0)
        rotulo = QLabel("NÍVEL DE COMPRESSÃO")
        rotulo.setObjectName("rotuloCampo")
        layout.addWidget(rotulo)
        layout.addWidget(self.opcao_sem_perda)
        layout.addWidget(_ajuda("Reorganiza o arquivo e remove repetições. Nada muda na aparência."))
        layout.addSpacing(4)
        layout.addWidget(self.opcao_recomendada)
        layout.addWidget(_ajuda("Também reduz fotos e imagens grandes. Ótima para PDFs escaneados."))
        layout.addSpacing(4)
        layout.addWidget(self.opcao_forte)
        layout.addWidget(self.ajuda_forte)
        layout.addSpacing(8)
        layout.addWidget(_ajuda(
            "PDFs só com texto, como a maioria das notas fiscais, já são pequenos e quase não diminuem."
        ))
        layout.addStretch()
        return painel

    def preencher_opcoes(self, info: InfoCompressao) -> None:
        motivo = ghostscript.disponivel()
        self.opcao_forte.setEnabled(motivo is None)
        if motivo:
            self.ajuda_forte.setText(
                "Precisa do Ghostscript, que não foi encontrado neste computador (gratuito, em ghostscript.com)."
            )
            if self.opcao_forte.isChecked():
                self.opcao_recomendada.setChecked(True)
        else:
            self.ajuda_forte.setText("Reprocessa o arquivo inteiro com o Ghostscript. É a que mais reduz.")

    def descrever(self, info: InfoCompressao) -> str:
        return f"{plural(info.paginas, 'página', 'páginas')}, {tamanho_legivel(info.tamanho)}"

    def destino(self) -> Path:
        return destino_derivado(self.origem, "comprimido", self.contexto.config.pasta_saida)

    def tarefa(self) -> Tarefa:
        origem, destino = self.origem, self.destino()
        if self.opcao_forte.isChecked():
            nivel = NivelCompressao.FORTE
        elif self.opcao_sem_perda.isChecked():
            nivel = NivelCompressao.SEM_PERDA
        else:
            nivel = NivelCompressao.RECOMENDADA
        return lambda p, c: comprimir(origem, destino, nivel, p, c)

    def resumo(self, resultado: Resultado) -> str:
        return "Compressão concluída."
