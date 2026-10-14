"""Ferramenta XML para PDF: DANFE, DANFCe, DACTE, DAMDFE, DANFSe e DACCe a partir dos XMLs."""
from __future__ import annotations

from dataclasses import dataclass, fields
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from unepdf.core.erros import ErroUnePDF, OperacaoCancelada
from unepdf.core.localizador import XML, Selecao, montar_selecao
from unepdf.core.nomenclatura import nome_saida
from unepdf.core.xml_fiscal import AnaliseXml, TipoDocumento, analisar, completar_cartas_de_correcao, nomes_dos_pdfs
from unepdf.core.xml_pdf import ACEITAM_LOGO, Fonte, OpcoesDocumento, ResultadoXml, converter_xmls
from unepdf.ui.componentes import AreaSoltar, PainelProgresso, PainelResultado
from unepdf.ui.contexto import ContextoApp
from unepdf.ui.dialogos import mostrar_erro
from unepdf.ui.ferramentas.arquivo_unico import ATRASO_PROGRESSO_MS
from unepdf.ui.ferramentas.base import TelaFerramenta
from unepdf.ui.tema import CORES
from unepdf.utils.texto import plural

if TYPE_CHECKING:
    from unepdf.ui.ferramentas import Ferramenta

# Opções que valem só para a conversão atual e nunca ficam salvas
NAO_SALVAR = {"marcar_todos_cancelados"}


@dataclass
class _Preparo:
    selecao: Selecao
    analise: AnaliseXml


def _ajuda(texto: str) -> QLabel:
    rotulo = QLabel(texto)
    rotulo.setObjectName("subtitulo")
    rotulo.setWordWrap(True)
    return rotulo


def _rotulo_campo(texto: str) -> QLabel:
    rotulo = QLabel(texto)
    rotulo.setObjectName("rotuloCampo")
    return rotulo


