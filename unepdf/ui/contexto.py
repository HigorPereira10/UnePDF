"""Estado compartilhado entre as telas: as configurações do usuário."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from unepdf.core import configuracoes
from unepdf.core.configuracoes import Configuracoes
from unepdf.core.erros import ErroUnePDF

log = logging.getLogger(__name__)


@dataclass
class ContextoApp:
    config: Configuracoes = field(default_factory=Configuracoes)

    def salvar_config(self) -> None:
        """Grava as configurações. Uma falha aqui não deve interromper o uso do app, só fica no log."""
        try:
            configuracoes.salvar(self.config)
        except ErroUnePDF as erro:
            log.warning("%s", erro)
