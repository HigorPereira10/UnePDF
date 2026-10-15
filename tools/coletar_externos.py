"""Copia do computador só a parte do Ghostscript e do Tesseract que o UnePDF usa, para ir no instalador.

Os dois são programas separados: vão em pastas próprias (ghostscript e tesseract, ao lado do
executável), cada uma com a licença do programa. O UnePDF os encontra ali antes de procurar no Windows.

Uso (feito pelo scripts/distribuir.bat): py tools/coletar_externos.py <pasta de destino>
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from unepdf.utils.programas import localizar_ghostscript, localizar_tesseract  # noqa: E402

LEIA_ME_GHOSTSCRIPT = """Ghostscript, distribuído junto com o UnePDF sem modificações.
Licença: GNU Affero General Public License, versão 3 (arquivo LICENSE.txt).
Código-fonte: https://ghostscript.com/releases/gsdnld.html
O UnePDF apenas executa este programa; ele não faz parte do código do UnePDF.
"""
LEIA_ME_TESSERACT = """Tesseract OCR, distribuído junto com o UnePDF sem modificações, com os idiomas português e inglês.
Licença: Apache License 2.0 (arquivo LICENSE.txt). Dados de idioma: projeto tessdata, Apache License 2.0.
Código-fonte: https://github.com/tesseract-ocr/tesseract
O UnePDF apenas executa este programa; ele não faz parte do código do UnePDF.
"""


def _copiar(origem: Path, destino: Path) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(origem, destino)


def coletar_ghostscript(destino: Path) -> Path:
    executavel = localizar_ghostscript()
    if executavel is None:
        raise SystemExit("Ghostscript não encontrado neste computador.")
    raiz = executavel.parent.parent
    for nome in ("gswin64c.exe", "gsdll64.dll"):
        _copiar(raiz / "bin" / nome, destino / "bin" / nome)
    # Perfis de cores usados na conversão para PDF/A
    for perfil in (raiz / "iccprofiles").glob("*.icc"):
        _copiar(perfil, destino / "iccprofiles" / perfil.name)
    _copiar(raiz / "doc" / "COPYING", destino / "LICENSE.txt")
    (destino / "LEIA-ME.txt").write_text(LEIA_ME_GHOSTSCRIPT, encoding="utf-8-sig")
    return raiz


def dependencias(executavel: Path) -> list[Path]:
    """Bibliotecas da mesma pasta de que o programa precisa, direta ou indiretamente."""
    import pefile

    pasta = executavel.parent
    locais = {p.name.lower(): p for p in pasta.glob("*.dll")}
    pendentes, encontradas = [executavel], {}
    tabelas = [pefile.DIRECTORY_ENTRY[n] for n in ("IMAGE_DIRECTORY_ENTRY_IMPORT", "IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT")]
    while pendentes:
        arquivo = pefile.PE(str(pendentes.pop()), fast_load=True)
        arquivo.parse_data_directories(directories=tabelas)
        for entrada in [*getattr(arquivo, "DIRECTORY_ENTRY_IMPORT", []), *getattr(arquivo, "DIRECTORY_ENTRY_DELAY_IMPORT", [])]:
            nome = entrada.dll.decode().lower()
            if nome in locais and nome not in encontradas:
                encontradas[nome] = locais[nome]
                pendentes.append(locais[nome])
        arquivo.close()
    return sorted(encontradas.values())


def coletar_tesseract(destino: Path) -> Path:
    executavel = localizar_tesseract()
    if executavel is None:
        raise SystemExit("Tesseract não encontrado neste computador.")
    raiz = executavel.parent
    _copiar(executavel, destino / "tesseract.exe")
    # Só as bibliotecas de que o tesseract.exe depende; as dos programas de treinamento ficam de fora
    for biblioteca in dependencias(executavel):
        _copiar(biblioteca, destino / biblioteca.name)
    for idioma in ("por", "eng"):
        origem = raiz / "tessdata" / f"{idioma}.traineddata"
        if not origem.is_file():
            raise SystemExit(f"Falta o idioma {idioma} no Tesseract ({origem}).")
        _copiar(origem, destino / "tessdata" / origem.name)
    # Fonte da camada de texto invisível e as configurações das saídas usadas (PDF e texto)
    _copiar(raiz / "tessdata" / "pdf.ttf", destino / "tessdata" / "pdf.ttf")
    for configuracao in ("pdf", "txt"):
        _copiar(raiz / "tessdata" / "configs" / configuracao, destino / "tessdata" / "configs" / configuracao)
    _copiar(raiz / "doc" / "LICENSE", destino / "LICENSE.txt")
    (destino / "LEIA-ME.txt").write_text(LEIA_ME_TESSERACT, encoding="utf-8-sig")
    return raiz


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    destino = Path(sys.argv[1])
    for pasta in ("ghostscript", "tesseract"):
        if (destino / pasta).exists():
            shutil.rmtree(destino / pasta)
    origem_gs = coletar_ghostscript(destino / "ghostscript")
    origem_tess = coletar_tesseract(destino / "tesseract")
    print(f"Ghostscript copiado de {origem_gs}")
    print(f"Tesseract copiado de {origem_tess}")


if __name__ == "__main__":
    main()
