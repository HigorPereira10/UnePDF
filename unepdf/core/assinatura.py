"""Assinatura digital de PDFs com certificado A1 (.pfx), no padrão PAdES aceito pela ICP-Brasil.

O certificado e a senha ficam só na memória durante a assinatura: nada é guardado. Quando há
internet, a confirmação de que o certificado não estava revogado vai junto no PDF, para a
assinatura continuar verificável depois que o certificado vencer. Só essa consulta à
certificadora sai do computador, nunca o documento.
"""
from __future__ import annotations

import asyncio
import csv
import getpass
import io
import logging
import platform
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from unepdf.core.carimbo import fonte_padrao, largura_texto, literal_pdf
from unepdf.core.erros import ErroUnePDF
from unepdf.core.gravacao import gravar_com_seguranca
from unepdf.core.leitor_pdf import ler_pdf_ou_erro
from unepdf.core.renderizacao import DocumentoRenderizavel
from unepdf.utils.recursos import caminho_recurso

log = logging.getLogger(__name__)

PASTA_RAIZES = "assets/icp-brasil"
SERVIDOR_ICP_BRASIL = "acraiz.icpbrasil.gov.br"

# Campos de identificação dos certificados ICP-Brasil, no "nome alternativo" do certificado
_OID_CNPJ = "2.16.76.1.3.3"
_OID_DADOS_PESSOA = "2.16.76.1.3.1"  # data de nascimento (8 dígitos) seguida do CPF
AVISO_VENCIMENTO_DIAS = 30
LARGURA_CARIMBO, ALTURA_CARIMBO = 230, 42  # pontos, parecido com o carimbo padrão do Adobe
MARGEM = 56


@dataclass
class Certificado:
    titular: str  # como no certificado, ex.: "EMPRESA EXEMPLO LTDA:12345678000199"
    nome: str  # sem o documento, ex.: "EMPRESA EXEMPLO LTDA"
    documento: str  # CNPJ ou CPF, só os dígitos (vazio se o certificado não informar)
    emissor: str
    valido_de: datetime
    valido_ate: datetime
    assinante: object = field(repr=False)  # assinante do pyHanko, com a chave privada

    @property
    def tipo_documento(self) -> str:
        return {14: "CNPJ", 11: "CPF"}.get(len(self.documento), "")

    @property
    def documento_formatado(self) -> str:
        d = self.documento
        if len(d) == 14:
            return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"
        if len(d) == 11:
            return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"
        return d

    def dias_restantes(self, agora: datetime | None = None) -> int:
        return (self.valido_ate - (agora or datetime.now(timezone.utc))).days

    @property
    def vencido(self) -> bool:
        return datetime.now(timezone.utc) > self.valido_ate


class SituacaoCertificado(Enum):
    VALIDO = "válido"  # cadeia até uma raiz da ICP-Brasil e não revogado
    REVOGADO = "revogado"
    CADEIA_DESCONHECIDA = "cadeia desconhecida"  # não chega a uma raiz da ICP-Brasil
    NAO_CONFERIDO = "não conferido"  # sem internet, ou a certificadora não respondeu


def _conteudo_der(valor: bytes) -> bytes:
    """Conteúdo de um valor DER simples (tipo, tamanho e dados), sem o tipo e o tamanho."""
    if len(valor) < 2:
        return b""
    tamanho = valor[1]
    if tamanho < 0x80:
        return valor[2:2 + tamanho]
    bytes_do_tamanho = tamanho & 0x7F
    tamanho = int.from_bytes(valor[2:2 + bytes_do_tamanho], "big")
    return valor[2 + bytes_do_tamanho:2 + bytes_do_tamanho + tamanho]


def documento_do_certificado(certificado, nome_comum: str) -> str:
    from cryptography import x509

    try:
        alternativos = certificado.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        for outro in alternativos.get_values_for_type(x509.OtherName):
            conteudo = _conteudo_der(outro.value)
            if outro.type_id.dotted_string == _OID_CNPJ and re.fullmatch(rb"\d{14}", conteudo):
                return conteudo.decode()
            if outro.type_id.dotted_string == _OID_DADOS_PESSOA and re.match(rb"\d{19}", conteudo):
                return conteudo[8:19].decode()
    except x509.ExtensionNotFound:
        pass
    achado = re.search(r":(\d{14}|\d{11})$", nome_comum)
    return achado.group(1) if achado else ""


