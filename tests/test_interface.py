import logging

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from unepdf.core.erros import ErroUnePDF
from unepdf.ui import app as modulo_app
from unepdf.ui import janela_principal as modulo_janela
from unepdf.ui.componentes import CartaoFerramenta
from unepdf.ui.contexto import ContextoApp
from unepdf.ui.dialogos import DialogoErro
from unepdf.ui.ferramentas import FERRAMENTAS
from unepdf.ui.janela_principal import JanelaPrincipal
from unepdf.ui.tema import aplicar_tema


@pytest.fixture
def janela(qtbot, qapp):
    aplicar_tema(qapp)
    janela = JanelaPrincipal(ContextoApp())
    qtbot.addWidget(janela)
    janela.show()
    return janela


def test_abre_na_tela_inicial_com_um_cartao_por_ferramenta(janela):
    assert janela.pilha.currentWidget() is janela.tela_inicial
    assert [c.chave for c in janela.tela_inicial.cartoes] == [f.chave for f in FERRAMENTAS]


def test_clicar_no_cartao_abre_a_ferramenta_e_a_lateral_volta_ao_inicio(qtbot, janela):
    cartao = janela.tela_inicial.cartoes[0]
    qtbot.mouseClick(cartao, Qt.MouseButton.LeftButton)

    assert janela.pilha.currentWidget() is janela.telas[cartao.chave]
    assert janela._botoes_por_chave[cartao.chave].isChecked()

    qtbot.mouseClick(janela._botoes_por_chave["inicio"], Qt.MouseButton.LeftButton)
    assert janela.pilha.currentWidget() is janela.tela_inicial


def test_cartao_abre_pelo_teclado(qtbot, janela):
    cartao = janela.tela_inicial.cartoes[0]
    qtbot.keyClick(cartao, Qt.Key.Key_Return)
    assert janela.pilha.currentWidget() is janela.telas[cartao.chave]


def test_tela_da_ferramenta_e_criada_uma_vez(janela):
    janela.abrir("unir")
    primeira = janela.telas["unir"]
    janela.abrir("inicio")
    janela.abrir("unir")
    assert janela.telas["unir"] is primeira


def test_cartao_indisponivel_mostra_o_motivo(qtbot):
    cartao = CartaoFerramenta("x", "Teste", "Descrição", "assets/icones/unir.svg", "Requer o Ghostscript.")
    qtbot.addWidget(cartao)
    assert cartao.property("disponivel") is False
    assert cartao.toolTip() == "Requer o Ghostscript."


@pytest.mark.parametrize("confirmou", [False, True])
def test_fechar_com_operacao_em_andamento_pergunta(qtbot, janela, monkeypatch, confirmou):
    janela.abrir("unir")
    executor = janela.telas["unir"].executor

    def tarefa(progresso, cancelamento):
        while True:
            cancelamento.verificar()

    executor.executar(tarefa)
    monkeypatch.setattr(modulo_janela, "perguntar", lambda *a, **k: confirmou)

    janela.close()

    assert janela.isVisible() is not confirmou
    if not confirmou:
        executor.cancelar()
        assert executor.aguardar()


def test_dialogo_de_erro_copia_os_detalhes(qtbot):
    try:
        raise ValueError("causa técnica")
    except ValueError as erro:
        dialogo = DialogoErro(None, erro)
    qtbot.addWidget(dialogo)

    qtbot.mouseClick(dialogo.botao_copiar, Qt.MouseButton.LeftButton)

    assert "causa técnica" in QApplication.clipboard().text()
    assert dialogo.botao_copiar.text() == "Copiado!"


def test_dialogo_so_sugere_relatar_em_erro_inesperado(qtbot):
    from PySide6.QtWidgets import QLabel

    def textos(dialogo):
        return " ".join(r.text() for r in dialogo.findChildren(QLabel))

    previsto = DialogoErro(None, ErroUnePDF("Pasta não encontrada."))
    inesperado = DialogoErro(None, ZeroDivisionError())
    qtbot.addWidget(previsto)
    qtbot.addWidget(inesperado)

    assert "issues" not in textos(previsto)
    assert "issues" in textos(inesperado)


def test_erro_nao_capturado_vai_para_o_log_e_vira_mensagem(qapp, monkeypatch, caplog):
    mostrados = []
    monkeypatch.setattr(modulo_app, "mostrar_erro", lambda pai, erro: mostrados.append(erro))
    erro = RuntimeError("falha num clique")

    with caplog.at_level(logging.CRITICAL):
        modulo_app.tratar_erro_nao_capturado(RuntimeError, erro, None)

    assert mostrados == [erro]
    assert "Erro não tratado" in caplog.text


def test_contexto_salva_e_tolera_falha(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    contexto = ContextoApp()
    contexto.config.pasta_saida = "RESULTADO"

    contexto.salvar_config()
    assert "RESULTADO" in (tmp_path / "UnePDF" / "config.json").read_text(encoding="utf-8")

    # Um arquivo no lugar da pasta impede a gravação, mas não pode quebrar o app
    bloqueio = tmp_path / "bloqueio"
    bloqueio.write_text("x")
    monkeypatch.setenv("APPDATA", str(bloqueio))
    contexto.salvar_config()


def test_ponto_de_entrada_importa():
    import unepdf.__main__ as principal

    assert callable(principal.main)