class PainelOpcoesXml(QWidget):
    """Opções de aparência, agrupadas por documento. Cada grupo só aparece se a seleção tiver aquele tipo."""

    def __init__(self, contexto: ContextoApp):
        super().__init__()
        self.contexto = contexto
        salvas = contexto.config.opcoes_xml
        self._logo: Path | None = Path(salvas["logo"]) if salvas.get("logo") else None

        self.combo_fonte = QComboBox()
        self.combo_fonte.addItem("Times (padrão)", Fonte.TIMES)
        self.combo_fonte.addItem("Courier", Fonte.COURIER)
        self.combo_decimais = QComboBox()
        self.combo_decimais.addItem("4 casas (padrão)", 4)
        self.combo_decimais.addItem("2 casas", 2)
        self.rotulo_logo = QLabel()
        self.rotulo_logo.setWordWrap(True)
        self.botao_logo = QPushButton("Escolher logo")
        self.botao_logo.clicked.connect(self._escolher_logo)
        self.botao_remover_logo = QPushButton("Remover")
        self.botao_remover_logo.clicked.connect(lambda: self._definir_logo(None))

        self.caixas: dict[str, QCheckBox] = {
            "marcar_todos_cancelados": QCheckBox("Marcar todos como CANCELADA"),
            "canhoto_no_rodape": QCheckBox("Canhoto no rodapé (e não no topo)"),
            "canhoto_transportador": QCheckBox("Canhoto extra para o transportador"),
            "fonte_grande": QCheckBox("Letras maiores (só com a fonte Times)"),
            "exibir_pis_cofins": QCheckBox("Mostrar PIS e COFINS nos totais"),
            "exibir_pedido_de_compra": QCheckBox("Mostrar o pedido de compra nos produtos"),
            "quebrar_linha_no_ponto_e_virgula": QCheckBox('Quebrar linha a cada ";" nas informações complementares'),
            "bobina_58mm": QCheckBox("Bobina de 58 mm (o padrão é 80 mm)"),
            "canhoto_danfse": QCheckBox("Mostrar o canhoto"),
        }
        self.aviso_canceladas = _ajuda("")

        self.grupo_geral = self._grupo("TODOS OS DOCUMENTOS", [
            self._linha("Fonte", self.combo_fonte),
            self._linha("Casas decimais", self.combo_decimais),
            self.caixas["marcar_todos_cancelados"],
            self.aviso_canceladas,
        ])
        linha_logo = QHBoxLayout()
        linha_logo.addWidget(self.botao_logo)
        linha_logo.addWidget(self.botao_remover_logo)
        linha_logo.addStretch()
        self.grupo_logo = self._grupo("LOGO DO EMITENTE", [
            _ajuda("Aparece no cabeçalho do DANFE, DANFCe, DACTE, DAMDFE e DACCe. Use só em notas da própria empresa."),
            self.rotulo_logo,
            linha_logo,
        ])
        self.grupo_danfe = self._grupo("DANFE", [
            self.caixas[c] for c in (
                "canhoto_no_rodape", "canhoto_transportador", "fonte_grande", "exibir_pis_cofins",
                "exibir_pedido_de_compra", "quebrar_linha_no_ponto_e_virgula",
            )
        ])
        self.grupo_danfce = self._grupo("DANFCE (CUPOM)", [self.caixas["bobina_58mm"]])
        self.grupo_danfse = self._grupo("DANFSE", [self.caixas["canhoto_danfse"]])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(14)
        for grupo in (self.grupo_geral, self.grupo_logo, self.grupo_danfe, self.grupo_danfce, self.grupo_danfse):
            layout.addWidget(grupo)
        layout.addStretch()

        # Valores salvos da última vez
        self.combo_fonte.setCurrentIndex(max(self.combo_fonte.findData(salvas.get("fonte", Fonte.TIMES)), 0))
        self.combo_decimais.setCurrentIndex(1 if salvas.get("casas_decimais") == "2" else 0)
        for nome, caixa in self.caixas.items():
            caixa.setChecked(nome not in NAO_SALVAR and salvas.get(nome) is True)
            caixa.toggled.connect(self._salvar)
        self.combo_fonte.currentIndexChanged.connect(self._salvar)
        self.combo_decimais.currentIndexChanged.connect(self._salvar)
        self._mostrar_logo()

    @staticmethod
    def _linha(rotulo: str, campo: QWidget) -> QWidget:
        linha = QWidget()
        layout = QHBoxLayout(linha)
        layout.setContentsMargins(0, 0, 0, 0)
        texto = QLabel(rotulo)
        texto.setMinimumWidth(110)
        layout.addWidget(texto)
        layout.addWidget(campo, 1)
        return linha

    @staticmethod
    def _grupo(titulo: str, itens: list) -> QFrame:
        grupo = QFrame()
        layout = QVBoxLayout(grupo)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(_rotulo_campo(titulo))
        for item in itens:
            if isinstance(item, QHBoxLayout):
                layout.addLayout(item)
            else:
                layout.addWidget(item)
        return grupo

    def ajustar_para(self, analise: AnaliseXml) -> None:
        """Mostra só os grupos dos tipos presentes e explica a marca automática de cancelada."""
        tipos = set(analise.contagem())
        self.grupo_logo.setVisible(bool(tipos & ACEITAM_LOGO))
        self.grupo_danfe.setVisible(TipoDocumento.DANFE in tipos)
        self.grupo_danfce.setVisible(TipoDocumento.DANFCE in tipos)
        self.grupo_danfse.setVisible(TipoDocumento.DANFSE in tipos)
        self.caixas["marcar_todos_cancelados"].setChecked(False)
        canceladas = sum(
            1 for d in analise.documentos if d.chave in analise.canceladas and d.tipo is not TipoDocumento.DACCE
        )
        if canceladas:
            texto = plural(
                canceladas,
                "documento tem o evento de cancelamento na seleção e sai marcado como CANCELADA.",
                "documentos têm o evento de cancelamento na seleção e saem marcados como CANCELADA.",
            )
        else:
            texto = "Notas com o XML do evento de cancelamento junto saem marcadas como CANCELADA automaticamente."
        self.aviso_canceladas.setText(texto)

    def opcoes(self) -> OpcoesDocumento:
        valores = {nome: caixa.isChecked() for nome, caixa in self.caixas.items()}
        return OpcoesDocumento(
            logo=self._logo,
            fonte=Fonte(self.combo_fonte.currentData()),
            casas_decimais=self.combo_decimais.currentData(),
            **valores,
        )

    def _escolher_logo(self) -> None:
        inicial = str(self._logo.parent) if self._logo else ""
        caminho, _ = QFileDialog.getOpenFileName(self, "Escolha a logo", inicial, "Imagens (*.png *.jpg *.jpeg)")
        if caminho:
            self._definir_logo(Path(caminho))

    def _definir_logo(self, caminho: Path | None) -> None:
        self._logo = caminho
        self._mostrar_logo()
        self._salvar()

    def _mostrar_logo(self) -> None:
        self.rotulo_logo.setText(self._logo.name if self._logo else "Sem logo")
        self.botao_remover_logo.setEnabled(self._logo is not None)

    def _salvar(self) -> None:
        opcoes = self.opcoes()
        salvas = dict(self.contexto.config.opcoes_xml)
        salvas.update({
            f.name: getattr(opcoes, f.name) for f in fields(OpcoesDocumento)
            if isinstance(getattr(opcoes, f.name), bool) and f.name not in NAO_SALVAR
        })
        salvas.update(logo=str(self._logo or ""), fonte=opcoes.fonte.value, casas_decimais=str(opcoes.casas_decimais))
        if salvas != self.contexto.config.opcoes_xml:
            self.contexto.config.opcoes_xml = salvas
            self.contexto.salvar_config()


