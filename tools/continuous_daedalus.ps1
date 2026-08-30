<#
.SYNOPSIS
Install and operate the bounded Daedalus nomination loop as a per-user Windows task.

.DESCRIPTION
This script schedules the existing `python -m daedalus.loop` entrypoint. The
loop may pick, attempt, gate, and retain candidate artifacts, but it cannot merge
or promote them. Every scheduled run has explicit iteration, wall-clock, spend,
and per-candidate attempt bounds.

The task runs only in the current user's interactive session, at LIMITED run
level, with Task Scheduler's IgnoreNew policy. A human stop is sticky: scheduled
runs use `--arm` without `--force`, so a stop marker prevents every later run
from silently re-arming.

Windows ignores LIMITED for the built-in RID-500 Administrator account. Install
therefore refuses that principal before arming the kill switch or writing a task.

Examples:
  powershell -ExecutionPolicy Bypass -File tools/continuous_daedalus.ps1 Install
  powershell -ExecutionPolicy Bypass -File tools/continuous_daedalus.ps1 Status
  powershell -ExecutionPolicy Bypass -File tools/continuous_daedalus.ps1 RunOnce
  powershell -ExecutionPolicy Bypass -File tools/continuous_daedalus.ps1 Stop
  powershell -ExecutionPolicy Bypass -File tools/continuous_daedalus.ps1 Uninstall
#>

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('Install', 'Uninstall', 'Status', 'RunOnce', 'Start', 'Stop', 'Arm')]
    [string]$Action = 'Status',

    [string]$RepoRoot = '',
    [string]$Python = '',

    [ValidateRange(15, 1440)]
    [int]$IntervalMinutes = 60,

    [ValidateRange(1, 20)]
    [int]$MaxIterations = 3,

    [ValidateRange(60, 7200)]
    [int]$MaxWallClockSeconds = 1500,

    [ValidateRange(0.10, 100.00)]
    [double]$MaxSpendUsd = 1.00,

    [ValidateRange(1, 10)]
    [int]$MaxAttemptsPerCandidate = 1,

    [ValidateRange(1, 100)]
    [int]$QueueLimit = 25,

    [switch]$ForceRearm
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$TaskPath = '\Daedalus\'
$TaskName = 'GateLoop'
$FullTaskName = "${TaskPath}${TaskName}"

function Assert-SupportedTaskPrincipal {
    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    if ($identity.User.IsWellKnown(
            [System.Security.Principal.WellKnownSidType]::AccountAdministratorSid
        )) {
        throw (
            "REFUSED: $FullTaskName cannot be installed for the built-in " +
            "Administrator (RID 500). Windows ignores RunLevel=Limited for " +
            "that principal, and a filtered token can also fail registration " +
            "with 0x80070005. Sign in with a non-built-in operator account. " +
            "No kill-switch or Task Scheduler state was changed."
        )
    }
}

function Resolve-RepoRoot {
    param([string]$Value)

    if ([string]::IsNullOrWhiteSpace($Value)) {
        $Value = Join-Path $PSScriptRoot '..'
    }
    $resolved = (Resolve-Path -LiteralPath $Value).Path
    if (-not (Test-Path -LiteralPath (Join-Path $resolved '.git'))) {
        throw "RepoRoot is not a Git checkout: $resolved"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $resolved 'daedalus\loop.py'))) {
        throw "RepoRoot does not contain daedalus.loop: $resolved"
    }
    return $resolved
}

function Resolve-Python {
    param([string]$Value)

    if (-not [string]::IsNullOrWhiteSpace($Value)) {
        $candidate = (Resolve-Path -LiteralPath $Value).Path
    }
    else {
        $command = Get-Command python.exe -ErrorAction SilentlyContinue
        if ($null -eq $command) {
            $command = Get-Command python -ErrorAction SilentlyContinue
        }
        if ($null -eq $command) {
            throw 'Python was not found on PATH. Pass -Python C:\path\to\python.exe.'
        }
        $candidate = $command.Source
    }
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
        throw "Python executable does not exist: $candidate"
    }
    return $candidate
}

function Quote-TaskArgument {
    param([string]$Value)
    return '"' + ($Value -replace '"', '\"') + '"'
}

