"""Preferências do usuário, guardadas em %APPDATA%\\UnePDF\\config.json.

O arquivo é tolerante a falhas: se estiver ausente, corrompido ou com valores inválidos,
o app usa os valores padrão (campo a campo) em vez de quebrar.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from unepdf.constantes import PASTA_SAIDA_PADRAO
from unepdf.core.erros import ErroUnePDF
from unepdf.core.gravacao import gravar_com_seguranca
from unepdf.core.localizador import OrdemArquivos
from unepdf.core.nomenclatura import CARACTERES_INVALIDOS, Perfil
from unepdf.utils.caminhos import pasta_configuracoes

log = logging.getLogger(__name__)

NOME_ARQUIVO = "config.json"


@dataclass
class Configuracoes:
    # Caminhos vazios significam "sem preferência": o diálogo abre na pasta padrão do Windows
    pasta_inicial: str = ""
    ultima_pasta: str = ""
    perfil_nomenclatura: Perfil = Perfil.GENERICO
    pasta_saida: str = PASTA_SAIDA_PADRAO
    # Últimas opções usadas em Unir PDFs e Unir em lote
    unir_ordem: OrdemArquivos = OrdemArquivos.NOME
    unir_pular_repetidos: bool = True
    unir_capa: bool = False
    # Opções de XML para PDF, com os nomes dos campos de OpcoesDocumento (texto ou sim/não)
    opcoes_xml: dict = field(default_factory=dict)
    # Opções de Office para PDF
    office_pdfa: bool = False
    office_juntar: bool = False
    ocr_juntar: bool = False


def pasta_saida_valida(nome: str) -> bool:
    """Nome simples de pasta (sem barras nem caracteres proibidos), usado como subpasta de saída."""
    return bool(nome.strip(" .")) and not CARACTERES_INVALIDOS.search(nome)


def caminho_padrao() -> Path:
    return pasta_configuracoes() / NOME_ARQUIVO


def carregar(caminho: Path | None = None) -> Configuracoes:
    """Lê as configurações. Nunca lança exceção: qualquer problema vira valor padrão."""
    caminho = caminho or caminho_padrao()
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return Configuracoes()
    except (OSError, ValueError) as erro:
        log.warning("Configurações ilegíveis em %s, usando os padrões: %s", caminho, erro)
        return Configuracoes()

    if not isinstance(dados, dict):
        log.warning("Configurações em formato inesperado em %s, usando os padrões", caminho)
        return Configuracoes()

    config = Configuracoes()
    for campo in fields(Configuracoes):
        if campo.name in dados:
            valor = _validar(campo.name, dados[campo.name])
            if valor is None:
                log.warning("Valor inválido para '%s' nas configurações, usando o padrão", campo.name)
            else:
                setattr(config, campo.name, valor)
    return config


def _validar(nome: str, valor: object) -> object | None:
    """Valor convertido para o tipo do campo, ou None se for inválido."""
    if nome == "opcoes_xml":
        if not isinstance(valor, dict):
            return None
        return {chave: v for chave, v in valor.items() if isinstance(chave, str) and isinstance(v, (str, bool))}
    if isinstance(getattr(Configuracoes, nome), bool):
        return valor if isinstance(valor, bool) else None
    if not isinstance(valor, str):
        return None
    enumeracoes = {"perfil_nomenclatura": Perfil, "unir_ordem": OrdemArquivos}
    if nome in enumeracoes:
        try:
            return enumeracoes[nome](valor)
        except ValueError:
            return None
    if nome == "pasta_saida":
        return valor.strip() if pasta_saida_valida(valor) else None
    return valor


def salvar(config: Configuracoes, caminho: Path | None = None) -> None:
    """Grava as configurações sem nunca deixar o arquivo pela metade."""
    caminho = caminho or caminho_padrao()
    conteudo = json.dumps(asdict(config), ensure_ascii=False, indent=2).encode("utf-8")
    try:
        gravar_com_seguranca(caminho, lambda arquivo: arquivo.write(conteudo))
    except ErroUnePDF as erro:
        raise ErroUnePDF(f"Não foi possível salvar as configurações.\n\n{erro}") from erro
