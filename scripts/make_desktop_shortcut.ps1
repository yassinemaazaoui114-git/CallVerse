# Create two Desktop shortcuts (the project root's .bat files). Run it once yourself:
#   "ShopNova"          -> ShopNova.bat  (the company's app, http://127.0.0.1:8501)
#   "CallVerse Console" -> Console.bat   (the center's read-only screen, http://127.0.0.1:8502; T19)
#
#   powershell -ExecutionPolicy Bypass -File .\scripts\make_desktop_shortcut.ps1
#
# Running it again replaces the shortcuts (for example after moving the project folder). It changes nothing else.

$root = Split-Path -Parent $PSScriptRoot             # the project folder (this script is in scripts\)
$desktop = [Environment]::GetFolderPath("Desktop")   # also right when the Desktop is in OneDrive
$shell = New-Object -ComObject WScript.Shell

function New-Shortcut($name, $bat, $description, $icon) {
    $target = Join-Path $root $bat
    if (-not (Test-Path $target)) {
        Write-Host "$bat not found in $root"
        return
    }
    $link = Join-Path $desktop "$name.lnk"
    $shortcut = $shell.CreateShortcut($link)
    $shortcut.TargetPath = $target
    $shortcut.WorkingDirectory = $root
    $shortcut.Description = $description
    $shortcut.IconLocation = $icon
    $shortcut.Save()
    Write-Host "Shortcut created: $link"
}

# Standard Windows icons: a globe for ShopNova, a monitor for the Console.
New-Shortcut "ShopNova" "ShopNova.bat" "Start the ShopNova app (http://127.0.0.1:8501)" "$env:SystemRoot\System32\shell32.dll,14"
New-Shortcut "CallVerse Console" "Console.bat" "Start the CallVerse Console (http://127.0.0.1:8502)" "$env:SystemRoot\System32\shell32.dll,15"
