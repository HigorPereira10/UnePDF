import subprocess
from pathlib import Path

import pytest
from conftest import criar_pdf_com_texto
from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfReader, PdfWriter

from unepdf.core import ocr
from unepdf.core.converter import pdf_para_texto
from unepdf.core.erros import ErroUnePDF, OperacaoCancelada
from unepdf.core.progresso import Cancelamento
from unepdf.utils import programas

TEXTO_DIGITAL = "Nota fiscal de servico emitida digitalmente, com texto selecionavel completo."
requer_tesseract = pytest.mark.skipif(ocr.disponivel() is not None, reason="Tesseract com português não instalado")


def _instalar(pasta: Path, idiomas=("por", "eng")) -> Path:
    executavel = pasta / "Tesseract-OCR" / "tesseract.exe"
    (executavel.parent / "tessdata").mkdir(parents=True)
    executavel.write_bytes(b"")
    for idioma in idiomas:
        (executavel.parent / "tessdata" / f"{idioma}.traineddata").write_bytes(b"")
    return executavel


@pytest.fixture
def tesseract_falso(tmp_path, monkeypatch):
    """Tesseract "instalado" que reconhece sempre o mesmo texto e registra as chamadas."""
    executavel = _instalar(tmp_path / "programas")
    monkeypatch.setattr(ocr, "localizar_tesseract", lambda: executavel)
    chamadas = []

    def executar(argumentos, cancelamento):
        chamadas.append(argumentos)
        imagem, base, *_, saida = argumentos
        if saida == "pdf":
            criar_pdf_com_texto(Path(base + ".pdf"), ["TEXTO RECONHECIDO"])
        else:
            Path(base + ".txt").write_text("TEXTO RECONHECIDO", encoding="utf-8")

    monkeypatch.setattr(ocr, "_executar", executar)
    return chamadas


def _texto(caminho: Path) -> list[str]:
    return [pagina.extract_text() for pagina in PdfReader(caminho).pages]


def _escaneado(caminho: Path, paginas: int = 2) -> Path:
    """PDF só com páginas sem texto, como um escaneamento."""
    return criar_pdf_com_texto(caminho, [""] * paginas)


def test_disponibilidade(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr, "localizar_tesseract", lambda: None)
    assert "UB-Mannheim" in ocr.disponivel()

    sem_portugues = _instalar(tmp_path / "a", idiomas=("eng",))
    monkeypatch.setattr(ocr, "localizar_tesseract", lambda: sem_portugues)
    assert "sem o idioma português" in ocr.disponivel()

    completo = _instalar(tmp_path / "b")
    monkeypatch.setattr(ocr, "localizar_tesseract", lambda: completo)
    assert ocr.disponivel() is None
    assert ocr.idiomas(completo) == "por+eng"
    assert ocr.idiomas(_instalar(tmp_path / "c", idiomas=("por",))) == "por"


def test_localizar_tesseract_prefere_a_copia_do_app(tmp_path, monkeypatch):
    do_app = tmp_path / "app" / "tesseract" / "tesseract.exe"
    do_app.parent.mkdir(parents=True)
    do_app.write_bytes(b"")
    monkeypatch.setattr(programas, "pasta_do_app", lambda: tmp_path / "app")
    assert programas.localizar_tesseract() == do_app


def test_pdf_escaneado_fica_pesquisavel(tmp_path, tesseract_falso):
    origem = _escaneado(tmp_path / "contrato.pdf")
    preparo = ocr.preparar([origem])
    passos = []

    resultado = ocr.ocr_documentos(preparo, tmp_path / "UnePDF", progresso=lambda *a: passos.append(a))

    destino = tmp_path / "UnePDF" / "contrato - OCR.pdf"
    assert resultado.gerados == [destino]
    assert all("TEXTO RECONHECIDO" in texto for texto in _texto(destino))
    assert resultado.paginas_reconhecidas == 2
    assert [p[0] for p in passos] == [1, 2] and passos[0][2] == "contrato.pdf: página 1 de 2"
    assert tesseract_falso[0][2:] == ["-l", "por+eng", "--dpi", "300", "-c", "textonly_pdf=1", "pdf"]


