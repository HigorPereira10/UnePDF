import shutil

import pytest
from test_separar import CLIENTE, EMPRESA, FORNECEDOR, OUTRO_FORNECEDOR, danfe

from unepdf.core.separar import COMO_USUARIO, Lado, chave_empresa, formatar_documento
from unepdf.ui.contexto import ContextoApp
from unepdf.ui.janela_principal import JanelaPrincipal


@pytest.fixture
def janela(qtbot, tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    janela = JanelaPrincipal(ContextoApp())
    qtbot.addWidget(janela)
    janela.show()
    return janela


@pytest.fixture
def tela(janela):
    janela.abrir("separar")
    return janela.telas["separar"]


@pytest.fixture
def mes(tmp_path):
    pasta = tmp_path / "Notas" / "DANFE" / "0001-EMPRESA EXEMPLO LTDA" / "012026"
    danfe(pasta, EMPRESA, CLIENTE, 1)
    copia = danfe(pasta, FORNECEDOR, EMPRESA, 2)
    shutil.copy(copia, pasta / "2.pdf")
    danfe(pasta, OUTRO_FORNECEDOR, EMPRESA, 3)
    return pasta


def _esperar(qtbot, tela):
    qtbot.waitUntil(lambda: not tela.executor.em_execucao, timeout=20_000)


def _analisar(qtbot, tela, *pastas):
    tela.receber_caminhos(list(pastas))
    _esperar(qtbot, tela)
    assert tela.estados.currentWidget() is tela.painel_previa


def _nomes(pasta):
    return sorted(p.name for p in pasta.iterdir())


def test_separa_e_desfaz(qtbot, tela, mes):
    antes = _nomes(mes)
    _analisar(qtbot, tela, mes)

    assert tela.resumo_previa.text() == "4 notas em 1 pasta"
    linha = tela.lista_previa.topLevelItem(0)
    assert [linha.text(c) for c in range(6)] == [
        "012026", "11.222.333/0001-81", "1 em EMITIDAS", "2 em RECEBIDAS", "1", "0",
    ]
    assert tela.botao_separar.text() == "Separar 4 notas"
    assert tela.botao_desfazer_anterior.isHidden()

    tela.botao_separar.click()
    _esperar(qtbot, tela)
    assert tela.titulo_resultado.text() == "Notas separadas!"
    assert tela.resumo_resultado.text() == "3 notas separadas, 1 cópia idêntica apagada."
    assert _nomes(mes) == ["EMITIDAS", "RECEBIDAS"]
    # A empresa descoberta pelas notas fica guardada para as pastas de outros tipos
    assert tela.contexto.config.separar_empresas == {chave_empresa(mes): EMPRESA}

    tela.botao_desfazer.click()
    _esperar(qtbot, tela)
    assert tela.titulo_resultado.text() == "Separação desfeita"
    assert _nomes(mes) == sorted(set(antes) - {"2.pdf"})
    assert not tela.botao_desfazer.isEnabled()


def test_empate_pergunta_e_guarda_a_resposta(qtbot, tela, tmp_path, monkeypatch):
    pasta = tmp_path / "DACTE" / "0001-EMPRESA EXEMPLO LTDA" / "012026"
    danfe(pasta, FORNECEDOR, EMPRESA, 1)
    perguntas = []
    monkeypatch.setattr(tela, "_perguntar_empresa", lambda leitura, motivo: perguntas.append(leitura) or EMPRESA)

    _analisar(qtbot, tela, pasta)

    assert len(perguntas) == 1
    assert tela.lista_previa.topLevelItem(0).text(3) == "1 em RECEBIDOS"
    assert COMO_USUARIO in tela.lista_previa.topLevelItem(0).toolTip(1)
    assert tela.contexto.config.separar_empresas[chave_empresa(pasta)] == EMPRESA

    # Na próxima vez, e no outro tipo de documento da mesma empresa, não pergunta de novo
    outra = tmp_path / "DANFE" / "0001-EMPRESA EXEMPLO LTDA" / "022026"
    danfe(outra, FORNECEDOR, EMPRESA, 2)
    tela.limpar()
    _analisar(qtbot, tela, outra)
    assert len(perguntas) == 1


def test_pergunta_vem_com_a_sugestao_do_nome_marcada(tmp_path):
    from test_separar import dacte_em_colunas

    from unepdf.core.separar import ler_pastas
    from unepdf.ui.ferramentas.separar import DialogoEmpresa

    pasta = tmp_path / "DACTE" / "0001-EMPRESA EXEMPLO LTDA" / "012026"
    dacte_em_colunas(pasta, 1, ("DISTRIBUIDORA EXEMPLO SA", FORNECEDOR), ("EMPRESA EXEMPLO LTDA", EMPRESA))
    leitura = ler_pastas([pasta])[0]

    dialogo = DialogoEmpresa(None, leitura, "Qual é a empresa?")
    assert dialogo.escolhido == EMPRESA and dialogo.botao_usar.isEnabled()
    marcada = next(b for b in dialogo._grupo.buttons() if b.isChecked())
    assert "o nome da pasta aparece junto dele" in marcada.text()


def test_pular_a_pasta(qtbot, tela, tmp_path, monkeypatch):
    pasta = tmp_path / "0001-EMPRESA EXEMPLO LTDA" / "012026"
    danfe(pasta, FORNECEDOR, EMPRESA, 1)
    monkeypatch.setattr(tela, "_perguntar_empresa", lambda leitura, motivo: "")

    _analisar(qtbot, tela, pasta)

    assert tela.lista_previa.topLevelItem(0).text(1) == "Pasta pulada: a empresa não foi escolhida."
    assert tela.botao_separar.text() == "Nada para separar" and not tela.botao_separar.isEnabled()
    assert tela.contexto.config.separar_empresas == {}


def test_trocar_a_empresa(qtbot, tela, mes, monkeypatch):
    _analisar(qtbot, tela, mes)
    monkeypatch.setattr(tela, "_perguntar_empresa", lambda leitura, motivo: FORNECEDOR)

    tela.lista_previa.setCurrentItem(tela.lista_previa.topLevelItem(0))
    assert tela.botao_trocar_empresa.isEnabled()
    tela.botao_trocar_empresa.click()
    _esperar(qtbot, tela)

    linha = tela.lista_previa.topLevelItem(0)
    assert linha.text(1) == formatar_documento(FORNECEDOR)
    assert linha.text(2) == "1 em EMITIDAS" and linha.text(5) == "2"


def test_desfazer_uma_separacao_anterior(qtbot, tela, mes):
    _analisar(qtbot, tela, mes)
    tela.botao_separar.click()
    _esperar(qtbot, tela)

    tela.limpar()
    _analisar(qtbot, tela, mes)
    assert tela.botao_separar.text() == "Nada para separar"
    assert not tela.botao_desfazer_anterior.isHidden()

    tela.botao_desfazer_anterior.click()
    _esperar(qtbot, tela)
    assert tela.titulo_resultado.text() == "Separação desfeita"
    assert "EMITIDAS" not in _nomes(mes)


def test_arquivos_em_vez_de_pastas(qtbot, tela, mes):
    tela.receber_caminhos([next(mes.iterdir())])
    assert tela.estados.currentWidget() is tela.area
    assert "Escolha pastas" in tela.area.aviso.text()


def test_unir_com_notas_separadas_vai_para_o_unir_em_lote(qtbot, janela, tmp_path, criar_pdf):
    mes = tmp_path / "DANFE" / "0001-EMPRESA EXEMPLO LTDA" / "012026"
    criar_pdf(mes / "EMITIDAS" / "1.pdf")
    criar_pdf(mes / "RECEBIDAS" / "2.pdf")
    janela.abrir("unir")
    unir = janela.telas["unir"]

    unir.receber_caminhos([mes])
    qtbot.waitUntil(lambda: "unir_lote" in janela.telas and not janela.telas["unir_lote"].executor.em_execucao, timeout=20_000)

    lote = janela.telas["unir_lote"]
    assert janela.pilha.currentWidget() is lote
    assert lote.resumo_selecao.text() == "2 pastas com PDFs"


def test_nomes_das_subpastas_nas_configuracoes(janela):
    janela.abrir("configuracoes")
    tela = janela.tela_configuracoes
    campo = tela.campos_separar["DANFSE", Lado.RECEBIDAS]
    assert campo.text() == "TOMADAS"

    campo.setText("SERVICOS TOMADOS")
    campo.textEdited.emit(campo.text())
    assert tela.contexto.config.separar_pastas == {"DANFSE": {"recebidas": "SERVICOS TOMADOS"}}

    campo.setText("PRESTADAS")
    campo.textEdited.emit(campo.text())
    assert "nomes diferentes" in tela.erro_separar.text()
    assert tela.contexto.config.separar_pastas == {"DANFSE": {"recebidas": "SERVICOS TOMADOS"}}

    campo.setText("TOMADAS")
    campo.textEdited.emit(campo.text())
    assert tela.contexto.config.separar_pastas == {}
