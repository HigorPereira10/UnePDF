from pathlib import Path

import pytest

from unepdf.core.nomenclatura import (
    Perfil,
    destino_derivado,
    destino_padrao,
    limpar_nome,
    nome_saida,
    pasta_resultado,
)

RAIZ = Path(r"C:\Notas\Arquivos")
NF = Perfil.NOTAS_FISCAIS


# Perfil Notas fiscais

def test_estrutura_padrao():
    base = RAIZ / "DANFE" / "0001-EMPRESA EXEMPLO LTDA" / "012026"
    assert nome_saida(base, NF) == "DANFE - 0001-EMPRESA EXEMPLO LTDA - 012026.pdf"


@pytest.mark.parametrize("tipo", ["DANFSE", "DANFE", "DANFCE", "DACTE"])
def test_todos_os_tipos_de_documento(tipo):
    base = RAIZ / tipo / "EMPRESA EXEMPLO" / "012026"
    assert nome_saida(base, NF) == f"{tipo} - EMPRESA EXEMPLO - 012026.pdf"


def test_empresa_quebrada_em_duas_pastas():
    # "S/S LTDA" foi salvo pelo sistema de origem como duas pastas
    base = RAIZ / "DANFSE" / "0002-EXEMPLO SERVICOS S" / "S LTDA" / "012026"
    assert nome_saida(base, NF) == "DANFSE - 0002-EXEMPLO SERVICOS S-S LTDA - 012026.pdf"


def test_competencia_sem_pasta_de_tipo():
    base = Path(r"C:\Notas\EMPRESA X\102026")
    assert nome_saida(base, NF) == "EMPRESA X - 102026.pdf"


def test_competencia_direto_na_pasta_de_tipo():
    assert nome_saida(RAIZ / "DANFE" / "012026", NF) == "DANFE - 012026.pdf"


def test_pasta_fora_do_padrao():
    assert nome_saida(Path(r"C:\Notas\avulsas"), NF) == "avulsas - UNIFICADO.pdf"


def test_tipo_em_minusculas_e_reconhecido():
    base = Path(r"C:\x\danfse\EMPRESA\012027")
    assert nome_saida(base, NF) == "DANFSE - EMPRESA - 012027.pdf"


def test_usa_o_tipo_mais_proximo_da_competencia():
    base = Path(r"C:\DANFE\copia\DACTE\EMPRESA EXEMPLO\012026")
    assert nome_saida(base, NF) == "DACTE - EMPRESA EXEMPLO - 012026.pdf"


def test_pasta_de_rede():
    base = Path(r"\\servidor\documentos\DANFE\EMPRESA EXEMPLO\012026")
    assert nome_saida(base, NF) == "DANFE - EMPRESA EXEMPLO - 012026.pdf"


# Perfil genérico

def test_generico_usa_o_nome_da_pasta():
    assert nome_saida(Path(r"C:\Notas\Janeiro")) == "Janeiro - UNIFICADO.pdf"


def test_generico_ignora_a_estrutura_de_notas_fiscais():
    base = RAIZ / "DANFE" / "0001-EMPRESA EXEMPLO LTDA" / "012026"
    assert nome_saida(base) == "012026 - UNIFICADO.pdf"


def test_raiz_do_disco_recebe_nome_padrao():
    assert nome_saida(Path("C:\\")) == "PDF - UNIFICADO.pdf"
    assert nome_saida(Path("C:\\"), NF) == "PDF - UNIFICADO.pdf"


# Destino e limpeza de nomes

def test_destino_fica_na_subpasta_unificado():
    base = RAIZ / "DANFE" / "0003-COMERCIO EXEMPLO" / "012026"
    assert destino_padrao(base, NF) == base / "UnePDF" / "DANFE - 0003-COMERCIO EXEMPLO - 012026.pdf"


def test_destino_com_subpasta_personalizada():
    base = Path(r"C:\Notas\Janeiro")
    assert destino_padrao(base, pasta_saida="PDF ÚNICO") == base / "PDF ÚNICO" / "Janeiro - UNIFICADO.pdf"


def test_limpar_nome_remove_caracteres_proibidos():
    assert limpar_nome('A/B:C*D?. ') == "A-B-C-D-"
    assert limpar_nome('<"x"|y>') == "--x--y-"
    assert limpar_nome("  .nome. ") == "nome"


def test_pasta_resultado_fica_na_subpasta_de_saida():
    assert pasta_resultado(Path(r"C:\Notas\contrato.pdf")) == Path(r"C:\Notas\UnePDF")
    assert pasta_resultado(Path(r"C:\Notas\contrato.pdf"), "RESULTADO") == Path(r"C:\Notas\RESULTADO")


def test_original_ja_na_pasta_de_saida_nao_cria_outra_dentro():
    assert pasta_resultado(Path(r"C:\Notas\UnePDF\u.pdf")) == Path(r"C:\Notas\UnePDF")
    assert pasta_resultado(Path(r"C:\Notas\unepdf\u.pdf")) == Path(r"C:\Notas\unepdf")


def test_destino_derivado():
    origem = Path(r"C:\Notas\contrato.pdf")
    assert destino_derivado(origem, "protegido") == Path(r"C:\Notas\UnePDF\contrato - protegido.pdf")
    assert destino_derivado(origem, "texto", extensao=".txt") == Path(r"C:\Notas\UnePDF\contrato - texto.txt")


def test_subpasta_de_competencia_grava_junto_da_competencia():
    mes = RAIZ / "DANFSE" / "0001-EMPRESA EXEMPLO LTDA" / "012026"
    assert nome_saida(mes / "PRESTADAS", NF) == "DANFSE - 0001-EMPRESA EXEMPLO LTDA - 012026 - PRESTADAS.pdf"
    assert destino_padrao(mes / "TOMADAS", NF) == mes / "UnePDF" / "DANFSE - 0001-EMPRESA EXEMPLO LTDA - 012026 - TOMADAS.pdf"
    # No perfil genérico nada muda
    assert destino_padrao(mes / "TOMADAS") == mes / "TOMADAS" / "UnePDF" / "TOMADAS - UNIFICADO.pdf"
