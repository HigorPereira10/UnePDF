"""Inicialização da interface gráfica e tratamento global de erros."""
from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QLibraryInfo, QTimer, QTranslator
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from unepdf import __version__
from unepdf.constantes import APP_ID, APP_NOME
from unepdf.core import configuracoes
from unepdf.ui.coletor import ColetorNaThreadPrincipal
from unepdf.ui.contexto import ContextoApp
from unepdf.ui.dialogos import mostrar_erro
from unepdf.ui.janela_principal import JanelaPrincipal
from unepdf.ui.tema import aplicar_tema
from unepdf.utils import atualizacao, menu_contexto
from unepdf.utils.instancia_unica import InstanciaUnica
from unepdf.utils.logs import configurar_logs
from unepdf.utils.recursos import caminho_recurso
from unepdf.utils.sistema import configurar_id_app

log = logging.getLogger(__name__)

INTERVALO_VERIFICACAO_MS = 4 * 60 * 60 * 1000  # nova consulta de versão a cada 4 horas com o app aberto


def tratar_erro_nao_capturado(tipo, erro, rastro) -> None:
    """Registra no log e mostra uma mensagem amigável, em vez de fechar o app."""
    if issubclass(tipo, KeyboardInterrupt):
        sys.__excepthook__(tipo, erro, rastro)
        return
    log.critical("Erro não tratado", exc_info=(tipo, erro, rastro))
    try:
        mostrar_erro(QApplication.activeWindow(), erro)
    except Exception:
        log.exception("Falha ao exibir a mensagem de erro")


def _tratar_erro_em_thread(argumentos: threading.ExceptHookArgs) -> None:
    # Fora da thread principal não dá para abrir janela: fica só o registro no log
    log.critical(
        "Erro não tratado na thread %s",
        argumentos.thread.name if argumentos.thread else "?",
        exc_info=(argumentos.exc_type, argumentos.exc_value, argumentos.exc_traceback),
    )


def carregar_traducao_do_qt(app: QApplication) -> bool:
    """Traduz para o português os textos prontos do Qt (ex.: menu de copiar e colar dos campos)."""
    tradutor = QTranslator(app)
    if not tradutor.load("qtbase_pt_BR", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        log.warning("Tradução do Qt para português não encontrada")
        return False
    return app.installTranslator(tradutor)


def arquivos_da_linha_de_comando(argumentos: list[str]) -> list[Path]:
    """Arquivos e pastas passados ao programa (pelo Explorer ou soltos no ícone). Opções como --unir são ignoradas."""
    return [Path(a) for a in argumentos if not a.startswith("--")]


def ferramenta_da_linha_de_comando(argumentos: list[str]) -> str:
    """Ferramenta que recebe os arquivos: a separação de notas com --separar, senão o Unir PDFs."""
    return "separar" if menu_contexto.SEPARAR in argumentos else "unir"


def _verificar_nova_versao(janela: JanelaPrincipal) -> None:
    def consultar() -> None:
        janela.nova_versao.emit(atualizacao.procurar(__version__))

    threading.Thread(target=consultar, name="nova-versao", daemon=True).start()


def _verificar_de_tempos_em_tempos(janela: JanelaPrincipal, contexto: ContextoApp) -> None:
    """Quem deixa o app aberto o dia todo também é lembrado da versão nova (o aviso volta a aparecer)."""
    def consultar() -> None:
        if contexto.config.verificar_atualizacoes:
            _verificar_nova_versao(janela)

    relogio = QTimer(janela)
    relogio.setInterval(INTERVALO_VERIFICACAO_MS)
    relogio.timeout.connect(consultar)
    relogio.start()


def executar() -> int:
    configurar_logs()
    arquivos = arquivos_da_linha_de_comando(sys.argv[1:])
    ferramenta = ferramenta_da_linha_de_comando(sys.argv[1:])

    # Com o app já aberto, esta cópia só entrega os arquivos à janela existente e fecha
    instancia = InstanciaUnica()
    if not instancia.tornar_principal():
        mensagem = {"caminhos": [str(c) for c in arquivos], "ferramenta": ferramenta}
        if instancia.enviar(mensagem):
            return 0
        log.warning("Abrindo uma segunda janela: a primeira não respondeu")

    log.info("%s %s iniciado", APP_NOME, __version__)

    # Precisa vir antes de criar a janela para o ícone correto aparecer na barra de tarefas
    configurar_id_app(APP_ID)

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NOME)
    app.setApplicationVersion(__version__)
    app.setWindowIcon(QIcon(str(caminho_recurso("assets/icone.ico"))))
    carregar_traducao_do_qt(app)
    aplicar_tema(app)
    # Precisa existir enquanto o app estiver aberto; o pai (app) mantém o objeto vivo
    ColetorNaThreadPrincipal(app)

    sys.excepthook = tratar_erro_nao_capturado
    threading.excepthook = _tratar_erro_em_thread

    contexto = ContextoApp(configuracoes.carregar())
    janela = JanelaPrincipal(contexto)
    janela.show()

    def ao_receber(mensagem: dict) -> None:
        caminhos = mensagem.get("caminhos") or []
        if caminhos:
            # Mensagens de versões anteriores não dizem a ferramenta: vão para o Unir PDFs
            janela.arquivos_externos.emit(list(caminhos), str(mensagem.get("ferramenta") or "unir"))
        else:
            janela.trazer_para_frente.emit()

    instancia.escutar(ao_receber)
    if arquivos:
        janela.receber_externos(arquivos, ferramenta)
    if contexto.config.verificar_atualizacoes:
        _verificar_nova_versao(janela)
    _verificar_de_tempos_em_tempos(janela, contexto)
    return app.exec()
