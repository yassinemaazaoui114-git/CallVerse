# Start the CallVerse demo on this PC (see docs/DEMO_RUNBOOK.md).
#
#   .\start_demo.ps1           agents use the normal chain (Groq gpt-oss-120b -> gpt-oss-20b -> Gemini Flash)
#   .\start_demo.ps1 -Gemini   agents use ONLY gemini-3.5-flash (if Groq is out of quota)
#
# Then open http://127.0.0.1:8000/demo in the browser. Stop with Ctrl+C.
# The settings below live only in this PowerShell window: config.yaml is not changed. No keys here (.env).

param(
    [switch]$Gemini
)

Set-Location -Path $PSScriptRoot
. "$PSScriptRoot\.venv\Scripts\Activate.ps1"

$env:CALLVERSE_DEMO_ENABLED = "1"
if ($Gemini) {
    $env:CALLVERSE_FORCE_AGENTS_MODEL = "gemini-3.5-flash"
    Write-Host "Agents model forced to gemini-3.5-flash"
} else {
    Remove-Item Env:\CALLVERSE_FORCE_AGENTS_MODEL -ErrorAction SilentlyContinue
}

Write-Host "Demo page: http://127.0.0.1:8000/demo"
python -m scripts.run_platform_server
