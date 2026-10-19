import os
import shutil

import pytest
from conftest import criar_pdf_com_texto
from xmls_fiscais import CNPJ_EMITENTE, chave, chave_nfse, evento, gravar, nfe, nfse

from unepdf.core import separar as s
from unepdf.core.separar import Lado

EMPRESA = CNPJ_EMITENTE  # 11.222.333/0001-81


def cnpj(base: str) -> str:
    """CNPJ válido a partir dos 12 primeiros dígitos."""
    for _ in range(2):
        soma = sum(int(d) * (2 + i % 8) for i, d in enumerate(reversed(base)))
        resto = soma % 11
        base += str(0 if resto < 2 else 11 - resto)
    return base


FORNECEDOR = cnpj("223334440001")
OUTRO_FORNECEDOR = cnpj("334445550001")
CLIENTE = cnpj("445556660001")
OUTRO_CLIENTE = cnpj("556667770001")


def grupos(chave_acesso: str) -> str:
    return " ".join(chave_acesso[i:i + 4] for i in range(0, len(chave_acesso), 4))


def danfe(pasta, emitente, destinatario, numero, nome_com_chave=True, texto_extra=""):
    """PDF de nota com a chave e os CNPJs no texto, como num DANFE de verdade."""
    ch = chave(55, numero, cnpj=emitente)
    texto = (
        f"DANFE CHAVE DE ACESSO {grupos(ch)} EMITENTE {s.formatar_documento(emitente)} "
        f"DESTINATARIO {s.formatar_documento(destinatario)} {texto_extra}"
    )
    nome = f"{ch}-nfe.pdf" if nome_com_chave else f"{numero}.pdf"
    return criar_pdf_com_texto(pasta / nome, [texto])


@pytest.fixture
def mes(tmp_path):
    return tmp_path / "Notas" / "DANFE" / "0001-EMPRESA EXEMPLO LTDA" / "012026"


@pytest.fixture
def registros(tmp_path):
    return tmp_path / "registros"


def _ler(pasta, **kwargs):
    return s.ler_pastas([pasta], **kwargs)[0]


def _planejar(leitura, personalizados=None):
    return s.planejar(leitura, leitura.empresa, s.nomes_das_pastas(leitura.tipo, personalizados))


def _nomes(pasta):
    return sorted(p.name for p in pasta.iterdir()) if pasta.is_dir() else []


# Chaves e documentos

def test_le_a_chave_da_nfe_e_da_nfse():
    nota = s.ler_chave(chave(55, 1234))
    assert nota.modelo == "55" and nota.emitente == EMPRESA

    servico = s.ler_chave(chave_nfse(42, FORNECEDOR))
    assert servico.modelo == "NFS" and servico.emitente == FORNECEDOR


def test_chave_de_emitente_pessoa_fisica():
    assert s.ler_chave(chave(55, 7, cnpj="00052998224725")).emitente == "52998224725"


@pytest.mark.parametrize("trocar", [
    lambda c: c[:-1] + str((int(c[-1]) + 1) % 10),  # dígito verificador errado
    lambda c: "99" + c[2:],  # UF que não existe
    lambda c: c[:20] + "99" + c[22:],  # modelo que não existe
])
def test_recusa_chave_invalida(trocar):
    assert s.ler_chave(trocar(chave(55, 1234))) is None


def test_acha_a_chave_em_qualquer_formato():
    ch = chave(55, 1234)
    pontuada = f"{ch[:2]}.{ch[2:6]}.{ch[6:20]}-{ch[20:22]}-{ch[22:25]}-{ch[25:34]}-{ch[34:]}"
    for texto in (f"CHAVE {grupos(ch)} SERIE", f"Chave:{pontuada}", f"{ch} 001/000000123", f"nfe{ch}-procnfe"):
        assert [c.numero for c in s.chaves_no_texto(texto)] == [ch], texto


