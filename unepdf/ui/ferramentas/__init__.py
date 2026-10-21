"""Registro das ferramentas exibidas na tela inicial e na barra lateral.

Só entram aqui ferramentas prontas. Para adicionar uma nova, crie a tela em um módulo
desta pasta e acrescente um item em FERRAMENTAS.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from unepdf.core import ghostscript, ocr, office, pdf_office
from unepdf.ui.contexto import ContextoApp
from unepdf.ui.ferramentas.base import TelaFerramenta
from unepdf.ui.ferramentas.assinar import TelaAssinar
from unepdf.ui.ferramentas.converter import TelaImagensParaPdf, TelaPdfA, TelaPdfParaImagens, TelaPdfParaTexto
from unepdf.ui.ferramentas.dividir import TelaDividir
from unepdf.ui.ferramentas.editar import TelaMarcaDagua, TelaNumerar
from unepdf.ui.ferramentas.ocr_pdf import TelaOcr
from unepdf.ui.ferramentas.office_pdf import TelaOfficeParaPdf
from unepdf.ui.ferramentas.otimizar import TelaComprimir
from unepdf.ui.ferramentas.paginas import TelaExtrair, TelaOrganizar
from unepdf.ui.ferramentas.pdf_para_office import TelaPdfParaExcel, TelaPdfParaWord
from unepdf.ui.ferramentas.seguranca import TelaProteger, TelaRemoverSenha
from unepdf.ui.ferramentas.separar import TelaSepararNotas
from unepdf.ui.ferramentas.unir import TelaUnir
from unepdf.ui.ferramentas.unir_lote import TelaUnirLote
from unepdf.ui.ferramentas.xml_pdf import TelaXmlParaPdf

# Ordem em que as categorias aparecem na tela inicial e na barra lateral
CATEGORIAS = ("Organizar", "Converter", "Editar", "Segurança", "Otimizar")


def _sempre_disponivel() -> str | None:
    return None


@dataclass(frozen=True)
class Ferramenta:
    chave: str
    nome: str
    descricao: str
    icone: str  # caminho relativo à raiz do projeto
    categoria: str
    tela: Callable[[Ferramenta, ContextoApp], TelaFerramenta]
    # Devolve o motivo quando falta algo para a ferramenta funcionar (ex.: programa externo ausente)
    motivo_indisponivel: Callable[[], str | None] = _sempre_disponivel
    # Nome na barra lateral, quando o completo não cabe nela
    nome_curto: str = ""

    @property
    def nome_lateral(self) -> str:
        return self.nome_curto or self.nome


FERRAMENTAS: list[Ferramenta] = [
    Ferramenta(
        chave="unir",
        nome="Unir PDFs",
        descricao="Junte vários PDFs em um só arquivo, com um marcador para cada um.",
        icone="assets/icones/unir.svg",
        categoria="Organizar",
        tela=TelaUnir,
    ),
    Ferramenta(
        chave="unir_lote",
        nome="Unir em lote",
        descricao="Gere um PDF unificado para cada subpasta de uma pasta, com relatório no final.",
        icone="assets/icones/unir_lote.svg",
        categoria="Organizar",
        tela=TelaUnirLote,
    ),
    Ferramenta(
        chave="separar",
        nome="Separar emitidas e recebidas",
        descricao="Separe as notas fiscais de uma pasta em subpastas de emitidas e recebidas, pelo CNPJ.",
        icone="assets/icones/separar.svg",
        categoria="Organizar",
        tela=TelaSepararNotas,
        nome_curto="Emitidas e recebidas",
    ),
    Ferramenta(
        chave="dividir",
        nome="Dividir PDF",
        descricao="Separe um PDF em vários: por intervalos, a cada N páginas ou por marcador.",
        icone="assets/icones/dividir.svg",
        categoria="Organizar",
        tela=TelaDividir,
    ),
    Ferramenta(
        chave="organizar",
        nome="Organizar páginas",
        descricao="Reordene arrastando, gire e remova páginas, vendo as miniaturas.",
        icone="assets/icones/organizar.svg",
        categoria="Organizar",
        tela=TelaOrganizar,
    ),
    Ferramenta(
        chave="extrair",
        nome="Extrair páginas",
        descricao="Escolha páginas de um PDF e salve em um novo arquivo.",
        icone="assets/icones/extrair.svg",
        categoria="Organizar",
        tela=TelaExtrair,
    ),
    Ferramenta(
        chave="xml_pdf",
        nome="XML para PDF",
        descricao="Gere DANFE, DANFCe, DACTE, DAMDFE, DANFSe e carta de correção a partir dos XMLs.",
        icone="assets/icones/xml_pdf.svg",
        categoria="Converter",
        tela=TelaXmlParaPdf,
    ),
    Ferramenta(
        chave="office_pdf",
        nome="Office para PDF",
        descricao="Converta documentos do Word, Excel e PowerPoint para PDF, vários de uma vez.",
        icone="assets/icones/office_pdf.svg",
        categoria="Converter",
        tela=TelaOfficeParaPdf,
        motivo_indisponivel=office.disponivel,
    ),
    Ferramenta(
        chave="pdf_word",
        nome="PDF para Word",
        descricao="Transforme PDFs em documentos do Word com o texto editável.",
        icone="assets/icones/pdf_word.svg",
        categoria="Converter",
        tela=TelaPdfParaWord,
        motivo_indisponivel=pdf_office.word_disponivel,
    ),
    Ferramenta(
        chave="pdf_excel",
        nome="PDF para Excel",
        descricao="Leve as tabelas de relatórios e extratos em PDF para uma planilha.",
        icone="assets/icones/pdf_excel.svg",
        categoria="Converter",
        tela=TelaPdfParaExcel,
    ),
    Ferramenta(
        chave="imagens_pdf",
        nome="Imagens para PDF",
        descricao="Transforme fotos e imagens escaneadas em um PDF, sem perder qualidade.",
        icone="assets/icones/imagens_pdf.svg",
        categoria="Converter",
        tela=TelaImagensParaPdf,
    ),
    Ferramenta(
        chave="pdf_imagens",
        nome="PDF para imagens",
        descricao="Salve cada página do PDF como uma imagem PNG ou JPG.",
        icone="assets/icones/pdf_imagens.svg",
        categoria="Converter",
        tela=TelaPdfParaImagens,
    ),
    Ferramenta(
        chave="pdf_texto",
        nome="PDF para texto",
        descricao="Copie todo o texto de um PDF para um arquivo .txt.",
        icone="assets/icones/pdf_texto.svg",
        categoria="Converter",
        tela=TelaPdfParaTexto,
    ),
    Ferramenta(
        chave="pdfa",
        nome="PDF para PDF/A",
        descricao="Converta para PDF/A-1b, 2b ou 3b, o formato de arquivamento de longo prazo.",
        icone="assets/icones/pdfa.svg",
        categoria="Converter",
        tela=TelaPdfA,
        motivo_indisponivel=ghostscript.disponivel,
    ),
    Ferramenta(
        chave="marca_dagua",
        nome="Marca d'água",
        descricao="Escreva um texto, como CONFIDENCIAL, sobre todas as páginas.",
        icone="assets/icones/marca_dagua.svg",
        categoria="Editar",
        tela=TelaMarcaDagua,
    ),
    Ferramenta(
        chave="numerar",
        nome="Numerar páginas",
        descricao="Coloque o número em cada página, no rodapé ou no topo.",
        icone="assets/icones/numerar.svg",
        categoria="Editar",
        tela=TelaNumerar,
    ),
    Ferramenta(
        chave="proteger",
        nome="Proteger com senha",
        descricao="Crie uma cópia do PDF que só abre com senha.",
        icone="assets/icones/proteger.svg",
        categoria="Segurança",
        tela=TelaProteger,
    ),
    Ferramenta(
        chave="remover_senha",
        nome="Remover senha",
        descricao="Crie uma cópia sem senha de um PDF protegido, informando a senha.",
        icone="assets/icones/remover_senha.svg",
        categoria="Segurança",
        tela=TelaRemoverSenha,
    ),
    Ferramenta(
        chave="assinar",
        nome="Assinar PDF",
        descricao="Assine PDFs com certificado digital A1 (.pfx), com carimbo na página.",
        icone="assets/icones/assinar.svg",
        categoria="Segurança",
        tela=TelaAssinar,
    ),
    Ferramenta(
        chave="comprimir",
        nome="Comprimir PDF",
        descricao="Reduza o tamanho do PDF, com ou sem perda de qualidade nas imagens.",
        icone="assets/icones/comprimir.svg",
        categoria="Otimizar",
        tela=TelaComprimir,
    ),
    Ferramenta(
        chave="ocr",
        nome="OCR",
        descricao="Deixe PDFs escaneados e imagens pesquisáveis, com o texto selecionável e copiável.",
        icone="assets/icones/ocr.svg",
        categoria="Otimizar",
        tela=TelaOcr,
        motivo_indisponivel=ocr.disponivel,
    ),
]


def buscar(chave: str) -> Ferramenta:
    return next(f for f in FERRAMENTAS if f.chave == chave)


def por_categoria(ferramentas: list[Ferramenta] = FERRAMENTAS) -> list[tuple[str, list[Ferramenta]]]:
    """Ferramentas agrupadas na ordem de CATEGORIAS. Categorias sem ferramentas ficam de fora."""
    grupos = [(c, [f for f in ferramentas if f.categoria == c]) for c in CATEGORIAS]
    return [(categoria, lista) for categoria, lista in grupos if lista]
