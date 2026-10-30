@echo off
rem CallVerse Console: double-click this file (or the "CallVerse Console" Desktop shortcut made by
rem scripts\make_desktop_shortcut.ps1).
rem 1. opens http://127.0.0.1:8502 in the browser as soon as the Console answers;
rem 2. runs start_console.ps1. The Console loads no model (no Ollama needed). Close this window or press Ctrl+C to stop.
title CallVerse Console
cd /d "%~dp0"

rem In the background: wait up to 3 minutes for the Console's health check, then open the browser once.
start "" /b powershell -NoProfile -ExecutionPolicy Bypass -Command "for ($i = 0; $i -lt 180; $i++) { try { Invoke-WebRequest -Uri 'http://127.0.0.1:8502/_stcore/health' -UseBasicParsing -TimeoutSec 2 | Out-Null; Start-Process 'http://127.0.0.1:8502'; exit } catch { Start-Sleep -Seconds 1 } }"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_console.ps1"
if errorlevel 1 (
    echo.
    echo The Console stopped with an error (see the lines above^).
    pause
)
