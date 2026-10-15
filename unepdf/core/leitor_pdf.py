"""Leitura e validação individual de cada PDF antes de ser usado por uma ferramenta."""
from __future__ import annotations

import io
import logging
from pathlib import Path

from pypdf import PdfReader

from unepdf.core.erros import ErroUnePDF

# O pypdf registra avisos para PDFs levemente fora do padrão que não afetam o resultado.
# Mantemos só erros reais para não poluir o log.
logging.getLogger("pypdf").setLevel(logging.ERROR)


class PdfInvalido(ValueError):
    """PDF que não pode ser usado. A mensagem é o motivo exibido ao usuário."""


def abrir_pdf(caminho: Path) -> PdfReader:
    """Lê o PDF inteiro para a memória e confirma que ele pode ser usado.

    Ler para a memória evita manter centenas de arquivos abertos na rede
    durante a operação. Lança PdfInvalido com o motivo quando o arquivo não serve.
    """
    return ler_pdf(caminho)[0]


def ler_pdf(caminho: Path) -> tuple[PdfReader, bytes]:
    """Como abrir_pdf, devolvendo também os bytes lidos (ex.: para gerar miniaturas sem ler de novo)."""
    try:
        dados = caminho.read_bytes()
    except OSError as erro:
        raise PdfInvalido(f"não foi possível ler o arquivo ({erro.strerror or erro})") from erro

    if not dados:
        raise PdfInvalido("arquivo vazio (0 KB)")

    try:
        leitor = PdfReader(io.BytesIO(dados))

        # PDFs com senha só de permissão abrem com senha em branco; os demais são recusados
        if leitor.is_encrypted and not leitor.decrypt(""):
            raise PdfInvalido("protegido por senha")

        # Acessa cada página para detectar corrupção agora, e não no meio da gravação
        for pagina in leitor.pages:
            _ = pagina.mediabox
        total_paginas = len(leitor.pages)
    except PdfInvalido:
        raise
    except Exception as erro:
        raise PdfInvalido("arquivo corrompido ou ilegível") from erro

    if total_paginas == 0:
        raise PdfInvalido("PDF sem páginas")

    return leitor, dados


def tem_assinatura(leitor: PdfReader) -> bool:
    """Indica se o PDF tem alguma assinatura digital. Qualquer alteração no arquivo a invalida."""
    try:
        campos = leitor.get_fields() or {}
    except Exception:
        return False
    return any(campo.get("/FT") == "/Sig" and campo.get("/V") is not None for campo in campos.values())


def abrir_pdf_ou_erro(caminho: Path) -> PdfReader:
    """Como abrir_pdf, para ferramentas que trabalham com um arquivo só: o problema vira ErroUnePDF."""
    return ler_pdf_ou_erro(caminho)[0]


def ler_pdf_ou_erro(caminho: Path) -> tuple[PdfReader, bytes]:
    try:
        return ler_pdf(caminho)
    except PdfInvalido as erro:
        raise ErroUnePDF(f'Não foi possível usar o arquivo "{caminho.name}": {erro}.') from erro
