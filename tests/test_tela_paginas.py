import pytest
from conftest import numeros_das_paginas
from pypdf import PdfReader
from PySide6.QtCore import QModelIndex, Qt

from unepdf.ui.contexto import ContextoApp
from unepdf.ui.janela_principal import JanelaPrincipal


@pytest.fixture
def janela(qtbot, tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    janela = JanelaPrincipal(ContextoApp())
    qtbot.addWidget(janela)
    janela.show()
    yield janela
    for tela in janela.telas.values():
        tela.encerrar()


def _abrir(qtbot, janela, chave, pdf):
    janela.abrir(chave)
    tela = janela.telas[chave]
    tela.receber_caminhos([pdf])
    qtbot.waitUntil(lambda: not tela.executor.em_execucao, timeout=10_000)
    return tela


def _processar(qtbot, tela):
    tela.botao_principal.click()
    qtbot.waitUntil(lambda: not tela.executor.em_execucao, timeout=10_000)


# Organizar páginas

def test_miniaturas_sao_geradas(qtbot, janela, tmp_path, criar_pdf):
    tela = _abrir(qtbot, janela, "organizar", criar_pdf(tmp_path / "a.pdf", paginas=4))

    assert tela.grade.count() == 4
    qtbot.waitUntil(lambda: len(tela.grade._imagens) == 4, timeout=10_000)
    assert not tela.botao_principal.isEnabled()  # nada alterado ainda


def test_organizar_reordena_gira_e_remove(qtbot, janela, tmp_path, criar_pdf):
    origem = criar_pdf(tmp_path / "a.pdf", paginas=4, identificar=True)
    tela = _abrir(qtbot, janela, "organizar", origem)
    grade = tela.grade

    grade.model().moveRow(QModelIndex(), 3, QModelIndex(), 0)  # o mesmo que arrastar a página 4 para o início
    grade.item(1).setSelected(True)
    tela.botao_girar_direita.click()
    grade.clearSelection()
    grade.item(3).setSelected(True)
    tela.botao_remover.click()
    _processar(qtbot, tela)

    destino = tmp_path / "UNIFICADO" / "a - organizado.pdf"
    assert tela.resultado.destino == destino
    assert numeros_das_paginas(destino) == [4, 1, 2]
    assert [p.rotation for p in PdfReader(destino).pages] == [0, 90, 0]
    assert tela.resultado.resumo.text() == "PDF salvo com 3 páginas."


def test_botoes_de_edicao_dependem_da_selecao(qtbot, janela, tmp_path, criar_pdf):
    tela = _abrir(qtbot, janela, "organizar", criar_pdf(tmp_path / "a.pdf", paginas=2))
    assert not tela.botao_girar_direita.isEnabled()
    tela.grade.item(0).setSelected(True)
    assert tela.botao_girar_direita.isEnabled() and tela.botao_remover.isEnabled()


def test_remover_todas_as_paginas_avisa(qtbot, janela, tmp_path, criar_pdf):
    tela = _abrir(qtbot, janela, "organizar", criar_pdf(tmp_path / "a.pdf", paginas=2))
    tela.grade.selectAll()
    tela.botao_remover.click()

    assert not tela.botao_principal.isEnabled()
    assert "Deixe pelo menos uma" in tela.aviso_opcoes.text()

    tela.botao_restaurar.click()
    assert tela.grade.count() == 2


def test_atalhos_de_teclado(qtbot, janela, tmp_path, criar_pdf):
    tela = _abrir(qtbot, janela, "organizar", criar_pdf(tmp_path / "a.pdf", paginas=3))
    grade = tela.grade
    grade.item(0).setSelected(True)

    qtbot.keyClick(grade, Qt.Key.Key_Right, Qt.KeyboardModifier.ControlModifier)
    assert [indice for indice, _ in grade.plano()] == [1, 0, 2]

    qtbot.keyClick(grade, Qt.Key.Key_Delete)
    assert [indice for indice, _ in grade.plano()] == [1, 2]


def test_trocar_arquivo_para_as_miniaturas(qtbot, janela, tmp_path, criar_pdf):
    tela = _abrir(qtbot, janela, "organizar", criar_pdf(tmp_path / "a.pdf", paginas=30))
    tela.limpar()
    assert tela.estados.currentWidget() is tela.area
    qtbot.waitUntil(lambda: not tela.grade._geradores, timeout=10_000)


# Extrair páginas

def test_digitar_seleciona_as_miniaturas_e_vice_versa(qtbot, janela, tmp_path, criar_pdf):
    tela = _abrir(qtbot, janela, "extrair", criar_pdf(tmp_path / "a.pdf", paginas=6))

    qtbot.keyClicks(tela.campo_paginas, "2-3, 6")
    assert tela.grade.indices_selecionados() == [1, 2, 5]
    assert tela.botao_principal.isEnabled()

    tela.grade.item(0).setSelected(True)
    assert tela.campo_paginas.text() == "1-3, 6"


def test_texto_invalido_avisa_e_desativa(qtbot, janela, tmp_path, criar_pdf):
    tela = _abrir(qtbot, janela, "extrair", criar_pdf(tmp_path / "a.pdf", paginas=3))
    qtbot.keyClicks(tela.campo_paginas, "1, 7")
    assert "A página 7 não existe" in tela.aviso_opcoes.text()
    assert not tela.botao_principal.isEnabled()


def test_extrair_em_um_pdf(qtbot, janela, tmp_path, criar_pdf):
    tela = _abrir(qtbot, janela, "extrair", criar_pdf(tmp_path / "a.pdf", paginas=5, identificar=True))
    qtbot.keyClicks(tela.campo_paginas, "4, 2")
    _processar(qtbot, tela)

    destino = tmp_path / "UNIFICADO" / "a - páginas extraídas.pdf"
    assert numeros_das_paginas(destino) == [2, 4]  # sempre na ordem do documento
    assert tela.resultado.resumo.text() == "2 páginas extraídas para um novo PDF."
    assert tela.resultado.botao_abrir.text() == "Abrir arquivo"


def test_extrair_um_pdf_por_pagina(qtbot, janela, tmp_path, criar_pdf):
    tela = _abrir(qtbot, janela, "extrair", criar_pdf(tmp_path / "a.pdf", paginas=5))
    qtbot.keyClicks(tela.campo_paginas, "1, 5")
    tela.opcao_separadas.click()
    assert tela.rotulo_destino.text() == str(tmp_path / "UNIFICADO" / "a - páginas extraídas")
    _processar(qtbot, tela)

    pasta = tmp_path / "UNIFICADO" / "a - páginas extraídas"
    assert sorted(p.name for p in pasta.iterdir()) == ["a - página 1.pdf", "a - página 5.pdf"]
    assert tela.resultado.botao_abrir.text() == "Abrir pasta"


def test_fechar_a_janela_com_miniaturas_sendo_geradas(qtbot, janela, tmp_path, criar_pdf):
    _abrir(qtbot, janela, "organizar", criar_pdf(tmp_path / "a.pdf", paginas=200))
    janela.close()  # não pode travar nem derrubar o app
    assert not janela.telas["organizar"].grade._gerador
