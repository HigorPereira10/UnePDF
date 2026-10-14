"""Texto desenhado sobre as páginas: marca d'água e numeração.

O texto usa a fonte Helvetica, que todo leitor de PDF já tem, então nada precisa ser embutido
no arquivo. Ela cobre as letras acentuadas do português; caracteres fora dela viram "?".
"""
from __future__ import annotations

import math
import unicodedata
from enum import StrEnum
from pathlib import Path
from typing import Callable

from pypdf import PageObject, PdfWriter
from pypdf.generic import (
    DecodedStreamObject,
    DictionaryObject,
    FloatObject,
    IndirectObject,
    NameObject,
    RectangleObject,
)

from unepdf.core.erros import ErroUnePDF
from unepdf.core.gravacao import gravar_com_seguranca
from unepdf.core.leitor_pdf import abrir_pdf_ou_erro
from unepdf.core.modelos import Resultado
from unepdf.core.progresso import CallbackProgresso, Cancelamento

# Larguras da Helvetica em milésimos do tamanho da fonte (tabela oficial da fonte padrão do PDF).
# Letras acentuadas têm a mesma largura da letra sem acento.
_CARACTERES = " !\"#$%&'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`abcdefghijklmnopqrstuvwxyz{|}~"
_LARGURAS = dict(zip(_CARACTERES, [
    278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278,
    556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556, 1015,
    667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778, 667, 778, 722, 667, 611,
    722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556, 333,
    556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556, 556, 556, 333, 500, 278,
    556, 500, 722, 500, 500, 500, 334, 260, 334, 584,
]))
MARGEM = 28  # cerca de 1 cm


class TamanhoMarca(StrEnum):
    PEQUENO = "pequeno"
    MEDIO = "medio"
    GRANDE = "grande"


_PROPORCAO_MARCA = {TamanhoMarca.PEQUENO: 0.4, TamanhoMarca.MEDIO: 0.65, TamanhoMarca.GRANDE: 0.9}


class FormatoNumero(StrEnum):
    NUMERO = "{n}"
    PAGINA = "Página {n}"
    PAGINA_DE_TOTAL = "Página {n} de {total}"
    BARRA = "{n} / {total}"


class Posicao(StrEnum):
    RODAPE_ESQUERDA = "rodape_esquerda"
    RODAPE_CENTRO = "rodape_centro"
    RODAPE_DIREITA = "rodape_direita"
    TOPO_ESQUERDA = "topo_esquerda"
    TOPO_CENTRO = "topo_centro"
    TOPO_DIREITA = "topo_direita"


def texto_suportado(texto: str) -> bool:
    """Verdadeiro se todos os caracteres existem na fonte usada (ex.: emojis não existem)."""
    try:
        texto.encode("cp1252")
        return True
    except UnicodeEncodeError:
        return False


def largura_texto(texto: str, tamanho: float) -> float:
    total = sum(_LARGURAS.get(unicodedata.normalize("NFD", c)[0], 556) for c in texto)
    return total * tamanho / 1000


def literal_pdf(texto: str) -> str:
    """Texto pronto para o conteúdo do PDF, com os caracteres especiais protegidos."""
    bruto = texto.encode("cp1252", errors="replace").decode("latin-1")
    return "(" + bruto.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ")"


def fonte_padrao(escritor: PdfWriter, nome: str = "/Helvetica") -> IndirectObject:
    """Fonte padrão do PDF (Helvetica ou Helvetica-Bold), sem nada embutido no arquivo."""
    return escritor._add_object(DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject(nome),
        NameObject("/Encoding"): NameObject("/WinAnsiEncoding"),
    }))


def _carimbar(
    origem: Path,
    destino: Path,
    desenhar: Callable[[int, int, RectangleObject], str | None],
    opacidade: float | None,
    progresso: CallbackProgresso | None,
    cancelamento: Cancelamento | None,
) -> Resultado:
    """Sobrepõe a cada página o conteúdo devolvido por `desenhar(indice, total, caixa)`."""
    escritor = PdfWriter(clone_from=abrir_pdf_ou_erro(origem))
    recursos = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/FUne"): fonte_padrao(escritor)})})
    if opacidade is not None:
        recursos[NameObject("/ExtGState")] = DictionaryObject({NameObject("/GSUne"): DictionaryObject({
            NameObject("/ca"): FloatObject(opacidade),
            NameObject("/CA"): FloatObject(opacidade),
        })})

    total = len(escritor.pages)
    for indice, pagina in enumerate(escritor.pages):
        if cancelamento:
            cancelamento.verificar()
        if progresso:
            progresso(indice + 1, total + 1, f"Página {indice + 1}")
        # Leva a rotação da página para o conteúdo, para o texto sair sempre de pé na tela
        if pagina.rotation:
            pagina.transfer_rotation_to_content()
        conteudo = desenhar(indice, total, pagina.cropbox)
        if conteudo is None:
            continue
        sobreposicao = PageObject.create_blank_page(None, float(pagina.mediabox.width), float(pagina.mediabox.height))
        sobreposicao.mediabox = pagina.mediabox
        sobreposicao[NameObject("/Resources")] = recursos
        fluxo = DecodedStreamObject()
        fluxo.set_data(conteudo.encode("latin-1"))
        sobreposicao[NameObject("/Contents")] = escritor._add_object(fluxo)
        pagina.merge_page(sobreposicao)

    if cancelamento:
        cancelamento.verificar()
    if progresso:
        progresso(total + 1, total + 1, f"Gravando {destino.name}")
    substituiu = gravar_com_seguranca(destino, escritor.write)
    return Resultado(destino, 1, total, substituiu)


