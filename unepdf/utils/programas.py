"""Localização de programas externos opcionais: Ghostscript, Tesseract, Office e LibreOffice.

Eles são programas separados, chamados pelo app: o UnePDF funciona sem eles e só as
ferramentas que dependem deles ficam desativadas, com a explicação do que falta.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path

NOMES_GHOSTSCRIPT = ("gswin64c.exe", "gswin32c.exe")


def pasta_do_app() -> Path:
    """Pasta onde o app está instalado (a do executável) ou a raiz do projeto, rodando pelo código-fonte."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parents[2]


def _versao(caminho: Path) -> tuple[int, ...]:
    """Números da versão no caminho (ex.: gs10.08.0 -> (10, 8, 0)), para preferir a mais nova."""
    encontrada = re.search(r"(\d+(?:\.\d+)+)", str(caminho))
    return tuple(int(n) for n in encontrada[1].split(".")) if encontrada else ()


def _do_registro() -> list[Path]:
    """Instalações registradas pelo instalador oficial do Ghostscript (versão mais nova primeiro)."""
    try:
        import winreg
    except ImportError:
        return []
    encontrados = []
    for raiz in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for empresa in ("GPL Ghostscript", "Artifex Ghostscript"):
            try:
                chave = winreg.OpenKey(raiz, rf"SOFTWARE\{empresa}")
            except OSError:
                continue
            with chave:
                for indice in range(winreg.QueryInfoKey(chave)[0]):
                    versao = winreg.EnumKey(chave, indice)
                    try:
                        with winreg.OpenKey(chave, versao) as subchave:
                            dll = Path(winreg.QueryValueEx(subchave, "GS_DLL")[0])
                    except OSError:
                        continue
                    encontrados += [dll.parent / nome for nome in NOMES_GHOSTSCRIPT]
    return sorted(encontrados, key=_versao, reverse=True)


def _das_pastas_padrao() -> list[Path]:
    encontrados = []
    for variavel in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
        base = os.environ.get(variavel)
        if base:
            for nome in NOMES_GHOSTSCRIPT:
                encontrados += Path(base, "gs").glob(f"gs*/bin/{nome}")
    return sorted(encontrados, key=_versao, reverse=True)


def candidatos_ghostscript() -> list[Path]:
    """Lugares onde procurar, em ordem de preferência.

    A cópia que vai junto com o app (instalador ou .zip portátil) vem primeiro, para todos os
    computadores do escritório usarem a mesma versão.
    """
    junto_do_app = [pasta_do_app() / "ghostscript" / "bin" / nome for nome in NOMES_GHOSTSCRIPT]
    no_path = [Path(c) for c in (shutil.which(n) for n in (*NOMES_GHOSTSCRIPT, "gs")) if c]
    return [*junto_do_app, *_do_registro(), *_das_pastas_padrao(), *no_path]


def localizar_ghostscript() -> Path | None:
    """Executável de linha de comando do Ghostscript, ou None se não estiver instalado."""
    return next((caminho for caminho in candidatos_ghostscript() if caminho.is_file()), None)


def office_instalado(prog_id: str) -> bool:
    """Indica se um aplicativo do Office (ex.: "Word.Application") está registrado para automação."""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, rf"{prog_id}\CLSID"):
            return True
    except (ImportError, OSError):
        return False


def _libreoffice_do_registro() -> list[Path]:
    try:
        import winreg
    except ImportError:
        return []
    encontrados = []
    for raiz in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for caminho in (r"SOFTWARE\LibreOffice\UNO\InstallPath", r"SOFTWARE\WOW6432Node\LibreOffice\UNO\InstallPath"):
            try:
                with winreg.OpenKey(raiz, caminho) as chave:
                    encontrados.append(Path(winreg.QueryValueEx(chave, "")[0]) / "soffice.com")
            except OSError:
                continue
    return encontrados


def localizar_libreoffice() -> Path | None:
    """Executável do LibreOffice para conversão sem janela, ou None se não estiver instalado."""
    pastas_padrao = [
        Path(base, "LibreOffice", "program", "soffice.com")
        for base in (os.environ.get(v) for v in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"))
        if base
    ]
    no_path = [Path(c) for c in (shutil.which(n) for n in ("soffice.com", "soffice")) if c]
    candidatos = [*_libreoffice_do_registro(), *pastas_padrao, *no_path]
    return next((caminho for caminho in candidatos if caminho.is_file()), None)


def impressora_pdf_do_windows() -> tuple[str, str] | None:
    """Nome e porta da impressora "Microsoft Print to PDF", que vem com o Windows 10 e 11."""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows NT\CurrentVersion\Devices") as chave:
            valor = winreg.QueryValueEx(chave, "Microsoft Print to PDF")[0]
    except (ImportError, OSError):
        return None
    porta = str(valor).split(",")[-1].strip()
    return ("Microsoft Print to PDF", porta) if porta else None


def candidatos_tesseract() -> list[Path]:
    """Lugares onde procurar o Tesseract, com a cópia que vai junto com o app primeiro."""
    candidatos = [pasta_do_app() / "tesseract" / "tesseract.exe"]
    try:
        import winreg

        for raiz in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(raiz, r"SOFTWARE\Tesseract-OCR") as chave:
                    candidatos.append(Path(winreg.QueryValueEx(chave, "InstallDir")[0]) / "tesseract.exe")
            except OSError:
                continue
    except ImportError:
        pass
    for variavel in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "LOCALAPPDATA"):
        base = os.environ.get(variavel)
        if base:
            subpasta = Path(base, "Programs") if variavel == "LOCALAPPDATA" else Path(base)
            candidatos.append(subpasta / "Tesseract-OCR" / "tesseract.exe")
    if no_path := shutil.which("tesseract"):
        candidatos.append(Path(no_path))
    return candidatos


def localizar_tesseract() -> Path | None:
    """Executável do Tesseract (OCR), ou None se não estiver instalado."""
    return next((caminho for caminho in candidatos_tesseract() if caminho.is_file()), None)
