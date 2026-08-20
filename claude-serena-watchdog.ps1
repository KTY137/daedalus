#requires -Version 5.1

<#
.SYNOPSIS
Runs a resumable Claude Code + Serena engineering mission for up to 48 hours.

.DESCRIPTION
The watchdog starts Claude Code in non-interactive mode, gives the run a stable
session ID, and resumes that session whenever Claude exits before the mission is
complete. Serena's system-prompt override is refreshed before every invocation.

Claude must explicitly create MISSION_COMPLETE or BLOCKED in the run directory
to stop the watchdog. Quota and transient service errors use bounded exponential
backoff. Existing project files and Git state are never reset by this script.

.EXAMPLE
.\claude-serena-watchdog.ps1 `
  -ProjectPath "C:\dev\daedalus" `
  -Goal "Implement the approved Daedalus milestone and verify all acceptance criteria."

.EXAMPLE
.\claude-serena-watchdog.ps1 `
  -ProjectPath "C:\dev\daedalus" `
  -PromptFile "C:\dev\daedalus\claude-long-run-prompt.md" `
  -MaxHours 48

.EXAMPLE
.\claude-serena-watchdog.ps1 `
  -ProjectPath "C:\dev\daedalus" `
  -PromptFile ".\claude-long-run-prompt.md" `
  -NewMission

.NOTES
Stop safely with Ctrl+C, or create the STOP file whose path is printed at
startup. The computer must remain awake and connected to the internet.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectPath,

    [string]$Goal,

    [string]$PromptFile,

    [ValidateRange(1, 168)]
    [int]$MaxHours = 48,

    [ValidateSet("default", "acceptEdits", "auto", "dontAsk", "manual")]
    [string]$PermissionMode = "auto",

    [ValidateSet("low", "medium", "high", "xhigh", "max", "ultracode")]
    [string]$Effort = "high",

    [string]$Model,

    [ValidateRange(1, 240)]
    [int]$QuotaRetryMinutes = 20,

    [ValidateRange(5, 3600)]
    [int]$RestartDelaySeconds = 20,

    [ValidateRange(0, 100000)]
    [double]$MaxBudgetUsdPerAttempt = 0,

    [switch]$NewMission
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Status {
    param(
        [Parameter(Mandatory = $true)][string]$Message,
        [ConsoleColor]$Color = [ConsoleColor]::Cyan
    )

    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Write-Host "[$timestamp] $Message" -ForegroundColor $Color
}

function Get-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Text)

    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($Text)
        $hash = $sha.ComputeHash($bytes)
        return ([System.BitConverter]::ToString($hash)).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $sha.Dispose()
    }
}

function Resolve-InputPath {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$BasePath
    )

    if ([System.IO.Path]::IsPathRooted($Path)) {
        return (Resolve-Path -LiteralPath $Path).Path
    }

    return (Resolve-Path -LiteralPath (Join-Path $BasePath $Path)).Path
}

function Save-State {
    param(
        [Parameter(Mandatory = $true)]$State,
        [Parameter(Mandatory = $true)][string]$Path
    )

    $temporaryPath = "$Path.tmp"
    $State.updatedAtUtc = [DateTime]::UtcNow.ToString("o")
    $State | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $temporaryPath -Encoding UTF8
    Move-Item -LiteralPath $temporaryPath -Destination $Path -Force
}

function Get-TailText {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return ""
    }

    return ((Get-Content -LiteralPath $Path -Tail 500 -ErrorAction SilentlyContinue) -join "`n")
}

