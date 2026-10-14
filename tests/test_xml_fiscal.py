import pytest
import xmls_fiscais as x
from pypdf import PdfReader

from unepdf.core.erros import ErroUnePDF
from unepdf.core.progresso import Cancelamento
from unepdf.core.xml_fiscal import (
    EventoCancelamento,
    TipoDocumento,
    XmlNaoReconhecido,
    analisar,
    completar_cartas_de_correcao,
    ler_xml,
    nomes_dos_pdfs,
)
from unepdf.core.xml_pdf import Fonte, OpcoesDocumento, converter_xmls, gerar_pdf


def _texto_pdf(dados_ou_caminho) -> str:
    import io

    origem = io.BytesIO(dados_ou_caminho) if isinstance(dados_ou_caminho, bytes) else dados_ou_caminho
    return "\n".join(p.extract_text() for p in PdfReader(origem).pages)


@pytest.mark.parametrize("conteudo,tipo,numero,emitente", [
    (x.nfe(), TipoDocumento.DANFE, 1234, "EMPRESA EXEMPLO LTDA"),
    (x.nfe(protocolo=False), TipoDocumento.DANFE, 1234, "EMPRESA EXEMPLO LTDA"),
    (x.nfe(modelo=65, numero=55), TipoDocumento.DANFCE, 55, "EMPRESA EXEMPLO LTDA"),
    (x.cte(), TipoDocumento.DACTE, 567, "EXEMPLO TRANSPORTES LTDA"),
    (x.mdfe(), TipoDocumento.DAMDFE, 89, "EXEMPLO TRANSPORTES LTDA"),
    (x.nfse(), TipoDocumento.DANFSE, 42, "EXEMPLO SERVICOS LTDA"),
    (x.evento(x.chave(55, 1234)), TipoDocumento.DACCE, 1234, ""),
])
def test_reconhece_cada_tipo_pelo_conteudo(tmp_path, conteudo, tipo, numero, emitente):
    documento = ler_xml(x.gravar(tmp_path / "qualquer nome.xml", conteudo))

    assert (documento.tipo, documento.numero, documento.emitente) == (tipo, numero, emitente)


def test_le_xml_em_iso_8859_1_com_acentos(tmp_path):
    caminho = x.gravar(tmp_path / "a.xml", x.nfe(emitente="AÇÚCAR &amp; CIA LTDA"), "iso-8859-1")
    documento = ler_xml(caminho)
    assert documento.emitente == "AÇÚCAR & CIA LTDA"
    assert "AÇÚCAR & CIA LTDA" in _texto_pdf(gerar_pdf(documento, OpcoesDocumento()))


def test_cancelamento_registrado_vira_evento(tmp_path):
    chave = x.chave(55, 1234)
    evento = ler_xml(x.gravar(tmp_path / "c.xml", x.evento(chave, tipo="110111")))
    assert evento == EventoCancelamento(tmp_path / "c.xml", chave)

    with pytest.raises(XmlNaoReconhecido, match="sem o registro da SEFAZ"):
        ler_xml(x.gravar(tmp_path / "d.xml", x.evento(chave, tipo="110111", c_stat="573")))


@pytest.mark.parametrize("conteudo,motivo", [
    ("", "arquivo vazio"),
    ("<NFe><infNFe>", "corrompido"),
    ("<?xml version='1.0'?><planilha><linha/></planilha>", "não é XML de documento fiscal"),
    ("<CompNfse xmlns='http://www.abrasf.org.br/nfse.xsd'><Nfse/></CompNfse>", "padrão próprio da prefeitura"),
    ("<ConsultarNfseResposta><ListaNfse/></ConsultarNfseResposta>", "padrão próprio da prefeitura"),
    (f"<resNFe xmlns='{x.NFE}'><chNFe>1</chNFe></resNFe>", "resumo da nota"),
    (x.cte(modelo=67), "CT-e OS"),
    (x.nfe(modelo=57), "modelo 57"),
    (x.evento(x.chave(55, 1), tipo="210200"), "evento sem representação em PDF"),
    (f"<NFSe xmlns='{x.NFSE}'><outra/></NFSe>", "sem a nota autorizada"),
])
def test_motivos_dos_xmls_nao_reconhecidos(tmp_path, conteudo, motivo):
    with pytest.raises(XmlNaoReconhecido, match=motivo):
        ler_xml(x.gravar(tmp_path / "a.xml", conteudo))


