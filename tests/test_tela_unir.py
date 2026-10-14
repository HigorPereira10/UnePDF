import pytest
from pypdf import PdfReader
from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QApplication

from unepdf.core.erros import OperacaoCancelada
from unepdf.core.nomenclatura import Perfil
from unepdf.ui import componentes
from unepdf.ui.contexto import ContextoApp
from unepdf.ui.ferramentas import unir as modulo_unir
from unepdf.ui.janela_principal import JanelaPrincipal


@pytest.fixture
def janela(qtbot, tmp_path, monkeypatch):
    # Configurações gravadas na pasta temporária, nunca no %APPDATA% real
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    janela = JanelaPrincipal(ContextoApp())
    qtbot.addWidget(janela)
    janela.show()
    return janela


@pytest.fixture
def tela(janela):
    janela.abrir("unir")
    return janela.telas["unir"]


def _esperar(qtbot, tela):
    qtbot.waitUntil(lambda: not tela.executor.em_execucao, timeout=10_000)


def test_pasta_vira_selecao_com_destino(qtbot, tela, tmp_path, criar_pdf):
    pasta = tmp_path / "Janeiro"
    for nome in ("10.pdf", "2.pdf"):
        criar_pdf(pasta / nome)

    tela.receber_caminhos([pasta])
    _esperar(qtbot, tela)

    assert tela.estados.currentWidget() is tela.painel_selecao
    assert [tela.lista_arquivos.item(i).text() for i in range(2)] == ["2.pdf", "10.pdf"]
    assert tela.destino_selecao.text() == str(pasta / "UnePDF" / "Janeiro - UNIFICADO.pdf")
    assert tela.contexto.config.ultima_pasta == str(pasta)


def test_usa_o_perfil_e_a_pasta_de_saida_das_configuracoes(qtbot, tela, tmp_path, criar_pdf):
    pasta = tmp_path / "DANFE" / "0001-EMPRESA EXEMPLO LTDA" / "012026"
    criar_pdf(pasta / "a.pdf")
    tela.contexto.config.perfil_nomenclatura = Perfil.NOTAS_FISCAIS
    tela.contexto.config.pasta_saida = "RESULTADO"

    tela.receber_caminhos([pasta])
    _esperar(qtbot, tela)

    assert tela.destino_selecao.text() == str(
        pasta / "RESULTADO" / "DANFE - 0001-EMPRESA EXEMPLO LTDA - 012026.pdf"
    )


def test_avisa_substituicao_e_itens_descartados(qtbot, tela, tmp_path, criar_pdf):
    a = criar_pdf(tmp_path / "a.pdf")
    criar_pdf(tmp_path / "UnePDF" / f"{tmp_path.name} - UNIFICADO.pdf")
    texto = tmp_path / "b.txt"
    texto.write_text("x")

    tela.receber_caminhos([a, texto])
    _esperar(qtbot, tela)

    assert "1 item ficou de fora" in tela.aviso_selecao.text()
    assert "será substituído" in tela.aviso_selecao.text()


def test_problema_na_selecao_vira_aviso_na_area(qtbot, tela, tmp_path):
    (tmp_path / "vazia").mkdir()

    tela.receber_caminhos([tmp_path / "vazia"])
    _esperar(qtbot, tela)

    assert tela.estados.currentWidget() is tela.area
    assert "Nenhum PDF encontrado" in tela.area.aviso.text()


def test_unir_mostra_resumo_e_ignorados(qtbot, tela, tmp_path, criar_pdf):
    criar_pdf(tmp_path / "1.pdf", paginas=2)
    criar_pdf(tmp_path / "2.pdf")
    (tmp_path / "vazio.pdf").write_bytes(b"")
    tela.receber_caminhos([tmp_path])
    _esperar(qtbot, tela)

    tela.botao_unir.click()
    _esperar(qtbot, tela)

    resultado = tela.resultado
    assert tela.estados.currentWidget() is resultado
    assert resultado.titulo.text() == "PDF criado!"
    assert resultado.resumo.text() == "2 arquivos unidos em 3 páginas."
    assert len(PdfReader(resultado.destino).pages) == 3
    assert resultado.lista_ignorados.count() == 1
    assert "vazio.pdf: arquivo vazio" in resultado.lista_ignorados.item(0).text()

    resultado.botao_copiar.click()
    assert str(tmp_path / "vazio.pdf") in QApplication.clipboard().text()


