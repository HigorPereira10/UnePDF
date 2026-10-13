import pytest
from PIL import Image
from pypdf import PdfReader

from unepdf.core.erros import ErroUnePDF, OperacaoCancelada
from unepdf.core.imagens import A4, TamanhoPagina, imagens_para_pdf
from unepdf.core.progresso import Cancelamento
from unepdf.core.renderizacao import DocumentoRenderizavel


def _imagem_do_pdf(pdf, pagina=0):
    return list(PdfReader(pdf).pages[pagina]["/Resources"]["/XObject"].values())[0].get_object()


def _render(pdf, largura=100):
    with DocumentoRenderizavel(pdf.read_bytes()) as documento:
        imagem = documento.renderizar(0, largura=largura)
    return Image.frombuffer(
        "RGBX", (imagem.largura, imagem.altura), imagem.dados, "raw", "BGRX", imagem.bytes_por_linha, 1
    ).convert("RGB")


def _vermelho(pixel):
    return pixel[0] > 200 and pixel[2] < 80


def _jpg_meio_a_meio(caminho, orientacao=1):
    """JPG com a metade esquerda vermelha e a direita azul, com a orientação EXIF indicada."""
    imagem = Image.new("RGB", (200, 100), "blue")
    imagem.paste("red", (0, 0, 100, 100))
    exif = Image.Exif()
    exif[0x0112] = orientacao
    imagem.save(caminho, quality=95, exif=exif.tobytes())
    return caminho


def test_jpg_entra_identico_sem_recompressao(tmp_path):
    foto = _jpg_meio_a_meio(tmp_path / "foto.jpg")
    resultado = imagens_para_pdf([foto], tmp_path / "f.pdf")

    imagem = _imagem_do_pdf(resultado.destino)
    assert imagem["/Filter"] == "/DCTDecode"
    assert imagem._data == foto.read_bytes()


