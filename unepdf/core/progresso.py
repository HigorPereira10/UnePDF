"""Acompanhamento e cancelamento de operações demoradas, sem depender da interface."""
from __future__ import annotations

import threading
from typing import Callable

from unepdf.core.erros import OperacaoCancelada

# Assinatura do callback de progresso: (passo atual, total de passos, descrição do passo)
CallbackProgresso = Callable[[int, int, str], None]


class Cancelamento:
    """Sinal de cancelamento compartilhado entre a interface e a operação em segundo plano.

    A interface chama `cancelar()`; a operação chama `verificar()` entre um arquivo e outro.
    """

    def __init__(self) -> None:
        self._evento = threading.Event()

    def cancelar(self) -> None:
        self._evento.set()

    @property
    def cancelado(self) -> bool:
        return self._evento.is_set()

    def verificar(self) -> None:
        """Lança OperacaoCancelada se o cancelamento foi pedido."""
        if self.cancelado:
            raise OperacaoCancelada()
