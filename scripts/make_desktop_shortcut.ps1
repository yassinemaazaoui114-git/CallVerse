# Create a "ShopNova" shortcut on the Desktop that runs ShopNova.bat (the project root). Run it once yourself:
#
#   powershell -ExecutionPolicy Bypass -File .\scripts\make_desktop_shortcut.ps1
#
# Running it again replaces the shortcut (for example after moving the project folder). It changes nothing else.

$root = Split-Path -Parent $PSScriptRoot             # the project folder (this script is in scripts\)
$target = Join-Path $root "ShopNova.bat"
if (-not (Test-Path $target)) {
    Write-Host "ShopNova.bat not found in $root"
    exit 1
}

$desktop = [Environment]::GetFolderPath("Desktop")   # also right when the Desktop is in OneDrive
$link = Join-Path $desktop "ShopNova.lnk"

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($link)
$shortcut.TargetPath = $target
$shortcut.WorkingDirectory = $root
$shortcut.Description = "Start the ShopNova app (http://127.0.0.1:8501)"
$shortcut.IconLocation = "$env:SystemRoot\System32\shell32.dll,14"   # a standard Windows globe icon
$shortcut.Save()

Write-Host "Shortcut created: $link"