@pytest.mark.parametrize("orientacao,vermelho_em", [(1, "esquerda"), (3, "direita"), (6, "topo"), (8, "base")])
def test_respeita_a_orientacao_da_camera(tmp_path, orientacao, vermelho_em):
    foto = _jpg_meio_a_meio(tmp_path / "foto.jpg", orientacao)
    resultado = imagens_para_pdf([foto], tmp_path / "f.pdf", TamanhoPagina.IMAGEM)

    render = _render(resultado.destino)
    largura, altura = render.size
    pontos = {
        "esquerda": (3, altura // 2), "direita": (largura - 4, altura // 2),
        "topo": (largura // 2, 3), "base": (largura // 2, altura - 4),
    }
    assert _vermelho(render.getpixel(pontos[vermelho_em]))
    assert (altura > largura) == (orientacao in (6, 8))
    assert _imagem_do_pdf(resultado.destino)._data == foto.read_bytes()  # continua sem recompressão


def test_foto_espelhada_tambem_fica_certa(tmp_path):
    # Orientação 2 (espelhada) não tem como ser só girada: os pixels são regravados sem perda
    foto = _jpg_meio_a_meio(tmp_path / "foto.jpg", 2)
    resultado = imagens_para_pdf([foto], tmp_path / "f.pdf", TamanhoPagina.IMAGEM)
    render = _render(resultado.destino)
    assert _vermelho(render.getpixel((render.width - 4, render.height // 2)))
    assert _imagem_do_pdf(resultado.destino)["/Filter"] == "/FlateDecode"


def test_png_com_transparencia_fica_com_fundo_branco(tmp_path):
    imagem = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
    imagem.paste((255, 0, 0, 255), (0, 0, 50, 100))
    imagem.save(tmp_path / "logo.png")

    resultado = imagens_para_pdf([tmp_path / "logo.png"], tmp_path / "l.pdf", TamanhoPagina.IMAGEM)

    assert "/SMask" in _imagem_do_pdf(resultado.destino)
    render = _render(resultado.destino)
    assert _vermelho(render.getpixel((5, 50)))
    assert render.getpixel((render.width - 5, 50)) == (255, 255, 255)


def test_tiff_com_varias_paginas_e_preto_e_branco(tmp_path):
    paginas = [Image.new("1", (300, 400), cor) for cor in (0, 1)]
    paginas[0].save(tmp_path / "scan.tif", save_all=True, append_images=paginas[1:], dpi=(300, 300))

    resultado = imagens_para_pdf([tmp_path / "scan.tif"], tmp_path / "s.pdf", TamanhoPagina.IMAGEM)

    leitor = PdfReader(resultado.destino)
    assert (resultado.arquivos, resultado.paginas) == (1, 2)
    assert _imagem_do_pdf(resultado.destino)["/BitsPerComponent"] == 1
    # 300 px a 300 dpi = 1 polegada = 72 pontos
    assert round(float(leitor.pages[0].mediabox.width)) == 72


def test_cmyk_mantem_as_cores(tmp_path):
    Image.new("CMYK", (60, 60), (0, 255, 255, 0)).save(tmp_path / "grafica.jpg", quality=95)
    resultado = imagens_para_pdf([tmp_path / "grafica.jpg"], tmp_path / "g.pdf")
    render = _render(resultado.destino)
    assert _vermelho(render.getpixel((render.width // 2, render.height // 2)))


@pytest.mark.parametrize("tamanho_imagem,orientacao_pagina", [((800, 1200), "em pé"), ((1200, 800), "deitada")])
def test_folha_a4_acompanha_o_formato_da_imagem(tmp_path, tamanho_imagem, orientacao_pagina):
    Image.new("RGB", tamanho_imagem, "green").save(tmp_path / "f.png")
    resultado = imagens_para_pdf([tmp_path / "f.png"], tmp_path / "f.pdf", TamanhoPagina.A4)
    caixa = PdfReader(resultado.destino).pages[0].mediabox
    esperado = A4 if orientacao_pagina == "em pé" else (A4[1], A4[0])
    assert (round(float(caixa.width)), round(float(caixa.height))) == tuple(round(v) for v in esperado)


def test_ordem_da_lista_e_ignorados(tmp_path):
    Image.new("RGB", (10, 10), "red").save(tmp_path / "b.png")
    Image.new("RGB", (10, 20), "blue").save(tmp_path / "a.png")
    (tmp_path / "vazia.jpg").write_bytes(b"")
    (tmp_path / "quebrada.png").write_bytes(b"isto nao e imagem")

    resultado = imagens_para_pdf(
        [tmp_path / "b.png", tmp_path / "vazia.jpg", tmp_path / "a.png", tmp_path / "quebrada.png"],
        tmp_path / "x.pdf",
        TamanhoPagina.IMAGEM,
    )

    alturas = [round(float(p.mediabox.height)) for p in PdfReader(resultado.destino).pages]
    assert alturas == [8, 15]  # b (10 px a 96 dpi) e depois a (20 px)
    assert {i.caminho.name: i.motivo for i in resultado.ignorados} == {
        "vazia.jpg": "arquivo vazio (0 KB)",
        "quebrada.png": "imagem corrompida ou em formato não suportado",
    }


def test_nenhuma_imagem_valida_e_erro(tmp_path):
    (tmp_path / "quebrada.png").write_bytes(b"x")
    with pytest.raises(ErroUnePDF) as erro:
        imagens_para_pdf([tmp_path / "quebrada.png"], tmp_path / "x.pdf")
    assert len(erro.value.ignorados) == 1
    assert not (tmp_path / "x.pdf").exists()


def test_cancelamento(tmp_path):
    Image.new("RGB", (10, 10)).save(tmp_path / "a.png")
    cancelamento = Cancelamento()
    cancelamento.cancelar()
    with pytest.raises(OperacaoCancelada):
        imagens_para_pdf([tmp_path / "a.png"], tmp_path / "x.pdf", cancelamento=cancelamento)
