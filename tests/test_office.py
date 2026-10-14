import threading
import time
from pathlib import Path

import pytest
from pypdf import PdfReader

from unepdf.core import office
from unepdf.core.erros import ErroUnePDF
from unepdf.core.office import Aplicativo, Motor, converter_documentos, nomes_dos_pdfs, preparar
from unepdf.core.progresso import Cancelamento
from unepdf.utils import programas
from unepdf.utils.programas import localizar_ghostscript, office_instalado

TODOS_COM_OFFICE = {app: Motor.OFFICE for app in Aplicativo}
requer_word_e_excel = pytest.mark.skipif(
    not (office_instalado("Word.Application") and office_instalado("Excel.Application")),
    reason="Microsoft Office não instalado",
)


@pytest.fixture
def office_falso(monkeypatch, criar_pdf):
    """Troca o Office por uma função que grava um PDF com uma página por letra do nome do arquivo."""
    convertidos = []

    def converter(instancia, caminho, saida, cancelamento):
        convertidos.append((instancia.app, caminho.name))
        criar_pdf(saida, paginas=1)

    monkeypatch.setattr(office, "_converter_um_com_office", converter)
    return convertidos


def _documento(caminho: Path, conteudo: str = "conteúdo") -> Path:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(conteudo, encoding="utf-8")
    return caminho


def test_nomes_dos_pdfs_diferenciam_nomes_repetidos(tmp_path):
    arquivos = [tmp_path / "relatorio.docx", tmp_path / "Relatorio.xlsx", tmp_path / "carta.rtf"]
    assert nomes_dos_pdfs(arquivos) == {
        arquivos[0]: "relatorio (docx).pdf",
        arquivos[1]: "Relatorio (xlsx).pdf",
        arquivos[2]: "carta.pdf",
    }


def test_preparar_separa_o_que_nao_pode_ser_convertido(tmp_path):
    arquivos = [tmp_path / n for n in ("a.docx", "~$a.docx", "b.xlsx", "c.pptx")]
    motores = {Aplicativo.WORD: Motor.OFFICE, Aplicativo.POWERPOINT: Motor.LIBREOFFICE}

    resultado = preparar(arquivos, motores)

    assert resultado.arquivos == [
        (arquivos[0], Aplicativo.WORD, Motor.OFFICE),
        (arquivos[3], Aplicativo.POWERPOINT, Motor.LIBREOFFICE),
    ]
    assert [(i.caminho.name, i.motivo) for i in resultado.ignorados] == [
        ("~$a.docx", "arquivo temporário do Office"),
        ("b.xlsx", "o Excel não está instalado (nem o LibreOffice)"),
    ]


def test_motores_preferem_o_office_e_usam_o_libreoffice_no_resto(monkeypatch, tmp_path):
    monkeypatch.setattr(office, "office_instalado", lambda prog_id: prog_id == "Word.Application")
    monkeypatch.setattr(office, "localizar_libreoffice", lambda: tmp_path / "soffice.com")
    assert office.motores_disponiveis() == {
        Aplicativo.WORD: Motor.OFFICE, Aplicativo.EXCEL: Motor.LIBREOFFICE, Aplicativo.POWERPOINT: Motor.LIBREOFFICE,
    }

    monkeypatch.setattr(office, "office_instalado", lambda prog_id: False)
    monkeypatch.setattr(office, "localizar_libreoffice", lambda: None)
    assert "libreoffice.org" in office.disponivel()


def test_localizar_libreoffice_pela_pasta_padrao(tmp_path, monkeypatch):
    executavel = tmp_path / "LibreOffice" / "program" / "soffice.com"
    executavel.parent.mkdir(parents=True)
    executavel.write_bytes(b"")
    monkeypatch.setattr(programas, "_libreoffice_do_registro", lambda: [])
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    assert programas.localizar_libreoffice() == executavel


