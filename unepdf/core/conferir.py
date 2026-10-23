"""Conferência das assinaturas digitais de PDFs, no próprio computador.

Para cada assinatura: se o documento continua como foi assinado, se o certificado chega a uma raiz
da ICP-Brasil sem estar revogado e se a cadeia e a confirmação de revogação vão dentro do PDF. Esse
último ponto importa porque o Adobe só reconhece a assinatura quando consegue montar a cadeia, e
nem sempre ele a busca sozinho. Só a consulta à certificadora sai do computador, nunca o documento.

Não substitui o validador do ITI, que também confere as regras formais da ICP-Brasil.
"""
from __future__ import annotations

import asyncio
import io
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path

from unepdf.core import assinatura
from unepdf.core.assinatura import SituacaoCertificado, documento_do_certificado
from unepdf.core.erros import ErroUnePDF
from unepdf.core.localizador import eh_pdf, ordem_natural
from unepdf.core.modelos import ArquivoIgnorado
from unepdf.core.separar import formatar_documento

log = logging.getLogger(__name__)


class Alteracao(Enum):
    NENHUMA = "nenhuma"
    PERMITIDA = "permitida"  # outra assinatura, preenchimento de formulário ou comentário depois
    PROIBIDA = "proibida"  # o conteúdo mudou depois da assinatura


@dataclass
class AssinaturaConferida:
    titular: str  # sem o documento, ex.: "EMPRESA EXEMPLO LTDA"
    documento: str  # CNPJ ou CPF formatado (vazio se o certificado não informar)
    quando: datetime | None  # data declarada por quem assinou (o relógio do computador dele)
    integra: bool  # o trecho assinado não mudou e a assinatura confere com o certificado
    alteracao: Alteracao
    situacao: SituacaoCertificado
    cadeia_no_pdf: bool
    revogacao_no_pdf: bool

    @property
    def valida(self) -> bool:
        return self.integra and self.alteracao is not Alteracao.PROIBIDA and self.situacao is SituacaoCertificado.VALIDO


@dataclass
class PdfConferido:
    caminho: Path
    assinaturas: list[AssinaturaConferida]


@dataclass
class ResultadoConferencia:
    documentos: list[PdfConferido] = field(default_factory=list)
    sem_assinatura: list[Path] = field(default_factory=list)
    ignorados: list[ArquivoIgnorado] = field(default_factory=list)
    pendentes: int = 0

    @property
    def cancelado(self) -> bool:
        return self.pendentes > 0


def selecionar_pdfs(caminhos: list[Path]) -> list[Path]:
    """PDFs escolhidos ou que estão direto nas pastas escolhidas. A pasta de saída também vale:
    é nela que ficam os PDFs assinados pelo app."""
    arquivos: list[Path] = []
    for caminho in caminhos:
        if caminho.is_dir():
            arquivos += sorted((p for p in caminho.iterdir() if p.is_file() and eh_pdf(p)), key=ordem_natural)
        elif eh_pdf(caminho):
            arquivos.append(caminho)
    vistos: set[Path] = set()
    unicos = [a for a in arquivos if not (a.resolve() in vistos or vistos.add(a.resolve()))]
    if not unicos:
        raise ErroUnePDF("Nenhum PDF encontrado. Escolha PDFs assinados ou a pasta onde eles estão.")
    return unicos


def _alteracao(status) -> Alteracao:
    from pyhanko.sign.diff_analysis import ModificationLevel
    from pyhanko.sign.validation.status import SignatureCoverageLevel

    nivel = status.modification_level
    if status.coverage not in (SignatureCoverageLevel.ENTIRE_FILE, SignatureCoverageLevel.ENTIRE_REVISION):
        return Alteracao.PROIBIDA
    if nivel is None or nivel == ModificationLevel.OTHER or not status.docmdp_ok:
        return Alteracao.PROIBIDA
    if nivel in (ModificationLevel.FORM_FILLING, ModificationLevel.ANNOTATIONS):
        return Alteracao.PERMITIDA
    return Alteracao.NENHUMA


