"""PDF para Word e PDF para Excel.

Word: o próprio Word instalado abre o PDF (ele tem um conversor de PDF para documento editável) e
salva como .docx. Fica bom em documentos de texto; layouts com colunas e muitos gráficos mudam.

Excel: as tabelas de cada página são lidas pela posição do texto e gravadas numa planilha, com os
números no formato brasileiro ("1.234,56") virando números de verdade. PDF escaneado precisa do OCR antes.
"""
from __future__ import annotations

import io
import logging
import re
import shutil
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from pypdf import PdfWriter

from unepdf.core import office
from unepdf.core.erros import ErroUnePDF, OperacaoCancelada
from unepdf.core.gravacao import gravar_arquivo_gerado
from unepdf.core.leitor_pdf import PdfInvalido, ler_pdf
from unepdf.core.modelos import ArquivoIgnorado
from unepdf.core.progresso import CallbackProgresso, Cancelamento
from unepdf.core.renderizacao import DocumentoRenderizavel
from unepdf.utils.programas import office_instalado

log = logging.getLogger(__name__)

WORD_AUSENTE = (
    "Esta ferramenta usa o conversor de PDF do Microsoft Word, que não foi encontrado neste computador.\n\n"
    "Ela funciona com o Word 2013 ou mais novo instalado."
)
SEM_TEXTO = "PDF sem texto (escaneado): passe pelo OCR antes"
MINIMO_DE_CARACTERES = 25
LARGURA_MAXIMA_COLUNA = 60


def word_disponivel() -> str | None:
    return None if office_instalado("Word.Application") else WORD_AUSENTE


@dataclass
class ResultadoConversao:
    pasta: Path
    gerados: list[Path] = field(default_factory=list)
    ignorados: list[ArquivoIgnorado] = field(default_factory=list)
    substituidos: int = 0
    pendentes: int = 0
    paginas_sem_tabela: int = 0  # só no Excel

    @property
    def cancelado(self) -> bool:
        return self.pendentes > 0


def _tem_texto(dados: bytes) -> bool:
    with DocumentoRenderizavel(dados) as documento:
        return any(
            len(re.sub(r"\s", "", documento.extrair_texto(indice))) >= MINIMO_DE_CARACTERES
            for indice in range(documento.total)
        )


def _copia_legivel(caminho: Path, pasta_temporaria: Path) -> Path:
    """Cópia do PDF com nome único, sem a senha de permissão, para o Word abrir.

    O Word marca o arquivo que estava abrindo quando foi fechado à força e, da vez seguinte, pergunta
    se quer recuperar os dados. Com uma cópia, o arquivo do usuário nunca fica marcado.
    """
    try:
        leitor, dados = ler_pdf(caminho)
    except PdfInvalido as erro:
        raise ErroUnePDF(str(erro)) from erro
    if not _tem_texto(dados):
        raise ErroUnePDF(SEM_TEXTO)
    copia = pasta_temporaria / f"unepdf-{uuid.uuid4().hex}.pdf"
    if leitor.is_encrypted:
        escritor = PdfWriter(clone_from=leitor)
        with open(copia, "wb") as arquivo:
            escritor.write(arquivo)
    else:
        copia.write_bytes(dados)
    return copia


@contextmanager
def _sem_aviso_de_conversao(versao: str):
    """Desliga o aviso "Agora o Word converterá o PDF..." enquanto o lote roda e devolve o valor original.

    Com o Word invisível, o aviso fica esperando um clique que nunca vem e a conversão trava.
    """
    try:
        import winreg
    except ImportError:
        yield
        return
    chave = rf"Software\Microsoft\Office\{versao}\Word\Options"
    nome = "DisableConvertPdfWarning"
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, chave) as registro:
            try:
                anterior = winreg.QueryValueEx(registro, nome)
            except OSError:
                anterior = None
            winreg.SetValueEx(registro, nome, 0, winreg.REG_DWORD, 1)
    except OSError:
        log.warning("Não foi possível desligar o aviso de conversão de PDF do Word")
        yield
        return
    try:
        yield
    finally:
        try:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, chave) as registro:
                if anterior is None:
                    winreg.DeleteValue(registro, nome)
                else:
                    winreg.SetValueEx(registro, nome, 0, anterior[1], anterior[0])
        except OSError:
            log.warning("Não foi possível devolver o aviso de conversão de PDF do Word ao valor original")


def _salvar_como_word(instancia: office._InstanciaOffice, copia: Path, saida: Path) -> None:
    documento = instancia.com.Documents.Open(
        str(copia), ConfirmConversions=False, ReadOnly=False, AddToRecentFiles=False, Visible=False,
    )
    try:
        documento.SaveAs2(str(saida), FileFormat=16)  # wdFormatXMLDocument (.docx)
    finally:
        documento.Close(0)


