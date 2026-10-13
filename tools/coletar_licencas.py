"""Copia os textos de licença das bibliotecas que vão dentro do executável.

Os textos vêm dos próprios pacotes instalados (pasta .dist-info), então sempre correspondem às
versões empacotadas. Também copia a licença do Python, que vai junto no executável, e os textos
da pasta licenses do repositório (LGPL e GPL, que o PySide6 não traz no pacote).

Uso (feito pelo scripts/build.bat): py tools/coletar_licencas.py <pasta de destino>
"""
from __future__ import annotations

import re
import shutil
import sys
from importlib import metadata
from pathlib import Path

from packaging.requirements import Requirement

RAIZ = Path(__file__).resolve().parent.parent
_ARQUIVO_DE_LICENCA = re.compile(r"(LICEN[CS]E|COPYING|NOTICE)", re.IGNORECASE)

# O pacote do PySide6 traz só o texto da licença comercial do Qt, que não é a usada aqui.
# A LGPL, que é a usada, fica na pasta licenses do repositório.
_IGNORADOS = re.compile(r"LicenseRef-Qt-Commercial", re.IGNORECASE)
_COBERTOS_PELO_REPOSITORIO = {"pyside6-essentials", "shiboken6"}


def _normalizar(nome: str) -> str:
    return re.sub(r"[-_.]+", "-", nome).lower()


def dependencias_de_execucao() -> list[metadata.Distribution]:
    """Pacotes do requirements.txt e tudo de que eles dependem, como o pip instalaria."""
    linhas = (RAIZ / "requirements.txt").read_text(encoding="utf-8").splitlines()
    pendentes = [Requirement(linha) for linha in linhas if linha.strip() and not linha.lstrip().startswith("#")]
    vistos: set[str] = set()
    distribuicoes = []
    while pendentes:
        requisito = pendentes.pop()
        nome = _normalizar(requisito.name)
        if nome in vistos:
            continue
        vistos.add(nome)
        distribuicao = metadata.distribution(requisito.name)
        distribuicoes.append(distribuicao)
        extras = requisito.extras or {""}
        for texto in distribuicao.requires or []:
            dependencia = Requirement(texto)
            if dependencia.marker and not any(dependencia.marker.evaluate({"extra": e}) for e in extras):
                continue
            pendentes.append(dependencia)
    return distribuicoes


def coletar(destino: Path) -> list[str]:
    """Copia as licenças para `destino` e devolve os pacotes que ficaram sem nenhum texto."""
    destino.mkdir(parents=True, exist_ok=True)
    for texto in (RAIZ / "licenses").glob("*.txt"):
        shutil.copy2(texto, destino / texto.name)
    shutil.copy2(Path(sys.base_prefix) / "LICENSE.txt", _pasta(destino, "Python") / "LICENSE.txt")

    sem_licenca = []
    for distribuicao in dependencias_de_execucao():
        nome = distribuicao.metadata["Name"]
        copiados = 0
        for arquivo in distribuicao.files or []:
            partes = Path(arquivo).parts
            if not partes[0].endswith(".dist-info") or _IGNORADOS.search(str(arquivo)):
                continue
            if not _ARQUIVO_DE_LICENCA.search(str(arquivo)):
                continue
            relativo = Path(*partes[1:])
            if relativo.parts[0] == "licenses" and len(relativo.parts) > 1:
                relativo = Path(*relativo.parts[1:])
            alvo = destino / nome / relativo
            alvo.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(arquivo.locate(), alvo)
            copiados += 1
        if not copiados and _normalizar(nome) not in _COBERTOS_PELO_REPOSITORIO:
            sem_licenca.append(nome)
    return sem_licenca


def _pasta(destino: Path, nome: str) -> Path:
    pasta = destino / nome
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) != 2:
        print("Uso: py tools/coletar_licencas.py <pasta de destino>")
        return 2
    sem_licenca = coletar(Path(sys.argv[1]))
    if sem_licenca:
        # Sem o texto, não dá para distribuir o executável cumprindo a licença do pacote
        print("Pacotes sem texto de licença encontrado:", ", ".join(sem_licenca))
        return 1
    print("Licenças copiadas para", sys.argv[1])
    return 0


if __name__ == "__main__":
    sys.exit(main())
