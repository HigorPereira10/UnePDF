import pytest

from unepdf.core.leitor_pdf import PdfInvalido, abrir_pdf


def test_le_pdf_valido(tmp_path, criar_pdf):
    leitor = abrir_pdf(criar_pdf(tmp_path / "ok.pdf", paginas=2))
    assert len(leitor.pages) == 2


@pytest.mark.parametrize("algoritmo", ["RC4-128", "AES-128", "AES-256"])
def test_abre_pdf_com_senha_so_de_permissao(tmp_path, criar_pdf, algoritmo):
    caminho = criar_pdf(tmp_path / "permissao.pdf", senha_dono="dono", algoritmo=algoritmo)
    assert len(abrir_pdf(caminho).pages) == 1


@pytest.mark.parametrize("algoritmo", ["RC4-128", "AES-256"])
def test_recusa_pdf_com_senha_de_abertura(tmp_path, criar_pdf, algoritmo):
    caminho = criar_pdf(tmp_path / "senha.pdf", senha="123", algoritmo=algoritmo)
    with pytest.raises(PdfInvalido, match="protegido por senha"):
        abrir_pdf(caminho)


def test_recusa_arquivo_vazio(tmp_path):
    vazio = tmp_path / "vazio.pdf"
    vazio.write_bytes(b"")
    with pytest.raises(PdfInvalido, match=r"arquivo vazio \(0 KB\)"):
        abrir_pdf(vazio)


@pytest.mark.parametrize("conteudo", [b"isto nao e um pdf", b"%PDF-1.7\n", b"%PDF-1.4\n1 0 obj\n<<"])
def test_recusa_arquivo_corrompido(tmp_path, conteudo):
    quebrado = tmp_path / "quebrado.pdf"
    quebrado.write_bytes(conteudo)
    with pytest.raises(PdfInvalido, match="corrompido ou ilegível"):
        abrir_pdf(quebrado)


def test_recusa_pdf_truncado(tmp_path, criar_pdf):
    # Simula um download ou cópia pela rede interrompidos no meio
    caminho = criar_pdf(tmp_path / "truncado.pdf", paginas=3)
    caminho.write_bytes(caminho.read_bytes()[:200])
    with pytest.raises(PdfInvalido):
        abrir_pdf(caminho)


def test_arquivo_inexistente(tmp_path):
    with pytest.raises(PdfInvalido, match="não foi possível ler o arquivo"):
        abrir_pdf(tmp_path / "sumiu.pdf")
