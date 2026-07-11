# bench_run.ps1 — sync branches to the sophonone test bench and run the TCT suite there.
# Runs on the LAPTOP (uses the already-authorized SSH key; changes nothing on the
# bench outside C:\bench). Usage examples:
#   .\bench_run.ps1                                   # sync + run suite on design/cockpit-v5
#   .\bench_run.ps1 -Branch experimental/qml-hybrid-slice1
#   .\bench_run.ps1 -Branch experimental/qml-hybrid-slice1 -SyncOnly
#
# Layout on the bench (created 2026-07-11):
#   C:\bench\project_tct  = repo, checkout of design/cockpit-v5
#   C:\bench\slice1       = worktree, checkout of experimental/qml-hybrid-slice1
#   shared venv           = C:\bench\project_tct\TCT_app\.venv (Python 3.10.11)
# Transport is git bundle + scp (repo is private on GitHub; the bench holds no
# credentials). LFS smudge is disabled per-invocation: bundles carry no LFS
# objects and the only LFS file (a PDF under artifacts_claude/) is irrelevant
# to tests.

param(
    [string]$Branch = "design/cockpit-v5",
    [switch]$SyncOnly
)

$ErrorActionPreference = "Stop"
$BenchHost  = "Administrator@100.119.126.9"
$SshOpts    = @("-o", "BatchMode=yes", "-o", "ConnectTimeout=10")
$RepoLocal  = "C:\Users\nukei\Desktop\project_tct"
$Bundle     = Join-Path $env:TEMP "tct_sync.bundle"
$LfsOff     = "-c filter.lfs.smudge= -c filter.lfs.process= -c filter.lfs.required=false"

# Bench checkout dir per branch (extend this map when adding branches).
$TreeMap = @{
    "design/cockpit-v5"              = "C:\bench\project_tct"
    "experimental/qml-hybrid-slice1" = "C:\bench\slice1"
}
if (-not $TreeMap.ContainsKey($Branch)) {
    Write-Host "No bench worktree mapped for '$Branch' - add it to `$TreeMap (git worktree add on the bench first)." -ForegroundColor Red
    exit 2
}
$Tree = $TreeMap[$Branch]

Write-Host "[1/4] Bundling $Branch ..." -ForegroundColor Cyan
git -C $RepoLocal bundle create $Bundle $Branch
if ($LASTEXITCODE -ne 0) { exit 1 }

Write-Host "[2/4] Shipping bundle to bench ..." -ForegroundColor Cyan
scp @SshOpts $Bundle "${BenchHost}:C:/bench/tct_sync.bundle"
if ($LASTEXITCODE -ne 0) { Write-Host "scp failed - is the PC on / Tailscale up?" -ForegroundColor Red; exit 1 }

Write-Host "[3/4] Fetch + hard-sync checkout on bench ..." -ForegroundColor Cyan
# Remote shell is cmd.exe: no pipes, no quotes-with-spaces, no trailing spaces
# before '&' (they end up inside values). Keep each remote line dead simple.
# Fetch into a staging ref (fetching into a checked-out branch is refused),
# then hard-reset the checkout onto it (this moves the branch ref too).
$remote = "git -C C:\bench\project_tct fetch C:\bench\tct_sync.bundle +${Branch}:refs/bench/staging & git -C $Tree $LfsOff reset --hard refs/bench/staging & git -C $Tree log --oneline -1"
ssh @SshOpts $BenchHost $remote
if ($LASTEXITCODE -ne 0) { Write-Host "bench sync failed" -ForegroundColor Red; exit 1 }

if ($SyncOnly) { Write-Host "Sync done (suite skipped)." -ForegroundColor Green; exit 0 }

Write-Host "[4/4] Running suite on bench (offscreen) ..." -ForegroundColor Cyan
$remote = "set QT_QPA_PLATFORM=offscreen& cd /d $Tree\TCT_app & C:\bench\project_tct\TCT_app\.venv\Scripts\python.exe -m pytest tests/ -q"
ssh @SshOpts $BenchHost $remote
$code = $LASTEXITCODE
if ($code -eq 0) { Write-Host "BENCH SUITE GREEN ($Branch)" -ForegroundColor Green }
else             { Write-Host "BENCH SUITE FAILED ($Branch) exit=$code" -ForegroundColor Red }
exit $code
