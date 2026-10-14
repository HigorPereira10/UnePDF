"""Leitura e identificação de XMLs de documentos fiscais eletrônicos.

O tipo de cada arquivo é descoberto pelo conteúdo (namespace, modelo e tipo de evento),
nunca pelo nome. Arquivos que não geram PDF voltam com o motivo em linguagem do usuário.
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from xml.etree.ElementTree import Element, ParseError

from defusedxml import DefusedXmlException
from defusedxml.ElementTree import fromstring

from unepdf.core.modelos import ArquivoIgnorado
from unepdf.core.nomenclatura import limpar_nome
from unepdf.core.progresso import CallbackProgresso, Cancelamento

log = logging.getLogger(__name__)

NFE = "http://www.portalfiscal.inf.br/nfe"
CTE = "http://www.portalfiscal.inf.br/cte"
MDFE = "http://www.portalfiscal.inf.br/mdfe"
NFSE = "http://www.sped.fazenda.gov.br/nfse"

EVENTO_CCE = "110110"
EVENTOS_CANCELAMENTO = ("110111", "110112")  # cancelamento e cancelamento por substituição (NFC-e)
# Evento registrado na SEFAZ: vinculado (135), não vinculado (136) e fora de prazo (155)
STATUS_REGISTRADO = ("135", "136", "155")

TAMANHO_MAXIMO_EMPRESA = 80  # caracteres; evita caminhos longos demais no Windows


class TipoDocumento(StrEnum):
    DANFE = "DANFE"
    DANFCE = "DANFCE"
    DACTE = "DACTE"
    DAMDFE = "DAMDFE"
    DANFSE = "DANFSE"
    DACCE = "DACCE"


ORDEM_TIPOS = list(TipoDocumento)


class XmlNaoReconhecido(ValueError):
    """XML que não vira PDF. A mensagem é o motivo exibido ao usuário."""


@dataclass
class DocumentoFiscal:
    caminho: Path
    tipo: TipoDocumento
    xml: str  # texto do XML, entregue ao gerador do PDF
    chave: str
    numero: int
    serie: int
    emitente: str  # razão social; vazio na carta de correção, que só traz o CNPJ
    cnpj_emitente: str
    sequencia: int = 1  # sequência do evento, na carta de correção
    endereco_emitente: dict[str, str] = field(default_factory=dict)

    @property
    def identificador(self) -> str:
        """Identifica o documento para achar repetidos: a mesma nota em dois arquivos."""
        return f"{self.chave}-{self.sequencia}" if self.tipo is TipoDocumento.DACCE else self.chave


@dataclass(frozen=True)
class EventoCancelamento:
    caminho: Path
    chave: str


@dataclass
class AnaliseXml:
    documentos: list[DocumentoFiscal]
    canceladas: set[str]  # chaves com evento de cancelamento na seleção
    ignorados: list[ArquivoIgnorado]

    def contagem(self) -> dict[TipoDocumento, int]:
        quantidades: dict[TipoDocumento, int] = defaultdict(int)
        for documento in self.documentos:
            quantidades[documento.tipo] += 1
        return {tipo: quantidades[tipo] for tipo in ORDEM_TIPOS if quantidades[tipo]}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _namespace(tag: str) -> str:
    return tag[1:].split("}", 1)[0] if tag.startswith("{") else ""


def _texto(no: Element | None, caminho: str, ns: str) -> str:
    """Texto da tag no caminho (ex.: "ide/nNF"), ou vazio quando ela não existe."""
    if no is None:
        return ""
    alvo = no.find("/".join(f"{{{ns}}}{parte}" for parte in caminho.split("/")))
    return (alvo.text or "").strip() if alvo is not None else ""


def _inteiro(texto: str) -> int:
    return int(texto) if texto.isdecimal() else 0


def _decodificar(dados: bytes) -> str:
    """Texto do XML na codificação declarada (UTF-8 quando não há declaração)."""
    declaracao = re.match(rb'\s*<\?xml[^>]*encoding=["\']([\w.-]+)["\']', dados.lstrip(b"\xef\xbb\xbf"))
    codificacao = declaracao.group(1).decode("ascii") if declaracao else "utf-8"
    return dados.decode(codificacao).lstrip("﻿")


def _endereco(emit: Element, ns: str) -> dict[str, str]:
    """Dados do emitente da NF-e, usados no cabeçalho da carta de correção da mesma nota."""
    logradouro = ", ".join(p for p in (_texto(emit, "enderEmit/xLgr", ns), _texto(emit, "enderEmit/nro", ns)) if p)
    cep = _texto(emit, "enderEmit/CEP", ns)
    return {
        "nome": _texto(emit, "xNome", ns),
        "end": logradouro,
        "bairro": _texto(emit, "enderEmit/xBairro", ns),
        "cep": f"{cep[:5]}-{cep[5:]}" if len(cep) == 8 else cep,
        "cidade": _texto(emit, "enderEmit/xMun", ns),
        "uf": _texto(emit, "enderEmit/UF", ns),
        "fone": _texto(emit, "enderEmit/fone", ns),
        "ie": _texto(emit, "IE", ns),
    }


def _evento(raiz: Element, ns: str, campo_chave: str, caminho: Path, texto: str) -> DocumentoFiscal | EventoCancelamento:
    inf = raiz.find(f".//{{{ns}}}infEvento")
    tipo_evento = _texto(inf, "tpEvento", ns)
    chave = _texto(inf, campo_chave, ns)
    status = ""
    retorno = raiz.find(f".//{{{ns}}}retEvento/{{{ns}}}infEvento")
    if retorno is not None:
        status = _texto(retorno, "cStat", ns)

    if tipo_evento in EVENTOS_CANCELAMENTO:
        if status not in STATUS_REGISTRADO:
            raise XmlNaoReconhecido("pedido de cancelamento sem o registro da SEFAZ")
        return EventoCancelamento(caminho, chave)
    if tipo_evento == EVENTO_CCE and ns == NFE and len(chave) == 44:
        return DocumentoFiscal(
            caminho, TipoDocumento.DACCE, texto, chave,
            numero=int(chave[25:34]), serie=int(chave[22:25]), emitente="",
            cnpj_emitente=_texto(inf, "CNPJ", ns) or _texto(inf, "CPF", ns),
            sequencia=_inteiro(_texto(inf, "nSeqEvento", ns)) or 1,
        )
    descricao = _texto(inf, "detEvento/descEvento", ns)
    raise XmlNaoReconhecido(f'evento sem representação em PDF ({descricao or "tipo " + tipo_evento})')


def _parece_nfse(raiz: Element) -> bool:
    for indice, elemento in enumerate(raiz.iter()):
        if indice > 50:
            return False
        if "nfse" in elemento.tag.lower():
            return True
    return False


def ler_xml(caminho: Path) -> DocumentoFiscal | EventoCancelamento:
    """Lê um XML e diz o que ele é. Lança XmlNaoReconhecido com o motivo quando não gera PDF."""
    try:
        dados = caminho.read_bytes()
    except OSError as erro:
        raise XmlNaoReconhecido(f"não foi possível ler o arquivo ({erro.strerror or erro})") from erro
    if not dados.strip():
        raise XmlNaoReconhecido("arquivo vazio (0 KB)")
    try:
        # defusedxml recusa XMLs montados para travar o programa (entidades que se multiplicam)
        raiz = fromstring(dados)
        texto = _decodificar(dados)
    except (ParseError, DefusedXmlException, ValueError, LookupError) as erro:
        raise XmlNaoReconhecido("XML corrompido ou incompleto") from erro

    ns, nome = _namespace(raiz.tag), _local(raiz.tag)

    if ns == NFE:
        if nome in ("resNFe", "resEvento"):
            raise XmlNaoReconhecido("resumo da nota, sem os itens e valores: baixe o XML completo")
        inf = raiz.find(f".//{{{NFE}}}infNFe")
        if inf is not None:
            modelo = _texto(inf, "ide/mod", NFE)
            if modelo not in ("55", "65"):
                raise XmlNaoReconhecido(f"modelo {modelo or 'desconhecido'} de nota não suportado")
            emit = inf.find(f"{{{NFE}}}emit")
            return DocumentoFiscal(
                caminho, TipoDocumento.DANFE if modelo == "55" else TipoDocumento.DANFCE, texto,
                inf.get("Id", "").removeprefix("NFe"),
                numero=_inteiro(_texto(inf, "ide/nNF", NFE)), serie=_inteiro(_texto(inf, "ide/serie", NFE)),
                emitente=_texto(emit, "xNome", NFE),
                cnpj_emitente=_texto(emit, "CNPJ", NFE) or _texto(emit, "CPF", NFE),
                endereco_emitente=_endereco(emit, NFE) if emit is not None else {},
            )
        if raiz.find(f".//{{{NFE}}}infEvento") is not None:
            return _evento(raiz, NFE, "chNFe", caminho, texto)

    elif ns == CTE:
        inf = raiz.find(f".//{{{CTE}}}infCte")
        if inf is not None:
            if _texto(inf, "ide/mod", CTE) != "57" or "OS" in nome:
                raise XmlNaoReconhecido("CT-e OS (modelo 67) ainda não é suportado")
            emit = inf.find(f"{{{CTE}}}emit")
            return DocumentoFiscal(
                caminho, TipoDocumento.DACTE, texto, inf.get("Id", "").removeprefix("CTe"),
                numero=_inteiro(_texto(inf, "ide/nCT", CTE)), serie=_inteiro(_texto(inf, "ide/serie", CTE)),
                emitente=_texto(emit, "xNome", CTE), cnpj_emitente=_texto(emit, "CNPJ", CTE),
            )
        if raiz.find(f".//{{{CTE}}}infEvento") is not None:
            return _evento(raiz, CTE, "chCTe", caminho, texto)

    elif ns == MDFE:
        inf = raiz.find(f".//{{{MDFE}}}infMDFe")
        if inf is not None:
            emit = inf.find(f"{{{MDFE}}}emit")
            return DocumentoFiscal(
                caminho, TipoDocumento.DAMDFE, texto, inf.get("Id", "").removeprefix("MDFe"),
                numero=_inteiro(_texto(inf, "ide/nMDF", MDFE)), serie=_inteiro(_texto(inf, "ide/serie", MDFE)),
                emitente=_texto(emit, "xNome", MDFE), cnpj_emitente=_texto(emit, "CNPJ", MDFE),
            )
        if raiz.find(f".//{{{MDFE}}}infEvento") is not None:
            raise XmlNaoReconhecido("evento de MDF-e, sem representação em PDF")

    elif ns == NFSE:
        inf = raiz.find(f".//{{{NFSE}}}infNFSe")
        if inf is not None:
            emit = inf.find(f"{{{NFSE}}}emit")
            return DocumentoFiscal(
                caminho, TipoDocumento.DANFSE, texto, inf.get("Id", "").removeprefix("NFS"),
                numero=_inteiro(_texto(inf, "nNFSe", NFSE)),
                serie=_inteiro(_texto(inf, "DPS/infDPS/serie", NFSE)),
                emitente=_texto(emit, "xNome", NFSE), cnpj_emitente=_texto(emit, "CNPJ", NFSE),
            )
        raise XmlNaoReconhecido("XML do padrão nacional da NFS-e sem a nota autorizada (só a DPS ou um evento)")

    if _parece_nfse(raiz):
        raise XmlNaoReconhecido(
            "NFS-e no padrão próprio da prefeitura. Só o padrão nacional da NFS-e é aceito"
        )
    raise XmlNaoReconhecido("não é XML de documento fiscal eletrônico")


def analisar(
    arquivos: list[Path],
    progresso: CallbackProgresso | None = None,
    cancelamento: Cancelamento | None = None,
) -> AnaliseXml:
    """Lê todos os XMLs da seleção. Arquivos com problema vão para os ignorados, sem interromper."""
    documentos: list[DocumentoFiscal] = []
    cancelamentos: list[EventoCancelamento] = []
    ignorados: list[ArquivoIgnorado] = []
    vistos: dict[str, Path] = {}

    for posicao, caminho in enumerate(arquivos, start=1):
        if cancelamento:
            cancelamento.verificar()
        if progresso:
            progresso(posicao, len(arquivos), caminho.name)
        try:
            lido = ler_xml(caminho)
        except XmlNaoReconhecido as erro:
            ignorados.append(ArquivoIgnorado(caminho, str(erro)))
            continue
        except Exception:
            log.exception("Falha inesperada ao ler %s", caminho)
            ignorados.append(ArquivoIgnorado(caminho, "XML ilegível"))
            continue
        if isinstance(lido, EventoCancelamento):
            cancelamentos.append(lido)
        elif lido.identificador in vistos:
            ignorados.append(ArquivoIgnorado(caminho, f'mesmo documento de "{vistos[lido.identificador].name}"'))
        else:
            vistos[lido.identificador] = caminho
            documentos.append(lido)

    chaves = {d.chave for d in documentos if d.tipo is not TipoDocumento.DACCE}
    for evento in cancelamentos:
        if evento.chave not in chaves:
            ignorados.append(ArquivoIgnorado(
                evento.caminho, "evento de cancelamento de um documento que não está na seleção"
            ))
    documentos.sort(key=lambda d: (ORDEM_TIPOS.index(d.tipo), d.emitente.casefold(), d.serie, d.numero, d.sequencia))
    return AnaliseXml(documentos, {e.chave for e in cancelamentos}, ignorados)


def completar_cartas_de_correcao(analise: AnaliseXml) -> None:
    """A carta de correção só traz o CNPJ: nome e endereço vêm da NF-e, quando ela está na seleção."""
    notas = {d.chave: d for d in analise.documentos if d.tipo is TipoDocumento.DANFE}
    for documento in analise.documentos:
        nota = notas.get(documento.chave) if documento.tipo is TipoDocumento.DACCE else None
        if nota:
            documento.emitente = nota.emitente
            documento.endereco_emitente = nota.endereco_emitente


def nomes_dos_pdfs(documentos: list[DocumentoFiscal]) -> dict[str, str]:
    """Nome do PDF de cada documento (pelo identificador), sem repetir nomes.

    Ex.: "DANFE 1234 - EMPRESA EXEMPLO LTDA (XML).pdf". Quando dois documentos dariam o mesmo nome,
    os dois recebem a série; se ainda assim repetir, um número no fim.
    """
    def base(documento: DocumentoFiscal, com_serie: bool) -> str:
        empresa = limpar_nome(documento.emitente or f"CNPJ {documento.cnpj_emitente}")[:TAMANHO_MAXIMO_EMPRESA].strip()
        numero = f"{documento.numero} série {documento.serie}" if com_serie else str(documento.numero)
        nome = f"{documento.tipo.value} {numero} - {empresa}"
        if documento.tipo is TipoDocumento.DACCE and documento.sequencia > 1:
            nome += f" - correção {documento.sequencia}"
        return nome

    grupos: dict[str, list[DocumentoFiscal]] = defaultdict(list)
    for documento in documentos:
        grupos[base(documento, False).casefold()].append(documento)

    nomes: dict[str, str] = {}
    usados: set[str] = set()
    for documento in documentos:
        nome = base(documento, len(grupos[base(documento, False).casefold()]) > 1)
        final, contador = nome, 2
        while final.casefold() in usados:
            final, contador = f"{nome} ({contador})", contador + 1
        usados.add(final.casefold())
        nomes[documento.identificador] = f"{final} (XML).pdf"
    return nomes
