from pathlib import Path

import pytest

from unepdf.core.erros import ErroUnePDF
from unepdf.core.localizador import (
    eh_pasta_saida,
    filtrar_pdfs_selecionados,
    listar_pdfs_da_pasta,
    ordem_natural,
    pasta_base,
)


def test_lista_apenas_pdfs_da_pasta_e_ignora_subpastas(tmp_path, criar_pdf):
    criar_pdf(tmp_path / "10.pdf")
    criar_pdf(tmp_path / "2.PDF")  # extensão maiúscula também conta
    (tmp_path / "notas.txt").write_text("x")
    criar_pdf(tmp_path / "UNIFICADO" / "antigo.pdf")
    criar_pdf(tmp_path / "outra" / "x.pdf")
    (tmp_path / "pasta.pdf").mkdir()  # pasta com nome de PDF não é arquivo

    nomes = [p.name for p in listar_pdfs_da_pasta(tmp_path)]

    # Ordem natural: 2 antes de 10
    assert nomes == ["2.PDF", "10.pdf"]


def test_ordem_natural():
    nomes = ["nota 10.pdf", "Nota 2.pdf", "nota 1.pdf", "b.pdf", "A.pdf", "²x.pdf"]
    ordenados = sorted((Path(n) for n in nomes), key=ordem_natural)
    assert [p.name for p in ordenados] == ["A.pdf", "b.pdf", "nota 1.pdf", "Nota 2.pdf", "nota 10.pdf", "²x.pdf"]


@pytest.mark.parametrize("nome", ["UNIFICADO", "unificado"])
def test_pasta_de_saida_nao_pode_ser_origem(tmp_path, criar_pdf, nome):
    criar_pdf(tmp_path / nome / "a.pdf")
    with pytest.raises(ErroUnePDF, match="não pode ser usada como origem"):
        listar_pdfs_da_pasta(tmp_path / nome)


def test_pasta_de_saida_personalizada(tmp_path, criar_pdf):
    criar_pdf(tmp_path / "a.pdf")
    criar_pdf(tmp_path / "RESULTADO" / "b.pdf")

    assert eh_pasta_saida(tmp_path / "Resultado", "RESULTADO")
    assert not eh_pasta_saida(tmp_path / "UNIFICADO", "RESULTADO")
    with pytest.raises(ErroUnePDF):
        listar_pdfs_da_pasta(tmp_path / "RESULTADO", "RESULTADO")


def test_pasta_inexistente_vira_erro_amigavel(tmp_path):
    with pytest.raises(ErroUnePDF, match="Não foi possível abrir a pasta"):
        listar_pdfs_da_pasta(tmp_path / "nao_existe")


def test_selecao_manual_descarta_saida_nao_pdf_e_duplicados(tmp_path, criar_pdf):
    a = criar_pdf(tmp_path / "a.pdf")
    unificado = criar_pdf(tmp_path / "UNIFICADO" / "u.pdf")
    texto = tmp_path / "b.txt"
    texto.write_text("x")
    mesma_com_outra_grafia = tmp_path / "A.PDF"

    assert filtrar_pdfs_selecionados([a, a, unificado, texto, mesma_com_outra_grafia]) == [a]


def test_selecao_manual_em_ordem_natural(tmp_path, criar_pdf):
    arquivos = [criar_pdf(tmp_path / n) for n in ("10.pdf", "9.pdf", "1.pdf")]
    assert [p.name for p in filtrar_pdfs_selecionados(arquivos)] == ["1.pdf", "9.pdf", "10.pdf"]


def test_pasta_base_e_a_do_primeiro_arquivo(tmp_path):
    assert pasta_base([tmp_path / "a.pdf", tmp_path / "b.pdf"]) == tmp_path
