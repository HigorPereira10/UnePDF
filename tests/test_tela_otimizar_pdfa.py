import pytest
from PIL import Image

from unepdf.core import ghostscript, pdfa
from unepdf.core.imagens import imagens_para_pdf
from unepdf.ui.contexto import ContextoApp
from unepdf.ui.janela_principal import JanelaPrincipal
from unepdf.utils.programas import localizar_ghostscript

requer_ghostscript = pytest.mark.skipif(localizar_ghostscript() is None, reason="Ghostscript não instalado")


@pytest.fixture
def sem_ghostscript(monkeypatch):
    monkeypatch.setattr(ghostscript, "localizar_ghostscript", lambda: None)


@pytest.fixture
def janela(qtbot, tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))

    def criar():
        janela = JanelaPrincipal(ContextoApp())
        qtbot.addWidget(janela)
        janela.show()
        return janela

    return criar


def _esperar(qtbot, tela):
    qtbot.waitUntil(lambda: not tela.executor.em_execucao, timeout=60_000)


def _abrir(qtbot, janela, chave, pdf):
    janela.abrir(chave)
    tela = janela.telas[chave]
    tela.receber_caminhos([pdf])
    _esperar(qtbot, tela)
    return tela


# PDF para PDF/A

def test_pdfa_sem_ghostscript_explica_e_bloqueia(qtbot, janela, tmp_path, criar_pdf, sem_ghostscript):
    janela = janela()
    cartao = next(c for c in janela.tela_inicial.cartoes if c.chave == "pdfa")
    assert cartao.property("disponivel") is False

    janela.abrir("pdfa")
    tela = janela.telas["pdfa"]
    assert "ghostscript.com" in tela.area.aviso.text()
    assert not tela.area.botao_arquivos.isEnabled()

    tela.receber_caminhos([criar_pdf(tmp_path / "a.pdf")])
    assert tela.estados.currentWidget() is tela.area


def test_pdfa_volta_a_funcionar_quando_o_ghostscript_aparece(qtbot, janela, tmp_path, monkeypatch):
    monkeypatch.setattr(ghostscript, "localizar_ghostscript", lambda: None)
    janela = janela()
    janela.abrir("pdfa")
    tela = janela.telas["pdfa"]
    assert not tela.area.botao_arquivos.isEnabled()

    # Simula a instalação com o app aberto: ao voltar para a ferramenta, ela já funciona
    monkeypatch.setattr(ghostscript, "localizar_ghostscript", lambda: tmp_path / "gswin64c.exe")
    janela.abrir("inicio")
    janela.abrir("pdfa")
    assert tela.area.botao_arquivos.isEnabled()
    assert not tela.area.aviso.text()


@requer_ghostscript
def test_converter_para_pdfa_1b(qtbot, janela, tmp_path, criar_pdf):
    tela = _abrir(qtbot, janela(), "pdfa", criar_pdf(tmp_path / "a.pdf", paginas=2))
    assert tela.opcoes_formato[pdfa.FormatoSaida.PDFA_2B].isChecked()

    tela.opcoes_formato[pdfa.FormatoSaida.PDFA_1B].click()
    destino = tmp_path / "UnePDF" / "a - PDFA-1b.pdf"
    assert tela.rotulo_destino.text() == str(destino)
    tela.botao_principal.click()
    _esperar(qtbot, tela)

    assert tela.resultado.titulo.text() == "Conversão concluída!"
    assert pdfa.conferir_pdfa(destino, 1)


# Comprimir

def test_compressao_forte_desativada_sem_ghostscript(qtbot, janela, tmp_path, criar_pdf, sem_ghostscript):
    tela = _abrir(qtbot, janela(), "comprimir", criar_pdf(tmp_path / "a.pdf"))
    assert not tela.opcao_forte.isEnabled()
    assert "ghostscript.com" in tela.ajuda_forte.text()
    assert tela.opcao_recomendada.isChecked()


def test_comprimir_mostra_quanto_diminuiu(qtbot, janela, tmp_path):
    Image.effect_noise((2400, 3200), 50).convert("RGB").save(tmp_path / "scan.png")
    pdf = imagens_para_pdf([tmp_path / "scan.png"], tmp_path / "scan.pdf").destino
    tela = _abrir(qtbot, janela(), "comprimir", pdf)
    assert "MB" in tela.detalhes_arquivo.text()

    tela.botao_principal.click()
    _esperar(qtbot, tela)

    assert (tmp_path / "UnePDF" / "scan - comprimido.pdf").exists()
    assert "% menor" in tela.resultado.resumo.text()
