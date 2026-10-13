"""Confere se os ícones gerados por tools/gerar_icones.py estão no repositório e íntegros."""
import struct
from pathlib import Path

ASSETS = Path(__file__).resolve().parents[1] / "assets"
ASSINATURA_PNG = b"\x89PNG\r\n\x1a\n"


def test_ico_tem_todos_os_tamanhos_em_png():
    dados = (ASSETS / "icone.ico").read_bytes()
    reservado, tipo, quantidade = struct.unpack_from("<HHH", dados)
    assert (reservado, tipo) == (0, 1)

    tamanhos = []
    for i in range(quantidade):
        lado, _, _, _, _, _, tamanho, deslocamento = struct.unpack_from("<BBBBHHII", dados, 6 + 16 * i)
        tamanhos.append(lado or 256)
        assert dados[deslocamento : deslocamento + 8] == ASSINATURA_PNG
        assert deslocamento + tamanho <= len(dados)

    assert tamanhos == [16, 20, 24, 32, 40, 48, 64, 128, 256]


def test_logo_png_existe():
    assert (ASSETS / "logo.png").read_bytes().startswith(ASSINATURA_PNG)
