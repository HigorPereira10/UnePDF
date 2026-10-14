import pytest
import xmls_fiscais as x
from pypdf import PdfReader

from unepdf.ui import componentes
from unepdf.ui.contexto import ContextoApp
from unepdf.ui.ferramentas import xml_pdf as modulo_xml
from unepdf.ui.janela_principal import JanelaPrincipal


@pytest.fixture
def tela(qtbot, tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    janela = JanelaPrincipal(ContextoApp())
    qtbot.addWidget(janela)
    janela.show()
    janela.abrir("xml_pdf")
    return janela.telas["xml_pdf"]


@pytest.fixture
def pasta(tmp_path):
    pasta = tmp_path / "Janeiro"
    x.gravar(pasta / "nota.xml", x.nfe())
    x.gravar(pasta / "cancelamento.xml", x.evento(x.chave(55, 1234), tipo="110111"))
    x.gravar(pasta / "frete.xml", x.cte())
    x.gravar(pasta / "prefeitura.xml", "<CompNfse><Nfse/></CompNfse>")
    return pasta


def _esperar(qtbot, tela):
    qtbot.waitUntil(lambda: not tela.executor.em_execucao, timeout=30_000)


def _carregar(qtbot, tela, caminhos):
    tela.receber_caminhos(caminhos)
    _esperar(qtbot, tela)
    assert tela.estados.currentWidget() is tela.painel_selecao


def _itens(tela):
    return [tela.lista.item(i).text() for i in range(tela.lista.count())]


def test_mostra_os_documentos_e_os_problemas(qtbot, tela, pasta):
    _carregar(qtbot, tela, [pasta])

    assert tela.resumo_selecao.text() == "2 documentos encontrados"
    assert tela.tipos_selecao.text() == "1 DANFE, 1 DACTE"
    assert _itens(tela) == [
        "DANFE 1234 - EMPRESA EXEMPLO LTDA",
        "DACTE 567 - EXEMPLO TRANSPORTES LTDA",
        "prefeitura.xml: NFS-e no padrão próprio da prefeitura. Só o padrão nacional da NFS-e é aceito",
    ]
    assert "1 arquivo não será convertido" in tela.aviso_selecao.text()
    assert "sai marcado como CANCELADA" in tela.opcoes.aviso_canceladas.text()
    assert tela.botao_converter.text() == "Converter 2 XMLs"
    # Só aparecem as opções dos tipos presentes
    assert tela.opcoes.grupo_danfe.isVisible() and not tela.opcoes.grupo_danfse.isVisible()
    assert tela.destino_selecao.text() == str(pasta / "UnePDF")


def test_converter_e_juntar(qtbot, tela, pasta, monkeypatch):
    _carregar(qtbot, tela, [pasta])
    tela.check_juntar.setChecked(True)
    assert "Janeiro - UNIFICADO (XML).pdf" in tela.destino_selecao.text()

    tela.botao_converter.click()
    _esperar(qtbot, tela)

    resultado = tela.resultado
    assert resultado.titulo.text() == "PDFs criados!"
    assert resultado.resumo.text() == (
        "2 PDFs gerados. 1 saiu marcado como CANCELADA. O PDF com todos tem 2 páginas."
    )
    assert resultado.destino == pasta / "UnePDF" / "Janeiro - UNIFICADO (XML).pdf"
    assert len(PdfReader(resultado.destino).pages) == 2
    assert resultado.lista_ignorados.count() == 1
    assert (pasta / "UnePDF" / "DANFE 1234 - EMPRESA EXEMPLO LTDA (XML).pdf").exists()

    chamadas = []
    monkeypatch.setattr(componentes.sistema, "abrir_arquivo", chamadas.append)
    resultado.botao_abrir.click()
    assert chamadas == [resultado.destino]


def test_sem_juntar_abre_a_pasta(qtbot, tela, pasta):
    _carregar(qtbot, tela, [pasta / "nota.xml"])
    tela.botao_converter.click()
    _esperar(qtbot, tela)
    assert tela.resultado.destino == pasta / "UnePDF"
    assert tela.resultado.botao_abrir.text() == "Abrir pasta"


def test_opcoes_ficam_salvas_menos_marcar_cancelados(qtbot, tela, pasta, tmp_path, monkeypatch):
    _carregar(qtbot, tela, [pasta])
    opcoes = tela.opcoes
    opcoes.combo_fonte.setCurrentIndex(1)
    opcoes.caixas["canhoto_no_rodape"].setChecked(True)
    opcoes.caixas["marcar_todos_cancelados"].setChecked(True)
    logo = tmp_path / "logo.png"
    monkeypatch.setattr(modulo_xml.QFileDialog, "getOpenFileName", lambda *a: (str(logo), ""))
    opcoes.botao_logo.click()
    tela.check_juntar.setChecked(True)

    salvas = tela.contexto.config.opcoes_xml
    assert salvas["fonte"] == "courier" and salvas["canhoto_no_rodape"] is True
    assert salvas["logo"] == str(logo) and salvas["juntar"] is True
    assert "marcar_todos_cancelados" not in salvas

    novo = modulo_xml.PainelOpcoesXml(tela.contexto)
    assert novo.combo_fonte.currentData() == "courier"
    assert novo.caixas["canhoto_no_rodape"].isChecked()
    assert not novo.caixas["marcar_todos_cancelados"].isChecked()
    assert novo.rotulo_logo.text() == "logo.png"


def test_nenhum_xml_valido(qtbot, tela, tmp_path):
    x.gravar(tmp_path / "a.xml", "lixo")
    _carregar(qtbot, tela, [tmp_path])
    assert not tela.botao_converter.isEnabled()


def test_pasta_sem_xml(qtbot, tela, tmp_path):
    (tmp_path / "vazia").mkdir()
    tela.receber_caminhos([tmp_path / "vazia"])
    _esperar(qtbot, tela)
    assert "Nenhum XML encontrado" in tela.area.aviso.text()
