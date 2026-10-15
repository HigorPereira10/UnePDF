from pathlib import Path

import pytest
from conftest import criar_pdf_com_texto
from PIL import Image

from unepdf.core import ocr
from unepdf.ui.contexto import ContextoApp
from unepdf.ui.janela_principal import JanelaPrincipal


@pytest.fixture
def janela(qtbot, tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    janela = JanelaPrincipal(ContextoApp())
    qtbot.addWidget(janela)
    janela.show()
    return janela


@pytest.fixture
def com_tesseract(tmp_path, monkeypatch):
    executavel = tmp_path / "Tesseract-OCR" / "tesseract.exe"
    (executavel.parent / "tessdata").mkdir(parents=True)
    executavel.write_bytes(b"")
    (executavel.parent / "tessdata" / "por.traineddata").write_bytes(b"")
    monkeypatch.setattr(ocr, "localizar_tesseract", lambda: executavel)

    def executar(argumentos, cancelamento):
        base, saida = argumentos[1], argumentos[-1]
        if saida == "pdf":
            criar_pdf_com_texto(Path(base + ".pdf"), ["TEXTO RECONHECIDO"])
        else:
            Path(base + ".txt").write_text("TEXTO RECONHECIDO", encoding="utf-8")

    monkeypatch.setattr(ocr, "_executar", executar)


def _esperar(qtbot, tela):
    qtbot.waitUntil(lambda: not tela.executor.em_execucao, timeout=30_000)


def test_sem_tesseract_explica_e_bloqueia(qtbot, tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setattr(ocr, "localizar_tesseract", lambda: None)
    # A janela é criada depois de o Tesseract "sumir": os cartões são montados na abertura
    janela = JanelaPrincipal(ContextoApp())
    qtbot.addWidget(janela)
    janela.show()
    cartao = next(c for c in janela.tela_inicial.cartoes if c.chave == "ocr")
    assert cartao.property("disponivel") is False
    janela.abrir("ocr")
    tela = janela.telas["ocr"]
    assert "UB-Mannheim" in tela.area.aviso.text()
    assert not tela.area.botao_arquivos.isEnabled()


def test_ocr_de_pasta_com_pdf_e_imagem(qtbot, janela, tmp_path, com_tesseract):
    pasta = tmp_path / "Digitalizados"
    criar_pdf_com_texto(pasta / "contrato.pdf", ["", ""])
    Image.new("RGB", (600, 800), "white").save(pasta / "recibo.jpg")
    (pasta / "quebrado.pdf").write_bytes(b"lixo")
    janela.abrir("ocr")
    tela = janela.telas["ocr"]

    tela.receber_caminhos([pasta])
    _esperar(qtbot, tela)

    assert tela.resumo_selecao.text() == "2 arquivos selecionados"
    assert tela.detalhe_selecao.text() == "3 páginas no total"
    itens = [tela.lista.item(i).text() for i in range(tela.lista.count())]
    assert itens == ["contrato.pdf (2 páginas)", "recibo.jpg (1 página)", "quebrado.pdf: arquivo corrompido ou ilegível"]

    tela.check_juntar.setChecked(True)
    tela.botao_ocr.click()
    _esperar(qtbot, tela)

    assert tela.resultado.titulo.text() == "OCR concluído!"
    assert tela.resultado.resumo.text() == (
        "2 arquivos ficaram pesquisáveis (3 páginas lidas com OCR). O PDF com todos tem 3 páginas."
    )
    assert tela.resultado.destino == pasta / "UnePDF" / "Digitalizados - UNIFICADO (OCR).pdf"
    assert (pasta / "UnePDF" / "recibo - OCR.pdf").exists()


def test_pdf_para_texto_oferece_ocr_quando_ha_tesseract(qtbot, janela, tmp_path, com_tesseract):
    pdf = criar_pdf_com_texto(tmp_path / "scan.pdf", [""])
    janela.abrir("pdf_texto")
    tela = janela.telas["pdf_texto"]
    tela.receber_caminhos([pdf])
    _esperar(qtbot, tela)
    assert tela.usar_ocr.isEnabled() and tela.usar_ocr.isChecked()

    tela.botao_principal.click()
    _esperar(qtbot, tela)

    texto = (tmp_path / "UnePDF" / "scan - texto.txt").read_text(encoding="utf-8-sig")
    assert "TEXTO RECONHECIDO" in texto
    assert "lidas com OCR" in tela.resultado.resumo.text()


def test_pdf_para_texto_sem_tesseract_desativa_a_opcao(qtbot, janela, tmp_path, monkeypatch):
    monkeypatch.setattr(ocr, "localizar_tesseract", lambda: None)
    janela.abrir("pdf_texto")
    tela = janela.telas["pdf_texto"]
    tela.receber_caminhos([criar_pdf_com_texto(tmp_path / "a.pdf", ["Texto qualquer de exemplo bem comprido."])])
    _esperar(qtbot, tela)
    assert not tela.usar_ocr.isEnabled()
    assert "Tesseract" in tela.ajuda_ocr.text()