def test_no_dacte_vale_a_chave_do_proprio_ct():
    nota_transportada = chave(55, 1234, cnpj=FORNECEDOR)
    conhecimento = chave(57, 567)
    texto = f"DOCUMENTOS ORIGINARIOS {nota_transportada} CHAVE DO CT-E {grupos(conhecimento)}"
    assert s.chave_principal(s.chaves_no_texto(texto)).numero == conhecimento


def test_cnpj_alfanumerico_e_cpf():
    assert s.cnpj_valido("12ABC34501DE35")
    assert not s.cnpj_valido("12ABC34501DE36")
    assert s.cpf_valido("52998224725") and not s.cpf_valido("11111111111")
    texto = "CNPJ 11.222.333/0001-81 CPF 529.982.247-25 FALSO 11.222.333/0001-82 12.ABC.345/01DE-35"
    assert s.documentos_no_texto(texto) == {EMPRESA, "52998224725", "12ABC34501DE35"}


# Leitura e descoberta da empresa

def test_separa_emitidas_e_recebidas(mes):
    danfe(mes, EMPRESA, CLIENTE, 1)
    danfe(mes, EMPRESA, OUTRO_CLIENTE, 2)
    danfe(mes, FORNECEDOR, EMPRESA, 3)
    gravar(mes / "compra.xml", nfe(numero=4, cnpj=OUTRO_FORNECEDOR, cnpj_dest=EMPRESA))

    leitura = _ler(mes)
    assert leitura.empresa == EMPRESA and leitura.como == s.COMO_NOTAS
    assert leitura.tipo == "DANFE"

    plano = _planejar(leitura)
    assert plano.quantidade(Lado.EMITIDAS) == 2 and plano.quantidade(Lado.RECEBIDAS) == 2
    destinos = {m.origem.name: m.destino.parent.name for m in plano.movimentos}
    assert destinos["compra.xml"] == "RECEBIDAS"
    assert not plano.copias and not plano.nao_classificadas


def test_nomes_das_subpastas_seguem_o_tipo_e_as_configuracoes(tmp_path):
    pasta = tmp_path / "DANFSE" / "0001-EMPRESA EXEMPLO LTDA" / "012026"
    gravar(pasta / "a.xml", nfse(1, cnpj=EMPRESA, tomador=CLIENTE, chave_nacional=True))
    gravar(pasta / "b.xml", nfse(2, cnpj=FORNECEDOR, tomador=EMPRESA, chave_nacional=True))
    gravar(pasta / "c.xml", nfse(3, cnpj=OUTRO_FORNECEDOR, tomador=EMPRESA, chave_nacional=True))
    leitura = _ler(pasta)

    padrao = _planejar(leitura)
    assert padrao.nomes == {Lado.EMITIDAS: "PRESTADAS", Lado.RECEBIDAS: "TOMADAS"}
    personalizado = _planejar(leitura, {"DANFSE": {"recebidas": "SERVICOS TOMADOS"}})
    assert personalizado.nomes == {Lado.EMITIDAS: "PRESTADAS", Lado.RECEBIDAS: "SERVICOS TOMADOS"}
    assert s.nomes_das_pastas("", None) == {Lado.EMITIDAS: "EMITIDAS", Lado.RECEBIDAS: "RECEBIDAS"}


def test_empate_sem_desempate_pede_ao_usuario(mes):
    # Todas as notas são com o mesmo fornecedor: os dois CNPJs aparecem em todas
    danfe(mes, FORNECEDOR, EMPRESA, 1)
    danfe(mes, FORNECEDOR, EMPRESA, 2)
    leitura = _ler(mes)
    assert leitura.empresa == ""
    assert {d for d, _ in leitura.candidatos} == {EMPRESA, FORNECEDOR}


def test_empate_resolvido_pelo_cnpj_no_nome_da_pasta(tmp_path):
    pasta = tmp_path / "DANFE" / f"0-{EMPRESA}" / "012026"
    danfe(pasta, FORNECEDOR, EMPRESA, 1)
    leitura = _ler(pasta)
    assert leitura.empresa == EMPRESA and leitura.como == s.COMO_CNPJ_NA_PASTA


