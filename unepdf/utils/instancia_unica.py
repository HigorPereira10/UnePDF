"""Instância única do app, para o "Unir com UnePDF" do Explorer.

Com vários arquivos selecionados, o Explorer abre o programa uma vez para cada arquivo. A primeira
cópia vira a principal; as outras entregam seus arquivos a ela por um canal local (named pipe do
Windows) e fecham. Assim todos os arquivos chegam juntos na mesma janela.
"""
from __future__ import annotations

import ctypes
import getpass
import hashlib
import logging
import threading
import time
from multiprocessing.connection import Client, Listener
from typing import Callable

log = logging.getLogger(__name__)

ERRO_JA_EXISTE = 183  # ERROR_ALREADY_EXISTS
_CHAVE = b"UnePDF"  # evita que outro programa que use o mesmo canal seja confundido com o app
QUALQUER_PROCESSO = -1  # ASFW_ANY
# Nome fixo que o instalador procura para pedir que o app seja fechado antes de atualizar
TRINCO_EM_EXECUCAO = "UnePDF.Executando"


def _nome() -> str:
    # Um canal por usuário do Windows: em servidores de terminal, cada pessoa tem o seu app
    usuario = hashlib.sha1(getpass.getuser().encode("utf-8", "replace")).hexdigest()[:12]
    return f"UnePDF-{usuario}"


class InstanciaUnica:
    def __init__(self, nome: str | None = None):
        self.nome = nome or _nome()
        self.endereco = rf"\\.\pipe\{self.nome}"
        self._trinco = None
        self._ouvinte: Listener | None = None

    def tornar_principal(self) -> bool:
        """Verdadeiro se esta é a primeira cópia aberta pelo usuário."""
        try:
            kernel32 = ctypes.windll.kernel32
        except AttributeError:
            return True  # fora do Windows não há Explorer abrindo várias cópias
        kernel32.SetLastError(0)
        trinco = kernel32.CreateMutexW(None, False, f"Local\\{self.nome}")
        if not trinco:
            return True
        if kernel32.GetLastError() == ERRO_JA_EXISTE:
            kernel32.CloseHandle(trinco)
            return False
        self._trinco = trinco
        self._em_execucao = kernel32.CreateMutexW(None, False, TRINCO_EM_EXECUCAO)
        return True

    def enviar(self, mensagem: dict, tempo_limite: float = 5.0) -> bool:
        """Entrega a mensagem à cópia principal, esperando até ela estar pronta para receber."""
        try:
            # Deixa a principal trazer a janela para a frente (o Windows só permite com essa licença)
            ctypes.windll.user32.AllowSetForegroundWindow(QUALQUER_PROCESSO)
        except AttributeError:
            pass
        limite = time.monotonic() + tempo_limite
        while True:
            try:
                with Client(self.endereco, family="AF_PIPE", authkey=_CHAVE) as conexao:
                    conexao.send(mensagem)
                return True
            except (OSError, EOFError):
                # A principal acabou de abrir e ainda não começou a escutar
                if time.monotonic() > limite:
                    log.warning("A cópia principal do app não respondeu")
                    return False
                time.sleep(0.1)

    def escutar(self, ao_receber: Callable[[dict], None]) -> None:
        """Recebe as mensagens das outras cópias em segundo plano. `ao_receber` roda fora da thread principal."""
        try:
            self._ouvinte = Listener(self.endereco, family="AF_PIPE", authkey=_CHAVE)
        except OSError:
            log.warning("Não foi possível abrir o canal da instância única", exc_info=True)
            return

        def atender() -> None:
            while True:
                try:
                    with self._ouvinte.accept() as conexao:
                        mensagem = conexao.recv()
                except Exception:
                    # Conexão de outro programa, ou interrompida no meio: ignora e continua escutando
                    log.debug("Mensagem da instância única descartada", exc_info=True)
                    time.sleep(0.05)
                    continue
                if isinstance(mensagem, dict):
                    ao_receber(mensagem)

        threading.Thread(target=atender, name="instancia-unica", daemon=True).start()
