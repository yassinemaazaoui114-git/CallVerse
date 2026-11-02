# One-click start of the CallVerse demo with the new web UI (T26). Double-click Demo.bat (or its Desktop shortcut).
#
#   powershell -ExecutionPolicy Bypass -File .\scripts\start_demo.ps1
#
# What it does:
#   1. checks that Ollama answers and that the local models exist (callverse-m2-v3 for agents A, B, C;
#      qwen2.5:1.5b for the reply writer);
#   2. checks that the demo logins exist (config/accounts.yaml);
#   3. opens two windows: the API (http://127.0.0.1:8610) and the web UI (http://127.0.0.1:5173);
#   4. opens the browser on the web UI.
# Close the two windows to stop the demo. To start again from clean data: scripts\reset_demo.ps1.
# The settings live only in these windows: config.yaml is not changed. No keys here (Groq / Gemini keys stay in .env).
# Not set on purpose: CALLVERSE_WEBUI_* (they point the API at temporary test files) and FAKE_CHAT (no model).

$root = Split-Path -Parent $PSScriptRoot   # the project folder (this script is in scripts\)
Set-Location -Path $root

# 1. Ollama and the local models. If Ollama is not running, start it (T28: no typed command needed).
function Get-OllamaTags {
    try { return Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -TimeoutSec 3 } catch { return $null }
}
$tags = Get-OllamaTags
if ($null -eq $tags) {
    # The usual install places of Ollama on Windows; else the "ollama" command on the PATH.
    $ollamaExe = @("$env:LOCALAPPDATA\Programs\Ollama\ollama.exe", "$env:ProgramFiles\Ollama\ollama.exe") |
        Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $ollamaExe) {
        $cmd = Get-Command ollama -ErrorAction SilentlyContinue
        if ($cmd) { $ollamaExe = $cmd.Source }
    }
    if (-not $ollamaExe) {
        Write-Host "Ollama is not installed (ollama.exe not found). Install it from https://ollama.com, then start again."
        exit 1
    }
    Write-Host "Starting Ollama ($ollamaExe serve)..."
    Start-Process -FilePath $ollamaExe -ArgumentList "serve" -WindowStyle Minimized
    for ($i = 0; $i -lt 60 -and $null -eq $tags; $i++) { Start-Sleep -Seconds 1; $tags = Get-OllamaTags }
    if ($null -eq $tags) {
        Write-Host "Ollama did not answer within 60 seconds on http://localhost:11434."
        exit 1
    }
}
Write-Host "Ollama answers."
$names = @($tags.models | ForEach-Object { $_.name })
foreach ($model in @("callverse-m2-v3", "qwen2.5:1.5b")) {
    if (-not ($names | Where-Object { $_ -eq $model -or $_ -eq "$model`:latest" })) {
        Write-Host "The Ollama model '$model' is missing."
        if ($model -eq "callverse-m2-v3") { Write-Host "Make it once with: ollama create callverse-m2-v3 -f models/m2/Modelfile_v3" }
        else { Write-Host "Get it once with: ollama pull $model" }
        exit 1
    }
}
Write-Host "Models found: callverse-m2-v3, qwen2.5:1.5b."

# 2. The demo logins (passwords are set by Yassine; this script never creates or prints one).
if (-not (Test-Path (Join-Path $root "config\accounts.yaml"))) {
    Write-Host "config/accounts.yaml is missing: run scripts/create_demo_accounts.py first (python -m scripts.create_demo_accounts)."
    exit 1
}

# 3. The frontend packages (only the first time).
if (-not (Test-Path (Join-Path $root "webui\frontend\node_modules"))) {
    Write-Host "Installing the web UI packages (first start only)..."
    npm --prefix webui/frontend install
    if ($LASTEXITCODE -ne 0) { Write-Host "npm install failed (is Node.js installed?)."; exit 1 }
}

# 4. The two servers, each in its own window. Same model settings as the Streamlit apps:
#    Intake fallback local (CALLVERSE_AGENTS_SET=local); A, B, C use config.yaml (callverse-m2-v3 first);
#    Layer 3 in queue mode: big refunds and compensations wait for the admin's approval.
Remove-Item Env:\CALLVERSE_WEBUI_ACCOUNTS, Env:\CALLVERSE_WEBUI_TICKETS_DB, Env:\CALLVERSE_WEBUI_SHOPNOVA_DB, `
    Env:\CALLVERSE_WEBUI_ATLAS_DB, Env:\CALLVERSE_WEBUI_FAKE_CHAT -ErrorAction SilentlyContinue
$apiCommand = "Set-Location '$root'; " +
    ". '$root\.venv\Scripts\Activate.ps1'; " +
    "`$env:CALLVERSE_AGENTS_SET = 'local'; " +
    "`$env:CALLVERSE_LAYER3_MODE = 'queue'; " +
    "Write-Host 'CallVerse API: http://127.0.0.1:8610 (close this window to stop)'; " +
    "python -m webui.api.run"
Start-Process powershell -ArgumentList "-NoExit", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $apiCommand

$uiCommand = "Set-Location '$root'; " +
    "Write-Host 'CallVerse web UI: http://127.0.0.1:5173 (close this window to stop)'; " +
    "npm --prefix webui/frontend run dev"
Start-Process powershell -ArgumentList "-NoExit", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $uiCommand

# 5. Open the browser as soon as the web UI and the API answer (max 2 minutes).
for ($i = 0; $i -lt 120; $i++) {
    try {
        Invoke-WebRequest -Uri "http://127.0.0.1:5173" -UseBasicParsing -TimeoutSec 2 | Out-Null
        Invoke-WebRequest -Uri "http://127.0.0.1:8610/api/docs" -UseBasicParsing -TimeoutSec 2 | Out-Null
        Start-Process "http://127.0.0.1:5173"
        Write-Host "Demo started: http://127.0.0.1:5173"
        exit 0
    } catch { Start-Sleep -Seconds 1 }
}
Write-Host "The web UI or the API did not answer within 2 minutes: look at the two windows for an error."
exit 1
