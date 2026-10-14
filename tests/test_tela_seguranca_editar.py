import pytest
from conftest import criar_pdf_com_texto
from pypdf import PdfReader
from PySide6.QtWidgets import QLineEdit

from unepdf.core.renderizacao import DocumentoRenderizavel
from unepdf.ui.contexto import ContextoApp
from unepdf.ui.janela_principal import JanelaPrincipal


@pytest.fixture
def janela(qtbot, tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    janela = JanelaPrincipal(ContextoApp())
    qtbot.addWidget(janela)
    janela.show()
    return janela


def _esperar(qtbot, tela):
    qtbot.waitUntil(lambda: not tela.executor.em_execucao, timeout=10_000)


def _abrir(qtbot, janela, chave, pdf):
    janela.abrir(chave)
    tela = janela.telas[chave]
    tela.receber_caminhos([pdf])
    _esperar(qtbot, tela)
    return tela


def _processar(qtbot, tela):
    tela.botao_principal.click()
    _esperar(qtbot, tela)


def _texto(pdf):
    with DocumentoRenderizavel(pdf.read_bytes()) as documento:
        return "".join(documento.extrair_texto(i) for i in range(documento.total))


# Proteger

def test_proteger_valida_as_senhas(qtbot, janela, tmp_path, criar_pdf):
    tela = _abrir(qtbot, janela, "proteger", criar_pdf(tmp_path / "a.pdf"))
    assert not tela.botao_principal.isEnabled()

    tela.campo_senha.setText("12")
    assert "pelo menos 4" in tela.aviso_opcoes.text()
    tela.campo_senha.setText("1234")
    tela.campo_confirmacao.setText("1235")
    assert "não são iguais" in tela.aviso_opcoes.text()
    assert not tela.botao_principal.isEnabled()

    tela.campo_confirmacao.setText("1234")
    assert tela.botao_principal.isEnabled()


def test_proteger_ate_o_resultado(qtbot, janela, tmp_path, criar_pdf):
    tela = _abrir(qtbot, janela, "proteger", criar_pdf(tmp_path / "a.pdf"))
    tela.campo_senha.setText("segredo1")
    tela.campo_confirmacao.setText("segredo1")
    _processar(qtbot, tela)

    destino = tmp_path / "UnePDF" / "a - protegido.pdf"
    assert tela.resultado.destino == destino
    leitor = PdfReader(destino)
    assert leitor.is_encrypted and leitor.decrypt("segredo1")


def test_mostrar_senha(qtbot, janela, tmp_path, criar_pdf):
    tela = _abrir(qtbot, janela, "proteger", criar_pdf(tmp_path / "a.pdf"))
    tela.mostrar.setChecked(True)
    assert tela.campo_senha.echoMode() == QLineEdit.EchoMode.Normal
    tela.mostrar.setChecked(False)
    assert tela.campo_confirmacao.echoMode() == QLineEdit.EchoMode.Password


# Remover senha

def test_remover_senha_errada_avisa_sem_janela(qtbot, janela, tmp_path, criar_pdf):
    tela = _abrir(qtbot, janela, "remover_senha", criar_pdf(tmp_path / "a.pdf", senha="1234"))
    assert tela.detalhes_arquivo.text() == "Protegido por senha"

    tela.campo_senha.setText("errada")
    _processar(qtbot, tela)

    assert tela.estados.currentWidget() is tela.painel_opcoes
    assert "Senha incorreta" in tela.aviso_opcoes.text()

    tela.campo_senha.setText("1234")
    _processar(qtbot, tela)
    assert not PdfReader(tmp_path / "UnePDF" / "a - sem senha.pdf").is_encrypted


def test_remover_senha_de_pdf_com_restricoes_explica_a_senha_do_proprietario(qtbot, janela, tmp_path, criar_pdf):
    pdf = criar_pdf(tmp_path / "a.pdf", senha_dono="dono", algoritmo="AES-256")
    tela = _abrir(qtbot, janela, "remover_senha", pdf)
    assert tela.detalhes_arquivo.text() == "Com restrições de permissão"
    assert "senha do proprietário" in tela.explicacao.text()


def test_remover_senha_de_pdf_sem_senha_avisa_na_escolha(qtbot, janela, tmp_path, criar_pdf):
    tela = _abrir(qtbot, janela, "remover_senha", criar_pdf(tmp_path / "a.pdf"))
    assert tela.estados.currentWidget() is tela.area
    assert "não tem senha" in tela.area.aviso.text()


# Marca d'água e numeração

def test_marca_dagua(qtbot, janela, tmp_path):
    tela = _abrir(qtbot, janela, "marca_dagua", criar_pdf_com_texto(tmp_path / "a.pdf", ["texto"]))
    tela.campo_texto.setText("RASCUNHO")
    tela.campo_opacidade.setValue(40)
    assert tela.rotulo_opacidade.text() == "40%"
    _processar(qtbot, tela)

    destino = tmp_path / "UnePDF" / "a - marca d'água.pdf"
    assert "RASCUNHO" in _texto(destino)


def test_marca_dagua_recusa_emoji(qtbot, janela, tmp_path, criar_pdf):
    tela = _abrir(qtbot, janela, "marca_dagua", criar_pdf(tmp_path / "a.pdf"))
    tela.campo_texto.setText("OK ✅")
    assert not tela.botao_principal.isEnabled()
    assert "emojis" in tela.aviso_opcoes.text()


def test_numerar(qtbot, janela, tmp_path):
    tela = _abrir(qtbot, janela, "numerar", criar_pdf_com_texto(tmp_path / "a.pdf", ["capa", "b", "c"]))
    tela.campo_formato.setCurrentIndex(2)  # "1 / 10"
    tela.pular_capa.setChecked(True)
    _processar(qtbot, tela)

    texto = _texto(tmp_path / "UnePDF" / "a - numerado.pdf")
    assert "2 / 3" in texto and "3 / 3" in texto and "1 / 3" not in texto
