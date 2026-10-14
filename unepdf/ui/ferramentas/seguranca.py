"""Ferramentas de segurança: proteger com senha e remover senha."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtWidgets import QCheckBox, QLabel, QLineEdit, QVBoxLayout, QWidget

from unepdf.core.erros import ErroUnePDF
from unepdf.core.leitor_pdf import abrir_pdf_ou_erro
from unepdf.core.modelos import Resultado
from unepdf.core.nomenclatura import destino_derivado
from unepdf.core.seguranca import TAMANHO_MINIMO_SENHA, SituacaoSenha, proteger, remover_senha, situacao_senha
from unepdf.ui.executor import Tarefa
from unepdf.ui.ferramentas.arquivo_unico import TelaArquivoUnico
from unepdf.utils.texto import plural


def _rotulo(texto: str) -> QLabel:
    rotulo = QLabel(texto)
    rotulo.setObjectName("rotuloCampo")
    return rotulo


def _ajuda(texto: str = "") -> QLabel:
    rotulo = QLabel(texto)
    rotulo.setObjectName("subtitulo")
    rotulo.setWordWrap(True)
    return rotulo


def _campo_senha(espaco_reservado: str) -> QLineEdit:
    campo = QLineEdit()
    campo.setEchoMode(QLineEdit.EchoMode.Password)
    campo.setPlaceholderText(espaco_reservado)
    campo.setMaximumWidth(360)
    return campo


def _alternar_visibilidade(campos: list[QLineEdit], visivel: bool) -> None:
    modo = QLineEdit.EchoMode.Normal if visivel else QLineEdit.EchoMode.Password
    for campo in campos:
        campo.setEchoMode(modo)


@dataclass
class InfoPdf:
    paginas: int


class TelaProteger(TelaArquivoUnico):
    dica_area = "O PDF protegido só abre com a senha, em qualquer leitor de PDF."
    texto_botao = "Proteger PDF"
    titulo_progresso = "Protegendo o PDF..."
    titulo_sucesso = "PDF protegido!"
    texto_novo = "Proteger outro PDF"

    def carregar(self, origem: Path) -> InfoPdf:
        return InfoPdf(len(abrir_pdf_ou_erro(origem).pages))

    def montar_opcoes(self) -> QWidget:
        self.campo_senha = _campo_senha("Senha")
        self.campo_confirmacao = _campo_senha("Digite a senha de novo")
        self.mostrar = QCheckBox("Mostrar a senha")
        self.mostrar.toggled.connect(lambda v: _alternar_visibilidade([self.campo_senha, self.campo_confirmacao], v))
        for campo in (self.campo_senha, self.campo_confirmacao):
            campo.textChanged.connect(lambda *_: self.atualizar_estado())

        painel = QWidget()
        layout = QVBoxLayout(painel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(_rotulo("SENHA PARA ABRIR O PDF"))
        layout.addWidget(self.campo_senha)
        layout.addWidget(self.campo_confirmacao)
        layout.addWidget(self.mostrar)
        layout.addWidget(_ajuda(
            "Guarde a senha em lugar seguro: sem ela não há como abrir o arquivo, nem com o UnePDF. "
            "O PDF original continua sem senha."
        ))
        layout.addStretch()
        return painel

    def preencher_opcoes(self, info: InfoPdf) -> None:
        self.campo_senha.clear()
        self.campo_confirmacao.clear()

    def descrever(self, info: InfoPdf) -> str:
        return plural(info.paginas, "página", "páginas")

    def destino(self) -> Path:
        return destino_derivado(self.origem, "protegido", self.contexto.config.pasta_saida)

    def validar(self) -> str | None:
        senha, confirmacao = self.campo_senha.text(), self.campo_confirmacao.text()
        if not senha:
            return ""
        if len(senha) < TAMANHO_MINIMO_SENHA:
            return f"A senha precisa ter pelo menos {TAMANHO_MINIMO_SENHA} caracteres."
        if not confirmacao:
            return ""
        if senha != confirmacao:
            return "As duas senhas não são iguais."
        return None

    def tarefa(self) -> Tarefa:
        origem, destino, senha = self.origem, self.destino(), self.campo_senha.text()
        return lambda p, c: proteger(origem, destino, senha, p, c)

    def resumo(self, resultado: Resultado) -> str:
        return "A cópia protegida usa criptografia AES de 256 bits e só abre com a senha."


class TelaRemoverSenha(TelaArquivoUnico):
    dica_area = "Gera uma cópia sem senha de um PDF protegido. É preciso saber a senha."
    texto_botao = "Remover senha"
    titulo_progresso = "Removendo a senha..."
    titulo_sucesso = "Senha removida!"
    texto_novo = "Escolher outro PDF"

    def carregar(self, origem: Path) -> SituacaoSenha:
        situacao = situacao_senha(origem)
        if not situacao.protegido:
            raise ErroUnePDF("Este PDF não tem senha.")
        return situacao

    def montar_opcoes(self) -> QWidget:
        self.campo_senha = _campo_senha("Senha")
        self.campo_senha.textChanged.connect(lambda *_: self.atualizar_estado())
        self.mostrar = QCheckBox("Mostrar a senha")
        self.mostrar.toggled.connect(lambda v: _alternar_visibilidade([self.campo_senha], v))
        self.explicacao = _ajuda()

        painel = QWidget()
        layout = QVBoxLayout(painel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(_rotulo("SENHA DO PDF"))
        layout.addWidget(self.campo_senha)
        layout.addWidget(self.mostrar)
        layout.addWidget(self.explicacao)
        layout.addStretch()
        return painel

    def preencher_opcoes(self, info: SituacaoSenha) -> None:
        self.campo_senha.clear()
        if info.pede_senha_para_abrir:
            self.explicacao.setText("Digite a senha usada para abrir o PDF.")
        else:
            self.explicacao.setText(
                "Este PDF abre sem senha, mas tem restrições (de impressão ou cópia, por exemplo). "
                "Para removê-las, digite a senha do proprietário do arquivo."
            )

    def descrever(self, info: SituacaoSenha) -> str:
        return "Protegido por senha" if info.pede_senha_para_abrir else "Com restrições de permissão"

    def destino(self) -> Path:
        return destino_derivado(self.origem, "sem senha", self.contexto.config.pasta_saida)

    def validar(self) -> str | None:
        return "" if not self.campo_senha.text() else None

    def tarefa(self) -> Tarefa:
        origem, destino, senha = self.origem, self.destino(), self.campo_senha.text()
        return lambda p, c: remover_senha(origem, destino, senha, p, c)

    def resumo(self, resultado: Resultado) -> str:
        return f"Cópia sem senha e sem restrições salva, com {plural(resultado.paginas, 'página', 'páginas')}."

    def _ao_falhar_processo(self, erro: BaseException) -> None:
        # Senha errada é o caso mais comum: o aviso aparece ao lado do campo, sem abrir uma janela
        if isinstance(erro, ErroUnePDF):
            self.estados.setCurrentWidget(self.painel_opcoes)
            self.atualizar_estado(str(erro))
            self.campo_senha.selectAll()
            self.campo_senha.setFocus()
        else:
            super()._ao_falhar_processo(erro)
