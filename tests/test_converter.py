import pytest
from conftest import criar_pdf_com_texto
from PIL import Image

from unepdf.core.converter import FormatoImagem, pdf_para_imagens, pdf_para_texto
from unepdf.core.erros import ErroUnePDF, OperacaoCancelada
from unepdf.core.progresso import Cancelamento


def test_pdf_para_png_uma_imagem_por_pagina(tmp_path, criar_pdf):
    origem = criar_pdf(tmp_path / "doc.pdf", paginas=12)
    pasta = tmp_path / "doc - imagens"

    resultado = pdf_para_imagens(origem, pasta, FormatoImagem.PNG, dpi=72)

    nomes = sorted(p.name for p in pasta.iterdir())
    assert resultado.arquivos == 12
    assert nomes[0] == "doc - página 01.png"  # zero à esquerda mantém a ordem no Explorer
    with Image.open(pasta / "doc - página 01.png") as imagem:
        assert imagem.size == (595, 842)


def test_pdf_para_jpg_em_300_dpi_so_algumas_paginas(tmp_path, criar_pdf):
    origem = criar_pdf(tmp_path / "doc.pdf", paginas=3)
    pasta = tmp_path / "saida"

    resultado = pdf_para_imagens(origem, pasta, FormatoImagem.JPG, dpi=300, paginas=[2])

    assert resultado.arquivos == 1
    with Image.open(pasta / "doc - página 3.jpg") as imagem:
        assert imagem.format == "JPEG"
        assert imagem.width == 2480  # 595 pontos a 300 dpi


@pytest.mark.parametrize("paginas,trecho", [([], "pelo menos uma"), ([5], "A página 6 não existe")])
def test_pdf_para_imagens_valida_as_paginas(tmp_path, criar_pdf, paginas, trecho):
    origem = criar_pdf(tmp_path / "doc.pdf", paginas=2)
    with pytest.raises(ErroUnePDF, match=trecho):
        pdf_para_imagens(origem, tmp_path / "x", paginas=paginas)


def test_pdf_para_imagens_cancelado_nao_deixa_pasta(tmp_path, criar_pdf):
    origem = criar_pdf(tmp_path / "doc.pdf", paginas=2)
    cancelamento = Cancelamento()
    cancelamento.cancelar()
    with pytest.raises(OperacaoCancelada):
        pdf_para_imagens(origem, tmp_path / "x", cancelamento=cancelamento)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["doc.pdf"]


def test_pdf_para_texto_com_acentos_e_marcas_de_pagina(tmp_path):
    origem = criar_pdf_com_texto(tmp_path / "contrato.pdf", ["Cláusula primeira: ação", "Página dois"])
    destino = tmp_path / "contrato - texto.txt"

    resultado = pdf_para_texto(origem, destino)

    dados = destino.read_bytes()
    assert dados.startswith(b"\xef\xbb\xbf")  # BOM, para o Bloco de Notas reconhecer os acentos
    texto = dados.decode("utf-8-sig")
    assert "===== Página 1 =====" in texto and "===== Página 2 =====" in texto
    assert "Cláusula primeira: ação" in texto
    assert resultado.paginas == 2 and not resultado.observacao


def test_pdf_para_texto_sem_marcas(tmp_path):
    origem = criar_pdf_com_texto(tmp_path / "a.pdf", ["Um", "Dois"])
    pdf_para_texto(origem, tmp_path / "a.txt", separar_paginas=False)
    assert "=====" not in (tmp_path / "a.txt").read_text(encoding="utf-8-sig")


def test_pdf_escaneado_sem_texto_explica_e_nao_grava(tmp_path):
    origem = criar_pdf_com_texto(tmp_path / "scan.pdf", ["", ""])
    with pytest.raises(ErroUnePDF, match="escaneados"):
        pdf_para_texto(origem, tmp_path / "scan.txt")
    assert not (tmp_path / "scan.txt").exists()


def test_pdf_misto_avisa_paginas_sem_texto(tmp_path):
    origem = criar_pdf_com_texto(tmp_path / "misto.pdf", ["Texto", "", ""])
    resultado = pdf_para_texto(origem, tmp_path / "misto.txt")
    assert resultado.observacao.startswith("2 página(s) não tinham texto")
