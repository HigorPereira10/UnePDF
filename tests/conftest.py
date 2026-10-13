"""Utilitários compartilhados pelos testes: criação de PDFs fictícios em pasta temporária.

Nenhum PDF real fica no repositório. Todo arquivo usado nos testes é gerado aqui, na hora.
"""
import os
from pathlib import Path

import pytest
from pypdf import PdfWriter

# Testes de interface rodam sem abrir janelas, inclusive no GitHub Actions
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _criar_pdf(
    caminho: Path,
    paginas: int = 1,
    senha: str | None = None,
    senha_dono: str | None = None,
    algoritmo: str = "RC4-128",
    identificar: bool = False,
) -> Path:
    """Grava um PDF com páginas A4 em branco.

    `senha` exige senha para abrir. `senha_dono` sozinha gera um PDF com senha só de
    permissão, que abre com a senha em branco (comum em notas emitidas por alguns sistemas).
    `algoritmo` aceita os valores do pypdf, como "RC4-128" e "AES-256".
    `identificar` dá a cada página uma largura diferente (101, 102, ...), para os testes
    saberem qual página do original foi parar onde. Veja `numeros_das_paginas`.
    """
    escritor = PdfWriter()
    for numero in range(1, paginas + 1):
        escritor.add_blank_page(width=100 + numero if identificar else 595, height=842)  # A4 em pontos
    if senha is not None or senha_dono is not None:
        escritor.encrypt(user_password=senha or "", owner_password=senha_dono, algorithm=algoritmo)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with open(caminho, "wb") as arquivo:
        escritor.write(arquivo)
    return caminho


def numeros_das_paginas(caminho: Path) -> list[int]:
    """Número original (a partir de 1) de cada página de um PDF criado com identificar=True."""
    from pypdf import PdfReader

    return [round(float(p.mediabox.width)) - 100 for p in PdfReader(caminho).pages]


@pytest.fixture(scope="session", autouse=True)
def coleta_de_lixo_na_thread_principal(request):
    """Mesma proteção do app: sem ela, testes com threads podem fechar o Python de forma intermitente."""
    from unepdf.ui.coletor import ColetorNaThreadPrincipal

    request.getfixturevalue("qapp")
    coletor = ColetorNaThreadPrincipal()
    yield
    coletor.encerrar()


@pytest.fixture
def criar_pdf():
    """Fixture que devolve a função de criar PDFs, para usar nos testes."""
    return _criar_pdf