def test_converte_em_lote_e_junta(tmp_path, office_falso):
    arquivos = [_documento(tmp_path / n) for n in ("carta.docx", "tabela.xlsx", "slides.pptx")]
    pasta = tmp_path / "UnePDF"
    passos = []

    resultado = converter_documentos(
        preparar(arquivos, TODOS_COM_OFFICE), pasta, juntar_em=pasta / "todos.pdf", progresso=lambda *a: passos.append(a)
    )

    assert [p.name for p in resultado.gerados] == ["carta.pdf", "tabela.pdf", "slides.pdf"]
    assert office_falso == [(Aplicativo.WORD, "carta.docx"), (Aplicativo.EXCEL, "tabela.xlsx"),
                            (Aplicativo.POWERPOINT, "slides.pptx")]
    assert [m.title for m in PdfReader(resultado.juntado).outline] == ["carta", "tabela", "slides"]
    assert passos[-1] == (4, 4, "Juntando em todos.pdf")
    assert converter_documentos(preparar(arquivos, TODOS_COM_OFFICE), pasta).substituidos == 3


def test_problemas_viram_ignorados_sem_parar_o_lote(tmp_path, office_falso, monkeypatch):
    vazio = tmp_path / "vazio.docx"
    vazio.write_bytes(b"")
    protegido = tmp_path / "protegido.xlsx"
    protegido.write_bytes(office.ASSINATURA_PROTEGIDO + b"resto")
    ok = _documento(tmp_path / "ok.docx")
    falha = _documento(tmp_path / "falha.pptx")
    original = office._converter_um_com_office

    def converter(instancia, caminho, saida, cancelamento):
        if caminho == falha:
            raise RuntimeError("erro interno")
        original(instancia, caminho, saida, cancelamento)

    monkeypatch.setattr(office, "_converter_um_com_office", converter)

    resultado = converter_documentos(preparar([vazio, protegido, ok, falha], TODOS_COM_OFFICE), tmp_path / "UnePDF")

    assert [p.name for p in resultado.gerados] == ["ok.pdf"]
    assert [(i.caminho.name, i.motivo) for i in resultado.ignorados] == [
        ("vazio.docx", "arquivo vazio (0 KB)"),
        ("protegido.xlsx", "protegido por senha"),
        ("falha.pptx", "falha inesperada (detalhes no registro)"),
    ]


def test_nenhum_convertido_vira_erro(tmp_path):
    vazio = tmp_path / "vazio.docx"
    vazio.write_bytes(b"")
    with pytest.raises(ErroUnePDF) as erro:
        converter_documentos(preparar([vazio], TODOS_COM_OFFICE), tmp_path / "UnePDF")
    assert erro.value.ignorados[0].motivo == "arquivo vazio (0 KB)"


def test_cancelar_mantem_os_pdfs_prontos(tmp_path, office_falso):
    arquivos = [_documento(tmp_path / f"{n}.docx") for n in (1, 2, 3)]
    cancelamento = Cancelamento()

    def progresso(atual, total, descricao):
        if atual == 2:
            cancelamento.cancelar()

    resultado = converter_documentos(preparar(arquivos, TODOS_COM_OFFICE), tmp_path / "UnePDF", progresso=progresso,
                                     cancelamento=cancelamento)

    # O documento que já estava em andamento termina; os seguintes ficam pendentes
    assert [p.name for p in resultado.gerados] == ["1.pdf", "2.pdf"]
    assert resultado.pendentes == 1


class _InstanciaFalsa:
    def __init__(self):
        self.encerrada = threading.Event()

    def encerrar_a_forca(self):
        self.encerrada.set()


def test_vigia_encerra_o_office_quando_passa_do_limite():
    instancia = _InstanciaFalsa()
    with office._vigia(instancia, None, limite=0.1) as motivo:
        assert instancia.encerrada.wait(5)
    assert motivo == ["tempo"]


def test_vigia_encerra_o_office_ao_cancelar():
    instancia, cancelamento = _InstanciaFalsa(), Cancelamento()
    with office._vigia(instancia, cancelamento, limite=60) as motivo:
        cancelamento.cancelar()
        assert instancia.encerrada.wait(5)
    assert motivo == ["cancelado"]


def test_vigia_nao_faz_nada_se_termina_a_tempo():
    instancia = _InstanciaFalsa()
    with office._vigia(instancia, Cancelamento(), limite=60) as motivo:
        time.sleep(0.05)
    assert motivo == [] and not instancia.encerrada.is_set()


