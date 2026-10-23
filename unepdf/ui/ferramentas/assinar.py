"""Ferramenta Assinar PDF: assinatura digital com certificado A1 (.pfx), com carimbo na página."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from unepdf.core import assinatura
from unepdf.core.assinatura import Certificado, PosicaoCarimbo, SituacaoCertificado
from unepdf.core.erros import ErroUnePDF
from unepdf.core.leitor_pdf import ler_pdf_ou_erro
from unepdf.core.localizador import Selecao, montar_selecao
from unepdf.core.nomenclatura import destino_derivado
from unepdf.core.renderizacao import DocumentoRenderizavel
from unepdf.ui.componentes import AreaSoltar, PainelProgresso, PainelResultado
from unepdf.ui.contexto import ContextoApp
from unepdf.ui.dialogos import mostrar_erro
from unepdf.ui.ferramentas.arquivo_unico import ATRASO_PROGRESSO_MS
from unepdf.ui.ferramentas.base import TelaFerramenta
from unepdf.ui.tema import CORES
from unepdf.utils.caminhos import arquivo_registro_assinaturas
from unepdf.utils.texto import plural

if TYPE_CHECKING:
    from unepdf.ui.ferramentas import Ferramenta

LARGURA_PREVIA = 420


def _ajuda(texto: str = "") -> QLabel:
    rotulo = QLabel(texto)
    rotulo.setObjectName("subtitulo")
    rotulo.setWordWrap(True)
    return rotulo


def _rotulo_campo(texto: str) -> QLabel:
    rotulo = QLabel(texto)
    rotulo.setObjectName("rotuloCampo")
    return rotulo


def para_tela(x: float, y: float, caixa: tuple, rotacao: int, largura: int, altura: int) -> tuple[float, float]:
    """Ponto da página (em pontos) na imagem da prévia, que mostra a página já girada."""
    esquerda, base, direita, topo = caixa
    fx, fy = (x - esquerda) / (direita - esquerda), (y - base) / (topo - base)
    u, v = {0: (fx, 1 - fy), 90: (fy, fx), 180: (1 - fx, fy), 270: (1 - fy, 1 - fx)}[rotacao % 360]
    return u * largura, v * altura


def para_pagina(u: float, v: float, caixa: tuple, rotacao: int, largura: int, altura: int) -> tuple[float, float]:
    """Inverso de `para_tela`: um clique na prévia vira um ponto da página."""
    esquerda, base, direita, topo = caixa
    fu, fv = u / largura, v / altura
    fx, fy = {0: (fu, 1 - fv), 90: (fv, fu), 180: (1 - fu, fv), 270: (1 - fv, 1 - fu)}[rotacao % 360]
    return esquerda + fx * (direita - esquerda), base + fy * (topo - base)


class PreviaCarimbo(QLabel):
    """Imagem da página com o lugar do carimbo marcado. Um clique leva o carimbo para o ponto clicado."""

    clicado = Signal(float, float)  # ponto da página, em pontos

    def __init__(self):
        super().__init__()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self._pagina: QImage | None = None
        self._caixa: tuple = (0, 0, 1, 1)
        self._rotacao = 0
        self._carimbo: tuple | None = None

    def mostrar(self, dados: bytes, posicao: PosicaoCarimbo | None, pagina: int) -> None:
        with DocumentoRenderizavel(dados) as documento:
            imagem = documento.renderizar(pagina, largura=LARGURA_PREVIA)
            self._caixa = documento.caixa_visivel(pagina)
            self._rotacao = documento.rotacao(pagina)
        # Na página girada de lado, a largura da imagem corresponde à altura da página
        self._pagina = QImage(
            imagem.dados, imagem.largura, imagem.altura, imagem.bytes_por_linha, QImage.Format.Format_RGB32
        ).copy()
        self._carimbo = posicao.caixa if posicao and posicao.pagina == pagina else None
        self._desenhar()

    def _desenhar(self) -> None:
        if self._pagina is None:
            return
        imagem = QPixmap.fromImage(self._pagina)
        if self._carimbo:
            x1, y1, x2, y2 = self._carimbo
            cantos = [para_tela(x, y, self._caixa, self._rotacao, imagem.width(), imagem.height())
                      for x, y in ((x1, y1), (x2, y2))]
            retangulo = QRectF(QPointF(*cantos[0]), QPointF(*cantos[1])).normalized()
            pintor = QPainter(imagem)
            cor = QColor(CORES.destaque)
            pintor.setPen(QPen(cor, 2))
            cor.setAlpha(60)
            pintor.fillRect(retangulo, cor)
            pintor.drawRect(retangulo)
            pintor.end()
        self.setPixmap(imagem)

    def mousePressEvent(self, evento: QMouseEvent) -> None:
        imagem = self.pixmap()
        if self._pagina is None or imagem is None or imagem.isNull():
            return
        # A imagem fica centralizada no rótulo
        u = evento.position().x() - (self.width() - imagem.width()) / 2
        v = evento.position().y() - (self.height() - imagem.height()) / 2
        if 0 <= u <= imagem.width() and 0 <= v <= imagem.height():
            self.clicado.emit(*para_pagina(u, v, self._caixa, self._rotacao, imagem.width(), imagem.height()))


@dataclass
class _Preparo:
    selecao: Selecao
    dados: bytes | None  # do único PDF escolhido, para a prévia
    total_paginas: int
    posicao: PosicaoCarimbo | None


class TelaAssinar(TelaFerramenta):
    aceita_arquivos = True

    def __init__(self, ferramenta: Ferramenta, contexto: ContextoApp):
        super().__init__(ferramenta, contexto)
        self._preparo: _Preparo | None = None
        self._certificado: Certificado | None = None
        self._situacao: SituacaoCertificado | None = None
        self._caminho_certificado: Path | None = None
        self._pagina_previa = 0

        self.area = AreaSoltar(
            "Arraste os PDFs para assinar",
            "Assine com o certificado A1 (.pfx). Vários PDFs do mesmo titular podem ser assinados de uma vez.",
            texto_arquivos="Escolher PDFs",
        )
        self.area.caminhos_soltos.connect(self.receber_caminhos)
        self.area.escolher_pasta.connect(self._escolher_pasta)
        self.area.escolher_arquivos.connect(self._escolher_arquivos)
        self.progresso = PainelProgresso()
        self.progresso.cancelar.connect(self.executor.cancelar)
        self.executor.progresso.connect(self.progresso.atualizar)
        self.resultado = PainelResultado("Assinar outros PDFs")
        self.resultado.novo.connect(self.limpar)

        self.estados = QStackedWidget()
        for painel in (self.area, self._montar_painel(), self.progresso, self.resultado):
            self.estados.addWidget(painel)
        self.corpo.addWidget(self.estados)

        self._timer_progresso = QTimer(self)
        self._timer_progresso.setSingleShot(True)
        self._timer_progresso.timeout.connect(lambda: self.estados.setCurrentWidget(self.progresso))

    def _montar_painel(self) -> QWidget:
        self.resumo_selecao = QLabel()
        self.resumo_selecao.setObjectName("tituloResultado")
        self.resumo_selecao.setWordWrap(True)
        trocar = QPushButton("Trocar seleção")
        trocar.clicked.connect(self.limpar)
        cabecalho = QHBoxLayout()
        cabecalho.addWidget(self.resumo_selecao, 1)
        cabecalho.addWidget(trocar)

        # Esquerda: prévia da página (um PDF) ou lista (vários)
        self.previa = PreviaCarimbo()
        self.previa.clicado.connect(self._mover_carimbo)
        self.botao_anterior = QPushButton("◀")
        self.botao_anterior.clicked.connect(lambda: self._mudar_pagina(-1))
        self.botao_proxima = QPushButton("▶")
        self.botao_proxima.clicked.connect(lambda: self._mudar_pagina(1))
        self.rotulo_pagina = QLabel()
        self.rotulo_pagina.setAlignment(Qt.AlignmentFlag.AlignCenter)
        navegacao = QHBoxLayout()
        navegacao.addWidget(self.botao_anterior)
        navegacao.addWidget(self.rotulo_pagina, 1)
        navegacao.addWidget(self.botao_proxima)
        self.dica_previa = _ajuda("Clique na página para mudar o lugar do carimbo.")
        self.painel_previa = QWidget()
        layout_previa = QVBoxLayout(self.painel_previa)
        layout_previa.setContentsMargins(0, 0, 0, 0)
        layout_previa.addWidget(self.previa, 1)
        layout_previa.addLayout(navegacao)
        layout_previa.addWidget(self.dica_previa)
        self.lista = QListWidget()
        self.lista.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.esquerda = QStackedWidget()
        self.esquerda.addWidget(self.painel_previa)
        self.esquerda.addWidget(self.lista)

        # Direita: certificado e opções
        self.botao_certificado = QPushButton("Escolher certificado (.pfx)")
        self.botao_certificado.clicked.connect(self._escolher_certificado)
        self.rotulo_certificado = _ajuda("Nenhum certificado escolhido")
        self.campo_senha = QLineEdit()
        self.campo_senha.setEchoMode(QLineEdit.EchoMode.Password)
        self.campo_senha.setPlaceholderText("Senha do certificado")
        self.campo_senha.returnPressed.connect(self._abrir_certificado)
        self.botao_abrir = QPushButton("Abrir")
        self.botao_abrir.clicked.connect(self._abrir_certificado)
        linha_senha = QHBoxLayout()
        linha_senha.addWidget(self.campo_senha, 1)
        linha_senha.addWidget(self.botao_abrir)
        self.dados_certificado = QLabel()
        self.dados_certificado.setWordWrap(True)
        self.dados_certificado.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.situacao_certificado = QLabel()
        self.situacao_certificado.setWordWrap(True)
        self.aviso_certificado = QLabel()
        self.aviso_certificado.setObjectName("aviso")
        self.aviso_certificado.setWordWrap(True)

        self.opcao_visivel = QRadioButton("Carimbo na página")
        self.opcao_invisivel = QRadioButton("Assinatura invisível (só no painel de assinaturas do leitor)")
        grupo = QButtonGroup(self)
        grupo.addButton(self.opcao_visivel)
        grupo.addButton(self.opcao_invisivel)
        self.opcao_visivel.setChecked(True)
        self.opcao_visivel.toggled.connect(self._ao_mudar_visibilidade)

        self.destino_selecao = QLabel()
        self.destino_selecao.setWordWrap(True)
        self.aviso_selecao = QLabel()
        self.aviso_selecao.setObjectName("aviso")
        self.aviso_selecao.setWordWrap(True)
        self.botao_assinar = QPushButton("Assinar")
        self.botao_assinar.setObjectName("botaoPrincipal")
        self.botao_assinar.clicked.connect(self._assinar)

        direita = QFrame()
        direita.setFixedWidth(380)
        layout_direita = QVBoxLayout(direita)
        layout_direita.setContentsMargins(0, 0, 0, 0)
        layout_direita.setSpacing(6)
        layout_direita.addWidget(_rotulo_campo("CERTIFICADO"))
        layout_direita.addWidget(self.botao_certificado)
        layout_direita.addWidget(self.rotulo_certificado)
        layout_direita.addLayout(linha_senha)
        layout_direita.addWidget(self.dados_certificado)
        layout_direita.addWidget(self.situacao_certificado)
        layout_direita.addWidget(self.aviso_certificado)
        layout_direita.addSpacing(10)
        layout_direita.addWidget(_rotulo_campo("CARIMBO"))
        layout_direita.addWidget(self.opcao_visivel)
        layout_direita.addWidget(self.opcao_invisivel)
        layout_direita.addSpacing(10)
        layout_direita.addWidget(_rotulo_campo("SERÁ SALVO EM"))
        layout_direita.addWidget(self.destino_selecao)
        layout_direita.addStretch()
        layout_direita.addWidget(self.aviso_selecao)
        layout_direita.addWidget(self.botao_assinar)

        meio = QHBoxLayout()
        meio.setSpacing(20)
        meio.addWidget(self.esquerda, 1)
        meio.addWidget(direita)

        painel = QWidget()
        layout = QVBoxLayout(painel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addLayout(cabecalho)
        layout.addLayout(meio, 1)
        self.painel_selecao = painel
        return painel

    # Escolha dos PDFs

    def _pasta_para_dialogo(self) -> str:
        for candidata in (self.contexto.config.ultima_pasta, self.contexto.config.pasta_inicial):
            if candidata and Path(candidata).is_dir():
                return candidata
        return ""

    def _escolher_pasta(self) -> None:
        pasta = QFileDialog.getExistingDirectory(self, "Escolha a pasta com os PDFs", self._pasta_para_dialogo())
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
        pasta_saida = self.contexto.config.pasta_saida

        def preparar(progresso, cancelamento) -> _Preparo:
            selecao = montar_selecao(caminhos, pasta_saida)
            if len(selecao.arquivos) != 1:
                return _Preparo(selecao, None, 0, None)
            leitor, dados = ler_pdf_ou_erro(selecao.arquivos[0])
            return _Preparo(selecao, dados, len(leitor.pages), assinatura.posicao_automatica(dados))

        self.progresso.iniciar("Lendo os arquivos...", cancelavel=False)
        self._timer_progresso.start(ATRASO_PROGRESSO_MS)
        self.executar(preparar, self._mostrar_selecao, self._ao_falhar_preparo)

    def _ao_falhar_preparo(self, erro: BaseException) -> None:
        self._timer_progresso.stop()
        self.limpar()
        if isinstance(erro, ErroUnePDF):
            self.area.mostrar_aviso(str(erro))
        else:
            mostrar_erro(self, erro)

    def _mostrar_selecao(self, preparo: _Preparo) -> None:
        self._timer_progresso.stop()
        self._preparo = preparo
        arquivos = preparo.selecao.arquivos
        if self.contexto.config.ultima_pasta != str(preparo.selecao.base):
            self.contexto.config.ultima_pasta = str(preparo.selecao.base)
            self.contexto.salvar_config()
        if preparo.dados is not None:
            self.resumo_selecao.setText(arquivos[0].name)
            self._pagina_previa = preparo.posicao.pagina
            self.esquerda.setCurrentWidget(self.painel_previa)
        else:
            self.resumo_selecao.setText(plural(len(arquivos), "PDF para assinar", "PDFs para assinar"))
            self.lista.clear()
            self.lista.addItems([a.name for a in arquivos])
            self.esquerda.setCurrentWidget(self.lista)
        self.destino_selecao.setText(str(self._destino(arquivos[0]).parent))
        self._ao_mudar_visibilidade()
        self._atualizar_estado()
        self.estados.setCurrentWidget(self.painel_selecao)
        if self._certificado:
            # Mesmo certificado, documentos novos: refaz a conferência do CNPJ
            self._abrir_certificado()

    def _destino(self, origem: Path) -> Path:
        return destino_derivado(origem, "assinado", self.contexto.config.pasta_saida)

    # Prévia e posição do carimbo

    def _atualizar_previa(self) -> None:
        preparo = self._preparo
        if not preparo or preparo.dados is None:
            return
        visivel = self.opcao_visivel.isChecked()
        self.previa.mostrar(preparo.dados, preparo.posicao if visivel else None, self._pagina_previa)
        self.rotulo_pagina.setText(f"Página {self._pagina_previa + 1} de {preparo.total_paginas}")
        self.botao_anterior.setEnabled(self._pagina_previa > 0)
        self.botao_proxima.setEnabled(self._pagina_previa < preparo.total_paginas - 1)
        self.dica_previa.setVisible(visivel)

    def _mudar_pagina(self, passo: int) -> None:
        if self._preparo and self._preparo.dados is not None:
            self._pagina_previa = max(0, min(self._preparo.total_paginas - 1, self._pagina_previa + passo))
            self._atualizar_previa()

    def _mover_carimbo(self, x: float, y: float) -> None:
        if not self._preparo or not self.opcao_visivel.isChecked():
            return
        self._preparo.posicao = assinatura.mover_carimbo(self._preparo.posicao, self._pagina_previa, x, y)
        self._atualizar_previa()

    def _ao_mudar_visibilidade(self) -> None:
        self._atualizar_previa()
        if self._preparo and self._preparo.dados is None:
            texto = (
                "Em cada PDF, o carimbo vai sobre a última linha de assinatura (ou no pé da última página)."
                if self.opcao_visivel.isChecked() else ""
            )
            self.aviso_selecao.setText(texto)

    # Certificado

    def _escolher_certificado(self) -> None:
        inicial = self.contexto.config.pasta_certificados
        caminho, _ = QFileDialog.getOpenFileName(
            self, "Escolha o certificado A1", inicial if inicial and Path(inicial).is_dir() else "",
            "Certificado A1 (*.pfx *.p12)",
        )
        if not caminho:
            return
        self._caminho_certificado = Path(caminho)
        self._certificado = None
        self.rotulo_certificado.setText(self._caminho_certificado.name)
        self.dados_certificado.clear()
        self.situacao_certificado.clear()
        self.aviso_certificado.clear()
        self.campo_senha.clear()
        self.campo_senha.setFocus()
        pasta = str(self._caminho_certificado.parent)
        if self.contexto.config.pasta_certificados != pasta:
            self.contexto.config.pasta_certificados = pasta
            self.contexto.salvar_config()
        self._atualizar_estado()

    def _abrir_certificado(self) -> None:
        if not self._caminho_certificado or not self._preparo or self.executor.em_execucao:
            return
        caminho, senha = self._caminho_certificado, self.campo_senha.text()
        arquivos = list(self._preparo.selecao.arquivos)

        def abrir(progresso, cancelamento):
            certificado = assinatura.abrir_certificado(caminho, senha)
            ausente = []
            for arquivo in arquivos:
                try:
                    if not assinatura.documento_aparece(ler_pdf_ou_erro(arquivo)[1], certificado.documento):
                        ausente.append(arquivo.name)
                except ErroUnePDF:
                    pass
            situacao = None if certificado.vencido else assinatura.conferir_certificado(certificado)
            return certificado, ausente, situacao

        self.situacao_certificado.clear()
        self.aviso_certificado.setText("Abrindo e conferindo o certificado...")
        self.executar(abrir, lambda r: self._ao_abrir_certificado(*r), self._ao_falhar_certificado)

    def _mostrar_situacao(self, situacao: SituacaoCertificado | None) -> None:
        textos = {
            SituacaoCertificado.VALIDO: (
                CORES.sucesso, "Válido na ICP-Brasil: cadeia e revogação conferidas na certificadora."),
            SituacaoCertificado.REVOGADO: (
                CORES.erro, "Revogado pela certificadora: este certificado não pode mais assinar."),
            SituacaoCertificado.CADEIA_DESCONHECIDA: (
                CORES.aviso, "Não foi possível ligar este certificado a uma raiz da ICP-Brasil. Dá para assinar, "
                "mas o Adobe e o validador do ITI podem não reconhecer a assinatura."),
            SituacaoCertificado.NAO_CONFERIDO: (
                CORES.aviso, "Não deu para conferir na certificadora (sem internet, ou ela não respondeu). "
                "Dá para assinar normalmente."),
        }
        cor, texto = textos.get(situacao, ("", ""))
        self.situacao_certificado.setStyleSheet(f"color: {cor};" if cor else "")
        self.situacao_certificado.setText(texto)

    def _ao_abrir_certificado(self, certificado: Certificado, ausente: list[str],
                              situacao: SituacaoCertificado | None = None) -> None:
        self._certificado = certificado
        self._situacao = situacao
        self._mostrar_situacao(situacao)
        linhas = [f"<b>{certificado.nome}</b>"]
        if certificado.documento:
            linhas.append(f"{certificado.tipo_documento} {certificado.documento_formatado}")
        linhas.append(f"Emitido por {certificado.emissor}")
        linhas.append(f"Válido até {certificado.valido_ate.astimezone():%d/%m/%Y}")
        self.dados_certificado.setText("<br>".join(linhas))
        avisos = []
        if certificado.vencido:
            avisos.append("Este certificado está vencido e não pode assinar.")
        elif certificado.dias_restantes() <= assinatura.AVISO_VENCIMENTO_DIAS:
            avisos.append(f"Atenção: o certificado vence em {plural(certificado.dias_restantes(), 'dia', 'dias')}.")
        if ausente:
            if len(ausente) == 1 and len(self._preparo.selecao.arquivos) == 1:
                avisos.append(
                    f"O {certificado.tipo_documento or 'documento'} deste certificado não aparece no PDF. "
                    "Confira se é o certificado certo."
                )
            else:
                avisos.append(
                    f"O {certificado.tipo_documento or 'documento'} do certificado não aparece em: "
                    f"{', '.join(ausente)}. Confira se é o certificado certo."
                )
        self.aviso_certificado.setText("\n".join(avisos))
        self._atualizar_estado()

    def _ao_falhar_certificado(self, erro: BaseException) -> None:
        self._certificado = None
        self.dados_certificado.clear()
        self.situacao_certificado.clear()
        if isinstance(erro, ErroUnePDF):
            self.aviso_certificado.setText(str(erro))
        else:
            self.aviso_certificado.clear()
            mostrar_erro(self, erro)
        self._atualizar_estado()

    def _atualizar_estado(self) -> None:
        pronto = (
            self._certificado is not None and not self._certificado.vencido and self._preparo is not None
            and self._situacao is not SituacaoCertificado.REVOGADO
        )
        self.botao_assinar.setEnabled(pronto)
        if self._preparo:
            self.botao_assinar.setText("Assinar " + plural(len(self._preparo.selecao.arquivos), "PDF", "PDFs"))

    def limpar(self) -> None:
        self._preparo = None
        # A senha não fica guardada nem na tela depois de trocar de documentos
        self.campo_senha.clear()
        self._certificado = None
        self._situacao = None
        self.dados_certificado.clear()
        self.situacao_certificado.clear()
        self.aviso_certificado.clear()
        self.aviso_selecao.clear()
        self.area.mostrar_aviso(None)
        self.estados.setCurrentWidget(self.area)

    # Assinatura

    def _assinar(self) -> None:
        if not self._preparo or not self._certificado or self.executor.em_execucao:
            return
        arquivos = list(self._preparo.selecao.arquivos)
        destinos = {a: self._destino(a) for a in arquivos}
        visivel = self.opcao_visivel.isChecked()
        posicoes = {arquivos[0]: self._preparo.posicao} if self._preparo.dados is not None else {}
        certificado, registro = self._certificado, arquivo_registro_assinaturas()
        self.progresso.iniciar("Assinando...")
        self.estados.setCurrentWidget(self.progresso)
        self.executar(
            lambda progresso, cancelamento: assinatura.assinar_varios(
                arquivos, destinos, certificado, visivel, posicoes, registro, progresso, cancelamento
            ),
            self._ao_assinar,
            self._ao_falhar_assinatura,
        )

    def _ao_assinar(self, resultado: assinatura.ResultadoLoteAssinatura) -> None:
        partes = [
            plural(len(resultado.gerados), "PDF assinado", "PDFs assinados")
            + f" com o certificado de {self._certificado.nome}."
        ]
        sem_internet = resultado.sem_validacao - resultado.sem_cadeia
        if sem_internet:
            partes.append(plural(
                sem_internet,
                "foi assinado sem a confirmação da certificadora (sem internet, ou ela não respondeu). A "
                "assinatura vale, mas fica mais difícil de conferir depois que o certificado vencer.",
                "foram assinados sem a confirmação da certificadora (sem internet, ou ela não respondeu). As "
                "assinaturas valem, mas ficam mais difíceis de conferir depois que o certificado vencer.",
            ))
        if resultado.sem_cadeia:
            partes.append(plural(
                resultado.sem_cadeia,
                "foi assinado sem a confirmação da certificadora: a cadeia do certificado não pôde ser conferida. "
                "Antes de enviar, confira o PDF em validar.iti.gov.br.",
                "foram assinados sem a confirmação da certificadora: a cadeia do certificado não pôde ser "
                "conferida. Antes de enviar, confira os PDFs em validar.iti.gov.br.",
            ))
        if resultado.substituidos:
            partes.append(plural(
                resultado.substituidos,
                "substituiu um arquivo anterior com o mesmo nome.",
                "substituíram arquivos anteriores com o mesmo nome.",
            ))
        if resultado.cancelado:
            partes.append(f"{plural(resultado.pendentes, 'PDF ficou', 'PDFs ficaram')} sem assinar.")
        partes.append("A assinatura ficou anotada no registro de assinaturas (veja em Configurações).")
        destino = resultado.gerados[0] if len(resultado.gerados) == 1 else resultado.gerados[0].parent
        texto_abrir = "Abrir arquivo" if len(resultado.gerados) == 1 else "Abrir pasta"
        if resultado.cancelado:
            titulo = "Assinatura interrompida"
        else:
            titulo = "PDF assinado!" if len(resultado.gerados) == 1 else "PDFs assinados!"
        self.resultado.mostrar_sucesso(titulo, " ".join(partes), destino, resultado.ignorados, texto_abrir)
        self.estados.setCurrentWidget(self.resultado)

    def _ao_falhar_assinatura(self, erro: BaseException) -> None:
        if isinstance(erro, ErroUnePDF) and erro.ignorados:
            self.resultado.mostrar_falha("Nenhum PDF foi assinado", str(erro), erro.ignorados)
            self.estados.setCurrentWidget(self.resultado)
            return
        self.estados.setCurrentWidget(self.painel_selecao)
        mostrar_erro(self, erro)
