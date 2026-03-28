@echo off
title JAMES — Autonomous System Orchestrator
color 0A

set PROJECT_ROOT=C:\Users\Administrator\antigravity-worspaces-1\antigravity-worspaces
set PYTHONPATH=%PROJECT_ROOT%
set VENV=%PROJECT_ROOT%\.venv\Scripts\python.exe

echo.
echo   ╔══════════════════════════════════════════════╗
echo   ║   JAMES — Initializing...                   ║
echo   ╚══════════════════════════════════════════════╝
echo.

:: Check venv exists
if not exist "%VENV%" (
    echo   [ERROR] Python venv not found at %VENV%
    echo   Run: python -m venv .venv
    pause
    exit /b 1
)

:: Launch browser after a short delay (gives Flask time to start)
start "" cmd /c "timeout /t 2 /nobreak >nul && start http://127.0.0.1:7700"

:: Start JAMES web dashboard (blocks until Ctrl+C)
echo   Starting JAMES Web Dashboard on http://127.0.0.1:7700
echo   Press Ctrl+C to stop.
echo.
"%VENV%" -m james web 7700

:: If we get here, server stopped
echo.
echo   JAMES stopped.
pause
