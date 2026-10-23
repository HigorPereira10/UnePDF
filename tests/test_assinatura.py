import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from certificados import (
    CNPJ_EXEMPLO,
    SENHA,
    certificado_da_autoridade,
    certificado_intermediario_der,
    criar_lcr,
    criar_pfx,
    numero_de_serie,
)
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from unepdf.core import assinatura
from unepdf.core.assinatura import PosicaoCarimbo, SituacaoCertificado, abrir_certificado, assinar, assinar_varios
from unepdf.core.carimbo import fonte_padrao, literal_pdf
from unepdf.core.erros import ErroUnePDF
from unepdf.core.leitor_pdf import tem_assinatura


def criar_procuracao(caminho: Path, cnpj: str = "12.345.678/0001-99", linha: bool = True, paginas: int = 1) -> Path:
    """Procuração fictícia: o outorgante com CNPJ e, na última página, a linha de assinatura."""
    escritor = PdfWriter()
    for numero in range(paginas):
        pagina = escritor.add_blank_page(595, 842)
        pagina[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): fonte_padrao(escritor)}),
        })
        textos = [(72, 760, "PROCURACAO"), (72, 720, f"OUTORGANTE: EMPRESA EXEMPLO LTDA, CNPJ {cnpj}")]
        if linha and numero == paginas - 1:
            textos += [(150, 200, "_" * 40), (190, 185, "EMPRESA EXEMPLO LTDA")]
        fluxo = DecodedStreamObject()
        fluxo.set_data("\n".join(f"BT /F1 12 Tf {x} {y} Td {literal_pdf(t)} Tj ET" for x, y, t in textos).encode("latin-1"))
        pagina[NameObject("/Contents")] = escritor._add_object(fluxo)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    escritor.write(caminho)
    return caminho


def validar(caminho: Path):
    """Estado de cada assinatura do PDF, conferida com a autoridade certificadora de teste."""
    from pyhanko.pdf_utils.reader import PdfFileReader
    from pyhanko.sign.validation import validate_pdf_signature
    from pyhanko_certvalidator import ValidationContext

    with open(caminho, "rb") as arquivo:
        leitor = PdfFileReader(arquivo)
        contexto = ValidationContext(trust_roots=[certificado_da_autoridade()])
        return [validate_pdf_signature(s, contexto) for s in leitor.embedded_signatures]


@pytest.fixture
def certificado(tmp_path):
    return abrir_certificado(criar_pfx(tmp_path / "cliente.pfx"), SENHA)


def test_abre_o_certificado_e_le_os_dados_da_icp_brasil(certificado):
    assert certificado.titular == f"EMPRESA EXEMPLO LTDA:{CNPJ_EXEMPLO}"
    assert certificado.nome == "EMPRESA EXEMPLO LTDA"
    assert (certificado.tipo_documento, certificado.documento_formatado) == ("CNPJ", "12.345.678/0001-99")
    assert certificado.emissor == "AC TESTE UNEPDF"
    assert 298 <= certificado.dias_restantes() <= 300 and not certificado.vencido


def test_certificado_de_pessoa_fisica(tmp_path):
    certificado = abrir_certificado(criar_pfx(tmp_path / "pf.pfx", "FULANO DE TAL", "12345678909"), SENHA)
    assert (certificado.tipo_documento, certificado.documento_formatado) == ("CPF", "123.456.789-09")


def test_senha_errada_e_arquivo_invalido(tmp_path):
    pfx = criar_pfx(tmp_path / "cliente.pfx")
    with pytest.raises(ErroUnePDF, match="Senha incorreta"):
        abrir_certificado(pfx, "errada")
    (tmp_path / "falso.pfx").write_bytes(b"nada")
    with pytest.raises(ErroUnePDF, match="Senha incorreta, ou o arquivo"):
        abrir_certificado(tmp_path / "falso.pfx", SENHA)


