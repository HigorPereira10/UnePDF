# Contribuindo com o UnePDF

Obrigado pelo interesse! Problemas, sugestões e código são bem-vindos.

## Relatando um problema

Abra uma [issue](https://github.com/HigorPereira10/UnePDF/issues/new/choose) com:

- o que você fez e o que esperava que acontecesse;
- a versão do UnePDF (aparece no rodapé da barra lateral);
- se apareceu uma mensagem de erro, o texto do botão "Copiar detalhes do erro".

**Nunca anexe documentos reais** (notas fiscais, contratos, certificados). Se o problema depende de
um arquivo, tente reproduzir com um arquivo de exemplo, sem dados de clientes.

## Contribuindo com código

1. Prepare o ambiente como explicado em "Para desenvolvedores", no [README](README.md).
2. Crie um branch a partir da `main` e faça as mudanças.
3. Rode `py -m pytest` e confira que tudo passa. Os testes também rodam sozinhos no pull request.
4. Abra o pull request explicando o que mudou e por quê.

### Como o código é organizado

- `unepdf/core` tem as regras de cada ferramenta e **não pode depender da interface** (um teste
  confere isso). A interface, em `unepdf/ui`, só usa o que o core oferece.
- Código, comentários, mensagens e testes são em português.
- Toda ferramenta nova precisa de testes, inclusive dos casos de erro (arquivo vazio, corrompido, com
  senha, destino aberto em outro programa).
- Os testes geram na hora os arquivos de que precisam (PDFs, XMLs, certificados). Não acrescente
  arquivos reais ao repositório.
- Arquivos são sempre gravados de forma segura (num arquivo temporário, trocado pelo definitivo no
  fim), e os originais nunca são alterados.

### Licenças

O projeto é MIT. Bibliotecas novas precisam de licença compatível. Para PDFs, use pypdf, pikepdf ou
pypdfium2 (PyMuPDF não, por ser AGPL). Programas externos (como o Ghostscript) são chamados como
programas separados e nunca incorporados ao código.
