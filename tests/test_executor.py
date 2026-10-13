import pytest

from unepdf.core.erros import ErroUnePDF, OperacaoCancelada
from unepdf.ui.executor import Executor


@pytest.fixture
def executor(qtbot):
    executor = Executor()
    yield executor
    executor.cancelar()
    assert executor.aguardar()


def test_entrega_o_resultado(qtbot, executor):
    with qtbot.waitSignal(executor.concluido) as sinal:
        executor.executar(lambda progresso, cancelamento: 42)

    assert sinal.args == [42]
    assert not executor.em_execucao


def test_agrega_o_progresso_e_sempre_entrega_o_ultimo(qtbot, executor):
    recebidos = []
    executor.progresso.connect(lambda *dados: recebidos.append(dados))

    def tarefa(progresso, cancelamento):
        for i in range(1, 2001):
            progresso(i, 2000, f"{i}.pdf")

    with qtbot.waitSignal(executor.concluido):
        executor.executar(tarefa)
    qtbot.wait(20)  # entrega os sinais de progresso ainda na fila

    assert 0 < len(recebidos) < 100
    assert recebidos[-1] == (2000, 2000, "2000.pdf")


def test_falha_chega_na_interface_com_a_excecao(qtbot, executor):
    def tarefa(progresso, cancelamento):
        raise ErroUnePDF("Falhou de propósito.")

    with qtbot.waitSignal(executor.falhou) as sinal:
        executor.executar(tarefa)

    assert isinstance(sinal.args[0], ErroUnePDF)
    assert not executor.em_execucao


def test_falha_inesperada_vai_para_o_log(qtbot, executor, caplog):
    with qtbot.waitSignal(executor.falhou):
        executor.executar(lambda progresso, cancelamento: 1 / 0)

    assert "Falha inesperada" in caplog.text


def test_cancelamento(qtbot, executor):
    def tarefa(progresso, cancelamento):
        while True:
            cancelamento.verificar()

    with qtbot.waitSignal(executor.falhou, timeout=5000) as sinal:
        executor.executar(tarefa)
        executor.cancelar()

    assert isinstance(sinal.args[0], OperacaoCancelada)


def test_uma_tarefa_por_vez(qtbot, executor):
    def lenta(progresso, cancelamento):
        while not cancelamento.cancelado:
            pass

    executor.executar(lenta)
    with pytest.raises(RuntimeError):
        executor.executar(lenta)
    with qtbot.waitSignal(executor.concluido):
        executor.cancelar()


def test_pode_iniciar_outra_tarefa_ao_concluir(qtbot, executor):
    resultados = []

    def ao_concluir(resultado):
        resultados.append(resultado)
        if resultado == 1:
            executor.executar(lambda p, c: 2)

    executor.concluido.connect(ao_concluir)
    with qtbot.waitSignal(executor.concluido):
        executor.executar(lambda p, c: 1)
    qtbot.waitUntil(lambda: resultados == [1, 2])
