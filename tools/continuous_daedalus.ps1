<#
.SYNOPSIS
Install and operate the bounded Daedalus nomination loop as a per-user Windows task.

.DESCRIPTION
This script remains the sole Windows Task Scheduler owner. Without
-CampaignFile it schedules the existing `python -m daedalus.loop` entrypoint.
With -CampaignFile it schedules `tools/gardener_campaign.py`, a small guard that
checks Europe/Berlin time and curated-queue convergence before invoking the same
canonical loop.

The task runs in the current interactive session at LIMITED run level with
IgnoreNew overlap policy. A human stop is sticky. Nothing here merges, pushes,
promotes, issues OwnerApproval, or mutates the primary checkout.
#>

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('Install', 'Uninstall', 'Status', 'RunOnce', 'Start', 'Stop', 'Arm')]
    [string]$Action = 'Status',

    [string]$RepoRoot = '',
    [string]$Python = '',
    [string]$CampaignFile = '',

    [ValidatePattern('^[A-Za-z0-9._-]{1,100}$')]
    [string]$ScheduledTaskName = 'GateLoop',

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
$TaskName = $ScheduledTaskName
$FullTaskName = "${TaskPath}${TaskName}"
$BerlinTimeZoneId = 'W. Europe Standard Time'

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
        if ($null -eq $command) { $command = Get-Command python -ErrorAction SilentlyContinue }
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

function Convert-BerlinDateToLocalTime {
    param([datetime]$BerlinDate)
    $berlin = [System.TimeZoneInfo]::FindSystemTimeZoneById($BerlinTimeZoneId)
    $unspecified = [datetime]::SpecifyKind($BerlinDate.Date, [System.DateTimeKind]::Unspecified)
    $utc = [System.TimeZoneInfo]::ConvertTimeToUtc($unspecified, $berlin)
    return $utc.ToLocalTime()
}

