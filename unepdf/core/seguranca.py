"""Proteção de PDFs com senha (AES-256) e remoção de senha.

A remoção exige sempre a senha correta: o app não quebra senha de ninguém. PDFs que abrem sem
senha, mas têm restrições de permissão (impressão, cópia), só são liberados com a senha do
proprietário.
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

from pypdf import PasswordType, PdfReader, PdfWriter

from unepdf.core.erros import ErroUnePDF
from unepdf.core.gravacao import gravar_com_seguranca
from unepdf.core.leitor_pdf import abrir_pdf_ou_erro
from unepdf.core.modelos import Resultado
from unepdf.core.progresso import CallbackProgresso, Cancelamento

TAMANHO_MINIMO_SENHA = 4


@dataclass(frozen=True)
class SituacaoSenha:
    protegido: bool  # tem algum tipo de criptografia
    pede_senha_para_abrir: bool  # False quando só há restrições de permissão
    paginas: int | None  # só conhecido quando o PDF abre sem senha


def situacao_senha(origem: Path) -> SituacaoSenha:
    """Descobre que tipo de senha o PDF tem, sem precisar dela."""
    leitor = _ler(origem)
    if not leitor.is_encrypted:
        return SituacaoSenha(False, False, len(leitor.pages))
    if leitor.decrypt("") != PasswordType.NOT_DECRYPTED:
        return SituacaoSenha(True, False, len(leitor.pages))
    return SituacaoSenha(True, True, None)


def _ler(origem: Path) -> PdfReader:
    try:
        dados = origem.read_bytes()
    except OSError as erro:
        raise ErroUnePDF(f'Não foi possível ler o arquivo "{origem.name}": {erro.strerror or erro}.') from erro
    if not dados:
        raise ErroUnePDF(f'O arquivo "{origem.name}" está vazio (0 KB).')
    try:
        return PdfReader(io.BytesIO(dados))
    except Exception as erro:
        raise ErroUnePDF(f'O arquivo "{origem.name}" está corrompido ou não é um PDF.') from erro


def proteger(
    origem: Path,
    destino: Path,
    senha: str,
    progresso: CallbackProgresso | None = None,
    cancelamento: Cancelamento | None = None,
) -> Resultado:
    """Grava uma cópia que só abre com a senha, mantendo marcadores, links e formulários."""
    if len(senha) < TAMANHO_MINIMO_SENHA:
        raise ErroUnePDF(f"A senha precisa ter pelo menos {TAMANHO_MINIMO_SENHA} caracteres.")
    leitor = abrir_pdf_ou_erro(origem)
    if cancelamento:
        cancelamento.verificar()
    if progresso:
        progresso(1, 1, f"Gravando {destino.name}")
    escritor = PdfWriter(clone_from=leitor)
    escritor.encrypt(user_password=senha, algorithm="AES-256")
    substituiu = gravar_com_seguranca(destino, escritor.write)
    return Resultado(destino, 1, len(leitor.pages), substituiu)


def remover_senha(
    origem: Path,
    destino: Path,
    senha: str,
    progresso: CallbackProgresso | None = None,
    cancelamento: Cancelamento | None = None,
) -> Resultado:
    """Grava uma cópia sem senha e sem restrições. Exige a senha de abertura ou a do proprietário."""
    leitor = _ler(origem)
    if not leitor.is_encrypted:
        raise ErroUnePDF("Este PDF não tem senha.")

    tipo = leitor.decrypt(senha)
    if tipo == PasswordType.NOT_DECRYPTED:
        raise ErroUnePDF("Senha incorreta.")
    if not senha and tipo == PasswordType.USER_PASSWORD:
        # Abriu com a senha em branco: só há restrições de permissão, que pertencem ao proprietário
        raise ErroUnePDF(
            "Este PDF abre sem senha, mas tem restrições (de impressão ou cópia, por exemplo).\n\n"
            "Para remover as restrições, digite a senha do proprietário do arquivo."
        )

    if cancelamento:
        cancelamento.verificar()
    if progresso:
        progresso(1, 1, f"Gravando {destino.name}")
    try:
        escritor = PdfWriter(clone_from=leitor)
    except Exception as erro:
        raise ErroUnePDF(f'O arquivo "{origem.name}" está corrompido.') from erro
    substituiu = gravar_com_seguranca(destino, escritor.write)
    return Resultado(destino, 1, len(escritor.pages), substituiu)
