import pytest
from conftest import criar_pdf_com_texto
from PIL import Image
from pypdf import PdfReader, PdfWriter

from unepdf.core import carimbo
from unepdf.core.erros import ErroUnePDF, OperacaoCancelada
from unepdf.core.progresso import Cancelamento
from unepdf.core.renderizacao import DocumentoRenderizavel


def _textos(pdf):
    with DocumentoRenderizavel(pdf.read_bytes()) as documento:
        return [documento.extrair_texto(i) for i in range(documento.total)]


def _render(pdf, indice=0, largura=300):
    with DocumentoRenderizavel(pdf.read_bytes()) as documento:
        imagem = documento.renderizar(indice, largura=largura)
    return Image.frombuffer(
        "RGBX", (imagem.largura, imagem.altura), imagem.dados, "raw", "BGRX", imagem.bytes_por_linha, 1
    ).convert("L")


def _tem_tinta(imagem, caixa):
    return imagem.crop(caixa).getextrema()[0] < 200


def test_largura_do_texto():
    assert carimbo.largura_texto("A", 1000) == 667
    assert carimbo.largura_texto("ação", 10) == carimbo.largura_texto("acao", 10)


def test_texto_suportado():
    assert carimbo.texto_suportado("CÓPIA nº 1 © «válida»")
    assert not carimbo.texto_suportado("Aprovado ✅")


def test_marca_dagua_em_todas_as_paginas_com_acentos(tmp_path):
    origem = criar_pdf_com_texto(tmp_path / "a.pdf", ["Conteúdo 1", "Conteúdo 2"])

    resultado = carimbo.aplicar_marca_dagua(origem, tmp_path / "m.pdf", "CÓPIA (não vale)")

    textos = _textos(resultado.destino)
    assert all("CÓPIA (não vale)" in t for t in textos)
    assert "Conteúdo 1" in textos[0]  # o conteúdo original continua lá
    assert resultado.paginas == 2


def test_marca_dagua_e_semitransparente_e_centralizada(tmp_path, criar_pdf):
    origem = criar_pdf(tmp_path / "a.pdf")
    destino = carimbo.aplicar_marca_dagua(origem, tmp_path / "m.pdf", "X" * 8, opacidade=0.3, diagonal=False).destino

    imagem = _render(destino)
    largura, altura = imagem.size
    meio = imagem.crop((0, altura // 2 - 20, largura, altura // 2 + 20))
    assert 100 < meio.getextrema()[0] < 255  # cinza claro, não preto
    assert not _tem_tinta(imagem, (0, 0, largura, altura // 4))  # nada no topo


def test_marca_dagua_texto_vazio_e_opacidade_invalida(tmp_path, criar_pdf):
    origem = criar_pdf(tmp_path / "a.pdf")
    with pytest.raises(ErroUnePDF, match="Digite o texto"):
        carimbo.aplicar_marca_dagua(origem, tmp_path / "m.pdf", "   ")
    with pytest.raises(ErroUnePDF, match="opacidade"):
        carimbo.aplicar_marca_dagua(origem, tmp_path / "m.pdf", "X", opacidade=0)


@pytest.mark.parametrize("formato,esperado", [
    (carimbo.FormatoNumero.PAGINA_DE_TOTAL, ["Página 1 de 3", "Página 2 de 3", "Página 3 de 3"]),
    (carimbo.FormatoNumero.BARRA, ["1 / 3", "2 / 3", "3 / 3"]),
])
def test_numeracao(tmp_path, formato, esperado):
    origem = criar_pdf_com_texto(tmp_path / "a.pdf", ["a", "b", "c"])
    destino = carimbo.numerar_paginas(origem, tmp_path / "n.pdf", formato).destino
    assert [e in t for e, t in zip(esperado, _textos(destino))] == [True, True, True]


def test_numeracao_pulando_a_capa(tmp_path):
    origem = criar_pdf_com_texto(tmp_path / "a.pdf", ["capa", "b"])
    destino = carimbo.numerar_paginas(origem, tmp_path / "n.pdf", carimbo.FormatoNumero.PAGINA, pular_primeira=True).destino
    textos = _textos(destino)
    assert "Página" not in textos[0]
    assert "Página 2" in textos[1]


@pytest.mark.parametrize("posicao,regiao", [
    (carimbo.Posicao.RODAPE_DIREITA, "baixo_direita"),
    (carimbo.Posicao.TOPO_ESQUERDA, "cima_esquerda"),
])
def test_posicao_da_numeracao(tmp_path, criar_pdf, posicao, regiao):
    destino = carimbo.numerar_paginas(criar_pdf(tmp_path / "a.pdf"), tmp_path / "n.pdf", posicao=posicao).destino
    imagem = _render(destino)
    largura, altura = imagem.size
    regioes = {
        "baixo_direita": (largura // 2, altura * 9 // 10, largura, altura),
        "cima_esquerda": (0, 0, largura // 2, altura // 10),
    }
    assert _tem_tinta(imagem, regioes[regiao])
    opostas = {"baixo_direita": "cima_esquerda", "cima_esquerda": "baixo_direita"}
    assert not _tem_tinta(imagem, regioes[opostas[regiao]])


def test_pagina_girada_recebe_o_texto_de_pe(tmp_path):
    escritor = PdfWriter()
    escritor.add_blank_page(595, 842).rotation = 90
    origem = tmp_path / "girada.pdf"
    escritor.write(origem)

    destino = carimbo.numerar_paginas(origem, tmp_path / "n.pdf", posicao=carimbo.Posicao.RODAPE_DIREITA).destino

    imagem = _render(destino)
    largura, altura = imagem.size
    assert largura > altura  # a página continua deitada na tela
    assert _tem_tinta(imagem, (largura // 2, altura * 85 // 100, largura, altura))
    assert PdfReader(destino).pages[0].rotation == 0  # a rotação passou para o conteúdo


def test_cancelamento(tmp_path, criar_pdf):
    cancelamento = Cancelamento()
    cancelamento.cancelar()
    with pytest.raises(OperacaoCancelada):
        carimbo.numerar_paginas(criar_pdf(tmp_path / "a.pdf"), tmp_path / "n.pdf", cancelamento=cancelamento)
    assert not (tmp_path / "n.pdf").exists()


def test_aceita_as_opcoes_como_texto(tmp_path):
    # A interface (e a linha de comando) entregam as opções como texto simples
    origem = criar_pdf_com_texto(tmp_path / "a.pdf", ["a"])
    destino = carimbo.numerar_paginas(origem, tmp_path / "n.pdf", "{n}", "topo_centro").destino
    marca = carimbo.aplicar_marca_dagua(origem, tmp_path / "m.pdf", "X", tamanho="grande").destino
    assert destino.exists() and marca.exists()
