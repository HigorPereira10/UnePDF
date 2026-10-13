import logging

import pytest

from unepdf.utils.caminhos import pasta_logs
from unepdf.utils.logs import configurar_logs


@pytest.fixture(autouse=True)
def restaurar_logging():
    # Os testes mexem no logger raiz; devolve o estado original para não afetar os outros
    raiz = logging.getLogger()
    handlers, nivel = list(raiz.handlers), raiz.level
    yield
    for handler in raiz.handlers:
        if handler not in handlers:
            raiz.removeHandler(handler)
            handler.close()
    raiz.setLevel(nivel)


def test_grava_no_arquivo(tmp_path):
    caminho = configurar_logs(tmp_path / "logs")
    logging.getLogger("unepdf.teste").info("mensagem de teste com acentuação")

    assert "mensagem de teste com acentuação" in caminho.read_text(encoding="utf-8")


def test_rotaciona_ao_atingir_o_tamanho(tmp_path):
    configurar_logs(tmp_path, tamanho_maximo=500, copias=2)
    for i in range(100):
        logging.getLogger("unepdf.teste").info("linha %03d %s", i, "x" * 40)

    arquivos = sorted(p.name for p in tmp_path.iterdir())
    assert arquivos == ["unepdf.log", "unepdf.log.1", "unepdf.log.2"]


def test_configurar_de_novo_nao_duplica_linhas(tmp_path):
    configurar_logs(tmp_path)
    caminho = configurar_logs(tmp_path)
    logging.getLogger("unepdf.teste").info("uma vez")

    assert caminho.read_text(encoding="utf-8").count("uma vez") == 1


def test_sem_permissao_segue_sem_log(tmp_path):
    bloqueio = tmp_path / "bloqueio"
    bloqueio.write_text("x")

    assert configurar_logs(bloqueio / "logs") is None


def test_pasta_padrao_fica_no_localappdata(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    assert pasta_logs() == tmp_path / "UnePDF" / "logs"
