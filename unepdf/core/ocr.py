"""Reconhecimento de texto (OCR) em PDFs escaneados e imagens, com o Tesseract.

O texto reconhecido entra como uma camada invisível por cima de cada página: a imagem original
não é reprocessada, então a aparência e o tamanho do arquivo quase não mudam, e o texto passa a
ser pesquisável, selecionável e copiável. Páginas que já têm texto ficam como estão.

O Tesseract é um programa separado (licença Apache), chamado por linha de comando.
"""
from __future__ import annotations

import logging
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader, PdfWriter, Transformation

from unepdf.core.erros import ErroUnePDF, OperacaoCancelada
from unepdf.core.gravacao import gravar_com_seguranca
from unepdf.core.imagens import TamanhoPagina, imagens_para_pdf
from unepdf.core.leitor_pdf import PdfInvalido, abrir_pdf, ler_pdf
from unepdf.core.localizador import IMAGEM, TipoArquivo, eh_do_tipo
from unepdf.core.modelos import ArquivoIgnorado
from unepdf.core.progresso import CallbackProgresso, Cancelamento
from unepdf.core.renderizacao import DocumentoRenderizavel
from unepdf.core.unir import unir
from unepdf.utils.programas import localizar_tesseract

log = logging.getLogger(__name__)

DPI = 300  # resolução recomendada pelo Tesseract para texto impresso
LIMITE_POR_PAGINA = 180  # segundos
# Menos que isso não conta como texto (ex.: só o carimbo que alguns scanners põem na página)
MINIMO_DE_CARACTERES = 25

PDF_OU_IMAGEM = TipoArquivo(
    (".pdf", *IMAGEM.extensoes),
    "Nenhum PDF ou imagem encontrado",
    "Escolha PDFs ou imagens escaneadas",
)
MENSAGEM_AUSENTE = (
    "Esta ferramenta precisa do Tesseract, que não foi encontrado neste computador.\n\n"
    "Ele é gratuito: instale a versão para Windows (github.com/UB-Mannheim/tesseract/wiki), "
    "marcando o idioma português, e abra esta ferramenta de novo."
)
MENSAGEM_SEM_PORTUGUES = (
    "O Tesseract está instalado, mas sem o idioma português.\n\n"
    "Instale de novo marcando \"Portuguese\" em \"Additional language data\" e abra esta ferramenta de novo."
)


def idiomas(executavel: Path) -> str | None:
    """Idiomas usados no reconhecimento: português, mais o inglês quando instalado."""
    pasta = executavel.parent / "tessdata"
    if not (pasta / "por.traineddata").is_file():
        return None
    return "por+eng" if (pasta / "eng.traineddata").is_file() else "por"


def disponivel() -> str | None:
    """None quando o OCR pode ser usado; senão, o motivo para mostrar ao usuário."""
    executavel = localizar_tesseract()
    if executavel is None:
        return MENSAGEM_AUSENTE
    return None if idiomas(executavel) else MENSAGEM_SEM_PORTUGUES


