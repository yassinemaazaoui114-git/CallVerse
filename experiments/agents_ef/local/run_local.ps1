<#
CallVerse Agents E & F: local reproduction on the RTX 4050 laptop (Windows 11, PowerShell 5.1 or 7).

What it does (each step prints what it is doing; nothing is pushed anywhere):
  1. Checks the GPU (nvidia-smi) and Python (3.10-3.12).
  2. Creates/reuses an isolated venv (default: <repo>\.venv-agents-ef). Installs the CUDA 12.1 build of
     PyTorch ONLY if the venv has no CUDA-enabled torch yet (~2.5 GB download, once), plus small libraries.
  3. Runs the research tests (CPU).
  4. Measures real latency / peak RAM / peak VRAM of the Agent E networks and the Agent F encoders
     -> experiments\agents_ef\results\local_measure\measure_v2_cuda.json   (share this file)
  5. -TrainF: runs pipelines/agent_f_pipeline.py: downloads the hash-checked EN/FR reviews (~5 MB) + Olist (~45 MB),
     rebuilds the subsets, fine-tunes the chosen Agent F model on the GPU (3 seeds, fp16), writes manifest.json.
  6. -TrainE: trains the Intake-aware Dueling Double DQN (CPU is enough: 7k parameters), 3 seeds.
Data and checkpoints go to $DataDir / $CkptDir (outside the repository). Nothing is committed.

Usage, from the repository root:
  powershell -ExecutionPolicy Bypass -File experiments\agents_ef\local\run_local.ps1            # steps 1-4
  powershell -ExecutionPolicy Bypass -File experiments\agents_ef\local\run_local.ps1 -TrainF -TrainE
#>
param(
    [string]$Venv = (Join-Path (Get-Location) ".venv-agents-ef"),
    [string]$DataDir = (Join-Path $(if ($env:LOCALAPPDATA) { $env:LOCALAPPDATA } else { $HOME }) "callverse_agents_ef\data"),
    [string]$CkptDir = (Join-Path $(if ($env:LOCALAPPDATA) { $env:LOCALAPPDATA } else { $HOME }) "callverse_agents_ef\checkpoints"),
    [switch]$SkipInstall, [switch]$SkipTests, [switch]$TrainF, [switch]$TrainE
)
$ErrorActionPreference = "Stop"
$Exp = Join-Path (Get-Location) "experiments\agents_ef"
if (-not (Test-Path $Exp)) { throw "Run this from the CallVerse repository root (experiments\agents_ef not found)." }

Write-Host "== 1. GPU and Python"
try { nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv } catch { Write-Host "nvidia-smi not found: CPU only." }
$py = if (Get-Command py -ErrorAction SilentlyContinue) { "py -3" } else { "python" }
Invoke-Expression "$py --version"

Write-Host "== 2. Virtual environment: $Venv"
if (-not (Test-Path $Venv)) { Invoke-Expression "$py -m venv `"$Venv`"" }
$P = Join-Path $Venv "Scripts\python.exe"
if (-not (Test-Path $P)) { $P = Join-Path $Venv "bin/python" }      # (non-Windows test runs)
if (-not $SkipInstall) {
    $hasCuda = & $P -c "import torch,sys; sys.stdout.write(str(torch.cuda.is_available()))" 2>$null
    if ($hasCuda -ne "True") {
        Write-Host "Installing PyTorch (CUDA 12.1 build, ~2.5 GB, one time)..."
        & $P -m pip install --upgrade pip
        & $P -m pip install torch --index-url https://download.pytorch.org/whl/cu121
    }
    & $P -m pip install "transformers>=4.44" "sentence-transformers>=3.0" scikit-learn scipy pyyaml psutil matplotlib pytest huggingface_hub
}
& $P -c "import torch; print('torch', torch.__version__, 'cuda', torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else '')"

Push-Location $Exp
try {
    if (-not $SkipTests) { Write-Host "== 3. Research tests"; & $P -m pytest -q tests }
    Write-Host "== 4. Hardware measurements (GPU if available)"
    & $P -m bench.measure_local --out results\local_measure
    if ($TrainF) {
        Write-Host "== 5. Agent F pipeline on the GPU (hash-checked data, e5-small trimmed, 3 seeds, fp16)"
        $work = Join-Path $DataDir "agent_f_pipeline"
        $dev = (& $P -c "import torch,sys; sys.stdout.write('cuda' if torch.cuda.is_available() else 'cpu')")
        $extra = @(); if ($dev -eq "cuda") { $extra = @("--fp16") }
        & $P -m pipelines.agent_f_pipeline --work $work --device $dev --threads 4 @extra
        Write-Host "Checkpoint + manifest.json are in $work (outside git). Share manifest.json (no text, no weights)."
    }
    if ($TrainE) {
        Write-Host "== 6. Agent E (Intake-aware Dueling Double DQN), CPU, 3 seeds"
        foreach ($s in 0, 1, 2) { & $P -m rl.train --algo dueling_double_dqn --env intake --seed $s --out (Join-Path $CkptDir "agent_e") }
    }
} finally { Pop-Location }
Write-Host "Done. Share experiments\agents_ef\results\local_measure\measure_v2_*.json (no data, no weights inside)."
