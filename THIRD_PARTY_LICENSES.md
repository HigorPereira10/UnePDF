# Licenças de terceiros

O UnePDF é distribuído sob a [licença MIT](LICENSE). Ele usa os componentes abaixo, cada um com a
sua própria licença.

Os textos completos de todas as licenças vão junto com o programa, na pasta `licenses` da instalação.
Eles são copiados dos próprios pacotes durante a geração do executável (veja
[tools/coletar_licencas.py](tools/coletar_licencas.py)), então sempre correspondem às versões
distribuídas. Quem roda pelo código-fonte recebe os mesmos textos junto com cada pacote instalado
pelo pip.

| Componente | Uso no UnePDF | Licença |
|---|---|---|
| [pypdf](https://github.com/py-pdf/pypdf) | Leitura e gravação de PDFs | BSD-3-Clause |
| [cryptography](https://github.com/pyca/cryptography) | Abrir PDFs protegidos com criptografia AES | Apache-2.0 ou BSD-3-Clause, à escolha |
| [cffi](https://github.com/python-cffi/cffi) | Dependência do cryptography | MIT-0 |
| [pycparser](https://github.com/eliben/pycparser) | Dependência do cffi | BSD-3-Clause |
| [pypdfium2](https://github.com/pypdfium2-team/pypdfium2) e [PDFium](https://pdfium.googlesource.com/pdfium/) | Miniaturas das páginas e conversão de páginas em imagem | BSD-3-Clause ou Apache-2.0 (pypdfium2), BSD-3-Clause (PDFium) e licenças dos componentes do PDFium |
| [Pillow](https://github.com/python-pillow/Pillow) | Leitura das imagens na conversão para PDF e gravação de PNG e JPG | MIT-CMU |
| [BrazilFiscalReport](https://github.com/Engenere/BrazilFiscalReport) | Desenho do DANFE, DANFCe, DACTE, DAMDFE, DANFSe e DACCe a partir dos XMLs | LGPL-3.0 |
| [fpdf2](https://github.com/py-pdf/fpdf2) | Geração dos PDFs dos documentos fiscais (dependência da BrazilFiscalReport) | LGPL-3.0 |
| [fontTools](https://github.com/fonttools/fonttools) | Dependência do fpdf2 | MIT |
| [qrcode](https://github.com/lincolnloop/python-qrcode) | QR Code dos documentos fiscais | BSD-3-Clause |
| [python-barcode](https://github.com/WhyNotHugo/python-barcode) | Código de barras da chave de acesso | MIT |
| [phonenumbers](https://github.com/daviddrysdale/python-phonenumbers) | Formatação de telefones nos documentos fiscais | Apache-2.0 |
| [defusedxml](https://github.com/tiran/defusedxml) | Leitura segura dos XMLs | PSF-2.0 |
| [pywin32](https://github.com/mhammond/pywin32) | Automação do Microsoft Office na conversão para PDF | PSF-2.0 |
| [pyHanko](https://github.com/MatthiasValvekens/pyHanko) e pyhanko-certvalidator | Assinatura digital de PDFs | MIT |
| [asn1crypto](https://github.com/wbond/asn1crypto) e [oscrypto](https://github.com/wbond/oscrypto) | Leitura de certificados (dependências do pyHanko) | MIT |
| [aiohttp](https://github.com/aio-libs/aiohttp), aiohappyeyeballs, aiosignal, frozenlist, multidict, propcache e yarl | Consulta à certificadora durante a assinatura | Apache-2.0 (aiohttp também MIT; aiohappyeyeballs PSF-2.0) |
| [lxml](https://github.com/lxml/lxml) | Dependência do pyHanko | BSD-3-Clause |
| attrs, tzlocal e uritools | Dependências do pyHanko | MIT |
| idna | Dependência do aiohttp | BSD-3-Clause |
| tzdata | Fusos horários da data da assinatura | Apache-2.0 |
| [certifi](https://github.com/certifi/python-certifi) | Certificados das conexões seguras, sem modificação | MPL-2.0 |
| [PySide6 e shiboken6](https://doc.qt.io/qtforpython-6/) (Qt for Python) | Interface gráfica | LGPL-3.0 ([texto](licenses/LGPL-3.0.txt), que complementa a [GPL-3.0](licenses/GPL-3.0.txt)) |
| [Qt 6](https://www.qt.io/) | Bibliotecas da interface, distribuídas junto com o PySide6 | LGPL-3.0 |
| [Python](https://www.python.org/) | Interpretador incluído no executável | PSF-2.0 |

## PySide6 e Qt (LGPL-3.0)

- O UnePDF usa o PySide6 e o Qt sob a LGPL-3.0, sem nenhuma modificação.
- As bibliotecas ficam como arquivos separados (`.dll` e `.pyd`) na pasta de instalação, ligadas
  dinamicamente. Você pode substituí-las por versões compatíveis, inclusive modificadas por você.
- Os pacotes do PySide6 não trazem o texto da LGPL, por isso ele (e o da GPL-3.0, que a LGPL
  complementa) fica na pasta [licenses](licenses/) deste repositório.
- Código-fonte do PySide6: <https://code.qt.io/cgit/pyside/pyside-setup.git/>
- Código-fonte do Qt: <https://download.qt.io/official_releases/qt/>
- O Qt inclui componentes de terceiros com licenças próprias, listados em
  <https://doc.qt.io/qt-6/licenses-used-in-qt.html>.

## BrazilFiscalReport e fpdf2 (LGPL-3.0)

- O UnePDF usa as duas bibliotecas sob a LGPL-3.0, sem nenhuma modificação.
- No executável, os módulos delas ficam como arquivos `.py` separados (nas pastas `brazilfiscalreport` e
  `fpdf` dentro de `_internal`), sem compactação, para que possam ser substituídos por versões
  compatíveis, inclusive modificadas.
- Código-fonte: <https://github.com/Engenere/BrazilFiscalReport> e <https://github.com/py-pdf/fpdf2>.

## PDFium

O PDFium, distribuído junto com o pypdfium2, inclui componentes de terceiros: Abseil, AGG, fast_float,
FreeType, ICU, Little CMS, libjpeg-turbo, OpenJPEG, libpng, LLVM libc, simdutf e zlib.

- Portions of this software are copyright © The FreeType Project (www.freetype.org). All rights reserved.
- This software is based in part on the work of the Independent JPEG Group.

## Ghostscript

A conversão para PDF/A e a compressão forte usam o [Ghostscript](https://ghostscript.com/), distribuído
sob a AGPL-3.0. Ele é um programa separado: o UnePDF apenas o executa por linha de comando, sem
incorporar o código dele, então a licença do UnePDF continua sendo a MIT. O instalador e o `.zip`
portátil trazem uma cópia sem modificações na pasta `ghostscript`, com o texto da licença
(`LICENSE.txt`) e o link para o código-fonte (<https://ghostscript.com/releases/gsdnld.html>). No
instalador, ele é um componente opcional.

## Tesseract

O OCR usa o [Tesseract](https://github.com/tesseract-ocr/tesseract), distribuído sob a Apache-2.0, com os
dados de idioma do projeto [tessdata](https://github.com/tesseract-ocr/tessdata) (também Apache-2.0). Ele é
um programa separado, que o UnePDF executa por linha de comando. O instalador e o `.zip` portátil trazem
uma cópia sem modificações na pasta `tesseract`, com os idiomas português e inglês e o texto da licença
(`LICENSE.txt`). No instalador, ele é um componente opcional.

## Microsoft Office e LibreOffice

A conversão de documentos do Office usa o Microsoft Office ou o LibreOffice já instalados no
computador. Eles são programas separados, que o UnePDF apenas aciona, e não vão junto com ele.

## Executável e instalador

O executável para Windows é gerado com o [PyInstaller](https://pyinstaller.org/). O carregador do
PyInstaller é distribuído sob a GPL-2.0 com uma exceção que permite usá-lo em programas de qualquer
licença, então ele não muda a licença do UnePDF. O instalador é gerado com o
[Inno Setup](https://jrsoftware.org/isinfo.php), cuja licença permite distribuir instaladores feitos com ele.