def test_botoes_abrir_e_mostrar_na_pasta(qtbot, tela, tmp_path, criar_pdf, monkeypatch):
    chamadas = []
    monkeypatch.setattr(componentes.sistema, "abrir_arquivo", lambda c: chamadas.append(("abrir", c)))
    monkeypatch.setattr(componentes.sistema, "mostrar_na_pasta", lambda c: chamadas.append(("pasta", c)))
    criar_pdf(tmp_path / "1.pdf")
    tela.receber_caminhos([tmp_path])
    _esperar(qtbot, tela)
    tela.botao_unir.click()
    _esperar(qtbot, tela)

    tela.resultado.botao_abrir.click()
    tela.resultado.botao_pasta.click()

    destino = tela.resultado.destino
    assert chamadas == [("abrir", destino), ("pasta", destino)]


def test_todos_invalidos_mostra_falha_com_a_lista(qtbot, tela, tmp_path):
    (tmp_path / "vazio.pdf").write_bytes(b"")
    (tmp_path / "quebrado.pdf").write_bytes(b"lixo")
    tela.receber_caminhos([tmp_path])
    _esperar(qtbot, tela)

    tela.botao_unir.click()
    _esperar(qtbot, tela)

    assert tela.resultado.titulo.text() == "Nenhum PDF foi unido"
    assert tela.resultado.lista_ignorados.count() == 2
    assert not tela.resultado.botao_abrir.isVisible()


def test_cancelar_volta_para_a_selecao(qtbot, tela, tmp_path, criar_pdf, monkeypatch):
    criar_pdf(tmp_path / "1.pdf")

    def unir_que_espera_o_cancelamento(arquivos, destino, progresso, cancelamento, **opcoes):
        while True:
            cancelamento.verificar()

    monkeypatch.setattr(modulo_unir, "unir", unir_que_espera_o_cancelamento)
    tela.receber_caminhos([tmp_path])
    _esperar(qtbot, tela)

    tela.botao_unir.click()
    assert tela.estados.currentWidget() is tela.progresso
    tela.progresso.botao_cancelar.click()
    _esperar(qtbot, tela)

    assert tela.estados.currentWidget() is tela.painel_selecao
    assert OperacaoCancelada().mensagem in tela.aviso_selecao.text()


def test_unir_outros_arquivos_volta_ao_inicio(qtbot, tela, tmp_path, criar_pdf):
    criar_pdf(tmp_path / "1.pdf")
    tela.receber_caminhos([tmp_path])
    _esperar(qtbot, tela)
    tela.botao_unir.click()
    _esperar(qtbot, tela)

    tela.resultado.botao_novo.click()

    assert tela.estados.currentWidget() is tela.area


def test_escolher_pasta_pelo_dialogo(qtbot, tela, tmp_path, criar_pdf, monkeypatch):
    criar_pdf(tmp_path / "1.pdf")
    monkeypatch.setattr(modulo_unir.QFileDialog, "getExistingDirectory", lambda *a: str(tmp_path))

    tela.area.botao_pasta.click()
    _esperar(qtbot, tela)

    assert tela.estados.currentWidget() is tela.painel_selecao


def test_soltar_arquivos_na_tela_inicial_abre_unir(qtbot, janela, tmp_path, criar_pdf):
    criar_pdf(tmp_path / "1.pdf")
    dados = QMimeData()
    dados.setUrls([QUrl.fromLocalFile(str(tmp_path))])
    evento = QDropEvent(
        QPointF(10, 10), Qt.DropAction.CopyAction, dados, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier
    )

    janela.dropEvent(evento)
    tela = janela.telas["unir"]
    _esperar(qtbot, tela)

    assert janela.pilha.currentWidget() is tela
    assert tela.estados.currentWidget() is tela.painel_selecao


