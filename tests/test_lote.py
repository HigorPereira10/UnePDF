from datetime import datetime

import pytest
from pypdf import PdfReader

from unepdf.core import lote
from unepdf.core.erros import ErroUnePDF, OperacaoCancelada
from unepdf.core.lote import procurar_pastas, texto_relatorio, unir_em_lote
from unepdf.core.nomenclatura import Perfil
from unepdf.core.progresso import Cancelamento


@pytest.fixture
def raiz(tmp_path, criar_pdf):
    """Estrutura no formato do perfil Notas fiscais, com pastas que devem ficar de fora."""
    raiz = tmp_path / "Notas"
    criar_pdf(raiz / "solto.pdf")
    criar_pdf(raiz / "DANFE" / "0001-EMPRESA EXEMPLO LTDA" / "012026" / "1.pdf", paginas=2)
    criar_pdf(raiz / "DANFE" / "0001-EMPRESA EXEMPLO LTDA" / "012026" / "2.pdf")
    criar_pdf(raiz / "DANFE" / "0001-EMPRESA EXEMPLO LTDA" / "022026" / "1.pdf")
    criar_pdf(raiz / "DANFE" / "0001-EMPRESA EXEMPLO LTDA" / "012026" / "UnePDF" / "velho.pdf")
    criar_pdf(raiz / "DANFE" / "0001-EMPRESA EXEMPLO LTDA" / "012026" / "UnePDF" / "sub" / "x.pdf")
    criar_pdf(raiz / ".oculta" / "x.pdf")
    (raiz / "DACTE" / "vazia").mkdir(parents=True)
    return raiz


def _relativos(varredura):
    return [lote.caminho_relativo(p.pasta, varredura.raiz) for p in varredura.pastas]


def test_encontra_as_pastas_com_pdfs_em_qualquer_nivel(raiz):
    varredura = procurar_pastas(raiz, Perfil.NOTAS_FISCAIS)

    assert _relativos(varredura) == [
        "Notas",
        r"DANFE\0001-EMPRESA EXEMPLO LTDA\012026",
        r"DANFE\0001-EMPRESA EXEMPLO LTDA\022026",
    ]
    competencia = varredura.pastas[1]
    assert [p.name for p in competencia.arquivos] == ["1.pdf", "2.pdf"]
    assert competencia.destino == competencia.pasta / "UnePDF" / "DANFE - 0001-EMPRESA EXEMPLO LTDA - 012026.pdf"


def test_respeita_a_pasta_de_saida_configurada(raiz, criar_pdf):
    criar_pdf(raiz / "RESULTADO" / "y.pdf")
    varredura = procurar_pastas(raiz, pasta_saida="RESULTADO")
    # A pasta "UnePDF" deixa de ser especial e a "RESULTADO" passa a ser ignorada
    assert r"DANFE\0001-EMPRESA EXEMPLO LTDA\012026\UnePDF" in _relativos(varredura)
    assert not any("RESULTADO" in r for r in _relativos(varredura))


def test_raiz_sem_pdfs_ou_pasta_de_saida(tmp_path):
    (tmp_path / "vazia" / "sub").mkdir(parents=True)
    with pytest.raises(ErroUnePDF, match="Nenhuma pasta com PDFs"):
        procurar_pastas(tmp_path / "vazia")
    (tmp_path / "UnePDF").mkdir()
    with pytest.raises(ErroUnePDF, match="grava os resultados"):
        procurar_pastas(tmp_path / "UnePDF")


def test_pasta_inacessivel_fica_de_fora_sem_interromper(raiz, monkeypatch):
    original = lote.os.scandir
    bloqueada = raiz / "DANFE" / "0001-EMPRESA EXEMPLO LTDA" / "022026"

    def scandir(caminho):
        if str(caminho) == str(bloqueada):
            raise PermissionError(13, "Acesso negado")
        return original(caminho)

    monkeypatch.setattr(lote.os, "scandir", scandir)

    varredura = procurar_pastas(raiz)

    assert len(varredura.pastas) == 2
    assert [i.caminho for i in varredura.inacessiveis] == [bloqueada]