def abrir_certificado(caminho: Path, senha: str) -> Certificado:
    """Lê o certificado A1. A senha errada vira uma mensagem clara, sem detalhes técnicos."""
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.x509.oid import NameOID
    from pyhanko.sign.signers import SimpleSigner

    try:
        dados = caminho.read_bytes()
    except OSError as erro:
        raise ErroUnePDF(f"Não foi possível ler o certificado:\n{caminho}\n\n{erro.strerror or erro}") from erro
    try:
        chave, certificado, _ = pkcs12.load_key_and_certificates(dados, senha.encode("utf-8") if senha else None)
    except ValueError as erro:
        raise ErroUnePDF("Senha incorreta, ou o arquivo não é um certificado A1 (.pfx) válido.") from erro
    if chave is None or certificado is None:
        raise ErroUnePDF("Este arquivo não traz a chave do certificado, então não serve para assinar.")
    assinante = SimpleSigner.load_pkcs12_data(dados, other_certs=None, passphrase=senha.encode("utf-8") if senha else None)
    if assinante is None:
        raise ErroUnePDF("Não foi possível usar este certificado para assinar.")

    def nome_comum(nome) -> str:
        atributos = nome.get_attributes_for_oid(NameOID.COMMON_NAME)
        return atributos[0].value if atributos else nome.rfc4514_string()

    titular = nome_comum(certificado.subject)
    documento = documento_do_certificado(certificado, titular)
    return Certificado(
        titular=titular,
        nome=re.sub(r":\d{11,14}$", "", titular),
        documento=documento,
        emissor=nome_comum(certificado.issuer),
        valido_de=certificado.not_valid_before_utc,
        valido_ate=certificado.not_valid_after_utc,
        assinante=assinante,
    )


def documento_aparece(dados: bytes, documento: str) -> bool:
    """Indica se o CNPJ ou CPF aparece no texto do PDF, com ou sem pontuação."""
    if not documento:
        return True
    with DocumentoRenderizavel(dados) as pdf:
        texto = " ".join(pdf.extrair_texto(i) for i in range(pdf.total))
    # Junta os números escritos com pontos, barras, hífens ou espaços (12.345.678/0001-99)
    so_numeros = re.sub(r"(?<=\d)[.\-/\s]+(?=\d)", "", texto)
    return re.search(rf"(?<!\d){documento}(?!\d)", so_numeros) is not None


# Posição do carimbo


@dataclass(frozen=True)
class PosicaoCarimbo:
    pagina: int  # a partir de 0
    caixa: tuple[float, float, float, float]  # x1, y1, x2, y2 em pontos, no sistema da página
    sobre_linha: bool  # encontrou uma linha de assinatura ("____")


def posicao_automatica(dados: bytes) -> PosicaoCarimbo:
    """Põe o carimbo sobre a última linha de assinatura do documento; sem linha, no pé da última página."""
    with DocumentoRenderizavel(dados) as pdf:
        for indice in range(pdf.total - 1, -1, -1):
            linhas = pdf.linhas_de_assinatura(indice)
            if linhas:
                # A mais baixa da página; entre linhas na mesma altura, a da direita
                x1, y1, x2, _ = min(linhas, key=lambda c: (round(c[1]), -c[0]))
                largura = min(LARGURA_CARIMBO, x2 - x1) if x2 - x1 > 120 else LARGURA_CARIMBO
                centro = (x1 + x2) / 2
                return PosicaoCarimbo(indice, (centro - largura / 2, y1 + 1, centro + largura / 2, y1 + 1 + ALTURA_CARIMBO), True)
        esquerda, base, direita, _ = pdf.caixa_visivel(pdf.total - 1)
        return PosicaoCarimbo(
            pdf.total - 1,
            (direita - MARGEM - LARGURA_CARIMBO, base + MARGEM, direita - MARGEM, base + MARGEM + ALTURA_CARIMBO),
            False,
        )


