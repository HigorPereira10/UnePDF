import subprocess

import pytest
from conftest import criar_pdf_com_texto
from PIL import Image
from pypdf import PdfReader

from unepdf.core import ghostscript, pdfa
from unepdf.core.comprimir import NivelCompressao, comprimir
from unepdf.core.erros import ErroUnePDF, OperacaoCancelada
from unepdf.core.imagens import imagens_para_pdf
from unepdf.core.progresso import Cancelamento
from unepdf.utils.programas import localizar_ghostscript

requer_ghostscript = pytest.mark.skipif(localizar_ghostscript() is None, reason="Ghostscript não instalado")


@pytest.fixture
def sem_ghostscript(monkeypatch):
    monkeypatch.setattr(ghostscript, "localizar_ghostscript", lambda: None)


def test_sem_ghostscript_explica_o_que_falta(tmp_path, criar_pdf, sem_ghostscript):
    assert "ghostscript.com" in ghostscript.disponivel()
    with pytest.raises(ErroUnePDF, match="precisa do Ghostscript"):
        pdfa.converter(criar_pdf(tmp_path / "a.pdf"), tmp_path / "b.pdf")
    with pytest.raises(ErroUnePDF, match="precisa do Ghostscript"):
        comprimir(criar_pdf(tmp_path / "c.pdf"), tmp_path / "d.pdf", NivelCompressao.FORTE)
    assert not (tmp_path / "b.pdf").exists()


def test_roda_sem_abrir_janela_de_console(monkeypatch, tmp_path):
    chamadas = {}

    class ProcessoFalso:
        stdout = iter(["Page 1\n"])
        returncode = 0

        def __init__(self, comando, **opcoes):
            chamadas.update(opcoes, comando=comando)

        def wait(self):
            return 0

    monkeypatch.setattr(ghostscript, "localizar_ghostscript", lambda: tmp_path / "gswin64c.exe")
    monkeypatch.setattr(ghostscript.subprocess, "Popen", ProcessoFalso)

    ghostscript.executar(["-sDEVICE=pdfwrite"])

    assert chamadas["creationflags"] == subprocess.CREATE_NO_WINDOW
    assert "-dSAFER" in chamadas["comando"]


def test_definicao_pdfa_protege_caracteres_especiais(tmp_path):
    texto = pdfa._definicao_pdfa(tmp_path / "pasta (1)" / "sRGB.icc")
    assert "pasta \\(1\\)" in texto
    assert "/OutputIntents" in texto


def test_pdf_comum_nao_passa_na_conferencia_de_pdfa(tmp_path, criar_pdf):
    assert not pdfa.conferir_pdfa(criar_pdf(tmp_path / "a.pdf"), 2)


@requer_ghostscript
@pytest.mark.parametrize("formato", [pdfa.FormatoSaida.PDFA_1B, pdfa.FormatoSaida.PDFA_2B, pdfa.FormatoSaida.PDFA_3B])
def test_converte_para_pdfa_de_verdade(tmp_path, formato):
    # Caminho com acentos e espaços, como os de muitos usuários
    origem = criar_pdf_com_texto(tmp_path / "Relatórios ção" / "contrato.pdf", ["Cláusula 1", "Cláusula 2"])
    passos = []

    resultado = pdfa.converter(origem, tmp_path / "saída.pdf", formato, lambda *a: passos.append(a[0]))

    assert pdfa.conferir_pdfa(resultado.destino, formato.parte_pdfa)
    assert resultado.paginas == 2 and passos == [1, 2]
    esperado = "%PDF-1.4" if formato is pdfa.FormatoSaida.PDFA_1B else "%PDF-1.7"
    assert PdfReader(resultado.destino).pdf_header == esperado


@requer_ghostscript
def test_converte_para_pdf_14(tmp_path, criar_pdf):
    resultado = pdfa.converter(criar_pdf(tmp_path / "a.pdf"), tmp_path / "b.pdf", "PDF 1.4")
    assert PdfReader(resultado.destino).pdf_header == "%PDF-1.4"


@requer_ghostscript
def test_resultado_que_nao_passa_na_conferencia_e_descartado(tmp_path, criar_pdf, monkeypatch):
    monkeypatch.setattr(pdfa, "conferir_pdfa", lambda caminho, parte: False)
    with pytest.raises(ErroUnePDF, match="nada foi gravado"):
        pdfa.converter(criar_pdf(tmp_path / "a.pdf"), tmp_path / "b.pdf")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.pdf"]


@requer_ghostscript
def test_cancelamento_interrompe_o_ghostscript(tmp_path, criar_pdf):
    origem = criar_pdf(tmp_path / "a.pdf", paginas=400)
    cancelamento = Cancelamento()

    def progresso(atual, total, descricao):
        if atual >= 2:
            cancelamento.cancelar()

    with pytest.raises(OperacaoCancelada):
        pdfa.converter(origem, tmp_path / "b.pdf", pdfa.FormatoSaida.PDFA_2B, progresso, cancelamento)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.pdf"]


@requer_ghostscript
def test_erro_do_ghostscript_vira_mensagem(tmp_path):
    entrada = tmp_path / "x.ps"
    entrada.write_text("isto nao e postscript valido {{{")
    with pytest.raises(ErroUnePDF, match="não conseguiu processar"):
        ghostscript.executar(["-sDEVICE=pdfwrite", f"-sOutputFile={tmp_path / 'y.pdf'}", str(entrada)])


@requer_ghostscript
def test_compressao_forte(tmp_path):
    Image.effect_noise((1600, 2200), 60).convert("RGB").save(tmp_path / "scan.png")
    origem = imagens_para_pdf([tmp_path / "scan.png"], tmp_path / "scan.pdf").destino

    resultado = comprimir(origem, tmp_path / "forte.pdf", NivelCompressao.FORTE)

    assert resultado.destino.stat().st_size < origem.stat().st_size / 3
    assert "menor" in resultado.observacao
