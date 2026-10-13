"""Localização dos PDFs de entrada, a partir de uma pasta ou de arquivos avulsos."""
from __future__ import annotations

import os
import re
from pathlib import Path

from unepdf.constantes import PASTA_SAIDA_PADRAO
from unepdf.core.erros import ErroUnePDF


def ordem_natural(caminho: Path) -> list:
    """Chave de ordenação que trata números como números (2.pdf antes de 10.pdf)."""
    return [int(parte) if parte.isdecimal() else parte.casefold() for parte in re.split(r"(\d+)", caminho.name)]


def eh_pdf(caminho: Path) -> bool:
    """Verdadeiro para arquivos com extensão .pdf, sem diferenciar maiúsculas."""
    return caminho.suffix.lower() == ".pdf" and caminho.is_file()


def eh_pasta_saida(pasta: Path, pasta_saida: str = PASTA_SAIDA_PADRAO) -> bool:
    """Indica se a pasta é a própria pasta de saída, que não pode ser usada como origem."""
    return pasta.name.casefold() == pasta_saida.casefold()


def listar_pdfs_da_pasta(pasta: Path, pasta_saida: str = PASTA_SAIDA_PADRAO) -> list[Path]:
    """Retorna os PDFs que estão diretamente na pasta, em ordem natural.

    A busca não entra em subpastas, então a pasta de saída (e qualquer outra) fica de fora.
    """
    if eh_pasta_saida(pasta, pasta_saida):
        raise ErroUnePDF(
            f'A pasta "{pasta.name}" é onde o UnePDF grava os resultados e não pode ser usada como origem.\n\n'
            "Escolha a pasta de cima."
        )
    try:
        return sorted((p for p in pasta.iterdir() if eh_pdf(p)), key=ordem_natural)
    except OSError as erro:
        raise ErroUnePDF(f"Não foi possível abrir a pasta:\n{pasta}\n\n{erro.strerror or erro}") from erro


def filtrar_pdfs_selecionados(arquivos: list[Path], pasta_saida: str = PASTA_SAIDA_PADRAO) -> list[Path]:
    """Limpa uma seleção manual de arquivos, em ordem natural.

    Remove o que não é PDF, duplicados e qualquer arquivo que esteja dentro
    da pasta de saída (para não juntar o próprio resultado).
    """
    unicos: dict[str, Path] = {}
    for caminho in arquivos:
        if eh_pdf(caminho) and not eh_pasta_saida(caminho.parent, pasta_saida):
            # O Windows não diferencia maiúsculas: "A.pdf" e "a.pdf" são o mesmo arquivo
            unicos.setdefault(os.path.normcase(caminho.resolve()), caminho)
    return sorted(unicos.values(), key=ordem_natural)


def pasta_base(arquivos: list[Path]) -> Path:
    """Pasta onde a subpasta de saída será criada.

    A seleção de arquivos do Windows só permite escolher dentro de uma pasta,
    então a pasta do primeiro arquivo representa toda a seleção.
    """
    return arquivos[0].parent
