"""Tela-base das ferramentas que trabalham com um PDF por vez.

O fluxo é sempre o mesmo: escolher o PDF, ajustar as opções, processar e ver o resultado.
Cada ferramenta herda desta classe e implementa só os ganchos marcados abaixo.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QPushButton, QStackedWidget, QVBoxLayout, QWidget

from unepdf.core.erros import ErroUnePDF, OperacaoCancelada
from unepdf.core.localizador import pdf_unico
from unepdf.core.modelos import Resultado
from unepdf.ui.componentes import AreaSoltar, PainelProgresso, PainelResultado
from unepdf.ui.contexto import ContextoApp
from unepdf.ui.dialogos import mostrar_erro
from unepdf.ui.executor import Tarefa
from unepdf.ui.ferramentas.base import TelaFerramenta

if TYPE_CHECKING:
    from unepdf.ui.ferramentas import Ferramenta

ATRASO_PROGRESSO_MS = 300


class TelaArquivoUnico(TelaFerramenta):
    aceita_arquivos = True

    # Textos de cada ferramenta
    dica_area = ""
    texto_botao = "Processar"
    titulo_progresso = "Processando..."
    titulo_sucesso = "Pronto!"
    texto_novo = "Escolher outro PDF"
    texto_abrir = "Abrir arquivo"

    def __init__(self, ferramenta: Ferramenta, contexto: ContextoApp):
        super().__init__(ferramenta, contexto)
        self.origem: Path | None = None
        self.info: object = None
        self._pasta_saida_usada = ""
        # Evita consultar o disco (às vezes na rede) a cada tecla digitada nas opções
        self._existencia: dict[Path, bool] = {}

        self.area = AreaSoltar("Arraste um PDF para cá", self.dica_area, com_pasta=False, texto_arquivos="Escolher PDF")
        self.area.caminhos_soltos.connect(self.receber_caminhos)
        self.area.escolher_arquivos.connect(self._escolher_arquivo)

        self.progresso = PainelProgresso()
        self.progresso.cancelar.connect(self.executor.cancelar)
        self.executor.progresso.connect(self.progresso.atualizar)
        self.resultado = PainelResultado(self.texto_novo)
        self.resultado.novo.connect(self.limpar)

        self.estados = QStackedWidget()
        for painel in (self.area, self._montar_painel_opcoes(), self.progresso, self.resultado):
            self.estados.addWidget(painel)
        self.corpo.addWidget(self.estados)

        self._timer_progresso = QTimer(self)
        self._timer_progresso.setSingleShot(True)
        self._timer_progresso.timeout.connect(lambda: self.estados.setCurrentWidget(self.progresso))

    # Ganchos de cada ferramenta

    def carregar(self, origem: Path) -> object:
        """Lê o PDF e o que mais a ferramenta precisar. Roda em segundo plano: não pode tocar na tela."""
        raise NotImplementedError

    def montar_opcoes(self) -> QWidget:
        """Widget com as opções da ferramenta. Chame `atualizar_estado()` quando uma opção mudar."""
        raise NotImplementedError

    def preencher_opcoes(self, info: object) -> None:
        """Ajusta as opções para o PDF recém-carregado."""

    def descrever(self, info: object) -> str:
        """Linha abaixo do nome do arquivo (ex.: "12 páginas")."""
        return ""

    def destino(self) -> Path:
        """Arquivo ou pasta que será gerado, mostrado antes de processar."""
        raise NotImplementedError

    def validar(self) -> str | None:
        """Mensagem quando as opções atuais são inválidas; o botão fica desativado enquanto houver.

        Devolva "" para desativar o botão sem mostrar mensagem (ex.: campo obrigatório ainda vazio).
        """
        return None

    def tarefa(self) -> Tarefa:
        """Tarefa principal, com as opções já lidas da tela."""
        raise NotImplementedError

    def resumo(self, resultado: Resultado) -> str:
        raise NotImplementedError

    # Montagem

    def _montar_painel_opcoes(self) -> QWidget:
        self.nome_arquivo = QLabel()
        self.nome_arquivo.setObjectName("tituloResultado")
        self.nome_arquivo.setWordWrap(True)
        self.detalhes_arquivo = QLabel()
        self.detalhes_arquivo.setObjectName("subtitulo")
        trocar = QPushButton("Trocar arquivo")
        trocar.clicked.connect(self.limpar)
        textos = QVBoxLayout()
        textos.setSpacing(2)
        textos.addWidget(self.nome_arquivo)
        textos.addWidget(self.detalhes_arquivo)
        cabecalho = QHBoxLayout()
        cabecalho.addLayout(textos, 1)
        cabecalho.addWidget(trocar)

        rotulo_destino = QLabel("SERÁ SALVO EM")
        rotulo_destino.setObjectName("rotuloCampo")
        self.rotulo_destino = QLabel()
        self.rotulo_destino.setWordWrap(True)
        self.aviso_opcoes = QLabel()
        self.aviso_opcoes.setObjectName("aviso")
        self.aviso_opcoes.setWordWrap(True)
        self.botao_principal = QPushButton(self.texto_botao)
        self.botao_principal.setObjectName("botaoPrincipal")
        self.botao_principal.clicked.connect(self._processar)
        rodape = QHBoxLayout()
        rodape.addWidget(self.aviso_opcoes, 1)
        rodape.addWidget(self.botao_principal)

        painel = QWidget()
        layout = QVBoxLayout(painel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addLayout(cabecalho)
        layout.addSpacing(6)
        layout.addWidget(self.montar_opcoes(), 1)
        layout.addWidget(rotulo_destino)
        layout.addWidget(self.rotulo_destino)
        layout.addLayout(rodape)
        self.painel_opcoes = painel
        return painel

    # Fluxo

    def _escolher_arquivo(self) -> None:
        inicial = self.contexto.config.ultima_pasta or self.contexto.config.pasta_inicial
        arquivo, _ = QFileDialog.getOpenFileName(self, "Escolha o PDF", inicial, "Arquivos PDF (*.pdf)")
        if arquivo:
            self.receber_caminhos([Path(arquivo)])

    def receber_caminhos(self, caminhos: list[Path]) -> None:
        if self.executor.em_execucao:
            return
        self.area.mostrar_aviso(None)
        try:
            origem = pdf_unico(caminhos)
        except ErroUnePDF as erro:
            self.limpar()
            self.area.mostrar_aviso(str(erro))
            return

        self.progresso.iniciar("Lendo o arquivo...", cancelavel=False)
        self._timer_progresso.start(ATRASO_PROGRESSO_MS)
        self.executar(
            lambda progresso, cancelamento: self.carregar(origem),
            lambda info: self._ao_carregar(origem, info),
            self._ao_falhar_carga,
        )

    def _ao_carregar(self, origem: Path, info: object) -> None:
        self._timer_progresso.stop()
        self.origem, self.info = origem, info
        self._existencia.clear()
        self._pasta_saida_usada = self.contexto.config.pasta_saida
        if self.contexto.config.ultima_pasta != str(origem.parent):
            self.contexto.config.ultima_pasta = str(origem.parent)
            self.contexto.salvar_config()
        self.nome_arquivo.setText(origem.name)
        self.detalhes_arquivo.setText(self.descrever(info))
        self.preencher_opcoes(info)
        self.atualizar_estado()
        self.estados.setCurrentWidget(self.painel_opcoes)

    def _ao_falhar_carga(self, erro: BaseException) -> None:
        self._timer_progresso.stop()
        self.limpar()
        if isinstance(erro, ErroUnePDF):
            self.area.mostrar_aviso(str(erro))
        else:
            mostrar_erro(self, erro)

    def atualizar_estado(self, aviso: str = "") -> None:
        """Atualiza o destino mostrado, os avisos e se o botão principal pode ser usado."""
        if self.origem is None:
            return
        destino = self.destino()
        self.rotulo_destino.setText(str(destino))
        problema = self.validar()
        avisos = [aviso] if aviso else []
        if problema:
            avisos.append(problema)
        elif self._existe(destino):
            avisos.append("Já existe um resultado com esse nome. Ele será substituído.")
        self.aviso_opcoes.setText("\n".join(avisos))
        self.botao_principal.setEnabled(problema is None)

    def _existe(self, caminho: Path) -> bool:
        if caminho not in self._existencia:
            self._existencia[caminho] = caminho.exists()
        return self._existencia[caminho]

    def _processar(self) -> None:
        if self.origem is None or self.executor.em_execucao or self.validar():
            return
        tarefa = self.tarefa()
        self.progresso.iniciar(self.titulo_progresso)
        self.estados.setCurrentWidget(self.progresso)
        self.executar(tarefa, self._ao_processar, self._ao_falhar_processo)

    def _ao_processar(self, resultado: Resultado) -> None:
        self._existencia.clear()
        resumo = self.resumo(resultado)
        if resultado.observacao:
            resumo += f" {resultado.observacao}"
        if resultado.substituiu_anterior:
            resumo += " O resultado anterior com o mesmo nome foi substituído."
        self.resultado.mostrar_sucesso(
            self.titulo_sucesso, resumo, resultado.destino, resultado.ignorados, self.texto_abrir
        )
        self.estados.setCurrentWidget(self.resultado)

    def _ao_falhar_processo(self, erro: BaseException) -> None:
        self.estados.setCurrentWidget(self.painel_opcoes)
        if isinstance(erro, OperacaoCancelada):
            self.atualizar_estado(str(erro))
        else:
            self.atualizar_estado()
            mostrar_erro(self, erro)

    def limpar(self) -> None:
        self.origem = self.info = None
        self.area.mostrar_aviso(None)
        self.estados.setCurrentWidget(self.area)

    def showEvent(self, evento: QShowEvent) -> None:
        super().showEvent(evento)
        # A subpasta de saída pode ter mudado nas configurações
        if self.origem is not None and self._pasta_saida_usada != self.contexto.config.pasta_saida:
            self._pasta_saida_usada = self.contexto.config.pasta_saida
            self.atualizar_estado()
