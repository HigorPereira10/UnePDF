import pytest

from unepdf.core import ghostscript, office
from unepdf.core.office import Aplicativo, Motor
from unepdf.ui.contexto import ContextoApp
from unepdf.ui.janela_principal import JanelaPrincipal


@pytest.fixture
def com_office(monkeypatch, criar_pdf):
    """Office "instalado" e trocado por uma função que grava um PDF de uma página."""
    monkeypatch.setattr(office, "motores_disponiveis", lambda: {app: Motor.OFFICE for app in Aplicativo})
    monkeypatch.setattr(office, "disponivel", lambda: None)
    monkeypatch.setattr(office, "_converter_um_com_office", lambda instancia, caminho, saida, c: criar_pdf(saida))


@pytest.fixture
def janela(qtbot, tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    janela = JanelaPrincipal(ContextoApp())
    qtbot.addWidget(janela)
    janela.show()
    return janela


def _esperar(qtbot, tela):
    qtbot.waitUntil(lambda: not tela.executor.em_execucao, timeout=30_000)


def _pasta(tmp_path):
    pasta = tmp_path / "Contratos"
    pasta.mkdir()
    for nome in ("contrato.docx", "planilha.xlsx", "~$contrato.docx", "notas.txt"):
        (pasta / nome).write_text("x", encoding="utf-8")
    return pasta


def test_sem_office_nem_libreoffice_explica_e_bloqueia(qtbot, janela, monkeypatch):
    monkeypatch.setattr(office, "office_instalado", lambda prog_id: False)
    monkeypatch.setattr(office, "localizar_libreoffice", lambda: None)
    janela.abrir("office_pdf")
    tela = janela.telas["office_pdf"]
    assert "libreoffice.org" in tela.area.aviso.text()
    assert not tela.area.botao_pasta.isEnabled()


def test_converte_a_pasta_e_junta(qtbot, janela, tmp_path, com_office):
    pasta = _pasta(tmp_path)
    janela.abrir("office_pdf")
    tela = janela.telas["office_pdf"]
    tela.receber_caminhos([pasta])
    _esperar(qtbot, tela)

    assert tela.resumo_selecao.text() == "2 documentos selecionados"
    assert tela.tipos_selecao.text() == "1 Word, 1 Excel"
    itens = [tela.lista.item(i).text() for i in range(tela.lista.count())]
    assert itens == ["contrato.docx", "planilha.xlsx", "~$contrato.docx: arquivo temporário do Office"]
    assert "Microsoft Office" in tela.motor_selecao.text()

    tela.check_juntar.setChecked(True)
    assert "Contratos - UNIFICADO (Office).pdf" in tela.destino_selecao.text()
    tela.botao_converter.click()
    _esperar(qtbot, tela)

    assert tela.resultado.titulo.text() == "PDFs criados!"
    assert tela.resultado.resumo.text() == "2 PDFs gerados. O PDF com todos tem 2 páginas."
    assert (pasta / "UnePDF" / "contrato.pdf").exists()
    assert tela.contexto.config.office_juntar is True


def test_pdfa_desativado_sem_ghostscript(qtbot, janela, tmp_path, com_office, monkeypatch):
    monkeypatch.setattr(ghostscript, "disponivel", lambda: ghostscript.MENSAGEM_AUSENTE)
    janela.abrir("office_pdf")
    tela = janela.telas["office_pdf"]
    tela.receber_caminhos([_pasta(tmp_path)])
    _esperar(qtbot, tela)

    assert not tela.check_pdfa.isEnabled()
    assert "ghostscript.com" in tela.ajuda_pdfa.text()


def test_um_documento_abre_o_proprio_pdf(qtbot, janela, tmp_path, com_office):
    pasta = _pasta(tmp_path)
    janela.abrir("office_pdf")
    tela = janela.telas["office_pdf"]
    tela.receber_caminhos([pasta / "contrato.docx"])
    _esperar(qtbot, tela)
    tela.botao_converter.click()
    _esperar(qtbot, tela)

    assert tela.resultado.destino == pasta / "UnePDF" / "contrato.pdf"
    assert tela.resultado.botao_abrir.text() == "Abrir arquivo"
