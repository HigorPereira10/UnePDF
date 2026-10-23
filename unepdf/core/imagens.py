"""Conversão de imagens (JPG, PNG, TIFF e outras) em PDF, sem perda de qualidade.

O JPG entra no PDF exatamente como está no arquivo, sem ser comprimido de novo. Os demais
formatos são gravados com compressão sem perda (a mesma usada pelo PNG). A Pillow é usada só
para ler as imagens; o PDF é montado direto com o pypdf.
"""
from __future__ import annotations

import io
import logging
import zlib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError
from pypdf import PdfWriter
from pypdf.generic import ArrayObject, DecodedStreamObject, DictionaryObject, EncodedStreamObject, NameObject, NumberObject

from unepdf.core.erros import ErroUnePDF
from unepdf.core.gravacao import gravar_com_seguranca
from unepdf.core.localizador import FORMATOS_IMAGEM
from unepdf.core.modelos import ArquivoIgnorado, Resultado
from unepdf.core.progresso import CallbackProgresso, Cancelamento

log = logging.getLogger(__name__)

A4 = (595.28, 841.89)  # em pontos (1/72 de polegada)
MARGEM_A4 = 18  # cerca de 6 mm
DPI_SEM_INFORMACAO = 96  # resolução assumida para imagens que não informam a sua (ex.: prints de tela)

# Pillow não deixa abrir imagens gigantes por segurança; documentos escaneados nunca chegam perto
Image.MAX_IMAGE_PIXELS = 300_000_000


class TamanhoPagina(StrEnum):
    A4 = "a4"  # a imagem é ajustada a uma folha A4, em pé ou deitada conforme o formato dela
    IMAGEM = "imagem"  # a página fica do tamanho da imagem, conforme a resolução dela


@dataclass
class _ImagemPdf:
    """Imagem pronta para entrar no PDF: o objeto de imagem e o tamanho em pixels já na posição de exibição."""

    objeto: EncodedStreamObject
    largura: int  # largura exibida, em pixels (já considerando a orientação da foto)
    altura: int
    dpi: tuple[float, float]
    # Orientação gravada pela câmera (1 normal, 3 de ponta-cabeça, 6 e 8 de lado); usada só no JPG original
    orientacao_exif: int = 1


class ImagemInvalida(ValueError):
    """Imagem que não pode ser usada. A mensagem é o motivo exibido ao usuário."""


def _fluxo(dados: bytes, filtro: str, largura: int, altura: int, cores: str, bits: int = 8) -> EncodedStreamObject:
    fluxo = EncodedStreamObject()
    fluxo._data = dados
    fluxo.update({
        NameObject("/Type"): NameObject("/XObject"),
        NameObject("/Subtype"): NameObject("/Image"),
        NameObject("/Width"): NumberObject(largura),
        NameObject("/Height"): NumberObject(altura),
        NameObject("/ColorSpace"): NameObject(cores),
        NameObject("/BitsPerComponent"): NumberObject(bits),
        NameObject("/Filter"): NameObject(filtro),
    })
    return fluxo


def _dpi(imagem: Image.Image) -> tuple[float, float]:
    dpi = imagem.info.get("dpi")
    try:
        x, y = float(dpi[0]), float(dpi[1])
        if x >= 10 and y >= 10:  # alguns programas gravam 1 ou 0 quando não sabem a resolução
            return x, y
    except (TypeError, ValueError, IndexError):
        pass
    return DPI_SEM_INFORMACAO, DPI_SEM_INFORMACAO


def _jpeg_original(dados: bytes, imagem: Image.Image) -> _ImagemPdf | None:
    """Usa os bytes do JPG sem recomprimir. None quando não dá (ex.: foto espelhada pela câmera)."""
    cores = {"RGB": "/DeviceRGB", "L": "/DeviceGray", "CMYK": "/DeviceCMYK"}.get(imagem.mode)
    orientacao = imagem.getexif().get(0x0112, 1)  # tag Orientation do EXIF
    if cores is None or orientacao not in (1, 3, 6, 8):
        return None
    fluxo = _fluxo(dados, "/DCTDecode", imagem.width, imagem.height, cores)
    if imagem.mode == "CMYK" and "adobe" in imagem.info:
        # JPGs CMYK gravados por programas da Adobe guardam as cores invertidas
        fluxo[NameObject("/Decode")] = ArrayObject([NumberObject(v) for v in (1, 0) * 4])
    largura, altura = (imagem.height, imagem.width) if orientacao in (6, 8) else (imagem.width, imagem.height)
    return _ImagemPdf(fluxo, largura, altura, _dpi(imagem), orientacao)


def _pixels_sem_perda(imagem: Image.Image, dpi: tuple[float, float], escritor: PdfWriter) -> _ImagemPdf:
    """Grava os pixels com compressão sem perda. A transparência vira uma máscara (fundo branco no papel)."""
    imagem = ImageOps.exif_transpose(imagem)
    mascara = None
    if imagem.mode in ("RGBA", "LA", "PA") or (imagem.mode == "P" and "transparency" in imagem.info):
        imagem = imagem.convert("RGBA")
        alfa = imagem.getchannel("A")
        if alfa.getextrema() != (255, 255):  # só cria máscara se houver transparência de verdade
            mascara = _fluxo(zlib.compress(alfa.tobytes()), "/FlateDecode", *alfa.size, "/DeviceGray")
        imagem = imagem.convert("RGB")
    elif imagem.mode not in ("1", "L", "RGB", "CMYK"):
        imagem = imagem.convert("L" if imagem.mode.startswith(("I", "F")) else "RGB")

    cores = {"1": "/DeviceGray", "L": "/DeviceGray", "RGB": "/DeviceRGB", "CMYK": "/DeviceCMYK"}[imagem.mode]
    bits = 1 if imagem.mode == "1" else 8  # preto e branco (comum em TIFF escaneado) fica bem menor
    fluxo = _fluxo(zlib.compress(imagem.tobytes()), "/FlateDecode", *imagem.size, cores, bits)
    if mascara is not None:
        fluxo[NameObject("/SMask")] = escritor._add_object(mascara)
    return _ImagemPdf(fluxo, imagem.width, imagem.height, dpi)