function New-LoopArgumentString {
    param([string]$Root)

    $spend = $MaxSpendUsd.ToString('0.00', [System.Globalization.CultureInfo]::InvariantCulture)
    $parts = @(
        '-m',
        'daedalus.loop',
        '--repo-root',
        (Quote-TaskArgument $Root),
        '--max-iterations',
        $MaxIterations,
        '--max-wall-clock-s',
        $MaxWallClockSeconds,
        '--max-spend-usd',
        $spend,
        '--max-attempts-per-candidate',
        $MaxAttemptsPerCandidate,
        '--queue-limit',
        $QueueLimit,
        '--json',
        '--arm'
    )
    return ($parts -join ' ')
}

function Invoke-DaedalusModule {
    param(
        [string]$PythonPath,
        [string]$Root,
        [string[]]$Arguments
    )

    Push-Location $Root
    try {
        # Capture the native success stream so the function returns exactly one
        # integer rather than an array containing program output plus exit code.
        # Write-Host keeps the operator-visible output out of the return stream.
        $output = & $PythonPath @Arguments 2>&1
        $exitCode = $LASTEXITCODE
        foreach ($line in $output) {
            Write-Host $line
        }
        return [int]$exitCode
    }
    finally {
        Pop-Location
    }
}

function Get-TaskOrNull {
    return Get-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName -ErrorAction SilentlyContinue
}

$ResolvedRepoRoot = Resolve-RepoRoot $RepoRoot
$ResolvedPython = Resolve-Python $Python
$LoopArguments = New-LoopArgumentString $ResolvedRepoRoot

