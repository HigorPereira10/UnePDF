import pytest

from unepdf.core.erros import ErroUnePDF
from unepdf.core.gravacao import gravar_com_seguranca
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
