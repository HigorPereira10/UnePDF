"""Conversão de PDF em outros formatos: imagens (PNG ou JPG) e texto."""
from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from PIL import Image

from unepdf.core.erros import ErroUnePDF
from unepdf.core.gravacao import gravar_com_seguranca, gravar_pasta_com_seguranca
from unepdf.core.leitor_pdf import ler_pdf_ou_erro
from unepdf.core.modelos import Resultado
from unepdf.core.progresso import CallbackProgresso, Cancelamento
from unepdf.core.renderizacao import DocumentoRenderizavel, ImagemPagina

QUALIDADE_JPG = 90


class FormatoImagem(StrEnum):
    PNG = "png"  # sem perda, ideal para documentos com texto
    JPG = "jpg"  # arquivos menores, ideal para fotos


def _para_pillow(imagem: ImagemPagina) -> Image.Image:
    return Image.frombuffer(
        "RGBX", (imagem.largura, imagem.altura), imagem.dados, "raw", "BGRX", imagem.bytes_por_linha, 1
    ).convert("RGB")


def pdf_para_imagens(
    origem: Path,
    pasta_destino: Path,
    formato: FormatoImagem = FormatoImagem.PNG,
    dpi: int = 150,
    paginas: list[int] | None = None,
    progresso: CallbackProgresso | None = None,
    cancelamento: Cancelamento | None = None,
) -> Resultado:
    """Grava uma imagem por página em `pasta_destino` (todas as páginas, ou só as indicadas)."""
    leitor, dados = ler_pdf_ou_erro(origem)
    total_paginas = len(leitor.pages)
    alvo = list(range(total_paginas)) if paginas is None else paginas
    if not alvo:
        raise ErroUnePDF("Escolha pelo menos uma página.")
    if invalidas := [p + 1 for p in alvo if not 0 <= p < total_paginas]:
        raise ErroUnePDF(f"A página {invalidas[0]} não existe: o PDF tem {total_paginas} página(s).")

    def escrever(pasta: Path) -> None:
        with DocumentoRenderizavel(dados) as documento:
            # Números com zeros à esquerda (01, 02...) mantêm a ordem certa no Explorer
            digitos = len(str(documento.total))
            for posicao, indice in enumerate(alvo, start=1):
                if cancelamento:
                    cancelamento.verificar()
                nome = f"{origem.stem} - página {indice + 1:0{digitos}}.{formato.value}"
                if progresso:
                    progresso(posicao, len(alvo), nome)
                imagem = _para_pillow(documento.renderizar(indice, dpi=dpi))
                if formato is FormatoImagem.JPG:
                    imagem.save(pasta / nome, "JPEG", quality=QUALIDADE_JPG, dpi=(dpi, dpi))
                else:
                    imagem.save(pasta / nome, "PNG", dpi=(dpi, dpi))

    substituiu = gravar_pasta_com_seguranca(pasta_destino, escrever)
    return Resultado(pasta_destino, len(alvo), len(alvo), substituiu)


def pdf_para_texto(
    origem: Path,
    destino: Path,
    separar_paginas: bool = True,
    progresso: CallbackProgresso | None = None,
    cancelamento: Cancelamento | None = None,
) -> Resultado:
    """Grava o texto selecionável do PDF em um arquivo .txt (UTF-8).

    PDFs escaneados não têm texto, só a imagem das páginas: nesse caso nada é gravado e o
    usuário recebe uma explicação. Páginas sem texto num PDF misto viram uma observação no resumo.
    """
    _, dados = ler_pdf_ou_erro(origem)
    partes = []
    sem_texto = 0
    with DocumentoRenderizavel(dados) as documento:
        for indice in range(documento.total):
            if cancelamento:
                cancelamento.verificar()
            if progresso:
                progresso(indice + 1, documento.total + 1, f"Página {indice + 1}")
            texto = documento.extrair_texto(indice).strip()
            if not texto:
                sem_texto += 1
            partes.append(f"===== Página {indice + 1} =====\n\n{texto}" if separar_paginas else texto)
        total = documento.total

    if sem_texto == total:
        raise ErroUnePDF(
            "Nenhum texto encontrado neste PDF.\n\n"
            "Isso costuma acontecer com PDFs escaneados, que guardam só a imagem das páginas."
        )

    conteudo = "\n\n".join(partes).strip() + "\n"
    if progresso:
        progresso(total + 1, total + 1, f"Gravando {destino.name}")
    # Com a marca BOM, o Bloco de Notas e o Excel antigos reconhecem os acentos corretamente
    substituiu = gravar_com_seguranca(destino, lambda arquivo: arquivo.write(conteudo.encode("utf-8-sig")))
    observacao = f"{sem_texto} página(s) não tinham texto (provavelmente escaneadas)." if sem_texto else ""
    return Resultado(destino, 1, total, substituiu, observacao=observacao)
