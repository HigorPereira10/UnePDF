"""Unir em lote: um PDF unificado para cada pasta que tem PDFs, dentro de uma pasta raiz.

Cada pasta segue as mesmas regras da união comum (só os PDFs direto nela, resultado na sua
própria subpasta de saída). Uma pasta com problema não interrompe as outras: no final o
relatório mostra o que foi gerado e o que deu errado em cada uma.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from unepdf.constantes import PASTA_SAIDA_PADRAO
from unepdf.core.erros import ErroUnePDF, OperacaoCancelada
from unepdf.core.localizador import (
    OrdemArquivos,
    eh_pasta_saida,
    listar_pdfs_da_pasta,
    ordem_natural,
    ordenar,
)
from unepdf.core.modelos import ArquivoIgnorado, Resultado
from unepdf.core.nomenclatura import Perfil, destino_padrao
from unepdf.core.progresso import CallbackProgresso, Cancelamento
from unepdf.core.unir import unir
from unepdf.utils.texto import plural

log = logging.getLogger(__name__)


@dataclass
class PastaLote:
    pasta: Path
    arquivos: list[Path]
    destino: Path


@dataclass
class Varredura:
    raiz: Path
    pastas: list[PastaLote]
    inacessiveis: list[ArquivoIgnorado] = field(default_factory=list)


@dataclass
class ItemLote:
    pasta: Path
    destino: Path
    resultado: Resultado | None = None
    erro: str = ""
    ignorados: list[ArquivoIgnorado] = field(default_factory=list)


@dataclass
class ResultadoLote:
    raiz: Path
    itens: list[ItemLote]
    # Pastas que não chegaram a ser processadas porque o usuário cancelou
    pendentes: list[Path] = field(default_factory=list)

    @property
    def gerados(self) -> list[ItemLote]:
        return [item for item in self.itens if item.resultado]

    @property
    def com_problema(self) -> list[ItemLote]:
        return [item for item in self.itens if not item.resultado]

    @property
    def cancelado(self) -> bool:
        return bool(self.pendentes)


def _oculta(entrada: os.DirEntry) -> bool:
    # Pastas como "$RECYCLE.BIN" e ".git" nunca são de documentos
    if entrada.name.startswith(("$", ".")):
        return True
    # Atalhos de pasta (junções e links) podem apontar para cima e fazer a busca andar em círculos
    return entrada.is_symlink() or getattr(entrada, "is_junction", lambda: False)()


def procurar_pastas(
    raiz: Path,
    perfil: Perfil = Perfil.GENERICO,
    pasta_saida: str = PASTA_SAIDA_PADRAO,
    cancelamento: Cancelamento | None = None,
) -> Varredura:
    """Percorre a raiz e todas as subpastas e devolve as que têm PDFs direto nelas.

    As pastas de saída (e tudo dentro delas) ficam de fora, para nunca unir resultados anteriores.
    """
    if eh_pasta_saida(raiz, pasta_saida):
        raise ErroUnePDF(
            f'A pasta "{raiz.name}" é onde o UnePDF grava os resultados e não pode ser usada como origem.\n\n'
            "Escolha a pasta de cima."
        )
    if not raiz.is_dir():
        raise ErroUnePDF(f"Não foi possível abrir a pasta:\n{raiz}")

    varredura = Varredura(raiz, [])
    pendentes = [raiz]
    while pendentes:
        if cancelamento:
            cancelamento.verificar()
        pasta = pendentes.pop()
        try:
            with os.scandir(pasta) as entradas:
                subpastas = [
                    Path(e.path) for e in entradas
                    if e.is_dir() and not _oculta(e) and not eh_pasta_saida(Path(e.path), pasta_saida)
                ]
            arquivos = listar_pdfs_da_pasta(pasta, pasta_saida)
        except (OSError, ErroUnePDF) as erro:
            if pasta == raiz:
                raise ErroUnePDF(f"Não foi possível abrir a pasta:\n{raiz}") from erro
            log.warning("Pasta ignorada no lote: %s (%s)", pasta, erro)
            varredura.inacessiveis.append(ArquivoIgnorado(pasta, "não foi possível abrir a pasta"))
            continue
        if arquivos:
            varredura.pastas.append(PastaLote(pasta, arquivos, destino_padrao(pasta, perfil, pasta_saida)))
        pendentes.extend(subpastas)

    if not varredura.pastas:
        raise ErroUnePDF(f"Nenhuma pasta com PDFs foi encontrada em:\n{raiz}")
    varredura.pastas.sort(key=lambda p: [ordem_natural(Path(parte)) for parte in p.pasta.relative_to(raiz).parts])
    return varredura


def caminho_relativo(pasta: Path, raiz: Path) -> str:
    """Como a pasta aparece nas listas: relativa à raiz, ou o nome da raiz quando é ela mesma."""
    relativo = pasta.relative_to(raiz)
    return str(relativo) if relativo.parts else raiz.name


def unir_em_lote(
    raiz: Path,
    pastas: list[PastaLote],
    ordem: OrdemArquivos = OrdemArquivos.NOME,
    pular_repetidos: bool = False,
    capa: bool = False,
    progresso: CallbackProgresso | None = None,
    cancelamento: Cancelamento | None = None,
) -> ResultadoLote:
    """Gera um unificado por pasta. Ao cancelar, as pastas já concluídas ficam prontas e as
    restantes aparecem como pendentes no resultado."""
    resultado = ResultadoLote(raiz, [])
    # Cada pasta conta um passo por arquivo e um de gravação, como na união comum
    total = sum(len(p.arquivos) + 1 for p in pastas)
    feitos = 0

    for posicao, pasta in enumerate(pastas):
        nome = caminho_relativo(pasta.pasta, raiz)

        def progresso_da_pasta(atual: int, _total: int, descricao: str, inicio: int = feitos, nome: str = nome):
            if progresso:
                progresso(inicio + atual, total, f"{nome}: {descricao}")

        item = ItemLote(pasta.pasta, pasta.destino)
        try:
            arquivos = ordenar(pasta.arquivos, ordem)
            item.resultado = unir(
                arquivos, pasta.destino, progresso_da_pasta, cancelamento,
                pular_repetidos=pular_repetidos, capa=capa,
            )
            item.ignorados = item.resultado.ignorados
        except OperacaoCancelada:
            resultado.pendentes = [p.pasta for p in pastas[posicao:]]
            break
        except ErroUnePDF as erro:
            item.erro, item.ignorados = erro.mensagem, erro.ignorados
        except Exception:
            log.exception("Falha inesperada ao unir a pasta %s", pasta.pasta)
            item.erro = "Falha inesperada. Os detalhes ficaram no registro de atividades."
        resultado.itens.append(item)
        feitos += len(pasta.arquivos) + 1

    log.info(
        "Lote em %s: %d gerados, %d com problema, %d pendentes",
        raiz, len(resultado.gerados), len(resultado.com_problema), len(resultado.pendentes),
    )
    return resultado


def texto_relatorio(resultado: ResultadoLote, quando: datetime | None = None) -> str:
    """Relatório em texto simples, para guardar ou enviar junto com os arquivos."""
    quando = quando or datetime.now()
    linhas = [
        "Relatório do Unir em lote (UnePDF)",
        f"Pasta: {resultado.raiz}",
        f"Data: {quando:%d/%m/%Y %H:%M}",
        "",
        resumo_lote(resultado),
        "",
    ]
    for item in resultado.itens:
        nome = caminho_relativo(item.pasta, resultado.raiz)
        if item.resultado:
            r = item.resultado
            linhas.append(f"[OK] {nome}")
            linhas.append(
                f"     {plural(r.arquivos, 'arquivo', 'arquivos')}, {plural(r.paginas, 'página', 'páginas')}: {r.destino}"
            )
        else:
            linhas.append(f"[PROBLEMA] {nome}")
            linhas.extend(f"     {parte}" for parte in item.erro.splitlines() if parte.strip())
        for ignorado in item.ignorados:
            linhas.append(f"     Não entrou: {ignorado.caminho.name} ({ignorado.motivo})")
    for pasta in resultado.pendentes:
        linhas.append(f"[NÃO PROCESSADA] {caminho_relativo(pasta, resultado.raiz)}")
    return "\n".join(linhas) + "\n"


def resumo_lote(resultado: ResultadoLote) -> str:
    partes = [plural(len(resultado.gerados), "unificado gerado", "unificados gerados")]
    if resultado.com_problema:
        partes.append(plural(len(resultado.com_problema), "pasta com problema", "pastas com problema"))
    if resultado.pendentes:
        partes.append(plural(len(resultado.pendentes), "pasta não processada", "pastas não processadas"))
    ignorados = sum(len(item.ignorados) for item in resultado.gerados)
    if ignorados:
        partes.append(plural(ignorados, "arquivo não entrou", "arquivos não entraram"))
    return ", ".join(partes) + "."
