import pytest
from certificados import SENHA, certificado_da_autoridade, certificado_intermediario_der, criar_pfx
from pypdf import PdfWriter
from test_assinatura import com_internet, criar_procuracao, pfx_com_lcr, raiz_de_teste, sem_internet  # noqa: F401

from unepdf.core import assinatura
from unepdf.core.assinatura import SituacaoCertificado, abrir_certificado, assinar
from unepdf.core.conferir import Alteracao, conferir_assinaturas, conferir_pdf, selecionar_pdfs
from unepdf.core.erros import ErroUnePDF


def _raizes():
    return [certificado_da_autoridade()]


@pytest.fixture
def certificado(tmp_path):
    return abrir_certificado(criar_pfx(tmp_path / "cliente.pfx"), SENHA)


def _assinado(tmp_path, certificado, nome="assinado.pdf", **opcoes):
    return assinar(criar_procuracao(tmp_path / "procuracao.pdf"), tmp_path / nome, certificado, None, **opcoes).destino


def test_assinatura_completa(tmp_path, raiz_de_teste, publicar):
    certificado = abrir_certificado(pfx_com_lcr(tmp_path / "cliente.pfx", publicar), SENHA)

    conferida = conferir_pdf(_assinado(tmp_path, certificado), _raizes()).assinaturas[0]

    assert conferida.valida and conferida.cadeia_no_pdf and conferida.revogacao_no_pdf
    assert conferida.alteracao is Alteracao.NENHUMA and conferida.situacao is SituacaoCertificado.VALIDO
    assert (conferida.titular, conferida.documento) == ("EMPRESA EXEMPLO LTDA", "12.345.678/0001-99")
    assert conferida.quando is not None


def test_sem_a_cadeia_no_pdf_vale_mas_fica_incompleta(tmp_path, publicar):
    # O caso que o Adobe recusa: o .pfx só tinha o titular e nada mais foi para dentro do PDF
    endereco = publicar("ac.cer", certificado_intermediario_der(), "application/pkix-cert")
    pfx = criar_pfx(tmp_path / "c.pfx", intermediaria=True, com_cadeia=False, endereco_ac=endereco)
    assinado = _assinado(tmp_path, abrir_certificado(pfx, SENHA), incluir_validacao=False)

    conferida = conferir_pdf(assinado, _raizes()).assinaturas[0]

    assert conferida.valida and conferida.situacao is SituacaoCertificado.VALIDO
    assert not conferida.cadeia_no_pdf and not conferida.revogacao_no_pdf


def test_alterado_depois_da_assinatura(tmp_path, certificado):
    assinado = _assinado(tmp_path, certificado)
    escritor = PdfWriter(assinado, incremental=True)
    escritor.add_blank_page(595, 842)
    escritor.write(tmp_path / "alterado.pdf")

    conferida = conferir_pdf(tmp_path / "alterado.pdf", _raizes()).assinaturas[0]

    assert conferida.integra and conferida.alteracao is Alteracao.PROIBIDA and not conferida.valida


def test_trecho_assinado_modificado(tmp_path, certificado):
    dados = _assinado(tmp_path, certificado).read_bytes()
    assert b"PROCURACAO" in dados
    (tmp_path / "modificado.pdf").write_bytes(dados.replace(b"PROCURACAO", b"PROCURACAX", 1))

    conferida = conferir_pdf(tmp_path / "modificado.pdf", _raizes()).assinaturas[0]

    assert not conferida.integra and not conferida.valida


def test_segunda_assinatura_nao_estraga_a_primeira(tmp_path, certificado):
    primeira = _assinado(tmp_path, certificado, "1.pdf")
    escritorio = abrir_certificado(criar_pfx(tmp_path / "e.pfx", "ESCRITORIO EXEMPLO LTDA", "99888777000166"), SENHA)
    segunda = assinar(primeira, tmp_path / "2.pdf", escritorio, None).destino

    cliente, do_escritorio = conferir_pdf(segunda, _raizes()).assinaturas

    assert cliente.valida and cliente.alteracao is Alteracao.PERMITIDA
    assert do_escritorio.valida and do_escritorio.alteracao is Alteracao.NENHUMA
    assert do_escritorio.titular == "ESCRITORIO EXEMPLO LTDA"


def test_certificado_revogado_antes_de_assinar(tmp_path, publicar):
    revogado = abrir_certificado(pfx_com_lcr(tmp_path / "r.pfx", publicar, revogado=True), SENHA)
    assinado = _assinado(tmp_path, revogado, incluir_validacao=False)

    conferida = conferir_pdf(assinado, _raizes()).assinaturas[0]

    assert conferida.situacao is SituacaoCertificado.REVOGADO and not conferida.valida


def test_cadeia_desconhecida_ou_nao_conferida(tmp_path, monkeypatch, certificado):
    assinado = _assinado(tmp_path, certificado, incluir_validacao=False)
    pfx = criar_pfx(tmp_path / "c.pfx", intermediaria=True, com_cadeia=False, endereco_ac="http://127.0.0.1:9/ac.cer")
    sem_cadeia = _assinado(tmp_path, abrir_certificado(pfx, SENHA), "sem_cadeia.pdf", incluir_validacao=False)

    monkeypatch.setattr("socket.create_connection", lambda *a, **k: type("Conexao", (), {"close": lambda self: None})())
    assert conferir_pdf(assinado, []).assinaturas[0].situacao is SituacaoCertificado.CADEIA_DESCONHECIDA

    def recusar(*args, **kwargs):
        raise OSError("sem conexão")

    monkeypatch.setattr("socket.create_connection", recusar)
    assert conferir_pdf(sem_cadeia, _raizes()).assinaturas[0].situacao is SituacaoCertificado.NAO_CONFERIDO


def test_varios_pdfs_com_e_sem_assinatura(tmp_path, monkeypatch, certificado, criar_pdf):
    monkeypatch.setattr(assinatura, "raizes_icp_brasil", _raizes)
    assinado = _assinado(tmp_path, certificado)
    comum = criar_pdf(tmp_path / "comum.pdf")
    (tmp_path / "quebrado.pdf").write_bytes(b"nao e pdf")
    com_senha = criar_pdf(tmp_path / "senha.pdf", senha="123")

    resultado = conferir_assinaturas([assinado, comum, tmp_path / "quebrado.pdf", com_senha])

    assert [d.caminho for d in resultado.documentos] == [assinado]
    assert resultado.sem_assinatura == [comum]
    assert {i.caminho.name for i in resultado.ignorados} == {"quebrado.pdf", "senha.pdf"}


def test_selecionar_pdfs_inclui_a_pasta_de_saida(tmp_path, criar_pdf):
    saida = tmp_path / "UnePDF"
    assinado = criar_pdf(saida / "contrato - assinado.pdf")
    (saida / "anotacao.txt").write_text("x")
    assert selecionar_pdfs([saida]) == [assinado]
    assert selecionar_pdfs([assinado, saida]) == [assinado]
    with pytest.raises(ErroUnePDF, match="Nenhum PDF"):
        selecionar_pdfs([saida / "anotacao.txt"])
