"""Registro das ferramentas exibidas na tela inicial e na barra lateral.

Só entram aqui ferramentas prontas. Para adicionar uma nova, crie a tela em um módulo
desta pasta e acrescente um item em FERRAMENTAS.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from unepdf.ui.contexto import ContextoApp
from unepdf.ui.ferramentas.base import TelaFerramenta
from unepdf.ui.ferramentas.dividir import TelaDividir
from unepdf.ui.ferramentas.unir import TelaUnir

# Ordem em que as categorias aparecem na tela inicial e na barra lateral
CATEGORIAS = ("Organizar", "Converter", "Editar", "Segurança", "Otimizar")


def _sempre_disponivel() -> str | None:
    return None


@dataclass(frozen=True)
class Ferramenta:
    chave: str
    nome: str
    descricao: str
    icone: str  # caminho relativo à raiz do projeto
    categoria: str
    tela: Callable[[Ferramenta, ContextoApp], TelaFerramenta]
    # Devolve o motivo quando falta algo para a ferramenta funcionar (ex.: programa externo ausente)
    motivo_indisponivel: Callable[[], str | None] = _sempre_disponivel


FERRAMENTAS: list[Ferramenta] = [
    Ferramenta(
        chave="unir",
        nome="Unir PDFs",
        descricao="Junte vários PDFs em um só arquivo, com um marcador para cada um.",
        icone="assets/icones/unir.svg",
        categoria="Organizar",
        tela=TelaUnir,
    ),
    Ferramenta(
        chave="dividir",
        nome="Dividir PDF",
        descricao="Separe um PDF em vários: por intervalos, a cada N páginas ou por marcador.",
        icone="assets/icones/dividir.svg",
        categoria="Organizar",
        tela=TelaDividir,
    ),
]


def buscar(chave: str) -> Ferramenta:
    return next(f for f in FERRAMENTAS if f.chave == chave)


def por_categoria(ferramentas: list[Ferramenta] = FERRAMENTAS) -> list[tuple[str, list[Ferramenta]]]:
    """Ferramentas agrupadas na ordem de CATEGORIAS. Categorias sem ferramentas ficam de fora."""
    grupos = [(c, [f for f in ferramentas if f.categoria == c]) for c in CATEGORIAS]
    return [(categoria, lista) for categoria, lista in grupos if lista]
