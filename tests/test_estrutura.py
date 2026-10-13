"""Testes da estrutura do pacote e da separação entre as camadas."""
import ast
import re
from pathlib import Path

from pypdf import PdfReader

import unepdf

PACOTE = Path(unepdf.__file__).resolve().parent


def _modulos_importados(arquivo: Path) -> set[str]:
    arvore = ast.parse(arquivo.read_text(encoding="utf-8"))
    nomes = set()
    for no in ast.walk(arvore):
        if isinstance(no, ast.Import):
            nomes.update(alias.name for alias in no.names)
        elif isinstance(no, ast.ImportFrom) and no.module:
            nomes.add(no.module)
    return nomes


def test_versao_no_formato_semantico():
    assert re.fullmatch(r"\d+\.\d+\.\d+", unepdf.__version__)


def test_core_nao_depende_da_interface():
    # O core também vai servir à linha de comando, então não pode importar Qt nem a camada ui
    for arquivo in (PACOTE / "core").rglob("*.py"):
        proibidos = {
            nome for nome in _modulos_importados(arquivo)
            if nome.startswith(("PySide6", "unepdf.ui"))
        }
        assert not proibidos, f"{arquivo.name} importa {proibidos}"


def test_fabrica_de_pdfs_dos_testes(tmp_path, criar_pdf):
    comum = PdfReader(criar_pdf(tmp_path / "comum.pdf", paginas=3))
    com_senha = PdfReader(criar_pdf(tmp_path / "senha.pdf", senha="123"))
    so_permissao = PdfReader(criar_pdf(tmp_path / "permissao.pdf", senha_dono="dono"))

    assert len(comum.pages) == 3
    assert com_senha.is_encrypted and not com_senha.decrypt("")
    assert so_permissao.is_encrypted and so_permissao.decrypt("")
