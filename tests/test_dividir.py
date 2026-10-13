import pytest
from conftest import numeros_das_paginas
from pypdf import PdfReader, PdfWriter

from unepdf.core import dividir
from unepdf.core.erros import ErroUnePDF, OperacaoCancelada
from unepdf.core.progresso import Cancelamento
from unepdf.core.unir import unir


def _arquivos(pasta):
    return sorted(p.name for p in pasta.iterdir())


def test_por_intervalos(tmp_path, criar_pdf):
    origem = criar_pdf(tmp_path / "contrato.pdf", paginas=6, identificar=True)
    pasta = tmp_path / "saida" / "contrato - dividido"

    resultado = dividir.dividir_por_intervalos(origem, "1-2, 4, 5-", pasta)

    assert (resultado.arquivos, resultado.paginas) == (3, 5)
    assert _arquivos(pasta) == [
        "contrato - página 4.pdf",
        "contrato - páginas 1-2.pdf",
        "contrato - páginas 5-6.pdf",
    ]
    assert numeros_das_paginas(pasta / "contrato - páginas 5-6.pdf") == [5, 6]


def test_a_cada_n_paginas(tmp_path, criar_pdf):
    origem = criar_pdf(tmp_path / "a.pdf", paginas=5, identificar=True)
    pasta = tmp_path / "a - dividido"

    resultado = dividir.dividir_a_cada(origem, 2, pasta)

    assert resultado.arquivos == 3
    assert numeros_das_paginas(pasta / "a - página 5.pdf") == [5]
    assert numeros_das_paginas(pasta / "a - páginas 3-4.pdf") == [3, 4]


def test_a_cada_zero_e_erro(tmp_path, criar_pdf):
    origem = criar_pdf(tmp_path / "a.pdf")
    with pytest.raises(ErroUnePDF, match="pelo menos 1"):
        dividir.dividir_a_cada(origem, 0, tmp_path / "x")


def test_por_marcadores_devolve_os_arquivos_unidos(tmp_path, criar_pdf):
    originais = [criar_pdf(tmp_path / f"NF {i}.pdf", paginas=i) for i in (1, 2, 3)]
    unido = unir(originais, tmp_path / "UNIFICADO" / "u.pdf").destino
    pasta = tmp_path / "UNIFICADO" / "u - dividido"

    resultado = dividir.dividir_por_marcadores(unido, pasta)

    assert _arquivos(pasta) == ["NF 1.pdf", "NF 2.pdf", "NF 3.pdf"]
    assert [len(PdfReader(pasta / f"NF {i}.pdf").pages) for i in (1, 2, 3)] == [1, 2, 3]
    assert resultado.paginas == 6


def test_paginas_antes_do_primeiro_marcador_entram_no_primeiro_arquivo(tmp_path):
    escritor = PdfWriter()
    for _ in range(4):
        escritor.add_blank_page(595, 842)
    escritor.add_outline_item("Capítulo A", 1)
    escritor.add_outline_item("Capítulo B", 3)
    origem = tmp_path / "livro.pdf"
    escritor.write(origem)

    dividir.dividir_por_marcadores(origem, tmp_path / "d")

    assert [len(PdfReader(tmp_path / "d" / n).pages) for n in ("Capítulo A.pdf", "Capítulo B.pdf")] == [3, 1]


def test_sem_marcadores_e_erro(tmp_path, criar_pdf):
    origem = criar_pdf(tmp_path / "a.pdf", paginas=2)
    with pytest.raises(ErroUnePDF, match="não tem marcadores"):
        dividir.dividir_por_marcadores(origem, tmp_path / "d")


def test_nomes_repetidos_longos_ou_invalidos(tmp_path):
    escritor = PdfWriter()
    for _ in range(4):
        escritor.add_blank_page(595, 842)
    for pagina, titulo in enumerate(["Nota", "nota", "A/B: C?", "x" * 300]):
        escritor.add_outline_item(titulo, pagina)
    origem = tmp_path / "m.pdf"
    escritor.write(origem)

    dividir.dividir_por_marcadores(origem, tmp_path / "d")

    nomes = _arquivos(tmp_path / "d")
    assert "Nota.pdf" in nomes and "nota (2).pdf" in nomes
    assert "A-B- C-.pdf" in nomes
    assert ("x" * dividir.TAMANHO_MAXIMO_NOME + ".pdf") in nomes


def test_refazer_substitui_a_pasta_inteira(tmp_path, criar_pdf):
    origem = criar_pdf(tmp_path / "a.pdf", paginas=4)
    pasta = tmp_path / "a - dividido"
    dividir.dividir_a_cada(origem, 1, pasta)

    resultado = dividir.dividir_a_cada(origem, 2, pasta)

    assert resultado.substituiu_anterior
    assert _arquivos(pasta) == ["a - páginas 1-2.pdf", "a - páginas 3-4.pdf"]
    assert _arquivos(tmp_path) == ["a - dividido", "a.pdf"]


def test_falha_no_meio_preserva_a_pasta_anterior(tmp_path, criar_pdf, monkeypatch):
    origem = criar_pdf(tmp_path / "a.pdf", paginas=4)
    pasta = tmp_path / "a - dividido"
    dividir.dividir_a_cada(origem, 4, pasta)
    chamadas = []

    def gravacao_que_falha(self, arquivo):
        chamadas.append(1)
        if len(chamadas) == 2:
            raise OSError(28, "Espaço insuficiente no disco")
        arquivo.write(b"%PDF-1.4")

    monkeypatch.setattr(PdfWriter, "write", gravacao_que_falha)

    with pytest.raises(ErroUnePDF, match="Espaço insuficiente"):
        dividir.dividir_a_cada(origem, 1, pasta)

    assert _arquivos(pasta) == ["a - páginas 1-4.pdf"]
    assert _arquivos(tmp_path) == ["a - dividido", "a.pdf"]


def test_cancelamento_preserva_a_pasta_anterior(tmp_path, criar_pdf):
    origem = criar_pdf(tmp_path / "a.pdf", paginas=2)
    pasta = tmp_path / "a - dividido"
    dividir.dividir_a_cada(origem, 2, pasta)
    cancelamento = Cancelamento()
    cancelamento.cancelar()

    with pytest.raises(OperacaoCancelada):
        dividir.dividir_a_cada(origem, 1, pasta, cancelamento=cancelamento)

    assert _arquivos(pasta) == ["a - páginas 1-2.pdf"]


def test_relata_progresso_por_arquivo(tmp_path, criar_pdf):
    origem = criar_pdf(tmp_path / "a.pdf", paginas=2)
    chamadas = []
    dividir.dividir_a_cada(origem, 1, tmp_path / "d", lambda *a: chamadas.append(a))
    assert chamadas == [(1, 2, "a - página 1.pdf"), (2, 2, "a - página 2.pdf")]
