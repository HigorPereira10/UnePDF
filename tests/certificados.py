"""Certificados fictícios para os testes de assinatura, no formato dos e-CNPJ e e-CPF da ICP-Brasil.

Tudo é gerado na hora: uma autoridade certificadora raiz de teste, uma intermediária e um certificado
A1 (.pfx) assinado por uma delas.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import AuthorityInformationAccessOID, NameOID

CNPJ_EXEMPLO = "12345678000199"
SENHA = "1234"
# Campos de identificação dos certificados ICP-Brasil (outros nomes no "nome alternativo")
OID_CNPJ = x509.ObjectIdentifier("2.16.76.1.3.3")
OID_DADOS_PESSOA = x509.ObjectIdentifier("2.16.76.1.3.1")

_cache: dict = {}


def _chave():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _autoridade():
    if "ac" not in _cache:
        chave = _chave()
        nome = x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, "BR"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "ICP-Teste"),
            x509.NameAttribute(NameOID.COMMON_NAME, "AC TESTE UNEPDF"),
        ])
        agora = datetime.now(timezone.utc)
        certificado = (
            x509.CertificateBuilder()
            .subject_name(nome).issuer_name(nome).public_key(chave.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(agora - timedelta(days=3650)).not_valid_after(agora + timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(
                digital_signature=False, content_commitment=False, key_encipherment=False, data_encipherment=False,
                key_agreement=False, key_cert_sign=True, crl_sign=True, encipher_only=False, decipher_only=False,
            ), critical=True)
            .sign(chave, hashes.SHA256())
        )
        _cache["ac"] = (chave, certificado)
    return _cache["ac"]


def _intermediaria():
    if "intermediaria" not in _cache:
        chave_ac, certificado_ac = _autoridade()
        chave = _chave()
        agora = datetime.now(timezone.utc)
        certificado = (
            x509.CertificateBuilder()
            .subject_name(x509.Name([
                x509.NameAttribute(NameOID.COUNTRY_NAME, "BR"),
                x509.NameAttribute(NameOID.ORGANIZATION_NAME, "ICP-Teste"),
                x509.NameAttribute(NameOID.COMMON_NAME, "AC INTERMEDIARIA TESTE UNEPDF"),
            ]))
            .issuer_name(certificado_ac.subject).public_key(chave.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(agora - timedelta(days=1825)).not_valid_after(agora + timedelta(days=1825))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(
                digital_signature=False, content_commitment=False, key_encipherment=False, data_encipherment=False,
                key_agreement=False, key_cert_sign=True, crl_sign=True, encipher_only=False, decipher_only=False,
            ), critical=True)
            .sign(chave_ac, hashes.SHA256())
        )
        _cache["intermediaria"] = (chave, certificado)
    return _cache["intermediaria"]


def certificado_intermediario_der() -> bytes:
    """A AC intermediária em DER, como as certificadoras publicam no endereço indicado no certificado."""
    return _intermediaria()[1].public_bytes(serialization.Encoding.DER)


def criar_pfx(
    caminho: Path,
    nome: str = "EMPRESA EXEMPLO LTDA",
    documento: str = CNPJ_EXEMPLO,
    senha: str = SENHA,
    dias_restantes: int = 300,
    intermediaria: bool = False,
    com_cadeia: bool = True,
    endereco_ac: str = "",
    endereco_lcr: str = "",
) -> Path:
    """Grava um certificado A1 com o nome no formato "RAZÃO SOCIAL:CNPJ" (ou "NOME:CPF").

    `com_cadeia` False imita os .pfx que trazem só o certificado do titular; `endereco_ac` é de onde
    a AC emissora pode ser baixada (a extensão de acesso às informações da autoridade) e
    `endereco_lcr`, de onde vem a lista de certificados revogados (veja `criar_lcr`).
    """
    chave_ac, certificado_ac = _intermediaria() if intermediaria else _autoridade()
    cadeia = [certificado_ac, _autoridade()[1]] if intermediaria else [certificado_ac]
    chave = _chave()
    agora = datetime.now(timezone.utc)
    if len(documento) == 14:
        outro_nome = x509.OtherName(OID_CNPJ, b"\x04\x0e" + documento.encode())
    else:
        dados = f"01011980{documento}" + "0" * 30
        outro_nome = x509.OtherName(OID_DADOS_PESSOA, b"\x04" + bytes([len(dados)]) + dados.encode())
    construtor = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, "BR"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "ICP-Teste"),
            x509.NameAttribute(NameOID.COMMON_NAME, f"{nome}:{documento}"),
        ]))
        .issuer_name(certificado_ac.subject).public_key(chave.public_key())
        .serial_number(x509.random_serial_number())
        # Validade de um ano, como a do A1, terminando daqui a `dias_restantes` (negativo: já vencido)
        .not_valid_before(agora + timedelta(days=dias_restantes - 365))
        .not_valid_after(agora + timedelta(days=dias_restantes))
        .add_extension(x509.SubjectAlternativeName([outro_nome]), critical=False)
        .add_extension(x509.KeyUsage(
            digital_signature=True, content_commitment=True, key_encipherment=True, data_encipherment=False,
            key_agreement=False, key_cert_sign=False, crl_sign=False, encipher_only=False, decipher_only=False,
        ), critical=True)
    )
    if endereco_ac:
        construtor = construtor.add_extension(x509.AuthorityInformationAccess([x509.AccessDescription(
            AuthorityInformationAccessOID.CA_ISSUERS, x509.UniformResourceIdentifier(endereco_ac),
        )]), critical=False)
    if endereco_lcr:
        construtor = construtor.add_extension(x509.CRLDistributionPoints([x509.DistributionPoint(
            full_name=[x509.UniformResourceIdentifier(endereco_lcr)], relative_name=None, reasons=None, crl_issuer=None,
        )]), critical=False)
    certificado = construtor.sign(chave_ac, hashes.SHA256())
    conteudo = pkcs12.serialize_key_and_certificates(
        nome.encode(), chave, certificado, cadeia if com_cadeia else None,
        serialization.BestAvailableEncryption(senha.encode()),
    )
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_bytes(conteudo)
    return caminho


def criar_lcr(revogados: tuple[int, ...] = ()) -> bytes:
    """Lista de certificados revogados da AC raiz de teste, em DER. Os revogados constam desde ontem."""
    chave_ac, certificado_ac = _autoridade()
    agora = datetime.now(timezone.utc)
    construtor = (
        x509.CertificateRevocationListBuilder()
        .issuer_name(certificado_ac.subject)
        .last_update(agora - timedelta(hours=1)).next_update(agora + timedelta(days=7))
    )
    for numero in revogados:
        construtor = construtor.add_revoked_certificate(
            x509.RevokedCertificateBuilder().serial_number(numero).revocation_date(agora - timedelta(days=1)).build()
        )
    return construtor.sign(chave_ac, hashes.SHA256()).public_bytes(serialization.Encoding.DER)


def numero_de_serie(pfx: Path, senha: str = SENHA) -> int:
    return pkcs12.load_key_and_certificates(pfx.read_bytes(), senha.encode())[1].serial_number


def certificado_da_autoridade():
    """Certificado da AC de teste, para validar as assinaturas nos testes."""
    from asn1crypto import x509 as x509_asn1

    return x509_asn1.Certificate.load(_autoridade()[1].public_bytes(serialization.Encoding.DER))
