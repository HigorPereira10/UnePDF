import json

import pytest

from unepdf.core.nomenclatura import Perfil
from unepdf.ui import tela_configuracoes as modulo_configuracoes
from unepdf.ui.contexto import ContextoApp
from unepdf.ui.janela_principal import JanelaPrincipal


@pytest.fixture
def appdata(tmp_path, monkeypatch):
    pasta = tmp_path / "appdata"
    monkeypatch.setenv("APPDATA", str(pasta))
    return pasta


@pytest.fixture
def janela(qtbot, appdata):
    janela = JanelaPrincipal(ContextoApp())
    qtbot.addWidget(janela)
    janela.show()
    janela.abrir("configuracoes")
    return janela


@pytest.fixture
def tela(janela):
    return janela.tela_configuracoes


def _gravado(appdata) -> dict:
    return json.loads((appdata / "UnePDF" / "config.json").read_text(encoding="utf-8"))


def test_abre_pela_barra_lateral(janela, tela):
    assert janela.pilha.currentWidget() is tela
    assert janela._botoes_por_chave["configuracoes"].isChecked()


def test_mostra_os_valores_atuais(qtbot, appdata):
    contexto = ContextoApp()
    contexto.config.pasta_inicial = r"\\servidor\documentos\notas"
    contexto.config.pasta_saida = "RESULTADO"
    contexto.config.perfil_nomenclatura = Perfil.NOTAS_FISCAIS
    janela = JanelaPrincipal(contexto)
    qtbot.addWidget(janela)
    tela = janela.tela_configuracoes

    assert tela.campo_pasta_inicial.text() == r"\\servidor\documentos\notas"
    assert tela.campo_pasta_saida.text() == "RESULTADO"
    assert tela.opcao_notas.isChecked()
    assert tela.previa.text().endswith(r"\RESULTADO\DANFE - 0001-EMPRESA EXEMPLO LTDA - 012026.pdf")


def test_trocar_perfil_salva_e_atualiza_a_previa(tela, appdata):
    tela.opcao_notas.click()

    assert tela.contexto.config.perfil_nomenclatura is Perfil.NOTAS_FISCAIS
    assert _gravado(appdata)["perfil_nomenclatura"] == "notas_fiscais"
    assert "DANFE - 0001-EMPRESA EXEMPLO LTDA - 012026.pdf" in tela.previa.text()

    tela.opcao_generico.click()
    assert tela.previa.text().endswith("Notas de janeiro - UNIFICADO.pdf")


def test_subpasta_de_saida_valida_e_salva(qtbot, tela, appdata):
    tela.campo_pasta_saida.clear()
    qtbot.keyClicks(tela.campo_pasta_saida, "RESULTADO")

    assert tela.contexto.config.pasta_saida == "RESULTADO"
    assert _gravado(appdata)["pasta_saida"] == "RESULTADO"
    assert "\\RESULTADO\\" in tela.previa.text()


def test_subpasta_de_saida_invalida_nao_e_salva(qtbot, tela):
    qtbot.keyClicks(tela.campo_pasta_saida, "/x")

    assert tela.contexto.config.pasta_saida == "UNIFICADO"
    assert not tela.erro_pasta_saida.isHidden()


def test_escolher_e_limpar_pasta_inicial(tela, appdata, tmp_path, monkeypatch):
    monkeypatch.setattr(modulo_configuracoes.QFileDialog, "getExistingDirectory", lambda *a: str(tmp_path))

    tela._escolher_pasta_inicial()
    assert tela.campo_pasta_inicial.text() == str(tmp_path)
    assert _gravado(appdata)["pasta_inicial"] == str(tmp_path)

    tela._definir_pasta_inicial("")
    assert _gravado(appdata)["pasta_inicial"] == ""


def test_restaurar_padroes_mantem_a_ultima_pasta(tela, monkeypatch):
    config = tela.contexto.config
    config.pasta_saida = "RESULTADO"
    config.perfil_nomenclatura = Perfil.NOTAS_FISCAIS
    config.ultima_pasta = r"C:\Notas"
    monkeypatch.setattr(modulo_configuracoes, "perguntar", lambda *a, **k: True)

    tela._restaurar_padroes()

    assert (config.pasta_saida, config.perfil_nomenclatura, config.ultima_pasta) == (
        "UNIFICADO", Perfil.GENERICO, r"C:\Notas"
    )
    assert tela.opcao_generico.isChecked()


def test_abrir_pasta_de_registros(tela, tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    abertos = []
    monkeypatch.setattr(modulo_configuracoes.sistema, "abrir_arquivo", abertos.append)

    tela._abrir_logs()

    assert abertos == [tmp_path / "UnePDF" / "logs"]


def test_mudanca_nas_configuracoes_atualiza_o_destino_da_selecao(qtbot, janela, tmp_path, criar_pdf):
    pasta = tmp_path / "Janeiro"
    criar_pdf(pasta / "a.pdf")
    janela.abrir("unir")
    unir = janela.telas["unir"]
    unir.receber_caminhos([pasta])
    qtbot.waitUntil(lambda: not unir.executor.em_execucao)

    janela.abrir("configuracoes")
    janela.tela_configuracoes.campo_pasta_saida.setText("RESULTADO")
    janela.tela_configuracoes._alterar_pasta_saida("RESULTADO")
    janela.abrir("unir")
    qtbot.waitUntil(lambda: not unir.executor.em_execucao)

    assert unir.destino_selecao.text() == str(pasta / "RESULTADO" / "Janeiro - UNIFICADO.pdf")
