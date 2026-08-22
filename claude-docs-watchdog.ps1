#requires -Version 5.1

<#
.SYNOPSIS
Keeps a Mnemosyne docs sweep running in the background, independent of any
interactive Claude Code session (owner standing order 2026-08-22).

.DESCRIPTION
Every tick the watchdog checks whether HEAD moved or the interval elapsed; if
so it runs ONE headless sweep: `claude --print --agent mnemosyne` with the
prompt in .claude/watchdog/docs-sweep-prompt.md. Each sweep is a fresh,
bounded session; logs land in .claude/watchdog/docs/attempt-NNNN-*.log and the
agent appends to .claude/watchdog/docs/sweeps.log. Quota / transient errors
use bounded exponential backoff. Git state is never reset by this script.

Stop with Ctrl+C or by creating the STOP file printed at startup.

.EXAMPLE
.\claude-docs-watchdog.ps1
.EXAMPLE
.\claude-docs-watchdog.ps1 -IntervalMinutes 30 -MaxHours 72
#>

[CmdletBinding()]
param(
    [string]$ProjectPath = $PSScriptRoot,
    [ValidateRange(2, 720)]
    [int]$IntervalMinutes = 20,
    [ValidateRange(1, 168)]
    [int]$MaxHours = 48,
    [string]$Model = "haiku",
    [string]$Agent = "mnemosyne",
    [ValidateSet("default", "acceptEdits", "auto", "dontAsk")]
    [string]$PermissionMode = "acceptEdits",
    [ValidateSet("low", "medium", "high")]
    [string]$Effort = "low",
    [ValidateRange(1, 240)]
    [int]$QuotaRetryMinutes = 20,
    [switch]$RunOnce
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Write-Status([string]$Message, [ConsoleColor]$Color = [ConsoleColor]::Gray) {
    Write-Host ("[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $Message) -ForegroundColor $Color
}

$resolvedProjectPath = (Resolve-Path -LiteralPath $ProjectPath).Path
if (-not (Get-Command claude -ErrorAction SilentlyContinue)) {
    throw "Claude Code was not found on PATH. Install it and run 'claude auth login' first."
}
$promptFile = Join-Path $resolvedProjectPath ".claude\watchdog\docs-sweep-prompt.md"
if (-not (Test-Path -LiteralPath $promptFile)) { throw "Sweep prompt missing: $promptFile" }

$runDir = Join-Path $resolvedProjectPath ".claude\watchdog\docs"
New-Item -ItemType Directory -Force -Path $runDir | Out-Null
$stopFile = Join-Path $runDir "STOP"
$stateFile = Join-Path $runDir "state.json"
$sweepLog = Join-Path $runDir "sweeps.log"
if (Test-Path -LiteralPath $stopFile) { Remove-Item -LiteralPath $stopFile -Force }

$state = [ordered]@{
    schemaVersion = 1
    projectPath = $resolvedProjectPath
    startedAtUtc = (Get-Date).ToUniversalTime().ToString("o")
    deadlineUtc = (Get-Date).ToUniversalTime().AddHours($MaxHours).ToString("o")
    attempt = 0
    consecutiveErrors = 0
    lastSweepHead = ""
    lastSweepUtc = ""
    lastExitCode = $null
}
if (Test-Path -LiteralPath $stateFile) {
    try {
        $prev = Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json
        $state.attempt = [int]$prev.attempt
        $state.lastSweepHead = [string]$prev.lastSweepHead
        $state.lastSweepUtc = [string]$prev.lastSweepUtc
    } catch { Write-Status "state.json unreadable; starting fresh" Yellow }
}
function Save-State { $state | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $stateFile -Encoding UTF8 }

function Get-Head {
    $h = (& git -C $resolvedProjectPath rev-parse HEAD 2>$null | Out-String).Trim()
    if ([string]::IsNullOrWhiteSpace($h)) { return "unknown" }
    return $h
}

Write-Status "Docs watchdog: project=$resolvedProjectPath agent=$Agent model=$Model interval=${IntervalMinutes}m max=${MaxHours}h" Cyan
Write-Status "Stop file: $stopFile" Cyan
$prompt = Get-Content -LiteralPath $promptFile -Raw
$deadline = [datetime]::Parse($state.deadlineUtc).ToUniversalTime()

while ($true) {
    if (Test-Path -LiteralPath $stopFile) { Write-Status "STOP file found; exiting." Yellow; break }
    $nowUtc = (Get-Date).ToUniversalTime()
    if ($nowUtc -ge $deadline) { Write-Status "MaxHours reached; exiting." Yellow; break }

    $head = Get-Head
    $due = $false
    if ($head -ne $state.lastSweepHead) { $due = $true }
    elseif ([string]::IsNullOrWhiteSpace($state.lastSweepUtc)) { $due = $true }
    else {
        $last = [datetime]::Parse($state.lastSweepUtc).ToUniversalTime()
        if (($nowUtc - $last).TotalMinutes -ge $IntervalMinutes) { $due = $true }
    }

    if (-not $due) { Start-Sleep -Seconds 60; continue }

    $state.attempt++
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $logPath = Join-Path $runDir ("attempt-{0:D4}-{1}.log" -f $state.attempt, $stamp)
    Write-Status ("Sweep #{0} at HEAD {1} (reason: {2})" -f $state.attempt, $head.Substring(0, 8), $(if ($head -ne $state.lastSweepHead) { "HEAD moved" } else { "interval" })) Green

    $claudeArguments = @(
        "--print",
        "--agent", $Agent,
        "--model", $Model,
        "--permission-mode", $PermissionMode,
        "--effort", $Effort,
        $prompt
    )
    Push-Location $resolvedProjectPath
    try {
        & claude @claudeArguments 2>&1 | Tee-Object -FilePath $logPath | ForEach-Object {
            $line = [string]$_
            if ($line.Length -gt 0) { Write-Host ("  | " + $line.Substring(0, [Math]::Min(160, $line.Length))) -ForegroundColor DarkGray }
        }
        $exit = $LASTEXITCODE
    } finally { Pop-Location }

    $state.lastExitCode = $exit
    $state.lastSweepUtc = (Get-Date).ToUniversalTime().ToString("o")
    $state.lastSweepHead = (Get-Head)

    $logText = if (Test-Path -LiteralPath $logPath) { Get-Content -LiteralPath $logPath -Raw } else { "" }
    $quotaHit = $logText -match "(?i)rate limit|usage limit|quota|overloaded|529|too many requests"
    $authHit = $logText -match "(?i)not logged in|authentication|unauthorized|invalid api key"

    if ($authHit) {
        Write-Status "Authentication failed. Run 'claude auth login', then rerun this script." Red
        Save-State; break
    }
    if ($exit -ne 0 -or $quotaHit) {
        $state.consecutiveErrors++
        $waitMin = [Math]::Min($QuotaRetryMinutes * [Math]::Pow(2, $state.consecutiveErrors - 1), 240)
        Write-Status ("Sweep #{0} exit {1}{2}; backing off {3} min" -f $state.attempt, $exit, $(if ($quotaHit) { " (quota)" } else { "" }), $waitMin) Yellow
        Save-State
        if ($RunOnce) { break }
        Start-Sleep -Seconds ([int]($waitMin * 60))
        continue
    }

    $state.consecutiveErrors = 0
    Save-State
    Write-Status ("Sweep #{0} done; log {1}" -f $state.attempt, $logPath) Green
    if ($RunOnce) { break }
    Start-Sleep -Seconds 60
}
Save-State
Write-Status "Docs watchdog stopped after $($state.attempt) sweep(s)." Cyan
