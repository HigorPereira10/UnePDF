import hashlib
import io
import json
import sys
from pathlib import Path

import pytest

from unepdf.core.erros import ErroUnePDF, OperacaoCancelada
from unepdf.core.progresso import Cancelamento
from unepdf.ui.atualizacao import DialogoAtualizacao
from unepdf.ui.contexto import ContextoApp
from unepdf.ui.janela_principal import JanelaPrincipal
from unepdf.utils import atualizacao
from unepdf.utils.atualizacao import Instalador, NovaVersao

DOWNLOAD = "https://github.com/HigorPereira10/UnePDF/releases/download/v2.2.0/"
CONTEUDO = b"instalador de mentira " * 5000


class _Resposta(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _arquivo(nome="UnePDF-2.2.0-instalador.exe", url=None, digest="sha256:" + "a" * 64):
    return {"name": nome, "browser_download_url": url or DOWNLOAD + nome, "size": 123, "digest": digest}


def _publicada(monkeypatch, *arquivos):
    corpo = {"tag_name": "v2.2.0", "html_url": "https://github.com/exemplo/releases/tag/v2.2.0", "assets": list(arquivos)}
    monkeypatch.setattr(atualizacao.urllib.request, "urlopen", lambda pedido, timeout: _Resposta(json.dumps(corpo).encode()))


def _instalador(conteudo=CONTEUDO, **troca):
    dados = {"nome": "UnePDF-2.2.0-instalador.exe", "url": DOWNLOAD + "UnePDF-2.2.0-instalador.exe",
             "tamanho": len(conteudo), "sha256": hashlib.sha256(conteudo).hexdigest(), **troca}
    return Instalador(**dados)


def _servir(monkeypatch, conteudo=CONTEUDO):
    monkeypatch.setattr(atualizacao.urllib.request, "urlopen", lambda pedido, timeout: _Resposta(conteudo))


# Consulta

def test_acha_o_instalador_da_versao_nova(monkeypatch):
    _publicada(monkeypatch, _arquivo("UnePDF-2.2.0-portatil.zip"), _arquivo())
    nova = atualizacao.procurar("2.1.1")
    assert nova.versao == "2.2.0"
    assert nova.instalador == Instalador("UnePDF-2.2.0-instalador.exe", DOWNLOAD + "UnePDF-2.2.0-instalador.exe", 123, "a" * 64)


@pytest.mark.parametrize("arquivo", [
    _arquivo(digest=None),  # sem o SHA-256 não dá para conferir
    _arquivo(url="https://outro-site.exemplo/UnePDF-2.2.0-instalador.exe"),
    _arquivo("UnePDF-2.1.0-instalador.exe"),
])
def test_sem_instalador_conferivel_o_aviso_leva_a_pagina(monkeypatch, arquivo):
    _publicada(monkeypatch, arquivo)
    nova = atualizacao.procurar("2.1.1")
    assert nova.versao == "2.2.0" and nova.instalador is None


def test_so_a_versao_instalada_atualiza_pelo_app(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "executable", str(tmp_path / "UnePDF.exe"))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert not atualizacao.pode_atualizar_pelo_app()  # portátil: sem desinstalador
    (tmp_path / "unins000.exe").write_bytes(b"")
    assert atualizacao.pode_atualizar_pelo_app()
    monkeypatch.setattr(sys, "frozen", False)
    assert not atualizacao.pode_atualizar_pelo_app()  # código-fonte


# Download

def test_baixa_e_confere(monkeypatch, tmp_path):
    (tmp_path / "UnePDF-2.1.1-instalador.exe").write_bytes(b"antigo")
    _servir(monkeypatch)
    andamento = []
    destino = atualizacao.baixar(_instalador(), tmp_path, lambda a, t, d: andamento.append((a, t)))
    assert destino.read_bytes() == CONTEUDO
    assert sorted(p.name for p in tmp_path.iterdir()) == ["UnePDF-2.2.0-instalador.exe"]
    assert andamento[-1] == (len(CONTEUDO), len(CONTEUDO))


@pytest.mark.parametrize("instalador", [
    _instalador(sha256="0" * 64),  # conteúdo diferente do publicado
    _instalador(tamanho=len(CONTEUDO) + 1),  # download incompleto
])
def test_arquivo_que_nao_confere_e_descartado(monkeypatch, tmp_path, instalador):
    _servir(monkeypatch)
    with pytest.raises(ErroUnePDF, match="não confere"):
        atualizacao.baixar(instalador, tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_falha_de_rede_vira_mensagem(monkeypatch, tmp_path):
    def falhar(pedido, timeout):
        raise OSError("sem conexão")

    monkeypatch.setattr(atualizacao.urllib.request, "urlopen", falhar)
    with pytest.raises(ErroUnePDF, match="Não foi possível baixar"):
        atualizacao.baixar(_instalador(), tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_cancelar_o_download(monkeypatch, tmp_path):
    _servir(monkeypatch)
    cancelamento = Cancelamento()
    cancelamento.cancelar()
    with pytest.raises(OperacaoCancelada):
        atualizacao.baixar(_instalador(), tmp_path, cancelamento=cancelamento)
    assert list(tmp_path.iterdir()) == []


def test_comando_espera_o_app_fechar_e_instala_em_silencio():
    comando = atualizacao.comando_de_instalacao(Path(r"C:\Dados\O'Brien\UnePDF-2.2.0-instalador.exe"), 4321, Path(r"C:\Logs\a.log"))
    assert comando[0] == "powershell.exe"
    script = comando[-1]
    assert script.index("Get-Process -Id 4321") < script.index("Start-Process")
    assert r"'C:\Dados\O''Brien\UnePDF-2.2.0-instalador.exe'" in script
    for argumento in ("'/VERYSILENT'", "'/SUPPRESSMSGBOXES'", "'/abrir=1'", r"""'/LOG="C:\Logs\a.log"'"""):
        assert argumento in script


# Interface

@pytest.fixture
def janela(qtbot, tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    janela = JanelaPrincipal(ContextoApp())
    qtbot.addWidget(janela)
    janela.show()
    return janela


NOVA = NovaVersao("2.2.0", "https://github.com/exemplo/releases/tag/v2.2.0", _instalador())


def test_faixa_atualiza_pelo_app(janela, monkeypatch, tmp_path):
    monkeypatch.setattr(atualizacao, "pode_atualizar_pelo_app", lambda: True)
    baixado = tmp_path / "UnePDF-2.2.0-instalador.exe"
    agendados, fechou = [], []
    monkeypatch.setattr(janela, "_baixar_atualizacao", lambda nova: baixado)
    monkeypatch.setattr(atualizacao, "instalar_depois_de_fechar", lambda instalador, registro: agendados.append(instalador))
    monkeypatch.setattr(janela, "_fechar_para_atualizar", lambda: fechou.append(True))

    janela.nova_versao.emit(NOVA)
    assert not janela.faixa_versao.isHidden()
    assert "2.2.0" in janela.faixa_versao.texto.text()
    assert janela.faixa_versao.botao_atualizar.text() == "Atualizar agora"

    janela.faixa_versao.botao_atualizar.click()
    assert agendados == [baixado] and fechou == [True]


def test_nao_atualiza_com_ferramenta_trabalhando(janela, monkeypatch):
    monkeypatch.setattr(atualizacao, "pode_atualizar_pelo_app", lambda: True)
    baixou = []
    monkeypatch.setattr(janela, "_baixar_atualizacao", lambda nova: baixou.append(nova))
    janela.abrir("unir")
    janela.nova_versao.emit(NOVA)
    with monkeypatch.context() as trabalhando:
        trabalhando.setattr(type(janela.telas["unir"].executor), "em_execucao", property(lambda self: True))
        janela.faixa_versao.botao_atualizar.click()
    assert baixou == []
    assert "Espere ela terminar" in janela.faixa_versao.texto.text()


def test_versao_portatil_baixa_pela_pagina(janela, monkeypatch):
    monkeypatch.setattr(atualizacao, "pode_atualizar_pelo_app", lambda: False)
    abertos = []
    monkeypatch.setattr("unepdf.ui.janela_principal.QDesktopServices.openUrl", lambda url: abertos.append(url.toString()))

    janela.nova_versao.emit(NOVA)
    assert janela.faixa_versao.botao_atualizar.text() == "Baixar"
    janela.faixa_versao.botao_atualizar.click()
    assert abertos == [NOVA.pagina]


def test_depois_esconde_ate_o_proximo_aviso(janela):
    janela.nova_versao.emit(NOVA)
    janela.faixa_versao.botao_depois.click()
    assert janela.faixa_versao.isHidden()
    assert not janela.aviso_versao.isHidden()  # a barra lateral continua lembrando

    janela.nova_versao.emit(NOVA)  # nova consulta, horas depois
    assert not janela.faixa_versao.isHidden()


def test_dialogo_baixa_com_progresso(qtbot, monkeypatch, tmp_path):
    def baixar(instalador, pasta, progresso, cancelamento):
        progresso(50, 100, "1 de 2 MB")
        return tmp_path / instalador.nome

    monkeypatch.setattr(atualizacao, "baixar", baixar)
    dialogo = DialogoAtualizacao(None, NOVA)
    qtbot.addWidget(dialogo)
    dialogo.iniciar()
    qtbot.waitUntil(lambda: dialogo.instalador is not None, timeout=5000)
    assert dialogo.instalador == tmp_path / "UnePDF-2.2.0-instalador.exe"


def test_dialogo_mostra_a_falha(qtbot, monkeypatch):
    def baixar(instalador, pasta, progresso, cancelamento):
        raise ErroUnePDF("O arquivo baixado não confere com o publicado e foi descartado.")

    monkeypatch.setattr(atualizacao, "baixar", baixar)
    dialogo = DialogoAtualizacao(None, NOVA)
    qtbot.addWidget(dialogo)
    dialogo.iniciar()
    qtbot.waitUntil(lambda: not dialogo.erro.isHidden(), timeout=5000)
    assert "não confere" in dialogo.erro.text()
    assert dialogo.instalador is None and dialogo.botao.text() == "Fechar"
