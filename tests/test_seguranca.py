import pytest
from pypdf import PdfReader, PdfWriter

from unepdf.core.erros import ErroUnePDF
from unepdf.core.seguranca import proteger, remover_senha, situacao_senha


def _com_marcador(caminho):
    escritor = PdfWriter()
    for _ in range(2):
        escritor.add_blank_page(595, 842)
    escritor.add_outline_item("Capítulo", 1)
    escritor.write(caminho)
    return caminho


def test_proteger_exige_a_senha_para_abrir(tmp_path):
    origem = _com_marcador(tmp_path / "contrato.pdf")

    resultado = proteger(origem, tmp_path / "p.pdf", "segredo1")

    leitor = PdfReader(resultado.destino)
    assert leitor.is_encrypted
    assert not leitor.decrypt("")
    assert leitor.decrypt("segredo1")
    assert leitor.trailer["/Encrypt"]["/V"] == 5  # versão 5 da criptografia do PDF: AES de 256 bits
    assert [m.title for m in leitor.outline] == ["Capítulo"]  # marcadores preservados
    assert not PdfReader(origem).is_encrypted  # o original continua sem senha


def test_proteger_senha_curta_e_erro(tmp_path, criar_pdf):
    with pytest.raises(ErroUnePDF, match="pelo menos 4"):
        proteger(criar_pdf(tmp_path / "a.pdf"), tmp_path / "p.pdf", "123")


def test_proteger_pdf_que_ja_pede_senha_e_erro(tmp_path, criar_pdf):
    origem = criar_pdf(tmp_path / "a.pdf", senha="antiga")
    with pytest.raises(ErroUnePDF, match="protegido por senha"):
        proteger(origem, tmp_path / "p.pdf", "nova1234")


def test_situacao_senha(tmp_path, criar_pdf):
    sem = situacao_senha(criar_pdf(tmp_path / "a.pdf", paginas=3))
    abrir = situacao_senha(criar_pdf(tmp_path / "b.pdf", senha="1234"))
    permissao = situacao_senha(criar_pdf(tmp_path / "c.pdf", senha_dono="dono", algoritmo="AES-256"))

    assert (sem.protegido, sem.pede_senha_para_abrir, sem.paginas) == (False, False, 3)
    assert (abrir.protegido, abrir.pede_senha_para_abrir, abrir.paginas) == (True, True, None)
    assert (permissao.protegido, permissao.pede_senha_para_abrir) == (True, False)


@pytest.mark.parametrize("algoritmo", ["RC4-128", "AES-256"])
def test_remover_senha_com_a_senha_de_abertura(tmp_path, criar_pdf, algoritmo):
    origem = criar_pdf(tmp_path / "a.pdf", paginas=2, senha="1234", algoritmo=algoritmo)

    resultado = remover_senha(origem, tmp_path / "livre.pdf", "1234")

    leitor = PdfReader(resultado.destino)
    assert not leitor.is_encrypted
    assert len(leitor.pages) == 2


def test_remover_senha_errada(tmp_path, criar_pdf):
    origem = criar_pdf(tmp_path / "a.pdf", senha="1234")
    with pytest.raises(ErroUnePDF, match="Senha incorreta"):
        remover_senha(origem, tmp_path / "livre.pdf", "9999")
    assert not (tmp_path / "livre.pdf").exists()


def test_restricoes_de_permissao_so_saem_com_a_senha_do_proprietario(tmp_path, criar_pdf):
    origem = criar_pdf(tmp_path / "a.pdf", senha_dono="dono", algoritmo="AES-256")

    with pytest.raises(ErroUnePDF, match="senha do proprietário"):
        remover_senha(origem, tmp_path / "livre.pdf", "")
    with pytest.raises(ErroUnePDF, match="Senha incorreta"):
        remover_senha(origem, tmp_path / "livre.pdf", "chute")

    resultado = remover_senha(origem, tmp_path / "livre.pdf", "dono")
    assert not PdfReader(resultado.destino).is_encrypted


def test_remover_de_pdf_sem_senha_e_erro(tmp_path, criar_pdf):
    with pytest.raises(ErroUnePDF, match="não tem senha"):
        remover_senha(criar_pdf(tmp_path / "a.pdf"), tmp_path / "x.pdf", "1234")


@pytest.mark.parametrize("conteudo,trecho", [(b"", "vazio"), (b"lixo", "corrompido")])
def test_arquivo_invalido(tmp_path, conteudo, trecho):
    ruim = tmp_path / "ruim.pdf"
    ruim.write_bytes(conteudo)
    with pytest.raises(ErroUnePDF, match=trecho):
        situacao_senha(ruim)


def test_ida_e_volta(tmp_path, criar_pdf):
    origem = criar_pdf(tmp_path / "a.pdf", paginas=3)
    protegido = proteger(origem, tmp_path / "p.pdf", "segredo1").destino
    livre = remover_senha(protegido, tmp_path / "l.pdf", "segredo1").destino
    assert len(PdfReader(livre).pages) == 3
