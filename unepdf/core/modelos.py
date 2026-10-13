"""Estruturas de dados compartilhadas pelas ferramentas."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ArquivoIgnorado:
    """Arquivo que não entrou no resultado, com o motivo em linguagem do usuário."""

    caminho: Path
    motivo: str


@dataclass
class Resultado:
    """Resumo de uma operação concluída, usado pela interface e pela CLI para montar o relatório."""

    destino: Path
    arquivos: int
    paginas: int
    substituiu_anterior: bool
    ignorados: list[ArquivoIgnorado] = field(default_factory=list)
    # Informação extra da ferramenta para o resumo (ex.: "2 páginas não tinham texto")
    observacao: str = ""