def mover_carimbo(posicao: PosicaoCarimbo, pagina: int, centro_x: float, centro_y: float) -> PosicaoCarimbo:
    x1, y1, x2, y2 = posicao.caixa
    largura, altura = x2 - x1, y2 - y1
    return PosicaoCarimbo(pagina, (centro_x - largura / 2, centro_y - altura / 2, centro_x + largura / 2, centro_y + altura / 2), False)


# Aparência do carimbo


def _quebrar(texto: str, tamanho: float, largura: float) -> list[str]:
    """Quebra o texto em linhas que cabem na largura; palavras longas demais são cortadas."""
    linhas, atual = [], ""
    for palavra in texto.split():
        tentativa = f"{atual} {palavra}".strip()
        if largura_texto(tentativa, tamanho) <= largura:
            atual = tentativa
            continue
        if atual:
            linhas.append(atual)
        while largura_texto(palavra, tamanho) > largura:
            corte = len(palavra)
            while corte > 1 and largura_texto(palavra[:corte], tamanho) > largura:
                corte -= 1
            linhas.append(palavra[:corte])
            palavra = palavra[corte:]
        atual = palavra
    if atual:
        linhas.append(atual)
    return linhas


def _ajustar(paragrafos: list[str], largura: float, altura: float, maximo: float, minimo: float = 4) -> tuple[float, list[str]]:
    """Maior tamanho de letra em que os parágrafos, quebrados em linhas, cabem na área."""
    tamanho = maximo
    while True:
        linhas = [linha for paragrafo in paragrafos for linha in _quebrar(paragrafo, tamanho, largura)]
        if len(linhas) * tamanho * 1.15 <= altura or tamanho <= minimo:
            return tamanho, linhas
        tamanho -= 0.25


def data_do_carimbo(quando: datetime) -> str:
    """Data no formato usado pelo carimbo padrão do Adobe: 2026.10.15 09:32:51 -03'00'."""
    deslocamento = quando.strftime("%z") or "+0000"
    return f"{quando:%Y.%m.%d %H:%M:%S} {deslocamento[:3]}'{deslocamento[3:]}'"


def desenhar_carimbo(titular: str, quando: datetime, largura: float = LARGURA_CARIMBO, altura: float = ALTURA_CARIMBO) -> bytes:
    """PDF de uma página com o desenho do carimbo: o nome em destaque à esquerda e os dados à direita."""
    escritor = PdfWriter()
    pagina = escritor.add_blank_page(largura, altura)
    pagina[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({
        NameObject("/F1"): fonte_padrao(escritor),
    })})
    respiro = 2
    meio = largura * 0.47
    comandos = []
    colunas = [
        (respiro, meio - 2 * respiro, [titular], 8.5),
        (meio + respiro, largura - meio - 2 * respiro,
         [f"Assinado de forma digital por {titular}", f"Dados: {data_do_carimbo(quando)}"], 6.5),
    ]
    for x, largura_coluna, paragrafos, maximo in colunas:
        tamanho, linhas = _ajustar(paragrafos, largura_coluna, altura - 2 * respiro, maximo)
        # Encostado embaixo, logo acima da linha de assinatura, como o carimbo padrão do Adobe
        y = respiro + (len(linhas) - 1) * tamanho * 1.15 + tamanho * 0.25
        for linha in linhas:
            comandos.append(f"BT /F1 {tamanho:.2f} Tf {x:.2f} {y:.2f} Td {literal_pdf(linha)} Tj ET")
            y -= tamanho * 1.15

    fluxo = DecodedStreamObject()
    fluxo.set_data("\n".join(comandos).encode("latin-1"))
    pagina[NameObject("/Contents")] = escritor._add_object(fluxo)
    saida = io.BytesIO()
    escritor.write(saida)
    return saida.getvalue()


# Assinatura


@dataclass
class ResultadoAssinatura:
    destino: Path
    substituiu_anterior: bool
    com_validacao: bool  # a confirmação de não revogação foi incluída
    pagina: int | None  # página do carimbo (None quando a assinatura é invisível)
    sem_internet: bool = False  # sem a confirmação por falta de conexão ou de resposta da certificadora


