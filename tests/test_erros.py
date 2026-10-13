import pytest

from unepdf import __version__
from unepdf.core.erros import ErroUnePDF, detalhes_do_erro, mensagem_amigavel


def _capturar(erro: BaseException) -> BaseException:
    # Lança e captura para o erro ter traceback, como acontece no app
    try:
        raise erro
    except BaseException as capturado:
        return capturado


@pytest.mark.parametrize("erro,trecho", [
    (ErroUnePDF("Mensagem pronta."), "Mensagem pronta."),
    (PermissionError(13, "Acesso negado"), "aberto em outro programa"),
    (FileNotFoundError(2, "Não encontrado", r"C:\Notas\a.pdf"), r"C:\Notas\a.pdf"),
    (OSError(28, "Espaço insuficiente no disco"), "Espaço insuficiente no disco"),
    (MemoryError(), "Memória insuficiente"),
    (ZeroDivisionError("division by zero"), "erro inesperado"),
])
def test_mensagem_amigavel(erro, trecho):
    assert trecho in mensagem_amigavel(erro)


def test_erro_inesperado_nao_expoe_texto_tecnico():
    assert "division" not in mensagem_amigavel(ZeroDivisionError("division by zero"))


def test_detalhes_trazem_versao_e_causa_encadeada():
    try:
        try:
            raise ValueError("causa original")
        except ValueError as causa:
            raise ErroUnePDF("Falhou.") from causa
    except ErroUnePDF as erro:
        detalhes = detalhes_do_erro(erro)

    assert f"UnePDF {__version__}" in detalhes
    assert "causa original" in detalhes
    assert "Falhou." in detalhes


def test_detalhes_de_erro_sem_traceback():
    assert "ZeroDivisionError" in detalhes_do_erro(ZeroDivisionError("x"))
    assert "ZeroDivisionError" in detalhes_do_erro(_capturar(ZeroDivisionError("x")))