def _nomes(tela):
    return [p.name for p in tela.lista_arquivos.arquivos()]


def test_ordem_por_data_manual_e_remover(qtbot, tela, tmp_path, criar_pdf):
    import os

    from PySide6.QtCore import QModelIndex

    for paginas, segundos in ((1, 300), (2, 100), (3, 200)):
        os.utime(criar_pdf(tmp_path / f"{paginas}.pdf", paginas=paginas), (segundos, segundos))
    tela.receber_caminhos([tmp_path])
    _esperar(qtbot, tela)
    assert _nomes(tela) == ["1.pdf", "2.pdf", "3.pdf"]

    combo = tela.opcoes.combo_ordem
    combo.setCurrentIndex(combo.findData("data"))
    assert _nomes(tela) == ["2.pdf", "3.pdf", "1.pdf"]
    assert tela.contexto.config.unir_ordem == "data"

    # Arrastar na lista passa para a ordem manual, que não fica salva
    tela.lista_arquivos.model().moveRow(QModelIndex(), 2, QModelIndex(), 0)
    assert _nomes(tela) == ["1.pdf", "2.pdf", "3.pdf"]
    assert combo.currentData() == "manual"
    assert tela.contexto.config.unir_ordem == "data"

    tela.lista_arquivos.item(1).setSelected(True)
    tela.botao_remover.click()
    assert _nomes(tela) == ["1.pdf", "3.pdf"]
    assert tela.resumo_selecao.text() == "2 PDFs selecionados"

    tela.botao_unir.click()
    _esperar(qtbot, tela)
    leitor = PdfReader(tela.resultado.destino)
    assert [m.title for m in leitor.outline] == ["1", "3"]


def test_remover_todos_desativa_o_botao(qtbot, tela, tmp_path, criar_pdf):
    criar_pdf(tmp_path / "1.pdf")
    tela.receber_caminhos([tmp_path])
    _esperar(qtbot, tela)

    tela.lista_arquivos.selectAll()
    qtbot.keyClick(tela.lista_arquivos, Qt.Key.Key_Delete)

    assert tela.lista_arquivos.count() == 0
    assert not tela.botao_unir.isEnabled()


def test_capa_e_repetidos_chegam_ao_resultado(qtbot, tela, tmp_path, criar_pdf):
    criar_pdf(tmp_path / "a.pdf")
    criar_pdf(tmp_path / "b.pdf")  # mesmo conteúdo de a.pdf
    tela.receber_caminhos([tmp_path])
    _esperar(qtbot, tela)
    assert tela.opcoes.check_repetidos.isChecked() and not tela.opcoes.check_capa.isChecked()

    tela.opcoes.check_capa.setChecked(True)
    tela.botao_unir.click()
    _esperar(qtbot, tela)

    assert tela.contexto.config.unir_capa
    assert tela.resultado.resumo.text() == "1 arquivo unido em 2 páginas."
    assert "conteúdo repetido" in tela.resultado.lista_ignorados.item(0).text()
    assert PdfReader(tela.resultado.destino).outline[0].title == "Índice"


def test_cancelar_mantem_a_ordem_manual(qtbot, tela, tmp_path, criar_pdf, monkeypatch):
    from PySide6.QtCore import QModelIndex

    criar_pdf(tmp_path / "1.pdf")
    criar_pdf(tmp_path / "2.pdf", paginas=2)

    def unir_que_espera_o_cancelamento(arquivos, destino, progresso, cancelamento, **opcoes):
        while True:
            cancelamento.verificar()

    monkeypatch.setattr(modulo_unir, "unir", unir_que_espera_o_cancelamento)
    tela.receber_caminhos([tmp_path])
    _esperar(qtbot, tela)
    tela.lista_arquivos.model().moveRow(QModelIndex(), 1, QModelIndex(), 0)

    tela.botao_unir.click()
    tela.progresso.botao_cancelar.click()
    _esperar(qtbot, tela)

    assert _nomes(tela) == ["2.pdf", "1.pdf"]
