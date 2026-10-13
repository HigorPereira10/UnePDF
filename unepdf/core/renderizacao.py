"""Desenho das páginas como imagem e extração de texto, usando o PDFium.

O resultado são bytes crus no formato BGRX (4 bytes por pixel), sem depender de nenhuma
biblioteca de interface: a camada ui converte para QImage, e a conversão para arquivo usa a Pillow.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass

import pypdfium2 as pdfium

from unepdf.core.erros import ErroUnePDF

# O PDFium não pode ser usado por duas threads ao mesmo tempo (ex.: miniaturas sendo geradas
# enquanto outra ferramenta converte páginas). Todo acesso a ele passa por esta trava.
_trava_pdfium = threading.Lock()


@dataclass(frozen=True)
class ImagemPagina:
    dados: bytes  # BGRX, linha por linha
    largura: int
    altura: int
    bytes_por_linha: int


class DocumentoRenderizavel:
    """PDF aberto para desenhar páginas. Use com `with` para liberar a memória no final."""

    def __init__(self, dados: bytes):
        with _trava_pdfium:
            try:
                self._documento = pdfium.PdfDocument(dados)
            except pdfium.PdfiumError as erro:
                raise ErroUnePDF("Não foi possível desenhar as páginas deste PDF.") from erro
            self.total = len(self._documento)

    def __enter__(self) -> DocumentoRenderizavel:
        return self

    def __exit__(self, *_) -> None:
        self.fechar()

    def fechar(self) -> None:
        with _trava_pdfium:
            self._documento.close()

    def renderizar(self, indice: int, largura: int | None = None, dpi: float | None = None) -> ImagemPagina:
        """Desenha a página com `largura` pixels (miniaturas) ou na resolução `dpi` (conversão).

        A rotação da própria página já é aplicada. O fundo é branco, como no papel.
        """
        with _trava_pdfium:
            pagina = self._documento[indice]
            try:
                largura_pontos, _ = pagina.get_size()
                escala = largura / largura_pontos if largura else (dpi or 72) / 72
                bitmap = pagina.render(scale=escala, fill_color=(255, 255, 255, 255), prefer_bgrx=True)
                return ImagemPagina(bytes(bitmap.buffer), bitmap.width, bitmap.height, bitmap.stride)
            finally:
                pagina.close()

    def extrair_texto(self, indice: int) -> str:
        """Texto selecionável da página, na ordem de leitura. Vazio em páginas escaneadas."""
        with _trava_pdfium:
            pagina = self._documento[indice]
            texto_pagina = pagina.get_textpage()
            try:
                return texto_pagina.get_text_range().replace("\r\n", "\n").replace("\r", "\n")
            finally:
                texto_pagina.close()
                pagina.close()
