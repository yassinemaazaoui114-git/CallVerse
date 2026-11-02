# Reset the demo data (T26), so the demo flows can be shown again from the start.
#
#   powershell -ExecutionPolicy Bypass -File .\scripts\reset_demo.ps1
#
# It rebuilds BOTH company databases from their seed (ShopNova shopnova.db, Atlas atlas.db) and deletes the tickets
# database (callverse/data/callverse.db: every ticket, chat, approval). The same commands as in the README.
# Stop the demo first (close the API window): an open database file cannot be deleted.

$root = Split-Path -Parent $PSScriptRoot   # the project folder (this script is in scripts\)
Set-Location -Path $root

Write-Host "This deletes every demo ticket, chat and approval, and rebuilds the ShopNova and Atlas data."
$answer = Read-Host "Type YES to reset"
if ($answer -cne "YES") {
    Write-Host "Nothing changed."
    exit 0
}

. "$root\.venv\Scripts\Activate.ps1"
python -m callverse.data.seed
if ($LASTEXITCODE -ne 0) { Write-Host "ShopNova seed failed."; exit 1 }
python -m callverse.data.atlas.seed
if ($LASTEXITCODE -ne 0) { Write-Host "Atlas seed failed."; exit 1 }
$tickets = Join-Path $root "callverse\data\callverse.db"
if (Test-Path $tickets) {
    try {
        Remove-Item $tickets -ErrorAction Stop
    } catch {
        Write-Host "Could not delete callverse/data/callverse.db (is the API still running? close its window first)."
        exit 1
    }
}
Write-Host "Demo data reset: ShopNova and Atlas rebuilt, tickets deleted."
