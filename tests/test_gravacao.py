import pytest

from unepdf.core.erros import ErroUnePDF
from unepdf.core.gravacao import gravar_com_seguranca, gravar_pasta_com_seguranca
from unepdf.core.progresso import Cancelamento


def test_grava_e_informa_substituicao(tmp_path):
    destino = tmp_path / "sub" / "a.txt"

    assert gravar_com_seguranca(destino, lambda f: f.write(b"um")) is False
    assert gravar_com_seguranca(destino, lambda f: f.write(b"dois")) is True
    assert destino.read_bytes() == b"dois"


def test_falha_no_meio_preserva_o_anterior(tmp_path):
    destino = tmp_path / "a.txt"
    destino.write_bytes(b"anterior")

    def escrever_pela_metade(arquivo):
        arquivo.write(b"meta")
        raise OSError(28, "Espaço insuficiente no disco")

    with pytest.raises(ErroUnePDF, match="Espaço insuficiente no disco"):
        gravar_com_seguranca(destino, escrever_pela_metade)

    assert destino.read_bytes() == b"anterior"
    assert list(tmp_path.iterdir()) == [destino]


def test_outras_excecoes_passam_adiante_sem_deixar_temporario(tmp_path):
    def falhar(arquivo):
        raise ValueError("falha")

    with pytest.raises(ValueError):
        gravar_com_seguranca(tmp_path / "a.txt", falhar)
    assert list(tmp_path.iterdir()) == []


def test_cancelamento():
    cancelamento = Cancelamento()
    cancelamento.verificar()  # sem cancelar, não faz nada
    assert not cancelamento.cancelado

    cancelamento.cancelar()

    assert cancelamento.cancelado
    with pytest.raises(ErroUnePDF, match="cancelada"):
        cancelamento.verificar()


def _escrever_arquivos(*nomes):
    def escrever(pasta):
        for nome in nomes:
            (pasta / nome).write_text(nome)
    return escrever


def test_pasta_nova_e_substituicao_completa(tmp_path):
    destino = tmp_path / "saida" / "x - dividido"

    assert gravar_pasta_com_seguranca(destino, _escrever_arquivos("a.pdf", "b.pdf")) is False
    assert gravar_pasta_com_seguranca(destino, _escrever_arquivos("c.pdf")) is True

    assert sorted(p.name for p in destino.iterdir()) == ["c.pdf"]
    assert sorted(p.name for p in destino.parent.iterdir()) == ["x - dividido"]


def test_pasta_falha_no_meio_preserva_a_anterior(tmp_path):
    destino = tmp_path / "x"
    gravar_pasta_com_seguranca(destino, _escrever_arquivos("antigo.pdf"))

    def falhar(pasta):
        (pasta / "meio.pdf").write_text("x")
        raise OSError(28, "Espaço insuficiente no disco")

    with pytest.raises(ErroUnePDF, match="Espaço insuficiente"):
        gravar_pasta_com_seguranca(destino, falhar)

    assert sorted(p.name for p in destino.iterdir()) == ["antigo.pdf"]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["x"]


def test_pasta_recupera_execucao_interrompida_entre_as_trocas(tmp_path):
    # Simula uma queda de energia depois de mover a pasta antiga e antes de colocar a nova
    antiga = tmp_path / "x.antiga"
    antiga.mkdir()
    (antiga / "bom.pdf").write_text("x")
    (tmp_path / "x.tmp").mkdir()

    def falhar(pasta):
        raise ValueError("falha")

    with pytest.raises(ValueError):
        gravar_pasta_com_seguranca(tmp_path / "x", falhar)

    assert sorted(p.name for p in tmp_path.iterdir()) == ["x"]
    assert (tmp_path / "x" / "bom.pdf").exists()