def _executar(argumentos: list[str], cancelamento: Cancelamento | None) -> None:
    executavel = localizar_tesseract()
    if executavel is None:
        raise ErroUnePDF(MENSAGEM_AUSENTE)
    processo = subprocess.Popen(
        [str(executavel), *argumentos], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    inicio = time.monotonic()
    while True:
        try:
            _, erros = processo.communicate(timeout=0.3)
            break
        except subprocess.TimeoutExpired:
            cancelado = cancelamento is not None and cancelamento.cancelado
            if cancelado or time.monotonic() - inicio > LIMITE_POR_PAGINA:
                processo.kill()
                processo.communicate()
                if cancelado:
                    raise OperacaoCancelada() from None
                raise ErroUnePDF("o Tesseract demorou demais em uma página e foi interrompido") from None
    if processo.returncode != 0:
        log.warning("Tesseract terminou com código %s: %s", processo.returncode, erros.decode("utf-8", "replace"))
        raise ErroUnePDF("o Tesseract não conseguiu ler a página")


def _imagem_da_pagina(documento: DocumentoRenderizavel, indice: int, destino: Path) -> Path:
    imagem = documento.renderizar(indice, dpi=DPI)
    # Em tons de cinza o reconhecimento é o mesmo e o Tesseract trabalha mais rápido
    Image.frombuffer(
        "RGBX", (imagem.largura, imagem.altura), imagem.dados, "raw", "BGRX", imagem.bytes_por_linha, 1
    ).convert("L").save(destino, "PNG", dpi=(DPI, DPI))
    return destino


def camada_de_texto(imagem: Path, idiomas_ocr: str, cancelamento: Cancelamento | None = None):
    """Página de PDF só com o texto invisível reconhecido na imagem, do tamanho da imagem a 300 dpi."""
    base = imagem.with_suffix("")
    _executar([str(imagem), str(base), "-l", idiomas_ocr, "--dpi", str(DPI), "-c", "textonly_pdf=1", "pdf"],
              cancelamento)
    return PdfReader(base.with_suffix(".pdf")).pages[0]


def reconhecer_texto(imagem: Path, idiomas_ocr: str, cancelamento: Cancelamento | None = None) -> str:
    """Texto reconhecido na imagem, como texto simples."""
    base = imagem.with_name(imagem.stem + "-texto")
    _executar([str(imagem), str(base), "-l", idiomas_ocr, "--dpi", str(DPI), "txt"], cancelamento)
    return base.with_suffix(".txt").read_text(encoding="utf-8").strip()


def tem_texto(documento: DocumentoRenderizavel, indice: int) -> bool:
    return len(re.sub(r"\s", "", documento.extrair_texto(indice))) >= MINIMO_DE_CARACTERES


def _sobrepor(pagina, camada) -> None:
    """Coloca a camada de texto exatamente sobre a área visível da página."""
    if pagina.rotation:
        # O PDFium desenhou a página já girada; o conteúdo passa a ficar na mesma posição
        pagina.transfer_rotation_to_content()
    caixa = pagina.cropbox
    escala_x = float(caixa.width) / float(camada.mediabox.width)
    escala_y = float(caixa.height) / float(camada.mediabox.height)
    transformacao = Transformation().scale(escala_x, escala_y).translate(float(caixa.left), float(caixa.bottom))
    pagina.merge_transformed_page(camada, transformacao)


# Preparação e conversão em lote


@dataclass
class ItemOcr:
    caminho: Path
    paginas: int
    imagem: bool


@dataclass
class PreparoOcr:
    itens: list[ItemOcr]
    ignorados: list[ArquivoIgnorado]

    @property
    def total_paginas(self) -> int:
        return sum(item.paginas for item in self.itens)


def preparar(arquivos: list[Path]) -> PreparoOcr:
    """Confere cada arquivo e conta as páginas, para o progresso mostrar o total certo."""
    itens, ignorados = [], []
    for caminho in arquivos:
        if eh_do_tipo(caminho, IMAGEM):
            try:
                with Image.open(caminho) as imagem:
                    itens.append(ItemOcr(caminho, getattr(imagem, "n_frames", 1), True))
            except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError):
                ignorados.append(ArquivoIgnorado(caminho, "imagem corrompida ou em formato não suportado"))
            continue
        try:
            itens.append(ItemOcr(caminho, len(abrir_pdf(caminho).pages), False))
        except PdfInvalido as erro:
            ignorados.append(ArquivoIgnorado(caminho, str(erro)))
    return PreparoOcr(itens, ignorados)


@dataclass
class ResultadoOcr:
    pasta: Path
    gerados: list[Path] = field(default_factory=list)
    ignorados: list[ArquivoIgnorado] = field(default_factory=list)
    paginas_reconhecidas: int = 0
    paginas_com_texto: int = 0  # já tinham texto e ficaram como estavam
    substituidos: int = 0
    juntado: Path | None = None
    paginas_juntado: int = 0
    pendentes: int = 0

    @property
    def cancelado(self) -> bool:
        return self.pendentes > 0


def nome_do_resultado(caminho: Path) -> str:
    return f"{caminho.stem} - OCR.pdf"


