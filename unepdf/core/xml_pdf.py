"""Geração dos PDFs (DANFE, DANFCe, DACTE, DAMDFE, DANFSe e DACCe) a partir dos XMLs.

O desenho de cada documento é feito pela biblioteca BrazilFiscalReport, que segue os leiautes
oficiais. Aqui ficam as opções, os nomes, a marca de cancelada e a conversão em lote.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from unepdf.core.erros import ErroUnePDF, OperacaoCancelada
from unepdf.core.gravacao import gravar_com_seguranca
from unepdf.core.modelos import ArquivoIgnorado
from unepdf.core.progresso import CallbackProgresso, Cancelamento
from unepdf.core.unir import unir
from unepdf.core.xml_fiscal import AnaliseXml, DocumentoFiscal, TipoDocumento, nomes_dos_pdfs

log = logging.getLogger(__name__)

# Tipos que a biblioteca sabe marcar como cancelados
ACEITAM_MARCA_CANCELADA = {TipoDocumento.DANFE, TipoDocumento.DANFCE, TipoDocumento.DACTE, TipoDocumento.DANFSE}
# Tipos que mostram a logo do emitente
ACEITAM_LOGO = {TipoDocumento.DANFE, TipoDocumento.DANFCE, TipoDocumento.DACTE, TipoDocumento.DAMDFE, TipoDocumento.DACCE}


class Fonte(StrEnum):
    TIMES = "times"
    COURIER = "courier"


@dataclass
class OpcoesDocumento:
    """Ajustes de aparência. Cada um vale só para os documentos que têm aquele recurso."""

    logo: Path | None = None
    fonte: Fonte = Fonte.TIMES
    fonte_grande: bool = False  # DANFE, só com a fonte Times
    casas_decimais: int = 4  # preço unitário e quantidade
    marcar_todos_cancelados: bool = False
    canhoto_no_rodape: bool = False  # DANFE e DACTE
    canhoto_transportador: bool = False  # DANFE
    exibir_pis_cofins: bool = False  # DANFE
    quebrar_linha_no_ponto_e_virgula: bool = False  # informações complementares do DANFE e DANFCe
    exibir_pedido_de_compra: bool = False  # DANFE
    bobina_58mm: bool = False  # DANFCe; o padrão é a bobina de 80 mm
    canhoto_danfse: bool = False


def _configuracao(documento: DocumentoFiscal, opcoes: OpcoesDocumento, cancelada: bool, logo: bytes | None):
    """Objeto de configuração da biblioteca para o tipo do documento."""
    tipo = documento.tipo
    if tipo is TipoDocumento.DANFE:
        from brazilfiscalreport.danfe import (
            DanfeConfig,
            DecimalConfig,
            FontSize,
            FontType,
            ProductDescriptionConfig,
            ReceiptPosition,
        )

        return DanfeConfig(
            logo=logo,
            font_type=FontType.COURIER if opcoes.fonte is Fonte.COURIER else FontType.TIMES,
            font_size=FontSize.BIG if opcoes.fonte_grande else FontSize.SMALL,
            decimal_config=DecimalConfig(opcoes.casas_decimais, opcoes.casas_decimais),
            receipt_pos=ReceiptPosition.BOTTOM if opcoes.canhoto_no_rodape else ReceiptPosition.TOP,
            carrier_receipt=opcoes.canhoto_transportador,
            display_pis_cofins=opcoes.exibir_pis_cofins,
            infcpl_semicolon_newline=opcoes.quebrar_linha_no_ponto_e_virgula,
            product_description_config=ProductDescriptionConfig(display_xped=opcoes.exibir_pedido_de_compra),
            watermark_cancelled=cancelada,
        )
    if tipo is TipoDocumento.DANFCE:
        from brazilfiscalreport.danfce import DanfceConfig, DecimalConfig, FontType

        return DanfceConfig(
            logo=logo,
            font_type=FontType.COURIER if opcoes.fonte is Fonte.COURIER else FontType.TIMES,
            decimal_config=DecimalConfig(opcoes.casas_decimais, opcoes.casas_decimais),
            line_break_char=";" if opcoes.quebrar_linha_no_ponto_e_virgula else None,
            paper_width=58 if opcoes.bobina_58mm else 80,
            watermark_cancelled=cancelada,
        )
    if tipo is TipoDocumento.DACTE:
        from brazilfiscalreport.dacte import DacteConfig, DecimalConfig, FontType, ReceiptPosition

        return DacteConfig(
            logo=logo,
            font_type=FontType.COURIER if opcoes.fonte is Fonte.COURIER else FontType.TIMES,
            decimal_config=DecimalConfig(opcoes.casas_decimais, opcoes.casas_decimais),
            receipt_pos=ReceiptPosition.BOTTOM if opcoes.canhoto_no_rodape else ReceiptPosition.TOP,
            watermark_cancelled=cancelada,
        )
    if tipo is TipoDocumento.DAMDFE:
        from brazilfiscalreport.damdfe import DamdfeConfig, DecimalConfig, FontType

        return DamdfeConfig(
            logo=logo,
            font_type=FontType.COURIER if opcoes.fonte is Fonte.COURIER else FontType.TIMES,
            decimal_config=DecimalConfig(opcoes.casas_decimais, opcoes.casas_decimais),
        )
    if tipo is TipoDocumento.DANFSE:
        from brazilfiscalreport.danfse import DanfseConfig, DecimalConfig

        # A fonte da DANFSe é definida pela norma (equivalente à Arial), por isso não muda
        return DanfseConfig(
            decimal_config=DecimalConfig(price_precision=min(opcoes.casas_decimais, 2)),
            watermark_cancelled=cancelada,
            display_canhoto=opcoes.canhoto_danfse,
        )
    return None


def gerar_pdf(documento: DocumentoFiscal, opcoes: OpcoesDocumento, cancelada: bool = False, logo: bytes | None = None) -> bytes:
    """PDF do documento, pronto para gravar."""
    configuracao = _configuracao(documento, opcoes, cancelada, logo)
    tipo = documento.tipo
    if tipo is TipoDocumento.DANFE:
        from brazilfiscalreport.danfe import Danfe as Gerador
    elif tipo is TipoDocumento.DANFCE:
        from brazilfiscalreport.danfce import Danfce as Gerador
    elif tipo is TipoDocumento.DACTE:
        from brazilfiscalreport.dacte import Dacte as Gerador
    elif tipo is TipoDocumento.DAMDFE:
        from brazilfiscalreport.damdfe import Damdfe as Gerador
    elif tipo is TipoDocumento.DANFSE:
        from brazilfiscalreport.danfse import Danfse as Gerador
    else:
        from brazilfiscalreport.dacce import DaCCe

        return bytes(DaCCe(xml=documento.xml, emitente=documento.endereco_emitente, image=logo).output())
    return bytes(Gerador(documento.xml, config=configuracao).output())


@dataclass
class ResultadoXml:
    pasta: Path
    gerados: list[Path] = field(default_factory=list)
    ignorados: list[ArquivoIgnorado] = field(default_factory=list)
    marcados_cancelados: int = 0
    substituidos: int = 0
    juntado: Path | None = None
    paginas_juntado: int = 0
    pendentes: int = 0  # documentos que ficaram de fora porque o usuário cancelou

    @property
    def cancelado(self) -> bool:
        return self.pendentes > 0


def _ler_logo(caminho: Path | None, ignorados: list[ArquivoIgnorado]) -> bytes | None:
    if caminho is None:
        return None
    try:
        return caminho.read_bytes()
    except OSError:
        log.warning("Logo não encontrada: %s", caminho)
        ignorados.append(ArquivoIgnorado(caminho, "a logo escolhida não foi encontrada; os PDFs saíram sem logo"))
        return None


def converter_xmls(
    analise: AnaliseXml,
    pasta: Path,
    opcoes: OpcoesDocumento | None = None,
    juntar_em: Path | None = None,
    progresso: CallbackProgresso | None = None,
    cancelamento: Cancelamento | None = None,
) -> ResultadoXml:
    """Gera um PDF por documento em `pasta` e, se pedido, um PDF com todos em `juntar_em`.

    Um documento com problema não interrompe os outros. Ao cancelar, os PDFs já gerados ficam
    prontos e o resultado informa quantos faltaram.
    """
    opcoes = opcoes or OpcoesDocumento()
    resultado = ResultadoXml(pasta, ignorados=list(analise.ignorados))
    if not analise.documentos:
        raise ErroUnePDF("Nenhum dos XMLs pôde ser convertido.", resultado.ignorados)

    logo = _ler_logo(opcoes.logo, resultado.ignorados)
    nomes = nomes_dos_pdfs(analise.documentos)
    total = len(analise.documentos) + (1 if juntar_em else 0)

    for posicao, documento in enumerate(analise.documentos):
        try:
            if cancelamento:
                cancelamento.verificar()
        except OperacaoCancelada:
            resultado.pendentes = len(analise.documentos) - posicao
            return resultado
        nome = nomes[documento.identificador]
        if progresso:
            progresso(posicao + 1, total, nome)
        cancelada = documento.tipo in ACEITAM_MARCA_CANCELADA and (
            opcoes.marcar_todos_cancelados or documento.chave in analise.canceladas
        )
        try:
            pdf = gerar_pdf(documento, opcoes, cancelada, logo if documento.tipo in ACEITAM_LOGO else None)
        except Exception:
            log.exception("Falha ao gerar o PDF de %s", documento.caminho)
            resultado.ignorados.append(ArquivoIgnorado(
                documento.caminho, "o XML tem dados que o gerador não conseguiu montar (detalhes no registro)"
            ))
            continue
        destino = pasta / nome
        try:
            if gravar_com_seguranca(destino, lambda arquivo: arquivo.write(pdf)):
                resultado.substituidos += 1
        except ErroUnePDF as erro:
            resultado.ignorados.append(ArquivoIgnorado(documento.caminho, erro.mensagem.replace("\n", " ")))
            continue
        resultado.gerados.append(destino)
        resultado.marcados_cancelados += cancelada

    if not resultado.gerados:
        raise ErroUnePDF("Nenhum dos XMLs pôde ser convertido.", resultado.ignorados)

    if juntar_em:
        if progresso:
            progresso(total, total, f"Juntando em {juntar_em.name}")
        try:
            marcadores = [g.name.removesuffix(" (XML).pdf") for g in resultado.gerados]
            juntado = unir(resultado.gerados, juntar_em, cancelamento=cancelamento, marcadores=marcadores)
        except OperacaoCancelada:
            return resultado
        resultado.juntado, resultado.paginas_juntado = juntado.destino, juntado.paginas
    return resultado
