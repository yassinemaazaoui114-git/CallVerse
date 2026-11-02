@echo off
rem Reset the CallVerse demo data (T28): double-click this file (or the "CallVerse Reset" Desktop shortcut made by
rem scripts\make_shortcuts.ps1). It runs scripts\reset_demo.ps1, which asks you to type YES first.
rem Close the demo's API window before, otherwise the tickets database cannot be deleted.
title CallVerse Reset
cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\reset_demo.ps1"
echo.
pause
