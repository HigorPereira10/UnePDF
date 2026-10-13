# Licenças de terceiros

O UnePDF é distribuído sob a [licença MIT](LICENSE). Ele usa os componentes abaixo, cada um com a
sua própria licença. Os textos completos estão na pasta [licenses](licenses/).

| Componente | Uso no UnePDF | Licença | Texto |
|---|---|---|---|
| [pypdf](https://github.com/py-pdf/pypdf) | Leitura e gravação de PDFs | BSD-3-Clause | [pypdf-BSD-3-Clause.txt](licenses/pypdf-BSD-3-Clause.txt) |
| [cryptography](https://github.com/pyca/cryptography) | Abrir PDFs protegidos com criptografia AES | Apache-2.0 ou BSD-3-Clause, à escolha | [cryptography-LICENSE.txt](licenses/cryptography-LICENSE.txt), [Apache-2.0](licenses/cryptography-Apache-2.0.txt), [BSD-3-Clause](licenses/cryptography-BSD-3-Clause.txt) |
| [cffi](https://github.com/python-cffi/cffi) | Dependência do cryptography | MIT-0 | [cffi-MIT-0.txt](licenses/cffi-MIT-0.txt) |
| [pycparser](https://github.com/eliben/pycparser) | Dependência do cffi | BSD-3-Clause | [pycparser-BSD-3-Clause.txt](licenses/pycparser-BSD-3-Clause.txt) |
| [PySide6 e shiboken6](https://doc.qt.io/qtforpython-6/) (Qt for Python) | Interface gráfica | LGPL-3.0 | [LGPL-3.0.txt](licenses/LGPL-3.0.txt), [GPL-3.0.txt](licenses/GPL-3.0.txt) |
| [Qt 6](https://www.qt.io/) | Bibliotecas da interface, distribuídas junto com o PySide6 | LGPL-3.0 | [LGPL-3.0.txt](licenses/LGPL-3.0.txt), [GPL-3.0.txt](licenses/GPL-3.0.txt) |
| [Python](https://www.python.org/) | Interpretador incluído no executável | PSF-2.0 | [Python-PSF-2.0.txt](licenses/Python-PSF-2.0.txt) |

## PySide6 e Qt (LGPL-3.0)

- O UnePDF usa o PySide6 e o Qt sob a LGPL-3.0, sem nenhuma modificação.
- As bibliotecas ficam como arquivos separados (`.dll` e `.pyd`) na pasta de instalação, ligadas
  dinamicamente. Você pode substituí-las por versões compatíveis, inclusive modificadas por você.
- A LGPL-3.0 é escrita como um complemento da GPL-3.0, por isso os dois textos estão incluídos.
- Código-fonte do PySide6: <https://code.qt.io/cgit/pyside/pyside-setup.git/>
- Código-fonte do Qt: <https://download.qt.io/official_releases/qt/>
- O Qt inclui componentes de terceiros com licenças próprias, listados em
  <https://doc.qt.io/qt-6/licenses-used-in-qt.html>.

## Executável

O executável para Windows é gerado com o [PyInstaller](https://pyinstaller.org/). O carregador do
PyInstaller é distribuído sob a GPL-2.0 com uma exceção que permite usá-lo em programas de qualquer
licença, então ele não muda a licença do UnePDF.
