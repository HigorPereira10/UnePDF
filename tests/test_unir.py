import sys

import pytest
from pypdf import PdfReader

from unepdf.core.erros import ErroUnePDF, OperacaoCancelada
from unepdf.core.localizador import listar_pdfs_da_pasta
from unepdf.core.nomenclatura import destino_padrao
from unepdf.core.progresso import Cancelamento
from unepdf.core.unir import unir


def test_mantem_todas_as_paginas_e_cria_marcador_por_arquivo(tmp_path, criar_pdf):
    criar_pdf(tmp_path / "1.pdf", paginas=1)
    criar_pdf(tmp_path / "2.pdf", paginas=3)
    destino = destino_padrao(tmp_path)

    resultado = unir(listar_pdfs_da_pasta(tmp_path), destino)

    assert (resultado.arquivos, resultado.paginas) == (2, 4)
    leitor = PdfReader(destino)
    assert len(leitor.pages) == 4
    assert [m.title for m in leitor.outline] == ["1", "2"]
    # Cada marcador aponta para a primeira página do seu arquivo
    assert [leitor.get_destination_page_number(m) for m in leitor.outline] == [0, 1]
    assert leitor.page_mode == "/UseOutlines"


def test_pula_arquivos_invalidos_e_informa_motivo(tmp_path, criar_pdf):
    criar_pdf(tmp_path / "ok.pdf")
    criar_pdf(tmp_path / "permissao.pdf", senha_dono="dono", algoritmo="AES-256")
    (tmp_path / "vazio.pdf").write_bytes(b"")
    (tmp_path / "quebrado.pdf").write_bytes(b"isto nao e um pdf")
    criar_pdf(tmp_path / "senha.pdf", senha="123")

    resultado = unir(listar_pdfs_da_pasta(tmp_path), destino_padrao(tmp_path))

    motivos = {i.caminho.name: i.motivo for i in resultado.ignorados}
    assert resultado.arquivos == 2
    assert motivos == {
        "vazio.pdf": "arquivo vazio (0 KB)",
        "quebrado.pdf": "arquivo corrompido ou ilegível",
        "senha.pdf": "protegido por senha",
    }


def test_nao_altera_os_arquivos_de_origem(tmp_path, criar_pdf):
    origens = [criar_pdf(tmp_path / "1.pdf"), criar_pdf(tmp_path / "2.pdf", senha_dono="dono")]
    conteudos_antes = [p.read_bytes() for p in origens]

    unir(origens, destino_padrao(tmp_path))

    assert [p.read_bytes() for p in origens] == conteudos_antes


def test_substitui_resultado_anterior(tmp_path, criar_pdf):
    criar_pdf(tmp_path / "1.pdf")
    destino = destino_padrao(tmp_path)

    primeiro = unir(listar_pdfs_da_pasta(tmp_path), destino)
    criar_pdf(tmp_path / "2.pdf")
    segundo = unir(listar_pdfs_da_pasta(tmp_path), destino)

    assert not primeiro.substituiu_anterior
    assert segundo.substituiu_anterior
    assert len(PdfReader(destino).pages) == 2
    assert not list(destino.parent.glob("*.tmp"))  # sem sobra de arquivo temporário


def test_resultado_nao_entra_na_proxima_uniao(tmp_path, criar_pdf):
    criar_pdf(tmp_path / "1.pdf")
    unir(listar_pdfs_da_pasta(tmp_path), destino_padrao(tmp_path))

    assert [p.name for p in listar_pdfs_da_pasta(tmp_path)] == ["1.pdf"]


def test_erro_quando_nenhum_pdf_valido(tmp_path):
    (tmp_path / "vazio.pdf").write_bytes(b"")
    destino = destino_padrao(tmp_path)

    with pytest.raises(ErroUnePDF) as erro:
        unir(listar_pdfs_da_pasta(tmp_path), destino)

    assert [i.caminho.name for i in erro.value.ignorados] == ["vazio.pdf"]
    assert not destino.exists()