def test_paginas_com_texto_ficam_como_estao(tmp_path, tesseract_falso):
    misto = criar_pdf_com_texto(tmp_path / "misto.pdf", [TEXTO_DIGITAL, ""])
    digital = criar_pdf_com_texto(tmp_path / "digital.pdf", [TEXTO_DIGITAL])

    resultado = ocr.ocr_documentos(ocr.preparar([misto, digital]), tmp_path / "UnePDF")

    textos = _texto(resultado.gerados[0])
    assert "TEXTO RECONHECIDO" not in textos[0] and "TEXTO RECONHECIDO" in textos[1]
    assert (resultado.paginas_reconhecidas, resultado.paginas_com_texto) == (1, 1)
    assert [(i.caminho.name, i.motivo) for i in resultado.ignorados] == [
        ("digital.pdf", "já tem texto em todas as páginas, não precisa de OCR"),
    ]
    assert len(tesseract_falso) == 1


def test_imagem_vira_pdf_pesquisavel(tmp_path, tesseract_falso):
    Image.new("RGB", (1240, 1754), "white").save(tmp_path / "scan.png", dpi=(150, 150))

    resultado = ocr.ocr_documentos(ocr.preparar([tmp_path / "scan.png"]), tmp_path / "UnePDF")

    destino = tmp_path / "UnePDF" / "scan - OCR.pdf"
    assert resultado.gerados == [destino]
    assert "TEXTO RECONHECIDO" in _texto(destino)[0]


def test_camada_acompanha_paginas_giradas_e_recortadas(tmp_path, tesseract_falso):
    escritor = PdfWriter()
    pagina = escritor.add_blank_page(595, 842)
    pagina.rotate(90)
    escritor.add_blank_page(842, 595).cropbox.lower_left = (100, 50)
    origem = tmp_path / "girado.pdf"
    escritor.write(origem)

    resultado = ocr.ocr_documentos(ocr.preparar([origem]), tmp_path / "UnePDF")

    leitor = PdfReader(resultado.gerados[0])
    assert all("TEXTO RECONHECIDO" in p.extract_text() for p in leitor.pages)
    # A página girada continua com a mesma aparência: deitada, 842 x 595
    assert sorted((float(leitor.pages[0].mediabox.width), float(leitor.pages[0].mediabox.height))) == [595, 842]


def test_juntar_e_problemas(tmp_path, tesseract_falso, monkeypatch):
    bom = _escaneado(tmp_path / "1.pdf", 1)
    (tmp_path / "vazio.pdf").write_bytes(b"")
    falha = _escaneado(tmp_path / "2.pdf", 1)
    executar = ocr._executar

    def executar_com_falha(argumentos, cancelamento):
        # Cada arquivo usa uma pasta temporária numerada; a do segundo arquivo é a "1"
        if Path(argumentos[0]).parent.name == "1":
            raise ErroUnePDF("o Tesseract não conseguiu ler a página")
        executar(argumentos, cancelamento)

    monkeypatch.setattr(ocr, "_executar", executar_com_falha)

    resultado = ocr.ocr_documentos(
        ocr.preparar([bom, tmp_path / "vazio.pdf", falha]), tmp_path / "UnePDF", juntar_em=tmp_path / "UnePDF" / "todos.pdf"
    )

    assert [p.name for p in resultado.gerados] == ["1 - OCR.pdf"]
    assert [(i.caminho.name, i.motivo) for i in resultado.ignorados] == [
        ("vazio.pdf", "arquivo vazio (0 KB)"),
        ("2.pdf", "o Tesseract não conseguiu ler a página"),
    ]
    assert [m.title for m in PdfReader(resultado.juntado).outline] == ["1"]


