"""Regras de nome e local do PDF unificado."""
from __future__ import annotations

import re
from enum import StrEnum
from pathlib import Path

from unepdf.constantes import PASTA_SAIDA_PADRAO

# Caracteres que o Windows não aceita em nomes de arquivo e de pasta
CARACTERES_INVALIDOS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# Pastas de tipo de documento usadas no perfil Notas fiscais
TIPOS_DOCUMENTO = ("DANFSE", "DANFE", "DANFCE", "DACTE")

# Pasta de competência no formato MMAAAA (ex.: 012026)
PADRAO_COMPETENCIA = re.compile(r"^\d{6}$")


class Perfil(StrEnum):
    """Regra usada para dar nome ao PDF unificado."""

    GENERICO = "generico"
    NOTAS_FISCAIS = "notas_fiscais"


def limpar_nome(texto: str) -> str:
    """Troca caracteres proibidos por hífen e remove espaços e pontos nas pontas."""
    return CARACTERES_INVALIDOS.sub("-", texto).strip(" .")


def nome_saida(base: Path, perfil: Perfil = Perfil.GENERICO) -> str:
    """Nome do arquivo final para a pasta `base`.

    Perfil genérico: "<nome da pasta> - UNIFICADO.pdf".
    Perfil Notas fiscais, quando a pasta é uma competência:
        ...\\DANFE\\0001-EMPRESA EXEMPLO LTDA\\012026
            -> "DANFE - 0001-EMPRESA EXEMPLO LTDA - 012026.pdf"
        ...\\DANFSE\\0002-EXEMPLO SERVICOS S\\S LTDA\\012026  (barra do "S/S" virou subpasta)
            -> "DANFSE - 0002-EXEMPLO SERVICOS S-S LTDA - 012026.pdf"
    Fora do padrão de competência, o perfil Notas fiscais usa a regra genérica.
    """
    if perfil is not Perfil.NOTAS_FISCAIS or not PADRAO_COMPETENCIA.match(base.name):
        return f"{limpar_nome(base.name) or 'PDF'} - UNIFICADO.pdf"

    partes = base.parts

    # Procura, subindo a partir da competência, a pasta que indica o tipo de documento
    idx_tipo = next(
        (i for i in range(len(partes) - 2, -1, -1) if partes[i].upper() in TIPOS_DOCUMENTO),
        None,
    )

    if idx_tipo is None:
        # Tem competência mas não tem tipo: usa a pasta imediatamente acima como empresa
        pedacos = [partes[-2] if len(partes) > 1 else "", base.name]
    else:
        # Tudo entre o tipo e a competência é o nome da empresa, mesmo que tenha virado várias pastas
        empresa = "-".join(partes[idx_tipo + 1 : -1])
        pedacos = [partes[idx_tipo].upper(), empresa, base.name]

    return " - ".join(limpo for limpo in map(limpar_nome, pedacos) if limpo) + ".pdf"


def destino_padrao(
    base: Path,
    perfil: Perfil = Perfil.GENERICO,
    pasta_saida: str = PASTA_SAIDA_PADRAO,
) -> Path:
    """Caminho completo do PDF unificado: <pasta base>\\<pasta de saída>\\<nome>.pdf"""
    return base / pasta_saida / nome_saida(base, perfil)


def pasta_resultado(origem: Path, pasta_saida: str = PASTA_SAIDA_PADRAO) -> Path:
    """Pasta onde fica o resultado de uma ferramenta que trabalha com um arquivo só.

    Normalmente é a subpasta de saída ao lado do original. Se o original já está dentro dela
    (ex.: dividir um PDF unificado), o resultado fica na mesma pasta, sem criar outra dentro.
    """
    if origem.parent.name.casefold() == pasta_saida.casefold():
        return origem.parent
    return origem.parent / pasta_saida


def destino_derivado(origem: Path, sufixo: str, pasta_saida: str = PASTA_SAIDA_PADRAO, extensao: str = ".pdf") -> Path:
    """Ex.: C:\\Notas\\contrato.pdf + "protegido" -> C:\\Notas\\UnePDF\\contrato - protegido.pdf"""
    return pasta_resultado(origem, pasta_saida) / f"{origem.stem} - {sufixo}{extensao}"
