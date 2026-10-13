"""Ferramenta Unir PDFs: escolha por pasta ou arquivos, progresso, resumo e arquivos ignorados."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from unepdf.core.erros import ErroUnePDF, OperacaoCancelada
from unepdf.core.localizador import Selecao, montar_selecao
from unepdf.core.modelos import Resultado
from unepdf.core.nomenclatura import destino_padrao
from unepdf.core.unir import unir
from unepdf.ui.componentes import AreaSoltar, PainelProgresso, PainelResultado
from unepdf.ui.contexto import ContextoApp
from unepdf.ui.dialogos import mostrar_erro
from unepdf.ui.ferramentas.base import TelaFerramenta
from unepdf.utils.texto import plural

if TYPE_CHECKING:
    from unepdf.ui.ferramentas import Ferramenta

# Tempo antes de mostrar o "Lendo a pasta...": em pastas locais a leitura é quase instantânea
# e a troca rápida de tela só piscaria
ATRASO_PROGRESSO_MS = 300


@dataclass
class _Preparo:
    selecao: Selecao
    destino: Path
    destino_existe: bool


class TelaUnir(TelaFerramenta):
    aceita_arquivos = True

    def __init__(self, ferramenta: Ferramenta, contexto: ContextoApp):
        super().__init__(ferramenta, contexto)
        self._preparo: _Preparo | None = None
        self._etapa = ""  # tarefa em andamento no executor: "selecao" ou "unir"

        self.area = AreaSoltar(
            "Arraste PDFs ou uma pasta para cá",
            "Cada arquivo começa em uma página nova e vira um marcador no PDF final.",
        )
        self.area.caminhos_soltos.connect(self.receber_caminhos)
        self.area.escolher_pasta.connect(self._escolher_pasta)
        self.area.escolher_arquivos.connect(self._escolher_arquivos)

        self.progresso = PainelProgresso()
        self.progresso.cancelar.connect(self.executor.cancelar)
        self.resultado = PainelResultado("Unir outros arquivos")
        self.resultado.novo.connect(self.limpar)

        self.estados = QStackedWidget()
        for painel in (self.area, self._montar_painel_selecao(), self.progresso, self.resultado):
            self.estados.addWidget(painel)
        self.corpo.addWidget(self.estados)

        self._timer_progresso = QTimer(self)
        self._timer_progresso.setSingleShot(True)
        self._timer_progresso.timeout.connect(lambda: self.estados.setCurrentWidget(self.progresso))

        self.executor.progresso.connect(self.progresso.atualizar)
        self.executor.concluido.connect(self._ao_concluir)
        self.executor.falhou.connect(self._ao_falhar)

    def _montar_painel_selecao(self) -> QWidget:
        self.resumo_selecao = QLabel()
        self.resumo_selecao.setObjectName("tituloResultado")
        self.origem_selecao = QLabel()
        self.origem_selecao.setObjectName("subtitulo")
        self.origem_selecao.setWordWrap(True)
        trocar = QPushButton("Trocar seleção")
        trocar.clicked.connect(self.limpar)

        textos = QVBoxLayout()
        textos.setSpacing(2)
        textos.addWidget(self.resumo_selecao)
        textos.addWidget(self.origem_selecao)
        cabecalho = QHBoxLayout()
        cabecalho.addLayout(textos, 1)
        cabecalho.addWidget(trocar)

        self.lista_arquivos = QListWidget()
        self.lista_arquivos.setSelectionMode(QListWidget.SelectionMode.NoSelection)

        rotulo_destino = QLabel("SERÁ SALVO EM")
        rotulo_destino.setObjectName("rotuloCampo")
        self.destino_selecao = QLabel()
        self.destino_selecao.setWordWrap(True)
        self.aviso_selecao = QLabel()
        self.aviso_selecao.setObjectName("aviso")
        self.aviso_selecao.setWordWrap(True)

        self.botao_unir = QPushButton("Unir PDFs")
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
        layout.addWidget(self.lista_arquivos, 1)
        layout.addSpacing(4)
        layout.addWidget(rotulo_destino)
        layout.addWidget(self.destino_selecao)
        layout.addSpacing(4)
        layout.addLayout(rodape)
        self.painel_selecao = painel
        return painel

    # Escolha dos arquivos

    def _pasta_para_dialogo(self) -> str:
        """Abre os diálogos na última pasta usada; sem ela, na pasta inicial das configurações."""
        for candidata in (self.contexto.config.ultima_pasta, self.contexto.config.pasta_inicial):
            if candidata and Path(candidata).is_dir():
                return candidata
        return ""

    def _escolher_pasta(self) -> None:
        pasta = QFileDialog.getExistingDirectory(self, "Escolha a pasta com os PDFs", self._pasta_para_dialogo())
        if pasta:
            self.receber_caminhos([Path(pasta)])

    def _escolher_arquivos(self) -> None:
        arquivos, _ = QFileDialog.getOpenFileNames(
            self, "Escolha os PDFs", self._pasta_para_dialogo(), "Arquivos PDF (*.pdf)"
        )
        if arquivos:
            self.receber_caminhos([Path(a) for a in arquivos])

    def receber_caminhos(self, caminhos: list[Path]) -> None:
        if self.executor.em_execucao:
            return
        self.area.mostrar_aviso(None)
        perfil = self.contexto.config.perfil_nomenclatura
        pasta_saida = self.contexto.config.pasta_saida

        # Roda em segundo plano porque listar uma pasta de rede grande pode demorar
        def preparar(progresso, cancelamento) -> _Preparo:
            selecao = montar_selecao(caminhos, pasta_saida)
            destino = destino_padrao(selecao.base, perfil, pasta_saida)
            return _Preparo(selecao, destino, destino.exists())

        self._etapa = "selecao"
        self.progresso.iniciar("Lendo os arquivos...", cancelavel=False)
        self._timer_progresso.start(ATRASO_PROGRESSO_MS)
        self.executor.executar(preparar)

    def _mostrar_selecao(self, preparo: _Preparo, aviso: str = "") -> None:
        self._preparo = preparo
        selecao = preparo.selecao
        self.resumo_selecao.setText(plural(len(selecao.arquivos), "PDF selecionado", "PDFs selecionados"))
        if selecao.pasta:
            self.origem_selecao.setText(f"Da pasta {selecao.pasta}")
        else:
            self.origem_selecao.setText(f"Arquivos escolhidos em {selecao.base}")
        self.lista_arquivos.clear()
        self.lista_arquivos.addItems([p.name for p in selecao.arquivos])
        self.destino_selecao.setText(str(preparo.destino))

        avisos = [aviso] if aviso else []
        if selecao.descartados:
            avisos.append(
                f"{plural(selecao.descartados, 'item ficou', 'itens ficaram')} de fora: "
                "não são PDF, estão repetidos ou estão na pasta de saída."
            )
        if preparo.destino_existe:
            avisos.append("Já existe um arquivo com esse nome. Ele será substituído.")
        self.aviso_selecao.setText("\n".join(avisos))
        self.estados.setCurrentWidget(self.painel_selecao)

    def limpar(self) -> None:
        self._preparo = None
        self.area.mostrar_aviso(None)
        self.estados.setCurrentWidget(self.area)

    # União

    def _unir(self) -> None:
        if not self._preparo or self.executor.em_execucao:
            return
        arquivos, destino = self._preparo.selecao.arquivos, self._preparo.destino
        self._etapa = "unir"
        self.progresso.iniciar("Unindo PDFs...")
        self.estados.setCurrentWidget(self.progresso)
        self.executor.executar(lambda progresso, cancelamento: unir(arquivos, destino, progresso, cancelamento))

    def _ao_concluir(self, resultado: _Preparo | Resultado) -> None:
        self._timer_progresso.stop()
        if self._etapa == "selecao":
            self._lembrar_pasta(resultado.selecao.base)
            self._mostrar_selecao(resultado)
            return

        resumo = (
            f"{plural(resultado.arquivos, 'arquivo unido', 'arquivos unidos')} em "
            f"{plural(resultado.paginas, 'página', 'páginas')}."
        )
        if resultado.substituiu_anterior:
            resumo += " O arquivo anterior com o mesmo nome foi substituído."
        self.resultado.mostrar_sucesso("PDF criado!", resumo, resultado.destino, resultado.ignorados)
        self.estados.setCurrentWidget(self.resultado)

    def _ao_falhar(self, erro: BaseException) -> None:
        self._timer_progresso.stop()
        if self._etapa == "selecao":
            self.estados.setCurrentWidget(self.area)
            if isinstance(erro, ErroUnePDF):
                self.area.mostrar_aviso(str(erro))
            else:
                mostrar_erro(self, erro)
            return

        if isinstance(erro, OperacaoCancelada):
            self._voltar_para_selecao(str(erro))
        elif isinstance(erro, ErroUnePDF) and erro.ignorados:
            self.resultado.mostrar_falha("Nenhum PDF foi unido", str(erro), erro.ignorados)
            self.estados.setCurrentWidget(self.resultado)
        else:
            self._voltar_para_selecao()
            mostrar_erro(self, erro)

    def _voltar_para_selecao(self, aviso: str = "") -> None:
        if self._preparo:
            self._mostrar_selecao(self._preparo, aviso)
        else:
            self.limpar()
            self.area.mostrar_aviso(aviso)

    def _lembrar_pasta(self, pasta: Path) -> None:
        if self.contexto.config.ultima_pasta != str(pasta):
            self.contexto.config.ultima_pasta = str(pasta)
            self.contexto.salvar_config()
