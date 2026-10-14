"""Conversão de PDF para PDF/A (arquivamento de longo prazo) e para versões antigas do PDF.

A conversão é feita de verdade pelo Ghostscript: fontes embutidas, cores convertidas para sRGB
e o perfil de cores incluído no arquivo. O resultado é conferido antes de ser entregue: um
arquivo sem os itens obrigatórios do PDF/A é descartado, nunca apenas "marcado" como PDF/A.
"""
from __future__ import annotations

import logging
import re
import tempfile
from enum import StrEnum
from pathlib import Path

from pypdf import PdfReader

from unepdf.core import ghostscript
from unepdf.core.erros import ErroUnePDF
from unepdf.core.gravacao import gravar_arquivo_gerado
from unepdf.core.leitor_pdf import abrir_pdf_ou_erro
from unepdf.core.modelos import Resultado
from unepdf.core.progresso import CallbackProgresso, Cancelamento

log = logging.getLogger(__name__)


class FormatoSaida(StrEnum):
    PDFA_1B = "PDF/A-1b"
    PDFA_2B = "PDF/A-2b"
    PDFA_3B = "PDF/A-3b"
    PDF_14 = "PDF 1.4"  # PDF comum, para sistemas que não aceitam versões mais novas

    @property
    def parte_pdfa(self) -> int | None:
        return {"PDF/A-1b": 1, "PDF/A-2b": 2, "PDF/A-3b": 3}.get(self.value)


def _definicao_pdfa(perfil_icc: Path) -> str:
    """Programa PostScript que inclui o perfil de cores (OutputIntent), obrigatório no PDF/A."""
    caminho = perfil_icc.as_posix().replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    return "\n".join([
        f"/ICCProfile ({caminho}) def",
        "[/_objdef {icc_PDFA} /type /stream /OBJ pdfmark",
        "[{icc_PDFA} << /N 3 >> /PUT pdfmark",
        "[{icc_PDFA} ICCProfile (r) file /PUT pdfmark",
        "[/_objdef {OutputIntent_PDFA} /type /dict /OBJ pdfmark",
        "[{OutputIntent_PDFA} << /Type /OutputIntent /S /GTS_PDFA1 /DestOutputProfile {icc_PDFA} "
        "/OutputConditionIdentifier (sRGB) >> /PUT pdfmark",
        "[{Catalog} << /OutputIntents [ {OutputIntent_PDFA} ] >> /PUT pdfmark",
    ]) + "\n"


def conferir_pdfa(caminho: Path, parte: int) -> bool:
    """Confere os itens obrigatórios: perfil de cores embutido e identificação PDF/A nos metadados.

    Não substitui um validador completo (como o veraPDF), mas garante que a conversão aconteceu.
    """
    try:
        raiz = PdfReader(caminho).trailer["/Root"]
        intencoes = raiz.get("/OutputIntents")
        perfil = intencoes[0].get_object()["/DestOutputProfile"].get_object() if intencoes else None
        metadados = raiz["/Metadata"].get_object().get_data().decode("utf-8", "replace")
    except Exception:
        return False
    identificado = re.search(rf"pdfaid:part(?:\s*=\s*['\"]{parte}['\"]|>\s*{parte}\s*<)", metadados)
    return perfil is not None and len(perfil.get_data()) > 0 and identificado is not None


def converter(
    origem: Path,
    destino: Path,
    formato: FormatoSaida = FormatoSaida.PDFA_2B,
    progresso: CallbackProgresso | None = None,
    cancelamento: Cancelamento | None = None,
) -> Resultado:
    formato = FormatoSaida(formato)
    total = len(abrir_pdf_ou_erro(origem).pages)  # recusa logo PDFs vazios, corrompidos ou com senha
    raiz_gs = ghostscript.pasta_do_ghostscript()
    if raiz_gs is None:
        raise ErroUnePDF(ghostscript.MENSAGEM_AUSENTE)
    avisos: list[str] = []

    def gerar(temporario: Path) -> None:
        argumentos = ["-sDEVICE=pdfwrite", f"-sOutputFile={temporario}"]
        with tempfile.TemporaryDirectory(prefix="unepdf-") as pasta_temporaria:
            if formato.parte_pdfa is None:
                argumentos += ["-dCompatibilityLevel=1.4", str(origem)]
            else:
                perfil = raiz_gs / "iccprofiles" / "default_rgb.icc"
                if not perfil.is_file():
                    raise ErroUnePDF("A instalação do Ghostscript está incompleta: falta o perfil de cores sRGB.")
                definicao = Path(pasta_temporaria) / "pdfa.ps"
                definicao.write_text(_definicao_pdfa(perfil), encoding="utf-8")
                argumentos += [
                    f"-dPDFA={formato.parte_pdfa}",
                    # Elementos proibidos no PDF/A (ex.: anexos no 1b e no 2b) são retirados, sem abortar
                    "-dPDFACompatibilityPolicy=1",
                    "-sColorConversionStrategy=RGB",
                    f"--permit-file-read={perfil}",
                    str(definicao),
                    str(origem),
                ]
            saida = ghostscript.executar(argumentos, total, progresso, cancelamento)
        avisos.extend(l for l in saida.splitlines() if "PDF/A" in l or "PDFA" in l)
        if formato.parte_pdfa and not conferir_pdfa(temporario, formato.parte_pdfa):
            raise ErroUnePDF(
                f"O Ghostscript não conseguiu gerar um {formato.value} válido a partir deste arquivo, "
                "então nada foi gravado."
            )

    substituiu = gravar_arquivo_gerado(destino, gerar)
    observacao = ""
    if avisos:
        log.warning("Avisos do Ghostscript na conversão de %s:\n%s", origem, "\n".join(avisos))
        observacao = "Alguns elementos que o padrão não permite foram retirados (detalhes no registro de atividades)."
    return Resultado(destino, 1, total, substituiu, observacao=observacao)
