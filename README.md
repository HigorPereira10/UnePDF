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

> O projeto está em desenvolvimento. A primeira ferramenta disponível é **Unir PDFs**, e outras vão
> chegar nas próximas versões.

## Unir PDFs

Escolha uma pasta (ou arraste os arquivos para a janela) e o UnePDF gera um único PDF:

- cada arquivo começa em uma página nova e mantém todas as suas páginas;
- a ordem segue o nome do arquivo, tratando números como números (`2.pdf` vem antes de `10.pdf`);
- cada arquivo vira um marcador no PDF final, e a maioria dos leitores de PDF já abre com a lista
  de marcadores visível;
- arquivos vazios, corrompidos ou protegidos por senha são pulados sem interromper o processo, e no
  final o app lista quais foram e o motivo;
- PDFs com senha só de permissão (os que abrem sem pedir senha) são aceitos normalmente;
- os arquivos originais nunca são alterados nem apagados;
- o resultado é gravado em uma subpasta (`UNIFICADO`, por padrão) e substitui o anterior de mesmo nome;
- se a gravação falhar no meio, o arquivo anterior continua intacto.

Na seleção por pasta entram só os PDFs que estão direto nela: subpastas e a pasta de saída ficam de
fora, para o resultado nunca entrar na próxima união.

### Nome do arquivo final

Por padrão o nome é `<nome da pasta> - UNIFICADO.pdf`. Nas configurações dá para ativar o perfil
**Notas fiscais**, que reconhece pastas organizadas por tipo de documento, empresa e competência:

```
C:\Notas\DANFE\0001-EMPRESA EXEMPLO LTDA\012026
    → UNIFICADO\DANFE - 0001-EMPRESA EXEMPLO LTDA - 012026.pdf
```

Os tipos reconhecidos são DANFE, DANFSE, DANFCE e DACTE, e a competência fica no formato `MMAAAA`.
Quando o nome da empresa tem uma barra (como em "S/S"), que o Windows transforma em várias pastas, as
partes são juntadas com hífen.

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
