from pathlib import Path

import pytest

from unepdf.core.erros import ErroUnePDF
from unepdf.core.localizador import (
    IMAGEM,
    SoEmSubpastas,
    eh_pasta_saida,
    filtrar_pdfs_selecionados,
    listar_pdfs_da_pasta,
    montar_selecao,
    ordem_natural,
    pasta_base,
    pdf_unico,
)


def test_lista_apenas_pdfs_da_pasta_e_ignora_subpastas(tmp_path, criar_pdf):
    criar_pdf(tmp_path / "10.pdf")
    criar_pdf(tmp_path / "2.PDF")  # extensão maiúscula também conta
    (tmp_path / "notas.txt").write_text("x")
    criar_pdf(tmp_path / "UnePDF" / "antigo.pdf")
    criar_pdf(tmp_path / "outra" / "x.pdf")
    (tmp_path / "pasta.pdf").mkdir()  # pasta com nome de PDF não é arquivo

    nomes = [p.name for p in listar_pdfs_da_pasta(tmp_path)]

    # Ordem natural: 2 antes de 10
    assert nomes == ["2.PDF", "10.pdf"]


def test_ordem_natural():
    nomes = ["nota 10.pdf", "Nota 2.pdf", "nota 1.pdf", "b.pdf", "A.pdf", "²x.pdf"]
    ordenados = sorted((Path(n) for n in nomes), key=ordem_natural)
    assert [p.name for p in ordenados] == ["A.pdf", "b.pdf", "nota 1.pdf", "Nota 2.pdf", "nota 10.pdf", "²x.pdf"]


@pytest.mark.parametrize("nome", ["UnePDF", "unepdf"])
def test_pasta_de_saida_nao_pode_ser_origem(tmp_path, criar_pdf, nome):
    criar_pdf(tmp_path / nome / "a.pdf")
    with pytest.raises(ErroUnePDF, match="não pode ser usada como origem"):
        listar_pdfs_da_pasta(tmp_path / nome)


def test_pasta_de_saida_personalizada(tmp_path, criar_pdf):
    criar_pdf(tmp_path / "a.pdf")
    criar_pdf(tmp_path / "RESULTADO" / "b.pdf")

    assert eh_pasta_saida(tmp_path / "Resultado", "RESULTADO")
    assert not eh_pasta_saida(tmp_path / "UnePDF", "RESULTADO")
    with pytest.raises(ErroUnePDF):
        listar_pdfs_da_pasta(tmp_path / "RESULTADO", "RESULTADO")


def test_pasta_inexistente_vira_erro_amigavel(tmp_path):
    with pytest.raises(ErroUnePDF, match="Não foi possível abrir a pasta"):
        listar_pdfs_da_pasta(tmp_path / "nao_existe")


def test_selecao_manual_descarta_saida_nao_pdf_e_duplicados(tmp_path, criar_pdf):
    a = criar_pdf(tmp_path / "a.pdf")
    unificado = criar_pdf(tmp_path / "UnePDF" / "u.pdf")
    texto = tmp_path / "b.txt"
    texto.write_text("x")
    mesma_com_outra_grafia = tmp_path / "A.PDF"

    assert filtrar_pdfs_selecionados([a, a, unificado, texto, mesma_com_outra_grafia]) == [a]


def test_selecao_manual_em_ordem_natural(tmp_path, criar_pdf):
    arquivos = [criar_pdf(tmp_path / n) for n in ("10.pdf", "9.pdf", "1.pdf")]
    assert [p.name for p in filtrar_pdfs_selecionados(arquivos)] == ["1.pdf", "9.pdf", "10.pdf"]


def test_pasta_base_e_a_do_primeiro_arquivo(tmp_path):
    assert pasta_base([tmp_path / "a.pdf", tmp_path / "b.pdf"]) == tmp_path


def test_selecao_de_pasta(tmp_path, criar_pdf):
    criar_pdf(tmp_path / "2.pdf")
    criar_pdf(tmp_path / "10.pdf")

    selecao = montar_selecao([tmp_path])

    assert [p.name for p in selecao.arquivos] == ["2.pdf", "10.pdf"]
    assert selecao.base == selecao.pasta == tmp_path


def test_selecao_de_pasta_sem_pdfs(tmp_path, criar_pdf):
    criar_pdf(tmp_path / "sub" / "a.pdf")
    with pytest.raises(ErroUnePDF, match="subpastas não entram"):
        montar_selecao([tmp_path])


def test_selecao_de_arquivos_conta_os_descartados(tmp_path, criar_pdf):
    a = criar_pdf(tmp_path / "a.pdf")
    texto = tmp_path / "b.txt"
    texto.write_text("x")

    selecao = montar_selecao([a, texto, a])

    assert selecao.arquivos == [a]
    assert selecao.base == tmp_path
    assert selecao.pasta is None
    assert selecao.descartados == 2


def test_selecao_sem_nenhum_pdf_utilizavel(tmp_path, criar_pdf):
    unificado = criar_pdf(tmp_path / "UnePDF" / "u.pdf")
    with pytest.raises(ErroUnePDF, match="Nenhum dos arquivos"):
        montar_selecao([unificado])


@pytest.mark.parametrize("mistura", ["duas_pastas", "pasta_e_arquivo"])
def test_selecao_recusa_misturas(tmp_path, criar_pdf, mistura):
    (tmp_path / "x").mkdir()
    outro = tmp_path / "y" if mistura == "duas_pastas" else criar_pdf(tmp_path / "a.pdf")
    if mistura == "duas_pastas":
        outro.mkdir()
    with pytest.raises(ErroUnePDF, match="uma pasta por vez"):
        montar_selecao([tmp_path / "x", outro])


def test_pdf_unico(tmp_path, criar_pdf):
    a = criar_pdf(tmp_path / "a.pdf")
    b = criar_pdf(tmp_path / "b.pdf")
    texto = tmp_path / "c.txt"
    texto.write_text("x")

    assert pdf_unico([a]) == a
    for invalida in ([], [a, b], [texto], [tmp_path]):
        with pytest.raises(ErroUnePDF, match="único arquivo PDF"):
            pdf_unico(invalida)


def test_selecao_de_imagens(tmp_path, criar_pdf):
    from PIL import Image

    for nome in ("10.jpg", "2.PNG", "3.tiff"):
        Image.new("RGB", (5, 5)).save(tmp_path / nome)
    criar_pdf(tmp_path / "doc.pdf")

    selecao = montar_selecao([tmp_path], tipo=IMAGEM)

    assert [p.name for p in selecao.arquivos] == ["2.PNG", "3.tiff", "10.jpg"]


def test_pasta_sem_imagens_tem_mensagem_propria(tmp_path, criar_pdf):
    criar_pdf(tmp_path / "doc.pdf")
    with pytest.raises(ErroUnePDF, match="Nenhuma imagem encontrada"):
        montar_selecao([tmp_path], tipo=IMAGEM)


def test_pasta_so_com_subpastas_avisa_quais_tem_pdfs(tmp_path, criar_pdf):
    criar_pdf(tmp_path / "012026" / "EMITIDAS" / "1.pdf")
    criar_pdf(tmp_path / "012026" / "RECEBIDAS" / "2.pdf")
    criar_pdf(tmp_path / "012026" / "UnePDF" / "unido.pdf")
    (tmp_path / "012026" / "vazia").mkdir()
    with pytest.raises(SoEmSubpastas) as erro:
        montar_selecao([tmp_path / "012026"])
    assert [p.name for p in erro.value.subpastas] == ["EMITIDAS", "RECEBIDAS"]
    assert erro.value.pasta == tmp_path / "012026"
