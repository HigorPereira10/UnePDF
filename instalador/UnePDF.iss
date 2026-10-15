; Instalador do UnePDF (Inno Setup 6). Gerado pelo scripts\distribuir.bat, que passa a versão:
;   ISCC /DVersao=2.0.0 instalador\UnePDF.iss
; Instala só para o usuário atual, sem pedir administrador.

#ifndef Versao
  #define Versao "0.0.0"
#endif
#define Repositorio "https://github.com/HigorPereira10/UnePDF"

[Setup]
; Identificador fixo: é por ele que o Windows reconhece uma atualização da mesma instalação
AppId={{5681BA57-D48E-4613-9FFE-32EF7DD4F400}
AppName=UnePDF
AppVersion={#Versao}
AppVerName=UnePDF {#Versao}
AppPublisher=UnePDF
AppPublisherURL={#Repositorio}
AppSupportURL={#Repositorio}/issues
AppUpdatesURL={#Repositorio}/releases
VersionInfoVersion={#Versao}
DefaultDirName={autopf}\UnePDF
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist\instalador
OutputBaseFilename=UnePDF-{#Versao}-instalador
SetupIconFile=..\assets\icone.ico
UninstallDisplayIcon={app}\UnePDF.exe
UninstallDisplayName=UnePDF
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
; Com o app aberto, o instalador pede para fechar antes de continuar
AppMutex=UnePDF.Executando
CloseApplications=yes

[Languages]
Name: "pt"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Types]
Name: "completa"; Description: "Completa (recomendada)"
Name: "personalizada"; Description: "Personalizada"; Flags: iscustom

[Components]
Name: "app"; Description: "UnePDF"; Types: completa personalizada; Flags: fixed
Name: "ghostscript"; Description: "Ghostscript: conversão para PDF/A e compressão forte (licença AGPL)"; Types: completa
Name: "tesseract"; Description: "Tesseract: OCR, com português e inglês (licença Apache)"; Types: completa

[Tasks]
Name: "menuexplorer"; Description: "Adicionar ""Unir com UnePDF"" ao botão direito do Explorer"
Name: "atalho"; Description: "Criar atalho na área de trabalho"; Flags: unchecked

[InstallDelete]
; Na atualização, remove a versão anterior do programa para não sobrar biblioteca antiga
Type: filesandordirs; Name: "{app}\_internal"
; Componente desmarcado numa atualização: a pasta dele sai
Type: filesandordirs; Name: "{app}\ghostscript"; Components: not ghostscript
Type: filesandordirs; Name: "{app}\tesseract"; Components: not tesseract

[Files]
Source: "..\dist\UnePDF\*"; DestDir: "{app}"; Components: app; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\dist\externos\ghostscript\*"; DestDir: "{app}\ghostscript"; Components: ghostscript; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\dist\externos\tesseract\*"; DestDir: "{app}\tesseract"; Components: tesseract; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; A mesma identificação que o app usa (constantes.APP_ID): a janela aberta e o atalho fixado ficam juntos na barra
Name: "{autoprograms}\UnePDF"; Filename: "{app}\UnePDF.exe"; AppUserModelID: "UnePDF.UnePDF"
Name: "{autodesktop}\UnePDF"; Filename: "{app}\UnePDF.exe"; AppUserModelID: "UnePDF.UnePDF"; Tasks: atalho

[Registry]
; Mesmas chaves que as configurações do app usam para ligar e desligar o item (unepdf\utils\menu_contexto.py)
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\UnePDF.Unir"; Flags: uninsdeletekey; Tasks: menuexplorer
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\UnePDF.Unir"; ValueType: string; ValueName: "MUIVerb"; ValueData: "Unir com UnePDF"; Tasks: menuexplorer
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\UnePDF.Unir"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\UnePDF.exe"; Tasks: menuexplorer
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\UnePDF.Unir"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Tasks: menuexplorer
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\UnePDF.Unir\command"; ValueType: string; ValueName: ""; ValueData: """{app}\UnePDF.exe"" --unir ""%1"""; Tasks: menuexplorer
Root: HKA; Subkey: "Software\Classes\Directory\shell\UnePDF.Unir"; Flags: uninsdeletekey; Tasks: menuexplorer
Root: HKA; Subkey: "Software\Classes\Directory\shell\UnePDF.Unir"; ValueType: string; ValueName: "MUIVerb"; ValueData: "Unir PDFs com UnePDF"; Tasks: menuexplorer
Root: HKA; Subkey: "Software\Classes\Directory\shell\UnePDF.Unir"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\UnePDF.exe"; Tasks: menuexplorer
Root: HKA; Subkey: "Software\Classes\Directory\shell\UnePDF.Unir"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Tasks: menuexplorer
Root: HKA; Subkey: "Software\Classes\Directory\shell\UnePDF.Unir\command"; ValueType: string; ValueName: ""; ValueData: """{app}\UnePDF.exe"" --unir ""%1"""; Tasks: menuexplorer

[Run]
Filename: "{app}\UnePDF.exe"; Description: "Abrir o UnePDF"; Flags: nowait postinstall skipifsilent