def test_empate_resolvido_pelos_outros_meses(mes):
    danfe(mes, FORNECEDOR, EMPRESA, 1)
    anterior = mes.parent / "122025"
    danfe(anterior, OUTRO_FORNECEDOR, EMPRESA, 2)
    danfe(anterior / "EMITIDAS", EMPRESA, CLIENTE, 3)  # mês já separado
    leitura = _ler(mes)
    assert leitura.empresa == EMPRESA and leitura.como == s.COMO_VIZINHAS


def test_no_empate_o_nome_da_pasta_so_sugere(mes):
    for numero in (1, 2):
        ch = chave(55, numero, cnpj=FORNECEDOR)
        texto = (
            f"CHAVE {ch} EMITENTE PARCEIRO COMERCIAL SA {s.formatar_documento(FORNECEDOR)} "
            + "ITEM " * 30
            + f"DESTINATARIO EMPRESA EXEMPLO LTDA {s.formatar_documento(EMPRESA)}"
        )
        criar_pdf_com_texto(mes / f"{numero}.pdf", [texto])
    leitura = _ler(mes)
    # Um erro aqui inverteria a pasta inteira: o app pergunta, com a sugestão marcada
    assert leitura.empresa == ""
    assert s.sugestao_pelo_nome(leitura) == EMPRESA


def pdf_em_colunas(caminho, linhas):
    """PDF com textos em posições escolhidas: [(x, y, texto)], como os blocos lado a lado de um DACTE."""
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    escritor = PdfWriter()
    fonte = escritor._add_object(DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    }))
    pagina = escritor.add_blank_page(595, 842)
    pagina[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): fonte}),
    })
    conteudo = DecodedStreamObject()
    conteudo.set_data("".join(f"BT /F1 9 Tf {x} {y} Td ({texto}) Tj ET\n" for x, y, texto in linhas).encode("latin-1"))
    pagina[NameObject("/Contents")] = escritor._add_object(conteudo)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    escritor.write(caminho)
    return caminho


def dacte_em_colunas(pasta, numero, remetente, destinatario):
    """Remetente à esquerda e destinatário à direita: no texto, o CNPJ do remetente vem logo depois
    do nome do destinatário, mas na página ele está na outra coluna."""
    ch = chave(57, numero, cnpj=OUTRO_FORNECEDOR)
    return pdf_em_colunas(pasta / f"{numero}.pdf", [
        (40, 800, f"DACTE CHAVE {ch}"),
        (40, 780, f"EMITENTE TRANSPORTES EXEMPLO {s.formatar_documento(OUTRO_FORNECEDOR)}"),
        (40, 700, f"REMETENTE {remetente[0]}"), (320, 700, f"DESTINATARIO {destinatario[0]}"),
        (40, 690, s.formatar_documento(remetente[1])), (320, 690, s.formatar_documento(destinatario[1])),
    ])


def test_nome_na_coluna_certa(mes):
    for numero in (1, 2):
        dacte_em_colunas(mes, numero, ("DISTRIBUIDORA EXEMPLO SA", FORNECEDOR), ("EMPRESA EXEMPLO LTDA", EMPRESA))
    # Com a transportadora, o remetente e a empresa em todas as notas, só o nome indica quem é quem
    leitura = _ler(mes)
    assert leitura.empresa == "" and s.sugestao_pelo_nome(leitura) == EMPRESA
    assert leitura.documento_do_nome == EMPRESA
    assert leitura.nome_na_nota == "EMPRESA EXEMPLO LTDA"


def test_nome_parecido_tambem_vale(tmp_path):
    pasta = tmp_path / "DACTE" / "0002-EMPRESA FILIAL EXEMPLO COMERCIO LTDA" / "012026"
    for numero in (1, 2):
        dacte_em_colunas(pasta, numero, ("DISTRIBUIDORA EXEMPLO SA", FORNECEDOR), ("EMPRESA EXEMPLO COMERCIO LTDA", EMPRESA))
    assert s.sugestao_pelo_nome(_ler(pasta)) == EMPRESA


