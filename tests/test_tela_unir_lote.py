import threading

import pytest
from PySide6.QtCore import Qt

from unepdf.core import lote
from unepdf.core.nomenclatura import Perfil
from unepdf.ui.contexto import ContextoApp
from unepdf.ui.ferramentas import unir_lote as modulo_lote
from unepdf.ui.janela_principal import JanelaPrincipal


@pytest.fixture
def tela(qtbot, tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    janela = JanelaPrincipal(ContextoApp())
    qtbot.addWidget(janela)
    janela.show()
    janela.abrir("unir_lote")
    return janela.telas["unir_lote"]


@pytest.fixture
def raiz(tmp_path, criar_pdf):
    raiz = tmp_path / "Notas"
    criar_pdf(raiz / "DANFE" / "0001-EMPRESA EXEMPLO LTDA" / "012026" / "1.pdf", paginas=2)
    criar_pdf(raiz / "DANFE" / "0001-EMPRESA EXEMPLO LTDA" / "022026" / "1.pdf")
    criar_pdf(raiz / "DACTE" / "0002-EXEMPLO TRANSPORTES" / "012026" / "1.pdf")
    return raiz


def _esperar(qtbot, tela):
    qtbot.waitUntil(lambda: not tela.executor.em_execucao, timeout=20_000)


def _carregar(qtbot, tela, raiz):
    tela.receber_caminhos([raiz])
    _esperar(qtbot, tela)
    assert tela.estados.currentWidget() is tela.painel_selecao


def test_lista_as_pastas_com_destino(qtbot, tela, raiz, criar_pdf):
    tela.contexto.config.perfil_nomenclatura = Perfil.NOTAS_FISCAIS
    criar_pdf(raiz / "DANFE" / "0001-EMPRESA EXEMPLO LTDA" / "022026" / "UnePDF"
              / "DANFE - 0001-EMPRESA EXEMPLO LTDA - 022026.pdf")
    _carregar(qtbot, tela, raiz)

    assert tela.resumo_selecao.text() == "3 pastas com PDFs"
    primeira = tela.lista_pastas.topLevelItem(0)
    assert primeira.text(0) == r"DACTE\0002-EXEMPLO TRANSPORTES\012026"
    assert primeira.text(2) == "DACTE - 0002-EXEMPLO TRANSPORTES - 012026.pdf"
    assert tela.botao_unir.text() == "Unir 3 pastas"
    assert "1 unificado já existe e será substituído." in tela.aviso_selecao.text()
    assert tela.contexto.config.ultima_pasta == str(raiz)


def test_desmarcar_pastas(qtbot, tela, raiz):
    _carregar(qtbot, tela, raiz)

    tela.lista_pastas.topLevelItem(0).setCheckState(0, Qt.CheckState.Unchecked)
    assert tela.botao_unir.text() == "Unir 2 pastas"
    assert tela.botao_marcar.text() == "Marcar todas"

    tela.botao_marcar.click()
    assert tela.botao_unir.text() == "Unir 3 pastas"
    tela.botao_marcar.click()
    assert not tela.botao_unir.isEnabled()


def test_arquivos_soltos_pedem_uma_pasta(qtbot, tela, raiz):
    tela.receber_caminhos([raiz / "DANFE" / "0001-EMPRESA EXEMPLO LTDA" / "012026" / "1.pdf"])
    assert tela.estados.currentWidget() is tela.area
    assert "Escolha uma pasta" in tela.area.aviso.text()


def test_pasta_sem_pdfs_vira_aviso(qtbot, tela, tmp_path):
    (tmp_path / "vazia").mkdir()
    tela.receber_caminhos([tmp_path / "vazia"])
    _esperar(qtbot, tela)
    assert "Nenhuma pasta com PDFs" in tela.area.aviso.text()


def test_unir_mostra_o_relatorio(qtbot, tela, raiz, tmp_path, monkeypatch):
    quebrada = raiz / "DACTE" / "0003-EXEMPLO QUEBRADO"
    quebrada.mkdir(parents=True)
    (quebrada / "a.pdf").write_bytes(b"")
    _carregar(qtbot, tela, raiz)
    tela.lista_pastas.topLevelItem(3).setCheckState(0, Qt.CheckState.Unchecked)  # DANFE\...\022026

    tela.botao_unir.click()
    _esperar(qtbot, tela)

    assert tela.estados.currentWidget() is tela.painel_resultado
    assert tela.titulo_resultado.text() == "Lote concluído, com problemas"
    assert tela.resumo_resultado.text() == "2 unificados gerados, 1 pasta com problema."
    lista = tela.lista_resultado
    assert lista.topLevelItemCount() == 3
    problema = lista.topLevelItem(1)
    assert problema.text(0) == r"DACTE\0003-EXEMPLO QUEBRADO"
    assert problema.child(0).text(1) == "arquivo vazio (0 KB)"
    assert not (raiz / "DANFE" / "0001-EMPRESA EXEMPLO LTDA" / "022026" / "UnePDF").exists()

    abertos = []
    monkeypatch.setattr(modulo_lote.sistema, "mostrar_na_pasta", abertos.append)
    tela._mostrar_item(lista.topLevelItem(0))
    assert abertos == [lista.topLevelItem(0).data(0, Qt.ItemDataRole.UserRole)]

    relatorio = tmp_path / "relatorio.txt"
    monkeypatch.setattr(modulo_lote.QFileDialog, "getSaveFileName", lambda *a: (str(relatorio), ""))
    tela.botao_relatorio.click()
    texto = relatorio.read_text(encoding="utf-8-sig")
    assert r"[PROBLEMA] DACTE\0003-EXEMPLO QUEBRADO" in texto
    assert tela.botao_relatorio.text() == "Relatório salvo!"


def test_cancelar_mostra_as_pastas_pendentes(qtbot, tela, raiz, monkeypatch):
    original = lote.unir
    chegou = threading.Event()

    def unir(arquivos, destino, progresso, cancelamento, **opcoes):
        if "022026" in str(destino):
            chegou.set()
            while True:
                cancelamento.verificar()
        return original(arquivos, destino, progresso, cancelamento, **opcoes)

    monkeypatch.setattr(lote, "unir", unir)
    _carregar(qtbot, tela, raiz)

    tela.botao_unir.click()
    qtbot.waitUntil(chegou.is_set)
    tela.progresso.botao_cancelar.click()
    _esperar(qtbot, tela)

    assert tela.titulo_resultado.text() == "Lote cancelado"
    assert "1 pasta não processada" in tela.resumo_resultado.text()
    ultima = tela.lista_resultado.topLevelItem(tela.lista_resultado.topLevelItemCount() - 1)
    assert ultima.text(1) == "Não processada (cancelado)"