switch ($Action) {
    'Install' {
        # This must precede both Task Scheduler writes and kill-switch arming.
        # A task labelled Limited but run as RID-500 Administrator is not a
        # limited task on Windows, so refusing is the only truthful outcome.
        Assert-SupportedTaskPrincipal
        Import-Module ScheduledTasks -ErrorAction Stop

        $scheduledAction = New-ScheduledTaskAction `
            -Execute $ResolvedPython `
            -Argument $LoopArguments `
            -WorkingDirectory $ResolvedRepoRoot

        # A finite repetition duration avoids the invalid TimeSpan::MaxValue
        # XML shape seen on newer Windows versions. Re-running Install refreshes
        # the 20-year horizon without changing task identity.
        $trigger = New-ScheduledTaskTrigger `
            -Once `
            -At ((Get-Date).AddMinutes(1)) `
            -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) `
            -RepetitionDuration (New-TimeSpan -Days 7300)

        $settings = New-ScheduledTaskSettingsSet `
            -StartWhenAvailable `
            -AllowStartIfOnBatteries `
            -DontStopIfGoingOnBatteries `
            -ExecutionTimeLimit (New-TimeSpan -Seconds ($MaxWallClockSeconds + 300)) `
            -MultipleInstances IgnoreNew

        $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
        $principal = New-ScheduledTaskPrincipal `
            -UserId $identity `
            -LogonType Interactive `
            -RunLevel Limited

        $task = New-ScheduledTask `
            -Action $scheduledAction `
            -Trigger $trigger `
            -Settings $settings `
            -Principal $principal `
            -Description 'Bounded Daedalus pick-attempt-gate-nominate loop. Never auto-merges or promotes.'

        # Construct the complete task before arming. That way a local cmdlet or
        # validation failure cannot leave an armed loop without an installed
        # task. Never override a prior human stop unless the operator supplied
        # -ForceRearm during this installation.
        $armArgs = @('-m', 'daedalus.spine.killswitch', 'arm')
        if ($ForceRearm) {
            $armArgs += '--force'
        }
        $armArgs += 'continuous Gate 0 to Gate 2 nomination loop'
        $armExit = Invoke-DaedalusModule $ResolvedPython $ResolvedRepoRoot $armArgs
        if ($armExit -ne 0) {
            throw "Kill switch did not arm (exit $armExit). A sticky human stop remains authoritative."
        }

        try {
            Register-ScheduledTask `
                -TaskPath $TaskPath `
                -TaskName $TaskName `
                -InputObject $task `
                -Force | Out-Null
        }
        catch {
            $registrationError = $_.Exception.Message.Trim()
            $stopExit = Invoke-DaedalusModule $ResolvedPython $ResolvedRepoRoot @(
                '-m', 'daedalus.spine.killswitch', 'stop',
                'continuous task registration failed'
            )
            if ($stopExit -ne 0) {
                throw (
                    "Task Scheduler registration failed and the fail-closed " +
                    "kill-switch stop also failed (exit $stopExit): " +
                    $registrationError
                )
            }
            throw (
                "Task Scheduler registration failed; the loop was left " +
                "STOPPED: " + $registrationError
            )
        }

        Write-Host "Installed $FullTaskName"
        Write-Host "Interval: $IntervalMinutes minute(s)"
        Write-Host "Bounds: iterations=$MaxIterations wall=${MaxWallClockSeconds}s spend=`$$($MaxSpendUsd.ToString('0.00')) attempts/candidate=$MaxAttemptsPerCandidate"
        Write-Host "Stop permanently: powershell -File tools/continuous_daedalus.ps1 Stop"
    }

    'Uninstall' {
        Import-Module ScheduledTasks -ErrorAction Stop
        $existing = Get-TaskOrNull
        if ($null -ne $existing) {
            Stop-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName -ErrorAction SilentlyContinue
            Unregister-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName -Confirm:$false
        }
        # Uninstall leaves the kill switch stopped. Reinstallation therefore
        # cannot resume silently without an explicit arm.
        $exit = Invoke-DaedalusModule $ResolvedPython $ResolvedRepoRoot @(
            '-m', 'daedalus.spine.killswitch', 'stop', 'continuous task uninstalled'
        )
        if ($exit -ne 0) {
            throw "Task was removed, but kill switch stop returned exit $exit."
        }
        Write-Host "Uninstalled $FullTaskName and left the loop stopped."
    }

    'Status' {
        Import-Module ScheduledTasks -ErrorAction Stop
        $existing = Get-TaskOrNull
        if ($null -eq $existing) {
            Write-Host "$FullTaskName is not installed."
        }
        else {
            $info = Get-ScheduledTaskInfo -TaskPath $TaskPath -TaskName $TaskName
            [pscustomobject]@{
                Task = $FullTaskName
                State = $existing.State
                LastRunTime = $info.LastRunTime
                LastTaskResult = $info.LastTaskResult
                NextRunTime = $info.NextRunTime
                Execute = $existing.Actions.Execute
                Arguments = $existing.Actions.Arguments
                WorkingDirectory = $existing.Actions.WorkingDirectory
                MultipleInstances = $existing.Settings.MultipleInstances
                ExecutionTimeLimit = $existing.Settings.ExecutionTimeLimit
            } | Format-List
        }
        [void](Invoke-DaedalusModule $ResolvedPython $ResolvedRepoRoot @(
            '-m', 'daedalus.spine.killswitch', 'status'
        ))
    }

    'RunOnce' {
        $args = @(
            '-m', 'daedalus.loop',
            '--repo-root', $ResolvedRepoRoot,
            '--max-iterations', [string]$MaxIterations,
            '--max-wall-clock-s', [string]$MaxWallClockSeconds,
            '--max-spend-usd', $MaxSpendUsd.ToString('0.00', [System.Globalization.CultureInfo]::InvariantCulture),
            '--max-attempts-per-candidate', [string]$MaxAttemptsPerCandidate,
            '--queue-limit', [string]$QueueLimit,
            '--json', '--arm'
        )
        exit (Invoke-DaedalusModule $ResolvedPython $ResolvedRepoRoot $args)
    }

    'Start' {
        Import-Module ScheduledTasks -ErrorAction Stop
        if ($null -eq (Get-TaskOrNull)) {
            throw "$FullTaskName is not installed."
        }
        Start-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName
        Write-Host "Started $FullTaskName."
    }

    'Stop' {
        Import-Module ScheduledTasks -ErrorAction Stop
        [void](Invoke-DaedalusModule $ResolvedPython $ResolvedRepoRoot @(
            '-m', 'daedalus.spine.killswitch', 'stop', 'operator stop via continuous_daedalus.ps1'
        ))
        Stop-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName -ErrorAction SilentlyContinue
        Write-Host "Stopped $FullTaskName. The sticky kill-switch marker blocks later scheduled runs."
    }

    'Arm' {
        $args = @('-m', 'daedalus.spine.killswitch', 'arm')
        if ($ForceRearm) {
            $args += '--force'
        }
        $args += 'operator arm via continuous_daedalus.ps1'
        exit (Invoke-DaedalusModule $ResolvedPython $ResolvedRepoRoot $args)
    }
}
