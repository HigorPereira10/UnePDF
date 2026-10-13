"""Execução de tarefas demoradas sem travar a interface.

O Qt só pode ser atualizado pela thread principal. Por isso a tarefa roda em uma QThread
e conversa com a tela por sinais, que o Qt entrega na thread principal.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable

from PySide6.QtCore import QObject, QThread, Signal, Slot

from unepdf.core.erros import ErroUnePDF
from unepdf.core.progresso import CallbackProgresso, Cancelamento

log = logging.getLogger(__name__)

# A tarefa recebe o callback de progresso e o sinal de cancelamento, e devolve o resultado final
Tarefa = Callable[[CallbackProgresso, Cancelamento], Any]


class _Trabalhador(QThread):
    progresso = Signal(int, int, str)
    concluido = Signal(object)
    falhou = Signal(object)

    def __init__(self, tarefa: Tarefa, cancelamento: Cancelamento, intervalo: float):
        super().__init__()
        self._tarefa = tarefa
        self._cancelamento = cancelamento
        self._intervalo = intervalo
        self._ultimo_envio = 0.0

    def _relatar(self, atual: int, total: int, descricao: str) -> None:
        # Com centenas de arquivos pequenos, redesenhar a cada um só deixaria a tela mais lenta
        agora = time.monotonic()
        if atual >= total or agora - self._ultimo_envio >= self._intervalo:
            self._ultimo_envio = agora
            self.progresso.emit(atual, total, descricao)

    def run(self) -> None:
        try:
            self.concluido.emit(self._tarefa(self._relatar, self._cancelamento))
        except BaseException as erro:  # qualquer falha precisa chegar à interface
            if not isinstance(erro, ErroUnePDF):
                log.error("Falha inesperada na tarefa em segundo plano", exc_info=erro)
            self.falhou.emit(erro)


class Executor(QObject):
    """Roda uma tarefa por vez em segundo plano. Os sinais chegam sempre na thread da interface."""

    progresso = Signal(int, int, str)
    concluido = Signal(object)
    falhou = Signal(object)

    def __init__(self, pai: QObject | None = None, intervalo: float = 0.05):
        super().__init__(pai)
        self._intervalo = intervalo
        self._trabalhador: _Trabalhador | None = None
        self._cancelamento: Cancelamento | None = None
        # Guarda as threads até terminarem de verdade: destruir uma QThread ainda ativa derruba o app
        self._threads_ativas: set[_Trabalhador] = set()

    @property
    def em_execucao(self) -> bool:
        return self._trabalhador is not None

    def executar(self, tarefa: Tarefa) -> None:
        if self.em_execucao:
            raise RuntimeError("Já existe uma tarefa em execução.")
        self._cancelamento = Cancelamento()
        trabalhador = _Trabalhador(tarefa, self._cancelamento, self._intervalo)
        trabalhador.progresso.connect(self.progresso)
        # Ligados a métodos deste objeto, os sinais são entregues na thread da interface
        trabalhador.concluido.connect(self._ao_concluir)
        trabalhador.falhou.connect(self._ao_falhar)
        trabalhador.finished.connect(self._ao_terminar_thread)
        self._threads_ativas.add(trabalhador)
        self._trabalhador = trabalhador
        trabalhador.start()

    def cancelar(self) -> None:
        """Pede o cancelamento. A tarefa para no próximo ponto de verificação e emite `falhou`."""
        if self._cancelamento:
            self._cancelamento.cancelar()

    def aguardar(self, milissegundos: int = 10_000) -> bool:
        """Espera as tarefas terminarem (usado ao fechar a janela). Retorna False se esgotar o tempo."""
        return all(thread.wait(milissegundos) for thread in list(self._threads_ativas))

    @Slot()
    def _ao_terminar_thread(self) -> None:
        thread = self.sender()
        thread.wait()
        self._threads_ativas.discard(thread)
        thread.deleteLater()

    # Liberam o executor antes de avisar a tela, para ela poder iniciar outra tarefa na resposta
    @Slot(object)
    def _ao_concluir(self, resultado: object) -> None:
        self._trabalhador = self._cancelamento = None
        self.concluido.emit(resultado)

    @Slot(object)
    def _ao_falhar(self, erro: object) -> None:
        self._trabalhador = self._cancelamento = None
        self.falhou.emit(erro)
