"""Capa com índice para o PDF unificado: o nome de cada arquivo e a página em que ele começa.

Cada linha do índice é um link para a página do arquivo. A capa usa as fontes padrão do PDF,
então nada é embutido no arquivo.
"""
from __future__ import annotations

from math import ceil

from pypdf import PdfWriter
from pypdf.annotations import Link
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from unepdf.core.carimbo import fonte_padrao, largura_texto, literal_pdf
from unepdf.utils.texto import plural

LARGURA, ALTURA = 595, 842  # A4 em pontos
MARGEM = 56
TOPO = ALTURA - 72
ALTURA_LINHA = 18
TAMANHO_TITULO = 18
TAMANHO_TEXTO = 10.5
INICIO_PRIMEIRA = TOPO - 58  # a primeira página tem o título e o resumo antes da lista
INICIO_DEMAIS = TOPO - 30

LINHAS_PRIMEIRA = int((INICIO_PRIMEIRA - MARGEM) / ALTURA_LINHA) + 1
LINHAS_DEMAIS = int((INICIO_DEMAIS - MARGEM) / ALTURA_LINHA) + 1


def paginas_da_capa(quantidade: int) -> int:
    """Quantas páginas o índice ocupa para `quantidade` arquivos."""
    if quantidade <= LINHAS_PRIMEIRA:
        return 1
    return 1 + ceil((quantidade - LINHAS_PRIMEIRA) / LINHAS_DEMAIS)


def encurtar(texto: str, tamanho: float, largura_maxima: float, fator: float = 1.0) -> str:
    """Corta o texto no fim, com reticências, até caber na largura.

    `fator` compensa fontes mais largas que a Helvetica comum (ex.: o negrito).
    """
    if largura_texto(texto, tamanho) * fator <= largura_maxima:
        return texto
    while texto and largura_texto(texto + "...", tamanho) * fator > largura_maxima:
        texto = texto[:-1]
    return texto.rstrip() + "..."


def desenhar_capa(
    escritor: PdfWriter,
    titulo: str,
    itens: list[tuple[str, int]],
    total_paginas: int,
) -> None:
    """Preenche as primeiras páginas do `escritor`, já criadas em branco, com o índice.

    `itens` traz o nome de cada arquivo e o índice (a partir de 0) da página onde ele começa.
    """
    recursos = DictionaryObject({NameObject("/Font"): DictionaryObject({
        NameObject("/FTexto"): fonte_padrao(escritor),
        NameObject("/FNegrito"): fonte_padrao(escritor, "/Helvetica-Bold"),
    })})
    largura_util = LARGURA - 2 * MARGEM
    largura_ponto = largura_texto(".", TAMANHO_TEXTO)
    restantes = list(enumerate(itens, start=1))

    for indice_pagina in range(paginas_da_capa(len(itens))):
        comandos: list[str] = []
        if indice_pagina == 0:
            resumo = f"{plural(len(itens), 'arquivo', 'arquivos')}, {plural(total_paginas, 'página', 'páginas')}"
            comandos += [
                f"BT /FNegrito {TAMANHO_TITULO} Tf {MARGEM} {TOPO} Td "
                f"{literal_pdf(encurtar(titulo, TAMANHO_TITULO, largura_util, 1.1))} Tj ET",
                f"0.4 g BT /FTexto 10 Tf {MARGEM} {TOPO - 22} Td {literal_pdf(resumo)} Tj ET 0 g",
                f"0.8 G 0.75 w {MARGEM} {TOPO - 36} m {LARGURA - MARGEM} {TOPO - 36} l S",
            ]
            y, linhas = INICIO_PRIMEIRA, LINHAS_PRIMEIRA
        else:
            comandos.append(f"0.4 g BT /FTexto 10 Tf {MARGEM} {TOPO} Td {literal_pdf('Índice (continuação)')} Tj ET 0 g")
            y, linhas = INICIO_DEMAIS, LINHAS_DEMAIS

        lote, restantes = restantes[:linhas], restantes[linhas:]
        for numero, (nome, pagina_inicial) in lote:
            numero_pagina = str(pagina_inicial + 1)
            largura_numero = largura_texto(numero_pagina, TAMANHO_TEXTO)
            texto = encurtar(f"{numero}. {nome}", TAMANHO_TEXTO, largura_util - largura_numero - 24)
            fim_texto = MARGEM + largura_texto(texto, TAMANHO_TEXTO) + 6
            inicio_numero = LARGURA - MARGEM - largura_numero
            pontos = "." * max(int((inicio_numero - 6 - fim_texto) / largura_ponto), 0)
            comandos += [
                f"BT /FTexto {TAMANHO_TEXTO} Tf {MARGEM} {y} Td {literal_pdf(texto)} Tj ET",
                f"0.6 g BT /FTexto {TAMANHO_TEXTO} Tf {fim_texto:.2f} {y} Td ({pontos}) Tj ET 0 g",
                f"BT /FTexto {TAMANHO_TEXTO} Tf {inicio_numero:.2f} {y} Td ({numero_pagina}) Tj ET",
            ]
            escritor.add_annotation(
                indice_pagina,
                Link(
                    rect=(MARGEM, y - 4, LARGURA - MARGEM, y + TAMANHO_TEXTO + 2),
                    target_page_index=pagina_inicial,
                    border=[0, 0, 0],
                ),
            )
            y -= ALTURA_LINHA

        pagina = escritor.pages[indice_pagina]
        pagina[NameObject("/Resources")] = recursos
        fluxo = DecodedStreamObject()
        fluxo.set_data("\n".join(comandos).encode("latin-1"))
        pagina[NameObject("/Contents")] = escritor._add_object(fluxo)