def test_assina_com_carimbo_sobre_a_linha(tmp_path, certificado):
    origem = criar_procuracao(tmp_path / "procuracao.pdf")
    dados = origem.read_bytes()
    posicao = assinatura.posicao_automatica(dados)
    assert posicao.sobre_linha and posicao.pagina == 0
    x1, y1, x2, y2 = posicao.caixa
    assert 197 <= y1 <= 201 and x2 - x1 == assinatura.LARGURA_CARIMBO

    resultado = assinar(origem, tmp_path / "assinado.pdf", certificado, posicao)

    estado = validar(resultado.destino)[0]
    assert estado.intact and estado.valid and estado.trusted
    leitor = PdfReader(resultado.destino)
    assert tem_assinatura(leitor) and not tem_assinatura(PdfReader(origem))
    # O carimbo fica no campo da assinatura, na posição escolhida
    campo = leitor.pages[0]["/Annots"][0].get_object()
    assert [round(float(v)) for v in campo["/Rect"]] == [round(v) for v in posicao.caixa]


def test_sem_linha_o_carimbo_vai_para_o_pe_da_ultima_pagina(tmp_path):
    dados = criar_procuracao(tmp_path / "a.pdf", linha=False, paginas=2).read_bytes()
    posicao = assinatura.posicao_automatica(dados)
    assert posicao.pagina == 1 and not posicao.sobre_linha
    assert posicao.caixa[1] == assinatura.MARGEM


def test_linha_na_pagina_anterior(tmp_path):
    escritor = PdfWriter()
    escritor.append(criar_procuracao(tmp_path / "a.pdf"))
    escritor.add_blank_page(595, 842)  # anexo sem linha de assinatura
    escritor.write(tmp_path / "b.pdf")
    assert assinatura.posicao_automatica((tmp_path / "b.pdf").read_bytes()).pagina == 0


def test_mover_carimbo_mantem_o_tamanho(tmp_path):
    posicao = PosicaoCarimbo(0, (10, 10, 240, 52), True)
    movida = assinatura.mover_carimbo(posicao, 1, 300, 400)
    assert movida.pagina == 1 and movida.caixa == (185, 379, 415, 421)


def test_assinatura_invisivel_e_segunda_assinatura(tmp_path, certificado):
    origem = criar_procuracao(tmp_path / "a.pdf")
    primeira = assinar(origem, tmp_path / "1.pdf", certificado, None).destino
    outro = abrir_certificado(criar_pfx(tmp_path / "escritorio.pfx", "ESCRITORIO EXEMPLO LTDA", "99888777000166"), SENHA)

    segunda = assinar(primeira, tmp_path / "2.pdf", outro, assinatura.posicao_automatica(primeira.read_bytes())).destino

    estados = validar(segunda)
    assert len(estados) == 2 and all(e.intact and e.valid for e in estados)


def test_cnpj_do_certificado_no_documento(tmp_path):
    assert assinatura.documento_aparece(criar_procuracao(tmp_path / "a.pdf").read_bytes(), CNPJ_EXEMPLO)
    assert assinatura.documento_aparece(criar_procuracao(tmp_path / "b.pdf", cnpj=CNPJ_EXEMPLO).read_bytes(), CNPJ_EXEMPLO)
    assert not assinatura.documento_aparece(criar_procuracao(tmp_path / "c.pdf").read_bytes(), "99888777000166")
    # Um número maior que contém os mesmos dígitos não conta
    assert not assinatura.documento_aparece(
        criar_procuracao(tmp_path / "d.pdf", cnpj="512345678000199").read_bytes(), CNPJ_EXEMPLO
    )


def test_certificado_vencido_nao_assina(tmp_path):
    vencido = abrir_certificado(criar_pfx(tmp_path / "v.pfx", dias_restantes=-2), SENHA)
    assert vencido.vencido
    with pytest.raises(ErroUnePDF, match="venceu"):
        assinar(criar_procuracao(tmp_path / "a.pdf"), tmp_path / "b.pdf", vencido, None)


def test_pdf_com_senha_nao_assina(tmp_path, certificado, criar_pdf):
    origem = criar_pdf(tmp_path / "a.pdf", senha_dono="dono")
    with pytest.raises(ErroUnePDF, match="Remova a senha"):
        assinar(origem, tmp_path / "b.pdf", certificado, None)


def test_sem_internet_assina_sem_a_confirmacao(tmp_path, certificado, monkeypatch):
    original = assinatura._assinar_bytes

    def sem_rede(dados, certificado, posicao, quando, com_validacao):
        if com_validacao:
            raise OSError("sem conexão")
        return original(dados, certificado, posicao, quando, com_validacao)

    monkeypatch.setattr(assinatura, "_assinar_bytes", sem_rede)
    resultado = assinar(criar_procuracao(tmp_path / "a.pdf"), tmp_path / "b.pdf", certificado, None)
    assert not resultado.com_validacao and resultado.sem_internet
    assert validar(resultado.destino)[0].intact


