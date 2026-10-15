import csv

import pytest
from certificados import SENHA, criar_pfx
from pypdf import PdfReader
from test_assinatura import criar_procuracao

from unepdf.core.leitor_pdf import tem_assinatura
from unepdf.ui.contexto import ContextoApp
from unepdf.ui.ferramentas import assinar as modulo_assinar
from unepdf.ui.janela_principal import JanelaPrincipal


@pytest.fixture
def tela(qtbot, tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    janela = JanelaPrincipal(ContextoApp())
    qtbot.addWidget(janela)
    janela.show()
    janela.abrir("assinar")
    return janela.telas["assinar"]


def _esperar(qtbot, tela):
    qtbot.waitUntil(lambda: not tela.executor.em_execucao, timeout=30_000)


def _abrir_certificado(qtbot, tela, monkeypatch, pfx, senha=SENHA):
    monkeypatch.setattr(modulo_assinar.QFileDialog, "getOpenFileName", lambda *a: (str(pfx), ""))
    tela.botao_certificado.click()
    tela.campo_senha.setText(senha)
    tela.botao_abrir.click()
    _esperar(qtbot, tela)


def test_assinar_um_pdf_com_carimbo(qtbot, tela, tmp_path, monkeypatch):
    origem = criar_procuracao(tmp_path / "procuracao.pdf")
    tela.receber_caminhos([origem])
    _esperar(qtbot, tela)
    assert tela.esquerda.currentWidget() is tela.painel_previa
    assert not tela.botao_assinar.isEnabled()

    _abrir_certificado(qtbot, tela, monkeypatch, criar_pfx(tmp_path / "certs" / "cliente.pfx"))

    assert "EMPRESA EXEMPLO LTDA" in tela.dados_certificado.text()
    assert "12.345.678/0001-99" in tela.dados_certificado.text()
    assert tela.aviso_certificado.text() == ""
    assert tela.botao_assinar.isEnabled()
    assert tela.contexto.config.pasta_certificados == str(tmp_path / "certs")

    tela.botao_assinar.click()
    _esperar(qtbot, tela)

    destino = tmp_path / "UnePDF" / "procuracao - assinado.pdf"
    assert tela.resultado.titulo.text() == "PDF assinado!"
    assert tem_assinatura(PdfReader(destino))
    registro = tmp_path / "local" / "UnePDF" / "logs" / "assinaturas.csv"
    assert list(csv.reader(registro.read_text(encoding="utf-8-sig").splitlines(), delimiter=";"))[1][2] == str(destino)
    # A senha não fica na tela depois de começar outra assinatura
    tela.resultado.botao_novo.click()
    assert tela.campo_senha.text() == ""


def test_avisa_quando_o_cnpj_nao_esta_no_documento(qtbot, tela, tmp_path, monkeypatch):
    tela.receber_caminhos([criar_procuracao(tmp_path / "a.pdf")])
    _esperar(qtbot, tela)
    outro = criar_pfx(tmp_path / "outro.pfx", "OUTRA EMPRESA LTDA", "99888777000166")

    _abrir_certificado(qtbot, tela, monkeypatch, outro)

    assert "não aparece no PDF" in tela.aviso_certificado.text()
    assert tela.botao_assinar.isEnabled()  # é um aviso: quem decide é quem assina


def test_senha_errada_e_certificado_vencido(qtbot, tela, tmp_path, monkeypatch):
    tela.receber_caminhos([criar_procuracao(tmp_path / "a.pdf")])
    _esperar(qtbot, tela)

    _abrir_certificado(qtbot, tela, monkeypatch, criar_pfx(tmp_path / "c.pfx"), senha="errada")
    assert "Senha incorreta" in tela.aviso_certificado.text()
    assert not tela.botao_assinar.isEnabled()

    _abrir_certificado(qtbot, tela, monkeypatch, criar_pfx(tmp_path / "v.pfx", dias_restantes=-1))
    assert "vencido" in tela.aviso_certificado.text()
    assert not tela.botao_assinar.isEnabled()


def test_clique_na_previa_muda_o_carimbo(qtbot, tela, tmp_path):
    tela.receber_caminhos([criar_procuracao(tmp_path / "a.pdf")])
    _esperar(qtbot, tela)
    antes = tela._preparo.posicao

    tela.previa.clicado.emit(300.0, 500.0)

    depois = tela._preparo.posicao
    assert depois.caixa != antes.caixa
    assert (depois.caixa[0] + depois.caixa[2]) / 2 == 300


def test_varios_pdfs_mostram_a_lista(qtbot, tela, tmp_path, monkeypatch):
    pasta = tmp_path / "Procuracoes"
    for nome in ("a.pdf", "b.pdf"):
        criar_procuracao(pasta / nome)
    tela.receber_caminhos([pasta])
    _esperar(qtbot, tela)
    assert tela.esquerda.currentWidget() is tela.lista
    assert "última linha de assinatura" in tela.aviso_selecao.text()

    _abrir_certificado(qtbot, tela, monkeypatch, criar_pfx(tmp_path / "c.pfx"))
    assert tela.botao_assinar.text() == "Assinar 2 PDFs"
    tela.botao_assinar.click()
    _esperar(qtbot, tela)
    assert tela.resultado.titulo.text() == "PDFs assinados!"
    assert (pasta / "UnePDF" / "b - assinado.pdf").exists()


@pytest.mark.parametrize("rotacao", [0, 90, 180, 270])
def test_conversao_entre_previa_e_pagina(rotacao):
    caixa = (10, 20, 610, 820)  # 600 x 800 pontos
    largura, altura = (300, 400) if rotacao in (0, 180) else (400, 300)
    for ponto in ((10, 20), (610, 820), (100, 700)):
        u, v = modulo_assinar.para_tela(*ponto, caixa, rotacao, largura, altura)
        assert modulo_assinar.para_pagina(u, v, caixa, rotacao, largura, altura) == pytest.approx(ponto)
    # Sem rotação, o canto superior esquerdo da página é o canto (0, 0) da imagem
    if rotacao == 0:
        assert modulo_assinar.para_tela(10, 820, caixa, 0, largura, altura) == (0, 0)


def test_pdf_assinado_avisa_nas_outras_ferramentas(qtbot, tmp_path, monkeypatch):
    from certificados import SENHA as senha

    from unepdf.core.assinatura import abrir_certificado, assinar

    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    certificado = abrir_certificado(criar_pfx(tmp_path / "c.pfx"), senha)
    assinado = assinar(criar_procuracao(tmp_path / "a.pdf"), tmp_path / "a - assinado.pdf", certificado, None).destino
    janela = JanelaPrincipal(ContextoApp())
    qtbot.addWidget(janela)
    janela.abrir("numerar")
    tela = janela.telas["numerar"]
    tela.receber_caminhos([assinado])
    qtbot.waitUntil(lambda: not tela.executor.em_execucao, timeout=10_000)
    assert "assinatura digital" in tela.aviso_opcoes.text()
