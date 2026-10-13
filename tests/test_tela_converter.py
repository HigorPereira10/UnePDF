import pytest
from conftest import criar_pdf_com_texto
from PIL import Image
from pypdf import PdfReader
from PySide6.QtCore import QModelIndex

from unepdf.ui.contexto import ContextoApp
from unepdf.ui.janela_principal import JanelaPrincipal


@pytest.fixture
def janela(qtbot, tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    janela = JanelaPrincipal(ContextoApp())
    qtbot.addWidget(janela)
    janela.show()
    return janela


def _esperar(qtbot, tela):
    qtbot.waitUntil(lambda: not tela.executor.em_execucao, timeout=10_000)


def _abrir(qtbot, janela, chave, caminhos):
    janela.abrir(chave)
    tela = janela.telas[chave]
    tela.receber_caminhos(caminhos)
    _esperar(qtbot, tela)
    return tela


# Imagens para PDF

def _fotos(pasta, quantidade=3):
    pasta.mkdir(parents=True, exist_ok=True)
    for i in range(1, quantidade + 1):
        Image.new("RGB", (100, 100 * i), "red").save(pasta / f"foto {i}.jpg")
    return pasta


def test_imagens_da_pasta_viram_pdf_na_ordem_da_lista(qtbot, janela, tmp_path):
    pasta = _fotos(tmp_path / "Obra")
    tela = _abrir(qtbot, janela, "imagens_pdf", [pasta])

    assert tela.resumo_selecao.text() == "3 imagens selecionadas"
    assert tela.destino_selecao.text() == str(pasta / "UNIFICADO" / "Obra - imagens.pdf")
    tela.lista.model().moveRow(QModelIndex(), 2, QModelIndex(), 0)  # o mesmo que arrastar a foto 3 para o topo
    tela.opcao_original.click()
    tela.botao_converter.click()
    _esperar(qtbot, tela)

    alturas = [round(float(p.mediabox.height)) for p in PdfReader(tela.resultado.destino).pages]
    assert alturas == [225, 75, 150]  # foto 3, foto 1, foto 2 (100 px = 75 pontos a 96 dpi)
    assert tela.resultado.resumo.text() == "3 imagens convertidas em um PDF de 3 páginas."


def test_uma_imagem_avulsa_leva_o_nome_dela(qtbot, janela, tmp_path):
    pasta = _fotos(tmp_path / "Obra", 1)
    tela = _abrir(qtbot, janela, "imagens_pdf", [pasta / "foto 1.jpg"])
    assert tela.destino_selecao.text() == str(pasta / "UNIFICADO" / "foto 1.pdf")


def test_pasta_sem_imagens_avisa(qtbot, janela, tmp_path, criar_pdf):
    criar_pdf(tmp_path / "doc.pdf")
    tela = _abrir(qtbot, janela, "imagens_pdf", [tmp_path])
    assert "Nenhuma imagem encontrada" in tela.area.aviso.text()


def test_todas_as_imagens_invalidas_mostra_a_lista(qtbot, janela, tmp_path):
    (tmp_path / "a.jpg").write_bytes(b"x")
    tela = _abrir(qtbot, janela, "imagens_pdf", [tmp_path])
    tela.botao_converter.click()
    _esperar(qtbot, tela)
    assert tela.resultado.titulo.text() == "Nenhuma imagem foi convertida"
    assert tela.resultado.lista_ignorados.count() == 1


# PDF para imagens

def test_pdf_para_imagens_todas_as_paginas(qtbot, janela, tmp_path, criar_pdf):
    tela = _abrir(qtbot, janela, "pdf_imagens", [criar_pdf(tmp_path / "doc.pdf", paginas=2)])
    tela.opcao_jpg.click()
    tela.campo_resolucao.setCurrentIndex(0)  # 72 dpi
    tela.botao_principal.click()
    _esperar(qtbot, tela)

    pasta = tmp_path / "UNIFICADO" / "doc - imagens"
    assert sorted(p.name for p in pasta.iterdir()) == ["doc - página 1.jpg", "doc - página 2.jpg"]
    assert tela.resultado.botao_abrir.text() == "Abrir pasta"


def test_pdf_para_imagens_so_algumas_paginas_valida_o_texto(qtbot, janela, tmp_path, criar_pdf):
    tela = _abrir(qtbot, janela, "pdf_imagens", [criar_pdf(tmp_path / "doc.pdf", paginas=3)])
    tela.opcao_algumas.click()
    assert not tela.botao_principal.isEnabled()  # campo ainda vazio

    tela.campo_paginas.setText("9")
    assert "A página 9 não existe" in tela.aviso_opcoes.text()

    tela.campo_paginas.setText("2-3")
    assert tela.botao_principal.isEnabled()
    tela.botao_principal.click()
    _esperar(qtbot, tela)
    assert tela.resultado.resumo.text().startswith("2 imagens criadas")


# PDF para texto

def test_pdf_para_texto(qtbot, janela, tmp_path):
    origem = criar_pdf_com_texto(tmp_path / "contrato.pdf", ["Cláusula única", ""])
    tela = _abrir(qtbot, janela, "pdf_texto", [origem])
    assert tela.rotulo_destino.text() == str(tmp_path / "UNIFICADO" / "contrato - texto.txt")

    tela.botao_principal.click()
    _esperar(qtbot, tela)

    texto = (tmp_path / "UNIFICADO" / "contrato - texto.txt").read_text(encoding="utf-8-sig")
    assert "Cláusula única" in texto
    assert "1 página(s) não tinham texto" in tela.resultado.resumo.text()


def test_pdf_escaneado_mostra_explicacao(qtbot, janela, tmp_path, monkeypatch):
    from unepdf.ui.ferramentas import arquivo_unico

    mostrados = []
    monkeypatch.setattr(arquivo_unico, "mostrar_erro", lambda pai, erro: mostrados.append(str(erro)))
    tela = _abrir(qtbot, janela, "pdf_texto", [criar_pdf_com_texto(tmp_path / "scan.pdf", [""])])
    tela.botao_principal.click()
    _esperar(qtbot, tela)

    assert "escaneados" in mostrados[0]
    assert tela.estados.currentWidget() is tela.painel_opcoes