def _converter_um(instancia: office._InstanciaOffice, copia: Path, saida: Path, cancelamento: Cancelamento | None) -> None:
    with office._vigia(instancia, cancelamento, office.LIMITE_POR_ARQUIVO) as motivo:
        try:
            _salvar_como_word(instancia, copia, saida)
            falha = None
        except Exception as erro:
            falha = office._sem_rastro(erro)
    if motivo == ["cancelado"]:
        raise OperacaoCancelada()
    if motivo == ["tempo"]:
        raise ErroUnePDF("o Word parou de responder e foi fechado")
    if falha is not None:
        try:
            _ = instancia.com.Name
        except Exception:
            instancia.com, instancia.pid = None, None
        log.warning("O Word recusou %s: %s", copia, falha)
        raise ErroUnePDF("o Word não conseguiu converter o PDF") from falha
    if not saida.is_file() or saida.stat().st_size == 0:
        raise ErroUnePDF("o Word não gerou o documento")


def pdf_para_word(
    arquivos: list[Path],
    pasta: Path,
    progresso: CallbackProgresso | None = None,
    cancelamento: Cancelamento | None = None,
) -> ResultadoConversao:
    """Um .docx por PDF em `pasta`. Um PDF com problema não interrompe os outros."""
    resultado = ResultadoConversao(pasta)
    instancia = office._InstanciaOffice(office.Aplicativo.WORD)
    com_iniciado = office._iniciar_com()
    with tempfile.TemporaryDirectory(prefix="unepdf-word-", ignore_cleanup_errors=True) as temporaria:
        try:
            for posicao, caminho in enumerate(arquivos):
                if cancelamento and cancelamento.cancelado:
                    resultado.pendentes = len(arquivos) - posicao
                    return resultado
                if progresso:
                    progresso(posicao + 1, len(arquivos), caminho.name)
                destino = pasta / f"{caminho.stem}.docx"
                try:
                    copia = _copia_legivel(caminho, Path(temporaria))
                    instancia.abrir()
                    saida = copia.with_suffix(".docx")
                    with _sem_aviso_de_conversao(instancia.com.Version):
                        _converter_um(instancia, copia, saida, cancelamento)
                    resultado.substituidos += gravar_arquivo_gerado(destino, lambda temporario: shutil.move(saida, temporario))
                except OperacaoCancelada:
                    resultado.pendentes = len(arquivos) - posicao
                    return resultado
                except ErroUnePDF as erro:
                    resultado.ignorados.append(ArquivoIgnorado(caminho, erro.mensagem.replace("\n", " ")))
                    continue
                except Exception:
                    log.exception("Falha ao converter %s para Word", caminho)
                    resultado.ignorados.append(ArquivoIgnorado(caminho, "falha inesperada (detalhes no registro)"))
                    continue
                resultado.gerados.append(destino)
        finally:
            instancia.fechar()
            if com_iniciado:
                office._encerrar_com()
    if not resultado.gerados and not resultado.cancelado:
        raise ErroUnePDF("Nenhum dos PDFs pôde ser convertido.", resultado.ignorados)
    return resultado


# Excel

_NUMERO_BR = re.compile(r"-?(\d{1,3}(\.\d{3})+|\d+),\d+")
_MILHAR_BR = re.compile(r"-?\d{1,3}(\.\d{3})+")
_INTEIRO = re.compile(r"-?[1-9]\d{0,11}|0")
# Tabelas com linhas desenhadas; sem elas, as colunas são deduzidas pelo alinhamento do texto
_POR_LINHAS = {"vertical_strategy": "lines", "horizontal_strategy": "lines"}
_POR_TEXTO = {"vertical_strategy": "text", "horizontal_strategy": "text"}


def valor_da_celula(texto: str | None) -> str | int | float | None:
    """Números brasileiros viram números ("1.234,56" -> 1234.56). Códigos com zero à esquerda, CNPJ,
    datas e números longos (chaves de acesso) continuam texto, para não perderem dígitos."""
    if texto is None:
        return None
    texto = " ".join(texto.split())
    if not texto:
        return None
    sem_moeda = re.sub(r"^R\$\s*", "", texto)
    if _NUMERO_BR.fullmatch(sem_moeda):
        return float(sem_moeda.replace(".", "").replace(",", "."))
    if _MILHAR_BR.fullmatch(sem_moeda) and not sem_moeda.lstrip("-").startswith("0"):
        return int(sem_moeda.replace(".", ""))
    if _INTEIRO.fullmatch(sem_moeda):
        return int(sem_moeda)
    return texto


def _juntar_palavras_cortadas(linha: list[str | None]) -> list[str | None]:
    """Sem linhas desenhadas, uma divisa de coluna pode cair no meio de uma palavra ("nota" | "s do mês"):
    a continuação começa em letra minúscula, colada no fim da célula anterior."""
    linha = list(linha)
    for coluna in range(len(linha) - 1, 0, -1):
        anterior, atual = linha[coluna - 1], linha[coluna]
        if anterior and atual and anterior[-1].isalnum() and atual[0].isalpha() and atual[0].islower():
            linha[coluna - 1], linha[coluna] = anterior + atual, None
    return linha