def test_une_cada_pasta_e_relata_os_problemas(raiz):
    quebrada = raiz / "DACTE" / "0002-EXEMPLO TRANSPORTES"
    quebrada.mkdir(parents=True)
    (quebrada / "a.pdf").write_bytes(b"")
    varredura = procurar_pastas(raiz)
    passos = []

    resultado = unir_em_lote(raiz, varredura.pastas, capa=True, progresso=lambda *a: passos.append(a))

    assert len(resultado.gerados) == 3 and not resultado.cancelado
    problema = resultado.com_problema[0]
    assert problema.pasta == quebrada
    assert "Nenhum dos PDFs" in problema.erro
    assert problema.ignorados[0].motivo == "arquivo vazio (0 KB)"
    competencia = next(i for i in resultado.gerados if i.pasta.name == "012026")
    assert len(PdfReader(competencia.destino).pages) == 4  # capa + 3 páginas
    # O progresso soma todas as pastas: um passo por arquivo e um de gravação em cada
    assert passos[-1][0] == passos[-1][1] == 5 + 4
    assert [p[2] for p in passos[:3]] == [
        "Notas: solto.pdf", "Notas: Gravando Notas - UNIFICADO.pdf", r"DACTE\0002-EXEMPLO TRANSPORTES: a.pdf",
    ]
    assert lote.resumo_lote(resultado) == "3 unificados gerados, 1 pasta com problema."


def test_cancelar_mantem_as_pastas_ja_concluidas(raiz):
    varredura = procurar_pastas(raiz)
    cancelamento = Cancelamento()

    def progresso(atual, total, descricao):
        if "022026" in descricao:
            cancelamento.cancelar()

    resultado = unir_em_lote(raiz, varredura.pastas, progresso=progresso, cancelamento=cancelamento)

    assert len(resultado.gerados) == 2
    assert resultado.pendentes == [varredura.pastas[2].pasta]
    assert resultado.gerados[0].destino.exists()
    assert not varredura.pastas[2].destino.exists()
    assert "1 pasta não processada" in lote.resumo_lote(resultado)


def test_falha_inesperada_em_uma_pasta_nao_para_o_lote(raiz, monkeypatch):
    original = lote.unir

    def unir(arquivos, destino, *args, **opcoes):
        if destino.parent.parent.name == "012026":
            raise RuntimeError("falha interna")
        return original(arquivos, destino, *args, **opcoes)

    monkeypatch.setattr(lote, "unir", unir)
    varredura = procurar_pastas(raiz)

    resultado = unir_em_lote(raiz, varredura.pastas)

    assert len(resultado.gerados) == 2
    assert "registro de atividades" in resultado.com_problema[0].erro


def test_cancelamento_na_busca(raiz):
    cancelamento = Cancelamento()
    cancelamento.cancelar()
    with pytest.raises(OperacaoCancelada):
        procurar_pastas(raiz, cancelamento=cancelamento)


def test_relatorio_em_texto(raiz):
    (raiz / "DANFE" / "0001-EMPRESA EXEMPLO LTDA" / "022026" / "vazio.pdf").write_bytes(b"")
    varredura = procurar_pastas(raiz)
    resultado = unir_em_lote(raiz, varredura.pastas)
    resultado.pendentes = [raiz / "Outra"]

    texto = texto_relatorio(resultado, datetime(2026, 1, 31, 9, 5))

    assert f"Pasta: {raiz}" in texto
    assert "Data: 31/01/2026 09:05" in texto
    assert r"[OK] DANFE\0001-EMPRESA EXEMPLO LTDA\012026" in texto
    assert "2 arquivos, 3 páginas: " in texto
    assert "Não entrou: vazio.pdf (arquivo vazio (0 KB))" in texto
    assert "[NÃO PROCESSADA] Outra" in texto
