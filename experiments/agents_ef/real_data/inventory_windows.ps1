<#
CallVerse data inventory: READ-ONLY on the data folder.
It never modifies, moves or copies data files.
It writes ONE report file (default: Documents\callverse_inventory.json), which contains no raw customer text.

Per file:
- relative path, size, last write time, SHA256;
- CSV/TSV: header, true record count (quote-aware parser, so multi-line fields are counted once),
  and per column: non-empty count, distinct count (capped);
- value counts ONLY for short categorical columns (<= 30 distinct values, average length <= 30 characters).
  That is where label columns show up: intent, language, rating, review_score...
- JSON: top-level keys and list lengths, plus scalar values of small files (e.g. migration_progress.json);
- JSONL: line count and the keys of the first record.
Free-text and personal columns (text, message, comment, name, email, phone, address, ...) are never printed.

Usage (PowerShell 5.1 or 7):
  powershell -ExecutionPolicy Bypass -File inventory_windows.ps1 `
      -Root "C:\Users\semah\Documents\ChatGPT\data collection\callverse-data"
#>
param(
    [string]$Root = "C:\Users\semah\Documents\ChatGPT\data collection\callverse-data",
    [string]$Out = (Join-Path ([Environment]::GetFolderPath("MyDocuments")) "callverse_inventory.json"),
    [int]$MaxHashMB = 2048
)
$ErrorActionPreference = "Continue"
Add-Type -AssemblyName Microsoft.VisualBasic
$piiOrText = '(?i)(text|message|msg|body|comment|content|utterance|transcript|review_comment|title|name|email|mail|phone|tel|address|street|zip|postal|customer_id|user_id|ip)'

function Inspect-Csv([string]$path, [string]$delim) {
    $p = New-Object Microsoft.VisualBasic.FileIO.TextFieldParser($path, [System.Text.Encoding]::UTF8)
    $p.TextFieldType = "Delimited"; $p.SetDelimiters($delim); $p.HasFieldsEnclosedInQuotes = $true
    $header = $p.ReadFields()
    $n = 0; $bad = 0
    $nonEmpty = @{}; $distinct = @{}; $lenSum = @{}
    foreach ($h in $header) { $nonEmpty[$h] = 0; $distinct[$h] = @{}; $lenSum[$h] = 0 }
    while (-not $p.EndOfData) {
        try { $f = $p.ReadFields() } catch { $bad++; continue }
        $n++
        if ($f.Count -ne $header.Count) { $bad++ }
        for ($i = 0; $i -lt [Math]::Min($f.Count, $header.Count); $i++) {
            $h = $header[$i]; $v = $f[$i]
            if ($v -ne "") {
                $nonEmpty[$h]++; $lenSum[$h] += $v.Length
                if ($distinct[$h].Count -le 50) { $distinct[$h][$v] = 1 + [int]$distinct[$h][$v] }
            }
        }
    }
    $p.Close()
    $cols = foreach ($h in $header) {
        $d = $distinct[$h].Count
        $avg = if ($nonEmpty[$h]) { [Math]::Round($lenSum[$h] / $nonEmpty[$h], 1) } else { 0 }
        $c = [ordered]@{ column = $h; non_empty = $nonEmpty[$h]; distinct = $(if ($d -gt 50) { ">50" } else { $d }); avg_len = $avg }
        if ($d -le 30 -and $avg -le 30 -and $h -notmatch $piiOrText) { $c.value_counts = $distinct[$h] }
        $c
    }
    [ordered]@{ header = $header; records = $n; malformed_rows = $bad; columns = @($cols) }
}

function Inspect-Json([string]$path, [long]$size) {
    $j = Get-Content -Raw -Encoding UTF8 $path | ConvertFrom-Json
    $info = [ordered]@{ type = $j.GetType().Name }
    if ($j -is [System.Array]) {
        $info.length = $j.Count
        if ($j.Count) { $info.first_keys = @($j[0].PSObject.Properties.Name) }
    } else {
        $keys = [ordered]@{}
        foreach ($pr in $j.PSObject.Properties) {
            $v = $pr.Value
            if ($v -is [System.Array]) { $keys[$pr.Name] = "list[$($v.Count)]" }
            elseif ($v -is [pscustomobject]) { $keys[$pr.Name] = "object{" + (@($v.PSObject.Properties.Name) -join ",") + "}" }
            elseif ($size -lt 200KB -and $pr.Name -notmatch $piiOrText) { $keys[$pr.Name] = $v }
            else { $keys[$pr.Name] = "(scalar)" }
        }
        $info.keys = $keys
    }
    $info
}

if (-not (Test-Path -LiteralPath $Root)) { Write-Host "NOT FOUND: $Root"; exit 1 }
$files = Get-ChildItem -LiteralPath $Root -Recurse -File
Write-Host "Root: $Root  ($($files.Count) files)"
$report = [ordered]@{ root = $Root; scanned_at = (Get-Date).ToString("s"); files = @() }
foreach ($f in $files) {
    $rel = $f.FullName.Substring($Root.Length).TrimStart('\')
    $e = [ordered]@{ path = $rel; bytes = $f.Length; modified = $f.LastWriteTime.ToString("s") }
    if ($f.Length -le $MaxHashMB * 1MB) { $e.sha256 = (Get-FileHash -LiteralPath $f.FullName -Algorithm SHA256).Hash }
    try {
        switch -Regex ($f.Extension.ToLower()) {
            '^\.csv$'           { $e.csv = Inspect-Csv $f.FullName "," }
            '^\.tsv$'           { $e.csv = Inspect-Csv $f.FullName "`t" }
            '^\.json$'          { $e.json = Inspect-Json $f.FullName $f.Length }
            '^\.(jsonl|ndjson)$' {
                $first = Get-Content -LiteralPath $f.FullName -TotalCount 1 -Encoding UTF8
                $e.jsonl = [ordered]@{ lines = ([System.IO.File]::ReadLines($f.FullName) | Measure-Object).Count
                                      first_keys = @(($first | ConvertFrom-Json).PSObject.Properties.Name) }
            }
        }
    } catch { $e.error = $_.Exception.Message }
    $rows = if ($e.csv) { " rows=$($e.csv.records) cols=$($e.csv.header.Count)" } elseif ($e.jsonl) { " lines=$($e.jsonl.lines)" } else { "" }
    Write-Host ("{0,10:N0} B  {1}{2}" -f $f.Length, $rel, $rows)
    $report.files += $e
}
$report | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 -LiteralPath $Out
Write-Host "`nReport written to: $Out  (no raw text; share this file)"
