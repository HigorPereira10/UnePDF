"""Localização dos arquivos de entrada, a partir de uma pasta ou de arquivos avulsos."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from unepdf.constantes import PASTA_SAIDA_PADRAO
from unepdf.core.erros import ErroUnePDF


@dataclass(frozen=True)
class TipoArquivo:
    """Extensões aceitas por uma ferramenta e os textos usados quando nada serve."""

    extensoes: tuple[str, ...]
    nenhum_na_pasta: str
    escolha: str


PDF = TipoArquivo((".pdf",), "Nenhum PDF encontrado", "Escolha arquivos PDF")
IMAGEM = TipoArquivo(
    (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"),
    "Nenhuma imagem encontrada",
    "Escolha imagens (JPG, PNG, TIFF, BMP ou WEBP)",
)


def ordem_natural(caminho: Path) -> list:
    """Chave de ordenação que trata números como números (2.pdf antes de 10.pdf)."""
    return [int(parte) if parte.isdecimal() else parte.casefold() for parte in re.split(r"(\d+)", caminho.name)]


class OrdemArquivos(StrEnum):
    NOME = "nome"
    DATA = "data"  # data de modificação, do mais antigo para o mais recente


def datas_modificacao(arquivos: list[Path]) -> dict[Path, float]:
    """Data de modificação de cada arquivo. Arquivos que não puderam ser consultados ficam de fora."""
    datas = {}
    for caminho in arquivos:
        try:
            datas[caminho] = caminho.stat().st_mtime
        except OSError:
            pass
    return datas


def ordenar(arquivos: list[Path], ordem: OrdemArquivos, datas: dict[Path, float] | None = None) -> list[Path]:
    """Arquivos na ordem escolhida. Na ordem por data, empates seguem o nome e os arquivos
    sem data conhecida vão para o fim."""
    por_nome = sorted(arquivos, key=ordem_natural)
    if OrdemArquivos(ordem) is OrdemArquivos.NOME:
        return por_nome
    if datas is None:
        datas = datas_modificacao(arquivos)
    return sorted(por_nome, key=lambda caminho: (caminho not in datas, datas.get(caminho, 0.0)))


def eh_do_tipo(caminho: Path, tipo: TipoArquivo) -> bool:
    """Verdadeiro para arquivos com uma das extensões do tipo, sem diferenciar maiúsculas."""
    return caminho.suffix.lower() in tipo.extensoes and caminho.is_file()


def eh_pdf(caminho: Path) -> bool:
    return eh_do_tipo(caminho, PDF)


def eh_pasta_saida(pasta: Path, pasta_saida: str = PASTA_SAIDA_PADRAO) -> bool:
    """Indica se a pasta é a própria pasta de saída, que não pode ser usada como origem."""
    return pasta.name.casefold() == pasta_saida.casefold()


def listar_pdfs_da_pasta(pasta: Path, pasta_saida: str = PASTA_SAIDA_PADRAO, tipo: TipoArquivo = PDF) -> list[Path]:
    """Retorna os arquivos do tipo que estão diretamente na pasta, em ordem natural.

    A busca não entra em subpastas, então a pasta de saída (e qualquer outra) fica de fora.
    """
    if eh_pasta_saida(pasta, pasta_saida):
        raise ErroUnePDF(
            f'A pasta "{pasta.name}" é onde o UnePDF grava os resultados e não pode ser usada como origem.\n\n'
            "Escolha a pasta de cima."
        )
    try:
        return sorted((p for p in pasta.iterdir() if eh_do_tipo(p, tipo)), key=ordem_natural)
    except OSError as erro:
        raise ErroUnePDF(f"Não foi possível abrir a pasta:\n{pasta}\n\n{erro.strerror or erro}") from erro


def filtrar_pdfs_selecionados(
    arquivos: list[Path], pasta_saida: str = PASTA_SAIDA_PADRAO, tipo: TipoArquivo = PDF
) -> list[Path]:
    """Limpa uma seleção manual de arquivos, em ordem natural.

    Remove o que não é do tipo, duplicados e qualquer arquivo que esteja dentro
    da pasta de saída (para não usar o próprio resultado como entrada).
    """
    unicos: dict[str, Path] = {}
    for caminho in arquivos:
        if eh_do_tipo(caminho, tipo) and not eh_pasta_saida(caminho.parent, pasta_saida):
            # O Windows não diferencia maiúsculas: "A.pdf" e "a.pdf" são o mesmo arquivo
            unicos.setdefault(os.path.normcase(caminho.resolve()), caminho)
    return sorted(unicos.values(), key=ordem_natural)


def pasta_base(arquivos: list[Path]) -> Path:
    """Pasta onde a subpasta de saída será criada.

    A seleção de arquivos do Windows só permite escolher dentro de uma pasta,
    então a pasta do primeiro arquivo representa toda a seleção.
    """
    return arquivos[0].parent


@dataclass
class Selecao:
    """Arquivos de entrada já validados, e a pasta onde o resultado será criado."""

    arquivos: list[Path]
    base: Path
    pasta: Path | None = None  # preenchida quando a seleção veio de uma pasta inteira
    descartados: int = 0  # itens da seleção manual que não são do tipo, repetidos ou da pasta de saída


def montar_selecao(
    caminhos: list[Path], pasta_saida: str = PASTA_SAIDA_PADRAO, tipo: TipoArquivo = PDF
) -> Selecao:
    """Interpreta o que o usuário escolheu ou arrastou: uma pasta, ou um conjunto de arquivos."""
    pastas = [c for c in caminhos if c.is_dir()]
    if pastas:
        if len(caminhos) > 1:
            raise ErroUnePDF("Escolha uma pasta por vez, ou então só arquivos.")
        pasta = pastas[0]
        arquivos = listar_pdfs_da_pasta(pasta, pasta_saida, tipo)
        if not arquivos:
            raise ErroUnePDF(
                f"{tipo.nenhum_na_pasta} direto na pasta:\n{pasta}\n\nArquivos dentro de subpastas não entram."
            )
        return Selecao(arquivos, pasta, pasta)

    arquivos = filtrar_pdfs_selecionados(caminhos, pasta_saida, tipo)
    if not arquivos:
        raise ErroUnePDF(
            "Nenhum dos arquivos escolhidos pode ser usado.\n\n"
            f'{tipo.escolha} que não estejam na pasta de saída ("{pasta_saida}").'
        )
    return Selecao(arquivos, pasta_base(arquivos), descartados=len(caminhos) - len(arquivos))


def pdf_unico(caminhos: list[Path]) -> Path:
    """O único PDF de uma seleção, para ferramentas que trabalham com um arquivo por vez."""
    if len(caminhos) != 1 or not eh_pdf(caminhos[0]):
        raise ErroUnePDF("Escolha um único arquivo PDF.")
    return caminhos[0]
