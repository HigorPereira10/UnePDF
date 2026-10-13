"""Coleta de lixo do Python só na thread da interface.

Objetos do Qt presos em ciclos de referência são destruídos pela coleta de lixo do Python, que
roda na thread que estiver alocando memória no momento. Se for uma thread de segundo plano
(ex.: a que une os PDFs), o objeto do Qt é destruído fora da thread da interface e o app fecha
sozinho com "access violation". Por isso a coleta automática fica desligada e é feita aqui,
periodicamente, sempre na thread da interface.
"""
from __future__ import annotations

import gc

from PySide6.QtCore import QObject, QTimer


class ColetorNaThreadPrincipal(QObject):
    def __init__(self, pai: QObject | None = None, intervalo_ms: int = 500):
        super().__init__(pai)
        self._limites = gc.get_threshold()
        gc.disable()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.verificar)
        self._timer.start(intervalo_ms)

    def verificar(self) -> None:
        """Faz a mesma coleta por gerações que o Python faria sozinho, na thread certa."""
        contagem = gc.get_count()
        if contagem[0] > self._limites[0]:
            geracao = 0
            if contagem[1] > self._limites[1]:
                geracao = 2 if contagem[2] > self._limites[2] else 1
            gc.collect(geracao)

    def encerrar(self) -> None:
        self._timer.stop()
        gc.enable()
