"""Ferramenta Conferir assinaturas: mostra se as assinaturas digitais de PDFs valem e se o Adobe as reconhece."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QBrush, QColor, QDesktopServices
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from unepdf.core import conferir
from unepdf.core.assinatura import SituacaoCertificado
from unepdf.core.conferir import Alteracao, AssinaturaConferida, ResultadoConferencia
from unepdf.core.erros import ErroUnePDF
from unepdf.ui.componentes import AreaSoltar, PainelProgresso
from unepdf.ui.contexto import ContextoApp
from unepdf.ui.dialogos import mostrar_erro
from unepdf.ui.ferramentas.base import TelaFerramenta
from unepdf.ui.tema import CORES
from unepdf.utils import sistema
from unepdf.utils.texto import plural

if TYPE_CHECKING:
    from unepdf.ui.ferramentas import Ferramenta

VALIDADOR_ITI = "https://validar.iti.gov.br"
OK, ATENCAO, PROBLEMA, NEUTRO = "ok", "atencao", "problema", "neutro"
_CORES = {OK: CORES.sucesso, ATENCAO: CORES.aviso, PROBLEMA: CORES.erro, NEUTRO: CORES.texto_suave}


def itens_da_assinatura(assinatura: AssinaturaConferida) -> list[tuple[str, str]]:
    """O que foi conferido, em frases curtas, cada uma com o nível (ok, atenção ou problema)."""
    itens = []
    if not assinatura.integra:
        itens.append((PROBLEMA, "A assinatura não confere: o trecho assinado foi modificado."))
    elif assinatura.alteracao is Alteracao.PROIBIDA:
        itens.append((PROBLEMA, "O documento foi alterado depois da assinatura."))
    elif assinatura.alteracao is Alteracao.PERMITIDA:
        itens.append((OK, "Depois dela, só entraram outras assinaturas ou preenchimentos, o que é permitido."))
    else:
        itens.append((OK, "O documento não foi alterado depois da assinatura."))

    itens.append({
        SituacaoCertificado.VALIDO: (OK, "Certificado válido na ICP-Brasil na data da assinatura."),
        SituacaoCertificado.REVOGADO: (PROBLEMA, "Certificado revogado pela certificadora antes da assinatura."),
        SituacaoCertificado.CADEIA_DESCONHECIDA: (PROBLEMA, "O certificado não chega a uma raiz da ICP-Brasil."),
        SituacaoCertificado.NAO_CONFERIDO: (
            ATENCAO, "Não deu para conferir o certificado na certificadora (sem internet, ou ela não respondeu)."),
    }[assinatura.situacao])

    if assinatura.cadeia_no_pdf:
        itens.append((OK, "A cadeia do certificado está dentro do PDF: o Adobe consegue conferir sozinho."))
    else:
        itens.append((ATENCAO, "A cadeia do certificado não está dentro do PDF: o Adobe pode mostrar a assinatura "
                               "como inválida. Assine de novo pelo UnePDF."))
    if assinatura.revogacao_no_pdf:
        itens.append((OK, "A confirmação de que o certificado não estava revogado está dentro do PDF."))
    else:
        itens.append((ATENCAO, "Sem a confirmação de revogação dentro do PDF: a assinatura fica mais difícil de "
                               "conferir depois que o certificado vencer."))
    return itens


def resumo_da_assinatura(assinatura: AssinaturaConferida) -> tuple[str, str]:
    if not assinatura.valida:
        if assinatura.integra and assinatura.situacao is SituacaoCertificado.NAO_CONFERIDO:
            return ATENCAO, "Não conferida"
        return PROBLEMA, "Com problema"
    if not assinatura.cadeia_no_pdf:
        return ATENCAO, "Válida, mas incompleta para o Adobe"
    return OK, "Válida"


class TelaConferirAssinaturas(TelaFerramenta):
    aceita_arquivos = True

    def __init__(self, ferramenta: Ferramenta, contexto: ContextoApp):
        super().__init__(ferramenta, contexto)
        self.area = AreaSoltar(
            "Arraste PDFs assinados ou uma pasta para cá",
            "Cada assinatura é conferida no próprio computador: o PDF não é enviado para nenhum site.",
            texto_arquivos="Escolher PDFs",
        )
        self.area.caminhos_soltos.connect(self.receber_caminhos)
        self.area.escolher_pasta.connect(self._escolher_pasta)
        self.area.escolher_arquivos.connect(self._escolher_arquivos)
        self.progresso = PainelProgresso()
        self.progresso.cancelar.connect(self.executor.cancelar)
        self.executor.progresso.connect(self.progresso.atualizar)

        self.estados = QStackedWidget()
        for painel in (self.area, self.progresso, self._montar_painel_resultado()):
            self.estados.addWidget(painel)
        self.corpo.addWidget(self.estados)

    def _montar_painel_resultado(self) -> QWidget:
        self.titulo = QLabel()
        self.titulo.setObjectName("tituloResultado")
        self.resumo = QLabel()
        self.resumo.setObjectName("subtitulo")
        self.resumo.setWordWrap(True)
        textos = QVBoxLayout()
        textos.setSpacing(2)
        textos.addWidget(self.titulo)
        textos.addWidget(self.resumo)

        self.arvore = QTreeWidget()
        self.arvore.setHeaderLabels(["Arquivo e assinaturas", "Resultado"])
        self.arvore.setWordWrap(True)
        self.arvore.header().setStretchLastSection(False)
        self.arvore.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.arvore.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.arvore.itemDoubleClicked.connect(self._abrir_item)

        dica = QLabel(
            "Clique duas vezes em um arquivo para abri-lo. Esta conferência não substitui o validador oficial do ITI, "
            "que também confere as regras formais da ICP-Brasil."
        )
        dica.setObjectName("subtitulo")
        dica.setWordWrap(True)
        iti = QPushButton("Abrir o validador do ITI")
        iti.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(VALIDADOR_ITI)))
        novo = QPushButton("Conferir outros PDFs")
        novo.setObjectName("botaoPrincipal")
        novo.clicked.connect(self.limpar)
        rodape = QHBoxLayout()
        rodape.addWidget(iti)
        rodape.addStretch()
        rodape.addWidget(novo)

        painel = QWidget()
        layout = QVBoxLayout(painel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addLayout(textos)
        layout.addWidget(self.arvore, 1)
        layout.addWidget(dica)
        layout.addLayout(rodape)
        self.painel_resultado = painel
        return painel

    # Escolha dos PDFs

    def _pasta_para_dialogo(self) -> str:
        for candidata in (self.contexto.config.ultima_pasta, self.contexto.config.pasta_inicial):
            if candidata and Path(candidata).is_dir():
                return candidata
        return ""

    def _escolher_pasta(self) -> None:
        pasta = QFileDialog.getExistingDirectory(self, "Escolha a pasta com os PDFs assinados", self._pasta_para_dialogo())
        if pasta:
            self.receber_caminhos([Path(pasta)])

    def _escolher_arquivos(self) -> None:
        arquivos, _ = QFileDialog.getOpenFileNames(self, "Escolha os PDFs", self._pasta_para_dialogo(), "Arquivos PDF (*.pdf)")
        if arquivos:
            self.receber_caminhos([Path(a) for a in arquivos])

    def receber_caminhos(self, caminhos: list[Path]) -> None:
        if self.executor.em_execucao:
            return
        self.area.mostrar_aviso(None)
        try:
            arquivos = conferir.selecionar_pdfs(caminhos)
        except ErroUnePDF as erro:
            self.area.mostrar_aviso(str(erro))
            return
        pasta = str(arquivos[0].parent)
        if self.contexto.config.ultima_pasta != pasta:
            self.contexto.config.ultima_pasta = pasta
            self.contexto.salvar_config()
        self.progresso.iniciar("Conferindo as assinaturas...")
        self.estados.setCurrentWidget(self.progresso)
        self.executar(
            lambda progresso, cancelamento: conferir.conferir_assinaturas(arquivos, progresso, cancelamento),
            self._mostrar_resultado,
            self._ao_falhar,
        )

    def _ao_falhar(self, erro: BaseException) -> None:
        self.limpar()
        mostrar_erro(self, erro)

    def limpar(self) -> None:
        self.area.mostrar_aviso(None)
        self.estados.setCurrentWidget(self.area)

    # Resultado

    @staticmethod
    def _linha(textos: list[str], nivel: str, caminho: Path | None = None) -> QTreeWidgetItem:
        linha = QTreeWidgetItem(textos)
        cor = QBrush(QColor(_CORES[nivel]))
        linha.setForeground(1 if len(textos) > 1 else 0, cor)
        if caminho:
            linha.setData(0, Qt.ItemDataRole.UserRole, str(caminho))
            linha.setToolTip(0, str(caminho))
        return linha

    def _mostrar_resultado(self, resultado: ResultadoConferencia) -> None:
        self.arvore.clear()
        assinaturas = [a for d in resultado.documentos for a in d.assinaturas]
        niveis = [resumo_da_assinatura(a)[0] for a in assinaturas]
        for documento in resultado.documentos:
            piores = [resumo_da_assinatura(a)[0] for a in documento.assinaturas]
            nivel = PROBLEMA if PROBLEMA in piores else ATENCAO if ATENCAO in piores else OK
            linha_pdf = self._linha(
                [documento.caminho.name, plural(len(documento.assinaturas), "assinatura", "assinaturas")],
                nivel, documento.caminho,
            )
            for assinatura in documento.assinaturas:
                quem = assinatura.titular + (f" ({assinatura.documento})" if assinatura.documento else "")
                if assinatura.quando:
                    quem += f", {assinatura.quando.astimezone():%d/%m/%Y %H:%M}"
                nivel_assinatura, texto = resumo_da_assinatura(assinatura)
                linha_assinatura = self._linha([quem, texto], nivel_assinatura)
                for nivel_item, frase in itens_da_assinatura(assinatura):
                    item = self._linha([frase], nivel_item)
                    item.setToolTip(0, frase)
                    linha_assinatura.addChild(item)
                linha_pdf.addChild(linha_assinatura)
            self.arvore.addTopLevelItem(linha_pdf)
            # As frases do que foi conferido usam a largura toda, sem a coluna de resultado
            for i in range(linha_pdf.childCount()):
                linha_assinatura = linha_pdf.child(i)
                for j in range(linha_assinatura.childCount()):
                    linha_assinatura.child(j).setFirstColumnSpanned(True)
        for arquivo in resultado.sem_assinatura:
            self.arvore.addTopLevelItem(self._linha([arquivo.name, "Sem assinatura digital"], NEUTRO, arquivo))
        for ignorado in resultado.ignorados:
            linha = self._linha([ignorado.caminho.name, "Não conferido"], ATENCAO, ignorado.caminho)
            linha.addChild(self._linha([ignorado.motivo], ATENCAO))
            self.arvore.addTopLevelItem(linha)
        self.arvore.expandAll()

        conferidos = len(resultado.documentos) + len(resultado.sem_assinatura) + len(resultado.ignorados)
        self.titulo.setText("Conferência interrompida" if resultado.cancelado else
                            plural(conferidos, "PDF conferido", "PDFs conferidos"))
        partes = []
        if assinaturas:
            validas = sum(a.valida for a in assinaturas)
            incompletas = sum(a.valida and not a.cadeia_no_pdf for a in assinaturas)
            nao_conferidas = len(assinaturas) - validas - niveis.count(PROBLEMA)
            partes.append(plural(len(assinaturas), "assinatura", "assinaturas") + ": "
                          + plural(validas, "válida", "válidas"))
            if incompletas:
                partes.append(plural(incompletas, "incompleta para o Adobe", "incompletas para o Adobe"))
            if niveis.count(PROBLEMA):
                partes.append(f"{niveis.count(PROBLEMA)} com problema")
            if nao_conferidas:
                partes.append(plural(nao_conferidas, "não conferida", "não conferidas"))
        if resultado.sem_assinatura:
            partes.append(plural(len(resultado.sem_assinatura), "PDF sem assinatura", "PDFs sem assinatura"))
        if resultado.cancelado:
            partes.append(f"{plural(resultado.pendentes, 'PDF ficou', 'PDFs ficaram')} sem conferir")
        self.resumo.setText(". ".join(partes) + "." if partes else "")
        self.estados.setCurrentWidget(self.painel_resultado)

    def _abrir_item(self, item: QTreeWidgetItem) -> None:
        caminho = item.data(0, Qt.ItemDataRole.UserRole)
        if caminho:
            try:
                sistema.abrir_arquivo(Path(caminho))
            except Exception as erro:
                mostrar_erro(self, erro, "Não foi possível abrir")
