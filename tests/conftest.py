"""Utilitários compartilhados pelos testes: criação de PDFs fictícios em pasta temporária.

Nenhum PDF real fica no repositório. Todo arquivo usado nos testes é gerado aqui, na hora.
"""
from pathlib import Path

import pytest
from pypdf import PdfWriter


def _criar_pdf(
    caminho: Path,
    paginas: int = 1,
    senha: str | None = None,
    senha_dono: str | None = None,
) -> Path:
    """Grava um PDF com páginas A4 em branco.

    `senha` exige senha para abrir. `senha_dono` sozinha gera um PDF com senha só de
    permissão, que abre com a senha em branco (comum em notas emitidas por alguns sistemas).
    """
    escritor = PdfWriter()
    for _ in range(paginas):
        escritor.add_blank_page(width=595, height=842)  # A4 em pontos
    if senha is not None or senha_dono is not None:
        escritor.encrypt(user_password=senha or "", owner_password=senha_dono)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with open(caminho, "wb") as arquivo:
        escritor.write(arquivo)
    return caminho


@pytest.fixture
def criar_pdf():
    """Fixture que devolve a função de criar PDFs, para usar nos testes."""
    return _criar_pdf