class TelaXmlParaPdf(TelaFerramenta):
    aceita_arquivos = True

    def __init__(self, ferramenta: Ferramenta, contexto: ContextoApp):
        super().__init__(ferramenta, contexto)
        self._preparo: _Preparo | None = None

        self.area = AreaSoltar(
            "Arraste XMLs ou uma pasta para cá",
            "NF-e, NFC-e, CT-e, MDF-e, NFS-e (padrão nacional) e cartas de correção. O tipo é reconhecido sozinho.",
            texto_arquivos="Escolher XMLs",
        )
        self.area.caminhos_soltos.connect(self.receber_caminhos)
        self.area.escolher_pasta.connect(self._escolher_pasta)
        self.area.escolher_arquivos.connect(self._escolher_arquivos)
        self.progresso = PainelProgresso()
        self.progresso.cancelar.connect(self.executor.cancelar)
        self.executor.progresso.connect(self.progresso.atualizar)
        self.resultado = PainelResultado("Converter outros XMLs")
        self.resultado.novo.connect(self.limpar)

        self.estados = QStackedWidget()
        for painel in (self.area, self._montar_painel_selecao(), self.progresso, self.resultado):
            self.estados.addWidget(painel)
        self.corpo.addWidget(self.estados)

        self._timer_progresso = QTimer(self)
        self._timer_progresso.setSingleShot(True)
        self._timer_progresso.timeout.connect(lambda: self.estados.setCurrentWidget(self.progresso))

    def _montar_painel_selecao(self) -> QWidget:
        self.resumo_selecao = QLabel()
        self.resumo_selecao.setObjectName("tituloResultado")
        self.tipos_selecao = _ajuda("")
        self.origem_selecao = _ajuda("")
        trocar = QPushButton("Trocar seleção")
        trocar.clicked.connect(self.limpar)
        textos = QVBoxLayout()
        textos.setSpacing(2)
        textos.addWidget(self.resumo_selecao)
        textos.addWidget(self.tipos_selecao)
        textos.addWidget(self.origem_selecao)
        cabecalho = QHBoxLayout()
        cabecalho.addLayout(textos, 1)
        cabecalho.addWidget(trocar)

        self.lista = QListWidget()
        self.lista.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.opcoes = PainelOpcoesXml(self.contexto)
        rolagem = QScrollArea()
        rolagem.setWidgetResizable(True)
        rolagem.setWidget(self.opcoes)
        rolagem.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        rolagem.setFixedWidth(370)
        meio = QHBoxLayout()
        meio.setSpacing(18)
        meio.addWidget(self.lista, 1)
        meio.addWidget(rolagem)

        self.check_juntar = QCheckBox("Também juntar tudo em um PDF, com um marcador por documento")
        self.check_juntar.setChecked(self.contexto.config.opcoes_xml.get("juntar") is True)
        self.check_juntar.toggled.connect(self._ao_mudar_juntar)
        self.destino_selecao = QLabel()
        self.destino_selecao.setWordWrap(True)
        self.aviso_selecao = QLabel()
        self.aviso_selecao.setObjectName("aviso")
        self.aviso_selecao.setWordWrap(True)
        self.botao_converter = QPushButton("Converter")
        self.botao_converter.setObjectName("botaoPrincipal")
        self.botao_converter.clicked.connect(self._converter)
        rodape = QHBoxLayout()
        rodape.addWidget(self.aviso_selecao, 1)
        rodape.addWidget(self.botao_converter)

        painel = QWidget()
        layout = QVBoxLayout(painel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addLayout(cabecalho)
        layout.addLayout(meio, 1)
        layout.addWidget(self.check_juntar)
        layout.addWidget(_rotulo_campo("SERÁ SALVO EM"))
        layout.addWidget(self.destino_selecao)
        layout.addLayout(rodape)
        self.painel_selecao = painel
        return painel

    # Escolha dos arquivos

    def _pasta_para_dialogo(self) -> str:
        for candidata in (self.contexto.config.ultima_pasta, self.contexto.config.pasta_inicial):
            if candidata and Path(candidata).is_dir():
                return candidata
        return ""

    def _escolher_pasta(self) -> None:
        pasta = QFileDialog.getExistingDirectory(self, "Escolha a pasta com os XMLs", self._pasta_para_dialogo())
        if pasta:
            self.receber_caminhos([Path(pasta)])

    def _escolher_arquivos(self) -> None:
        arquivos, _ = QFileDialog.getOpenFileNames(self, "Escolha os XMLs", self._pasta_para_dialogo(), "XML (*.xml)")
        if arquivos:
            self.receber_caminhos([Path(a) for a in arquivos])

    def receber_caminhos(self, caminhos: list[Path]) -> None:
        if self.executor.em_execucao:
            return
        self.area.mostrar_aviso(None)
        pasta_saida = self.contexto.config.pasta_saida

        def preparar(progresso, cancelamento) -> _Preparo:
            selecao = montar_selecao(caminhos, pasta_saida, XML)
            analise = analisar(selecao.arquivos, progresso, cancelamento)
            completar_cartas_de_correcao(analise)
            return _Preparo(selecao, analise)

        self.progresso.iniciar("Lendo os XMLs...")
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
        selecao, analise = preparo.selecao, preparo.analise
        if self.contexto.config.ultima_pasta != str(selecao.base):
            self.contexto.config.ultima_pasta = str(selecao.base)
            self.contexto.salvar_config()

        self.resumo_selecao.setText(plural(len(analise.documentos), "documento encontrado", "documentos encontrados"))
        self.tipos_selecao.setText(", ".join(f"{n} {tipo.value}" for tipo, n in analise.contagem().items()))
        self.origem_selecao.setText(f"Da pasta {selecao.pasta}" if selecao.pasta else f"Arquivos de {selecao.base}")

        self.lista.clear()
        nomes = nomes_dos_pdfs(analise.documentos)
        for documento in analise.documentos:
            item = QListWidgetItem(nomes[documento.identificador].removesuffix(" (XML).pdf"))
            item.setToolTip(str(documento.caminho))
            self.lista.addItem(item)
        aviso = QBrush(QColor(CORES.aviso))
        for ignorado in analise.ignorados:
            item = QListWidgetItem(f"{ignorado.caminho.name}: {ignorado.motivo}")
            item.setForeground(aviso)
            item.setToolTip(str(ignorado.caminho))
            self.lista.addItem(item)

        self.opcoes.ajustar_para(analise)
        avisos = []
        if analise.ignorados:
            avisos.append(
                plural(len(analise.ignorados), "arquivo não será convertido", "arquivos não serão convertidos")
                + " (em amarelo na lista)."
            )
        if selecao.descartados:
            avisos.append(
                f"{plural(selecao.descartados, 'item ficou', 'itens ficaram')} de fora: "
                "não são XML ou estão na pasta de saída."
            )
        self.aviso_selecao.setText("\n".join(avisos))
        self.botao_converter.setText("Converter " + plural(len(analise.documentos), "XML", "XMLs"))
        self.botao_converter.setEnabled(bool(analise.documentos))
        self._mostrar_destino()
        self.estados.setCurrentWidget(self.painel_selecao)

    def _pasta_destino(self) -> Path:
        return self._preparo.selecao.base / self.contexto.config.pasta_saida

    def _destino_juntado(self) -> Path:
        base = self._preparo.selecao.base
        nome = nome_saida(base, self.contexto.config.perfil_nomenclatura).removesuffix(".pdf")
        return self._pasta_destino() / f"{nome} (XML).pdf"

    def _mostrar_destino(self) -> None:
        texto = str(self._pasta_destino())
        if self.check_juntar.isChecked():
            texto += f"\nPDF com todos: {self._destino_juntado().name}"
        self.destino_selecao.setText(texto)

    def _ao_mudar_juntar(self, marcado: bool) -> None:
        opcoes = dict(self.contexto.config.opcoes_xml, juntar=marcado)
        self.contexto.config.opcoes_xml = opcoes
        self.contexto.salvar_config()
        if self._preparo:
            self._mostrar_destino()

    def limpar(self) -> None:
        self._preparo = None
        self.area.mostrar_aviso(None)
        self.estados.setCurrentWidget(self.area)

    # Conversão

    def _converter(self) -> None:
        if not self._preparo or self.executor.em_execucao:
            return
        analise, pasta, opcoes = self._preparo.analise, self._pasta_destino(), self.opcoes.opcoes()
        juntar_em = self._destino_juntado() if self.check_juntar.isChecked() else None
        self.progresso.iniciar("Gerando os PDFs...")
        self.estados.setCurrentWidget(self.progresso)
        self.executar(
            lambda progresso, cancelamento: converter_xmls(analise, pasta, opcoes, juntar_em, progresso, cancelamento),
            self._ao_converter,
            self._ao_falhar_conversao,
        )

    def _ao_converter(self, resultado: ResultadoXml) -> None:
        partes = [plural(len(resultado.gerados), "PDF gerado", "PDFs gerados") + "."]
        if resultado.marcados_cancelados:
            partes.append(plural(resultado.marcados_cancelados, "saiu marcado", "saíram marcados") + " como CANCELADA.")
        if resultado.substituidos:
            partes.append(plural(
                resultado.substituidos,
                "substituiu um arquivo anterior com o mesmo nome.",
                "substituíram arquivos anteriores com o mesmo nome.",
            ))
        if resultado.juntado:
            partes.append(f"O PDF com todos tem {plural(resultado.paginas_juntado, 'página', 'páginas')}.")
        if resultado.cancelado:
            titulo = "Conversão interrompida"
            partes.append(f"{plural(resultado.pendentes, 'documento ficou', 'documentos ficaram')} sem converter.")
        else:
            titulo = "PDFs criados!"
        if resultado.juntado:
            destino, texto_abrir = resultado.juntado, "Abrir PDF com todos"
        else:
            destino, texto_abrir = resultado.pasta, "Abrir pasta"
        self.resultado.mostrar_sucesso(titulo, " ".join(partes), destino, resultado.ignorados, texto_abrir)
        self.estados.setCurrentWidget(self.resultado)

    def _ao_falhar_conversao(self, erro: BaseException) -> None:
        if isinstance(erro, ErroUnePDF) and erro.ignorados and not isinstance(erro, OperacaoCancelada):
            self.resultado.mostrar_falha("Nenhum PDF foi gerado", str(erro), erro.ignorados)
            self.estados.setCurrentWidget(self.resultado)
            return
        self.estados.setCurrentWidget(self.painel_selecao)
        mostrar_erro(self, erro)
