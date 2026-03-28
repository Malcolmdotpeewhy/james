@echo off
REM JAMES Launcher — Sets up environment and runs JAMES CLI
REM Usage: james.bat <command> [args...]
REM   james.bat status
REM   james.bat run "!hostname"
REM   james.bat bootstrap
REM   james.bat layers

set PROJECT_ROOT=%~dp0
set PYTHONPATH=%PROJECT_ROOT%

if exist "%PROJECT_ROOT%.venv\Scripts\python.exe" (
    set PYTHON=%PROJECT_ROOT%.venv\Scripts\python.exe
) else (
    set PYTHON=python
)

"%PYTHON%" -m james %*