def ocr_documentos(
    preparo: PreparoOcr,
    pasta: Path,
    juntar_em: Path | None = None,
    progresso: CallbackProgresso | None = None,
    cancelamento: Cancelamento | None = None,
) -> ResultadoOcr:
    """Grava uma cópia pesquisável de cada arquivo em `pasta` e, se pedido, todas juntas em `juntar_em`."""
    resultado = ResultadoOcr(pasta, ignorados=list(preparo.ignorados))
    if not preparo.itens:
        raise ErroUnePDF("Nenhum dos arquivos pode passar pelo OCR.", resultado.ignorados)
    executavel = localizar_tesseract()
    idiomas_ocr = idiomas(executavel) if executavel else None
    if not idiomas_ocr:
        raise ErroUnePDF(MENSAGEM_AUSENTE if executavel is None else MENSAGEM_SEM_PORTUGUES)

    total = preparo.total_paginas + (1 if juntar_em else 0)
    passo = 0
    with tempfile.TemporaryDirectory(prefix="unepdf-ocr-", ignore_cleanup_errors=True) as temporaria:
        temporaria = Path(temporaria)
        for posicao, item in enumerate(preparo.itens):
            pasta_item = temporaria / str(posicao)
            pasta_item.mkdir()
            passo_inicial = passo
            try:
                if cancelamento:
                    cancelamento.verificar()
                if item.imagem:
                    origem = imagens_para_pdf([item.caminho], pasta_item / "imagem.pdf", TamanhoPagina.IMAGEM).destino
                else:
                    origem = item.caminho
                leitor, dados = ler_pdf(origem)
                escritor = PdfWriter(clone_from=leitor)
                reconhecidas = com_texto = 0
                with DocumentoRenderizavel(dados) as documento:
                    for indice in range(documento.total):
                        passo += 1
                        if progresso:
                            progresso(passo, total, f"{item.caminho.name}: página {indice + 1} de {documento.total}")
                        if cancelamento:
                            cancelamento.verificar()
                        if tem_texto(documento, indice):
                            com_texto += 1
                            continue
                        imagem = _imagem_da_pagina(documento, indice, pasta_item / f"{indice}.png")
                        _sobrepor(escritor.pages[indice], camada_de_texto(imagem, idiomas_ocr, cancelamento))
                        reconhecidas += 1
                if reconhecidas == 0:
                    raise ErroUnePDF("já tem texto em todas as páginas, não precisa de OCR")
                destino = pasta / nome_do_resultado(item.caminho)
                resultado.substituidos += gravar_com_seguranca(destino, escritor.write)
            except OperacaoCancelada:
                resultado.pendentes = len(preparo.itens) - posicao
                return resultado
            except (ErroUnePDF, PdfInvalido) as erro:
                passo = passo_inicial + item.paginas
                motivo = erro.mensagem if isinstance(erro, ErroUnePDF) else str(erro)
                resultado.ignorados.append(ArquivoIgnorado(item.caminho, motivo.replace("\n", " ")))
                continue
            except Exception:
                passo = passo_inicial + item.paginas
                log.exception("Falha no OCR de %s", item.caminho)
                resultado.ignorados.append(ArquivoIgnorado(item.caminho, "falha inesperada (detalhes no registro)"))
                continue
            resultado.gerados.append(destino)
            resultado.paginas_reconhecidas += reconhecidas
            resultado.paginas_com_texto += com_texto

    if not resultado.gerados:
        raise ErroUnePDF("Nenhum arquivo passou pelo OCR.", resultado.ignorados)
    if juntar_em:
        if progresso:
            progresso(total, total, f"Juntando em {juntar_em.name}")
        try:
            marcadores = [g.name.removesuffix(" - OCR.pdf") for g in resultado.gerados]
            juntado = unir(resultado.gerados, juntar_em, cancelamento=cancelamento, marcadores=marcadores)
        except OperacaoCancelada:
            return resultado
        resultado.juntado, resultado.paginas_juntado = juntado.destino, juntado.paginas
    return resultado