def test_recusa_xml_com_entidades_que_se_multiplicam(tmp_path):
    bomba = (
        '<?xml version="1.0"?><!DOCTYPE a [<!ENTITY b "bbbbbbbbbb"><!ENTITY c "&b;&b;&b;&b;&b;&b;">]>'
        "<a>&c;&c;&c;</a>"
    )
    with pytest.raises(XmlNaoReconhecido, match="corrompido"):
        ler_xml(x.gravar(tmp_path / "a.xml", bomba))


def test_analise_separa_documentos_eventos_e_problemas(tmp_path):
    chave = x.chave(55, 1234)
    arquivos = [
        x.gravar(tmp_path / "1.xml", x.nfe()),
        x.gravar(tmp_path / "2.xml", x.nfe()),  # o mesmo documento de novo
        x.gravar(tmp_path / "3.xml", x.evento(chave, tipo="110111")),
        x.gravar(tmp_path / "4.xml", x.evento(x.chave(55, 999), tipo="110111")),
        x.gravar(tmp_path / "5.xml", x.cte()),
        x.gravar(tmp_path / "6.xml", "lixo"),
    ]
    passos = []

    analise = analisar(arquivos, lambda *a: passos.append(a[0]))

    assert [d.tipo for d in analise.documentos] == [TipoDocumento.DANFE, TipoDocumento.DACTE]
    assert analise.canceladas == {chave, x.chave(55, 999)}
    assert [(i.caminho.name, i.motivo) for i in analise.ignorados] == [
        ("2.xml", 'mesmo documento de "1.xml"'),
        ("6.xml", "XML corrompido ou incompleto"),
        ("4.xml", "evento de cancelamento de um documento que não está na seleção"),
    ]
    assert passos == [1, 2, 3, 4, 5, 6]


def test_carta_de_correcao_usa_os_dados_da_nota(tmp_path):
    chave = x.chave(55, 1234)
    analise = analisar([x.gravar(tmp_path / "a.xml", x.evento(chave)), x.gravar(tmp_path / "b.xml", x.nfe())])
    completar_cartas_de_correcao(analise)

    carta = next(d for d in analise.documentos if d.tipo is TipoDocumento.DACCE)
    assert carta.emitente == "EMPRESA EXEMPLO LTDA"
    assert carta.endereco_emitente["cep"] == "01001-000"
    assert "RUA EXEMPLO, 100" in _texto_pdf(gerar_pdf(carta, OpcoesDocumento()))


def test_nomes_dos_pdfs(tmp_path):
    chave = x.chave(55, 1234)
    analise = analisar([
        x.gravar(tmp_path / "1.xml", x.nfe(numero=1234, serie=1)),
        x.gravar(tmp_path / "2.xml", x.nfe(numero=1234, serie=2)),
        x.gravar(tmp_path / "3.xml", x.nfe(numero=7, emitente="EXEMPLO S/S LTDA", cnpj="99888777000166")),
        x.gravar(tmp_path / "4.xml", x.evento(chave, sequencia=1)),
        x.gravar(tmp_path / "5.xml", x.evento(chave, sequencia=2)),
        x.gravar(tmp_path / "6.xml", x.nfse()),
    ])

    nomes = sorted(nomes_dos_pdfs(analise.documentos).values())

    assert nomes == [
        "DACCE 1234 - CNPJ 11222333000181 (XML).pdf",
        "DACCE 1234 - CNPJ 11222333000181 - correção 2 (XML).pdf",
        "DANFE 1234 série 1 - EMPRESA EXEMPLO LTDA (XML).pdf",
        "DANFE 1234 série 2 - EMPRESA EXEMPLO LTDA (XML).pdf",
        "DANFE 7 - EXEMPLO S-S LTDA (XML).pdf",
        "DANFSE 42 - EXEMPLO SERVICOS LTDA (XML).pdf",
    ]