def test_erro_quando_lista_vazia(tmp_path):
    with pytest.raises(ErroUnePDF, match="Nenhum PDF"):
        unir([], destino_padrao(tmp_path))


def test_relata_progresso_com_passo_de_gravacao(tmp_path, criar_pdf):
    for nome in ("a.pdf", "b.pdf"):
        criar_pdf(tmp_path / nome)
    destino = destino_padrao(tmp_path)
    chamadas = []

    unir(listar_pdfs_da_pasta(tmp_path), destino, lambda *a: chamadas.append(a))

    assert chamadas == [(1, 3, "a.pdf"), (2, 3, "b.pdf"), (3, 3, f"Gravando {destino.name}")]


def test_cancelamento_no_meio_nao_gera_arquivo(tmp_path, criar_pdf):
    for nome in ("a.pdf", "b.pdf", "c.pdf"):
        criar_pdf(tmp_path / nome)
    destino = destino_padrao(tmp_path)
    cancelamento = Cancelamento()

    def progresso(atual, total, nome):
        if atual == 2:
            cancelamento.cancelar()

    with pytest.raises(OperacaoCancelada):
        unir(listar_pdfs_da_pasta(tmp_path), destino, progresso, cancelamento)

    assert not destino.parent.exists()


def test_cancelamento_preserva_resultado_anterior(tmp_path, criar_pdf):
    criar_pdf(tmp_path / "a.pdf")
    destino = destino_padrao(tmp_path)
    unir(listar_pdfs_da_pasta(tmp_path), destino)
    anterior = destino.read_bytes()
    cancelamento = Cancelamento()
    cancelamento.cancelar()

    with pytest.raises(OperacaoCancelada):
        unir(listar_pdfs_da_pasta(tmp_path), destino, cancelamento=cancelamento)

    assert destino.read_bytes() == anterior


@pytest.mark.skipif(sys.platform != "win32", reason="o bloqueio de arquivo aberto é do Windows")
def test_destino_aberto_em_outro_programa(tmp_path, criar_pdf):
    criar_pdf(tmp_path / "a.pdf")
    destino = destino_padrao(tmp_path)
    unir(listar_pdfs_da_pasta(tmp_path), destino)
    anterior = destino.read_bytes()

    # Enquanto o arquivo está aberto, o Windows não deixa substituí-lo (como num leitor de PDF)
    with open(destino, "rb"):
        with pytest.raises(ErroUnePDF, match="aberto em outro programa"):
            unir(listar_pdfs_da_pasta(tmp_path), destino)

    assert destino.read_bytes() == anterior
    assert not list(destino.parent.glob("*.tmp"))


def test_pasta_de_destino_impossivel_de_criar(tmp_path, criar_pdf):
    origem = criar_pdf(tmp_path / "a.pdf")
    bloqueio = tmp_path / "bloqueio"
    bloqueio.write_text("x")

    with pytest.raises(ErroUnePDF, match="Não foi possível criar a pasta de destino"):
        unir([origem], bloqueio / "UnePDF" / "final.pdf")


def test_falha_inesperada_na_gravacao_vira_erro_amigavel(tmp_path, criar_pdf, monkeypatch):
    origem = criar_pdf(tmp_path / "a.pdf")
    destino = destino_padrao(tmp_path)

    def gravacao_quebrada(self, arquivo):
        raise KeyError("objeto ausente")

    monkeypatch.setattr("pypdf.PdfWriter.write", gravacao_quebrada)

    with pytest.raises(ErroUnePDF, match="conteúdo danificado"):
        unir([origem], destino)
    assert not destino.exists()
    assert not list(destino.parent.glob("*.tmp"))