async def _conferir_assinatura(assinatura_pdf, raizes, certificados_dss, revogacao_no_dss, buscador) -> AssinaturaConferida:
    from cryptography import x509
    from pyhanko.sign.validation import async_validate_pdf_signature
    from pyhanko_certvalidator import ValidationContext

    quando = assinatura_pdf.self_reported_timestamp
    # Como o Adobe: o certificado é conferido na data da assinatura, para um certificado já vencido
    # não invalidar o que foi assinado enquanto ele valia
    contexto = ValidationContext(
        trust_roots=raizes, other_certs=certificados_dss, allow_fetching=True, revocation_mode="soft-fail",
        moment=quando, retroactive_revinfo=True, fetcher_backend=buscador,
    )
    status = await async_validate_pdf_signature(assinatura_pdf, contexto)

    certificado = assinatura_pdf.signer_cert
    nome_comum = certificado.subject.native.get("common_name") or certificado.subject.human_friendly
    documento = documento_do_certificado(x509.load_der_x509_certificate(certificado.dump()), nome_comum)

    no_pdf = {c.dump() for c in assinatura_pdf.other_embedded_certs} | {c.dump() for c in certificados_dss}
    caminho = status.validation_path
    cadeia_no_pdf = caminho is not None and all(
        c.dump() in no_pdf for c in caminho.iter_certs(include_root=False) if c.dump() != certificado.dump()
    )
    atributos = assinatura_pdf.signer_info["signed_attrs"]
    revogacao_no_pdf = revogacao_no_dss or any(
        a["type"].native == "adobe_revocation_info_archival" for a in atributos
    )

    if status.revoked:
        situacao = SituacaoCertificado.REVOGADO
    elif status.trusted:
        situacao = SituacaoCertificado.VALIDO
    elif not cadeia_no_pdf and assinatura.sem_conexao():
        situacao = SituacaoCertificado.NAO_CONFERIDO
    else:
        situacao = SituacaoCertificado.CADEIA_DESCONHECIDA

    return AssinaturaConferida(
        titular=re.sub(r":\d{11,14}$", "", nome_comum),
        documento=formatar_documento(documento),
        quando=quando,
        integra=status.intact and status.valid,
        alteracao=_alteracao(status),
        situacao=situacao,
        cadeia_no_pdf=cadeia_no_pdf,
        revogacao_no_pdf=revogacao_no_pdf,
    )


def conferir_pdf(caminho: Path, raizes: list | None = None) -> PdfConferido:
    """Confere todas as assinaturas do PDF. Erro de leitura ou PDF com senha vira ErroUnePDF."""
    from pyhanko.pdf_utils.reader import PdfFileReader
    from pyhanko.sign.validation.dss import DocumentSecurityStore
    from pyhanko.sign.validation.errors import NoDSSFoundError
    from pyhanko_certvalidator.fetchers.aiohttp_fetchers import AIOHttpFetcherBackend

    try:
        dados = caminho.read_bytes()
    except OSError as erro:
        raise ErroUnePDF(f"Não foi possível ler: {erro.strerror or erro}") from erro
    try:
        # Sem o modo estrito: PDFs gerados pelo Word têm referências "híbridas", que o modo estrito recusa
        leitor = PdfFileReader(io.BytesIO(dados), strict=False)
        if leitor.encrypted:
            raise ErroUnePDF("PDF protegido por senha")
        assinaturas = list(leitor.embedded_regular_signatures)
    except ErroUnePDF:
        raise
    except Exception as erro:
        raise ErroUnePDF("arquivo corrompido ou não é um PDF") from erro
    if not assinaturas:
        return PdfConferido(caminho, [])

    try:
        dss = DocumentSecurityStore.read_dss(leitor)
        certificados_dss = list(dss.load_certs())
        revogacao_no_dss = bool(dss.ocsps or dss.crls)
    except NoDSSFoundError:
        certificados_dss, revogacao_no_dss = [], False
    raizes = assinatura.raizes_icp_brasil() if raizes is None else raizes

    async def conferir_todas() -> list[AssinaturaConferida]:
        buscador = AIOHttpFetcherBackend(per_request_timeout=15)
        try:
            return [
                await _conferir_assinatura(a, raizes, certificados_dss, revogacao_no_dss, buscador) for a in assinaturas
            ]
        finally:
            await buscador.close()

    try:
        return PdfConferido(caminho, asyncio.run(conferir_todas()))
    except Exception as erro:
        log.exception("Falha ao conferir as assinaturas de %s", caminho)
        raise ErroUnePDF("não foi possível conferir as assinaturas (detalhes no registro de atividades)") from erro


def conferir_assinaturas(arquivos: list[Path], progresso=None, cancelamento=None) -> ResultadoConferencia:
    resultado = ResultadoConferencia()
    raizes = assinatura.raizes_icp_brasil()
    for indice, arquivo in enumerate(arquivos):
        if cancelamento and cancelamento.cancelado:
            resultado.pendentes = len(arquivos) - indice
            return resultado
        if progresso:
            progresso(indice + 1, len(arquivos), arquivo.name)
        try:
            conferido = conferir_pdf(arquivo, raizes)
        except ErroUnePDF as erro:
            resultado.ignorados.append(ArquivoIgnorado(arquivo, erro.mensagem.replace("\n", " ")))
            continue
        if conferido.assinaturas:
            resultado.documentos.append(conferido)
        else:
            resultado.sem_assinatura.append(arquivo)
    return resultado
