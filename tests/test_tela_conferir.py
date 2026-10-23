import pytest
from certificados import SENHA, certificado_intermediario_der, criar_pfx
from test_assinatura import criar_procuracao, raiz_de_teste  # noqa: F401

from unepdf.core.assinatura import abrir_certificado, assinar
from unepdf.ui.contexto import ContextoApp
from unepdf.ui.janela_principal import JanelaPrincipal


@pytest.fixture
def tela(qtbot, tmp_path, monkeypatch, raiz_de_teste):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    janela = JanelaPrincipal(ContextoApp())
    qtbot.addWidget(janela)
    janela.show()
    janela.abrir("conferir")
    return janela.telas["conferir"]


def _conferir(qtbot, tela, caminhos):
    tela.receber_caminhos(caminhos)
    qtbot.waitUntil(lambda: not tela.executor.em_execucao, timeout=30_000)


def _textos(item, coluna=0):
    return [item.child(i).text(coluna) for i in range(item.childCount())]


def test_mostra_cada_assinatura_e_o_que_foi_conferido(qtbot, tela, tmp_path, criar_pdf, publicar):
    certificado = abrir_certificado(criar_pfx(tmp_path / "c.pfx"), SENHA)
    completo = assinar(criar_procuracao(tmp_path / "a.pdf"), tmp_path / "UnePDF" / "a - assinado.pdf", certificado, None).destino
    endereco = publicar("ac.cer", certificado_intermediario_der(), "application/pkix-cert")
    so_titular = criar_pfx(tmp_path / "t.pfx", intermediaria=True, com_cadeia=False, endereco_ac=endereco)
    incompleto = assinar(criar_procuracao(tmp_path / "b.pdf"), tmp_path / "UnePDF" / "b - assinado.pdf",
                         abrir_certificado(so_titular, SENHA), None, incluir_validacao=False).destino
    criar_pdf(tmp_path / "UnePDF" / "comum.pdf")

    _conferir(qtbot, tela, [tmp_path / "UnePDF"])

    assert tela.estados.currentWidget() is tela.painel_resultado
    assert tela.titulo.text() == "3 PDFs conferidos"
    arvore = tela.arvore
    linhas = {arvore.topLevelItem(i).text(0): arvore.topLevelItem(i) for i in range(arvore.topLevelItemCount())}
    assert linhas["comum.pdf"].text(1) == "Sem assinatura digital"

    assinatura_completa = linhas[completo.name].child(0)
    assert assinatura_completa.text(0).startswith("EMPRESA EXEMPLO LTDA (12.345.678/0001-99)")
    assert assinatura_completa.text(1) == "Válida"
    assert "O documento não foi alterado depois da assinatura." in _textos(assinatura_completa)

    assinatura_incompleta = linhas[incompleto.name].child(0)
    assert assinatura_incompleta.text(1) == "Válida, mas incompleta para o Adobe"
    assert any("Adobe pode mostrar a assinatura como inválida" in t for t in _textos(assinatura_incompleta))
    assert "1 incompleta para o Adobe" in tela.resumo.text()

    # "Conferir outros PDFs" volta para a área de soltar
    tela.limpar()
    assert tela.estados.currentWidget() is tela.area


def test_sem_pdf_na_selecao(qtbot, tela, tmp_path):
    (tmp_path / "nota.txt").write_text("x")
    tela.receber_caminhos([tmp_path / "nota.txt"])
    assert tela.estados.currentWidget() is tela.area
    assert "Nenhum PDF" in tela.area.aviso.text()