def test_nome_junto_de_outro_cnpj_pede_conferencia(mes):
    # Pelas notas a empresa é a 11.222.333, mas nelas o nome da pasta está junto do cliente
    for numero in (1, 2, 3):
        dacte_em_colunas(mes, numero, ("EMPRESA EXEMPLO LTDA", CLIENTE), ("OUTRA FIRMA SA", EMPRESA))
    danfe(mes, EMPRESA, OUTRO_CLIENTE, 4)
    leitura = _ler(mes)
    assert leitura.empresa == EMPRESA and leitura.como == s.COMO_NOTAS
    assert leitura.documento_do_nome == CLIENTE and leitura.conferir_empresa


def test_sem_o_nome_nas_notas_nao_confere_nada(mes):
    danfe(mes, EMPRESA, CLIENTE, 1)
    danfe(mes, FORNECEDOR, EMPRESA, 2)
    leitura = _ler(mes)
    assert leitura.empresa == EMPRESA
    assert leitura.documento_do_nome == "" and leitura.nome_na_nota == "" and not leitura.conferir_empresa


def test_resposta_guardada_so_vale_se_aparece_nas_notas(mes):
    danfe(mes, FORNECEDOR, EMPRESA, 1)
    chave_da_empresa = s.chave_empresa(mes)
    assert chave_da_empresa == "0001-empresa exemplo ltda"

    leitura = _ler(mes, empresas_conhecidas={chave_da_empresa: EMPRESA})
    assert leitura.empresa == EMPRESA and leitura.como == s.COMO_GUARDADA

    leitura = _ler(mes, empresas_conhecidas={chave_da_empresa: CLIENTE})
    assert leitura.empresa == ""


def test_pastas_que_nao_podem_ser_separadas(tmp_path, mes):
    danfe(mes, EMPRESA, CLIENTE, 1)
    (tmp_path / "vazia").mkdir()
    leituras = s.ler_pastas(
        [mes / "UnePDF", mes / "EMITIDAS", tmp_path / "vazia", tmp_path / "nao existe"],
        pastas_de_separacao=s.todas_as_pastas(),
    )
    assert "grava os resultados" in leituras[0].erro
    assert "já é uma pasta de notas separadas" in leituras[1].erro
    assert leituras[2].erro == "Nenhuma nota (PDF ou XML) direto na pasta."
    assert "Não foi possível abrir" in leituras[3].erro


def test_nota_sem_texto_nem_chave_fica_sem_classificacao(mes):
    danfe(mes, EMPRESA, CLIENTE, 1)
    danfe(mes, FORNECEDOR, EMPRESA, 2)
    criar_pdf_com_texto(mes / "escaneada.pdf", [""])
    (mes / "vazio.pdf").write_bytes(b"")

    plano = _planejar(_ler(mes))
    motivos = {i.caminho.name: i.motivo for i in plano.nao_classificadas}
    assert motivos == {"escaneada.pdf": "PDF sem texto (escaneado)", "vazio.pdf": "arquivo vazio (0 KB)"}


def test_nota_de_outra_empresa_fica_sem_classificacao(mes):
    danfe(mes, EMPRESA, CLIENTE, 1)
    danfe(mes, EMPRESA, CLIENTE, 2)
    danfe(mes, FORNECEDOR, EMPRESA, 3)
    danfe(mes, FORNECEDOR, EMPRESA, 4)
    danfe(mes, OUTRO_FORNECEDOR, OUTRO_CLIENTE, 5)  # salva na pasta errada

    plano = _planejar(_ler(mes))
    assert [i.motivo for i in plano.nao_classificadas] == [
        "a empresa da pasta (11.222.333/0001-81) não aparece nesta nota"
    ]


