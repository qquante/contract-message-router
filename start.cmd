@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo ERRO: ambiente virtual nao encontrado em .venv
    echo Execute: py -m venv .venv
    exit /b 1
)

".venv\Scripts\python.exe" -m token_forwarder
exit /b %ERRORLEVEL%

