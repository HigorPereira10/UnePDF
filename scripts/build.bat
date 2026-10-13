@echo off
REM Gera o executavel em dist\UnePDF\UnePDF.exe (modo pasta, que abre mais rapido que o arquivo unico).
REM Uso: clique duas vezes neste arquivo ou rode "scripts\build.bat" na raiz do projeto.
REM      "scripts\build.bat --sem-pausa" nao espera uma tecla no final (para automacao).
setlocal

REM Garante que os comandos rodem a partir da raiz do projeto
cd /d "%~dp0.."

REM Usa sempre o ambiente virtual do projeto, para nao depender nem mexer no Python da maquina
if not exist ".venv\Scripts\python.exe" (
    echo Criando o ambiente virtual .venv...
    py -m venv .venv || goto erro
)
set PYTHON=.venv\Scripts\python.exe

echo Instalando dependencias...
%PYTHON% -m pip install --quiet --upgrade pip || goto erro
%PYTHON% -m pip install --quiet -r requirements-dev.txt || goto erro

echo Rodando os testes...
%PYTHON% -m pytest -q || goto erro

echo Gerando o executavel...
REM --paths . permite importar o pacote unepdf a partir do ponto de entrada unepdf\__main__.py
%PYTHON% -m PyInstaller --noconfirm --clean --onedir --windowed ^
    --name "UnePDF" ^
    --icon "assets\icone.ico" ^
    --paths . ^
    --add-data "assets;assets" ^
    --exclude-module tkinter ^
    --exclude-module pytest ^
    --exclude-module pytestqt ^
    --exclude-module PySide6.QtNetwork ^
    unepdf\__main__.py || goto erro

REM Remove o que o app nao usa: OpenGL por software (a interface e so de widgets)
REM e as traducoes do Qt em outros idiomas (o app carrega so a de portugues)
set QT=dist\UnePDF\_internal\PySide6
if exist "%QT%\opengl32sw.dll" del /q "%QT%\opengl32sw.dll"
for %%f in ("%QT%\translations\*.qm") do if /i not "%%~nxf"=="qtbase_pt_BR.qm" del /q "%%f"

REM As licencas ficam ao lado do executavel, visiveis para quem recebe o programa
copy /y LICENSE "dist\UnePDF\LICENSE.txt" >nul || goto erro
copy /y THIRD_PARTY_LICENSES.md "dist\UnePDF\" >nul || goto erro
REM Os textos vem dos proprios pacotes instalados, nas versoes que foram empacotadas
%PYTHON% tools\coletar_licencas.py "dist\UnePDF\licenses" || goto erro

echo.
echo Pronto: dist\UnePDF\UnePDF.exe
if /i not "%~1"=="--sem-pausa" pause
exit /b 0

:erro
echo.
echo Falha no build. Veja as mensagens acima.
if /i not "%~1"=="--sem-pausa" pause
exit /b 1
