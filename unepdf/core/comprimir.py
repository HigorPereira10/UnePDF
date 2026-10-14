"""Redução do tamanho de PDFs, em três níveis.

Sem perda: reorganiza o arquivo, sem mexer na qualidade de nada.
Recomendada: também reduz fotos e imagens grandes (funciona sem programas externos).
Forte: usa o Ghostscript, que reprocessa o arquivo inteiro e costuma reduzir bem mais.

PDFs só com texto (como a maioria das notas fiscais) já costumam ser pequenos e quase não diminuem.
"""
from __future__ import annotations

import io
import logging
from enum import StrEnum
from pathlib import Path

from PIL import Image
from pypdf import PdfWriter

from unepdf.core import ghostscript
from unepdf.core.gravacao import gravar_arquivo_gerado, gravar_com_seguranca
from unepdf.core.leitor_pdf import abrir_pdf_ou_erro
from unepdf.core.modelos import Resultado
from unepdf.core.progresso import CallbackProgresso, Cancelamento
from unepdf.utils.texto import tamanho_legivel

log = logging.getLogger(__name__)

LADO_MAXIMO = 2200  # pixels; uma folha A4 inteira a 200 dpi
QUALIDADE_JPG = 75
TAMANHO_MINIMO_IMAGEM = 50 * 1024  # imagens menores que isso não compensam


class NivelCompressao(StrEnum):
    SEM_PERDA = "sem_perda"
    RECOMENDADA = "recomendada"
    FORTE = "forte"  # exige o Ghostscript


def _reduzir_imagens(escritor: PdfWriter, cancelamento: Cancelamento | None) -> int:
    """Regrava como JPG as imagens grandes que ficam menores assim. Devolve quantas foram trocadas."""
    vistas: set[int] = set()
    trocadas = 0
    for pagina in escritor.pages:
        for imagem in pagina.images:
            if cancelamento:
                cancelamento.verificar()
            referencia = imagem.indirect_reference
            if referencia is None or referencia.idnum in vistas:
                continue  # imagem dentro do texto da página, ou já tratada em outra página
            vistas.add(referencia.idnum)
            objeto = referencia.get_object()
            # Transparência e preto e branco puro (escaneamento de texto) pioram como JPG
            if any(chave in objeto for chave in ("/SMask", "/Mask")) or objeto.get("/ImageMask"):
                continue
            if len(objeto.get_data() if hasattr(objeto, "get_data") else b"") < TAMANHO_MINIMO_IMAGEM:
                continue
            try:
                original = imagem.image
                if original.mode not in ("RGB", "L"):
                    continue
                reduzida = original.copy()
                reduzida.thumbnail((LADO_MAXIMO, LADO_MAXIMO), Image.Resampling.LANCZOS)
                teste = io.BytesIO()
                reduzida.save(teste, "JPEG", quality=QUALIDADE_JPG)
                if teste.tell() >= len(objeto._data) * 0.9:
                    continue  # não compensa trocar
                imagem.replace(reduzida, quality=QUALIDADE_JPG)
                trocadas += 1
            except Exception:
                # Uma imagem em formato incomum não pode impedir a compressão do resto
                log.debug("Imagem mantida como estava (objeto %s)", referencia.idnum, exc_info=True)
    return trocadas


def comprimir(
    origem: Path,
    destino: Path,
    nivel: NivelCompressao = NivelCompressao.RECOMENDADA,
    progresso: CallbackProgresso | None = None,
    cancelamento: Cancelamento | None = None,
) -> Resultado:
    nivel = NivelCompressao(nivel)
    tamanho_original = origem.stat().st_size if origem.exists() else 0
    leitor = abrir_pdf_ou_erro(origem)
    total = len(leitor.pages)

    if nivel is NivelCompressao.FORTE:
        argumentos_base = [
            "-sDEVICE=pdfwrite",
            "-dPDFSETTINGS=/ebook",  # imagens a 150 dpi: boa leitura na tela e impressão comum
            "-dCompatibilityLevel=1.5",
            "-dDetectDuplicateImages=true",
        ]
        substituiu = gravar_arquivo_gerado(
            destino,
            lambda temporario: ghostscript.executar(
                [*argumentos_base, f"-sOutputFile={temporario}", str(origem)], total, progresso, cancelamento
            ),
        )
    else:
        escritor = PdfWriter(clone_from=leitor)
        for indice, pagina in enumerate(escritor.pages):
            if cancelamento:
                cancelamento.verificar()
            if progresso:
                progresso(indice + 1, total + 1, f"Página {indice + 1}")
            pagina.compress_content_streams(level=9)
        if nivel is NivelCompressao.RECOMENDADA:
            _reduzir_imagens(escritor, cancelamento)
        # Por padrão remove objetos repetidos e os que não são usados por nenhuma página
        escritor.compress_identical_objects()
        if progresso:
            progresso(total + 1, total + 1, f"Gravando {destino.name}")
        substituiu = gravar_com_seguranca(destino, escritor.write)

    tamanho_final = destino.stat().st_size
    if tamanho_original and tamanho_final < tamanho_original:
        reducao = round(100 * (1 - tamanho_final / tamanho_original))
        observacao = (
            f"De {tamanho_legivel(tamanho_original)} para {tamanho_legivel(tamanho_final)} ({reducao}% menor)."
        )
    else:
        observacao = (
            f"O arquivo já estava bem compactado: o resultado ficou com {tamanho_legivel(tamanho_final)} "
            f"(o original tem {tamanho_legivel(tamanho_original)}). Prefira usar o original."
        )
    return Resultado(destino, 1, total, substituiu, observacao=observacao)