@pytest.fixture
def raiz_de_teste(monkeypatch):
    """A AC de teste no lugar das raízes da ICP-Brasil."""
    monkeypatch.setattr(assinatura, "raizes_icp_brasil", lambda: [certificado_da_autoridade()])


@pytest.fixture
def com_internet(monkeypatch):
    monkeypatch.setattr("socket.create_connection", lambda *args, **kwargs: type("Conexao", (), {"close": lambda self: None})())


@pytest.fixture
def sem_internet(monkeypatch):
    def recusar(*args, **kwargs):
        raise OSError("sem conexão")

    monkeypatch.setattr("socket.create_connection", recusar)


def pfx_com_lcr(caminho: Path, publicar, revogado: bool = False) -> Path:
    """Certificado com a lista de revogação publicada no servidor local, como os da ICP-Brasil."""
    endereco = publicar(f"{caminho.stem}.crl")
    pfx = criar_pfx(caminho, endereco_lcr=endereco)
    publicar(f"{caminho.stem}.crl", criar_lcr((numero_de_serie(pfx),) if revogado else ()), "application/pkix-crl")
    return pfx


def _nomes_dos_certificados(caminho: Path) -> set[str]:
    from pyhanko.pdf_utils.reader import PdfFileReader

    with open(caminho, "rb") as arquivo:
        cms = PdfFileReader(arquivo).embedded_signatures[0].signed_data
        return {c.chosen.subject.native["common_name"] for c in cms["certificates"]}


def test_raizes_da_icp_brasil():
    raizes = assinatura.raizes_icp_brasil()
    assert len(raizes) >= 6
    assert all(r.self_issued and r.ca for r in raizes)
    assert all(r.subject.native["common_name"].startswith("Autoridade Certificadora Raiz Brasileira") for r in raizes)


def test_pfx_sem_a_cadeia_busca_a_ac_e_inclui_na_assinatura(tmp_path, raiz_de_teste, publicar):
    # Como alguns e-CNPJ: o .pfx só tem o titular, e a raiz vem do próprio app
    endereco = publicar("ac.cer", certificado_intermediario_der(), "application/pkix-cert")
    pfx = criar_pfx(tmp_path / "cliente.pfx", intermediaria=True, com_cadeia=False, endereco_ac=endereco)

    resultado = assinar(criar_procuracao(tmp_path / "a.pdf"), tmp_path / "b.pdf", abrir_certificado(pfx, SENHA), None)

    assert resultado.com_validacao
    assert "AC INTERMEDIARIA TESTE UNEPDF" in _nomes_dos_certificados(resultado.destino)
    # Quem confere a assinatura só precisa conhecer a raiz
    estado = validar(resultado.destino)[0]
    assert estado.intact and estado.valid and estado.trusted


def test_cadeia_desconhecida_com_internet_avisa_que_nao_conferiu(tmp_path, monkeypatch, com_internet):
    monkeypatch.setattr(assinatura, "raizes_icp_brasil", lambda: [])
    pfx = criar_pfx(tmp_path / "cliente.pfx", intermediaria=True, com_cadeia=False)
    origem = criar_procuracao(tmp_path / "a.pdf")

    resultado = assinar_varios([origem], {origem: tmp_path / "b.pdf"}, abrir_certificado(pfx, SENHA), visivel=False)

    assert (resultado.sem_validacao, resultado.sem_cadeia) == (1, 1)
    assert validar(resultado.gerados[0])[0].intact


def test_certificado_revogado_nao_assina(tmp_path, raiz_de_teste, publicar):
    revogado = abrir_certificado(pfx_com_lcr(tmp_path / "revogado.pfx", publicar, revogado=True), SENHA)
    with pytest.raises(ErroUnePDF, match="revogado"):
        assinar(criar_procuracao(tmp_path / "a.pdf"), tmp_path / "b.pdf", revogado, None)
    assert not (tmp_path / "b.pdf").exists()


# Conferência do certificado ao abrir