def raizes_icp_brasil() -> list:
    """Raízes oficiais da ICP-Brasil, do repositório do ITI. Muitos .pfx trazem só o certificado do titular."""
    from asn1crypto import pem, x509 as x509_asn1

    raizes = []
    for arquivo in sorted(caminho_recurso(PASTA_RAIZES).glob("*.crt")):
        dados = arquivo.read_bytes()
        if pem.detect(dados):
            dados = pem.unarmor(dados)[2]
        raizes.append(x509_asn1.Certificate.load(dados))
    return raizes


def _contexto_de_validacao(certificado: Certificado, buscador):
    from pyhanko_certvalidator import ValidationContext

    cadeia = list(certificado.assinante.cert_registry)
    raizes = [c for c in cadeia if c.self_issued] + raizes_icp_brasil()
    return ValidationContext(
        trust_roots=raizes, other_certs=cadeia, allow_fetching=True, revocation_mode="hard-fail",
        fetcher_backend=buscador,
    )


async def _completar_cadeia(certificado: Certificado, contexto) -> None:
    """Junta à assinatura os intermediários que faltam no .pfx, buscados na certificadora.

    O pyHanko os grava só nos dados de validação, e sem eles o Adobe não monta o caminho até a raiz.
    """
    from pyhanko.sign.general import SigningError
    from pyhanko_certvalidator import CertificateValidator
    from pyhanko_certvalidator.errors import PathBuildingError, PathValidationError

    assinante = certificado.assinante
    validador = CertificateValidator(
        assinante.signing_cert, intermediate_certs=assinante.cert_registry, validation_context=contexto,
    )
    try:
        caminho = await validador.async_validate_usage({"non_repudiation"})
    except (PathBuildingError, PathValidationError) as erro:
        raise SigningError("The signer's certificate could not be validated") from erro
    assinante.cert_registry.register_multiple(c for c in caminho.iter_certs(include_root=False) if c != assinante.signing_cert)


def situacao_pelo_erro(erro: BaseException) -> SituacaoCertificado:
    """Traduz a falha da validação do certificado (pyHanko) para o que o usuário precisa saber."""
    from pyhanko_certvalidator.errors import InsufficientRevinfoError, PathBuildingError, PathValidationError, RevokedError

    causas = []
    while erro is not None and erro not in causas:
        causas.append(erro)
        erro = erro.__cause__ or erro.__context__
    if any(isinstance(c, RevokedError) for c in causas):
        return SituacaoCertificado.REVOGADO
    if _sem_internet(causas[0]) or any(isinstance(c, InsufficientRevinfoError) for c in causas):
        return SituacaoCertificado.NAO_CONFERIDO
    if any(isinstance(c, (PathBuildingError, PathValidationError)) for c in causas):
        return SituacaoCertificado.CADEIA_DESCONHECIDA
    return SituacaoCertificado.NAO_CONFERIDO


def conferir_certificado(certificado: Certificado) -> SituacaoCertificado:
    """Confere, antes de assinar, se o certificado chega a uma raiz da ICP-Brasil e não foi revogado.

    Só as raízes oficiais contam: uma raiz que venha dentro do .pfx não torna o certificado válido.
    """
    from pyhanko_certvalidator import CertificateValidator, ValidationContext
    from pyhanko_certvalidator.fetchers.aiohttp_fetchers import AIOHttpFetcherBackend

    assinante = certificado.assinante

    async def conferir() -> None:
        buscador = AIOHttpFetcherBackend(per_request_timeout=15)
        try:
            contexto = ValidationContext(
                trust_roots=raizes_icp_brasil(), other_certs=list(assinante.cert_registry), allow_fetching=True,
                revocation_mode="hard-fail", fetcher_backend=buscador,
            )
            validador = CertificateValidator(
                assinante.signing_cert, intermediate_certs=assinante.cert_registry, validation_context=contexto,
            )
            await validador.async_validate_usage({"non_repudiation"})
        finally:
            await buscador.close()

    try:
        asyncio.run(conferir())
    except Exception as erro:
        log.info("Certificado de %s não confirmado: %s", certificado.titular, erro)
        return situacao_pelo_erro(erro)
    return SituacaoCertificado.VALIDO


