<p align="center">
  <img src="assets/logo.png" alt="Logo do UnePDF" width="120">
</p>

<h1 align="center">UnePDF</h1>

<p align="center">
  Ferramentas de PDF para Windows, <strong>100% locais</strong>: os seus arquivos nunca saem do computador.
</p>

---

O UnePDF nasceu para resolver um problema do dia a dia de escritório: juntar em um único PDF
dezenas ou centenas de documentos que chegam em arquivos separados, como notas fiscais. Ele funciona
sem internet, não envia nada para servidor nenhum e foi feito para aguentar uso diário com muitos
arquivos, inclusive em pastas de rede.

> O projeto está em desenvolvimento ativo.

## Ferramentas

| Categoria | Ferramentas |
|---|---|
| Organizar | Unir PDFs, Unir em lote, Dividir PDF, Organizar páginas (reordenar, girar, remover) e Extrair páginas |
| Converter | XML para PDF (DANFE, DANFCe, DACTE, DAMDFE, DANFSe e carta de correção), Imagens para PDF (sem perda de qualidade), PDF para imagens, PDF para texto e PDF para PDF/A (1b, 2b e 3b) |
| Editar | Marca d'água e Numerar páginas |
| Segurança | Proteger com senha (AES de 256 bits) e Remover senha |
| Otimizar | Comprimir PDF |

## Unir PDFs

Escolha uma pasta (ou arraste os arquivos para a janela) e o UnePDF gera um único PDF:

- cada arquivo começa em uma página nova e mantém todas as suas páginas;
- a ordem segue o nome do arquivo, tratando números como números (`2.pdf` vem antes de `10.pdf`);
  também dá para ordenar pela data de modificação ou arrastar os arquivos na lista;
- cada arquivo vira um marcador no PDF final, e a maioria dos leitores de PDF já abre com a lista
  de marcadores visível;
- arquivos vazios, corrompidos ou protegidos por senha são pulados sem interromper o processo, e no
  final o app lista quais foram e o motivo;
- PDFs com senha só de permissão (os que abrem sem pedir senha) são aceitos normalmente;
- os arquivos originais nunca são alterados nem apagados;
- o resultado é gravado em uma subpasta (`UnePDF`, por padrão) e substitui o anterior de mesmo nome;
- se a gravação falhar no meio, o arquivo anterior continua intacto.

Opções:

- **pular arquivos repetidos**: arquivos com o mesmo conteúdo de outro já incluído ficam de fora,
  mesmo com nomes diferentes (como `nota.pdf` e `nota (1).pdf`);
- **capa com índice**: o PDF começa com uma página que lista os arquivos e a página onde cada um
  começa, com link para ela.

Na seleção por pasta entram só os PDFs que estão direto nela: subpastas e a pasta de saída ficam de
fora, para o resultado nunca entrar na próxima união.

### Unir em lote

Para muitas pastas de uma vez: escolha uma pasta raiz e o UnePDF gera um unificado para cada pasta
com PDFs que estiver dentro dela, em qualquer nível. Antes de começar dá para desmarcar as pastas que
não devem entrar. Uma pasta com problema não interrompe as outras, e no final o relatório mostra o
resultado de cada uma (e pode ser salvo em um arquivo de texto).

### Nome do arquivo final

Por padrão o nome é `<nome da pasta> - UNIFICADO.pdf`. Nas configurações dá para ativar o perfil
**Notas fiscais**, que reconhece pastas organizadas por tipo de documento, empresa e competência:

```
C:\Notas\DANFE\0001-EMPRESA EXEMPLO LTDA\012026
    → UnePDF\DANFE - 0001-EMPRESA EXEMPLO LTDA - 012026.pdf
```

Os tipos reconhecidos são DANFE, DANFSE, DANFCE e DACTE, e a competência fica no formato `MMAAAA`.
Quando o nome da empresa tem uma barra (como em "S/S"), que o Windows transforma em várias pastas, as
partes são juntadas com hífen.

## XML para PDF

Gera o documento auxiliar de cada XML no leiaute oficial: DANFE (NF-e), DANFCe (NFC-e), DACTE (CT-e),
DAMDFE (MDF-e), DANFSe (NFS-e do padrão nacional) e DACCe (carta de correção da NF-e). O tipo de cada
arquivo é reconhecido pelo conteúdo, então uma pasta pode ter tipos misturados.

- cada PDF recebe o nome do documento, como `DANFE 1234 - EMPRESA EXEMPLO LTDA (XML).pdf`;
- se a seleção tiver o XML do evento de cancelamento de uma nota, o PDF dela sai marcado como
  CANCELADA;
- a carta de correção usa o nome e o endereço do emitente da NF-e, quando o XML da nota está junto;
- opcionalmente, todos os documentos também são juntados em um único PDF, com um marcador por documento;
- dá para ajustar a fonte, as casas decimais, a logo do emitente, a posição do canhoto e outros
  detalhes, e as escolhas ficam salvas;
- XMLs que não geram PDF (NFS-e no padrão próprio de uma prefeitura, resumos de nota, arquivos
  corrompidos) aparecem na lista final com o motivo.

O desenho dos documentos é feito pela biblioteca
[BrazilFiscalReport](https://github.com/Engenere/BrazilFiscalReport).

## Instalação

Ainda não há uma versão publicada para download. Por enquanto, o UnePDF pode ser usado a partir do
código-fonte, como explicado abaixo.

## Rodando pelo código-fonte

Requer Windows e [Python](https://www.python.org/downloads/) 3.11 ou superior.

```bat
git clone https://github.com/HigorPereira10/UnePDF.git
cd UnePDF
py -m venv .venv
.venv\Scripts\activate
py -m pip install -r requirements-dev.txt
py -m unepdf
```

Para rodar os testes:

```bat
py -m pytest
```

## Ghostscript (opcional)

A conversão para PDF/A e a compressão forte usam o [Ghostscript](https://ghostscript.com/), um programa
gratuito e separado do UnePDF. Sem ele, todas as outras ferramentas funcionam normalmente; as que
dependem dele aparecem com a explicação do que falta.

Para usar pelo código-fonte, instale o Ghostscript para Windows de 64 bits a partir da
[página de downloads](https://ghostscript.com/releases/gsdnld.html), com as opções padrão. O UnePDF
encontra a instalação sozinho, sem nenhuma configuração.

## Onde ficam os dados do app

| O quê | Onde |
|---|---|
| Configurações | `%APPDATA%\UnePDF\config.json` |
| Registro de atividades (log) | `%LOCALAPPDATA%\UnePDF\logs` |

Se o arquivo de configurações for apagado ou estiver corrompido, o app volta para os valores padrão.

## Estrutura do projeto

```
unepdf/
  core/    regras de cada ferramenta, sem nenhuma dependência da interface
  ui/      interface gráfica em PySide6
  utils/   integração com o Windows, caminhos e logs
tests/     testes automatizados (os PDFs de teste são gerados na hora)
tools/     scripts de apoio, como a geração dos ícones a partir do SVG
assets/    logo e ícones
```

## Contribuindo

Encontrou um problema ou tem uma sugestão? Abra uma
[issue](https://github.com/HigorPereira10/UnePDF/issues). Se o app mostrar uma mensagem de erro, o
botão "Copiar detalhes do erro" copia as informações técnicas que ajudam a investigar.

## Licença

O UnePDF é software livre, distribuído sob a [licença MIT](LICENSE). As bibliotecas usadas e as suas
licenças estão em [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).
