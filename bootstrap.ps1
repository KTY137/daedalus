# daedalus bootstrap (Windows) -- drop the repo on a PC and run this.
#   powershell -ExecutionPolicy Bypass -File .\bootstrap.ps1
param(
    [switch]$GpuResearch
)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

function ConvertTo-NvidiaDriverVersion {
    param([Parameter(Mandatory = $true)][string]$Value)

    $parts = @($Value.Trim() -split '\.')
    if ($parts.Count -lt 2 -or $parts.Count -gt 4 -or ($parts | Where-Object { $_ -notmatch '^\d+$' })) {
        throw "nvidia-smi returned an unparseable NVIDIA driver version: '$Value'"
    }
    while ($parts.Count -lt 4) { $parts += "0" }
    return [Version]($parts -join '.')
}

function Assert-GpuResearchHost {
    $runtime = [System.Runtime.InteropServices.RuntimeInformation]
    $osArchitecture = $runtime::OSArchitecture.ToString()
    $processArchitecture = $runtime::ProcessArchitecture.ToString()
    if (-not $runtime::IsOSPlatform([System.Runtime.InteropServices.OSPlatform]::Windows) -or
        $osArchitecture -ne "X64" -or $processArchitecture -ne "X64") {
        throw "-GpuResearch supports only native x86-64 Windows (OS=$osArchitecture, process=$processArchitecture). No packages were installed."
    }

    $nvidiaSmi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
    if (-not $nvidiaSmi) {
        throw "-GpuResearch requires nvidia-smi on PATH and a working NVIDIA driver. No packages were installed."
    }

    [string[]]$gpuNames = @(& $nvidiaSmi.Source --query-gpu=name --format=csv,noheader,nounits 2>$null) |
        ForEach-Object { $_.Trim() } | Where-Object { $_ }
    $nameExitCode = $LASTEXITCODE
    if ($nameExitCode -ne 0 -or $gpuNames.Count -eq 0) {
        throw "nvidia-smi did not enumerate an NVIDIA GPU (exit=$nameExitCode). No packages were installed."
    }

    [string[]]$driverVersions = @(& $nvidiaSmi.Source --query-gpu=driver_version --format=csv,noheader,nounits 2>$null) |
        ForEach-Object { $_.Trim() } | Where-Object { $_ }
    $driverExitCode = $LASTEXITCODE
    if ($driverExitCode -ne 0 -or $driverVersions.Count -eq 0) {
        throw "nvidia-smi could not report the NVIDIA driver version (exit=$driverExitCode). No packages were installed."
    }

    $minimumDriver = [Version]"561.17.0.0"
    Write-Host ("NVIDIA GPU(s): " + ($gpuNames -join "; ")) -ForegroundColor Cyan
    Write-Host ("NVIDIA driver(s): " + ($driverVersions -join "; ") + " (required >= 561.17 for pinned CUDA 12.6.3)") -ForegroundColor Cyan
    foreach ($driverVersion in $driverVersions) {
        if ((ConvertTo-NvidiaDriverVersion $driverVersion) -lt $minimumDriver) {
            throw "NVIDIA driver $driverVersion is below the conservative CUDA 12.6.3 Windows floor 561.17. No packages were installed."
        }
    }

    [string[]]$capabilities = @(& $nvidiaSmi.Source --query-gpu=name,compute_cap --format=csv,noheader,nounits 2>$null) |
        ForEach-Object { $_.Trim() } | Where-Object { $_ }
    $capabilityExitCode = $LASTEXITCODE
    if ($capabilityExitCode -eq 0 -and $capabilities.Count -gt 0) {
        Write-Host ("NVIDIA compute capability inventory: " + ($capabilities -join "; ")) -ForegroundColor Cyan
    } else {
        Write-Host "nvidia-smi could not report compute capability; continuing to the installed Torch/deep device probes." -ForegroundColor Yellow
    }
    Write-Host "Pre-install compute capability is advisory; the exact Torch CUDA operation and final Daedalus deep probe decide readiness." -ForegroundColor Yellow
}

Write-Host "== daedalus bootstrap ==" -ForegroundColor Cyan

if ($GpuResearch) {
    Assert-GpuResearchHost
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if (-not $uv) { throw "The -GpuResearch path requires uv so uv.lock and the exclusive CUDA index are enforced. Install uv, then re-run." }
}

# 1. Python 3.10+
$py = (Get-Command python -ErrorAction SilentlyContinue)
if (-not $py) { throw "Python 3.10+ is required and not on PATH. Install it, then re-run." }
python --version

# 2. venv (clean, isolated -- zero deps but good hygiene)
if (-not (Test-Path .venv)) { python -m venv .venv }
& .\.venv\Scripts\Activate.ps1

# 3. install the harness editable (+ optional YAML checks).  The CUDA research
# stack is multi-gigabyte and remains an explicit owner opt-in.  That path uses
# the checked-in uv lock; pip cannot publish an alternate-index mapping.
if ($GpuResearch) {
    uv sync --locked --all-extras --python .\.venv\Scripts\python.exe
    & .\.venv\Scripts\python.exe -c "import torch; assert torch.__version__ == '2.14.0+cu126' and torch.version.cuda == '12.6', (torch.__version__, torch.version.cuda); assert torch.cuda.is_available() and torch.cuda.device_count() > 0, 'Torch did not enumerate a CUDA device'; x = torch.arange(256, dtype=torch.float32, device='cuda:0'); y = (x * 2 + 1).cpu(); torch.cuda.synchronize(); assert torch.equal(y, torch.arange(256, dtype=torch.float32) * 2 + 1), 'bounded CUDA oracle mismatch'; print('Torch CUDA 12.6 bounded device oracle passed on', torch.cuda.get_device_name(0), torch.cuda.get_device_capability(0))"
    uv pip check --python .\.venv\Scripts\python.exe
    Write-Host "`n== CUDA research evidence ==" -ForegroundColor Cyan
    daedalus accelerators --deep --json
    if ($LASTEXITCODE -ne 0) { throw "The final Daedalus deep accelerator probe failed (exit=$LASTEXITCODE)." }
} else {
    python -m pip install --upgrade pip | Out-Null
    python -m pip install -e ".[yaml]"
}

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
