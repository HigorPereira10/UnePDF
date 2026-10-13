"""Gera o PNG e o ICO do app a partir das logos em SVG de assets/.

Arquivos gerados:
    logo.png    512 px, usado no README e onde o SVG não pode ser usado
    icone.ico   ícone do executável, do instalador e das janelas

Nos tamanhos pequenos (até 40 px) o ICO usa logo_pequena.svg, sem as letras "PDF",
que nesses tamanhos virariam um borrão. Cada tamanho é desenhado direto do SVG,
e não reduzido de uma imagem grande, para ficar nítido.

Uso: py tools/gerar_icones.py
"""
import os
import struct
import sys
from pathlib import Path

# Não precisa de janela nem de fontes: as logos são só formas
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage, QPainter  # noqa: E402
from PySide6.QtSvg import QSvgRenderer  # noqa: E402

ASSETS = Path(__file__).resolve().parent.parent / "assets"
TAMANHOS_ICO = (16, 20, 24, 32, 40, 48, 64, 128, 256)
LIMITE_LOGO_PEQUENA = 40


def renderizar_png(svg: Path, tamanho: int) -> bytes:
    """Desenha o SVG em um quadrado de `tamanho` px e devolve os bytes do PNG."""
    renderizador = QSvgRenderer(str(svg))
    if not renderizador.isValid():
        raise ValueError(f"SVG inválido: {svg}")

    imagem = QImage(tamanho, tamanho, QImage.Format.Format_ARGB32)
    imagem.fill(Qt.GlobalColor.transparent)
    pintor = QPainter(imagem)
    pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderizador.render(pintor, QRectF(0, 0, tamanho, tamanho))
    pintor.end()

    dados = QByteArray()
    buffer = QBuffer(dados)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    imagem.save(buffer, "PNG")
    return bytes(dados)


def montar_ico(imagens: dict[int, bytes]) -> bytes:
    """Monta um .ico com uma imagem PNG por tamanho (formato aceito desde o Windows Vista)."""
    cabecalho = struct.pack("<HHH", 0, 1, len(imagens))
    entradas = b""
    conteudo = b""
    deslocamento = 6 + 16 * len(imagens)
    for tamanho, png in sorted(imagens.items()):
        lado = 0 if tamanho >= 256 else tamanho  # no formato ICO, 0 significa 256
        entradas += struct.pack("<BBBBHHII", lado, lado, 0, 0, 1, 32, len(png), deslocamento + len(conteudo))
        conteudo += png
    return cabecalho + entradas + conteudo


def main() -> None:
    app = QGuiApplication(sys.argv)  # noqa: F841 (o Qt exige a aplicação para desenhar)
    logo, logo_pequena = ASSETS / "logo.svg", ASSETS / "logo_pequena.svg"

    (ASSETS / "logo.png").write_bytes(renderizar_png(logo, 512))
    imagens = {
        tamanho: renderizar_png(logo_pequena if tamanho <= LIMITE_LOGO_PEQUENA else logo, tamanho)
        for tamanho in TAMANHOS_ICO
    }
    (ASSETS / "icone.ico").write_bytes(montar_ico(imagens))
    print("Ícones gerados em", ASSETS)


if __name__ == "__main__":
    main()
