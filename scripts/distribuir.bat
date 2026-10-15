@echo off
REM Gera o instalador e o .zip portatil em dist\ (com os testes, como o build.bat).
REM Precisa do Ghostscript e do Tesseract (com portugues) instalados, e do Inno Setup 6.
REM Uso: scripts\distribuir.bat   (ou "scripts\distribuir.bat --sem-pausa" para automacao)
setlocal
cd /d "%~dp0.."
set PYTHON=.venv\Scripts\python.exe

call scripts\build.bat --sem-pausa || goto erro

echo Copiando Ghostscript e Tesseract...
%PYTHON% tools\coletar_externos.py dist\externos || goto erro

echo Montando o .zip portatil...
%PYTHON% tools\empacotar_portatil.py || goto erro

REM O Inno Setup pode estar instalado para todos os usuarios ou so para o atual
set ISCC=
for %%c in ("%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" "%ProgramFiles%\Inno Setup 6\ISCC.exe" "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe") do if exist %%c set ISCC=%%c
if not defined ISCC (
    echo Inno Setup 6 nao encontrado. Instale pelo site jrsoftware.org/isdl.php e rode de novo.
    goto erro
)
for /f %%v in ('%PYTHON% -c "import unepdf; print(unepdf.__version__)"') do set VERSAO=%%v
echo Gerando o instalador da versao %VERSAO%...
%ISCC% /Q /DVersao=%VERSAO% instalador\UnePDF.iss || goto erro

echo.
echo Pronto: dist\instalador\UnePDF-%VERSAO%-instalador.exe e dist\UnePDF-%VERSAO%-portatil.zip
if /i not "%~1"=="--sem-pausa" pause
exit /b 0

:erro
echo.
echo Falha ao gerar a distribuicao. Veja as mensagens acima.
if /i not "%~1"=="--sem-pausa" pause
exit /b 1
