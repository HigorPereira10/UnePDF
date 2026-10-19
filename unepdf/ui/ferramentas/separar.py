"""Ferramenta Separar emitidas e recebidas: move as notas de cada pasta para as subpastas do seu lado."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QShowEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QRadioButton,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from unepdf.core.erros import OperacaoCancelada
from unepdf.core.separar import (
    COMO_USUARIO,
    PASTA_REPETIDAS,
    Lado,
    LeituraPasta,
    Plano,
    Registro,
    ResultadoDesfazer,
    ResultadoSeparacao,
    chave_empresa,
    desfazer,
    formatar_documento,
    ler_pastas,
    nomes_das_pastas,
    planejar,
    separar,
    sugestao_pelo_nome,
    todas_as_pastas,
    ultimo_registro,
)
from unepdf.ui.componentes import AreaSoltar, PainelProgresso
from unepdf.ui.contexto import ContextoApp
from unepdf.ui.dialogos import mostrar_erro
from unepdf.ui.ferramentas.base import TelaFerramenta
from unepdf.ui.tema import CORES
from unepdf.utils import sistema
from unepdf.utils.texto import plural

if TYPE_CHECKING:
    from unepdf.ui.ferramentas import Ferramenta

CANDIDATOS_MOSTRADOS = 5


@dataclass
class _Analise:
    leituras: list[LeituraPasta]
    planos: dict[Path, Plano] = field(default_factory=dict)
    # Separação anterior que ainda pode ser desfeita, quando uma pasta só foi escolhida
    anterior: Registro | None = None


def _arvore(colunas: list[str]) -> QTreeWidget:
    arvore = QTreeWidget()
    arvore.setHeaderLabels(colunas)
    arvore.setUniformRowHeights(True)
    arvore.header().setStretchLastSection(False)
    arvore.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    for coluna in range(1, len(colunas)):
        arvore.header().setSectionResizeMode(coluna, QHeaderView.ResizeMode.ResizeToContents)
    return arvore


def trecho_do_documento(leitura: LeituraPasta, documento: str) -> str:
    """Texto que vem antes do CNPJ na primeira nota em que ele aparece: costuma ser o nome da empresa."""
    formatado = formatar_documento(documento)
    for nota in leitura.notas:
        posicao = nota.texto.upper().find(formatado)
        if posicao > 0:
            trecho = " ".join(nota.texto[max(0, posicao - 90):posicao].split())
            return re.sub(r"^\S*\s", "", trecho)[-70:]  # descarta a palavra cortada no começo
    return ""


class DialogoEmpresa(QDialog):
    """Pergunta qual dos documentos que aparecem nas notas é a empresa dona da pasta."""

    def __init__(self, pai: QWidget | None, leitura: LeituraPasta, motivo: str):
        super().__init__(pai)
        self.setWindowTitle("Qual é a empresa desta pasta?")
        self.setMinimumWidth(560)
        texto = QLabel(f"{motivo}\n\n{leitura.pasta}")
        texto.setWordWrap(True)
        emitentes = {nota.emitente for nota in leitura.notas if nota.emitente and not nota.evento}

        self._grupo = QButtonGroup(self)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.addWidget(texto)
        sugerido = leitura.empresa or sugestao_pelo_nome(leitura)
        for documento, votos in leitura.candidatos[:CANDIDATOS_MOSTRADOS]:
            detalhes = [f"aparece em {votos} de {leitura.com_participantes} notas"]
            if emitentes == {documento}:
                detalhes.append("emitiu todas as notas")
            if documento == sugerido and not leitura.empresa:
                detalhes.append("o nome da pasta aparece junto dele")
            opcao = QRadioButton(f"{formatar_documento(documento)}  ({', '.join(detalhes)})")
            opcao.setProperty("documento", documento)
            if documento == sugerido:
                opcao.setChecked(True)
            self._grupo.addButton(opcao)
            layout.addWidget(opcao)
            trecho = trecho_do_documento(leitura, documento)
            if trecho:
                dica = QLabel(f"...{trecho}")
                dica.setObjectName("subtitulo")
                dica.setContentsMargins(26, 0, 0, 4)
                layout.addWidget(dica)

        botoes = QDialogButtonBox()
        self.botao_usar = botoes.addButton("Usar esta empresa", QDialogButtonBox.ButtonRole.AcceptRole)
        botoes.addButton("Pular esta pasta", QDialogButtonBox.ButtonRole.RejectRole)
        botoes.accepted.connect(self.accept)
        botoes.rejected.connect(self.reject)
        self.botao_usar.setEnabled(self._grupo.checkedButton() is not None)
        self._grupo.buttonClicked.connect(lambda *_: self.botao_usar.setEnabled(True))
        layout.addSpacing(6)
        layout.addWidget(botoes)

    @property
    def escolhido(self) -> str:
        botao = self._grupo.checkedButton()
        return botao.property("documento") if botao else ""


class TelaSepararNotas(TelaFerramenta):
    aceita_arquivos = True

    def __init__(self, ferramenta: Ferramenta, contexto: ContextoApp):
        super().__init__(ferramenta, contexto)
        self._analise: _Analise | None = None
        self._resultados: list[ResultadoSeparacao] = []
        self._ultimas_pastas: list[Path] = []
        self._config_usada: tuple = ()

        self.area = AreaSoltar(
            "Arraste a pasta do mês para cá",
            "As notas (PDF ou XML) que estão direto na pasta vão para as subpastas de emitidas e "
            "recebidas, criadas dentro dela. Pode arrastar várias pastas de uma vez.",
        )
        self.area.botao_arquivos.hide()
        self.area.caminhos_soltos.connect(self.receber_caminhos)
        self.area.escolher_pasta.connect(self._escolher_pasta)

        self.progresso = PainelProgresso()
        self.progresso.cancelar.connect(self.executor.cancelar)
        self.executor.progresso.connect(self.progresso.atualizar)

        self.estados = QStackedWidget()
        for painel in (self.area, self._montar_painel_previa(), self.progresso, self._montar_painel_resultado()):
            self.estados.addWidget(painel)
        self.corpo.addWidget(self.estados)

    def _montar_painel_previa(self) -> QWidget:
        self.resumo_previa = QLabel()
        self.resumo_previa.setObjectName("tituloResultado")
        self.origem_previa = QLabel()
        self.origem_previa.setObjectName("subtitulo")
        self.origem_previa.setWordWrap(True)
        trocar = QPushButton("Trocar pasta")
        trocar.clicked.connect(self.limpar)
        textos = QVBoxLayout()
        textos.setSpacing(2)
        textos.addWidget(self.resumo_previa)
        textos.addWidget(self.origem_previa)
        cabecalho = QHBoxLayout()
        cabecalho.addLayout(textos, 1)
        cabecalho.addWidget(trocar)

        self.lista_previa = _arvore(["Pasta", "Empresa", "Emitidas", "Recebidas", "Repetidas", "Sem classificação"])
        self.lista_previa.itemSelectionChanged.connect(self._atualizar_botao_trocar)
        self.lista_previa.itemDoubleClicked.connect(lambda *_: self._trocar_empresa())

        self.info_previa = QLabel()
        self.info_previa.setObjectName("subtitulo")
        self.info_previa.setWordWrap(True)
        self.aviso_previa = QLabel()
        self.aviso_previa.setObjectName("aviso")
        self.aviso_previa.setWordWrap(True)
        self.aviso_previa.hide()

        self.botao_trocar_empresa = QPushButton("Trocar empresa")
        self.botao_trocar_empresa.clicked.connect(self._trocar_empresa)
        self.botao_desfazer_anterior = QPushButton("Desfazer a última separação")
        self.botao_desfazer_anterior.clicked.connect(self._desfazer_anterior)
        self.botao_separar = QPushButton()
        self.botao_separar.setObjectName("botaoPrincipal")
        self.botao_separar.clicked.connect(self._separar)
        rodape = QHBoxLayout()
        rodape.addWidget(self.botao_trocar_empresa)
        rodape.addWidget(self.botao_desfazer_anterior)
        rodape.addStretch()
        rodape.addWidget(self.botao_separar)

        painel = QWidget()
        layout = QVBoxLayout(painel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addLayout(cabecalho)
        layout.addWidget(self.lista_previa, 1)
        layout.addWidget(self.aviso_previa)
        layout.addWidget(self.info_previa)
        layout.addLayout(rodape)
        self.painel_previa = painel
        return painel

    def _montar_painel_resultado(self) -> QWidget:
        self.titulo_resultado = QLabel()
        self.titulo_resultado.setObjectName("tituloResultado")
        self.resumo_resultado = QLabel()
        self.resumo_resultado.setWordWrap(True)
        dica = QLabel("Clique duas vezes em uma pasta para abrir no Explorador de Arquivos.")
        dica.setObjectName("subtitulo")

        self.lista_resultado = _arvore(["Pasta", "Resultado"])
        self.lista_resultado.itemDoubleClicked.connect(self._abrir_item)

        self.botao_abrir = QPushButton("Abrir pasta")
        self.botao_abrir.setObjectName("botaoPrincipal")
        self.botao_abrir.clicked.connect(self._abrir_primeira)
        self.botao_desfazer = QPushButton("Desfazer")
        self.botao_desfazer.clicked.connect(self._desfazer_resultados)
        novo = QPushButton("Separar outra pasta")
        novo.clicked.connect(self.limpar)
        botoes = QHBoxLayout()
        botoes.addWidget(self.botao_abrir)
        botoes.addWidget(self.botao_desfazer)
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

    # Escolha das pastas e análise

    def _pasta_para_dialogo(self) -> str:
        for candidata in (self.contexto.config.ultima_pasta, self.contexto.config.pasta_inicial):
            if candidata and Path(candidata).is_dir():
                return candidata
        return ""

    def _escolher_pasta(self) -> None:
        pasta = QFileDialog.getExistingDirectory(self, "Escolha a pasta do mês", self._pasta_para_dialogo())
        if pasta:
            self.receber_caminhos([Path(pasta)])

    def receber_caminhos(self, caminhos: list[Path]) -> None:
        if self.executor.em_execucao:
            return
        self.area.mostrar_aviso(None)
        pastas = list(dict.fromkeys(caminhos))
        if not pastas or not all(p.is_dir() for p in pastas):
            self.estados.setCurrentWidget(self.area)
            self.area.mostrar_aviso("Escolha pastas, não arquivos: a pasta do mês, onde estão as notas.")
            return
        config = self.contexto.config
        self._ultimas_pastas = pastas
        self._config_usada = (config.pasta_saida, repr(config.separar_pastas))
        conhecidas = dict(config.separar_empresas)
        pasta_saida = config.pasta_saida
        reservadas = todas_as_pastas(config.separar_pastas)

        def analisar(progresso, cancelamento) -> _Analise:
            leituras = ler_pastas(pastas, conhecidas, pasta_saida, reservadas, progresso, cancelamento)
            anterior = ultimo_registro(pastas[0]) if len(pastas) == 1 else None
            return _Analise(leituras, anterior=anterior)

        self.progresso.iniciar("Lendo as notas...")
        self.estados.setCurrentWidget(self.progresso)
        self.executar(analisar, self._ao_analisar, self._ao_falhar_analise)

    def _ao_falhar_analise(self, erro: BaseException) -> None:
        self.estados.setCurrentWidget(self.area)
        if isinstance(erro, OperacaoCancelada):
            self.area.mostrar_aviso("Leitura cancelada. Nada foi movido.")
        else:
            mostrar_erro(self, erro)

    def _ao_analisar(self, analise: _Analise) -> None:
        self._analise = analise
        self._lembrar_pasta(analise.leituras[0].pasta)
        for leitura in analise.leituras:
            if leitura.erro or leitura.empresa:
                continue
            if not leitura.candidatos:
                leitura.erro = "Não deu para descobrir a empresa: nenhuma nota tem o emitente e o destinatário legíveis."
                continue
            escolhido = self._perguntar_empresa(
                leitura,
                "Não deu para saber sozinho qual é a empresa desta pasta: os mesmos participantes aparecem "
                "nas notas. Qual destes é a empresa?",
            )
            if escolhido:
                leitura.empresa, leitura.como = escolhido, COMO_USUARIO
            else:
                leitura.erro = "Pasta pulada: a empresa não foi escolhida."
        self._guardar_empresas(analise.leituras)
        self._planejar(analise)

    def _perguntar_empresa(self, leitura: LeituraPasta, motivo: str) -> str:
        """Documento escolhido pelo usuário, ou vazio se ele pulou a pasta. Os testes substituem este método."""
        dialogo = DialogoEmpresa(self, leitura, motivo)
        return dialogo.escolhido if dialogo.exec() == QDialog.DialogCode.Accepted else ""

    def _guardar_empresas(self, leituras: list[LeituraPasta]) -> None:
        empresas = self.contexto.config.separar_empresas
        mudou = False
        for leitura in leituras:
            chave = chave_empresa(leitura.pasta)
            if leitura.guardar_empresa and empresas.get(chave) != leitura.empresa:
                empresas[chave] = leitura.empresa
                mudou = True
        if mudou:
            self.contexto.salvar_config()

    def _planejar(self, analise: _Analise) -> None:
        config = self.contexto.config
        personalizados, pasta_saida = dict(config.separar_pastas), config.pasta_saida

        def montar(progresso, cancelamento) -> _Analise:
            analise.planos = {
                leitura.pasta: planejar(leitura, leitura.empresa, nomes_das_pastas(leitura.tipo, personalizados), pasta_saida)
                for leitura in analise.leituras if leitura.empresa and not leitura.erro
            }
            return analise

        self.progresso.iniciar("Preparando a separação...", cancelavel=False)
        self.estados.setCurrentWidget(self.progresso)
        self.executar(montar, self._mostrar_previa, self._ao_falhar_analise)

    # Prévia

    def _mostrar_previa(self, analise: _Analise) -> None:
        self._analise = analise
        planos = list(analise.planos.values())
        notas = sum(len(l.notas) for l in analise.leituras)
        self.resumo_previa.setText(
            f"{plural(notas, 'nota', 'notas')} em {plural(len(analise.leituras), 'pasta', 'pastas')}"
        )
        self.origem_previa.setText(
            str(analise.leituras[0].pasta) if len(analise.leituras) == 1 else f"Em {analise.leituras[0].pasta.parent}"
        )

        aviso = QBrush(QColor(CORES.aviso))
        apagado = QBrush(QColor(CORES.texto_desativado))
        self.lista_previa.clear()
        for leitura in analise.leituras:
            plano = analise.planos.get(leitura.pasta)
            if plano is None:
                linha = QTreeWidgetItem([leitura.pasta.name, leitura.erro or "Nada a fazer"])
                for coluna in range(2):
                    linha.setForeground(coluna, apagado)
                linha.setToolTip(0, str(leitura.pasta))
                linha.setToolTip(1, leitura.erro)
                self.lista_previa.addTopLevelItem(linha)
                continue
            repetidas = plano.quantidade(None) + len(plano.copias)
            linha = QTreeWidgetItem([
                leitura.pasta.name,
                self._texto_empresa(leitura),
                f"{plano.quantidade(Lado.EMITIDAS)} em {plano.nomes[Lado.EMITIDAS]}",
                f"{plano.quantidade(Lado.RECEBIDAS)} em {plano.nomes[Lado.RECEBIDAS]}",
                str(repetidas),
                str(len(plano.nao_classificadas)),
            ])
            linha.setData(0, Qt.ItemDataRole.UserRole, leitura.pasta)
            linha.setToolTip(0, str(leitura.pasta))
            linha.setToolTip(1, self._dica_empresa(leitura))
            if leitura.conferir_empresa:
                for coluna in range(2):
                    linha.setForeground(coluna, aviso)
            linha.setToolTip(4, (
                f"{plural(len(plano.copias), 'cópia idêntica será apagada', 'cópias idênticas serão apagadas')}; "
                f"{plural(plano.quantidade(None), 'outra versão vai', 'outras versões vão')} para {PASTA_REPETIDAS}"
            ))
            for coluna in range(2, 6):
                linha.setTextAlignment(coluna, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            for ignorado in plano.nao_classificadas:
                filho = QTreeWidgetItem([ignorado.caminho.name, ignorado.motivo])
                filho.setToolTip(0, str(ignorado.caminho))
                filho.setToolTip(1, ignorado.motivo)
                filho.setForeground(0, aviso)
                filho.setForeground(1, aviso)
                linha.addChild(filho)
            self.lista_previa.addTopLevelItem(linha)

        pasta_saida = self.contexto.config.pasta_saida
        self.info_previa.setText(
            "As notas vão para as subpastas indicadas, dentro de cada pasta. Cópias idênticas de uma nota são "
            f'apagadas e outras versões da mesma nota vão para "{pasta_saida}\\{PASTA_REPETIDAS}". As notas sem '
            "classificação ficam onde estão. A separação pode ser desfeita depois."
        )
        conferir = sum(1 for l in analise.leituras if l.pasta in analise.planos and l.conferir_empresa)
        self.aviso_previa.setText(plural(
            conferir,
            "pasta com a empresa para conferir: o nome da pasta aparece junto de outro CNPJ nas notas. "
            "Clique duas vezes nela para ver e trocar.",
            "pastas com a empresa para conferir: o nome da pasta aparece junto de outro CNPJ nas notas. "
            "Clique duas vezes nelas para ver e trocar.",
        ) if conferir else "")
        self.aviso_previa.setVisible(bool(conferir))
        mudancas = sum(len(p.movimentos) + len(p.copias) for p in planos)
        self.botao_separar.setText("Separar " + plural(mudancas, "nota", "notas") if mudancas else "Nada para separar")
        self.botao_separar.setEnabled(bool(mudancas))
        self.botao_desfazer_anterior.setVisible(analise.anterior is not None)
        if analise.anterior:
            self.botao_desfazer_anterior.setToolTip(
                f"Separação de {analise.anterior.data:%d/%m/%Y %H:%M}: "
                f"{plural(len(analise.anterior.movidos), 'nota volta', 'notas voltam')} para a pasta."
            )
        self._atualizar_botao_trocar()
        self.estados.setCurrentWidget(self.painel_previa)

    @staticmethod
    def _texto_empresa(leitura: LeituraPasta) -> str:
        documento = formatar_documento(leitura.empresa)
        if leitura.conferir_empresa:
            return f"Confira: {documento}"
        # A linha da nota onde aparece o nome da pasta, junto do CNPJ escolhido, para conferir de relance
        return f"{documento}  {leitura.nome_na_nota}" if leitura.documento_do_nome else documento

    @staticmethod
    def _dica_empresa(leitura: LeituraPasta) -> str:
        dica = f"Empresa descoberta {leitura.como}."
        if leitura.conferir_empresa:
            dica += (
                f"\nAtenção: nas notas, o nome da pasta aparece junto de {formatar_documento(leitura.documento_do_nome)}"
                f' ("{leitura.nome_na_nota}"), e não do CNPJ escolhido.'
            )
        elif leitura.documento_do_nome:
            dica += f'\nNas notas, o nome da pasta aparece junto deste CNPJ: "{leitura.nome_na_nota}".'
        return dica + "\nClique duas vezes para trocar."

    def _leitura_selecionada(self) -> LeituraPasta | None:
        item = self.lista_previa.currentItem()
        while item is not None and item.parent() is not None:
            item = item.parent()
        pasta = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        if not pasta or not self._analise:
            return None
        return next((l for l in self._analise.leituras if l.pasta == pasta and l.candidatos), None)

    def _atualizar_botao_trocar(self) -> None:
        self.botao_trocar_empresa.setEnabled(self._leitura_selecionada() is not None)

    def _trocar_empresa(self) -> None:
        leitura = self._leitura_selecionada()
        if leitura is None or self.executor.em_execucao:
            return
        escolhido = self._perguntar_empresa(leitura, "Qual destes é a empresa desta pasta?")
        if escolhido and escolhido != leitura.empresa:
            leitura.empresa, leitura.como = escolhido, COMO_USUARIO
            self._guardar_empresas([leitura])
            self._planejar(self._analise)

    def showEvent(self, evento: QShowEvent) -> None:
        super().showEvent(evento)
        # Nomes das subpastas ou subpasta de saída alterados nas configurações mudam a prévia
        config = self.contexto.config
        mudou = self._config_usada != (config.pasta_saida, repr(config.separar_pastas))
        if mudou and self._analise and self.estados.currentWidget() is self.painel_previa and not self.executor.em_execucao:
            self._config_usada = (config.pasta_saida, repr(config.separar_pastas))
            self._planejar(self._analise)

    def limpar(self) -> None:
        self._analise = None
        self.area.mostrar_aviso(None)
        self.estados.setCurrentWidget(self.area)

    # Separação

    def _separar(self) -> None:
        if not self._analise or self.executor.em_execucao:
            return
        planos = [p for p in self._analise.planos.values() if not p.vazio]
        if not planos:
            return
        self.progresso.iniciar("Separando as notas...")
        self.estados.setCurrentWidget(self.progresso)
        self.executar(
            lambda progresso, cancelamento: separar(planos, progresso, cancelamento),
            self._mostrar_resultado,
            self._ao_falhar_separacao,
        )

    def _ao_falhar_separacao(self, erro: BaseException) -> None:
        self.estados.setCurrentWidget(self.painel_previa)
        mostrar_erro(self, erro)

    def _definir_titulo(self, titulo: str, estado: str) -> None:
        self.titulo_resultado.setText(titulo)
        self.titulo_resultado.setProperty("estado", estado)
        self.titulo_resultado.style().unpolish(self.titulo_resultado)
        self.titulo_resultado.style().polish(self.titulo_resultado)

    def _mostrar_resultado(self, resultados: list[ResultadoSeparacao]) -> None:
        self._resultados = resultados
        cancelado = any(r.cancelado for r in resultados)
        falhas = sum(len(r.falhas) for r in resultados)
        if cancelado:
            self._definir_titulo("Separação cancelada", "falha")
        elif falhas:
            self._definir_titulo("Separação concluída, com problemas", "falha")
        else:
            self._definir_titulo("Notas separadas!", "sucesso")

        movidas = sum(r.movidas[Lado.EMITIDAS] + r.movidas[Lado.RECEBIDAS] for r in resultados)
        partes = [plural(movidas, "nota separada", "notas separadas")]
        repetidas = sum(r.movidas[None] for r in resultados)
        apagadas = sum(r.apagadas for r in resultados)
        sem_classificacao = sum(len(r.nao_classificadas) for r in resultados)
        if apagadas:
            partes.append(plural(apagadas, "cópia idêntica apagada", "cópias idênticas apagadas"))
        if repetidas:
            partes.append(plural(repetidas, f"versão repetida movida para {PASTA_REPETIDAS}", f"versões repetidas movidas para {PASTA_REPETIDAS}"))
        if sem_classificacao:
            partes.append(plural(sem_classificacao, "nota ficou sem classificação", "notas ficaram sem classificação"))
        if falhas:
            partes.append(plural(falhas, "arquivo não pôde ser mexido", "arquivos não puderam ser mexidos"))
        resumo = ", ".join(partes) + "."
        if cancelado:
            resumo += " O que já foi movido pode ser desfeito."
        self.resumo_resultado.setText(resumo)

        aviso = QBrush(QColor(CORES.aviso))
        self.lista_resultado.clear()
        for resultado in resultados:
            texto = (
                f"{resultado.movidas[Lado.EMITIDAS]} em {resultado.nomes[Lado.EMITIDAS]}, "
                f"{resultado.movidas[Lado.RECEBIDAS]} em {resultado.nomes[Lado.RECEBIDAS]}"
            )
            if resultado.cancelado and not resultado.registro:
                texto = "Não processada (cancelado)"
            linha = QTreeWidgetItem([resultado.pasta.name, texto])
            linha.setData(0, Qt.ItemDataRole.UserRole, resultado.pasta)
            linha.setToolTip(0, str(resultado.pasta))
            for ignorado in [*resultado.falhas, *resultado.nao_classificadas]:
                filho = QTreeWidgetItem([ignorado.caminho.name, ignorado.motivo])
                filho.setToolTip(0, str(ignorado.caminho))
                filho.setToolTip(1, ignorado.motivo)
                filho.setForeground(0, aviso)
                filho.setForeground(1, aviso)
                linha.addChild(filho)
            self.lista_resultado.addTopLevelItem(linha)
        self.botao_desfazer.setText("Desfazer")
        self.botao_desfazer.setEnabled(any(r.registro for r in resultados))
        self.estados.setCurrentWidget(self.painel_resultado)

    # Desfazer

    def _desfazer(self, arquivos: list[Path]) -> None:
        def tarefa(progresso, cancelamento) -> list[ResultadoDesfazer]:
            return [desfazer(Registro.de_json(arquivo), progresso) for arquivo in arquivos]

        self.progresso.iniciar("Devolvendo as notas...", cancelavel=False)
        self.estados.setCurrentWidget(self.progresso)
        self.executar(tarefa, self._mostrar_desfeito, self._ao_falhar_desfazer)

    def _desfazer_resultados(self) -> None:
        arquivos = [r.registro for r in self._resultados if r.registro and r.registro.exists()]
        if arquivos and not self.executor.em_execucao:
            self._desfazer(arquivos)

    def _desfazer_anterior(self) -> None:
        anterior = self._analise.anterior if self._analise else None
        if anterior and anterior.arquivo and not self.executor.em_execucao:
            self._resultados = []
            self._desfazer([anterior.arquivo])

    def _ao_falhar_desfazer(self, erro: BaseException) -> None:
        self.estados.setCurrentWidget(self.painel_resultado)
        mostrar_erro(self, erro, "Não foi possível desfazer")

    def _mostrar_desfeito(self, resultados: list[ResultadoDesfazer]) -> None:
        devolvidas = sum(r.devolvidas for r in resultados)
        falhas = [falha for r in resultados for falha in r.falhas]
        self._definir_titulo("Separação desfeita" if not falhas else "Separação desfeita em parte", "falha" if falhas else "sucesso")
        resumo = plural(devolvidas, "nota voltou para a pasta original.", "notas voltaram para a pasta original.")
        copias = sum(r.copias_apagadas for r in resultados)
        if copias:
            resumo += " " + plural(
                copias, "cópia idêntica apagada não volta", "cópias idênticas apagadas não voltam"
            ) + ", mas a nota igual a ela continua na pasta."
        if falhas:
            resumo += " As notas abaixo ficaram onde estavam; dá para tentar desfazer de novo depois."
        self.resumo_resultado.setText(resumo)

        aviso = QBrush(QColor(CORES.aviso))
        self.lista_resultado.clear()
        for resultado in resultados:
            linha = QTreeWidgetItem([resultado.pasta.name, plural(resultado.devolvidas, "nota devolvida", "notas devolvidas")])
            linha.setData(0, Qt.ItemDataRole.UserRole, resultado.pasta)
            linha.setToolTip(0, str(resultado.pasta))
            for falha in resultado.falhas:
                filho = QTreeWidgetItem([falha.caminho.name, falha.motivo])
                filho.setToolTip(0, str(falha.caminho))
                filho.setForeground(0, aviso)
                filho.setForeground(1, aviso)
                linha.addChild(filho)
            self.lista_resultado.addTopLevelItem(linha)
        self._resultados = []
        self.botao_desfazer.setText("Desfeito")
        self.botao_desfazer.setEnabled(False)
        self.estados.setCurrentWidget(self.painel_resultado)

    # Explorador de Arquivos

    def _abrir_item(self, item: QTreeWidgetItem) -> None:
        while item.parent() is not None:
            item = item.parent()
        pasta = item.data(0, Qt.ItemDataRole.UserRole)
        if pasta:
            self._abrir(pasta)

    def _abrir_primeira(self) -> None:
        item = self.lista_resultado.topLevelItem(0)
        if item is not None:
            self._abrir_item(item)

    def _abrir(self, pasta: Path) -> None:
        try:
            sistema.abrir_arquivo(pasta)
        except Exception as erro:
            mostrar_erro(self, erro, "Não foi possível abrir")

    def _lembrar_pasta(self, pasta: Path) -> None:
        if self.contexto.config.ultima_pasta != str(pasta):
            self.contexto.config.ultima_pasta = str(pasta)
            self.contexto.salvar_config()
