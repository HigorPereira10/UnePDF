"""Separar notas emitidas e recebidas: cada nota da pasta vai para a subpasta do seu lado.

A empresa dona da pasta é descoberta pelas próprias notas: é o único CNPJ (ou CPF) presente em
todas, ora como emitente, ora como destinatário ou tomador. Quem emitiu cada nota vem da chave de
acesso, que traz o CNPJ do emitente e fica no nome do arquivo, no texto do PDF ou no XML.

A mesma nota salva mais de uma vez não é separada duas vezes: a cópia idêntica é apagada e a
versão diferente vai para a pasta de repetidas. Cada separação fica registrada e pode ser desfeita.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from unepdf.constantes import PASTA_SAIDA_PADRAO
from unepdf.core.erros import ErroUnePDF
from unepdf.core.gravacao import gravar_com_seguranca
from unepdf.core.localizador import PDF, XML, eh_do_tipo, eh_pasta_saida, ordem_natural
from unepdf.core.modelos import ArquivoIgnorado
from unepdf.core.nomenclatura import PADRAO_COMPETENCIA, TIPOS_DOCUMENTO
from unepdf.core.progresso import CallbackProgresso, Cancelamento
from unepdf.core.renderizacao import DocumentoRenderizavel
from unepdf.core.xml_fiscal import DocumentoFiscal, TipoDocumento, XmlNaoReconhecido, ler_xml
from unepdf.utils.caminhos import pasta_separacoes

log = logging.getLogger(__name__)

# Fica dentro da pasta de saída, para o Unir nunca juntar as repetidas com as notas
PASTA_REPETIDAS = "Repetidas"
PAGINAS_LIDAS = 3  # a chave fica no topo da primeira página; as outras só são lidas se ela não aparecer
# Parte das notas em que a empresa precisa aparecer para ser reconhecida sem perguntar
PROPORCAO_MINIMA = 0.8
LIMITE_VIZINHAS = 30  # notas de outros meses lidas para desempatar
LIMITE_TEXTO = 20_000  # caracteres do PDF guardados para desempatar pelo nome
LIMITE_CONFERENCIA = 200  # notas usadas para conferir o nome da pasta (bastam para uma maioria clara)
# Palavras que não ajudam a reconhecer o nome de uma empresa
PALAVRAS_GENERICAS = frozenset({
    "LTDA", "ME", "EPP", "EIRELI", "SA", "S", "A", "CIA", "DE", "DA", "DO", "DAS", "DOS", "E", "EM", "LIMITADA",
})

# Como a empresa da pasta foi descoberta (mostrado ao usuário na prévia)
COMO_NOTAS = "pelas notas"
COMO_CNPJ_NA_PASTA = "pelo CNPJ no nome da pasta"
COMO_GUARDADA = "pela resposta guardada"
COMO_VIZINHAS = "pelos outros meses da empresa"
COMO_USUARIO = "escolhida por você"

UFS = frozenset({
    11, 12, 13, 14, 15, 16, 17, 21, 22, 23, 24, 25, 26, 27, 28, 29,
    31, 32, 33, 35, 41, 42, 43, 50, 51, 52, 53,
})
MODELO_NFSE = "NFS"
TIPO_POR_MODELO = {
    "55": TipoDocumento.DANFE, "65": TipoDocumento.DANFCE, "57": TipoDocumento.DACTE,
    "67": TipoDocumento.DACTE, "58": TipoDocumento.DAMDFE, MODELO_NFSE: TipoDocumento.DANFSE,
}
# O texto pode ter várias chaves (o DACTE traz a da NF-e transportada): a do próprio documento
# é a de menor número
PRIORIDADE_MODELO = {"58": 0, MODELO_NFSE: 0, "57": 1, "67": 1, "55": 2, "65": 2}


class Lado(StrEnum):
    EMITIDAS = "emitidas"
    RECEBIDAS = "recebidas"


# Nomes das subpastas por tipo de documento; o usuário pode trocar nas configurações
PASTAS_PADRAO: dict[str, tuple[str, str]] = {
    "DANFE": ("EMITIDAS", "RECEBIDAS"),
    "DANFCE": ("EMITIDAS", "RECEBIDAS"),
    "DANFSE": ("PRESTADAS", "TOMADAS"),
    "DACTE": ("EMITIDOS", "RECEBIDOS"),
    "OUTROS": ("EMITIDAS", "RECEBIDAS"),
}


def nomes_das_pastas(tipo: str, personalizados: dict | None = None) -> dict[Lado, str]:
    chave = tipo if tipo in PASTAS_PADRAO else "OUTROS"
    emitidas, recebidas = PASTAS_PADRAO[chave]
    escolhidos = (personalizados or {}).get(chave) or {}
    return {
        Lado.EMITIDAS: escolhidos.get(Lado.EMITIDAS.value) or emitidas,
        Lado.RECEBIDAS: escolhidos.get(Lado.RECEBIDAS.value) or recebidas,
    }


def todas_as_pastas(personalizados: dict | None = None) -> set[str]:
    """Nomes de todas as subpastas de separação, para não separar de novo dentro de uma delas."""
    return {nome.casefold() for tipo in PASTAS_PADRAO for nome in nomes_das_pastas(tipo, personalizados).values()}


# Documentos: CNPJ (inclusive o alfanumérico), CPF e chave de acesso

def _digito(texto: str) -> int:
    """Dígito módulo 11 com pesos de 2 a 9, usado na chave de acesso e no CNPJ.

    No CNPJ alfanumérico cada letra vale o código ASCII menos 48, a mesma conta que dá o valor dos dígitos.
    """
    soma, peso = 0, 2
    for caractere in reversed(texto):
        soma += (ord(caractere) - 48) * peso
        peso = 2 if peso == 9 else peso + 1
    resto = soma % 11
    return 0 if resto < 2 else 11 - resto


def cnpj_valido(cnpj: str) -> bool:
    if not re.fullmatch(r"[0-9A-Z]{12}\d{2}", cnpj) or len(set(cnpj)) == 1:
        return False
    return _digito(cnpj[:12]) == int(cnpj[12]) and _digito(cnpj[:13]) == int(cnpj[13])


def cpf_valido(cpf: str) -> bool:
    if len(cpf) != 11 or not cpf.isdecimal() or len(set(cpf)) == 1:
        return False
    for posicao in (9, 10):
        soma = sum(int(cpf[i]) * (posicao + 1 - i) for i in range(posicao))
        if soma * 10 % 11 % 10 != int(cpf[posicao]):
            return False
    return True


def formatar_documento(documento: str) -> str:
    """Ex.: "11222333000181" -> "11.222.333/0001-81"; CPF -> "123.456.789-09"."""
    d = documento
    if len(d) == 14:
        return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"
    if len(d) == 11:
        return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"
    return d


@dataclass(frozen=True)
class Chave:
    numero: str
    modelo: str  # "55", "65", "57", "67", "58" ou "NFS"
    emitente: str  # CNPJ, ou CPF quando quem emitiu é pessoa física


def _inscricao(texto: str, tipo: str = "") -> str:
    """CNPJ ou CPF de 14 posições na chave. O CPF vem com três zeros à esquerda."""
    if tipo != "1" and cnpj_valido(texto):
        return texto
    if tipo != "2" and texto.startswith("000") and cpf_valido(texto[3:]):
        return texto[3:]
    return ""


def ler_chave(texto: str) -> Chave | None:
    """A chave de acesso (NF-e, NFC-e, CT-e, MDF-e ou NFS-e nacional), se o texto for uma válida."""
    if len(texto) == 44 and texto[:6].isdecimal() and texto[20:].isdecimal():
        modelo = texto[20:22]
        if int(texto[:2]) not in UFS or not 1 <= int(texto[4:6]) <= 12 or modelo not in PRIORIDADE_MODELO:
            return None
        emitente = _inscricao(texto[6:20])
    elif len(texto) == 50 and texto[:9].isdecimal() and texto[23:].isdecimal():
        # Município (7), ambiente, tipo de inscrição (1 CPF, 2 CNPJ), inscrição (14), número (13),
        # ano e mês, código e dígito
        modelo = MODELO_NFSE
        if int(texto[:2]) not in UFS or texto[7] not in "12" or texto[8] not in "12":
            return None
        if not 1 <= int(texto[38:40]) <= 12:
            return None
        emitente = _inscricao(texto[9:23], texto[8])
    else:
        return None
    if not emitente or _digito(texto[:-1]) != int(texto[-1]):
        return None
    return Chave(texto, modelo, emitente)


# A chave aparece corrida, em grupos de 4 ou com pontos e traços, às vezes grudada em outros números
_TRECHO = re.compile(r"[0-9A-Z](?:[ .\-/]?[0-9A-Z]){43,}")
_CNPJ_FORMATADO = re.compile(r"(?<![\d.])([0-9A-Z]{2})\.([0-9A-Z]{3})\.([0-9A-Z]{3})/([0-9A-Z]{4})-(\d{2})(?!\d)")
_CPF_FORMATADO = re.compile(r"(?<![\d.])(\d{3})\.(\d{3})\.(\d{3})-(\d{2})(?!\d)")


def chaves_no_texto(texto: str) -> list[Chave]:
    """Chaves de acesso válidas no texto, na ordem em que aparecem."""
    encontradas: dict[str, Chave] = {}
    for trecho in _TRECHO.finditer(texto.upper()):
        corrido = re.sub(r"[^0-9A-Z]", "", trecho.group())
        for inicio in range(len(corrido) - 43):
            for tamanho in (44, 50):
                chave = ler_chave(corrido[inicio:inicio + tamanho])
                if chave:
                    encontradas.setdefault(chave.numero, chave)
    return list(encontradas.values())


def chave_principal(chaves: list[Chave]) -> Chave | None:
    return min(chaves, key=lambda chave: PRIORIDADE_MODELO[chave.modelo], default=None)


def documentos_no_texto(texto: str) -> set[str]:
    """CNPJs e CPFs formatados (com pontos e traço) que existem de verdade, pelo dígito verificador."""
    encontrados = set()
    for padrao, valido in ((_CNPJ_FORMATADO, cnpj_valido), (_CPF_FORMATADO, cpf_valido)):
        for achado in padrao.finditer(texto.upper()):
            documento = "".join(achado.groups())
            if valido(documento):
                encontrados.add(documento)
    return encontrados


# Leitura das notas

@dataclass
class Nota:
    caminho: Path
    tamanho: int
    resumo: str  # sha256 do conteúdo, para achar cópias idênticas; vazio quando não deu para ler
    chave: Chave | None = None
    participantes: frozenset[str] = frozenset()  # CNPJ ou CPF de todos os envolvidos, emitente incluído
    evento: bool = False  # cancelamento ou carta de correção: acompanha a nota, mas não diz quem é a empresa
    motivo: str = ""  # por que a nota não pôde ser identificada por completo
    texto: str = field(default="", repr=False)  # texto do PDF, para mostrar ao usuário quem é cada CNPJ
    # O documento que fica junto do nome da empresa da pasta na página, e a linha onde o nome aparece
    perto_do_nome: str = ""
    linha_do_nome: str = ""

    @property
    def emitente(self) -> str:
        return self.chave.emitente if self.chave else ""

    @property
    def chave_no_nome(self) -> bool:
        return bool(self.chave) and self.chave.numero in self.caminho.name.upper()

    @property
    def identidade(self) -> tuple[str, str] | None:
        """A mesma nota em dois arquivos do mesmo formato (PDF ou XML) tem a mesma identidade."""
        if self.evento or not self.chave:
            return None
        return self.chave.numero, self.caminho.suffix.lower()


def _ler_pdf(nota: Nota, dados: bytes, nome: list[str]) -> None:
    chave = chave_principal(chaves_no_texto(nota.caminho.stem))
    try:
        with DocumentoRenderizavel(dados) as documento:
            texto, caixas = documento.texto_com_posicoes(0) if documento.total else ("", None)
            primeira = texto
            do_texto = chaves_no_texto(texto)
            if not chave and not do_texto:
                for indice in range(1, min(documento.total, PAGINAS_LIDAS)):
                    texto += "\n" + documento.extrair_texto(indice)
                do_texto = chaves_no_texto(texto)
    except Exception:
        log.debug("PDF ilegível ao separar: %s", nota.caminho, exc_info=True)
        nota.chave, nota.motivo = chave, "PDF corrompido ou protegido por senha"
        nota.participantes = frozenset({chave.emitente} if chave else ())
        return

    nota.chave = chave or chave_principal(do_texto)
    participantes = documentos_no_texto(texto)
    if nota.chave:
        participantes.add(nota.chave.emitente)
    nota.participantes = frozenset(participantes)
    if not texto.strip():
        nota.motivo = "PDF sem texto (escaneado)"
    elif not nota.chave:
        nota.motivo = "a chave de acesso não foi encontrada no PDF"
    nota.texto = texto[:LIMITE_TEXTO]
    if nome:
        nota.perto_do_nome, nota.linha_do_nome = _junto_do_nome(primeira, caixas, nome)


def _ler_xml(caminho: Path, dados: bytes) -> tuple[Chave | None, frozenset[str], bool, str]:
    try:
        lido = ler_xml(caminho)
    except XmlNaoReconhecido as erro:
        # Eventos e resumos de outros formatos ainda citam a chave da nota e vão para o lado dela
        chave = chave_principal(chaves_no_texto(dados.decode("utf-8", "replace")))
        return chave, frozenset(), True, "" if chave else str(erro)
    chave = ler_chave(lido.chave)
    if isinstance(lido, DocumentoFiscal) and lido.tipo is not TipoDocumento.DACCE:
        participantes = set(lido.participantes) | ({chave.emitente} if chave else set())
        return chave, frozenset(participantes), False, "" if chave else "XML sem chave de acesso válida"
    return chave, frozenset(), True, "" if chave else "evento sem chave de acesso válida"


def ler_nota(caminho: Path, nome: list[str] | None = None) -> Nota:
    """Lê o arquivo inteiro para a memória (nada fica aberto na rede) e identifica a nota.

    `nome` são as palavras do nome da empresa da pasta, procuradas na página para saber de qual CNPJ ele fica junto.
    """
    try:
        dados = caminho.read_bytes()
    except OSError as erro:
        return Nota(caminho, 0, "", motivo=f"não foi possível ler o arquivo ({erro.strerror or erro})")
    if not dados:
        return Nota(caminho, 0, "", motivo="arquivo vazio (0 KB)")
    nota = Nota(caminho, len(dados), hashlib.sha256(dados).hexdigest())
    if eh_do_tipo(caminho, XML):
        nota.chave, nota.participantes, nota.evento, nota.motivo = _ler_xml(caminho, dados)
    else:
        _ler_pdf(nota, dados, nome or [])
    return nota


# Descoberta da empresa da pasta

@dataclass
class LeituraPasta:
    pasta: Path
    notas: list[Nota] = field(default_factory=list)
    tipo: str = ""  # tipo de documento da pasta (DANFE, DANFSE...), vazio quando não deu para saber
    candidatos: list[tuple[str, int]] = field(default_factory=list)  # documento e em quantas notas aparece
    com_participantes: int = 0  # notas que dizem quem participa (a base da contagem)
    empresa: str = ""  # vazio quando é preciso perguntar ao usuário
    como: str = ""  # como a empresa foi descoberta, para o usuário conferir
    erro: str = ""  # a pasta não pôde ser lida
    # Conferência pelo nome da pasta: o documento que aparece junto dele nas notas e a linha da nota com o nome
    documento_do_nome: str = ""
    nome_na_nota: str = ""

    @property
    def conferir_empresa(self) -> bool:
        """O nome da pasta aparece junto de outro documento, não do escolhido."""
        return bool(self.empresa and self.documento_do_nome and self.documento_do_nome != self.empresa)

    @property
    def guardar_empresa(self) -> bool:
        """A empresa foi descoberta com segurança e pode valer para as pastas de outros tipos."""
        return bool(self.empresa) and self.como in (COMO_NOTAS, COMO_VIZINHAS, COMO_CNPJ_NA_PASTA, COMO_USUARIO)


def pasta_da_empresa(pasta: Path) -> Path:
    """A pasta do mês (MMAAAA) fica dentro da pasta da empresa; fora desse padrão, é a própria pasta."""
    return pasta.parent if PADRAO_COMPETENCIA.match(pasta.name) else pasta


def chave_empresa(pasta: Path) -> str:
    """Identifica a empresa nas respostas guardadas: o nome da pasta dela, sem diferenciar maiúsculas.

    É o nome e não o caminho para a resposta valer também nas pastas de outros tipos de documento
    (...\\DANFE\\0001-EMPRESA e ...\\DACTE\\0001-EMPRESA).
    """
    return pasta_da_empresa(pasta).name.casefold()


def _documento_no_nome(pasta: Path) -> str:
    """CNPJ ou CPF no nome da pasta da empresa (ex.: "0-11222333000181")."""
    for nome in dict.fromkeys((pasta.name, pasta_da_empresa(pasta).name)):
        for numero in re.findall(r"(?<!\d)(\d{14}|\d{11})(?!\d)", nome):
            if cnpj_valido(numero) or cpf_valido(numero):
                return numero
    return ""


def _tipo_da_pasta(pasta: Path, notas: list[Nota]) -> str:
    for parte in reversed(pasta.parts):
        if parte.upper() in TIPOS_DOCUMENTO:
            return parte.upper()
    tipos = Counter(TIPO_POR_MODELO[nota.chave.modelo].value for nota in notas if nota.chave)
    return tipos.most_common(1)[0][0] if tipos else ""


def _votos(notas: list[Nota]) -> tuple[list[tuple[str, int]], int]:
    # A mesma nota salva duas vezes conta uma vez só
    unicas = {nota.identidade or nota.resumo or id(nota): nota for nota in notas}.values()
    validas = [nota for nota in unicas if not nota.evento and len(nota.participantes) >= 2]
    votos = Counter(documento for nota in validas for documento in nota.participantes)
    return sorted(votos.items(), key=lambda item: (-item[1], item[0])), len(validas)


def _mais_votados(candidatos: list[tuple[str, int]]) -> list[str]:
    return [documento for documento, votos in candidatos if votos == candidatos[0][1]] if candidatos else []


def _listar_notas(pasta: Path) -> list[Path]:
    return sorted((p for p in pasta.iterdir() if eh_do_tipo(p, PDF) or eh_do_tipo(p, XML)), key=ordem_natural)


def _desempatar(
    pasta: Path, empatados: list[str], pasta_saida: str, cancelamento: Cancelamento | None
) -> str:
    """Desempata com outros meses da mesma empresa: ela aparece em todos, o parceiro do mês não.

    Só vale para a pasta de um mês (MMAAAA): fora disso, as pastas vizinhas são de outras empresas.
    """
    if not PADRAO_COMPETENCIA.match(pasta.name):
        return ""
    vizinhas: list[Nota] = []
    lidos = 0
    try:
        meses = sorted(
            (p for p in pasta.parent.iterdir() if p.is_dir() and p != pasta and PADRAO_COMPETENCIA.match(p.name)),
            key=ordem_natural, reverse=True,
        )
        for mes in meses:
            # As notas de meses já separados estão nas subpastas
            locais = [mes, *(p for p in mes.iterdir() if p.is_dir() and not eh_pasta_saida(p, pasta_saida))]
            for local in locais:
                for arquivo in _listar_notas(local):
                    if len(vizinhas) >= LIMITE_VIZINHAS or lidos >= LIMITE_VIZINHAS * 2:
                        break
                    if cancelamento:
                        cancelamento.verificar()
                    lidos += 1
                    nota = ler_nota(arquivo)
                    if not nota.evento and len(nota.participantes) >= 2:
                        vizinhas.append(nota)
    except OSError:
        log.debug("Pastas vizinhas ilegíveis ao desempatar: %s", pasta, exc_info=True)

    votos = Counter(d for nota in vizinhas for d in nota.participantes if d in empatados).most_common()
    if not votos or (len(votos) > 1 and votos[0][1] == votos[1][1]):
        return ""
    return votos[0][0] if votos[0][1] >= PROPORCAO_MINIMA * len(vizinhas) else ""


def _sem_acentos(texto: str) -> str:
    """Maiúsculas sem acento, com o mesmo tamanho do texto original (as posições continuam valendo)."""
    return "".join((unicodedata.normalize("NFKD", c)[:1] or " ").upper()[:1] for c in texto)


def _palavras(texto: str) -> list[tuple[str, int]]:
    return [
        (achado.group(), achado.start()) for achado in re.finditer(r"[A-Z0-9]+", texto)
        if achado.group() not in PALAVRAS_GENERICAS
    ]


def _nome_da_pasta(pasta: Path) -> list[str]:
    """Palavras que identificam a empresa no nome da pasta, sem o código do início e sem LTDA, ME etc."""
    nome = re.sub(r"^\s*\d+\s*-\s*", "", pasta_da_empresa(pasta).name)
    palavras = list(dict.fromkeys(palavra for palavra, _ in _palavras(_sem_acentos(nome)) if not palavra.isdecimal()))
    return palavras[:6] if len(palavras) >= 2 or (palavras and len(palavras[0]) >= 4) else []


def _ocorrencias_do_nome(texto: str, nome: list[str]) -> list[tuple[int, int, str]]:
    """Trechos (início, fim, linha) das linhas do texto que têm a maior parte das palavras do nome.

    Não exige o nome exato: "COMERCIO EXEMPLO CENTRO LTDA" na nota vale para a pasta "COMERCIO EXEMPLO
    FILIAL CENTRO" (nomes de quatro palavras ou mais precisam de três quartos delas).
    """
    # Nomes curtos precisam de todas as palavras: com duas de três, um endereço como "RODOVIA EXEMPLO,
    # CENTRO" já bateria com a pasta "ALFA CENTRO EXEMPLO"
    minimo = len(nome) if len(nome) <= 3 else -(-len(nome) * 3 // 4)
    ocorrencias = []
    for linha in re.finditer(r"[^\r\n]+", texto):
        achadas = [
            (linha.start() + achado.start(), linha.start() + achado.end())
            for achado in re.finditer(r"[A-Z0-9]+", _sem_acentos(linha.group())) if achado.group() in nome
        ]
        palavras = {_sem_acentos(texto[inicio:fim]) for inicio, fim in achadas}
        if len(palavras) >= minimo:
            # O menor trecho com todas as palavras achadas: uma delas pode se repetir em outra coluna da linha
            inicio, fim = min(
                ((achadas[i][0], achadas[j][1]) for i in range(len(achadas)) for j in range(i, len(achadas))
                 if len({_sem_acentos(texto[a:b]) for a, b in achadas[i:j + 1]}) == len(palavras)),
                key=lambda trecho: trecho[1] - trecho[0],
            )
            # O nome mostrado ao usuário inclui o LTDA, ME etc. logo depois (a linha pode ter outra coluna)
            fim_nome = fim
            for seguinte in re.finditer(r"\S+", texto[fim:linha.end()]):
                if re.sub(r"\W", "", _sem_acentos(seguinte.group())) not in PALAVRAS_GENERICAS:
                    break
                fim_nome = fim + seguinte.end()
            ocorrencias.append((inicio, fim, " ".join(texto[inicio:fim_nome].split())[:80]))
    return ocorrencias


def _distancia_na_pagina(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    """Vão entre as duas caixas, com o vão vertical valendo o dobro (um bloco acima é de outro participante)."""
    horizontal = max(0.0, b[0] - a[2], a[0] - b[2])
    vertical = max(0.0, b[1] - a[3], a[1] - b[3])
    return math.hypot(horizontal, 2 * vertical)


def _junto_do_nome(texto: str, caixas: list | None, nome: list[str]) -> tuple[str, str]:
    """O CNPJ ou CPF que fica junto do nome da empresa na página, e a linha onde o nome aparece.

    Primeiro mede na página: no DACTE, remetente e destinatário ficam em colunas lado a lado, e no texto
    o CNPJ de um vem logo depois do nome do outro. Quando a página não decide (no DANFE o nome e o CNPJ
    ficam na mesma linha, em caixas separadas), vale a distância no texto. Só decide com folga clara.
    """
    ocorrencias = _ocorrencias_do_nome(texto, nome)
    if not ocorrencias:
        return "", ""
    normalizado = _sem_acentos(texto)  # mesmo tamanho do texto: as posições batem com as caixas das letras
    documentos: list[tuple[str, int, int]] = []
    for padrao, valido in ((_CNPJ_FORMATADO, cnpj_valido), (_CPF_FORMATADO, cpf_valido)):
        for achado in padrao.finditer(normalizado):
            documento = "".join(achado.groups())
            if valido(documento):
                documentos.append((documento, achado.start(), achado.end()))
    if not documentos:
        return "", ocorrencias[0][2]

    def caixa(inicio: int, fim: int) -> tuple[float, float, float, float] | None:
        partes = [c for c in caixas[inicio:fim] if c and c[2] > c[0]] if caixas else []
        if not partes:
            return None
        return min(c[0] for c in partes), min(c[1] for c in partes), max(c[2] for c in partes), max(c[3] for c in partes)

    def na_pagina(a: tuple[int, int], b: tuple[int, int]) -> float | None:
        caixa_a, caixa_b = caixa(*a), caixa(*b)
        return None if caixa_a is None or caixa_b is None else _distancia_na_pagina(caixa_a, caixa_b)

    def no_texto(a: tuple[int, int], b: tuple[int, int]) -> float:
        return abs(a[0] - b[0])

    def escolher(medida) -> tuple[str, str]:
        melhores: dict[str, tuple[float, str]] = {}
        for documento, inicio, fim in documentos:
            for nome_inicio, nome_fim, linha in ocorrencias:
                valor = medida((nome_inicio, nome_fim), (inicio, fim))
                if valor is None:
                    return "", ""
                if documento not in melhores or valor < melhores[documento][0]:
                    melhores[documento] = (valor, linha)
        ordenados = sorted(melhores.items(), key=lambda item: item[1][0])
        if len(ordenados) > 1 and ordenados[0][1][0] * 1.5 >= ordenados[1][1][0]:
            return "", ordenados[0][1][1]
        return ordenados[0][0], ordenados[0][1][1]

    if caixas:
        documento, linha = escolher(na_pagina)
        if documento:
            return documento, linha
    documento, linha = escolher(no_texto)
    return documento, linha or ocorrencias[0][2]


def _votos_do_nome(leitura: LeituraPasta, entre: set[str] | None = None) -> tuple[str, str]:
    """O documento junto do nome da pasta em quase todas as notas em que o nome aparece, e a linha dele."""
    notas = [nota for nota in leitura.notas if nota.perto_do_nome and not nota.evento]
    if entre is not None:
        notas = [nota for nota in notas if nota.perto_do_nome in entre]
    votos = Counter(nota.perto_do_nome for nota in notas).most_common()
    if not votos or (len(votos) > 1 and votos[0][1] == votos[1][1]):
        return "", ""
    documento, quantidade = votos[0]
    if quantidade < PROPORCAO_MINIMA * sum(1 for nota in leitura.notas if nota.perto_do_nome):
        return "", ""
    return documento, next(nota.linha_do_nome for nota in notas if nota.perto_do_nome == documento)


def conferir_nome(leitura: LeituraPasta) -> tuple[str, str]:
    """O documento que aparece junto do nome da pasta em quase todas as notas, e a linha da nota com o nome.

    Serve para o usuário confirmar a empresa de relance e para avisar quando o nome aponta para outro CNPJ.
    Devolve vazio quando o nome não aparece nas notas ou não aponta claramente para ninguém.
    """
    return _votos_do_nome(leitura)


def sugestao_pelo_nome(leitura: LeituraPasta) -> str:
    """Entre os mais votados, o que fica junto do nome da empresa em quase todas as notas.

    Só sugere: a pergunta ao usuário já vem com ele marcado.
    """
    return _votos_do_nome(leitura, set(_mais_votados(leitura.candidatos)))[0]


def _escolher_empresa(
    leitura: LeituraPasta, conhecida: str, pasta_saida: str, cancelamento: Cancelamento | None
) -> tuple[str, str]:
    """A empresa da pasta e como ela foi descoberta, ou ("", "") quando é preciso perguntar."""
    votos = dict(leitura.candidatos)
    no_nome = _documento_no_nome(leitura.pasta)
    if no_nome and (votos.get(no_nome) or not leitura.com_participantes):
        return no_nome, COMO_CNPJ_NA_PASTA
    # A resposta guardada é pelo nome da pasta: só vale se o documento aparece nestas notas
    if conhecida and votos.get(conhecida):
        return conhecida, COMO_GUARDADA
    mais_votados = _mais_votados(leitura.candidatos)
    if len(mais_votados) == 1:
        if leitura.candidatos[0][1] >= PROPORCAO_MINIMA * leitura.com_participantes:
            return mais_votados[0], COMO_NOTAS
        return "", ""
    if mais_votados:
        empresa = _desempatar(leitura.pasta, mais_votados, pasta_saida, cancelamento)
        if empresa:
            return empresa, COMO_VIZINHAS
    # O nome da pasta não decide sozinho (um erro inverteria a pasta inteira): vira a sugestão da pergunta
    return "", ""


def ler_pastas(
    pastas: list[Path],
    empresas_conhecidas: dict[str, str] | None = None,
    pasta_saida: str = PASTA_SAIDA_PADRAO,
    pastas_de_separacao: set[str] | None = None,
    progresso: CallbackProgresso | None = None,
    cancelamento: Cancelamento | None = None,
) -> list[LeituraPasta]:
    """Lê as notas de cada pasta (só as que estão direto nela) e descobre a empresa de cada uma.

    `empresas_conhecidas` traz as respostas já dadas pelo usuário, por `chave_empresa`.
    Uma pasta com problema volta com `erro` preenchido, sem impedir as outras.
    """
    empresas_conhecidas = empresas_conhecidas or {}
    reservadas = pastas_de_separacao or set()
    leituras: list[LeituraPasta] = []
    arquivos: dict[Path, list[Path]] = {}
    for pasta in pastas:
        leitura = LeituraPasta(pasta)
        leituras.append(leitura)
        if eh_pasta_saida(pasta, pasta_saida):
            leitura.erro = f'"{pasta.name}" é onde o UnePDF grava os resultados. Escolha a pasta de cima.'
        elif pasta.name.casefold() in reservadas:
            leitura.erro = f'"{pasta.name}" já é uma pasta de notas separadas. Escolha a pasta de cima.'
        else:
            try:
                arquivos[pasta] = _listar_notas(pasta)
            except OSError as erro:
                leitura.erro = f"Não foi possível abrir a pasta ({erro.strerror or erro})."
                continue
            if not arquivos[pasta]:
                leitura.erro = "Nenhuma nota (PDF ou XML) direto na pasta."

    total = sum(len(lista) for lista in arquivos.values())
    feitos = 0
    for leitura in leituras:
        nome = _nome_da_pasta(leitura.pasta)
        for caminho in arquivos.get(leitura.pasta, []):
            if cancelamento:
                cancelamento.verificar()
            feitos += 1
            if progresso:
                progresso(feitos, total, f"{leitura.pasta.name}: {caminho.name}")
            # Para conferir o nome, bastam as primeiras notas: em pastas enormes isso economiza tempo
            leitura.notas.append(ler_nota(caminho, nome if len(leitura.notas) < LIMITE_CONFERENCIA else None))
        if leitura.erro:
            continue
        leitura.tipo = _tipo_da_pasta(leitura.pasta, leitura.notas)
        leitura.candidatos, leitura.com_participantes = _votos(leitura.notas)
        conhecida = empresas_conhecidas.get(chave_empresa(leitura.pasta), "")
        leitura.empresa, leitura.como = _escolher_empresa(leitura, conhecida, pasta_saida, cancelamento)
        leitura.documento_do_nome, leitura.nome_na_nota = conferir_nome(leitura)
    return leituras


# Plano da separação

@dataclass
class Movimento:
    origem: Path
    destino: Path
    lado: Lado | None  # None: repetida, vai para a pasta de repetidas


@dataclass
class Copia:
    """Cópia idêntica de outra nota, que será apagada."""

    caminho: Path
    original: Path  # onde a nota que fica estará depois da separação
    resumo: str


@dataclass
class Plano:
    pasta: Path
    empresa: str
    nomes: dict[Lado, str]
    movimentos: list[Movimento] = field(default_factory=list)
    copias: list[Copia] = field(default_factory=list)
    nao_classificadas: list[ArquivoIgnorado] = field(default_factory=list)

    def quantidade(self, lado: Lado | None) -> int:
        return sum(1 for movimento in self.movimentos if movimento.lado is lado)

    @property
    def vazio(self) -> bool:
        return not self.movimentos and not self.copias


def classificar(nota: Nota, empresa: str) -> tuple[Lado | None, str]:
    """Lado da nota para a empresa, ou None com o motivo quando não há certeza."""
    if not nota.emitente:
        return None, nota.motivo or "não foi possível identificar quem emitiu a nota"
    if nota.emitente == empresa:
        return Lado.EMITIDAS, ""
    if nota.evento or empresa in nota.participantes:
        return Lado.RECEBIDAS, ""
    if len(nota.participantes) < 2:
        return None, nota.motivo or "não foi possível ler o destinatário da nota"
    return None, f"a empresa da pasta ({formatar_documento(empresa)}) não aparece nesta nota"


def _resumo_arquivo(caminho: Path) -> str:
    try:
        return hashlib.sha256(caminho.read_bytes()).hexdigest()
    except OSError:
        return ""


class _JaSeparadas:
    """Notas que já estão nas subpastas, de uma separação anterior."""

    def __init__(self, pastas: list[Path]):
        self.nomes: dict[Path, set[str]] = defaultdict(set)
        self.identidades: dict[tuple[str, str], Path] = {}
        self._por_tamanho: dict[int, list[Path]] = defaultdict(list)
        self._resumos: dict[Path, str] = {}
        for pasta in pastas:
            try:
                arquivos = list(pasta.iterdir()) if pasta.is_dir() else []
            except OSError:
                continue
            for arquivo in arquivos:
                self.nomes[pasta].add(arquivo.name.casefold())
                if not (eh_do_tipo(arquivo, PDF) or eh_do_tipo(arquivo, XML)):
                    continue
                # Só a chave do nome: ler o texto de todas as notas já separadas deixaria tudo lento na rede
                chave = chave_principal(chaves_no_texto(arquivo.stem))
                if chave:
                    self.identidades.setdefault((chave.numero, arquivo.suffix.lower()), arquivo)
                try:
                    self._por_tamanho[arquivo.stat().st_size].append(arquivo)
                except OSError:
                    pass

    def identica(self, nota: Nota) -> Path | None:
        if not nota.resumo:
            return None
        for caminho in self._por_tamanho.get(nota.tamanho, []):
            if caminho not in self._resumos:
                self._resumos[caminho] = _resumo_arquivo(caminho)
            if self._resumos[caminho] == nota.resumo:
                return caminho
        return None


def _nome_livre(nome: str, usados: set[str]) -> str:
    base, extensao = os.path.splitext(nome)
    candidato, contador = nome, 2
    while candidato.casefold() in usados:
        candidato, contador = f"{base} ({contador}){extensao}", contador + 1
    usados.add(candidato.casefold())
    return candidato


def _preferida(notas: list[Nota]) -> Nota:
    # Entre cópias da mesma nota, fica a que tem a chave no nome, que é o padrão dos sistemas atuais
    return min(notas, key=lambda nota: (not nota.chave_no_nome, ordem_natural(nota.caminho)))


def planejar(
    leitura: LeituraPasta, empresa: str, nomes: dict[Lado, str], pasta_saida: str = PASTA_SAIDA_PADRAO
) -> Plano:
    """Decide o destino de cada nota, sem mexer em nada. A execução fica para `separar`."""
    pasta = leitura.pasta
    plano = Plano(pasta, empresa, nomes)
    destinos = {lado: pasta / nome for lado, nome in nomes.items()}
    repetidas = pasta / pasta_saida / PASTA_REPETIDAS
    separadas = _JaSeparadas([*destinos.values(), repetidas])
    final: dict[int, Path] = {}  # onde cada nota estará no fim, para as cópias apontarem para ela

    def mover(nota: Nota, lado: Lado | None, pasta_destino: Path) -> None:
        destino = pasta_destino / _nome_livre(nota.caminho.name, separadas.nomes[pasta_destino])
        plano.movimentos.append(Movimento(nota.caminho, destino, lado))
        final[id(nota)] = destino

    # Cópias idênticas na própria pasta: fica uma
    por_conteudo: dict[str, list[Nota]] = defaultdict(list)
    restantes: list[Nota] = []
    for nota in leitura.notas:
        if nota.resumo:
            por_conteudo[nota.resumo].append(nota)
        else:
            restantes.append(nota)
    copias: list[tuple[Nota, Nota]] = []
    for grupo in por_conteudo.values():
        fica = _preferida(grupo)
        restantes.append(fica)
        copias.extend((nota, fica) for nota in grupo if nota is not fica)
    restantes.sort(key=lambda nota: ordem_natural(nota.caminho))

    # A mesma nota com conteúdo diferente (gerada de novo): as outras versões vão para as repetidas
    por_identidade: dict[tuple[str, str], list[Nota]] = defaultdict(list)
    for nota in restantes:
        if nota.identidade:
            por_identidade[nota.identidade].append(nota)
    outras_versoes = {
        id(nota) for grupo in por_identidade.values() if len(grupo) > 1
        for nota in grupo if nota is not _preferida(grupo)
    }

    for nota in restantes:
        if id(nota) in outras_versoes:
            mover(nota, None, repetidas)
            continue
        # A nota já foi separada antes e voltou para a pasta (o sistema que baixa as notas gravou de novo)
        igual = separadas.identica(nota)
        if igual:
            plano.copias.append(Copia(nota.caminho, igual, nota.resumo))
            final[id(nota)] = igual
            continue
        if nota.identidade in separadas.identidades:
            mover(nota, None, repetidas)
            continue
        lado, motivo = classificar(nota, empresa)
        if lado is None:
            plano.nao_classificadas.append(ArquivoIgnorado(nota.caminho, motivo))
            final[id(nota)] = nota.caminho
        else:
            mover(nota, lado, destinos[lado])

    for copia, fica in copias:
        plano.copias.append(Copia(copia.caminho, final[id(fica)], copia.resumo))
    return plano


# Execução, registro e desfazer

@dataclass
class Registro:
    """O que uma separação mudou, para poder desfazer."""

    pasta: Path
    data: datetime
    empresa: str = ""
    movidos: list[tuple[Path, Path]] = field(default_factory=list)  # (origem, destino)
    apagados: list[tuple[Path, Path]] = field(default_factory=list)  # (cópia, nota idêntica que ficou)
    pastas_criadas: list[Path] = field(default_factory=list)
    arquivo: Path | None = None

    def para_json(self) -> bytes:
        dados = {
            "pasta": str(self.pasta),
            "data": self.data.isoformat(timespec="seconds"),
            "empresa": self.empresa,
            "movidos": [[str(a), str(b)] for a, b in self.movidos],
            "apagados": [[str(a), str(b)] for a, b in self.apagados],
            "pastas_criadas": [str(p) for p in self.pastas_criadas],
        }
        return json.dumps(dados, ensure_ascii=False, indent=1).encode("utf-8")

    @classmethod
    def de_json(cls, arquivo: Path) -> Registro:
        dados = json.loads(arquivo.read_text(encoding="utf-8"))
        return cls(
            Path(dados["pasta"]), datetime.fromisoformat(dados["data"]), dados.get("empresa", ""),
            [(Path(a), Path(b)) for a, b in dados.get("movidos", [])],
            [(Path(a), Path(b)) for a, b in dados.get("apagados", [])],
            [Path(p) for p in dados.get("pastas_criadas", [])],
            arquivo,
        )


def _gravar_registro(registro: Registro, pasta_registros: Path) -> Path:
    if registro.arquivo is None:
        marca = hashlib.sha1(os.path.normcase(str(registro.pasta)).encode("utf-8")).hexdigest()[:10]
        registro.arquivo = pasta_registros / f"{registro.data:%Y%m%d-%H%M%S-%f}-{marca}.json"
    conteudo = registro.para_json()
    gravar_com_seguranca(registro.arquivo, lambda arquivo: arquivo.write(conteudo))
    return registro.arquivo


def ultimo_registro(pasta: Path, pasta_registros: Path | None = None) -> Registro | None:
    """A separação mais recente da pasta que ainda pode ser desfeita."""
    pasta_registros = pasta_registros or pasta_separacoes()
    alvo = os.path.normcase(str(pasta))
    try:
        arquivos = sorted(pasta_registros.glob("*.json"), reverse=True)
    except OSError:
        return None
    for arquivo in arquivos:
        try:
            registro = Registro.de_json(arquivo)
        except (OSError, ValueError, KeyError, TypeError):
            log.warning("Registro de separação ilegível: %s", arquivo)
            continue
        if os.path.normcase(str(registro.pasta)) == alvo and registro.movidos:
            return registro
    return None


def _motivo_falha(erro: OSError) -> str:
    if isinstance(erro, PermissionError):
        return "o arquivo está aberto em outro programa ou sem permissão"
    if isinstance(erro, FileNotFoundError):
        return "o arquivo não foi encontrado (foi movido ou apagado durante a separação)"
    return f"não foi possível mover ({erro.strerror or erro})"


def _criar_pasta(pasta: Path, registro: Registro) -> None:
    if pasta.is_dir():
        return
    _criar_pasta(pasta.parent, registro)
    pasta.mkdir()
    registro.pastas_criadas.append(pasta)


def _apagar_copia(copia: Copia) -> str:
    """Só apaga com a nota que fica no lugar e com o conteúdo ainda idêntico. Devolve o motivo da recusa."""
    if not copia.original.is_file():
        return "a cópia não foi apagada porque a nota que fica não foi encontrada"
    if _resumo_arquivo(copia.caminho) != copia.resumo or _resumo_arquivo(copia.original) != copia.resumo:
        return "a cópia não foi apagada porque o conteúdo mudou durante a separação"
    try:
        os.remove(copia.caminho)
    except OSError as erro:
        return _motivo_falha(erro)
    return ""


@dataclass
class ResultadoSeparacao:
    pasta: Path
    nomes: dict[Lado, str]
    movidas: Counter = field(default_factory=Counter)  # por lado; None são as repetidas
    apagadas: int = 0
    nao_classificadas: list[ArquivoIgnorado] = field(default_factory=list)
    falhas: list[ArquivoIgnorado] = field(default_factory=list)
    registro: Path | None = None
    cancelado: bool = False


def separar(
    planos: list[Plano],
    progresso: CallbackProgresso | None = None,
    cancelamento: Cancelamento | None = None,
    pasta_registros: Path | None = None,
) -> list[ResultadoSeparacao]:
    """Move as notas e apaga as cópias idênticas, conforme os planos.

    Um arquivo com problema não interrompe os outros. Ao cancelar, o que já foi movido fica
    registrado e pode ser desfeito.
    """
    pasta_registros = pasta_registros or pasta_separacoes()
    total = sum(len(plano.movimentos) + len(plano.copias) for plano in planos)
    feitos = 0
    resultados = []
    for plano in planos:
        resultado = ResultadoSeparacao(plano.pasta, plano.nomes, nao_classificadas=list(plano.nao_classificadas))
        resultados.append(resultado)
        if cancelamento and cancelamento.cancelado:
            resultado.cancelado = True
            continue
        registro = Registro(plano.pasta, datetime.now(), plano.empresa)
        try:
            for movimento in plano.movimentos:
                if cancelamento and cancelamento.cancelado:
                    resultado.cancelado = True
                    break
                feitos += 1
                if progresso:
                    progresso(feitos, total, f"{plano.pasta.name}: {movimento.origem.name}")
                try:
                    _criar_pasta(movimento.destino.parent, registro)
                    destino = movimento.destino
                    if destino.exists():
                        # Outro programa criou um arquivo com o mesmo nome depois da análise
                        destino = destino.parent / _nome_livre(destino.name, {p.name.casefold() for p in destino.parent.iterdir()})
                    # rename nunca substitui um arquivo existente no Windows
                    os.rename(movimento.origem, destino)
                except OSError as erro:
                    resultado.falhas.append(ArquivoIgnorado(movimento.origem, _motivo_falha(erro)))
                    continue
                registro.movidos.append((movimento.origem, destino))
                resultado.movidas[movimento.lado] += 1

            for copia in plano.copias:
                if resultado.cancelado or (cancelamento and cancelamento.cancelado):
                    resultado.cancelado = True
                    break
                feitos += 1
                if progresso:
                    progresso(feitos, total, f"{plano.pasta.name}: {copia.caminho.name}")
                motivo = _apagar_copia(copia)
                if motivo:
                    resultado.falhas.append(ArquivoIgnorado(copia.caminho, motivo))
                else:
                    registro.apagados.append((copia.caminho, copia.original))
                    resultado.apagadas += 1
        finally:
            if registro.movidos or registro.apagados:
                try:
                    resultado.registro = _gravar_registro(registro, pasta_registros)
                except ErroUnePDF:
                    log.exception("Não foi possível gravar o registro da separação de %s", plano.pasta)
        log.info(
            "Separação em %s: %s movidas, %d cópias apagadas, %d sem classificação, %d falhas",
            plano.pasta, dict(resultado.movidas), resultado.apagadas,
            len(resultado.nao_classificadas), len(resultado.falhas),
        )
    return resultados


@dataclass
class ResultadoDesfazer:
    pasta: Path
    devolvidas: int = 0
    copias_apagadas: int = 0  # não voltam, mas a nota idêntica a cada uma volta para a pasta
    falhas: list[ArquivoIgnorado] = field(default_factory=list)


def desfazer(registro: Registro, progresso: CallbackProgresso | None = None) -> ResultadoDesfazer:
    """Devolve as notas para a pasta original e remove as subpastas criadas, se ficarem vazias.

    Notas que não puderam voltar continuam no registro, para tentar de novo depois.
    """
    resultado = ResultadoDesfazer(registro.pasta, copias_apagadas=len(registro.apagados))
    pendentes = []
    for posicao, (origem, destino) in enumerate(reversed(registro.movidos), start=1):
        if progresso:
            progresso(posicao, len(registro.movidos), destino.name)
        if origem.exists():
            motivo = "já existe um arquivo com o mesmo nome na pasta original"
        elif not destino.exists():
            motivo = f'o arquivo não está mais em "{destino.parent.name}"'
        else:
            try:
                os.rename(destino, origem)
                resultado.devolvidas += 1
                continue
            except OSError as erro:
                motivo = _motivo_falha(erro)
        resultado.falhas.append(ArquivoIgnorado(destino, motivo))
        pendentes.append((origem, destino))

    for pasta in reversed(registro.pastas_criadas):
        try:
            pasta.rmdir()  # só remove se estiver vazia
        except OSError:
            pass

    if registro.arquivo:
        try:
            if pendentes:
                registro.movidos, registro.apagados = list(reversed(pendentes)), []
                _gravar_registro(registro, registro.arquivo.parent)
            else:
                registro.arquivo.unlink(missing_ok=True)
        except (OSError, ErroUnePDF):
            log.exception("Não foi possível atualizar o registro da separação %s", registro.arquivo)
    log.info("Separação desfeita em %s: %d devolvidas, %d falhas", registro.pasta, resultado.devolvidas, len(resultado.falhas))
    return resultado