def test_evento_acompanha_o_lado_da_nota(mes):
    venda = chave(55, 1, cnpj=EMPRESA)
    compra = chave(55, 2, cnpj=FORNECEDOR)
    danfe(mes, EMPRESA, CLIENTE, 1)
    danfe(mes, FORNECEDOR, EMPRESA, 2)
    gravar(mes / "cancelamento.xml", evento(venda, tipo="110111"))
    gravar(mes / "correcao.xml", evento(compra))

    destinos = {m.origem.name: m.lado for m in _planejar(_ler(mes)).movimentos}
    assert destinos["cancelamento.xml"] is Lado.EMITIDAS
    assert destinos["correcao.xml"] is Lado.RECEBIDAS


# Repetidas

def test_copia_identica_e_apagada_e_fica_a_com_chave_no_nome(mes):
    original = danfe(mes, FORNECEDOR, EMPRESA, 1)
    shutil.copy(original, mes / "1.pdf")
    danfe(mes, OUTRO_FORNECEDOR, EMPRESA, 2)
    danfe(mes, EMPRESA, CLIENTE, 3)

    plano = _planejar(_ler(mes))
    assert [c.caminho.name for c in plano.copias] == ["1.pdf"]
    assert plano.copias[0].original == mes / "RECEBIDAS" / original.name
    assert plano.quantidade(Lado.RECEBIDAS) == 2


def test_mesma_nota_com_conteudo_diferente_vai_para_repetidas(mes):
    nova = danfe(mes, FORNECEDOR, EMPRESA, 1)
    danfe(mes, FORNECEDOR, EMPRESA, 1, nome_com_chave=False, texto_extra="GERADA DE NOVO")
    danfe(mes, OUTRO_FORNECEDOR, EMPRESA, 2)
    danfe(mes, EMPRESA, CLIENTE, 3)

    plano = _planejar(_ler(mes))
    repetidas = [m for m in plano.movimentos if m.lado is None]
    assert [m.origem.name for m in repetidas] == ["1.pdf"]
    assert repetidas[0].destino == mes / "UnePDF" / "Repetidas" / "1.pdf"
    assert any(m.origem == nova and m.lado is Lado.RECEBIDAS for m in plano.movimentos)


# Execução e desfazer

def _montar_mes(mes):
    danfe(mes, EMPRESA, CLIENTE, 1)
    copia = danfe(mes, FORNECEDOR, EMPRESA, 2)
    shutil.copy(copia, mes / "2.pdf")
    danfe(mes, OUTRO_FORNECEDOR, EMPRESA, 3)
    criar_pdf_com_texto(mes / "escaneada.pdf", [""])


def test_separa_e_desfaz(mes, registros):
    _montar_mes(mes)
    antes = _nomes(mes)
    plano = _planejar(_ler(mes))

    resultado = s.separar([plano], pasta_registros=registros)[0]

    assert resultado.movidas[Lado.EMITIDAS] == 1 and resultado.movidas[Lado.RECEBIDAS] == 2
    assert resultado.apagadas == 1 and not resultado.falhas
    assert _nomes(mes) == ["EMITIDAS", "RECEBIDAS", "escaneada.pdf"]
    assert len(_nomes(mes / "RECEBIDAS")) == 2
    assert resultado.registro.parent == registros

    registro = s.ultimo_registro(mes, registros)
    assert registro is not None and len(registro.movidos) == 3

    desfeito = s.desfazer(registro)
    assert desfeito.devolvidas == 3 and desfeito.copias_apagadas == 1 and not desfeito.falhas
    # A cópia idêntica apagada não volta; as subpastas criadas somem
    assert _nomes(mes) == sorted(set(antes) - {"2.pdf"})
    assert s.ultimo_registro(mes, registros) is None