def _assinar_bytes(dados: bytes, certificado: Certificado, posicao: PosicaoCarimbo | None, quando: datetime,
                   com_validacao: bool) -> bytes:
    from pyhanko import stamp
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko.sign import fields, signers
    from pyhanko_certvalidator.fetchers.aiohttp_fetchers import AIOHttpFetcherBackend

    escritor = IncrementalPdfFileWriter(io.BytesIO(dados), strict=False)
    existentes = {nome for nome, _, _ in fields.enumerate_sig_fields(escritor)}
    numero = 1
    while f"Assinatura{numero}" in existentes:
        numero += 1
    nome_campo = f"Assinatura{numero}"

    async def assinar_com(buscador) -> bytes:
        contexto = None
        if com_validacao:
            contexto = _contexto_de_validacao(certificado, buscador)
            await _completar_cadeia(certificado, contexto)
        metadados = signers.PdfSignatureMetadata(
            field_name=nome_campo, md_algorithm="sha256", subfilter=fields.SigSeedSubFilter.PADES,
            name=certificado.titular, embed_validation_info=com_validacao, validation_context=contexto,
        )
        assinador = signers.PdfSigner(metadados, signer=certificado.assinante, stamp_style=estilo, new_field_spec=campo)
        saida = io.BytesIO()
        await assinador.async_sign_pdf(escritor, output=saida)
        return saida.getvalue()

    async def assinar_e_fechar() -> bytes:
        if not com_validacao:
            return await assinar_com(None)
        buscador = AIOHttpFetcherBackend(per_request_timeout=15)
        try:
            return await assinar_com(buscador)
        finally:
            await buscador.close()

    estilo = None
    with tempfile.TemporaryDirectory(prefix="unepdf-assinatura-", ignore_cleanup_errors=True) as temporaria:
        if posicao is not None:
            x1, y1, x2, y2 = posicao.caixa
            desenho = Path(temporaria) / "carimbo.pdf"
            desenho.write_bytes(desenhar_carimbo(certificado.titular, quando, x2 - x1, y2 - y1))
            estilo = stamp.StaticStampStyle.from_pdf_file(str(desenho), border_width=0)
            campo = fields.SigFieldSpec(nome_campo, on_page=posicao.pagina, box=tuple(round(v) for v in posicao.caixa))
        else:
            campo = fields.SigFieldSpec(nome_campo, on_page=0, box=None)
        return asyncio.run(assinar_e_fechar())


def sem_conexao() -> bool:
    """Confere se o repositório da ICP-Brasil responde. Nenhum dado é enviado."""
    import socket

    try:
        socket.create_connection((SERVIDOR_ICP_BRASIL, 80), timeout=5).close()
    except OSError:
        return True
    return False


def _sem_internet(erro: BaseException) -> bool:
    """Se a confirmação falhou por falta de conexão, e não por um problema na cadeia do certificado."""
    import aiohttp

    vistos = set()
    while erro is not None and id(erro) not in vistos:
        vistos.add(id(erro))
        if isinstance(erro, (OSError, aiohttp.ClientError)):
            return True
        erro = erro.__cause__ or erro.__context__
    # Sem a cadeia completa o pyHanko não diz se a busca falhou por conexão
    return sem_conexao()


def assinar(
    origem: Path,
    destino: Path,
    certificado: Certificado,
    posicao: PosicaoCarimbo | None,
    incluir_validacao: bool = True,
    quando: datetime | None = None,
) -> ResultadoAssinatura:
    """Grava em `destino` uma cópia assinada de `origem`. `posicao` None faz uma assinatura invisível."""
    if certificado.vencido:
        raise ErroUnePDF(f"O certificado venceu em {certificado.valido_ate:%d/%m/%Y} e não pode mais assinar.")
    leitor, dados = ler_pdf_ou_erro(origem)
    if leitor.is_encrypted:
        raise ErroUnePDF(f'"{origem.name}" tem senha. Remova a senha antes de assinar.')
    quando = quando or datetime.now().astimezone()

    com_validacao = False
    sem_internet = False
    assinado = None
    if incluir_validacao:
        try:
            assinado = _assinar_bytes(dados, certificado, posicao, quando, True)
            com_validacao = True
        except Exception as erro:
            # Sem internet, sem resposta da certificadora ou cadeia desconhecida: assina sem a confirmação embutida
            log.warning("Assinatura sem os dados de revogação de %s", origem, exc_info=True)
            situacao = situacao_pelo_erro(erro)
            if situacao is SituacaoCertificado.REVOGADO:
                raise ErroUnePDF("O certificado foi revogado pela certificadora e não pode mais assinar.") from erro
            sem_internet = situacao is SituacaoCertificado.NAO_CONFERIDO
    if assinado is None:
        try:
            assinado = _assinar_bytes(dados, certificado, posicao, quando, False)
        except ErroUnePDF:
            raise
        except Exception as erro:
            log.exception("Falha ao assinar %s", origem)
            raise ErroUnePDF(f'Não foi possível assinar "{origem.name}". Os detalhes ficaram no registro de atividades.') from erro

    substituiu = gravar_com_seguranca(destino, lambda arquivo: arquivo.write(assinado))
    return ResultadoAssinatura(destino, substituiu, com_validacao, posicao.pagina if posicao else None, sem_internet)


