"""Registro das ferramentas exibidas na tela inicial e na barra lateral.

Só entram aqui ferramentas prontas. Para adicionar uma nova, crie a tela em um módulo
desta pasta e acrescente um item em FERRAMENTAS.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from unepdf.ui.contexto import ContextoApp
from unepdf.ui.ferramentas.base import TelaFerramenta
from unepdf.ui.ferramentas.unir import TelaUnir


def _sempre_disponivel() -> str | None:
    return None


@dataclass(frozen=True)
class Ferramenta:
    chave: str
    nome: str
    descricao: str
    icone: str  # caminho relativo à raiz do projeto
    tela: Callable[[Ferramenta, ContextoApp], TelaFerramenta]
    # Devolve o motivo quando falta algo para a ferramenta funcionar (ex.: programa externo ausente)
    motivo_indisponivel: Callable[[], str | None] = _sempre_disponivel


FERRAMENTAS: list[Ferramenta] = [
    Ferramenta(
        chave="unir",
        nome="Unir PDFs",
        descricao="Junte vários PDFs em um só arquivo, com um marcador para cada um.",
        icone="assets/icones/unir.svg",
        tela=TelaUnir,
    ),
]


def buscar(chave: str) -> Ferramenta:
    return next(f for f in FERRAMENTAS if f.chave == chave)
