@echo off
rem ShopNova app: double-click this file (or the Desktop shortcut made by scripts\make_desktop_shortcut.ps1).
rem 1. checks that Ollama answers (else: a message, and the window waits for a key);
rem 2. opens http://127.0.0.1:8501 in the browser as soon as the app answers;
rem 3. runs start_shopnova.ps1 (the same settings as before). Close this window or press Ctrl+C to stop the app.
title ShopNova
cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Invoke-RestMethod -Uri 'http://localhost:11434/api/tags' -TimeoutSec 5 | Out-Null; exit 0 } catch { exit 1 }"
if errorlevel 1 (
    echo.
    echo Start Ollama first, then run ShopNova again.
    echo.
    pause
    exit /b 1
)

rem In the background: wait up to 3 minutes for the app's health check, then open the browser once.
start "" /b powershell -NoProfile -ExecutionPolicy Bypass -Command "for ($i = 0; $i -lt 180; $i++) { try { Invoke-WebRequest -Uri 'http://127.0.0.1:8501/_stcore/health' -UseBasicParsing -TimeoutSec 2 | Out-Null; Start-Process 'http://127.0.0.1:8501'; exit } catch { Start-Sleep -Seconds 1 } }"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_shopnova.ps1"
if errorlevel 1 (
    echo.
    echo ShopNova stopped with an error (see the lines above^).
    pause
)
