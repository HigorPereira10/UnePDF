import threading

import pytest

from unepdf.core.erros import ErroUnePDF
from unepdf.core.renderizacao import DocumentoRenderizavel


def test_renderiza_na_largura_pedida(tmp_path, criar_pdf):
    dados = criar_pdf(tmp_path / "a.pdf", paginas=2).read_bytes()  # páginas A4 (595 x 842 pontos)

    with DocumentoRenderizavel(dados) as documento:
        imagem = documento.renderizar(1, largura=119)

    assert documento.total == 2
    assert imagem.largura == 119
    assert imagem.altura in (168, 169)  # 842 * 119 / 595 = 168,4; o arredondamento é do PDFium
    assert len(imagem.dados) == imagem.bytes_por_linha * imagem.altura
    assert imagem.dados[:4] == b"\xff\xff\xff\xff"  # fundo branco


def test_renderiza_por_resolucao(tmp_path, criar_pdf):
    dados = criar_pdf(tmp_path / "a.pdf").read_bytes()
    with DocumentoRenderizavel(dados) as documento:
        assert documento.renderizar(0, dpi=144).largura == 1190


def test_aplica_a_rotacao_da_pagina(tmp_path, criar_pdf):
    from unepdf.core.paginas import girar

    girado = girar(criar_pdf(tmp_path / "a.pdf"), 90, tmp_path / "g.pdf").destino
    with DocumentoRenderizavel(girado.read_bytes()) as documento:
        imagem = documento.renderizar(0, largura=100)
    assert imagem.largura > imagem.altura


def test_dados_invalidos_viram_erro_amigavel():
    with pytest.raises(ErroUnePDF, match="desenhar as páginas"):
        DocumentoRenderizavel(b"lixo")


def test_duas_threads_ao_mesmo_tempo(tmp_path, criar_pdf):
    # O PDFium não aceita uso simultâneo; a trava interna precisa evitar a falha
    dados = criar_pdf(tmp_path / "a.pdf", paginas=20).read_bytes()
    erros = []

    def desenhar_tudo():
        try:
            with DocumentoRenderizavel(dados) as documento:
                for indice in range(documento.total):
                    documento.renderizar(indice, largura=60)
        except Exception as erro:
            erros.append(erro)

    threads = [threading.Thread(target=desenhar_tudo) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert erros == []
