"""Ferramenta Unir em lote: um unificado para cada pasta com PDFs dentro de uma pasta raiz."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QShowEvent
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

from unepdf.core.erros import ErroUnePDF, OperacaoCancelada
from unepdf.core.gravacao import gravar_com_seguranca
from unepdf.core.lote import (
    ResultadoLote,
    Varredura,
    caminho_relativo,
    procurar_pastas,
    resumo_lote,
    texto_relatorio,
    unir_em_lote,
)
from unepdf.ui.componentes import AreaSoltar, PainelProgresso
from unepdf.ui.contexto import ContextoApp
from unepdf.ui.dialogos import mostrar_erro
from unepdf.ui.ferramentas.base import TelaFerramenta
from unepdf.ui.ferramentas.unir import OpcoesUniao
from unepdf.ui.tema import CORES
from unepdf.utils import sistema
from unepdf.utils.texto import plural

if TYPE_CHECKING:
    from unepdf.ui.ferramentas import Ferramenta


@dataclass
class _Preparo:
    varredura: Varredura
    existentes: set[Path]  # destinos que já existem e serão substituídos


def _arvore(colunas: list[str]) -> QTreeWidget:
    arvore = QTreeWidget()
    arvore.setHeaderLabels(colunas)
    arvore.setRootIsDecorated(False)
    arvore.setUniformRowHeights(True)
    arvore.header().setStretchLastSection(False)
    arvore.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    for coluna in range(1, len(colunas)):
        arvore.header().setSectionResizeMode(coluna, QHeaderView.ResizeMode.ResizeToContents)
    return arvore


class TelaUnirLote(TelaFerramenta):
    aceita_arquivos = True

    def __init__(self, ferramenta: Ferramenta, contexto: ContextoApp):
        super().__init__(ferramenta, contexto)
        self._preparo: _Preparo | None = None
        self._resultado: ResultadoLote | None = None
        self._ultima_raiz: Path | None = None
        self._config_usada: tuple = ()

        self.area = AreaSoltar(
            "Arraste uma pasta para cá",
            "Cada pasta com PDFs, em qualquer nível dentro dela, vira um unificado separado.",
        )
        self.area.botao_arquivos.hide()
        self.area.caminhos_soltos.connect(self.receber_caminhos)
        self.area.escolher_pasta.connect(self._escolher_pasta)

        self.progresso = PainelProgresso()
        self.progresso.cancelar.connect(self.executor.cancelar)
        self.executor.progresso.connect(self.progresso.atualizar)

        self.estados = QStackedWidget()
        for painel in (self.area, self._montar_painel_selecao(), self.progresso, self._montar_painel_resultado()):
            self.estados.addWidget(painel)
        self.corpo.addWidget(self.estados)

    def _montar_painel_selecao(self) -> QWidget:
        self.resumo_selecao = QLabel()
        self.resumo_selecao.setObjectName("tituloResultado")
        self.origem_selecao = QLabel()
        self.origem_selecao.setObjectName("subtitulo")
        self.origem_selecao.setWordWrap(True)
        trocar = QPushButton("Trocar pasta")
        trocar.clicked.connect(self.limpar)
        textos = QVBoxLayout()
        textos.setSpacing(2)
        textos.addWidget(self.resumo_selecao)
        textos.addWidget(self.origem_selecao)
        cabecalho = QHBoxLayout()
        cabecalho.addLayout(textos, 1)
        cabecalho.addWidget(trocar)

        self.lista_pastas = _arvore(["Pasta", "PDFs", "Unificado"])
        self.lista_pastas.itemChanged.connect(lambda *_: self._atualizar_botao())
        self.botao_marcar = QPushButton("Desmarcar todas")
        self.botao_marcar.clicked.connect(self._alternar_marcacao)

        self.opcoes = OpcoesUniao(self.contexto, com_manual=False)
        linha_opcoes = QHBoxLayout()
        linha_opcoes.addWidget(self.opcoes, 1)
        linha_opcoes.addWidget(self.botao_marcar, 0, Qt.AlignmentFlag.AlignTop)

        self.info_destino = QLabel()
        self.info_destino.setObjectName("subtitulo")
        self.info_destino.setWordWrap(True)
        self.aviso_selecao = QLabel()
        self.aviso_selecao.setObjectName("aviso")
        self.aviso_selecao.setWordWrap(True)
        self.botao_unir = QPushButton()
        self.botao_unir.setObjectName("botaoPrincipal")
        self.botao_unir.clicked.connect(self._unir)
        rodape = QHBoxLayout()
        rodape.addWidget(self.aviso_selecao, 1)
        rodape.addWidget(self.botao_unir)

        painel = QWidget()
        layout = QVBoxLayout(painel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addLayout(cabecalho)
        layout.addWidget(self.lista_pastas, 1)
        layout.addLayout(linha_opcoes)
        layout.addWidget(self.info_destino)
        layout.addLayout(rodape)
        self.painel_selecao = painel
        return painel

    def _montar_painel_resultado(self) -> QWidget:
        self.titulo_resultado = QLabel()
        self.titulo_resultado.setObjectName("tituloResultado")
        self.resumo_resultado = QLabel()
        self.resumo_resultado.setWordWrap(True)
        dica = QLabel("Clique duas vezes em uma pasta para ver o unificado no Explorador de Arquivos.")
        dica.setObjectName("subtitulo")

        self.lista_resultado = _arvore(["Pasta", "Resultado"])
        self.lista_resultado.setRootIsDecorated(True)
        self.lista_resultado.itemDoubleClicked.connect(self._mostrar_item)

        self.botao_abrir_pasta = QPushButton("Abrir pasta")
        self.botao_abrir_pasta.setObjectName("botaoPrincipal")
        self.botao_abrir_pasta.clicked.connect(self._abrir_raiz)
        self.botao_relatorio = QPushButton("Salvar relatório")
        self.botao_relatorio.clicked.connect(self._salvar_relatorio)
        novo = QPushButton("Unir outra pasta")
        novo.clicked.connect(self.limpar)
        botoes = QHBoxLayout()
        botoes.addWidget(self.botao_abrir_pasta)
        botoes.addWidget(self.botao_relatorio)
        botoes.addStretch()
        botoes.addWidget(novo)

        painel = QWidget()
        layout = QVBoxLayout(painel)
        layout.setContentsMargins(0, 24, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(self.titulo_resultado)
        layout.addWidget(self.resumo_resultado)
        layout.addLayout(botoes)
        layout.addSpacing(4)
        layout.addWidget(dica)
        layout.addWidget(self.lista_resultado, 1)
        self.painel_resultado = painel
        return painel

    # Escolha da pasta

    def _pasta_para_dialogo(self) -> str:
        for candidata in (self.contexto.config.ultima_pasta, self.contexto.config.pasta_inicial):
            if candidata and Path(candidata).is_dir():
                return candidata
        return ""

    def _escolher_pasta(self) -> None:
        pasta = QFileDialog.getExistingDirectory(self, "Escolha a pasta raiz", self._pasta_para_dialogo())
        if pasta:
            self.receber_caminhos([Path(pasta)])

    def receber_caminhos(self, caminhos: list[Path]) -> None:
        if self.executor.em_execucao:
            return
        self.area.mostrar_aviso(None)
        if len(caminhos) != 1 or not caminhos[0].is_dir():
            self.estados.setCurrentWidget(self.area)
            self.area.mostrar_aviso("Escolha uma pasta só. Os PDFs de cada subpasta viram um unificado separado.")
            return
        raiz = caminhos[0]
        perfil, pasta_saida = self.contexto.config.perfil_nomenclatura, self.contexto.config.pasta_saida
        self._ultima_raiz = raiz
        self._config_usada = (perfil, pasta_saida)

        def preparar(progresso, cancelamento) -> _Preparo:
            varredura = procurar_pastas(raiz, perfil, pasta_saida, cancelamento)
            return _Preparo(varredura, {p.destino for p in varredura.pastas if p.destino.exists()})

        self.progresso.iniciar("Procurando pastas com PDFs...")
        self.estados.setCurrentWidget(self.progresso)
        self.executar(preparar, self._mostrar_selecao, self._ao_falhar_preparo)

    def _ao_falhar_preparo(self, erro: BaseException) -> None:
        self.estados.setCurrentWidget(self.area)
        if isinstance(erro, OperacaoCancelada):
            self.area.mostrar_aviso("Busca cancelada.")
        elif isinstance(erro, ErroUnePDF):
            self.area.mostrar_aviso(str(erro))
        else:
            mostrar_erro(self, erro)

    def _mostrar_selecao(self, preparo: _Preparo) -> None:
        self._preparo = preparo
        varredura = preparo.varredura
        self._lembrar_pasta(varredura.raiz)
        self.resumo_selecao.setText(plural(len(varredura.pastas), "pasta com PDFs", "pastas com PDFs"))
        self.origem_selecao.setText(f"Em {varredura.raiz}")

        self.lista_pastas.blockSignals(True)
        self.lista_pastas.clear()
        for pasta in varredura.pastas:
            item = QTreeWidgetItem([
                caminho_relativo(pasta.pasta, varredura.raiz), str(len(pasta.arquivos)), pasta.destino.name,
            ])
            item.setData(0, Qt.ItemDataRole.UserRole, pasta)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Checked)
            item.setToolTip(0, str(pasta.pasta))
            item.setToolTip(2, str(pasta.destino))
            item.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.lista_pastas.addTopLevelItem(item)
        self.lista_pastas.blockSignals(False)

        pasta_saida = self.contexto.config.pasta_saida
        self.info_destino.setText(
            f'Cada unificado é salvo na subpasta "{pasta_saida}" da sua própria pasta. Os originais não são alterados.'
        )
        avisos = []
        if preparo.existentes:
            avisos.append(plural(
                len(preparo.existentes),
                "unificado já existe e será substituído.",
                "unificados já existem e serão substituídos.",
            ))
        if varredura.inacessiveis:
            avisos.append(plural(
                len(varredura.inacessiveis),
                "pasta não pôde ser aberta e ficou de fora.",
                "pastas não puderam ser abertas e ficaram de fora.",
            ))
        self.aviso_selecao.setText("\n".join(avisos))
        self._atualizar_botao()
        self.estados.setCurrentWidget(self.painel_selecao)

    def _itens_pastas(self) -> list[QTreeWidgetItem]:
        return [self.lista_pastas.topLevelItem(i) for i in range(self.lista_pastas.topLevelItemCount())]

    def _marcadas(self) -> list:
        return [
            item.data(0, Qt.ItemDataRole.UserRole)
            for item in self._itens_pastas()
            if item.checkState(0) == Qt.CheckState.Checked
        ]

    def _atualizar_botao(self) -> None:
        quantidade = len(self._marcadas())
        self.botao_unir.setText("Unir " + plural(quantidade, "pasta", "pastas"))
        self.botao_unir.setEnabled(quantidade > 0)
        todas = quantidade == len(self._itens_pastas())
        self.botao_marcar.setText("Desmarcar todas" if todas else "Marcar todas")

    def _alternar_marcacao(self) -> None:
        estado = Qt.CheckState.Unchecked if self.botao_marcar.text() == "Desmarcar todas" else Qt.CheckState.Checked
        self.lista_pastas.blockSignals(True)
        for item in self._itens_pastas():
            item.setCheckState(0, estado)
        self.lista_pastas.blockSignals(False)
        self._atualizar_botao()

    def showEvent(self, evento: QShowEvent) -> None:
        super().showEvent(evento)
        # Perfil ou subpasta de saída alterados nas configurações mudam os destinos mostrados
        config = self.contexto.config
        mudou = self._config_usada != (config.perfil_nomenclatura, config.pasta_saida)
        if mudou and self.estados.currentWidget() is self.painel_selecao and not self.executor.em_execucao:
            self.receber_caminhos([self._ultima_raiz])

    def limpar(self) -> None:
        self._preparo = None
        self.area.mostrar_aviso(None)
        self.estados.setCurrentWidget(self.area)

    # Execução

    def _unir(self) -> None:
        pastas = self._marcadas()
        if not self._preparo or not pastas or self.executor.em_execucao:
            return
        raiz = self._preparo.varredura.raiz
        ordem, repetidos, capa = self.opcoes.ordem, self.opcoes.pular_repetidos, self.opcoes.capa
        self.progresso.iniciar("Unindo as pastas...")
        self.estados.setCurrentWidget(self.progresso)
        self.executar(
            lambda progresso, cancelamento: unir_em_lote(
                raiz, pastas, ordem, repetidos, capa, progresso, cancelamento
            ),
            self._mostrar_resultado,
            self._ao_falhar_lote,
        )

    def _ao_falhar_lote(self, erro: BaseException) -> None:
        self.estados.setCurrentWidget(self.painel_selecao)
        mostrar_erro(self, erro)

    def _mostrar_resultado(self, resultado: ResultadoLote) -> None:
        self._resultado = resultado
        self.botao_relatorio.setText("Salvar relatório")
        if resultado.cancelado:
            titulo, estado = "Lote cancelado", "falha"
        elif resultado.com_problema:
            titulo, estado = "Lote concluído, com problemas", "falha"
        else:
            titulo, estado = "Lote concluído!", "sucesso"
        self.titulo_resultado.setText(titulo)
        self.titulo_resultado.setProperty("estado", estado)
        self.titulo_resultado.style().unpolish(self.titulo_resultado)
        self.titulo_resultado.style().polish(self.titulo_resultado)
        resumo = resumo_lote(resultado)
        if resultado.cancelado:
            resumo += " Os unificados já gerados estão completos e podem ser usados."
        self.resumo_resultado.setText(resumo)

        aviso = QBrush(QColor(CORES.aviso))
        apagado = QBrush(QColor(CORES.texto_desativado))
        self.lista_resultado.clear()
        for item in resultado.itens:
            nome = caminho_relativo(item.pasta, resultado.raiz)
            if item.resultado:
                r = item.resultado
                texto = f"{plural(r.arquivos, 'arquivo', 'arquivos')}, {plural(r.paginas, 'página', 'páginas')}"
                if item.ignorados:
                    texto += f" ({plural(len(item.ignorados), 'ficou', 'ficaram')} de fora)"
            else:
                texto = item.erro.splitlines()[0] if item.erro else "Não foi possível unir"
            linha = QTreeWidgetItem([nome, texto])
            linha.setData(0, Qt.ItemDataRole.UserRole, item.resultado.destino if item.resultado else None)
            linha.setToolTip(0, str(item.pasta))
            linha.setToolTip(1, str(item.resultado.destino) if item.resultado else item.erro)
            if not item.resultado:
                for coluna in (0, 1):
                    linha.setForeground(coluna, aviso)
            for ignorado in item.ignorados:
                filho = QTreeWidgetItem([ignorado.caminho.name, ignorado.motivo])
                filho.setToolTip(0, str(ignorado.caminho))
                filho.setForeground(0, aviso)
                filho.setForeground(1, aviso)
                linha.addChild(filho)
            self.lista_resultado.addTopLevelItem(linha)
        for pasta in resultado.pendentes:
            linha = QTreeWidgetItem([caminho_relativo(pasta, resultado.raiz), "Não processada (cancelado)"])
            for coluna in (0, 1):
                linha.setForeground(coluna, apagado)
            self.lista_resultado.addTopLevelItem(linha)
        self.estados.setCurrentWidget(self.painel_resultado)

    def _mostrar_item(self, item: QTreeWidgetItem) -> None:
        destino = item.data(0, Qt.ItemDataRole.UserRole)
        if destino:
            try:
                sistema.mostrar_na_pasta(destino)
            except Exception as erro:
                mostrar_erro(self, erro, "Não foi possível abrir")

    def _abrir_raiz(self) -> None:
        if self._resultado:
            try:
                sistema.abrir_arquivo(self._resultado.raiz)
            except Exception as erro:
                mostrar_erro(self, erro, "Não foi possível abrir")

    def _salvar_relatorio(self) -> None:
        if not self._resultado:
            return
        sugestao = self._resultado.raiz / "Relatório do lote.txt"
        caminho, _ = QFileDialog.getSaveFileName(self, "Salvar relatório", str(sugestao), "Texto (*.txt)")
        if not caminho:
            return
        # Com a marca de UTF-8 no início, o Bloco de Notas e o Excel mostram os acentos corretamente
        conteudo = texto_relatorio(self._resultado).encode("utf-8-sig")
        try:
            gravar_com_seguranca(Path(caminho), lambda arquivo: arquivo.write(conteudo))
        except Exception as erro:
            mostrar_erro(self, erro, "Não foi possível salvar o relatório")
            return
        self.botao_relatorio.setText("Relatório salvo!")

    def _lembrar_pasta(self, pasta: Path) -> None:
        if self.contexto.config.ultima_pasta != str(pasta):
            self.contexto.config.ultima_pasta = str(pasta)
            self.contexto.salvar_config()