def _ler_imagens(caminho: Path, escritor: PdfWriter) -> list[_ImagemPdf]:
    """Todas as imagens de um arquivo (um TIFF pode ter várias páginas)."""
    try:
        dados = caminho.read_bytes()
    except OSError as erro:
        raise ImagemInvalida(f"não foi possível ler o arquivo ({erro.strerror or erro})") from erro
    if not dados:
        raise ImagemInvalida("arquivo vazio (0 KB)")
    with Image.open(io.BytesIO(dados), formats=FORMATOS_IMAGEM) as imagem:
        if imagem.format == "JPEG":
            original = _jpeg_original(dados, imagem)
            if original:
                return [original]
        quadros = []
        for numero in range(getattr(imagem, "n_frames", 1)):
            imagem.seek(numero)
            quadros.append(_pixels_sem_perda(imagem.copy(), _dpi(imagem), escritor))
        return quadros


def _matriz(imagem: _ImagemPdf, x: float, y: float, largura: float, altura: float) -> str:
    """Matriz do PDF que desenha a imagem na caixa indicada, girando conforme a orientação da foto."""
    matrizes = {
        1: (largura, 0, 0, altura, x, y),
        3: (-largura, 0, 0, -altura, x + largura, y + altura),
        6: (0, -altura, largura, 0, x, y + altura),
        8: (0, altura, -largura, 0, x + largura, y),
    }
    return " ".join(f"{v:.4f}" for v in matrizes[imagem.orientacao_exif])


def _adicionar_pagina(escritor: PdfWriter, imagem: _ImagemPdf, tamanho: TamanhoPagina) -> None:
    largura_natural = imagem.largura * 72 / imagem.dpi[0]
    altura_natural = imagem.altura * 72 / imagem.dpi[1]
    if tamanho is TamanhoPagina.IMAGEM:
        pagina_l, pagina_a = largura_natural, altura_natural
        x, y, largura, altura = 0, 0, largura_natural, altura_natural
    else:
        pagina_l, pagina_a = A4 if altura_natural >= largura_natural else (A4[1], A4[0])
        escala = min((pagina_l - 2 * MARGEM_A4) / largura_natural, (pagina_a - 2 * MARGEM_A4) / altura_natural)
        largura, altura = largura_natural * escala, altura_natural * escala
        x, y = (pagina_l - largura) / 2, (pagina_a - altura) / 2

    pagina = escritor.add_blank_page(pagina_l, pagina_a)
    pagina[NameObject("/Resources")] = DictionaryObject({
        NameObject("/XObject"): DictionaryObject({NameObject("/Im0"): escritor._add_object(imagem.objeto)}),
    })
    conteudo = DecodedStreamObject()
    conteudo.set_data(f"q {_matriz(imagem, x, y, largura, altura)} cm /Im0 Do Q".encode("ascii"))
    pagina[NameObject("/Contents")] = escritor._add_object(conteudo)


def imagens_para_pdf(
    arquivos: list[Path],
    destino: Path,
    tamanho: TamanhoPagina = TamanhoPagina.A4,
    progresso: CallbackProgresso | None = None,
    cancelamento: Cancelamento | None = None,
) -> Resultado:
    """Gera um PDF com uma página por imagem, na ordem da lista. Imagens ilegíveis são puladas."""
    if not arquivos:
        raise ErroUnePDF("Nenhuma imagem para converter.")

    escritor = PdfWriter()
    ignorados: list[ArquivoIgnorado] = []
    convertidas = 0
    total_passos = len(arquivos) + 1
    for posicao, caminho in enumerate(arquivos, start=1):
        if cancelamento:
            cancelamento.verificar()
        if progresso:
            progresso(posicao, total_passos, caminho.name)
        try:
            for imagem in _ler_imagens(caminho, escritor):
                _adicionar_pagina(escritor, imagem, tamanho)
            convertidas += 1
        except ImagemInvalida as erro:
            ignorados.append(ArquivoIgnorado(caminho, str(erro)))
        except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError):
            # A Pillow usa OSError e SyntaxError para imagens truncadas ou com cabeçalho inválido
            ignorados.append(ArquivoIgnorado(caminho, "imagem corrompida ou em formato não suportado"))
        except Exception:
            log.exception("Falha ao converter a imagem %s", caminho)
            ignorados.append(ArquivoIgnorado(caminho, "imagem corrompida ou em formato não suportado"))

    if convertidas == 0:
        raise ErroUnePDF("Nenhuma das imagens pôde ser lida, então o PDF não foi gerado.", ignorados)

    if cancelamento:
        cancelamento.verificar()
    if progresso:
        progresso(total_passos, total_passos, f"Gravando {destino.name}")
    substituiu = gravar_com_seguranca(destino, escritor.write)
    return Resultado(destino, convertidas, len(escritor.pages), substituiu, ignorados)