def test_nota_que_volta_depois_de_separada(mes, registros):
    _montar_mes(mes)
    s.separar([_planejar(_ler(mes))], pasta_registros=registros)

    # O sistema que baixa as notas grava de novo uma nota já separada, e outra versão de outra
    recebida = next((mes / "RECEBIDAS").iterdir())
    shutil.copy(recebida, mes / recebida.name)
    danfe(mes, OUTRO_FORNECEDOR, EMPRESA, 3, texto_extra="VERSAO NOVA")

    plano = _planejar(_ler(mes))
    assert [c.caminho.name for c in plano.copias] == [recebida.name]
    assert [m.destino.parent.name for m in plano.movimentos] == ["Repetidas"]

    s.separar([plano], pasta_registros=registros)
    assert _nomes(mes) == ["EMITIDAS", "RECEBIDAS", "UnePDF", "escaneada.pdf"]


def test_arquivo_aberto_nao_impede_os_outros(mes, registros, monkeypatch):
    _montar_mes(mes)
    plano = _planejar(_ler(mes))
    bloqueado = next(m.origem for m in plano.movimentos if m.lado is Lado.EMITIDAS)
    renomear = os.rename

    def rename(origem, destino):
        if origem == bloqueado:
            raise PermissionError("em uso")
        renomear(origem, destino)

    monkeypatch.setattr(s.os, "rename", rename)
    resultado = s.separar([plano], pasta_registros=registros)[0]

    assert [(f.caminho, f.motivo) for f in resultado.falhas] == [
        (bloqueado, "o arquivo está aberto em outro programa ou sem permissão")
    ]
    assert resultado.movidas[Lado.RECEBIDAS] == 2 and bloqueado.exists()


def test_copia_so_e_apagada_se_a_original_estiver_no_lugar(mes, registros):
    original = danfe(mes, FORNECEDOR, EMPRESA, 1)
    shutil.copy(original, mes / "1.pdf")
    danfe(mes, EMPRESA, CLIENTE, 2)
    danfe(mes, OUTRO_FORNECEDOR, EMPRESA, 3)
    plano = _planejar(_ler(mes))
    plano.movimentos = [m for m in plano.movimentos if m.origem != original]  # a original não sai do lugar

    resultado = s.separar([plano], pasta_registros=registros)[0]
    assert (mes / "1.pdf").exists() and resultado.apagadas == 0
    assert "nota que fica não foi encontrada" in resultado.falhas[0].motivo


def test_desfazer_com_arquivo_no_caminho(mes, registros):
    _montar_mes(mes)
    s.separar([_planejar(_ler(mes))], pasta_registros=registros)
    emitida = next((mes / "EMITIDAS").iterdir())
    (mes / emitida.name).write_bytes(b"outro arquivo com o mesmo nome")

    registro = s.ultimo_registro(mes, registros)
    desfeito = s.desfazer(registro)
    assert desfeito.devolvidas == 2
    assert desfeito.falhas[0].motivo == "já existe um arquivo com o mesmo nome na pasta original"
    # O que não voltou continua registrado, para tentar de novo
    assert len(s.ultimo_registro(mes, registros).movidos) == 1


def test_cancelar_deixa_o_que_foi_feito_registrado(mes, registros):
    _montar_mes(mes)
    plano = _planejar(_ler(mes))
    cancelamento = s.Cancelamento()

    def progresso(atual, total, descricao):
        if atual == 2:
            cancelamento.cancelar()

    resultado = s.separar([plano], progresso, cancelamento, pasta_registros=registros)[0]
    assert resultado.cancelado
    assert sum(resultado.movidas.values()) == 2 and resultado.apagadas == 0
    assert len(s.ultimo_registro(mes, registros).movidos) == 2


def test_nome_ja_usado_na_subpasta_ganha_numero(mes, registros):
    danfe(mes, EMPRESA, CLIENTE, 1)
    danfe(mes, EMPRESA, OUTRO_CLIENTE, 2, nome_com_chave=False)
    danfe(mes, FORNECEDOR, EMPRESA, 3)
    (mes / "EMITIDAS").mkdir()
    (mes / "EMITIDAS" / "2.pdf").write_bytes(b"arquivo antigo que nao e nota")

    plano = _planejar(_ler(mes))
    assert any(m.destino == mes / "EMITIDAS" / "2 (2).pdf" for m in plano.movimentos)
