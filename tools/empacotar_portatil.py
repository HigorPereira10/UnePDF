"""Monta o .zip portátil: o programa com o Ghostscript e o Tesseract, pronto para usar sem instalar.

Uso (feito pelo scripts/distribuir.bat): py tools/empacotar_portatil.py
Lê dist/UnePDF e dist/externos e grava dist/UnePDF-<versão>-portatil.zip.
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from unepdf import __version__  # noqa: E402

LEIA_ME = """UnePDF {versao}, versão portátil

Para usar, extraia esta pasta para onde quiser (por exemplo, Documentos) e abra o UnePDF.exe.
Não precisa instalar. As configurações ficam em %APPDATA%\\UnePDF, como na versão instalada.

Para o item "Unir com UnePDF" aparecer no botão direito do Explorer, ligue a opção em
Configurações > Windows. Se mudar a pasta de lugar depois, desligue e ligue de novo.
"""


def main() -> None:
    programa = RAIZ / "dist" / "UnePDF"
    externos = RAIZ / "dist" / "externos"
    if not (programa / "UnePDF.exe").is_file():
        raise SystemExit("Gere o executável antes (scripts\\build.bat).")
    destino = RAIZ / "dist" / f"UnePDF-{__version__}-portatil.zip"
    destino.unlink(missing_ok=True)
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as pacote:
        for origem, prefixo in ((programa, "UnePDF"), (externos, "UnePDF")):
            for arquivo in sorted(origem.rglob("*")):
                if arquivo.is_file():
                    pacote.write(arquivo, f"{prefixo}/{arquivo.relative_to(origem).as_posix()}")
        pacote.writestr("UnePDF/LEIA-ME.txt", LEIA_ME.format(versao=__version__).encode("utf-8-sig"))
    print(f"Pronto: {destino} ({destino.stat().st_size / 1024 / 1024:.0f} MB)")


if __name__ == "__main__":
    main()
