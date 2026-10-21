"""Conversão de documentos do Word, Excel e PowerPoint para PDF.

Usa o Microsoft Office instalado (por automação, sem abrir janelas) e, para o que o Office não
cobre, o LibreOffice. Os dois são programas separados: sem nenhum deles, a ferramenta explica o
que falta. Cada aplicativo do Office é aberto uma vez só para o lote inteiro, em uma instância
própria, então os documentos que o usuário tiver abertos não são afetados.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from unepdf.core.erros import ErroUnePDF, OperacaoCancelada
from unepdf.core.gravacao import gravar_arquivo_gerado
from unepdf.core.localizador import TipoArquivo
from unepdf.core.modelos import ArquivoIgnorado
from unepdf.core.progresso import CallbackProgresso, Cancelamento
from unepdf.core.unir import unir
from unepdf.utils.programas import impressora_pdf_do_windows, localizar_libreoffice, office_instalado

log = logging.getLogger(__name__)

# Um documento que passa disso travou (ex.: o Office abriu uma pergunta invisível) e o programa é fechado
LIMITE_POR_ARQUIVO = 180  # segundos
# Senha que nenhum documento usa: com ela, um arquivo protegido falha na hora em vez de pedir a senha
SENHA_FALSA = "unepdf-sem-senha"
# Arquivos do Office protegidos por senha são gravados em outro formato, que começa assim
ASSINATURA_PROTEGIDO = bytes.fromhex("d0cf11e0a1b11ae1")

MENSAGEM_AUSENTE = (
    "Esta ferramenta precisa do Microsoft Office ou do LibreOffice, e nenhum dos dois foi encontrado "
    "neste computador.\n\nO LibreOffice é gratuito: instale pelo site libreoffice.org e abra esta ferramenta de novo."
)


class Aplicativo(StrEnum):
    WORD = "Word"
    EXCEL = "Excel"
    POWERPOINT = "PowerPoint"


EXTENSOES = {
    Aplicativo.WORD: (".doc", ".docx", ".docm", ".dot", ".dotx", ".rtf", ".odt"),
    Aplicativo.EXCEL: (".xls", ".xlsx", ".xlsm", ".xlsb", ".csv", ".ods"),
    Aplicativo.POWERPOINT: (".ppt", ".pptx", ".pptm", ".pps", ".ppsx", ".odp"),
}
OFFICE = TipoArquivo(
    tuple(e for extensoes in EXTENSOES.values() for e in extensoes),
    "Nenhum documento do Word, Excel ou PowerPoint encontrado",
    "Escolha documentos do Word, Excel ou PowerPoint",
)
_PROG_ID = {Aplicativo.WORD: "Word.Application", Aplicativo.EXCEL: "Excel.Application",
            Aplicativo.POWERPOINT: "PowerPoint.Application"}
_EXECUTAVEL = {Aplicativo.WORD: "winword.exe", Aplicativo.EXCEL: "excel.exe", Aplicativo.POWERPOINT: "powerpnt.exe"}


class Motor(StrEnum):
    OFFICE = "Microsoft Office"
    LIBREOFFICE = "LibreOffice"


def aplicativo_do_arquivo(caminho: Path) -> Aplicativo:
    extensao = caminho.suffix.lower()
    return next(app for app, extensoes in EXTENSOES.items() if extensao in extensoes)


def motores_disponiveis() -> dict[Aplicativo, Motor]:
    """Programa que converte cada tipo: o Office quando o aplicativo existe, senão o LibreOffice."""
    libreoffice = localizar_libreoffice() is not None
    motores = {}
    for app in Aplicativo:
        if office_instalado(_PROG_ID[app]):
            motores[app] = Motor.OFFICE
        elif libreoffice:
            motores[app] = Motor.LIBREOFFICE
    return motores


def disponivel() -> str | None:
    """None quando há como converter algum tipo; senão, o motivo para mostrar ao usuário."""
    return None if motores_disponiveis() else MENSAGEM_AUSENTE


@dataclass
class Preparo:
    """Arquivos que podem ser convertidos, com o programa de cada um, e os que ficam de fora."""

    arquivos: list[tuple[Path, Aplicativo, Motor]]
    ignorados: list[ArquivoIgnorado]


def preparar(arquivos: list[Path], motores: dict[Aplicativo, Motor] | None = None) -> Preparo:
    motores = motores_disponiveis() if motores is None else motores
    validos, ignorados = [], []
    for caminho in arquivos:
        if caminho.name.startswith("~$"):
            # Criado pelo Office enquanto o documento está aberto; não é um documento de verdade
            ignorados.append(ArquivoIgnorado(caminho, "arquivo temporário do Office"))
            continue
        app = aplicativo_do_arquivo(caminho)
        if app not in motores:
            ignorados.append(ArquivoIgnorado(caminho, f"o {app.value} não está instalado (nem o LibreOffice)"))
            continue
        validos.append((caminho, app, motores[app]))
    return Preparo(validos, ignorados)


def nomes_dos_pdfs(arquivos: list[Path]) -> dict[Path, str]:
    """Nome do PDF de cada arquivo: o mesmo nome, com .pdf. Se dois arquivos têm o mesmo nome com
    extensões diferentes (relatorio.docx e relatorio.xlsx), a extensão entra no nome."""
    repetidos = Counter(c.stem.casefold() for c in arquivos)
    return {
        c: f"{c.stem} ({c.suffix.lstrip('.').lower()}).pdf" if repetidos[c.stem.casefold()] > 1 else f"{c.stem}.pdf"
        for c in arquivos
    }


# Microsoft Office


def _processos(executavel: str) -> set[int]:
    """Processos do aplicativo que estão rodando agora."""
    import win32api
    import win32con
    import win32process

    encontrados = set()
    for pid in win32process.EnumProcesses():
        try:
            identificador = win32api.OpenProcess(win32con.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        except Exception:
            continue
        try:
            if os.path.basename(win32process.GetModuleFileNameEx(identificador, 0)).lower() == executavel:
                encontrados.add(pid)
        except Exception:
            pass
        finally:
            win32api.CloseHandle(identificador)
    return encontrados


class _InstanciaOffice:
    """Uma instância invisível de um aplicativo do Office, aberta só para o UnePDF."""

    def __init__(self, app: Aplicativo):
        self.app = app
        self.com = None
        self.pid: int | None = None
        # Nome da impressora virtual como este Excel aceita; False quando não deu para usar
        self.impressora: str | bool | None = None

    def abrir(self):
        if self.com is not None:
            return self.com
        import win32com.client

        antes = _processos(_EXECUTAVEL[self.app])
        com = win32com.client.DispatchEx(_PROG_ID[self.app])
        novos = _processos(_EXECUTAVEL[self.app]) - antes
        self.pid = novos.pop() if len(novos) == 1 else None
        # Macros desligadas e nenhuma pergunta na tela: a conversão não pode ficar esperando o usuário
        com.AutomationSecurity = 3
        if self.app is Aplicativo.WORD:
            com.Visible = False
            com.DisplayAlerts = 0
        elif self.app is Aplicativo.EXCEL:
            com.Visible = False
            com.DisplayAlerts = False
            com.AskToUpdateLinks = False
        else:
            com.DisplayAlerts = 1  # ppAlertsNone
        self.com = com
        return com

    def encerrar_a_forca(self) -> None:
        """Fecha o processo quando ele trava. Sem saber qual processo é o nosso, não fecha nenhum."""
        if self.pid is not None:
            import win32api
            import win32con

            try:
                identificador = win32api.OpenProcess(win32con.PROCESS_TERMINATE, False, self.pid)
                win32api.TerminateProcess(identificador, 1)
                win32api.CloseHandle(identificador)
            except Exception:
                log.warning("Não foi possível encerrar o %s travado (processo %s)", self.app.value, self.pid)
        self.com, self.pid, self.impressora = None, None, None

    def fechar(self) -> None:
        if self.com is None:
            return
        try:
            self.com.Quit()
        except Exception:
            self.encerrar_a_forca()
        self.com, self.pid = None, None


@contextmanager
def _vigia(instancia: _InstanciaOffice, cancelamento: Cancelamento | None, limite: float):
    """Encerra o Office se o documento passar do limite de tempo ou se o usuário cancelar."""
    terminou = threading.Event()
    motivo: list[str] = []

    def vigiar() -> None:
        inicio = time.monotonic()
        while not terminou.wait(0.3):
            if cancelamento and cancelamento.cancelado:
                motivo.append("cancelado")
            elif time.monotonic() - inicio > limite:
                motivo.append("tempo")
            else:
                continue
            instancia.encerrar_a_forca()
            return

    vigilante = threading.Thread(target=vigiar, daemon=True)
    vigilante.start()
    try:
        yield motivo
    finally:
        terminou.set()
        vigilante.join()


def _protegido_por_senha(caminho: Path) -> bool:
    if caminho.suffix.lower() not in (".docx", ".docm", ".xlsx", ".xlsm", ".xlsb", ".pptx", ".pptm", ".ppsx"):
        return False
    with open(caminho, "rb") as arquivo:
        return arquivo.read(8) == ASSINATURA_PROTEGIDO


def _usar_impressora_virtual(instancia: _InstanciaOffice) -> None:
    """O Excel monta as páginas pela impressora padrão. Se ela não responde na hora (comum nas de rede),
    ele abre a janela "Configurar impressora" e a conversão fica parada. A impressora de PDF que vem
    com o Windows sempre responde. A troca vale só para este Excel: a padrão do Windows não muda.
    """
    if instancia.impressora is False:
        return
    com = instancia.com
    if instancia.impressora:
        com.ActivePrinter = instancia.impressora
        return
    virtual = impressora_pdf_do_windows()
    if virtual is None:
        instancia.impressora = False
        return
    nome, porta = virtual
    # O nome leva uma palavra no idioma do Office ("em", "on"...), que vem do nome atual
    conectores = []
    try:
        atual = re.search(r" (\S+) [^ ]+:$", com.ActivePrinter)
        if atual:
            conectores.append(atual[1])
    except Exception:
        pass
    for conector in dict.fromkeys([*conectores, "em", "on"]):
        try:
            com.ActivePrinter = f"{nome} {conector} {porta}"
        except Exception:
            continue
        instancia.impressora = f"{nome} {conector} {porta}"
        return
    log.warning("O Excel não aceitou a impressora de PDF do Windows; usando a padrão")
    instancia.impressora = False


def _exportar_com_office(instancia: _InstanciaOffice, origem: Path, saida: Path) -> None:
    com, app = instancia.com, instancia.app
    if app is Aplicativo.WORD:
        documento = com.Documents.Open(
            str(origem), ConfirmConversions=False, ReadOnly=True, AddToRecentFiles=False,
            PasswordDocument=SENHA_FALSA, WritePasswordDocument=SENHA_FALSA, Visible=False, NoEncodingDialog=True,
        )
        try:
            # Os títulos do documento viram marcadores no PDF
            documento.ExportAsFixedFormat(
                str(saida), 17, OpenAfterExport=False, CreateBookmarks=1, DocStructureTags=True,
            )
        finally:
            documento.Close(0)
    elif app is Aplicativo.EXCEL:
        pasta = com.Workbooks.Open(
            str(origem), UpdateLinks=0, ReadOnly=True, Password=SENHA_FALSA, WriteResPassword=SENHA_FALSA,
            IgnoreReadOnlyRecommended=True, Notify=False, AddToMru=False, Local=True,
        )
        try:
            _usar_impressora_virtual(instancia)
            pasta.ExportAsFixedFormat(0, str(saida), OpenAfterPublish=False)
        finally:
            pasta.Close(False)
    else:
        apresentacao = com.Presentations.Open(str(origem), ReadOnly=True, Untitled=False, WithWindow=False)
        try:
            apresentacao.SaveAs(str(saida), 32)  # ppSaveAsPDF
        finally:
            apresentacao.Close()


def _motivo_da_falha(erro: Exception, app: Aplicativo) -> str:
    texto = str(erro).lower()
    if "senha" in texto or "password" in texto:
        return "protegido por senha"
    if app is Aplicativo.EXCEL and ("impress" in texto or "print" in texto):
        return "a planilha não tem nada para imprimir"
    return f"o {app.value} não conseguiu abrir o arquivo (pode estar corrompido)"


# LibreOffice


def _exportar_com_libreoffice(origem: Path, saida: Path, cancelamento: Cancelamento | None) -> None:
    programa = localizar_libreoffice()
    if programa is None:
        raise ErroUnePDF("O LibreOffice não foi encontrado.")
    with tempfile.TemporaryDirectory(prefix="unepdf-lo-", ignore_cleanup_errors=True) as temporaria:
        temporaria = Path(temporaria)
        # Perfil próprio: não briga com um LibreOffice que o usuário esteja usando
        perfil = (temporaria / "perfil").as_uri()
        comando = [
            str(programa), f"-env:UserInstallation={perfil}", "--headless", "--norestore", "--nolockcheck",
            "--convert-to", "pdf", "--outdir", str(temporaria), str(origem),
        ]
        processo = subprocess.Popen(
            comando, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        inicio = time.monotonic()
        while processo.poll() is None:
            if (cancelamento and cancelamento.cancelado) or time.monotonic() - inicio > LIMITE_POR_ARQUIVO:
                processo.kill()
                processo.wait()
                if cancelamento and cancelamento.cancelado:
                    raise OperacaoCancelada()
                raise ErroUnePDF("o LibreOffice demorou demais e foi fechado")
            time.sleep(0.2)
        gerado = temporaria / f"{origem.stem}.pdf"
        if not gerado.is_file():
            raise ErroUnePDF("o LibreOffice não conseguiu converter o arquivo (pode estar corrompido)")
        shutil.move(gerado, saida)


# Conversão em lote


@dataclass
class ResultadoOffice:
    pasta: Path
    gerados: list[Path] = field(default_factory=list)
    ignorados: list[ArquivoIgnorado] = field(default_factory=list)
    substituidos: int = 0
    juntado: Path | None = None
    paginas_juntado: int = 0
    pendentes: int = 0

    @property
    def cancelado(self) -> bool:
        return self.pendentes > 0


def _iniciar_com() -> bool:
    try:
        import pythoncom
    except ImportError:
        return False
    pythoncom.CoInitialize()
    return True


def _encerrar_com() -> None:
    """Solta os objetos do Office que ainda existam antes de encerrar a automação: liberados depois,
    eles chamam um Office que já fechou e derrubam o Python (erro 0x800706ba)."""
    import gc

    import pythoncom

    gc.collect()
    pythoncom.CoUninitialize()


def _sem_rastro(erro: Exception) -> Exception:
    """O rastro do erro guarda as variáveis do momento, inclusive o documento aberto no Office."""
    erro.__traceback__ = None
    return erro


def converter_documentos(
    preparo: Preparo,
    pasta: Path,
    pdfa: bool = False,
    juntar_em: Path | None = None,
    progresso: CallbackProgresso | None = None,
    cancelamento: Cancelamento | None = None,
) -> ResultadoOffice:
    """Gera um PDF por documento em `pasta` e, se pedido, um PDF com todos em `juntar_em`.

    Com `pdfa`, cada PDF passa pelo Ghostscript e sai em PDF/A-2b. Um documento com problema não
    interrompe os outros; ao cancelar, os PDFs prontos ficam e o resultado informa quantos faltaram.
    """
    from unepdf.core import pdfa as modulo_pdfa

    resultado = ResultadoOffice(pasta, ignorados=list(preparo.ignorados))
    if not preparo.arquivos:
        raise ErroUnePDF("Nenhum dos arquivos pode ser convertido.", resultado.ignorados)

    nomes = nomes_dos_pdfs([caminho for caminho, _, _ in preparo.arquivos])
    instancias = {app: _InstanciaOffice(app) for app in Aplicativo}
    total = len(preparo.arquivos) + (1 if juntar_em else 0)
    com_iniciado = _iniciar_com()
    # Um Office encerrado à força pode segurar arquivos temporários por alguns instantes
    with tempfile.TemporaryDirectory(prefix="unepdf-office-", ignore_cleanup_errors=True) as temporaria:
        try:
            for posicao, (caminho, app, motor) in enumerate(preparo.arquivos):
                if cancelamento and cancelamento.cancelado:
                    resultado.pendentes = len(preparo.arquivos) - posicao
                    return resultado
                if progresso:
                    progresso(posicao + 1, total, caminho.name)
                saida = Path(temporaria) / f"{posicao}.pdf"
                destino = pasta / nomes[caminho]
                try:
                    if not caminho.is_file() or caminho.stat().st_size == 0:
                        raise ErroUnePDF("arquivo vazio (0 KB)" if caminho.is_file() else "arquivo não encontrado")
                    if _protegido_por_senha(caminho):
                        raise ErroUnePDF("protegido por senha")
                    if motor is Motor.OFFICE:
                        _converter_um_com_office(instancias[app], caminho, saida, cancelamento)
                    else:
                        _exportar_com_libreoffice(caminho, saida, cancelamento)
                    if pdfa:
                        convertido = modulo_pdfa.converter(saida, destino, modulo_pdfa.FormatoSaida.PDFA_2B)
                        substituiu = convertido.substituiu_anterior
                    else:
                        substituiu = gravar_arquivo_gerado(destino, lambda temporario: shutil.move(saida, temporario))
                except OperacaoCancelada:
                    resultado.pendentes = len(preparo.arquivos) - posicao
                    return resultado
                except ErroUnePDF as erro:
                    resultado.ignorados.append(ArquivoIgnorado(caminho, erro.mensagem.replace("\n", " ")))
                    continue
                except Exception:
                    log.exception("Falha ao converter %s", caminho)
                    resultado.ignorados.append(ArquivoIgnorado(caminho, "falha inesperada (detalhes no registro)"))
                    continue
                resultado.gerados.append(destino)
                resultado.substituidos += substituiu
        finally:
            for instancia in instancias.values():
                instancia.fechar()
            if com_iniciado:
                _encerrar_com()

    if not resultado.gerados:
        raise ErroUnePDF("Nenhum dos arquivos pôde ser convertido.", resultado.ignorados)
    if juntar_em:
        if progresso:
            progresso(total, total, f"Juntando em {juntar_em.name}")
        try:
            marcadores = [g.stem for g in resultado.gerados]
            juntado = unir(resultado.gerados, juntar_em, cancelamento=cancelamento, marcadores=marcadores)
        except OperacaoCancelada:
            return resultado
        resultado.juntado, resultado.paginas_juntado = juntado.destino, juntado.paginas
    return resultado


def _converter_um_com_office(
    instancia: _InstanciaOffice, caminho: Path, saida: Path, cancelamento: Cancelamento | None
) -> None:
    instancia.abrir()
    with _vigia(instancia, cancelamento, LIMITE_POR_ARQUIVO) as motivo:
        try:
            _exportar_com_office(instancia, caminho, saida)
            falha = None
        except Exception as erro:
            falha = _sem_rastro(erro)
    if motivo == ["cancelado"]:
        raise OperacaoCancelada()
    if motivo == ["tempo"]:
        raise ErroUnePDF(f"o {instancia.app.value} parou de responder e foi fechado")
    if falha is not None:
        try:
            _ = instancia.com.Name
        except Exception:
            # O programa fechou sozinho: o próximo documento abre outra instância
            instancia.com, instancia.pid = None, None
        log.warning("O %s recusou %s: %s", instancia.app.value, caminho, falha)
        raise ErroUnePDF(_motivo_da_falha(falha, instancia.app)) from falha
    if not saida.is_file() or saida.stat().st_size == 0:
        raise ErroUnePDF(f"o {instancia.app.value} não gerou o PDF")