def test_converte_marca_cancelada_e_junta(tmp_path):
    chave = x.chave(55, 1234)
    analise = analisar([
        x.gravar(tmp_path / "a.xml", x.nfe()),
        x.gravar(tmp_path / "b.xml", x.evento(chave, tipo="110111")),
        x.gravar(tmp_path / "c.xml", x.cte()),
        x.gravar(tmp_path / "d.xml", "lixo"),
    ])
    pasta = tmp_path / "UnePDF"
    passos = []

    resultado = converter_xmls(analise, pasta, juntar_em=pasta / "todos (XML).pdf", progresso=lambda *a: passos.append(a))

    assert [p.name for p in resultado.gerados] == [
        "DANFE 1234 - EMPRESA EXEMPLO LTDA (XML).pdf", "DACTE 567 - EXEMPLO TRANSPORTES LTDA (XML).pdf",
    ]
    assert resultado.marcados_cancelados == 1
    assert "CANCELADA" in _texto_pdf(resultado.gerados[0])
    assert "CANCELADA" not in _texto_pdf(resultado.gerados[1])
    assert [i.caminho.name for i in resultado.ignorados] == ["d.xml"]
    leitor = PdfReader(resultado.juntado)
    assert [m.title for m in leitor.outline] == ["DANFE 1234 - EMPRESA EXEMPLO LTDA", "DACTE 567 - EXEMPLO TRANSPORTES LTDA"]
    assert passos[-1] == (3, 3, "Juntando em todos (XML).pdf")

    # Converter de novo substitui os mesmos arquivos
    assert converter_xmls(analise, pasta).substituidos == 2


def test_opcoes_chegam_ao_pdf(tmp_path, monkeypatch):
    from brazilfiscalreport import danfe

    recebidas = []
    original = danfe.Danfe.__new__

    def espiar(cls, xml, config=None):
        recebidas.append(config)
        return original(cls, xml, config)

    monkeypatch.setattr(danfe.Danfe, "__new__", espiar)
    logo = tmp_path / "logo.png"
    from PIL import Image

    Image.new("RGB", (60, 30), "red").save(logo)
    documento = ler_xml(x.gravar(tmp_path / "a.xml", x.nfe()))

    gerar_pdf(documento, OpcoesDocumento(fonte=Fonte.COURIER, casas_decimais=2, canhoto_no_rodape=True), logo=logo.read_bytes())

    config = recebidas[0]
    assert config.font_type.value == "Courier"
    assert config.decimal_config.price_precision == 2
    assert config.receipt_pos.value == "bottom"
    assert config.logo == logo.read_bytes()


def test_marcar_todos_cancelados_e_logo_ausente(tmp_path):
    analise = analisar([x.gravar(tmp_path / "a.xml", x.nfe()), x.gravar(tmp_path / "b.xml", x.mdfe())])
    opcoes = OpcoesDocumento(marcar_todos_cancelados=True, logo=tmp_path / "nao existe.png")

    resultado = converter_xmls(analise, tmp_path / "UnePDF", opcoes)

    # O DAMDFE não tem marca de cancelada no leiaute oficial
    assert resultado.marcados_cancelados == 1
    assert "logo escolhida não foi encontrada" in resultado.ignorados[0].motivo
    assert len(resultado.gerados) == 2


def test_falha_do_gerador_nao_para_os_outros(tmp_path, monkeypatch):
    from unepdf.core import xml_pdf

    original = xml_pdf.gerar_pdf

    def gerar(documento, *args, **kwargs):
        if documento.tipo is TipoDocumento.DACTE:
            raise ValueError("tag inesperada")
        return original(documento, *args, **kwargs)

    monkeypatch.setattr(xml_pdf, "gerar_pdf", gerar)
    analise = analisar([x.gravar(tmp_path / "a.xml", x.nfe()), x.gravar(tmp_path / "b.xml", x.cte())])

    resultado = converter_xmls(analise, tmp_path / "UnePDF")

    assert len(resultado.gerados) == 1
    assert "não conseguiu montar" in resultado.ignorados[0].motivo


def test_nenhum_convertido_vira_erro_com_a_lista(tmp_path):
    analise = analisar([x.gravar(tmp_path / "a.xml", "lixo")])
    with pytest.raises(ErroUnePDF) as erro:
        converter_xmls(analise, tmp_path / "UnePDF")
    assert erro.value.ignorados[0].caminho.name == "a.xml"
    assert not (tmp_path / "UnePDF").exists()


def test_cancelar_mantem_os_pdfs_prontos(tmp_path):
    analise = analisar([x.gravar(tmp_path / f"{n}.xml", x.nfe(numero=n)) for n in (1, 2, 3)])
    cancelamento = Cancelamento()

    def progresso(atual, total, descricao):
        if atual == 2:
            cancelamento.cancelar()

    resultado = converter_xmls(analise, tmp_path / "UnePDF", progresso=progresso, cancelamento=cancelamento)

    assert len(resultado.gerados) == 2 and resultado.pendentes == 1
    assert resultado.cancelado
