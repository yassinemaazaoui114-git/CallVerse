# Create (or re-create) the two Desktop shortcuts of the web UI demo (T28). Run it again after moving the folder:
#   "CallVerse Demo"  -> Demo.bat  (starts Ollama if needed, the API and the web UI, then opens the login page)
#   "CallVerse Reset" -> Reset.bat (rebuilds the demo data; it asks you to type YES first)
#
#   powershell -ExecutionPolicy Bypass -File .\scripts\make_shortcuts.ps1
#
# It changes nothing else. The older Streamlit shortcuts are made by scripts\make_desktop_shortcut.ps1.

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

# Standard Windows icons: a play arrow for the Demo, a recycle bin for the Reset.
New-Shortcut "CallVerse Demo" "Demo.bat" "Start the CallVerse demo (Ollama, API, web UI) and open the login page" "$env:SystemRoot\System32\shell32.dll,137"
New-Shortcut "CallVerse Reset" "Reset.bat" "Reset the CallVerse demo data (asks to type YES)" "$env:SystemRoot\System32\shell32.dll,31"
