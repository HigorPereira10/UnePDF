import io
import json
import sys
import threading
import uuid
from pathlib import Path

import pytest

from unepdf.ui.app import arquivos_da_linha_de_comando, ferramenta_da_linha_de_comando
from unepdf.ui.contexto import ContextoApp
from unepdf.ui.janela_principal import JanelaPrincipal
from unepdf.utils import atualizacao, menu_contexto
from unepdf.utils.instancia_unica import InstanciaUnica


@pytest.fixture
def janela(qtbot, tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    janela = JanelaPrincipal(ContextoApp())
    qtbot.addWidget(janela)
    janela.show()
    return janela


# Instância única

def test_so_a_primeira_copia_e_a_principal():
    nome = f"UnePDF-teste-{uuid.uuid4().hex}"
    primeira, segunda = InstanciaUnica(nome), InstanciaUnica(nome)
    assert primeira.tornar_principal()
    assert not segunda.tornar_principal()


def test_mensagens_chegam_a_copia_principal():
    nome = f"UnePDF-teste-{uuid.uuid4().hex}"
    principal = InstanciaUnica(nome)
    recebidas, chegou = [], threading.Event()

    def ao_receber(mensagem):
        recebidas.append(mensagem)
        if len(recebidas) == 2:
            chegou.set()

    principal.escutar(ao_receber)
    assert InstanciaUnica(nome).enviar({"caminhos": ["a.pdf"]})
    assert InstanciaUnica(nome).enviar({"caminhos": ["b.pdf"]})
    assert chegou.wait(5)
    assert recebidas == [{"caminhos": ["a.pdf"]}, {"caminhos": ["b.pdf"]}]


def test_sem_copia_principal_o_envio_desiste():
    assert not InstanciaUnica(f"UnePDF-teste-{uuid.uuid4().hex}").enviar({"caminhos": []}, tempo_limite=0.3)


def test_arquivos_da_linha_de_comando():
    assert arquivos_da_linha_de_comando(["--unir", r"C:\Notas\a.pdf", r"C:\Notas"]) == [
        Path(r"C:\Notas\a.pdf"), Path(r"C:\Notas"),
    ]
    assert arquivos_da_linha_de_comando([]) == []
    assert ferramenta_da_linha_de_comando(["--unir", r"C:\Notas"]) == "unir"
    assert ferramenta_da_linha_de_comando(["--separar", r"C:\Notas\012026"]) == "separar"
    assert ferramenta_da_linha_de_comando([r"C:\Notas\a.pdf"]) == "unir"


def test_arquivos_que_chegam_juntos_vao_de_uma_vez_para_o_unir(qtbot, janela, tmp_path, criar_pdf):
    a, b = criar_pdf(tmp_path / "a.pdf"), criar_pdf(tmp_path / "b.pdf", paginas=2)

    janela.receber_externos([a])
    janela.arquivos_externos.emit([str(b), str(a)], "unir")  # como chega de outra cópia, repetindo um arquivo

    tela = None
    qtbot.waitUntil(lambda: "unir" in janela.telas and not janela.telas["unir"].executor.em_execucao
                    and janela.telas["unir"].estados.currentWidget() is janela.telas["unir"].painel_selecao,
                    timeout=10_000)
    tela = janela.telas["unir"]
    assert tela.lista_arquivos.arquivos() == [a, b]
    assert janela.pilha.currentWidget() is tela


def test_pastas_do_explorer_vao_para_a_separacao(qtbot, janela, tmp_path, monkeypatch, criar_pdf):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    janeiro, fevereiro = tmp_path / "012026", tmp_path / "022026"
    criar_pdf(janeiro / "1.pdf")
    criar_pdf(fevereiro / "1.pdf")

    janela.receber_externos([janeiro], "separar")
    janela.arquivos_externos.emit([str(fevereiro)], "separar")

    qtbot.waitUntil(lambda: "separar" in janela.telas and not janela.telas["separar"].executor.em_execucao
                    and janela.telas["separar"].estados.currentWidget() is janela.telas["separar"].painel_previa,
                    timeout=10_000)
    tela = janela.telas["separar"]
    assert janela.pilha.currentWidget() is tela
    assert tela.resumo_previa.text() == "2 notas em 2 pastas"


# Nova versão

class _Resposta(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _publicada(monkeypatch, **dados):
    corpo = {"tag_name": "v2.1.0", "html_url": "https://github.com/exemplo/releases/tag/v2.1.0", **dados}
    monkeypatch.setattr(atualizacao.urllib.request, "urlopen",
                        lambda pedido, timeout: _Resposta(json.dumps(corpo).encode()))


def test_numero_da_versao():
    assert atualizacao.numero("v2.10.1") == (2, 10, 1)
    assert atualizacao.numero("2.0.0-beta") == (2, 0, 0)
    assert atualizacao.numero("v2.10.0") > atualizacao.numero("2.9.9")


def test_avisa_so_quando_a_publicada_e_mais_nova(monkeypatch):
    _publicada(monkeypatch)
    assert atualizacao.procurar("2.0.0") == atualizacao.NovaVersao("2.1.0", "https://github.com/exemplo/releases/tag/v2.1.0")
    assert atualizacao.procurar("2.1.0") is None
    assert atualizacao.procurar("3.0.0") is None
    _publicada(monkeypatch, prerelease=True)
    assert atualizacao.procurar("2.0.0") is None


def test_sem_internet_fica_em_silencio(monkeypatch):
    def falhar(pedido, timeout):
        raise OSError("sem conexão")

    monkeypatch.setattr(atualizacao.urllib.request, "urlopen", falhar)
    assert atualizacao.procurar("2.0.0") is None


def test_aviso_de_nova_versao_na_barra_lateral(janela, monkeypatch):
    assert janela.aviso_versao.isHidden()
    janela.nova_versao.emit(None)
    assert janela.aviso_versao.isHidden()

    abertos = []
    monkeypatch.setattr("unepdf.ui.janela_principal.QDesktopServices.openUrl", lambda url: abertos.append(url.toString()))
    janela.nova_versao.emit(atualizacao.NovaVersao("2.1.0", "https://github.com/exemplo/releases/tag/v2.1.0"))
    assert not janela.aviso_versao.isHidden()
    assert janela.aviso_versao.text() == "Nova versão 2.1.0 disponível"
    janela.aviso_versao.click()
    assert abertos == ["https://github.com/exemplo/releases/tag/v2.1.0"]


# Menu do Explorer, com um registro do Windows de mentira

class _RegistroFalso:
    HKEY_CURRENT_USER = "HKCU"
    REG_SZ = 1

    def __init__(self):
        self.chaves: dict[str, dict] = {}

    class _Chave:
        def __init__(self, nome):
            self.nome = nome

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def CreateKey(self, raiz, nome):
        self.chaves.setdefault(nome, {})
        return self._Chave(nome)

    def OpenKey(self, raiz, nome):
        if nome not in self.chaves:
            raise OSError("não existe")
        return self._Chave(nome)

    def SetValueEx(self, chave, valor, _reservado, _tipo, dado):
        self.chaves[chave.nome][valor] = dado

    def DeleteKey(self, raiz, nome):
        if nome not in self.chaves:
            raise OSError("não existe")
        del self.chaves[nome]


@pytest.fixture
def registro(monkeypatch):
    falso = _RegistroFalso()
    monkeypatch.setitem(sys.modules, "winreg", falso)
    return falso


def test_instala_e_remove_o_item_do_explorer(registro):
    assert not menu_contexto.instalado()

    menu_contexto.instalar()

    assert menu_contexto.instalado()
    pdf = registro.chaves[r"Software\Classes\SystemFileAssociations\.pdf\shell\UnePDF.Unir"]
    assert pdf["MUIVerb"] == "Unir com UnePDF" and pdf["MultiSelectModel"] == "Player"
    comando = registro.chaves[r"Software\Classes\Directory\shell\UnePDF.Unir\command"][""]
    assert comando.endswith('--unir "%1"')
    separar = registro.chaves[r"Software\Classes\Directory\shell\UnePDF.Separar"]
    assert separar["MUIVerb"] == "Separar emitidas e recebidas (UnePDF)" and separar["MultiSelectModel"] == "Player"
    assert registro.chaves[r"Software\Classes\Directory\shell\UnePDF.Separar\command"][""].endswith('--separar "%1"')

    menu_contexto.remover()
    assert not menu_contexto.instalado() and registro.chaves == {}


def test_item_novo_faltando_conta_como_desligado(registro):
    # Quem ligou o menu numa versão anterior só tem o "Unir": a caixa aparece desmarcada para ligar de novo
    menu_contexto.instalar()
    del registro.chaves[r"Software\Classes\Directory\shell\UnePDF.Separar\command"]
    assert not menu_contexto.instalado()


def test_comando_do_executavel_e_do_codigo_fonte(monkeypatch):
    assert "__main__.py" in menu_contexto.comando()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Programas\UnePDF\UnePDF.exe")
    assert menu_contexto.comando() == r'"C:\Programas\UnePDF\UnePDF.exe" --unir "%1"'


def test_configuracoes_ligam_o_item_do_explorer(janela, registro):
    janela.abrir("configuracoes")
    tela = janela.tela_configuracoes
    # A tela leu o registro do Windows ao abrir, e nele o item pode estar instalado de verdade
    tela.carregar()
    assert not tela.check_menu_explorer.isChecked()

    tela.check_menu_explorer.setChecked(True)
    assert menu_contexto.instalado()
    tela.check_menu_explorer.setChecked(False)
    assert not menu_contexto.instalado()

    tela.check_atualizacoes.setChecked(False)
    assert tela.contexto.config.verificar_atualizacoes is False
