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

## PDFium

O PDFium, distribuído junto com o pypdfium2, inclui componentes de terceiros: Abseil, AGG, fast_float,
FreeType, ICU, Little CMS, libjpeg-turbo, OpenJPEG, libpng, LLVM libc, simdutf e zlib.

- Portions of this software are copyright © The FreeType Project (www.freetype.org). All rights reserved.
- This software is based in part on the work of the Independent JPEG Group.

## Executável

O executável para Windows é gerado com o [PyInstaller](https://pyinstaller.org/). O carregador do
PyInstaller é distribuído sob a GPL-2.0 com uma exceção que permite usá-lo em programas de qualquer
licença, então ele não muda a licença do UnePDF.
