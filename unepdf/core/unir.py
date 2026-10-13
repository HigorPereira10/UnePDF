"""Junção de vários PDFs em um único arquivo.

Regras:
    cada arquivo começa em uma página nova e mantém todas as suas páginas;
    cada arquivo vira um marcador no índice do PDF, com o nome do arquivo;
    arquivos inválidos são pulados e devolvidos no resultado, sem interromper o processo;
    os arquivos de origem nunca são alterados nem apagados;
    um resultado anterior com o mesmo nome é substituído, gerado do zero.
"""
from __future__ import annotations

import logging
from pathlib import Path

from pypdf import PdfWriter

from unepdf.core.erros import ErroUnePDF
from unepdf.core.gravacao import gravar_com_seguranca
from unepdf.core.leitor_pdf import PdfInvalido, abrir_pdf
from unepdf.core.modelos import ArquivoIgnorado, Resultado
from unepdf.core.progresso import CallbackProgresso, Cancelamento

log = logging.getLogger(__name__)


def unir(
    arquivos: list[Path],
    destino: Path,
    progresso: CallbackProgresso | None = None,
    cancelamento: Cancelamento | None = None,
) -> Resultado:
    """Gera o PDF unido em `destino` e retorna o resumo da operação.

    O progresso conta um passo por arquivo lido e um passo final de gravação.
    """
    if not arquivos:
        raise ErroUnePDF("Nenhum PDF encontrado para unir.")

    total_passos = len(arquivos) + 1
    escritor = PdfWriter()
    ignorados: list[ArquivoIgnorado] = []
    unidos = 0

    for posicao, caminho in enumerate(arquivos, start=1):
        if cancelamento:
            cancelamento.verificar()
        if progresso:
            progresso(posicao, total_passos, caminho.name)
        try:
            leitor = abrir_pdf(caminho)
            escritor.append(leitor, outline_item=caminho.stem)
            unidos += 1
        except PdfInvalido as erro:
            ignorados.append(ArquivoIgnorado(caminho, str(erro)))
        except Exception:
            # Falha inesperada ao copiar as páginas: trata como arquivo ruim e segue para o próximo
            log.exception("Falha ao copiar as páginas de %s", caminho)
            ignorados.append(ArquivoIgnorado(caminho, "arquivo corrompido ou ilegível"))

    for ignorado in ignorados:
        log.warning("Ignorado: %s (%s)", ignorado.caminho, ignorado.motivo)

    if unidos == 0:
        raise ErroUnePDF(
            "Nenhum dos PDFs pôde ser lido, então o arquivo final não foi gerado.",
            ignorados,
        )

    # Faz o leitor de PDF abrir o arquivo já mostrando o índice de arquivos
    escritor.page_mode = "/UseOutlines"

    if cancelamento:
        cancelamento.verificar()
    if progresso:
        progresso(total_passos, total_passos, f"Gravando {destino.name}")
    try:
        substituiu = gravar_com_seguranca(destino, escritor.write)
    except ErroUnePDF:
        raise
    except Exception as erro:
        raise ErroUnePDF(
            "Não foi possível gerar o PDF final. Algum dos arquivos tem conteúdo danificado "
            "que só apareceu na gravação."
        ) from erro

    log.info("PDF unido: %s (%d arquivos, %d ignorados)", destino, unidos, len(ignorados))
    return Resultado(
        destino=destino,
        arquivos=unidos,
        paginas=len(escritor.pages),
        substituiu_anterior=substituiu,
        ignorados=ignorados,
    )
