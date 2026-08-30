# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

# bench_run.ps1 — sync branches to the sophonone test bench and run the TCT suite there.
# Runs on the LAPTOP (uses the already-authorized SSH key; changes nothing on the
# bench outside C:\bench). Usage examples:
#   .\bench_run.ps1                                   # sync + run suite on design/cockpit-v5
#   .\bench_run.ps1 -Branch experimental/qml-hybrid-slice1
#   .\bench_run.ps1 -Branch experimental/qml-hybrid-slice1 -SyncOnly
#   .\bench_run.ps1 -Xdist                            # parallel suite (~31 s vs ~231 s)
#   .\bench_run.ps1 -Xdist -Workers 4                 # isolation stress (most tests/worker)
#
# Layout on the bench (created 2026-07-11):
#   C:\bench\project_tct  = repo, checkout of design/cockpit-v5
#   C:\bench\slice1       = worktree, checkout of experimental/qml-hybrid-slice1
#   shared venv           = C:\bench\project_tct\TCT_app\.venv (Python 3.10.11)
# Transport is git bundle + scp (repo is private on GitHub; the bench holds no
# credentials). LFS smudge is disabled per-invocation because bundles carry no
# LFS objects — but since U2.1 (2026-07-15) LFS files under TCT_app/ (the QML
# kit's baked PNG assets) are READ BY TESTS, so step [3b] ships exactly those
# objects (KBs, never the 1.9 GB store) and smudges them offline with
# 'git lfs checkout' on the bench. LFS files outside TCT_app/ stay pointers.

param(
    [string]$Branch = "design/cockpit-v5",
    [switch]$SyncOnly,
    [switch]$Xdist,                 # run the suite in parallel (pytest-xdist)
    [string]$Workers = "auto"       # -n value when -Xdist is given (auto|4|8|16)
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
    "design/glass-wave-1"            = "C:\bench\project_tct"
    "main"                           = "C:\bench\project_tct"
    "ui-qml-migration"               = "C:\bench\project_tct"
    "liquid-shell"                   = "C:\bench\project_tct"
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

# [3b] LFS objects for files under TCT_app/ (tests read them; see header note).
# Worktrees share the main repo's object store, so the tar always lands in
# C:\bench\project_tct\.git\lfs\objects regardless of $Tree.
$lfsEntries = git -C $RepoLocal lfs ls-files -l $Branch |
    ForEach-Object { $p = $_ -split ' ', 3; [pscustomobject]@{ Oid = $p[0]; Path = $p[2] } } |
    Where-Object { $_.Path -like 'TCT_app/*' }
if ($lfsEntries) {
    Write-Host "[3b] Shipping $(@($lfsEntries).Count) LFS objects under TCT_app/ ..." -ForegroundColor Cyan
    # Stage objects WITH the lfs/objects/ prefix so remote extraction targets
    # .git (always exists) - no mkdir, no cmd 'if' (its &-grouping is a trap).
    $staging = Join-Path $env:TEMP "tct_lfs_stage"
    if (Test-Path $staging) { Remove-Item -Recurse -Force $staging }
    foreach ($e in $lfsEntries) {
        $oid = $e.Oid
        $src = Join-Path $RepoLocal ".git\lfs\objects\$($oid.Substring(0,2))\$($oid.Substring(2,2))\$oid"
        if (-not (Test-Path $src)) { Write-Host "LFS object missing locally for $($e.Path) ($oid) - run 'git lfs fetch' first" -ForegroundColor Red; exit 1 }
        $dstDir = Join-Path $staging "lfs\objects\$($oid.Substring(0,2))\$($oid.Substring(2,2))"
        New-Item -ItemType Directory -Force $dstDir | Out-Null
        Copy-Item $src $dstDir
    }
    $tarLocal = Join-Path $env:TEMP "tct_lfs.tar"
    # Use Windows' own bsdtar explicitly: a Git-Bash GNU tar earlier on PATH
    # parses "C:\..." as host:path ("Cannot connect to C") — 2026-07-16 fix.
    & "$env:SystemRoot\System32\tar.exe" -cf $tarLocal -C $staging lfs
    if ($LASTEXITCODE -ne 0) { Write-Host "local lfs tar failed" -ForegroundColor Red; exit 1 }
    scp @SshOpts $tarLocal "${BenchHost}:C:/bench/tct_lfs.tar"
    if ($LASTEXITCODE -ne 0) { Write-Host "scp lfs tar failed" -ForegroundColor Red; exit 1 }
    ssh @SshOpts $BenchHost "tar -xf C:\bench\tct_lfs.tar -C C:\bench\project_tct\.git"
    if ($LASTEXITCODE -ne 0) { Write-Host "bench lfs tar extract failed" -ForegroundColor Red; exit 1 }
    ssh @SshOpts $BenchHost "git -C $Tree lfs checkout TCT_app"
    if ($LASTEXITCODE -ne 0) { Write-Host "bench lfs checkout failed" -ForegroundColor Red; exit 1 }
    # Verify: 'git lfs ls-files' marks smudged content '*' and bare pointers '-'
    # (no path arg - the bench git-lfs rejects '-- <path>' as a bad ref).
    $lfsOut = @(ssh @SshOpts $BenchHost "git -C $Tree lfs ls-files")
    if ($LASTEXITCODE -ne 0) { Write-Host "bench lfs ls-files failed" -ForegroundColor Red; exit 1 }
    $pointers = @($lfsOut | Where-Object { $_ -match '^\S+ - .*TCT_app/' })
    if ($pointers.Count -gt 0) { Write-Host "LFS files still pointers on bench (tests would fail):" -ForegroundColor Red; $pointers | Write-Host; exit 1 }
    Write-Host "LFS OK: $(@($lfsOut | Where-Object { $_ -match 'TCT_app/' }).Count) TCT_app files smudged on bench" -ForegroundColor Green
}

if ($SyncOnly) { Write-Host "Sync done (suite skipped)." -ForegroundColor Green; exit 0 }

# -Xdist: run the suite in parallel (pytest-xdist, installed in the bench venv).
# ~31 s vs ~231 s serial on the 16-core bench. Trustworthy since 2026-07-13:
# the suite's cross-test leaks (flash_button's unowned restore timer; QSettings
# hitting the shared real registry from every worker) are fixed, so a failure
# under -n auto is now a real failure. Serial stays the DEFAULT: it is still the
# reference lane, and -n <N> with a SMALL N (4) is the most sensitive setting
# for isolation defects (more tests per worker), so it is the useful stress run.
$pytestArgs = if ($Xdist) { "-n $Workers" } else { "" }
Write-Host "[4/4] Running suite on bench (offscreen$(if ($Xdist) { ", -n $Workers" })) ..." -ForegroundColor Cyan
$remote = "set QT_QPA_PLATFORM=offscreen& cd /d $Tree\TCT_app & C:\bench\project_tct\TCT_app\.venv\Scripts\python.exe -m pytest tests/ -q $pytestArgs"
ssh @SshOpts $BenchHost $remote
$code = $LASTEXITCODE
if ($code -eq 0) { Write-Host "BENCH SUITE GREEN ($Branch)" -ForegroundColor Green }
else             { Write-Host "BENCH SUITE FAILED ($Branch) exit=$code" -ForegroundColor Red }
exit $code
