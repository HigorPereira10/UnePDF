"""Junção de vários PDFs em um único arquivo.

Regras:
    cada arquivo começa em uma página nova e mantém todas as suas páginas;
    cada arquivo vira um marcador no índice do PDF, com o nome do arquivo;
    arquivos inválidos são pulados e devolvidos no resultado, sem interromper o processo;
    os arquivos de origem nunca são alterados nem apagados;
    um resultado anterior com o mesmo nome é substituído, gerado do zero;
    opcionalmente, arquivos com conteúdo idêntico a um anterior são pulados (comparação por hash);
    opcionalmente, o PDF começa com uma capa que lista os arquivos e a página de cada um.
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from pypdf import PdfWriter

from unepdf.core.capa import ALTURA, LARGURA, desenhar_capa, paginas_da_capa
from unepdf.core.erros import ErroUnePDF
from unepdf.core.gravacao import gravar_com_seguranca
from unepdf.core.leitor_pdf import PdfInvalido, ler_pdf, tem_assinatura
from unepdf.core.modelos import ArquivoIgnorado, Resultado
from unepdf.core.progresso import CallbackProgresso, Cancelamento

log = logging.getLogger(__name__)


def unir(
    arquivos: list[Path],
    destino: Path,
    progresso: CallbackProgresso | None = None,
    cancelamento: Cancelamento | None = None,
    *,
    pular_repetidos: bool = False,
    capa: bool = False,
    marcadores: list[str] | None = None,
) -> Resultado:
    """Gera o PDF unido em `destino` e retorna o resumo da operação.

    O progresso conta um passo por arquivo lido e um passo final de gravação.
    `marcadores` troca o nome do arquivo pelo texto do marcador de cada um, na mesma ordem.
    """
    if not arquivos:
        raise ErroUnePDF("Nenhum PDF encontrado para unir.")

    total_passos = len(arquivos) + 1
    escritor = PdfWriter()
    ignorados: list[ArquivoIgnorado] = []
    vistos: dict[bytes, Path] = {}
    # Nome de cada arquivo unido e a página onde ele começa, para a capa
    inicios: list[tuple[str, int]] = []
    assinados = 0
    if capa:
        # A primeira página da capa e o seu marcador vêm antes de tudo; se o índice precisar
        # de mais páginas, elas entram no final, logo depois desta
        escritor.add_blank_page(LARGURA, ALTURA)
        escritor.add_outline_item("Índice", 0)

    for posicao, caminho in enumerate(arquivos, start=1):
        if cancelamento:
            cancelamento.verificar()
        if progresso:
            progresso(posicao, total_passos, caminho.name)
        try:
            leitor, dados = ler_pdf(caminho)
            assinados += tem_assinatura(leitor)
            if pular_repetidos:
                assinatura = hashlib.sha256(dados).digest()
                if assinatura in vistos:
                    motivo = f'conteúdo repetido, igual ao de "{vistos[assinatura].name}"'
                    ignorados.append(ArquivoIgnorado(caminho, motivo))
                    continue
                vistos[assinatura] = caminho
            inicio = len(escritor.pages)
            titulo = marcadores[posicao - 1] if marcadores else caminho.stem
            escritor.append(leitor, outline_item=titulo)
            inicios.append((titulo, inicio))
        except PdfInvalido as erro:
            ignorados.append(ArquivoIgnorado(caminho, str(erro)))
        except Exception:
            # Falha inesperada ao copiar as páginas: trata como arquivo ruim e segue para o próximo
            log.exception("Falha ao copiar as páginas de %s", caminho)
            ignorados.append(ArquivoIgnorado(caminho, "arquivo corrompido ou ilegível"))

    for ignorado in ignorados:
        log.warning("Ignorado: %s (%s)", ignorado.caminho, ignorado.motivo)

    if not inicios:
        raise ErroUnePDF(
            "Nenhum dos PDFs pôde ser lido, então o arquivo final não foi gerado.",
            ignorados,
        )

    if capa:
        _incluir_capa(escritor, destino.stem, inicios)

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

    log.info("PDF unido: %s (%d arquivos, %d ignorados)", destino, len(inicios), len(ignorados))
    return Resultado(
        destino=destino,
        arquivos=len(inicios),
        paginas=len(escritor.pages),
        substituiu_anterior=substituiu,
        ignorados=ignorados,
        observacao=(
            f"{assinados} arquivo(s) tinham assinatura digital, que não vale no PDF unido: "
            "assine o resultado de novo, se precisar." if assinados else ""
        ),
    )


def _incluir_capa(escritor: PdfWriter, titulo: str, inicios: list[tuple[str, int]]) -> None:
    """Completa as páginas do índice, que ficam logo depois da primeira, já criada."""
    extras = paginas_da_capa(len(inicios)) - 1
    for _ in range(extras):
        escritor.insert_blank_page(LARGURA, ALTURA, index=1)
    deslocados = [(nome, inicio + extras) for nome, inicio in inicios]
    desenhar_capa(escritor, titulo, deslocados, len(escritor.pages))
