<#
.SYNOPSIS
    ARCHIVED project_tct workstation runbook; unrelated to Daedalus environments.

    Supervised runbook to recreate TCT_app\.venv with a REAL CPython 3.10
    (not the Microsoft Store alias). DRY-RUN BY DEFAULT: prints the exact
    plan and changes nothing. Pass -Execute to actually do it.

.DESCRIPTION
    ROOT CAUSE (diagnosed 2026-07-13): TCT_app\.venv\pyvenv.cfg has
        home = C:\Users\...\AppData\Local\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.10_...
    i.e. the venv was created from the Windows Store Python. Store installs
    live behind app-execution-alias reparse points that a sandboxed process
    (Codex CLI sandbox, restricted runners) cannot launch, and the sandbox has
    no alternate python. Any lane that tries to use this venv from a sandbox
    fails. Fix: recreate the venv from a normal (non-Store) 64-bit CPython
    3.10 install.

    WHY 64-bit CPython 3.10 exactly: the vendored FLIR PySpin 3.2 wheel is
    cp310/win_amd64 and built against the numpy 1.x C-ABI (numpy is pinned <2
    in requirements.txt -- do not bump it). Simulation-only work has no such
    constraint, but the venv should stay real-camera-capable.

    !! OPERATIONAL RULES (non-negotiable) !!
    * Run ONLY at a quiet boundary: no scan running, no watcher task
      executing against project_tct, app closed. Adam/Kaya supervised.
    * The PySpin wheel install is a MANUAL step: this script prints the
      command but only runs it when you explicitly pass -InstallPySpin
      (real-camera bench use only; simulation mode does not need it).
    * The old venv is KEPT as .venv_old until a human verified the app runs.

.PARAMETER Execute
    Actually perform the plan. Without it, the script only detects and prints.

.PARAMETER InstallPySpin
    (Only with -Execute) also install the vendored PySpin wheel into the new
    venv. Off by default -- the wheel step stays manual unless asked for.

.PARAMETER TctApp
    Path to the TCT application folder (contains requirements.txt and .venv).

.PARAMETER PySpinWheel
    Path to the vendored cp310/win_amd64 PySpin wheel.

.EXAMPLE
    powershell -File tools\recreate_tct_venv.ps1              # dry-run (safe)
    powershell -File tools\recreate_tct_venv.ps1 -Execute     # do it (supervised!)
#>
[CmdletBinding()]
param(
    [switch]$Execute,
    [switch]$InstallPySpin,
    [string]$TctApp = "C:\Users\nukei\Desktop\project_tct\TCT_app",
    [string]$PySpinWheel = "C:\Users\nukei\Desktop\project_tct\reference\spinnaker_sdk\spinnaker_python-3.2.0.65-cp310-cp310-win_amd64\spinnaker_python-3.2.0.65-cp310-cp310-win_amd64.whl"
)

$ErrorActionPreference = "Stop"

function Write-Step([string]$Message) { Write-Host ("  " + $Message) }
function Write-Head([string]$Message) { Write-Host ""; Write-Host $Message -ForegroundColor Cyan }

# --------------------------------------------------------------------------
# 1. Detect candidate non-Store CPython 3.10 installs
# --------------------------------------------------------------------------
Write-Head "[1/4] Detecting non-Store CPython 3.10 (64-bit) candidates"

$candidates = New-Object System.Collections.Generic.List[string]

# a) py launcher inventory
try {
    $pyList = & py -0p 2>$null
    if ($pyList) {
        foreach ($line in $pyList) {
            if ($line -match "3\.10" -and $line -match "([A-Za-z]:\\[^*]*python\.exe)") {
                $candidates.Add($Matches[1].Trim())
            }
        }
    }
} catch {}

# b) conventional install locations
$conventional = @(
    (Join-Path $env:LOCALAPPDATA "Programs\Python\Python310\python.exe"),
    "C:\Python310\python.exe"
)
foreach ($p in $conventional) {
    if (Test-Path $p) { $candidates.Add($p) }
}

# c) anything called python* on PATH (the 3.10/64-bit probe below filters)
try {
    foreach ($cmd in (Get-Command python, python3, python3.10 -ErrorAction SilentlyContinue)) {
        if ($cmd.Source) { $candidates.Add($cmd.Source) }
    }
} catch {}

# d) filter: no Store aliases, must really be 3.10 and 64-bit
$chosen = $null
foreach ($cand in ($candidates | Select-Object -Unique)) {
    if ($cand -like "*WindowsApps*") {
        Write-Step "SKIP (Store alias)      : $cand"
        continue
    }
    try {
        $probe = & $cand -c "import sys,struct;print('%d.%d/%d' % (sys.version_info[0], sys.version_info[1], struct.calcsize('P')*8))" 2>$null
    } catch { $probe = $null }
    if ($probe -eq "3.10/64") {
        Write-Step "OK   (CPython 3.10 x64) : $cand"
        if (-not $chosen) { $chosen = $cand }
    } else {
        Write-Step "SKIP (probe='$probe')      : $cand"
    }
}

if (-not $chosen) {
    Write-Host ""
    Write-Host "NO usable non-Store CPython 3.10 (64-bit) found." -ForegroundColor Yellow
    Write-Host "Install one first (python.org installer, 'Windows installer (64-bit)'):"
    Write-Host "    https://www.python.org/downloads/release/python-31011/"
    Write-Host "Then re-run this script. Nothing was changed."
    exit 1
}
Write-Host ""
Write-Host "Selected interpreter: $chosen" -ForegroundColor Green

