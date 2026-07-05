# daedalus bootstrap (Windows) -- drop the repo on a PC and run this.
#   powershell -ExecutionPolicy Bypass -File .\bootstrap.ps1
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

Write-Host "== daedalus bootstrap ==" -ForegroundColor Cyan

# 1. Python 3.10+
$py = (Get-Command python -ErrorAction SilentlyContinue)
if (-not $py) { throw "Python 3.10+ is required and not on PATH. Install it, then re-run." }
python --version

# 2. venv (clean, isolated -- zero deps but good hygiene)
if (-not (Test-Path .venv)) { python -m venv .venv }
& .\.venv\Scripts\Activate.ps1

# 3. install the harness editable (+ optional YAML checks)
python -m pip install --upgrade pip | Out-Null
python -m pip install -e ".[yaml]"

# 4. Ollama (the local bench)
if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    Write-Host "Installing Ollama via winget..." -ForegroundColor Yellow
    winget install --id Ollama.Ollama -e --accept-source-agreements --accept-package-agreements
    Write-Host "NOTE: you may need a new terminal for 'ollama' to be on PATH." -ForegroundColor Yellow
} else { Write-Host "Ollama already installed." }

# 5. pull models (coder + embedder). Override coder with $env:OLLAMA_MODEL.
$model = if ($env:OLLAMA_MODEL) { $env:OLLAMA_MODEL } else { "qwen2.5-coder:7b" }
try {
    ollama pull $model
    ollama pull nomic-embed-text
} catch {
    Write-Host "Could not pull models yet (open a new terminal so 'ollama' is on PATH, then: ollama pull $model)" -ForegroundColor Yellow
}

# 6. readiness check
Write-Host "`n== readiness ==" -ForegroundColor Cyan
daedalus doctor
Write-Host "`nDone. To enable writes in a repo:  cd <repo>; daedalus init; then edit .agentenv\agentenv.json" -ForegroundColor Green