def registrar(arquivo_registro: Path, assinado: Path, certificado: Certificado, quando: datetime | None = None) -> None:
    """Acrescenta uma linha ao registro local de assinaturas (planilha que abre no Excel)."""
    quando = quando or datetime.now()
    novo = not arquivo_registro.exists()
    try:
        arquivo_registro.parent.mkdir(parents=True, exist_ok=True)
        with open(arquivo_registro, "a", encoding="utf-8-sig" if novo else "utf-8", newline="") as arquivo:
            escritor = csv.writer(arquivo, delimiter=";")
            if novo:
                escritor.writerow(["Data", "Hora", "Arquivo assinado", "Titular do certificado", "Documento",
                                   "Usuário do Windows", "Computador"])
            escritor.writerow([
                f"{quando:%d/%m/%Y}", f"{quando:%H:%M:%S}", str(assinado), certificado.nome,
                certificado.documento_formatado, getpass.getuser(), platform.node(),
            ])
    except OSError:
        # O registro é um controle a mais: uma falha nele não pode desfazer a assinatura já gravada
        log.warning("Não foi possível gravar o registro de assinaturas em %s", arquivo_registro, exc_info=True)


# Vários PDFs


@dataclass
class ResultadoLoteAssinatura:
    gerados: list[Path] = field(default_factory=list)
    ignorados: list = field(default_factory=list)
    sem_validacao: int = 0  # assinados sem a confirmação da certificadora (ex.: sem internet)
    sem_cadeia: int = 0  # dos sem confirmação, os que tinham internet mas a cadeia não foi conferida
    substituidos: int = 0
    pendentes: int = 0

    @property
    def cancelado(self) -> bool:
        return self.pendentes > 0


def assinar_varios(
    arquivos: list[Path],
    destinos: dict[Path, Path],
    certificado: Certificado,
    visivel: bool = True,
    posicoes: dict[Path, PosicaoCarimbo] | None = None,
    arquivo_registro: Path | None = None,
    progresso=None,
    cancelamento=None,
) -> ResultadoLoteAssinatura:
    """Assina cada PDF. Sem posição escolhida pelo usuário, o carimbo vai para a posição automática."""
    from unepdf.core.modelos import ArquivoIgnorado

    resultado = ResultadoLoteAssinatura()
    posicoes = posicoes or {}
    for indice, origem in enumerate(arquivos):
        if cancelamento and cancelamento.cancelado:
            resultado.pendentes = len(arquivos) - indice
            return resultado
        if progresso:
            progresso(indice + 1, len(arquivos), origem.name)
        try:
            posicao = None
            if visivel:
                posicao = posicoes.get(origem) or posicao_automatica(ler_pdf_ou_erro(origem)[1])
            assinado = assinar(origem, destinos[origem], certificado, posicao)
        except ErroUnePDF as erro:
            resultado.ignorados.append(ArquivoIgnorado(origem, erro.mensagem.replace("\n", " ")))
            continue
        resultado.gerados.append(assinado.destino)
        resultado.substituidos += assinado.substituiu_anterior
        resultado.sem_validacao += not assinado.com_validacao
        resultado.sem_cadeia += not assinado.com_validacao and not assinado.sem_internet
        if arquivo_registro:
            registrar(arquivo_registro, assinado.destino, certificado)
    if not resultado.gerados:
        raise ErroUnePDF("Nenhum PDF foi assinado.", resultado.ignorados)
    return resultado