def test_cancelar_mantem_os_prontos(tmp_path, tesseract_falso):
    arquivos = [_escaneado(tmp_path / f"{n}.pdf", 1) for n in (1, 2, 3)]
    cancelamento = Cancelamento()

    def progresso(atual, total, descricao):
        if atual == 2:
            cancelamento.cancelar()

    resultado = ocr.ocr_documentos(ocr.preparar(arquivos), tmp_path / "UnePDF", progresso=progresso,
                                   cancelamento=cancelamento)

    assert [p.name for p in resultado.gerados] == ["1 - OCR.pdf"]
    assert resultado.pendentes == 2


def test_sem_tesseract_explica(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr, "localizar_tesseract", lambda: None)
    with pytest.raises(ErroUnePDF, match="precisa do Tesseract"):
        ocr.ocr_documentos(ocr.preparar([_escaneado(tmp_path / "a.pdf")]), tmp_path / "UnePDF")


def test_executar_sem_janela_e_cancelavel(tmp_path, monkeypatch):
    executavel = _instalar(tmp_path)
    monkeypatch.setattr(ocr, "localizar_tesseract", lambda: executavel)
    registro = {}

    class ProcessoFalso:
        returncode = None

        def __init__(self, comando, **opcoes):
            registro.update(opcoes, comando=comando)

        def communicate(self, timeout=None):
            if registro.get("morto"):
                return b"", b""
            raise subprocess.TimeoutExpired("tesseract", timeout)

        def kill(self):
            registro["morto"] = True

    monkeypatch.setattr(ocr.subprocess, "Popen", ProcessoFalso)
    cancelamento = Cancelamento()
    cancelamento.cancelar()

    with pytest.raises(OperacaoCancelada):
        ocr._executar(["a.png", "a", "pdf"], cancelamento)

    assert registro["morto"] and registro["creationflags"] == subprocess.CREATE_NO_WINDOW


def test_pdf_para_texto_com_ocr(tmp_path, tesseract_falso):
    origem = criar_pdf_com_texto(tmp_path / "misto.pdf", [TEXTO_DIGITAL, ""])

    resultado = pdf_para_texto(origem, tmp_path / "misto.txt", usar_ocr=True)

    texto = (tmp_path / "misto.txt").read_text(encoding="utf-8-sig")
    assert TEXTO_DIGITAL in texto and "TEXTO RECONHECIDO" in texto
    assert "1 página(s) lidas com OCR" in resultado.observacao


# Com o Tesseract de verdade (pulados onde ele não está instalado)

def _imagem_com_texto(caminho: Path, texto: str) -> Path:
    imagem = Image.new("L", (2480, 600), 255)
    fonte = ImageFont.truetype("arial.ttf", 90)
    ImageDraw.Draw(imagem).text((120, 220), texto, fill=0, font=fonte)
    imagem.save(caminho, dpi=(300, 300))
    return caminho


@requer_tesseract
def test_ocr_de_verdade_em_imagem_e_pdf(tmp_path):
    imagem = _imagem_com_texto(tmp_path / "recibo.png", "Recibo de pagamento numero 4521")

    resultado = ocr.ocr_documentos(ocr.preparar([imagem]), tmp_path / "UnePDF")

    texto = PdfReader(resultado.gerados[0]).pages[0].extract_text()
    assert "Recibo" in texto and "4521" in texto
    # A camada é invisível: o PDF continua do tamanho da imagem original, a 300 dpi
    assert round(float(PdfReader(resultado.gerados[0]).pages[0].mediabox.width)) == 595


@requer_tesseract
def test_pdf_para_texto_com_ocr_de_verdade(tmp_path):
    from unepdf.core.imagens import TamanhoPagina, imagens_para_pdf

    imagem = _imagem_com_texto(tmp_path / "carta.png", "Contrato de prestacao de servicos")
    pdf = imagens_para_pdf([imagem], tmp_path / "carta.pdf", TamanhoPagina.IMAGEM).destino

    pdf_para_texto(pdf, tmp_path / "carta.txt", usar_ocr=True)

    assert "Contrato" in (tmp_path / "carta.txt").read_text(encoding="utf-8-sig")