def test_pula_repetidos_pelo_conteudo_mesmo_com_outro_nome(tmp_path, criar_pdf):
    criar_pdf(tmp_path / "nota.pdf", paginas=2)
    criar_pdf(tmp_path / "nota (1).pdf", paginas=2)
    criar_pdf(tmp_path / "outra.pdf", paginas=1)
    arquivos = [tmp_path / "nota.pdf", tmp_path / "nota (1).pdf", tmp_path / "outra.pdf"]

    resultado = unir(arquivos, tmp_path / "u.pdf", pular_repetidos=True)

    assert (resultado.arquivos, resultado.paginas) == (2, 3)
    assert [(i.caminho.name, i.motivo) for i in resultado.ignorados] == [
        ("nota (1).pdf", 'conteúdo repetido, igual ao de "nota.pdf"'),
    ]
    # Sem a opção, os repetidos entram normalmente
    assert unir(arquivos, tmp_path / "v.pdf").arquivos == 3


def test_capa_lista_os_arquivos_com_link_para_cada_um(tmp_path, criar_pdf):
    arquivos = [criar_pdf(tmp_path / "a.pdf", paginas=2), criar_pdf(tmp_path / "b.pdf", paginas=3)]
    destino = tmp_path / "UnePDF" / "Janeiro - UNIFICADO.pdf"

    resultado = unir(arquivos, destino, capa=True)

    leitor = PdfReader(destino)
    assert resultado.paginas == len(leitor.pages) == 6
    assert [m.title for m in leitor.outline] == ["Índice", "a", "b"]
    assert [leitor.get_destination_page_number(m) for m in leitor.outline] == [0, 1, 3]
    texto = leitor.pages[0].extract_text()
    assert "Janeiro - UNIFICADO" in texto and "2 arquivos, 6 páginas" in texto
    assert "1. a" in texto and "2. b" in texto
    links = [a.get_object() for a in leitor.pages[0]["/Annots"]]
    assert [leitor.get_page_number(link["/Dest"][0].get_object()) for link in links] == [1, 3]


def test_indice_longo_ocupa_varias_paginas(tmp_path, criar_pdf):
    from unepdf.core.capa import LINHAS_PRIMEIRA, paginas_da_capa

    origem = criar_pdf(tmp_path / "base.pdf")
    arquivos = []
    for numero in range(1, LINHAS_PRIMEIRA + 6):
        destino = tmp_path / f"{numero}.pdf"
        destino.write_bytes(origem.read_bytes())
        arquivos.append(destino)

    unir(arquivos, tmp_path / "u.pdf", capa=True)

    leitor = PdfReader(tmp_path / "u.pdf")
    assert paginas_da_capa(len(arquivos)) == 2
    assert len(leitor.pages) == len(arquivos) + 2
    # O primeiro arquivo começa depois das duas páginas do índice
    assert leitor.get_destination_page_number(leitor.outline[1]) == 2
    assert "Índice (continuação)" in leitor.pages[1].extract_text()
    assert f"{len(arquivos)}. {len(arquivos)}" in leitor.pages[1].extract_text()


def test_nome_longo_e_cortado_na_capa():
    from unepdf.core.capa import encurtar
    from unepdf.core.carimbo import largura_texto

    nome = "NF 0001 - EMPRESA EXEMPLO LTDA - " + "servicos " * 20
    curto = encurtar(nome, 10.5, 300)
    assert curto.endswith("...") and largura_texto(curto, 10.5) <= 300
    assert encurtar("a.pdf", 10.5, 300) == "a.pdf"


def test_ordenar_por_nome_ou_data(tmp_path, criar_pdf):
    import os

    from unepdf.core.localizador import OrdemArquivos, ordenar

    arquivos = [criar_pdf(tmp_path / nome) for nome in ("10.pdf", "2.pdf", "1.pdf")]
    for segundos, caminho in zip((100, 300, 200), arquivos):
        os.utime(caminho, (segundos, segundos))

    assert [p.name for p in ordenar(arquivos, OrdemArquivos.NOME)] == ["1.pdf", "2.pdf", "10.pdf"]
    assert [p.name for p in ordenar(arquivos, OrdemArquivos.DATA)] == ["10.pdf", "1.pdf", "2.pdf"]
    # Sem data conhecida, o arquivo vai para o fim
    datas = {arquivos[1]: 1.0, arquivos[2]: 1.0}
    assert [p.name for p in ordenar(arquivos, "data", datas)] == ["1.pdf", "2.pdf", "10.pdf"]
