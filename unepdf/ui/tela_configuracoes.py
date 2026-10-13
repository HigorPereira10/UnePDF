"""Tela de configurações. Cada mudança é salva na hora, sem botão de salvar."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from unepdf.core.configuracoes import Configuracoes, pasta_saida_valida
from unepdf.core.nomenclatura import Perfil, destino_padrao
from unepdf.ui.contexto import ContextoApp
from unepdf.ui.dialogos import mostrar_erro, perguntar
from unepdf.utils import sistema
from unepdf.utils.caminhos import pasta_logs

# Pastas fictícias usadas só para mostrar como fica o nome do arquivo final
EXEMPLO_GENERICO = Path(r"C:\Documentos\Notas de janeiro")
EXEMPLO_NOTAS = Path(r"C:\Notas\DANFE\0001-EMPRESA EXEMPLO LTDA\012026")


def _texto_ajuda(texto: str) -> QLabel:
    rotulo = QLabel(texto)
    rotulo.setObjectName("subtitulo")
    rotulo.setWordWrap(True)
    return rotulo


class _Secao(QFrame):
    """Bloco com título e conteúdo, no mesmo estilo dos cartões da tela inicial."""

    def __init__(self, titulo: str):
        super().__init__()
        self.setObjectName("secaoConfiguracao")
        rotulo = QLabel(titulo)
        rotulo.setObjectName("nomeFerramenta")
        self.corpo = QVBoxLayout(self)
        self.corpo.setContentsMargins(22, 18, 22, 20)
        self.corpo.setSpacing(8)
        self.corpo.addWidget(rotulo)


class TelaConfiguracoes(QWidget):
    def __init__(self, contexto: ContextoApp):
        super().__init__()
        self.contexto = contexto

        titulo = QLabel("Configurações")
        titulo.setObjectName("titulo")
        subtitulo = QLabel("As mudanças são salvas automaticamente e valem para todas as ferramentas.")
        subtitulo.setObjectName("subtitulo")

        conteudo = QWidget()
        conteudo.setObjectName("areaConteudo")
        layout = QVBoxLayout(conteudo)
        layout.setContentsMargins(36, 32, 36, 28)
        layout.setSpacing(16)
        layout.addWidget(titulo)
        layout.addWidget(subtitulo)
        layout.addSpacing(8)
        layout.addWidget(self._montar_pasta_inicial())
        layout.addWidget(self._montar_nomenclatura())
        layout.addWidget(self._montar_manutencao())
        layout.addStretch()

        rolagem = QScrollArea()
        rolagem.setWidgetResizable(True)
        rolagem.setWidget(conteudo)
        externo = QVBoxLayout(self)
        externo.setContentsMargins(0, 0, 0, 0)
        externo.addWidget(rolagem)

        self.carregar()

    def _montar_pasta_inicial(self) -> _Secao:
        secao = _Secao("Pasta inicial")
        secao.corpo.addWidget(_texto_ajuda(
            "Onde os diálogos de escolha abrem quando ainda não há uma pasta usada recentemente. "
            "Pode ser uma pasta da rede, como a pasta onde ficam as notas fiscais."
        ))
        self.campo_pasta_inicial = QLineEdit()
        self.campo_pasta_inicial.setReadOnly(True)
        self.campo_pasta_inicial.setPlaceholderText("Nenhuma: usa a pasta padrão do Windows")
        escolher = QPushButton("Escolher...")
        escolher.clicked.connect(self._escolher_pasta_inicial)
        limpar = QPushButton("Limpar")
        limpar.clicked.connect(lambda: self._definir_pasta_inicial(""))
        linha = QHBoxLayout()
        linha.addWidget(self.campo_pasta_inicial, 1)
        linha.addWidget(escolher)
        linha.addWidget(limpar)
        secao.corpo.addLayout(linha)
        return secao

    def _montar_nomenclatura(self) -> _Secao:
        secao = _Secao("Arquivo final")

        rotulo_saida = QLabel("SUBPASTA DE SAÍDA")
        rotulo_saida.setObjectName("rotuloCampo")
        self.campo_pasta_saida = QLineEdit()
        self.campo_pasta_saida.setMaximumWidth(320)
        self.campo_pasta_saida.textEdited.connect(self._alterar_pasta_saida)
        self.erro_pasta_saida = QLabel()
        self.erro_pasta_saida.setObjectName("aviso")
        self.erro_pasta_saida.hide()
        secao.corpo.addWidget(rotulo_saida)
        secao.corpo.addWidget(_texto_ajuda(
            "Criada dentro da pasta de origem para guardar o resultado. Ela nunca é usada como origem."
        ))
        secao.corpo.addWidget(self.campo_pasta_saida)
        secao.corpo.addWidget(self.erro_pasta_saida)
        secao.corpo.addSpacing(10)

        rotulo_perfil = QLabel("NOME DO ARQUIVO")
        rotulo_perfil.setObjectName("rotuloCampo")
        self.opcao_generico = QRadioButton("Genérico: usa o nome da pasta")
        self.opcao_notas = QRadioButton("Notas fiscais: tipo, empresa e competência")
        self._perfis = QButtonGroup(self)
        self._perfis.addButton(self.opcao_generico)
        self._perfis.addButton(self.opcao_notas)
        self._perfis.buttonClicked.connect(self._alterar_perfil)
        secao.corpo.addWidget(rotulo_perfil)
        secao.corpo.addWidget(self.opcao_generico)
        secao.corpo.addWidget(self.opcao_notas)
        secao.corpo.addWidget(_texto_ajuda(
            "O perfil Notas fiscais reconhece pastas no formato TIPO\\EMPRESA\\MMAAAA, com o tipo "
            "DANFE, DANFSE, DANFCE ou DACTE. Em pastas fora desse formato, usa o nome genérico."
        ))
        secao.corpo.addSpacing(6)

        rotulo_previa = QLabel("EXEMPLO")
        rotulo_previa.setObjectName("rotuloCampo")
        self.previa = QLabel()
        self.previa.setObjectName("previaCaminho")
        self.previa.setWordWrap(True)
        secao.corpo.addWidget(rotulo_previa)
        secao.corpo.addWidget(self.previa)
        return secao

    def _montar_manutencao(self) -> _Secao:
        secao = _Secao("Suporte")
        secao.corpo.addWidget(_texto_ajuda(
            "O registro de atividades ajuda a investigar problemas. Ele fica só neste computador."
        ))
        abrir_logs = QPushButton("Abrir pasta de registros")
        abrir_logs.clicked.connect(self._abrir_logs)
        restaurar = QPushButton("Restaurar configurações padrão")
        restaurar.clicked.connect(self._restaurar_padroes)
        linha = QHBoxLayout()
        linha.addWidget(abrir_logs)
        linha.addWidget(restaurar)
        linha.addStretch()
        secao.corpo.addLayout(linha)
        return secao

    def carregar(self) -> None:
        """Preenche os campos com as configurações atuais."""
        config = self.contexto.config
        self.campo_pasta_inicial.setText(config.pasta_inicial)
        self.campo_pasta_saida.setText(config.pasta_saida)
        self.erro_pasta_saida.hide()
        (self.opcao_notas if config.perfil_nomenclatura is Perfil.NOTAS_FISCAIS else self.opcao_generico).setChecked(True)
        self._atualizar_previa()

    def _atualizar_previa(self) -> None:
        config = self.contexto.config
        exemplo = EXEMPLO_NOTAS if config.perfil_nomenclatura is Perfil.NOTAS_FISCAIS else EXEMPLO_GENERICO
        self.previa.setText(str(destino_padrao(exemplo, config.perfil_nomenclatura, config.pasta_saida)))

    def _escolher_pasta_inicial(self) -> None:
        pasta = QFileDialog.getExistingDirectory(self, "Escolha a pasta inicial", self.contexto.config.pasta_inicial)
        if pasta:
            self._definir_pasta_inicial(str(Path(pasta)))

    def _definir_pasta_inicial(self, pasta: str) -> None:
        self.contexto.config.pasta_inicial = pasta
        self.campo_pasta_inicial.setText(pasta)
        self.contexto.salvar_config()

    def _alterar_pasta_saida(self, texto: str) -> None:
        if not pasta_saida_valida(texto):
            self.erro_pasta_saida.setText('Use um nome de pasta simples, sem \\ / : * ? " < > |')
            self.erro_pasta_saida.show()
            return
        self.erro_pasta_saida.hide()
        self.contexto.config.pasta_saida = texto.strip()
        self.contexto.salvar_config()
        self._atualizar_previa()

    def _alterar_perfil(self) -> None:
        perfil = Perfil.NOTAS_FISCAIS if self.opcao_notas.isChecked() else Perfil.GENERICO
        self.contexto.config.perfil_nomenclatura = perfil
        self.contexto.salvar_config()
        self._atualizar_previa()

    def _abrir_logs(self) -> None:
        try:
            pasta = pasta_logs()
            pasta.mkdir(parents=True, exist_ok=True)
            sistema.abrir_arquivo(pasta)
        except Exception as erro:
            mostrar_erro(self, erro, "Não foi possível abrir")

    def _restaurar_padroes(self) -> None:
        if not perguntar(
            self,
            "Restaurar configurações",
            "Voltar todas as configurações para os valores padrão?",
            confirmar="Restaurar",
            recusar="Cancelar",
        ):
            return
        # A última pasta usada não é uma preferência, então é mantida
        padrao = Configuracoes(ultima_pasta=self.contexto.config.ultima_pasta)
        for campo, valor in vars(padrao).items():
            setattr(self.contexto.config, campo, valor)
        self.contexto.salvar_config()
        self.carregar()