def aplicar_marca_dagua(
    origem: Path,
    destino: Path,
    texto: str,
    opacidade: float = 0.25,
    tamanho: TamanhoMarca = TamanhoMarca.MEDIO,
    diagonal: bool = True,
    progresso: CallbackProgresso | None = None,
    cancelamento: Cancelamento | None = None,
) -> Resultado:
    """Escreve `texto` em cinza, semitransparente, no centro de todas as páginas."""
    tamanho = TamanhoMarca(tamanho)  # aceita também o texto ("medio"), como vem da interface
    texto = texto.strip()
    if not texto:
        raise ErroUnePDF("Digite o texto da marca d'água.")
    if not 0.05 <= opacidade <= 1:
        raise ErroUnePDF("A opacidade precisa ficar entre 5% e 100%.")

    def desenhar(indice: int, total: int, caixa: RectangleObject) -> str:
        largura, altura = float(caixa.width), float(caixa.height)
        angulo = math.atan2(altura, largura) if diagonal else 0.0
        # O texto ocupa uma fração da diagonal (ou da largura) da página, conforme o tamanho escolhido
        espaco = math.hypot(largura, altura) if diagonal else largura
        fonte = espaco * _PROPORCAO_MARCA[tamanho] / max(largura_texto(texto, 1), 1)
        cos, sen = math.cos(angulo), math.sin(angulo)
        centro_x, centro_y = float(caixa.left) + largura / 2, float(caixa.bottom) + altura / 2
        return (
            f"q /GSUne gs 0.5 0.5 0.5 rg BT /FUne {fonte:.2f} Tf "
            f"{cos:.4f} {sen:.4f} {-sen:.4f} {cos:.4f} {centro_x:.2f} {centro_y:.2f} Tm "
            f"{-largura_texto(texto, fonte) / 2:.2f} {-fonte * 0.35:.2f} Td {literal_pdf(texto)} Tj ET Q"
        )

    return _carimbar(origem, destino, desenhar, opacidade, progresso, cancelamento)


def numerar_paginas(
    origem: Path,
    destino: Path,
    formato: FormatoNumero = FormatoNumero.PAGINA_DE_TOTAL,
    posicao: Posicao = Posicao.RODAPE_CENTRO,
    pular_primeira: bool = False,
    tamanho: float = 10,
    progresso: CallbackProgresso | None = None,
    cancelamento: Cancelamento | None = None,
) -> Resultado:
    """Escreve o número de cada página. Com `pular_primeira`, a capa fica sem número e as
    demais mantêm a numeração do documento (a segunda página recebe o número 2)."""
    formato, posicao = FormatoNumero(formato), Posicao(posicao)

    def desenhar(indice: int, total: int, caixa: RectangleObject) -> str | None:
        if pular_primeira and indice == 0:
            return None
        texto = formato.value.format(n=indice + 1, total=total)
        largura_t = largura_texto(texto, tamanho)
        esquerda, base = float(caixa.left), float(caixa.bottom)
        largura, altura = float(caixa.width), float(caixa.height)
        horizontal = posicao.value.split("_")[1]
        x = {
            "esquerda": esquerda + MARGEM,
            "centro": esquerda + (largura - largura_t) / 2,
            "direita": esquerda + largura - MARGEM - largura_t,
        }[horizontal]
        y = base + altura - MARGEM - tamanho if posicao.value.startswith("topo") else base + MARGEM
        return f"q 0.25 g BT /FUne {tamanho:.2f} Tf {x:.2f} {y:.2f} Td {literal_pdf(texto)} Tj ET Q"

    return _carimbar(origem, destino, desenhar, None, progresso, cancelamento)