function Resolve-Campaign {
    param([string]$Root, [string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value)) { return $null }

    $candidate = $Value
    if (-not [System.IO.Path]::IsPathRooted($candidate)) {
        $candidate = Join-Path $Root $candidate
    }
    $path = (Resolve-Path -LiteralPath $candidate).Path
    $rootPrefix = $Root.TrimEnd('\') + '\'
    if (-not $path.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "CampaignFile must remain inside RepoRoot: $path"
    }

    $document = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($document.schema -ne 'daedalus-gardener-campaign/1') {
        throw "Unsupported campaign schema: $($document.schema)"
    }
    if ($document.timezone -ne 'Europe/Berlin') {
        throw 'Campaign timezone must be Europe/Berlin.'
    }
    if ($document.work_until_date_exclusive -ne $document.final_report_date) {
        throw 'Campaign final date must equal the first non-working date.'
    }

    $berlinDate = [datetime]::ParseExact(
        [string]$document.work_until_date_exclusive,
        'yyyy-MM-dd',
        [System.Globalization.CultureInfo]::InvariantCulture
    )
    $cutoffLocal = Convert-BerlinDateToLocalTime $berlinDate
    $interval = [int]$document.schedule.interval_minutes
    if ($interval -lt 15 -or $interval -gt 1440) {
        throw "Campaign interval is outside 15..1440 minutes: $interval"
    }
    $wallSeconds = [int]$document.activation_bounds.max_wall_clock_s
    if ($wallSeconds -lt 60 -or $wallSeconds -gt 7200) {
        throw "Campaign wall-clock bound is outside 60..7200 seconds: $wallSeconds"
    }
    return [pscustomobject]@{
        Path = $path
        Document = $document
        BerlinCutoffDate = $berlinDate.Date
        CutoffLocal = $cutoffLocal
        IntervalMinutes = $interval
        WallSeconds = $wallSeconds
    }
}

function Quote-TaskArgument {
    param([string]$Value)
    return '"' + ($Value -replace '"', '\"') + '"'
}

function New-LoopArgumentString {
    param([string]$Root, $Campaign)

    if ($null -ne $Campaign) {
        $guard = Join-Path $Root 'tools\gardener_campaign.py'
        if (-not (Test-Path -LiteralPath $guard -PathType Leaf)) {
            throw "Campaign guard is missing: $guard"
        }
        return (@(
            (Quote-TaskArgument $guard),
            'run',
            '--repo-root',
            (Quote-TaskArgument $Root),
            '--campaign',
            (Quote-TaskArgument $Campaign.Path)
        ) -join ' ')
    }

    $spend = $MaxSpendUsd.ToString('0.00', [System.Globalization.CultureInfo]::InvariantCulture)
    return (@(
        '-m', 'daedalus.loop',
        '--repo-root', (Quote-TaskArgument $Root),
        '--max-iterations', $MaxIterations,
        '--max-wall-clock-s', $MaxWallClockSeconds,
        '--max-spend-usd', $spend,
        '--max-attempts-per-candidate', $MaxAttemptsPerCandidate,
        '--queue-limit', $QueueLimit,
        '--json', '--arm'
    ) -join ' ')
}

function Invoke-DaedalusModule {
    param([string]$PythonPath, [string]$Root, [string[]]$Arguments)
    Push-Location $Root
    try {
        $output = & $PythonPath @Arguments 2>&1
        $exitCode = $LASTEXITCODE
        foreach ($line in $output) { Write-Host $line }
        return [int]$exitCode
    }
    finally { Pop-Location }
}

function Get-TaskOrNull {
    return Get-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName -ErrorAction SilentlyContinue
}

$ResolvedRepoRoot = Resolve-RepoRoot $RepoRoot
$ResolvedPython = Resolve-Python $Python
$ResolvedCampaign = Resolve-Campaign $ResolvedRepoRoot $CampaignFile
$LoopArguments = New-LoopArgumentString $ResolvedRepoRoot $ResolvedCampaign

switch ($Action) {
    'Install' {
        Import-Module ScheduledTasks -ErrorAction Stop
        if ($null -ne $ResolvedCampaign) {
            if ($ResolvedCampaign.CutoffLocal -le (Get-Date)) {
                throw "Campaign cutoff has passed: $($ResolvedCampaign.BerlinCutoffDate.ToString('yyyy-MM-dd')) Europe/Berlin"
            }
            $guardExit = Invoke-DaedalusModule $ResolvedPython $ResolvedRepoRoot @(
                (Join-Path $ResolvedRepoRoot 'tools\gardener_campaign.py'),
                'status', '--repo-root', $ResolvedRepoRoot,
                '--campaign', $ResolvedCampaign.Path
            )
            if ($guardExit -ne 0) {
                throw "Campaign guard refused installation (exit $guardExit)."
            }
        }

        $armArgs = @('-m', 'daedalus.spine.killswitch', 'arm')
        if ($ForceRearm) { $armArgs += '--force' }
        $armArgs += 'continuous bounded Daedalus nomination loop'
        $armExit = Invoke-DaedalusModule $ResolvedPython $ResolvedRepoRoot $armArgs
        if ($armExit -ne 0) {
            throw "Kill switch did not arm (exit $armExit). A sticky human stop remains authoritative."
        }

        $scheduledAction = New-ScheduledTaskAction `
            -Execute $ResolvedPython `
            -Argument $LoopArguments `
            -WorkingDirectory $ResolvedRepoRoot

        $start = (Get-Date).AddMinutes(1)
        if ($null -eq $ResolvedCampaign) {
            $trigger = New-ScheduledTaskTrigger `
                -Once -At $start `
                -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) `
                -RepetitionDuration (New-TimeSpan -Days 7300)
            $triggers = @($trigger)
            $executionLimit = $MaxWallClockSeconds + 300
        }
        else {
            $minutes = [math]::Max(1, [int](($ResolvedCampaign.CutoffLocal - $start).TotalMinutes))
            $repeat = New-ScheduledTaskTrigger `
                -Once -At $start `
                -RepetitionInterval (New-TimeSpan -Minutes $ResolvedCampaign.IntervalMinutes) `
                -RepetitionDuration (New-TimeSpan -Minutes $minutes)
            $final = New-ScheduledTaskTrigger -Once -At $ResolvedCampaign.CutoffLocal
            $triggers = @($repeat, $final)
            $executionLimit = $ResolvedCampaign.WallSeconds + 600
        }

        $settings = New-ScheduledTaskSettingsSet `
            -StartWhenAvailable `
            -AllowStartIfOnBatteries `
            -DontStopIfGoingOnBatteries `
            -ExecutionTimeLimit (New-TimeSpan -Seconds $executionLimit) `
            -MultipleInstances IgnoreNew

        $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
        $principal = New-ScheduledTaskPrincipal `
            -UserId $identity `
            -LogonType Interactive `
            -RunLevel Limited

        $task = New-ScheduledTask `
            -Action $scheduledAction `
            -Trigger $triggers `
            -Settings $settings `
            -Principal $principal `
            -Description 'Bounded Daedalus pick-attempt-gate-nominate loop. Never automatic merge or promotion.'

        Register-ScheduledTask `
            -TaskPath $TaskPath `
            -TaskName $TaskName `
            -InputObject $task `
            -Force | Out-Null

        Write-Host "Installed $FullTaskName"
        Write-Host "Arguments: $LoopArguments"
        if ($null -ne $ResolvedCampaign) {
            Write-Host "Campaign cutoff: $($ResolvedCampaign.BerlinCutoffDate.ToString('yyyy-MM-dd')) 00:00 Europe/Berlin"
            Write-Host "Local trigger: $($ResolvedCampaign.CutoffLocal.ToString('yyyy-MM-dd HH:mm:ss zzz'))"
            Write-Host "Interval: $($ResolvedCampaign.IntervalMinutes) minute(s); final trigger installed"
        }
        else {
            Write-Host "Interval: $IntervalMinutes minute(s)"
            Write-Host "Bounds: iterations=$MaxIterations wall=${MaxWallClockSeconds}s spend=`$$($MaxSpendUsd.ToString('0.00')) attempts/candidate=$MaxAttemptsPerCandidate"
        }
    }

    'Uninstall' {
        Import-Module ScheduledTasks -ErrorAction Stop
        if ($null -ne (Get-TaskOrNull)) {
            Stop-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName -ErrorAction SilentlyContinue
            Unregister-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName -Confirm:$false
        }
        $exit = Invoke-DaedalusModule $ResolvedPython $ResolvedRepoRoot @(
            '-m', 'daedalus.spine.killswitch', 'stop', 'continuous task uninstalled'
        )
        if ($exit -ne 0) { throw "Kill switch stop returned exit $exit." }
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
                TriggerCount = @($existing.Triggers).Count
                MultipleInstances = $existing.Settings.MultipleInstances
                ExecutionTimeLimit = $existing.Settings.ExecutionTimeLimit
            } | Format-List
        }
        if ($null -ne $ResolvedCampaign) {
            [void](Invoke-DaedalusModule $ResolvedPython $ResolvedRepoRoot @(
                (Join-Path $ResolvedRepoRoot 'tools\gardener_campaign.py'),
                'status', '--repo-root', $ResolvedRepoRoot,
                '--campaign', $ResolvedCampaign.Path
            ))
        }
        [void](Invoke-DaedalusModule $ResolvedPython $ResolvedRepoRoot @(
            '-m', 'daedalus.spine.killswitch', 'status'
        ))
    }

    'RunOnce' {
        if ($null -ne $ResolvedCampaign) {
            exit (Invoke-DaedalusModule $ResolvedPython $ResolvedRepoRoot @(
                (Join-Path $ResolvedRepoRoot 'tools\gardener_campaign.py'),
                'run', '--repo-root', $ResolvedRepoRoot,
                '--campaign', $ResolvedCampaign.Path
            ))
        }
        exit (Invoke-DaedalusModule $ResolvedPython $ResolvedRepoRoot @(
            '-m', 'daedalus.loop',
            '--repo-root', $ResolvedRepoRoot,
            '--max-iterations', [string]$MaxIterations,
            '--max-wall-clock-s', [string]$MaxWallClockSeconds,
            '--max-spend-usd', $MaxSpendUsd.ToString('0.00', [System.Globalization.CultureInfo]::InvariantCulture),
            '--max-attempts-per-candidate', [string]$MaxAttemptsPerCandidate,
            '--queue-limit', [string]$QueueLimit,
            '--json', '--arm'
        ))
    }

    'Start' {
        Import-Module ScheduledTasks -ErrorAction Stop
        if ($null -eq (Get-TaskOrNull)) { throw "$FullTaskName is not installed." }
        Start-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName
        Write-Host "Started $FullTaskName."
    }

    'Stop' {
        Import-Module ScheduledTasks -ErrorAction Stop
        [void](Invoke-DaedalusModule $ResolvedPython $ResolvedRepoRoot @(
            '-m', 'daedalus.spine.killswitch', 'stop', 'operator stop via continuous_daedalus.ps1'
        ))
        Stop-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName -ErrorAction SilentlyContinue
        Write-Host "Stopped $FullTaskName. The sticky kill switch blocks later runs."
    }

    'Arm' {
        $args = @('-m', 'daedalus.spine.killswitch', 'arm')
        if ($ForceRearm) { $args += '--force' }
        $args += 'operator arm via continuous_daedalus.ps1'
        exit (Invoke-DaedalusModule $ResolvedPython $ResolvedRepoRoot $args)
    }
}
