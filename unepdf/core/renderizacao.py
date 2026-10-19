"""Desenho das páginas como imagem e extração de texto, usando o PDFium.

O resultado são bytes crus no formato BGRX (4 bytes por pixel), sem depender de nenhuma
biblioteca de interface: a camada ui converte para QImage, e a conversão para arquivo usa a Pillow.
"""
from __future__ import annotations

import re
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
                # Sem isso o PDFium não desenha campos de formulário, como o carimbo de uma assinatura
                self._documento.init_forms()
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

    def texto_com_posicoes(self, indice: int) -> tuple[str, list[tuple[float, float, float, float]] | None]:
        """Texto da página e a caixa (esquerda, base, direita, topo) de cada caractere, na mesma ordem.

        As caixas voltam None quando não batem um a um com o texto, o que acontece com alguns PDFs.
        """
        with _trava_pdfium:
            pagina = self._documento[indice]
            texto_pagina = pagina.get_textpage()
            try:
                total = texto_pagina.count_chars()
                texto = texto_pagina.get_text_range(0, total)
                if len(texto) != total:
                    return texto, None
                return texto, [texto_pagina.get_charbox(i) for i in range(total)]
            finally:
                texto_pagina.close()
                pagina.close()

    def caixa_visivel(self, indice: int) -> tuple[float, float, float, float]:
        """Área visível da página (esquerda, base, direita, topo), em pontos, sem considerar a rotação."""
        with _trava_pdfium:
            pagina = self._documento[indice]
            try:
                return tuple(pagina.get_cropbox())
            finally:
                pagina.close()

    def rotacao(self, indice: int) -> int:
        with _trava_pdfium:
            pagina = self._documento[indice]
            try:
                return pagina.get_rotation()
            finally:
                pagina.close()

    def linhas_de_assinatura(self, indice: int, minimo: int = 8) -> list[tuple[float, float, float, float]]:
        """Caixas das sequências de sublinhados ("________") da página, que marcam onde assinar."""
        with _trava_pdfium:
            pagina = self._documento[indice]
            texto_pagina = pagina.get_textpage()
            try:
                total = texto_pagina.count_chars()
                texto = texto_pagina.get_text_range(0, total)
                linhas = []
                for sequencia in re.finditer(rf"_{{{minimo},}}", texto):
                    caixas = [texto_pagina.get_charbox(i) for i in range(sequencia.start(), min(sequencia.end(), total))]
                    if caixas:
                        linhas.append((
                            min(c[0] for c in caixas), min(c[1] for c in caixas),
                            max(c[2] for c in caixas), max(c[3] for c in caixas),
                        ))
                return linhas
            finally:
                texto_pagina.close()
                pagina.close()
