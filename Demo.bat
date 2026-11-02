@echo off
rem CallVerse demo with the new web UI (T26): double-click this file (or the "CallVerse Demo" Desktop shortcut made by
rem scripts\make_desktop_shortcut.ps1). It runs scripts\start_demo.ps1:
rem 1. checks Ollama, the local models and the demo logins (else: a message, and the window waits for a key);
rem 2. opens two windows: the API (http://127.0.0.1:8610) and the web UI (http://127.0.0.1:5173);
rem 3. opens the browser. Close the two windows to stop. Clean data again: scripts\reset_demo.ps1.
title CallVerse Demo
cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_demo.ps1"
if errorlevel 1 (
    echo.
    echo The demo did not start (see the lines above^).
    pause
)