def test_conferir_certificado_valido_e_revogado(tmp_path, raiz_de_teste, publicar):
    valido = abrir_certificado(pfx_com_lcr(tmp_path / "valido.pfx", publicar), SENHA)
    revogado = abrir_certificado(pfx_com_lcr(tmp_path / "revogado.pfx", publicar, revogado=True), SENHA)
    assert assinatura.conferir_certificado(valido) is SituacaoCertificado.VALIDO
    assert assinatura.conferir_certificado(revogado) is SituacaoCertificado.REVOGADO


def test_conferir_certificado_busca_a_ac_que_falta(tmp_path, raiz_de_teste, publicar):
    endereco = publicar("ac.cer", certificado_intermediario_der(), "application/pkix-cert")
    pfx = criar_pfx(tmp_path / "c.pfx", intermediaria=True, com_cadeia=False, endereco_ac=endereco)
    assert assinatura.conferir_certificado(abrir_certificado(pfx, SENHA)) is SituacaoCertificado.VALIDO


def test_raiz_dentro_do_pfx_nao_torna_o_certificado_valido(certificado, monkeypatch, com_internet):
    # O .pfx de teste traz a própria AC; sem ela entre as raízes oficiais, a cadeia é desconhecida
    monkeypatch.setattr(assinatura, "raizes_icp_brasil", lambda: [])
    assert assinatura.conferir_certificado(certificado) is SituacaoCertificado.CADEIA_DESCONHECIDA


def test_conferir_certificado_sem_internet(tmp_path, raiz_de_teste, sem_internet):
    pfx = criar_pfx(tmp_path / "c.pfx", intermediaria=True, com_cadeia=False, endereco_ac="http://127.0.0.1:9/ac.cer")
    assert assinatura.conferir_certificado(abrir_certificado(pfx, SENHA)) is SituacaoCertificado.NAO_CONFERIDO


def test_desenho_do_carimbo(certificado):
    quando = datetime(2026, 10, 15, 9, 32, 51, tzinfo=timezone(timedelta(hours=-3)))
    assert assinatura.data_do_carimbo(quando) == "2026.10.15 09:32:51 -03'00'"
    desenho = assinatura.desenhar_carimbo(certificado.titular, quando)
    texto = PdfReader(__import__("io").BytesIO(desenho)).pages[0].extract_text()
    assert "Assinado de forma digital por" in texto and "Dados: 2026.10.15 09:32:51 -03'00'" in texto
    # Nome comprido também cabe, em letras menores
    longo = assinatura.desenhar_carimbo("EMPRESA DE NOME MUITO COMPRIDO EXEMPLO COMERCIO E SERVICOS LTDA:12345678000199", quando)
    assert "COMPRIDO" in PdfReader(__import__("io").BytesIO(longo)).pages[0].extract_text()


def test_assinar_varios_com_registro(tmp_path, certificado, criar_pdf):
    arquivos = [criar_procuracao(tmp_path / "a.pdf"), criar_procuracao(tmp_path / "b.pdf", linha=False)]
    (tmp_path / "vazio.pdf").write_bytes(b"")
    arquivos.append(tmp_path / "vazio.pdf")
    destinos = {a: tmp_path / "UnePDF" / f"{a.stem} - assinado.pdf" for a in arquivos}
    registro = tmp_path / "logs" / "assinaturas.csv"

    resultado = assinar_varios(arquivos, destinos, certificado, arquivo_registro=registro)

    assert [p.name for p in resultado.gerados] == ["a - assinado.pdf", "b - assinado.pdf"]
    assert resultado.ignorados[0].caminho.name == "vazio.pdf"
    linhas = list(csv.reader(registro.read_text(encoding="utf-8-sig").splitlines(), delimiter=";"))
    assert linhas[0][:4] == ["Data", "Hora", "Arquivo assinado", "Titular do certificado"]
    assert linhas[1][3:5] == ["EMPRESA EXEMPLO LTDA", "12.345.678/0001-99"]
    assert len(linhas) == 3


def test_unir_avisa_que_assinaturas_nao_valem(tmp_path, certificado, criar_pdf):
    from unepdf.core.unir import unir

    assinado = assinar(criar_procuracao(tmp_path / "a.pdf"), tmp_path / "a - assinado.pdf", certificado, None).destino
    resultado = unir([assinado, criar_pdf(tmp_path / "b.pdf")], tmp_path / "u.pdf")
    assert "1 arquivo(s) tinham assinatura digital" in resultado.observacao
