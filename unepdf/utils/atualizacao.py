"""Verificação de nova versão na página de versões (Releases) do projeto no GitHub.

Só consulta qual é a versão mais recente: nenhum arquivo do usuário é enviado. Sem internet, ou com
qualquer problema na consulta, fica em silêncio.
"""
from __future__ import annotations

import json
import logging
import re
import urllib.request
from dataclasses import dataclass

from unepdf.constantes import REPOSITORIO_GITHUB

log = logging.getLogger(__name__)

URL_ULTIMA_VERSAO = f"https://api.github.com/repos/{REPOSITORIO_GITHUB}/releases/latest"


@dataclass(frozen=True)
class NovaVersao:
    versao: str
    pagina: str  # página da versão, com os arquivos para baixar


def numero(versao: str) -> tuple[int, ...]:
    """Ex.: "v2.1.0" -> (2, 1, 0). Partes que não são números (ex.: "-beta") ficam de fora."""
    return tuple(int(parte) for parte in re.findall(r"\d+", versao.split("-")[0])[:3])


def procurar(versao_atual: str, tempo_limite: float = 5.0) -> NovaVersao | None:
    """A versão publicada mais recente, se for mais nova que a atual."""
    pedido = urllib.request.Request(
        URL_ULTIMA_VERSAO,
        headers={"Accept": "application/vnd.github+json", "User-Agent": f"UnePDF/{versao_atual}"},
    )
    try:
        with urllib.request.urlopen(pedido, timeout=tempo_limite) as resposta:
            dados = json.load(resposta)
        publicada = str(dados["tag_name"])
        pagina = str(dados.get("html_url") or f"https://github.com/{REPOSITORIO_GITHUB}/releases/latest")
    except Exception as erro:
        log.info("Verificação de nova versão não concluída: %s", erro)
        return None
    if dados.get("draft") or dados.get("prerelease"):
        return None
    if numero(publicada) > numero(versao_atual):
        return NovaVersao(publicada.lstrip("vV"), pagina)
    return None
