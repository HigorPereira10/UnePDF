import pytest
from conftest import numeros_das_paginas
from pypdf import PdfReader

from unepdf.core.erros import ErroUnePDF, OperacaoCancelada
from unepdf.core.paginas import (
    descrever_intervalos,
    extrair,
    girar,
    interpretar_grupos,
    interpretar_paginas,
    remover,
    reordenar,
    reorganizar,
)
from unepdf.core.progresso import Cancelamento


@pytest.mark.parametrize("texto,grupos", [
    ("1-3, 5, 8-10", [[0, 1, 2], [4], [7, 8, 9]]),
    ("8-", [[7, 8, 9]]),
    ("-2", [[0, 1]]),
    (" 4 ; 2 ", [[3], [1]]),
    ("3 - 4", [[2, 3]]),
    ("10", [[9]]),
])
def test_interpretar_grupos(texto, grupos):
    assert interpretar_grupos(texto, 10) == grupos


@pytest.mark.parametrize("texto,trecho", [
    ("", "Informe as páginas"),
    ("  ,  ", "Informe as páginas"),
    ("11", "A página 11 não existe"),
    ("0", "A página 0 não existe"),
    ("5-3", "está invertido"),
    ("abc", 'Não entendi "abc"'),
    ("1-2-3", 'Não entendi "1-2-3"'),
    ("-", 'Não entendi "-"'),
])
def test_interpretar_grupos_com_erro(texto, trecho):
    with pytest.raises(ErroUnePDF, match=trecho):
        interpretar_grupos(texto, 10)


def test_interpretar_paginas_sem_repeticoes_na_ordem_digitada():
    assert interpretar_paginas("5, 1-3, 2", 10) == [4, 0, 1, 2]


def test_extrair_na_ordem_indicada(tmp_path, criar_pdf):
    origem = criar_pdf(tmp_path / "a.pdf", paginas=5, identificar=True)
    conteudo_antes = origem.read_bytes()

    resultado = extrair(origem, [4, 0, 2], tmp_path / "saida" / "a - extraido.pdf")

    assert numeros_das_paginas(resultado.destino) == [5, 1, 3]
    assert resultado.paginas == 3
    assert origem.read_bytes() == conteudo_antes


def test_remover(tmp_path, criar_pdf):
    origem = criar_pdf(tmp_path / "a.pdf", paginas=5, identificar=True)
    resultado = remover(origem, [1, 3], tmp_path / "r.pdf")
    assert numeros_das_paginas(resultado.destino) == [1, 3, 5]


def test_remover_todas_e_erro(tmp_path, criar_pdf):
    origem = criar_pdf(tmp_path / "a.pdf", paginas=2)
    with pytest.raises(ErroUnePDF, match="ficaria vazio"):
        remover(origem, [0, 1], tmp_path / "r.pdf")


def test_girar_algumas_paginas(tmp_path, criar_pdf):
    origem = criar_pdf(tmp_path / "a.pdf", paginas=3)
    resultado = girar(origem, 90, tmp_path / "g.pdf", paginas=[1])
    assert [p.rotation for p in PdfReader(resultado.destino).pages] == [0, 90, 0]


def test_girar_todas_e_rotacao_acumula_com_a_original(tmp_path, criar_pdf):
    origem = criar_pdf(tmp_path / "a.pdf", paginas=2)
    girado = girar(origem, 270, tmp_path / "g1.pdf").destino
    de_novo = girar(girado, 180, tmp_path / "g2.pdf").destino
    assert [p.rotation for p in PdfReader(de_novo).pages] == [90, 90]


def test_reordenar(tmp_path, criar_pdf):
    origem = criar_pdf(tmp_path / "a.pdf", paginas=3, identificar=True)
    resultado = reordenar(origem, [2, 0, 1], tmp_path / "o.pdf")
    assert numeros_das_paginas(resultado.destino) == [3, 1, 2]


@pytest.mark.parametrize("ordem", [[0, 1], [0, 0, 1], [0, 1, 3]])
def test_reordenar_exige_cada_pagina_uma_vez(tmp_path, criar_pdf, ordem):
    origem = criar_pdf(tmp_path / "a.pdf", paginas=3)
    with pytest.raises(ErroUnePDF, match="exatamente uma vez"):
        reordenar(origem, ordem, tmp_path / "o.pdf")


def test_reorganizar_combina_ordem_rotacao_e_remocao(tmp_path, criar_pdf):
    origem = criar_pdf(tmp_path / "a.pdf", paginas=4, identificar=True)

    resultado = reorganizar(origem, [(3, 90), (0, 0), (1, -90)], tmp_path / "o.pdf")

    leitor = PdfReader(resultado.destino)
    assert numeros_das_paginas(resultado.destino) == [4, 1, 2]
    assert [p.rotation for p in leitor.pages] == [90, 0, 270]


@pytest.mark.parametrize("plano,trecho", [
    ([], "pelo menos uma página"),
    ([(5, 0)], "A página 6 não existe"),
    ([(0, 45)], "múltipla de 90"),
])
def test_reorganizar_valida_o_plano(tmp_path, criar_pdf, plano, trecho):
    origem = criar_pdf(tmp_path / "a.pdf", paginas=2)
    with pytest.raises(ErroUnePDF, match=trecho):
        reorganizar(origem, plano, tmp_path / "o.pdf")


def test_aceita_pdf_com_senha_so_de_permissao(tmp_path, criar_pdf):
    origem = criar_pdf(tmp_path / "a.pdf", paginas=2, senha_dono="dono", algoritmo="AES-256")
    assert extrair(origem, [1], tmp_path / "e.pdf").paginas == 1


@pytest.mark.parametrize("conteudo,trecho", [(b"", "vazio"), (b"lixo", "corrompido")])
def test_origem_invalida_vira_erro_amigavel(tmp_path, conteudo, trecho):
    origem = tmp_path / "ruim.pdf"
    origem.write_bytes(conteudo)
    with pytest.raises(ErroUnePDF, match=f'"ruim.pdf": .*{trecho}'):
        extrair(origem, [0], tmp_path / "e.pdf")


def test_cancelamento_nao_gera_arquivo(tmp_path, criar_pdf):
    origem = criar_pdf(tmp_path / "a.pdf", paginas=3)
    cancelamento = Cancelamento()
    cancelamento.cancelar()

    with pytest.raises(OperacaoCancelada):
        extrair(origem, [0, 1], tmp_path / "e.pdf", cancelamento=cancelamento)
    assert not (tmp_path / "e.pdf").exists()


def test_relata_progresso(tmp_path, criar_pdf):
    origem = criar_pdf(tmp_path / "a.pdf", paginas=2)
    chamadas = []
    extrair(origem, [1, 0], tmp_path / "e.pdf", lambda *a: chamadas.append(a))
    assert chamadas == [(1, 3, "Página 2"), (2, 3, "Página 1"), (3, 3, "Gravando e.pdf")]


@pytest.mark.parametrize("indices,texto", [
    ([], ""),
    ([0], "1"),
    ([0, 1, 2, 4], "1-3, 5"),
    ([9, 7, 8, 0], "1, 8-10"),
    ([3, 3, 4], "4-5"),
])
def test_descrever_intervalos(indices, texto):
    assert descrever_intervalos(indices) == texto
