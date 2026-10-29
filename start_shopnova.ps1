# Start the ShopNova app (T17, T18: app.py + admin pages) on this PC: http://127.0.0.1:8501 (localhost only). Stop with Ctrl+C.
#
#   .\start_shopnova.ps1
#
# Before the first start: create the demo logins once with  python -m scripts.create_demo_accounts  (README).
# Models (T16): Intake + Agent A + the SLM run locally (Ollama), Agent B stays on Groq.
# The settings below live only in this PowerShell window: config.yaml is not changed. No keys here (.env).

Set-Location -Path $PSScriptRoot
. "$PSScriptRoot\.venv\Scripts\Activate.ps1"

# 1. Ollama must answer (local models of Intake's fallback, Agent A and the SLM).
try {
    Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -TimeoutSec 5 | Out-Null
    Write-Host "Ollama answers."
} catch {
    Write-Host "Ollama does not answer on http://localhost:11434. Start Ollama first, then run this script again."
    exit 1
}

# 2. Intake + Agent A local, Agent B on Groq (its own model list).
$env:CALLVERSE_AGENTS_SET = "local"
Remove-Item Env:\CALLVERSE_AGENT_B_SET -ErrorAction SilentlyContinue
# T18: the real Layer 3 queue: refunds above 300 TND wait for the ShopNova admin (Refund approvals page).
$env:CALLVERSE_LAYER3_MODE = "queue"

# 3. The app. Started from apps/shopnova so Streamlit reads apps/shopnova/.streamlit/config.toml (the style).
Write-Host "ShopNova app: http://127.0.0.1:8501"
Set-Location -Path "$PSScriptRoot\apps\shopnova"
try {
    streamlit run app.py --server.address 127.0.0.1 --server.port 8501
} finally {
    Set-Location -Path $PSScriptRoot
}