def _tabelas_da_pagina(pagina) -> list[list[list[str | None]]]:
    tabelas = [t for t in pagina.extract_tables(_POR_LINHAS) if any(any(c for c in linha) for linha in t)]
    if tabelas:
        return tabelas
    # Sem linhas desenhadas: as linhas vazias entre os registros saem, e as palavras cortadas voltam a se juntar
    tabelas = []
    for tabela in pagina.extract_tables(_POR_TEXTO):
        linhas = [_juntar_palavras_cortadas(linha) for linha in tabela if any(c and c.strip() for c in linha)]
        if linhas:
            tabelas.append(linhas)
    return tabelas


def _escrever(aba, linhas: list[list[str | None]], inicio: int) -> int:
    for deslocamento, linha in enumerate(linhas):
        for coluna, texto in enumerate(linha, start=1):
            valor = valor_da_celula(texto)
            if valor is not None:
                celula = aba.cell(row=inicio + deslocamento, column=coluna, value=valor)
                if isinstance(valor, float):
                    celula.number_format = "#,##0.00"
    return inicio + len(linhas)


def _ajustar_larguras(aba) -> None:
    from openpyxl.utils import get_column_letter

    larguras: dict[int, int] = {}
    for linha in aba.iter_rows():
        for celula in linha:
            if celula.value is not None:
                larguras[celula.column] = max(larguras.get(celula.column, 0), len(str(celula.value)))
    for coluna, largura in larguras.items():
        aba.column_dimensions[get_column_letter(coluna)].width = min(max(largura + 2, 8), LARGURA_MAXIMA_COLUNA)


def _planilha(dados: bytes, uma_aba: bool, cancelamento: Cancelamento | None, ao_ler_pagina) -> tuple[object, int, int]:
    """Monta a planilha. Devolve a pasta de trabalho, as páginas com tabela e as sem tabela."""
    import pdfplumber
    from openpyxl import Workbook

    pasta_de_trabalho = Workbook()
    pasta_de_trabalho.remove(pasta_de_trabalho.active)
    unica = pasta_de_trabalho.create_sheet("Tabelas") if uma_aba else None
    proxima_linha = 1
    com_tabela = sem_tabela = 0
    with pdfplumber.open(io.BytesIO(dados)) as pdf:
        for numero, pagina in enumerate(pdf.pages, start=1):
            if cancelamento:
                cancelamento.verificar()
            ao_ler_pagina(numero, len(pdf.pages))
            tabelas = _tabelas_da_pagina(pagina)
            pagina.close()  # libera a memória da página: relatórios podem ter centenas
            if not tabelas:
                sem_tabela += 1
                continue
            com_tabela += 1
            aba = unica or pasta_de_trabalho.create_sheet(f"Página {numero}")
            linha = proxima_linha if unica else 1
            for tabela in tabelas:
                linha = _escrever(aba, tabela, linha) + 1  # uma linha em branco entre tabelas
            if unica:
                proxima_linha = linha
    for aba in pasta_de_trabalho.worksheets:
        _ajustar_larguras(aba)
    return pasta_de_trabalho, com_tabela, sem_tabela


def pdf_para_excel(
    arquivos: list[Path],
    pasta: Path,
    uma_aba: bool = False,
    progresso: CallbackProgresso | None = None,
    cancelamento: Cancelamento | None = None,
) -> ResultadoConversao:
    """Um .xlsx por PDF em `pasta`: uma aba por página com tabela, ou todas as tabelas numa aba só."""
    resultado = ResultadoConversao(pasta)
    for posicao, caminho in enumerate(arquivos):
        if cancelamento and cancelamento.cancelado:
            resultado.pendentes = len(arquivos) - posicao
            return resultado
        destino = pasta / f"{caminho.stem}.xlsx"

        def ao_ler_pagina(pagina: int, total: int, nome: str = caminho.name, posicao: int = posicao) -> None:
            if progresso:
                progresso(posicao + 1, len(arquivos), f"{nome}: página {pagina} de {total}")

        try:
            try:
                _, dados = ler_pdf(caminho)
            except PdfInvalido as erro:
                raise ErroUnePDF(str(erro)) from erro
            planilha, com_tabela, sem_tabela = _planilha(dados, uma_aba, cancelamento, ao_ler_pagina)
            if not com_tabela:
                raise ErroUnePDF("nenhuma tabela encontrada" if _tem_texto(dados) else SEM_TEXTO)
            resultado.substituidos += gravar_arquivo_gerado(destino, lambda temporario: planilha.save(temporario))
            resultado.paginas_sem_tabela += sem_tabela
        except OperacaoCancelada:
            resultado.pendentes = len(arquivos) - posicao
            return resultado
        except ErroUnePDF as erro:
            resultado.ignorados.append(ArquivoIgnorado(caminho, erro.mensagem.replace("\n", " ")))
            continue
        except Exception:
            log.exception("Falha ao converter %s para Excel", caminho)
            resultado.ignorados.append(ArquivoIgnorado(caminho, "falha inesperada (detalhes no registro)"))
            continue
        resultado.gerados.append(destino)
    if not resultado.gerados and not resultado.cancelado:
        raise ErroUnePDF("Nenhum dos PDFs pôde ser convertido.", resultado.ignorados)
    return resultado
