# Start the CallVerse Console (T19) on this PC: http://127.0.0.1:8502 (localhost only). Stop with Ctrl+C.
#
#   .\start_console.ps1
#
# The Console is the center's read-only screen for the CallVerse supervisor (login: the "supervisor" account made
# by  python -m scripts.create_demo_accounts). It loads NO model and needs no Ollama: it only reads
# callverse/data/callverse.db (the tickets) and the company's data, in read-only mode. No keys here (.env).

Set-Location -Path $PSScriptRoot
. "$PSScriptRoot\.venv\Scripts\Activate.ps1"

# Started from apps/console so Streamlit reads apps/console/.streamlit/config.toml (the style).
Write-Host "CallVerse Console: http://127.0.0.1:8502"
Set-Location -Path "$PSScriptRoot\apps\console"
try {
    streamlit run app.py --server.address 127.0.0.1 --server.port 8502
} finally {
    Set-Location -Path $PSScriptRoot
}
