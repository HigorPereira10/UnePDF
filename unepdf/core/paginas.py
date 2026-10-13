"""Operações com as páginas de um PDF: extrair, remover, girar e reordenar.

Todas são casos de uma operação só, `reorganizar`: montar um PDF novo a partir de uma lista
de páginas do original, cada uma com a sua rotação. As páginas são numeradas a partir de 0
no código e a partir de 1 nos textos digitados pelo usuário.
"""
from __future__ import annotations

import re
from pathlib import Path

from pypdf import PdfReader, PdfWriter

from unepdf.core.erros import ErroUnePDF
from unepdf.core.gravacao import gravar_com_seguranca
from unepdf.core.leitor_pdf import abrir_pdf_ou_erro
from unepdf.core.modelos import Resultado
from unepdf.core.progresso import CallbackProgresso, Cancelamento

# Página (índice a partir de 0) e rotação em graus, no sentido horário
PlanoPaginas = list[tuple[int, int]]

_ITEM_INTERVALO = re.compile(r"^(\d*)\s*-\s*(\d*)$")


def interpretar_grupos(texto: str, total: int) -> list[list[int]]:
    """Converte um texto como "1-3, 5, 8-" em grupos de páginas (índices a partir de 0).

    Cada item separado por vírgula (ou ponto e vírgula) vira um grupo. "8-" vai até a última
    página e "-3" começa na primeira. Lança ErroUnePDF com uma explicação quando o texto é inválido.
    """
    itens = [item.strip() for item in re.split(r"[,;]", texto) if item.strip()]
    if not itens:
        raise ErroUnePDF("Informe as páginas, por exemplo: 1-3, 5, 8-10.")

    grupos = []
    for item in itens:
        if item.isdigit():
            inicio = fim = int(item)
        elif intervalo := _ITEM_INTERVALO.match(item):
            inicio = int(intervalo[1]) if intervalo[1] else 1
            fim = int(intervalo[2]) if intervalo[2] else total
            if not intervalo[1] and not intervalo[2]:
                raise ErroUnePDF(f'Não entendi "{item}". Use números e intervalos, como 1-3, 5, 8-10.')
        else:
            raise ErroUnePDF(f'Não entendi "{item}". Use números e intervalos, como 1-3, 5, 8-10.')

        for pagina in (inicio, fim):
            if not 1 <= pagina <= total:
                raise ErroUnePDF(f"A página {pagina} não existe: o PDF tem {total} página(s).")
        if inicio > fim:
            raise ErroUnePDF(f'O intervalo "{item}" está invertido. Use o menor número primeiro, como {fim}-{inicio}.')
        grupos.append(list(range(inicio - 1, fim)))
    return grupos


def interpretar_paginas(texto: str, total: int) -> list[int]:
    """Como interpretar_grupos, mas devolve uma lista só, sem repetições e na ordem digitada."""
    return list(dict.fromkeys(p for grupo in interpretar_grupos(texto, total) for p in grupo))


def reorganizar(
    origem: Path,
    plano: PlanoPaginas,
    destino: Path,
    progresso: CallbackProgresso | None = None,
    cancelamento: Cancelamento | None = None,
) -> Resultado:
    """Grava em `destino` um PDF com as páginas do plano, na ordem e com as rotações indicadas."""
    return _gravar_plano(abrir_pdf_ou_erro(origem), plano, destino, progresso, cancelamento)


def _gravar_plano(
    leitor: PdfReader,
    plano: PlanoPaginas,
    destino: Path,
    progresso: CallbackProgresso | None,
    cancelamento: Cancelamento | None,
) -> Resultado:
    if not plano:
        raise ErroUnePDF("O PDF final precisa ter pelo menos uma página.")
    total = len(leitor.pages)

    escritor = PdfWriter()
    for posicao, (indice, rotacao) in enumerate(plano, start=1):
        if cancelamento:
            cancelamento.verificar()
        if not 0 <= indice < total:
            raise ErroUnePDF(f"A página {indice + 1} não existe: o PDF tem {total} página(s).")
        if rotacao % 90:
            raise ErroUnePDF("A rotação precisa ser múltipla de 90 graus.")
        if progresso:
            progresso(posicao, len(plano) + 1, f"Página {indice + 1}")
        pagina = escritor.add_page(leitor.pages[indice])
        if rotacao % 360:
            # Soma à rotação que a página já tinha e normaliza: alguns leitores recusam valores como 450
            pagina.rotation = (pagina.rotation + rotacao) % 360

    if cancelamento:
        cancelamento.verificar()
    if progresso:
        progresso(len(plano) + 1, len(plano) + 1, f"Gravando {destino.name}")
    substituiu = gravar_com_seguranca(destino, escritor.write)
    return Resultado(destino=destino, arquivos=1, paginas=len(plano), substituiu_anterior=substituiu)


def extrair(origem: Path, paginas: list[int], destino: Path, progresso=None, cancelamento=None) -> Resultado:
    """Novo PDF só com as páginas indicadas, na ordem indicada."""
    return reorganizar(origem, [(p, 0) for p in paginas], destino, progresso, cancelamento)


def remover(origem: Path, paginas: list[int], destino: Path, progresso=None, cancelamento=None) -> Resultado:
    """Novo PDF sem as páginas indicadas."""
    leitor = abrir_pdf_ou_erro(origem)
    retiradas = set(paginas)
    restantes = [p for p in range(len(leitor.pages)) if p not in retiradas]
    if not restantes:
        raise ErroUnePDF("Não dá para remover todas as páginas: o PDF final ficaria vazio.")
    return _gravar_plano(leitor, [(p, 0) for p in restantes], destino, progresso, cancelamento)


def girar(
    origem: Path, graus: int, destino: Path, paginas: list[int] | None = None, progresso=None, cancelamento=None
) -> Resultado:
    """Novo PDF com as páginas indicadas (ou todas) giradas em `graus`, no sentido horário."""
    leitor = abrir_pdf_ou_erro(origem)
    total = len(leitor.pages)
    alvo = set(range(total) if paginas is None else paginas)
    plano = [(p, graus if p in alvo else 0) for p in range(total)]
    return _gravar_plano(leitor, plano, destino, progresso, cancelamento)


def reordenar(origem: Path, ordem: list[int], destino: Path, progresso=None, cancelamento=None) -> Resultado:
    """Novo PDF com todas as páginas na ordem indicada."""
    leitor = abrir_pdf_ou_erro(origem)
    if sorted(ordem) != list(range(len(leitor.pages))):
        raise ErroUnePDF("A nova ordem precisa conter cada página exatamente uma vez.")
    return _gravar_plano(leitor, [(p, 0) for p in ordem], destino, progresso, cancelamento)
