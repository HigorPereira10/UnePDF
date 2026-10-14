import pytest
from pypdf import PdfReader

from unepdf.core.unir import unir
from unepdf.ui.contexto import ContextoApp
from unepdf.ui.ferramentas import arquivo_unico, por_categoria
from unepdf.ui.janela_principal import JanelaPrincipal


@pytest.fixture
def janela(qtbot, tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    janela = JanelaPrincipal(ContextoApp())
    qtbot.addWidget(janela)
    janela.show()
    return janela


@pytest.fixture
def tela(janela):
    janela.abrir("dividir")
    return janela.telas["dividir"]


def _carregar(qtbot, tela, caminho):
    tela.receber_caminhos([caminho])
    qtbot.waitUntil(lambda: not tela.executor.em_execucao, timeout=10_000)


def _unido(tmp_path, criar_pdf):
    originais = [criar_pdf(tmp_path / f"NF {i}.pdf", paginas=i) for i in (1, 2)]
    return unir(originais, tmp_path / "UnePDF" / "Janeiro - UNIFICADO.pdf").destino


def test_pdf_com_marcadores_ja_vem_com_essa_opcao(qtbot, tela, tmp_path, criar_pdf):
    _carregar(qtbot, tela, _unido(tmp_path, criar_pdf))

    assert tela.estados.currentWidget() is tela.painel_opcoes
    assert tela.detalhes_arquivo.text() == "3 páginas"
    assert tela.opcao_marcadores.isChecked()
    assert "2 marcadores encontrados" in tela.ajuda_marcadores.text()
    # O original já está na pasta de saída: o resultado fica ao lado dele
    assert tela.rotulo_destino.text() == str(tmp_path / "UnePDF" / "Janeiro - UNIFICADO - dividido")


def test_pdf_sem_marcadores_comeca_por_intervalos(qtbot, tela, tmp_path, criar_pdf):
    _carregar(qtbot, tela, criar_pdf(tmp_path / "a.pdf", paginas=4))

    assert tela.opcao_intervalos.isChecked()
    assert not tela.opcao_marcadores.isEnabled()
    assert tela.rotulo_destino.text() == str(tmp_path / "UnePDF" / "a - dividido")


def test_intervalo_invalido_desativa_o_botao(qtbot, tela, tmp_path, criar_pdf):
    _carregar(qtbot, tela, criar_pdf(tmp_path / "a.pdf", paginas=4))

    tela.campo_intervalos.setText("1-2, 9")
    assert not tela.botao_principal.isEnabled()
    assert "A página 9 não existe" in tela.aviso_opcoes.text()

    tela.campo_intervalos.setText("1-2, 4")
    assert tela.botao_principal.isEnabled()


def test_a_cada_mostra_quantos_arquivos_serao_gerados(qtbot, tela, tmp_path, criar_pdf):
    _carregar(qtbot, tela, criar_pdf(tmp_path / "a.pdf", paginas=5))
    tela.opcao_a_cada.click()
    tela.campo_a_cada.setValue(2)
    assert tela.ajuda_a_cada.text() == "Vai gerar 3 arquivos."


def test_dividir_por_marcadores_ate_o_resultado(qtbot, tela, tmp_path, criar_pdf):
    _carregar(qtbot, tela, _unido(tmp_path, criar_pdf))

    tela.botao_principal.click()
    qtbot.waitUntil(lambda: not tela.executor.em_execucao, timeout=10_000)

    pasta = tmp_path / "UnePDF" / "Janeiro - UNIFICADO - dividido"
    assert tela.estados.currentWidget() is tela.resultado
    assert tela.resultado.titulo.text() == "PDF dividido!"
    assert tela.resultado.resumo.text() == "2 arquivos criados com 3 páginas no total."
    assert tela.resultado.botao_abrir.text() == "Abrir pasta"
    assert tela.resultado.destino == pasta
    assert [len(PdfReader(pasta / f"NF {i}.pdf").pages) for i in (1, 2)] == [1, 2]


def test_refazer_avisa_que_a_pasta_sera_substituida(qtbot, tela, tmp_path, criar_pdf):
    origem = criar_pdf(tmp_path / "a.pdf", paginas=2)
    (tmp_path / "UnePDF" / "a - dividido").mkdir(parents=True)
    _carregar(qtbot, tela, origem)
    assert "será substituído" in tela.aviso_opcoes.text()


def test_arquivo_que_nao_e_pdf_vira_aviso(qtbot, tela, tmp_path):
    texto = tmp_path / "a.txt"
    texto.write_text("x")
    tela.receber_caminhos([texto])
    assert tela.estados.currentWidget() is tela.area
    assert "único arquivo PDF" in tela.area.aviso.text()


def test_pdf_corrompido_vira_aviso(qtbot, tela, tmp_path):
    ruim = tmp_path / "ruim.pdf"
    ruim.write_bytes(b"lixo")
    _carregar(qtbot, tela, ruim)
    assert "corrompido" in tela.area.aviso.text()


def test_escolher_pelo_dialogo(qtbot, tela, tmp_path, criar_pdf, monkeypatch):
    origem = criar_pdf(tmp_path / "a.pdf", paginas=2)
    monkeypatch.setattr(arquivo_unico.QFileDialog, "getOpenFileName", lambda *a: (str(origem), ""))
    tela.area.botao_arquivos.click()
    qtbot.waitUntil(lambda: not tela.executor.em_execucao, timeout=10_000)
    assert tela.estados.currentWidget() is tela.painel_opcoes


def test_ferramentas_agrupadas_por_categoria(janela):
    from PySide6.QtWidgets import QLabel

    categorias = [c for c, _ in por_categoria()]
    assert categorias[0] == "Organizar"
    assert list(janela._grupos) == categorias
    titulos_grade = [r.text() for r in janela.tela_inicial.findChildren(QLabel) if r.objectName() == "tituloCategoria"]
    assert titulos_grade == categorias