function Get-FailureClass {
    param(
        [Parameter(Mandatory = $true)][string]$Output,
        [Parameter(Mandatory = $true)][int]$ExitCode
    )

    if ($Output -match "(?i)(please run .?login|not logged in|authentication[_ -]?error|invalid (api|x-api)[ -]?key|oauth token.*expired|unauthorized.*anthropic)") {
        return "authentication"
    }

    if ($Output -match "(?i)(budget limit reached|credit balance.*too low|insufficient credits)") {
        return "billing"
    }

    if ($Output -match "(?i)(usage limit|hit your limit|rate[ -]?limit|resets at|too many requests|\b429\b)") {
        return "quota"
    }

    if ($Output -match "(?i)(overloaded|temporarily unavailable|\b529\b|econnreset|connection reset|network error|timed out|timeout|service unavailable)") {
        return "transient"
    }

    if ($Output -match "(?i)(no conversation found|session.*not found|unable to resume|could not.*resume)") {
        return "missing-session"
    }

    if ($ExitCode -eq 0) {
        return "normal"
    }

    return "failure"
}

function New-GeneratedMission {
    param(
        [Parameter(Mandatory = $true)][string]$MissionGoal,
        [Parameter(Mandatory = $true)][string]$MissionCompletePath,
        [Parameter(Mandatory = $true)][string]$BlockedPath
    )

    return @"
# Long-horizon autonomous engineering mission

## Primary objective

$MissionGoal

Work continuously and autonomously on the current repository until the objective
and all acceptance criteria discoverable from the repository are implemented and
verified. Completing one milestone is not a reason to stop.

## Mandatory Serena workflow

Serena is the primary interface for source-code understanding and semantic edits.
At startup, activate the current project, read Serena's initial instructions,
perform onboarding if needed, and read all relevant memories. Prefer symbol
overviews, find-symbol, reference search, symbol-aware editing, and semantic
renames over whole-file reading, grep, or fragile text replacement. Use ordinary
tools for configuration, documentation, tests, generated files, and cases Serena
cannot handle reliably.

Maintain a Serena memory named `long_horizon_work_state` containing the mission,
completed work, current work, ordered next steps, decisions, changed symbols,
verification commands and results, failures, risks, Git state, and the exact first
action after a restart. Update it after every coherent implementation slice and
before context compaction or exit.

## Continuous work loop

1. Inspect repository instructions, Serena memories, Git status, relevant symbols,
   references, tests, and existing patterns.
2. Select the highest-value unblocked vertical slice.
3. Define an observable verification condition.
4. Implement the smallest complete change consistent with the architecture.
5. Run focused tests, then appropriate lint, type, build, and smoke checks.
6. Inspect the diff critically and fix discovered regressions.
7. Update Serena memory and create a small local checkpoint commit only when it is
   coherent, verified, permitted by repository policy, and does not include
   unrelated pre-existing changes.
8. Immediately continue with the next task.

Never claim a check passed unless it was run successfully. Preserve all existing
user changes. Never reset or clean the repository, expose secrets, weaken security,
push, merge, deploy, publish, purchase services, or modify production unless the
mission explicitly authorizes it.

Make reversible conservative decisions without asking. Ask only for a genuinely
irreversible, security-sensitive, externally consequential, or product-defining
decision. If one task is blocked, record it and work on another useful task.

## Watchdog completion protocol

Only when every acceptance criterion is genuinely complete and verified:

1. Update `long_horizon_work_state` with the final state.
2. Write a concise completion report to:
   $MissionCompletePath
3. Then return the final handoff.

If all meaningful work is blocked by something requiring the user, credentials,
or unavailable external authority:

1. Update `long_horizon_work_state`.
2. Write the exact blocker and required user action to:
   $BlockedPath
3. Then return the blocker report.

Never create either marker for a normal context boundary, quota interruption,
temporary tool failure, or completion of only one phase. Begin implementation now.
"@
}

$resolvedProjectPath = (Resolve-Path -LiteralPath $ProjectPath).Path
if (-not (Test-Path -LiteralPath $resolvedProjectPath -PathType Container)) {
    throw "ProjectPath is not a directory: $resolvedProjectPath"
}

if ([string]::IsNullOrWhiteSpace($Goal) -and [string]::IsNullOrWhiteSpace($PromptFile)) {
    throw "Provide either -Goal or -PromptFile."
}