def test_libreoffice_converte_e_explica_falhas(tmp_path, monkeypatch, criar_pdf):
    comandos = []

    class ProcessoFalso:
        def __init__(self, comando, **opcoes):
            comandos.append((comando, opcoes))
            pasta = Path(comando[comando.index("--outdir") + 1])
            origem = Path(comando[-1])
            if origem.stem != "quebrado":
                criar_pdf(pasta / f"{origem.stem}.pdf")

        def poll(self):
            return 0

    monkeypatch.setattr(office, "localizar_libreoffice", lambda: tmp_path / "soffice.com")
    monkeypatch.setattr(office.subprocess, "Popen", ProcessoFalso)
    motores = {app: Motor.LIBREOFFICE for app in Aplicativo}
    arquivos = [_documento(tmp_path / "planilha.ods"), _documento(tmp_path / "quebrado.odt")]

    resultado = converter_documentos(preparar(arquivos, motores), tmp_path / "UnePDF")

    assert [p.name for p in resultado.gerados] == ["planilha.pdf"]
    assert "LibreOffice não conseguiu converter" in resultado.ignorados[0].motivo
    comando, opcoes = comandos[0]
    assert "--headless" in comando and any(c.startswith("-env:UserInstallation=file:") for c in comando)
    assert opcoes["creationflags"] == office.subprocess.CREATE_NO_WINDOW


# Com o Microsoft Office de verdade (pulados onde ele não está instalado)

@requer_word_e_excel
def test_converte_com_o_office_de_verdade(tmp_path):
    carta = tmp_path / "carta.rtf"
    carta.write_text(r"{\rtf1\ansi\deff0 {\fonttbl {\f0 Arial;}}\f0\fs24 Contrato de exemplo\par}", encoding="ascii")
    tabela = _documento(tmp_path / "tabela.csv", "produto;valor\nPRODUTO EXEMPLO;100\n")
    quebrado = tmp_path / "quebrado.docx"
    quebrado.write_bytes(b"PK isto nao e um docx")

    resultado = converter_documentos(preparar([carta, tabela, quebrado], TODOS_COM_OFFICE), tmp_path / "UnePDF")

    assert [p.name for p in resultado.gerados] == ["carta.pdf", "tabela.pdf"]
    assert "Contrato de exemplo" in PdfReader(resultado.gerados[0]).pages[0].extract_text()
    assert "PRODUTO EXEMPLO" in PdfReader(resultado.gerados[1]).pages[0].extract_text()
    assert "não conseguiu abrir" in resultado.ignorados[0].motivo


@requer_word_e_excel
@pytest.mark.skipif(localizar_ghostscript() is None, reason="Ghostscript não instalado")
def test_office_com_pdfa(tmp_path):
    from unepdf.core.pdfa import conferir_pdfa

    carta = tmp_path / "carta.rtf"
    carta.write_text(r"{\rtf1\ansi Carta de exemplo\par}", encoding="ascii")

    resultado = converter_documentos(preparar([carta], TODOS_COM_OFFICE), tmp_path / "UnePDF", pdfa=True)

    assert conferir_pdfa(resultado.gerados[0], 2)


class _ExcelFalso:
    """Imita o Excel: só aceita a impressora com a palavra do idioma dele ("em")."""

    def __init__(self):
        self._impressora = "IMPRESSORA DE REDE em Ne00:"
        self.trocas = []

    @property
    def ActivePrinter(self):
        return self._impressora

    @ActivePrinter.setter
    def ActivePrinter(self, nome):
        self.trocas.append(nome)
        if " em " not in nome:
            raise ValueError("nome de impressora inválido")
        self._impressora = nome


def test_excel_usa_a_impressora_de_pdf_do_windows(monkeypatch):
    monkeypatch.setattr(office, "impressora_pdf_do_windows", lambda: ("Microsoft Print to PDF", "Ne02:"))
    instancia = office._InstanciaOffice(Aplicativo.EXCEL)
    instancia.com = _ExcelFalso()

    office._usar_impressora_virtual(instancia)
    office._usar_impressora_virtual(instancia)

    assert instancia.com.ActivePrinter == "Microsoft Print to PDF em Ne02:"
    # A segunda vez já usa o nome que deu certo, sem tentar de novo
    assert instancia.com.trocas == ["Microsoft Print to PDF em Ne02:", "Microsoft Print to PDF em Ne02:"]


def test_sem_impressora_de_pdf_mantem_a_do_excel(monkeypatch):
    monkeypatch.setattr(office, "impressora_pdf_do_windows", lambda: None)
    instancia = office._InstanciaOffice(Aplicativo.EXCEL)
    instancia.com = _ExcelFalso()

    office._usar_impressora_virtual(instancia)

    assert instancia.com.trocas == [] and instancia.impressora is False
