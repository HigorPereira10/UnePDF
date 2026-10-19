import json

import pytest

from unepdf.core.configuracoes import (
    Configuracoes,
    caminho_padrao,
    carregar,
    pasta_saida_valida,
    salvar,
)
from unepdf.core.erros import ErroUnePDF
from unepdf.core.localizador import OrdemArquivos
from unepdf.core.nomenclatura import Perfil


def test_arquivo_ausente_usa_padroes(tmp_path):
    assert carregar(tmp_path / "config.json") == Configuracoes()


@pytest.mark.parametrize("conteudo", [b"{ isto nao e json", b"", b"[1, 2]", b"\xff\xfe\x00lixo"])
def test_arquivo_corrompido_usa_padroes(tmp_path, conteudo):
    arquivo = tmp_path / "config.json"
    arquivo.write_bytes(conteudo)

    assert carregar(arquivo) == Configuracoes()


def test_salvar_e_carregar_preserva_valores(tmp_path):
    arquivo = tmp_path / "sub" / "config.json"
    original = Configuracoes(
        pasta_inicial=r"\\servidor\documentos\notas",
        ultima_pasta=r"C:\Notas\DANFE\0001-EMPRESA EXEMPLO LTDA\012026",
        perfil_nomenclatura=Perfil.NOTAS_FISCAIS,
        pasta_saida="PDF ÚNICO",
        unir_ordem=OrdemArquivos.DATA,
        unir_pular_repetidos=False,
        unir_capa=True,
    )

    salvar(original, arquivo)

    assert carregar(arquivo) == original
    assert not list(arquivo.parent.glob("*.tmp"))


def test_valor_invalido_vira_padrao_so_naquele_campo(tmp_path):
    arquivo = tmp_path / "config.json"
    arquivo.write_text(
        json.dumps({
            "pasta_inicial": r"C:\Notas",
            "perfil_nomenclatura": "inexistente",
            "pasta_saida": "a/b",
            "ultima_pasta": 123,
            "unir_ordem": "aleatoria",
            "unir_capa": "sim",
            "unir_pular_repetidos": 1,
            "campo_de_versao_futura": True,
        }),
        encoding="utf-8",
    )

    config = carregar(arquivo)

    assert config == Configuracoes(pasta_inicial=r"C:\Notas")


def test_falha_ao_salvar_vira_erro_amigavel(tmp_path):
    # Um arquivo no lugar da pasta impede criar o config.json
    bloqueio = tmp_path / "bloqueio"
    bloqueio.write_text("x")

    with pytest.raises(ErroUnePDF, match="Não foi possível salvar as configurações"):
        salvar(Configuracoes(), bloqueio / "config.json")


@pytest.mark.parametrize("nome,valido", [
    ("UNIFICADO", True),
    ("PDF ÚNICO", True),
    ("", False),
    ("  ", False),
    ("..", False),
    ("a/b", False),
    ("a\\b", False),
    ("nome?", False),
])
def test_pasta_saida_valida(nome, valido):
    assert pasta_saida_valida(nome) is valido


def test_caminho_padrao_fica_no_appdata(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))

    assert caminho_padrao() == tmp_path / "UnePDF" / "config.json"


def test_opcoes_da_separacao_de_notas(tmp_path):
    caminho = tmp_path / "config.json"
    caminho.write_text(json.dumps({
        "separar_pastas": {"DANFSE": {"emitidas": "PRESTADAS", "recebidas": "TOM/ADAS"}, "DANFE": "x"},
        "separar_empresas": {"0001-empresa exemplo ltda": "11222333000181", "outra": 5},
    }), encoding="utf-8")
    config = carregar(caminho)
    assert config.separar_pastas == {"DANFSE": {"emitidas": "PRESTADAS"}}
    assert config.separar_empresas == {"0001-empresa exemplo ltda": "11222333000181"}
    assert Configuracoes().separar_pastas == {} and Configuracoes().separar_empresas == {}