# --------------------------------------------------------------------------
# 2. Sanity-check the target and show the current (broken) state
# --------------------------------------------------------------------------
Write-Head "[2/4] Target state"
$venv    = Join-Path $TctApp ".venv"
$venvNew = Join-Path $TctApp ".venv_new"
$venvOld = Join-Path $TctApp ".venv_old"
$reqs    = Join-Path $TctApp "requirements.txt"

if (-not (Test-Path $reqs)) { Write-Host "requirements.txt not found at $reqs -- wrong -TctApp?" -ForegroundColor Red; exit 1 }
$cfg = Join-Path $venv "pyvenv.cfg"
if (Test-Path $cfg) {
    $home310 = (Select-String -Path $cfg -Pattern "^home\s*=\s*(.+)$").Matches[0].Groups[1].Value
    Write-Step "current .venv home      : $home310"
    if ($home310 -like "*WindowsApps*") {
        Write-Step "-> confirmed Store-alias venv (the sandbox-launch failure)"
    } else {
        Write-Step "-> NOTE: current venv is NOT Store-based; re-check whether this fix is still needed."
    }
} else {
    Write-Step "no existing .venv found (fresh create)"
}
foreach ($blocker in @($venvNew, $venvOld)) {
    if (Test-Path $blocker) {
        Write-Host "REFUSING: $blocker already exists (leftover from a previous attempt). Clean it up by hand first." -ForegroundColor Red
        exit 1
    }
}
if (-not (Test-Path $PySpinWheel)) {
    Write-Step "WARNING: PySpin wheel not found at $PySpinWheel (manual step will need the right path)"
}

# --------------------------------------------------------------------------
# 3. The plan
# --------------------------------------------------------------------------
Write-Head "[3/4] Plan (dry-run prints only; -Execute performs steps A-E)"
Write-Step "A. & `"$chosen`" -m venv `"$venvNew`""
Write-Step "B. & `"$venvNew\Scripts\python.exe`" -m pip install --upgrade pip"
Write-Step "C. & `"$venvNew\Scripts\python.exe`" -m pip install -r `"$reqs`""
Write-Step "D. verify: numpy<2 imports, pyvenv.cfg home is NOT WindowsApps"
Write-Step "E. swap:   .venv -> .venv_old ; .venv_new -> .venv   (keep .venv_old)"
Write-Step "MANUAL (real camera only; run yourself or pass -InstallPySpin with -Execute):"
Write-Step "   & `"$venv\Scripts\python.exe`" -m pip install `"$PySpinWheel`""
Write-Step "   (also requires the Spinnaker SDK runtime installer -- see TCT_app docs)"

if (-not $Execute) {
    Write-Host ""
    Write-Host "DRY-RUN: nothing was changed. Re-run with -Execute at a quiet boundary (Adam/Kaya supervised)." -ForegroundColor Yellow
    exit 0
}

# --------------------------------------------------------------------------
# 4. Execute (supervised)
# --------------------------------------------------------------------------
Write-Head "[4/4] Executing"
Write-Step "A. creating $venvNew"
& $chosen -m venv $venvNew
if ($LASTEXITCODE -ne 0) { Write-Host "venv creation failed; aborting (nothing swapped)." -ForegroundColor Red; exit 1 }
$newPy = Join-Path $venvNew "Scripts\python.exe"

Write-Step "B. upgrading pip"
& $newPy -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { Write-Host "pip upgrade failed; aborting (old .venv untouched)." -ForegroundColor Red; exit 1 }

Write-Step "C. installing requirements.txt"
& $newPy -m pip install -r $reqs
if ($LASTEXITCODE -ne 0) { Write-Host "requirements install failed; aborting (old .venv untouched)." -ForegroundColor Red; exit 1 }

if ($InstallPySpin) {
    Write-Step "C2. installing vendored PySpin wheel (explicitly requested)"
    & $newPy -m pip install $PySpinWheel
    if ($LASTEXITCODE -ne 0) { Write-Host "PySpin wheel install failed; aborting (old .venv untouched)." -ForegroundColor Red; exit 1 }
}

Write-Step "D. verification"
$numpyVer = & $newPy -c "import numpy;print(numpy.__version__)"
if ($LASTEXITCODE -ne 0 -or -not $numpyVer.StartsWith("1.")) {
    Write-Host "numpy check failed (got '$numpyVer', need 1.x for the PySpin C-ABI); aborting (old .venv untouched)." -ForegroundColor Red
    exit 1
}
Write-Step "   numpy $numpyVer (<2: OK)"
$newHome = (Select-String -Path (Join-Path $venvNew "pyvenv.cfg") -Pattern "^home\s*=\s*(.+)$").Matches[0].Groups[1].Value
if ($newHome -like "*WindowsApps*") {
    Write-Host "new venv home is STILL a Store alias ($newHome); aborting (old .venv untouched)." -ForegroundColor Red
    exit 1
}
Write-Step "   pyvenv.cfg home = $newHome (non-Store: OK)"

Write-Step "E. swapping (.venv -> .venv_old, .venv_new -> .venv)"
if (Test-Path $venv) { Move-Item $venv $venvOld }
Move-Item $venvNew $venv

Write-Host ""
Write-Host "DONE. Old venv kept at $venvOld -- delete it only after a human verified" -ForegroundColor Green
Write-Host "the app runs (simulation mode: .\run.ps1 ; tests: python -m pytest tests/ -q)."
if (-not $InstallPySpin) {
    Write-Host "PySpin was NOT installed (manual step; real-camera use only):"
    Write-Host "    & `"$venv\Scripts\python.exe`" -m pip install `"$PySpinWheel`""
}