if (-not [string]::IsNullOrWhiteSpace($Goal) -and -not [string]::IsNullOrWhiteSpace($PromptFile)) {
    throw "Use either -Goal or -PromptFile, not both."
}

$claudeCommand = Get-Command claude -ErrorAction SilentlyContinue
if ($null -eq $claudeCommand) {
    throw "Claude Code was not found on PATH. Install it and run 'claude auth login' first."
}

$serenaCommand = Get-Command serena -ErrorAction SilentlyContinue
if ($null -eq $serenaCommand) {
    throw "Serena was not found on PATH. Run 'uv tool install -p 3.13 serena-agent', 'serena init', and 'serena setup claude-code'."
}

$watchdogRoot = Join-Path $resolvedProjectPath ".claude\watchdog"
New-Item -ItemType Directory -Path $watchdogRoot -Force | Out-Null

$projectHash = (Get-Sha256 -Text $resolvedProjectPath).Substring(0, 20)
$mutexName = "ClaudeSerenaWatchdog_$projectHash"
$mutex = New-Object System.Threading.Mutex($false, $mutexName)
$hasMutex = $false

try {
    try {
        $hasMutex = $mutex.WaitOne(0, $false)
    }
    catch [System.Threading.AbandonedMutexException] {
        $hasMutex = $true
    }

    if (-not $hasMutex) {
        throw "Another watchdog is already running for this project."
    }

    Push-Location $resolvedProjectPath
    try {
        $claudeVersion = (& claude --version 2>&1 | Out-String).Trim()
        Write-Status "Claude Code: $claudeVersion"

        $mcpList = (& claude mcp list 2>&1 | Out-String)
        if ($mcpList -notmatch "(?i)serena") {
            throw "Serena is not configured in Claude Code. Run 'serena setup claude-code', then retry."
        }

        $activeStatePath = Join-Path $watchdogRoot "active-state.json"
        $globalStopPath = Join-Path $watchdogRoot "STOP"
        if (Test-Path -LiteralPath $globalStopPath) {
            throw "A STOP marker already exists at '$globalStopPath'. Rename or remove it before starting."
        }

        $promptSource = $null
        $suppliedMissionHash = $null
        if (-not [string]::IsNullOrWhiteSpace($PromptFile)) {
            $resolvedPromptFile = Resolve-InputPath -Path $PromptFile -BasePath $resolvedProjectPath
            $promptSource = Get-Content -LiteralPath $resolvedPromptFile -Raw
            $suppliedMissionHash = Get-Sha256 -Text $promptSource
        }
        else {
            $suppliedMissionHash = Get-Sha256 -Text $Goal
        }

        $state = $null
        if ((Test-Path -LiteralPath $activeStatePath) -and -not $NewMission) {
            $state = Get-Content -LiteralPath $activeStatePath -Raw | ConvertFrom-Json
            if ($state.projectPath -ne $resolvedProjectPath) {
                throw "The stored watchdog state belongs to another project. Use -NewMission to create a new run."
            }

            $deadlineUtc = [DateTime]::Parse($state.deadlineUtc).ToUniversalTime()
            if ([DateTime]::UtcNow -ge $deadlineUtc) {
                throw "The stored mission deadline has passed. Use -NewMission to start another work window."
            }

            $runDirectory = $state.runDirectory
            $missionPath = Join-Path $runDirectory "mission.md"
            if (-not (Test-Path -LiteralPath $missionPath)) {
                throw "Stored mission file is missing: $missionPath"
            }

            if ($state.sourcePromptHash -ne $suppliedMissionHash) {
                throw "The supplied Goal or PromptFile differs from the active mission. Use -NewMission to start with the new input."
            }

            Write-Status "Resuming watchdog session $($state.sessionId)."
        }
        else {
            $sessionId = [Guid]::NewGuid().ToString()
            $runDirectory = Join-Path $watchdogRoot $sessionId
            New-Item -ItemType Directory -Path $runDirectory -Force | Out-Null

            $missionCompletePath = Join-Path $runDirectory "MISSION_COMPLETE"
            $blockedPath = Join-Path $runDirectory "BLOCKED"

            if ($null -eq $promptSource) {
                $promptSource = New-GeneratedMission `
                    -MissionGoal $Goal `
                    -MissionCompletePath $missionCompletePath `
                    -BlockedPath $blockedPath
            }
            else {
                $watchdogProtocol = @"

## Watchdog completion protocol

This mission is supervised by a restart watchdog. Maintain Serena memory
`long_horizon_work_state` after every coherent slice and before exiting.

Only after the entire mission is implemented and verified, write a completion
report to: $missionCompletePath
If all useful work is blocked by something only the user can resolve, write the
blocker and required action to: $blockedPath
Do not create either marker for an intermediate milestone, context compaction,
quota interruption, or temporary tool failure. Continue automatically after each
completed task.
"@
                $promptSource = $promptSource.TrimEnd() + "`r`n" + $watchdogProtocol
            }

            $missionPath = Join-Path $runDirectory "mission.md"
            $promptSource | Set-Content -LiteralPath $missionPath -Encoding UTF8

            $nowUtc = [DateTime]::UtcNow
            $deadlineUtc = $nowUtc.AddHours($MaxHours)
            $state = [PSCustomObject]@{
                schemaVersion      = 1
                projectPath        = $resolvedProjectPath
                sessionId          = $sessionId
                sessionInitialized = $false
                runDirectory       = $runDirectory
                sourcePromptHash   = $suppliedMissionHash
                startedAtUtc       = $nowUtc.ToString("o")
                deadlineUtc        = $deadlineUtc.ToString("o")
                attempt            = 0
                consecutiveErrors  = 0
                lastExitCode       = $null
                lastFailureClass   = $null
                lastLogPath        = $null
                updatedAtUtc       = $nowUtc.ToString("o")
            }
            Save-State -State $state -Path $activeStatePath
            Write-Status "Created watchdog session $sessionId."
        }

        $runDirectory = $state.runDirectory
        $missionPath = Join-Path $runDirectory "mission.md"
        $missionCompletePath = Join-Path $runDirectory "MISSION_COMPLETE"
        $blockedPath = Join-Path $runDirectory "BLOCKED"
        $runStopPath = Join-Path $runDirectory "STOP"
        $serenaSystemPromptPath = Join-Path $runDirectory "serena-system-prompt.txt"
        $deadlineUtc = [DateTime]::Parse($state.deadlineUtc).ToUniversalTime()

        if ([string]::IsNullOrWhiteSpace($env:MCP_TIMEOUT)) {
            $env:MCP_TIMEOUT = "60000"
        }

        Write-Status "Project: $resolvedProjectPath"
        Write-Status "Deadline: $($deadlineUtc.ToLocalTime().ToString('yyyy-MM-dd HH:mm:ss zzz'))"
        Write-Status "Stop file: $runStopPath"
        Write-Status "Global stop file: $globalStopPath"
        Write-Status "Logs: $runDirectory"
        Write-Status "Permission mode: $PermissionMode (bypassPermissions is deliberately unsupported)" -Color Yellow

        while ([DateTime]::UtcNow -lt $deadlineUtc) {
            if ((Test-Path -LiteralPath $globalStopPath) -or (Test-Path -LiteralPath $runStopPath)) {
                Write-Status "STOP marker detected. Ending watchdog without changing project state." -Color Yellow
                break
            }

            if (Test-Path -LiteralPath $missionCompletePath) {
                Write-Status "Mission complete marker detected." -Color Green
                Write-Host (Get-Content -LiteralPath $missionCompletePath -Raw)
                break
            }

            if (Test-Path -LiteralPath $blockedPath) {
                Write-Status "Mission is blocked and needs user input." -Color Yellow
                Write-Host (Get-Content -LiteralPath $blockedPath -Raw)
                break
            }

            $state.attempt = [int]$state.attempt + 1
            $attempt = [int]$state.attempt
            $logPath = Join-Path $runDirectory ("attempt-{0:D4}-{1}.log" -f $attempt, (Get-Date -Format "yyyyMMdd-HHmmss"))

            Write-Status "Refreshing Serena's Claude Code system-prompt override."
            $serenaOverride = (& serena prompts print-cc-system-prompt-override 2>&1 | Out-String)
            if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($serenaOverride)) {
                throw "Could not obtain Serena's Claude Code system-prompt override."
            }
            $serenaOverride | Set-Content -LiteralPath $serenaSystemPromptPath -Encoding UTF8

            $remaining = $deadlineUtc - [DateTime]::UtcNow
            $resumePrompt = @"
This is an automatic continuation of the long-horizon mission. Read the mission
at $missionPath, activate the current project with Serena, read Serena's initial
instructions and long_horizon_work_state, inspect Git status and the current
diff, run the smallest relevant verification check, and continue from the exact
recorded next action. Do not restart the analysis and do not merely summarize.
Approximately $([Math]::Floor($remaining.TotalHours)) hours remain in the work
window. Follow the completion-marker protocol in the mission file.
"@

            $initialPrompt = @"
Read and execute the complete long-horizon mission at $missionPath. Activate
the current project with Serena, read its initial instructions, complete onboarding
if necessary, initialize long_horizon_work_state, inspect the repository, and
immediately begin the highest-priority implementation slice. Follow the watchdog
completion-marker protocol in the mission file.
"@

            $claudeArguments = @(
                "--print",
                "--permission-mode", $PermissionMode,
                "--effort", $Effort,
                "--system-prompt-file", $serenaSystemPromptPath,
                "--disallowedTools",
                "Bash(git push *)",
                "Bash(git reset --hard *)",
                "Bash(git clean *)",
                "Bash(gh pr merge *)",
                "Bash(npm publish *)",
                "Bash(pnpm publish *)",
                "Bash(yarn publish *)"
            )

            if (-not [string]::IsNullOrWhiteSpace($Model)) {
                $claudeArguments += @("--model", $Model)
            }

            if ($MaxBudgetUsdPerAttempt -gt 0) {
                $claudeArguments += @("--max-budget-usd", $MaxBudgetUsdPerAttempt.ToString([System.Globalization.CultureInfo]::InvariantCulture))
            }

            if ([bool]$state.sessionInitialized) {
                $claudeArguments += @("--resume", $state.sessionId, $resumePrompt)
            }
            else {
                $claudeArguments += @("--session-id", $state.sessionId, $initialPrompt)
            }

            @(
                "Claude Serena watchdog attempt $attempt",
                "Started: $((Get-Date).ToString('o'))",
                "Session: $($state.sessionId)",
                "Project: $resolvedProjectPath",
                ""
            ) | Set-Content -LiteralPath $logPath -Encoding UTF8

            Write-Status "Starting Claude attempt $attempt (session $($state.sessionId))." -Color Green
            $attemptStarted = [DateTime]::UtcNow
            $exitCode = 1

            try {
                & claude @claudeArguments 2>&1 | ForEach-Object {
                    $line = $_.ToString()
                    Write-Host $line
                    Add-Content -LiteralPath $logPath -Value $line -Encoding UTF8
                }
                $exitCode = $LASTEXITCODE
                if ($null -eq $exitCode) {
                    $exitCode = 0
                }
            }
            catch {
                $message = $_ | Out-String
                Write-Host $message -ForegroundColor Red
                Add-Content -LiteralPath $logPath -Value $message -Encoding UTF8
                $exitCode = 1
            }

            $state.sessionInitialized = $true
            $state.lastExitCode = $exitCode
            $state.lastLogPath = $logPath

            if ((Test-Path -LiteralPath $missionCompletePath) -or (Test-Path -LiteralPath $blockedPath)) {
                Save-State -State $state -Path $activeStatePath
                continue
            }

            $tail = Get-TailText -Path $logPath
            $failureClass = Get-FailureClass -Output $tail -ExitCode $exitCode
            $state.lastFailureClass = $failureClass
            $runDuration = [DateTime]::UtcNow - $attemptStarted

            if ($runDuration.TotalMinutes -ge 20 -or $failureClass -eq "normal") {
                $state.consecutiveErrors = 0
            }
            else {
                $state.consecutiveErrors = [int]$state.consecutiveErrors + 1
            }

            Save-State -State $state -Path $activeStatePath

            switch ($failureClass) {
                "authentication" {
                    Write-Status "Authentication failed. Run 'claude auth login', then rerun this script to resume." -Color Red
                    return
                }

                "billing" {
                    Write-Status "A billing or per-attempt budget limit stopped Claude. Resolve it or raise -MaxBudgetUsdPerAttempt, then rerun to resume." -Color Red
                    return
                }

                "missing-session" {
                    $oldSessionId = $state.sessionId
                    $state.sessionId = [Guid]::NewGuid().ToString()
                    $state.sessionInitialized = $false
                    Save-State -State $state -Path $activeStatePath
                    Write-Status "Session $oldSessionId could not be resumed. Created recovery session $($state.sessionId); Serena memory will restore state." -Color Yellow
                    $delaySeconds = 5
                }

                "quota" {
                    $power = [Math]::Min([int]$state.consecutiveErrors, 3)
                    $delayMinutes = [Math]::Min(120, $QuotaRetryMinutes * [Math]::Pow(1.5, $power))
                    $delaySeconds = [int][Math]::Ceiling($delayMinutes * 60)
                    Write-Status "Quota/rate limit detected. Retrying in $([Math]::Round($delayMinutes, 1)) minutes." -Color Yellow
                }

                "transient" {
                    $power = [Math]::Min([int]$state.consecutiveErrors, 5)
                    $delaySeconds = [int][Math]::Min(1800, 60 * [Math]::Pow(2, $power))
                    Write-Status "Transient service/network failure. Retrying in $delaySeconds seconds." -Color Yellow
                }

                "normal" {
                    $delaySeconds = $RestartDelaySeconds
                    Write-Status "Claude exited without a completion marker. Resuming in $delaySeconds seconds." -Color Yellow
                }

                default {
                    $power = [Math]::Min([int]$state.consecutiveErrors, 6)
                    $delaySeconds = [int][Math]::Min(1800, $RestartDelaySeconds * [Math]::Pow(2, $power))
                    Write-Status "Claude exited with code $exitCode. Retrying in $delaySeconds seconds." -Color Yellow
                }
            }

            $secondsRemaining = [Math]::Max(0, [int]($deadlineUtc - [DateTime]::UtcNow).TotalSeconds)
            $delaySeconds = [Math]::Min($delaySeconds, $secondsRemaining)
            while ($delaySeconds -gt 0) {
                if ((Test-Path -LiteralPath $globalStopPath) -or
                    (Test-Path -LiteralPath $runStopPath) -or
                    (Test-Path -LiteralPath $missionCompletePath) -or
                    (Test-Path -LiteralPath $blockedPath)) {
                    break
                }

                $sleepChunk = [Math]::Min(30, $delaySeconds)
                Start-Sleep -Seconds $sleepChunk
                $delaySeconds -= $sleepChunk
            }
        }

        if ([DateTime]::UtcNow -ge $deadlineUtc -and
            -not (Test-Path -LiteralPath $missionCompletePath) -and
            -not (Test-Path -LiteralPath $blockedPath)) {
            Write-Status "The configured work window ended. State remains resumable in Serena and $activeStatePath." -Color Yellow
        }
    }
    finally {
        Pop-Location
    }
}
finally {
    if ($hasMutex) {
        $mutex.ReleaseMutex()
    }
    $mutex.Dispose()
}
