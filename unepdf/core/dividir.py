"""Divisão de um PDF em vários: por intervalos, a cada N páginas ou um arquivo por marcador.

Os arquivos gerados vão para uma pasta "<nome> - dividido", gravada de forma segura:
uma pasta anterior com o mesmo nome é substituída por inteiro.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader, PdfWriter

from unepdf.core.erros import ErroUnePDF
from unepdf.core.gravacao import gravar_pasta_com_seguranca
from unepdf.core.leitor_pdf import abrir_pdf_ou_erro
from unepdf.core.modelos import Resultado
from unepdf.core.nomenclatura import limpar_nome
from unepdf.core.paginas import interpretar_grupos
from unepdf.core.progresso import CallbackProgresso, Cancelamento

# Nomes muito longos (títulos de marcadores) estouram o limite de caminho do Windows
TAMANHO_MAXIMO_NOME = 120


@dataclass(frozen=True)
class Parte:
    nome: str  # sem a extensão
    paginas: list[int]  # índices a partir de 0


def nome_pasta_divisao(origem: Path) -> str:
    return f"{origem.stem} - dividido"


def _descrever_paginas(paginas: list[int]) -> str:
    inicio, fim = paginas[0] + 1, paginas[-1] + 1
    return f"página {inicio}" if inicio == fim else f"páginas {inicio}-{fim}"


def partes_por_intervalos(texto: str, total: int, base: str) -> list[Parte]:
    return [Parte(f"{base} - {_descrever_paginas(g)}", g) for g in interpretar_grupos(texto, total)]


def partes_a_cada(n: int, total: int, base: str) -> list[Parte]:
    if n < 1:
        raise ErroUnePDF("A quantidade de páginas por arquivo precisa ser pelo menos 1.")
    grupos = [list(range(i, min(i + n, total))) for i in range(0, total, n)]
    return [Parte(f"{base} - {_descrever_paginas(g)}", g) for g in grupos]


def marcadores(leitor: PdfReader) -> list[tuple[str, int]]:
    """Marcadores do primeiro nível do índice, como (título, página inicial), em ordem de página."""
    encontrados = []
    for item in leitor.outline:
        if isinstance(item, list):  # submarcadores do item anterior
            continue
        try:
            pagina = leitor.get_destination_page_number(item)
        except Exception:
            continue
        if pagina is not None and pagina >= 0:
            encontrados.append((str(item.title or "").strip(), pagina))
    return sorted(encontrados, key=lambda m: m[1])


def partes_por_marcadores(leitor: PdfReader, base: str) -> list[Parte]:
    """Um arquivo por marcador, do início dele até a página antes do próximo.

    As páginas antes do primeiro marcador (ex.: uma capa) entram no primeiro arquivo.
    Dividir um PDF gerado pelo Unir PDFs devolve os arquivos originais, com os mesmos nomes.
    """
    lista = marcadores(leitor)
    if not lista:
        raise ErroUnePDF("Este PDF não tem marcadores para usar na divisão.")
    total = len(leitor.pages)
    inicios = [0] + [pagina for _, pagina in lista[1:]] + [total]

    partes = []
    for posicao, (titulo, _) in enumerate(lista):
        paginas = list(range(inicios[posicao], inicios[posicao + 1]))
        if paginas:  # dois marcadores na mesma página: o primeiro fica sem páginas e é pulado
            partes.append(Parte(limpar_nome(titulo) or f"{base} - parte {posicao + 1}", paginas))
    return partes


def _nomes_unicos(partes: list[Parte]) -> list[str]:
    """Encurta nomes longos e numera repetidos ("Nota (2)"), sem diferenciar maiúsculas como o Windows."""
    usados: set[str] = set()
    nomes = []
    for parte in partes:
        base = parte.nome[:TAMANHO_MAXIMO_NOME].strip(" .") or "parte"
        nome, contador = base, 2
        while nome.casefold() in usados:
            nome = f"{base} ({contador})"
            contador += 1
        usados.add(nome.casefold())
        nomes.append(nome)
    return nomes


def gravar_partes(
    leitor: PdfReader,
    partes: list[Parte],
    pasta_destino: Path,
    progresso: CallbackProgresso | None = None,
    cancelamento: Cancelamento | None = None,
) -> Resultado:
    """Grava cada parte como um PDF dentro de `pasta_destino`."""
    if not partes:
        raise ErroUnePDF("Nenhuma parte para gravar.")

    def escrever(pasta: Path) -> None:
        for posicao, (parte, nome) in enumerate(zip(partes, _nomes_unicos(partes)), start=1):
            if cancelamento:
                cancelamento.verificar()
            if progresso:
                progresso(posicao, len(partes), f"{nome}.pdf")
            escritor = PdfWriter()
            for indice in parte.paginas:
                escritor.add_page(leitor.pages[indice])
            with open(pasta / f"{nome}.pdf", "wb") as arquivo:
                escritor.write(arquivo)

    substituiu = gravar_pasta_com_seguranca(pasta_destino, escrever)
    return Resultado(
        destino=pasta_destino,
        arquivos=len(partes),
        paginas=sum(len(p.paginas) for p in partes),
        substituiu_anterior=substituiu,
    )


def dividir_por_intervalos(origem: Path, texto: str, pasta_destino: Path, progresso=None, cancelamento=None) -> Resultado:
    leitor = abrir_pdf_ou_erro(origem)
    partes = partes_por_intervalos(texto, len(leitor.pages), origem.stem)
    return gravar_partes(leitor, partes, pasta_destino, progresso, cancelamento)


def dividir_a_cada(origem: Path, n: int, pasta_destino: Path, progresso=None, cancelamento=None) -> Resultado:
    leitor = abrir_pdf_ou_erro(origem)
    partes = partes_a_cada(n, len(leitor.pages), origem.stem)
    return gravar_partes(leitor, partes, pasta_destino, progresso, cancelamento)


def separar_paginas(origem: Path, paginas: list[int], pasta_destino: Path, progresso=None, cancelamento=None) -> Resultado:
    """Um PDF para cada página indicada."""
    leitor = abrir_pdf_ou_erro(origem)
    partes = [Parte(f"{origem.stem} - página {p + 1}", [p]) for p in paginas]
    return gravar_partes(leitor, partes, pasta_destino, progresso, cancelamento)


def dividir_por_marcadores(origem: Path, pasta_destino: Path, progresso=None, cancelamento=None) -> Resultado:
    leitor = abrir_pdf_ou_erro(origem)
    return gravar_partes(leitor, partes_por_marcadores(leitor, origem.stem), pasta_destino, progresso, cancelamento)
