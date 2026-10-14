import pytest
from conftest import criar_pdf_com_texto
from PIL import Image
from pypdf import PdfReader

from unepdf.core.comprimir import NivelCompressao, comprimir
from unepdf.core.erros import OperacaoCancelada
from unepdf.core.imagens import imagens_para_pdf
from unepdf.core.progresso import Cancelamento
from unepdf.utils.texto import tamanho_legivel


def _pdf_de_imagem(tmp_path, tamanho=(2600, 3400), modo="RGB"):
    Image.effect_noise(tamanho, 50).convert(modo).save(tmp_path / "scan.png")
    return imagens_para_pdf([tmp_path / "scan.png"], tmp_path / "scan.pdf").destino


def test_sem_perda_compacta_o_conteudo(tmp_path):
    origem = criar_pdf_com_texto(tmp_path / "texto.pdf", ["Linha de texto repetida " * 40] * 20)

    resultado = comprimir(origem, tmp_path / "c.pdf", NivelCompressao.SEM_PERDA)

    assert resultado.destino.stat().st_size < origem.stat().st_size
    assert len(PdfReader(resultado.destino).pages) == 20


def test_recomendada_reduz_imagens_grandes(tmp_path):
    origem = _pdf_de_imagem(tmp_path)

    resultado = comprimir(origem, tmp_path / "c.pdf", NivelCompressao.RECOMENDADA)

    imagem = PdfReader(resultado.destino).pages[0].images[0].image
    assert max(imagem.size) <= 2200
    assert resultado.destino.stat().st_size < origem.stat().st_size / 3
    assert "% menor" in resultado.observacao


def test_preto_e_branco_nao_vira_jpg(tmp_path):
    origem = _pdf_de_imagem(tmp_path, modo="1")
    resultado = comprimir(origem, tmp_path / "c.pdf", NivelCompressao.RECOMENDADA)
    imagem = list(PdfReader(resultado.destino).pages[0]["/Resources"]["/XObject"].values())[0].get_object()
    assert imagem["/Filter"] != "/DCTDecode"


def test_arquivo_que_nao_diminui_recebe_aviso(tmp_path, criar_pdf):
    resultado = comprimir(criar_pdf(tmp_path / "a.pdf"), tmp_path / "c.pdf", NivelCompressao.SEM_PERDA)
    assert "já estava bem compactado" in resultado.observacao


def test_cancelamento(tmp_path, criar_pdf):
    cancelamento = Cancelamento()
    cancelamento.cancelar()
    with pytest.raises(OperacaoCancelada):
        comprimir(criar_pdf(tmp_path / "a.pdf"), tmp_path / "c.pdf", cancelamento=cancelamento)
    assert not (tmp_path / "c.pdf").exists()


@pytest.mark.parametrize("tamanho,texto", [
    (850, "850 bytes"), (1, "1 byte"), (2048, "2,0 KB"), (1_250_000, "1,2 MB"), (52_000_000, "50 MB"),
])
def test_tamanho_legivel(tamanho, texto):
    assert tamanho_legivel(tamanho) == texto
