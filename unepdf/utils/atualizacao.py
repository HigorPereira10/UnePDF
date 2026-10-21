"""Nova versão: consulta na página de versões (Releases) do projeto no GitHub e atualização pelo app.

A consulta só pergunta qual é a versão mais recente: nenhum arquivo do usuário é enviado. Sem
internet, ou com qualquer problema na consulta, fica em silêncio.

Para atualizar, o app baixa o instalador publicado, confere o SHA-256 informado pelo GitHub e, depois
de fechar, roda o instalador em modo silencioso, que abre o app de novo no fim. A instalação é por
usuário, então não pede administrador. Só funciona na versão instalada (a portátil não tem instalador).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from unepdf.constantes import REPOSITORIO_GITHUB
from unepdf.core.erros import ErroUnePDF
from unepdf.core.progresso import CallbackProgresso, Cancelamento

log = logging.getLogger(__name__)

URL_ULTIMA_VERSAO = f"https://api.github.com/repos/{REPOSITORIO_GITHUB}/releases/latest"
# Só baixa arquivos publicados neste repositório
PREFIXO_DOWNLOAD = f"https://github.com/{REPOSITORIO_GITHUB}/releases/download/"
BLOCO = 256 * 1024
DESINSTALADOR = "unins000.exe"  # criado pelo Inno Setup na pasta do app instalado
SEM_JANELA = 0x08000000  # CREATE_NO_WINDOW


@dataclass(frozen=True)
class Instalador:
    nome: str
    url: str
    tamanho: int
    sha256: str


@dataclass(frozen=True)
class NovaVersao:
    versao: str
    pagina: str  # página da versão, com os arquivos para baixar
    instalador: Instalador | None = None  # None quando a versão não tem um instalador que dê para conferir


def numero(versao: str) -> tuple[int, ...]:
    """Ex.: "v2.1.0" -> (2, 1, 0). Partes que não são números (ex.: "-beta") ficam de fora."""
    return tuple(int(parte) for parte in re.findall(r"\d+", versao.split("-")[0])[:3])


def _instalador(dados: dict, versao: str) -> Instalador | None:
    nome_esperado = f"UnePDF-{versao}-instalador.exe".casefold()
    for arquivo in dados.get("assets") or []:
        nome, url = str(arquivo.get("name", "")), str(arquivo.get("browser_download_url", ""))
        resumo = str(arquivo.get("digest") or "")
        if nome.casefold() != nome_esperado or not url.startswith(PREFIXO_DOWNLOAD):
            continue
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", resumo):
            log.info("Instalador %s sem SHA-256 informado: a atualização pelo app fica desligada", nome)
            return None
        return Instalador(nome, url, int(arquivo.get("size") or 0), resumo.removeprefix("sha256:"))
    return None


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
        versao = publicada.lstrip("vV")
        return NovaVersao(versao, pagina, _instalador(dados, versao))
    return None


def pode_atualizar_pelo_app() -> bool:
    """Verdadeiro na versão instalada. A portátil e quem roda pelo código-fonte atualizam pela página."""
    return getattr(sys, "frozen", False) and (Path(sys.executable).parent / DESINSTALADOR).exists()


def baixar(
    instalador: Instalador,
    pasta: Path,
    progresso: CallbackProgresso | None = None,
    cancelamento: Cancelamento | None = None,
    tempo_limite: float = 30.0,
) -> Path:
    """Baixa o instalador para a pasta e confere tamanho e SHA-256. Nada fica para trás se der errado."""
    pasta.mkdir(parents=True, exist_ok=True)
    for antigo in pasta.glob("*.exe*"):
        antigo.unlink(missing_ok=True)  # sobras de uma atualização anterior
    destino = pasta / instalador.nome
    parcial = destino.with_name(destino.name + ".parcial")
    resumo = hashlib.sha256()
    baixados = 0
    pedido = urllib.request.Request(instalador.url, headers={"User-Agent": "UnePDF"})
    try:
        with urllib.request.urlopen(pedido, timeout=tempo_limite) as resposta, open(parcial, "wb") as arquivo:
            while bloco := resposta.read(BLOCO):
                if cancelamento:
                    cancelamento.verificar()
                arquivo.write(bloco)
                resumo.update(bloco)
                baixados += len(bloco)
                if progresso:
                    progresso(baixados, instalador.tamanho, f"{baixados / 1024**2:.0f} de {instalador.tamanho / 1024**2:.0f} MB")
    except ErroUnePDF:
        parcial.unlink(missing_ok=True)
        raise
    except Exception as erro:
        parcial.unlink(missing_ok=True)
        raise ErroUnePDF(
            "Não foi possível baixar a versão nova.\n\n"
            "Confira a internet e tente de novo, ou baixe pela página de download."
        ) from erro
    if baixados != instalador.tamanho or resumo.hexdigest() != instalador.sha256:
        parcial.unlink(missing_ok=True)
        raise ErroUnePDF(
            "O arquivo baixado não confere com o publicado e foi descartado.\n\n"
            "Tente de novo mais tarde, ou baixe pela página de download."
        )
    os.replace(parcial, destino)
    log.info("Instalador da versão nova baixado e conferido: %s", destino)
    return destino


def comando_de_instalacao(instalador: Path, pid: int, registro: Path) -> list[str]:
    """Espera o app fechar e roda o instalador em silêncio; ele abre o app de novo no fim (/abrir=1)."""
    def texto(valor: object) -> str:
        return "'" + str(valor).replace("'", "''") + "'"

    argumentos = ", ".join(texto(a) for a in (
        "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/abrir=1", f'/LOG="{registro}"',
    ))
    script = (
        f"$app = Get-Process -Id {pid} -ErrorAction SilentlyContinue; "
        "if ($app) { $app.WaitForExit(120000) | Out-Null }; "
        f"Start-Process -FilePath {texto(instalador)} -ArgumentList {argumentos}"
    )
    return ["powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", script]


def instalar_depois_de_fechar(instalador: Path, registro: Path) -> None:
    """Deixa a instalação agendada. O app precisa fechar em seguida (o instalador recusa com ele aberto)."""
    comando = comando_de_instalacao(instalador, os.getpid(), registro)
    subprocess.Popen(comando, creationflags=SEM_JANELA, close_fds=True)
    log.info("Atualização agendada: o instalador roda quando o app fechar")
