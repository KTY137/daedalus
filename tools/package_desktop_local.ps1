# Local, owner-invoked wrapper around the documented desktop build commands.
# Use an isolated source copy for unattended builds. This does not publish,
# install, tag, commit, merge, schedule tasks, or create a runtime entrypoint.
[CmdletBinding()]
param(
    [string]$SourceRoot = '',
    [string]$OutputRoot = (Join-Path $env:LOCALAPPDATA 'Daedalus/packages'),
    [string]$CacheRoot = '',
    [ValidatePattern('^\d+\.\d+\.\d+$')][string]$ExpectedVersion = '0.1.6',
    [ValidateSet('x86_64-pc-windows-gnu', 'x86_64-pc-windows-msvc')]
    [string]$Target = 'x86_64-pc-windows-gnu',
    [switch]$PreflightOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if (-not $SourceRoot) { $SourceRoot = Split-Path -Parent $PSScriptRoot }
$source = (Resolve-Path -LiteralPath $SourceRoot).Path
$output = [System.IO.Path]::GetFullPath($OutputRoot)
$cache = if ($CacheRoot) { [System.IO.Path]::GetFullPath($CacheRoot) } else { Join-Path $output "cache/$Target" }
$web = Join-Path $source 'apps/web'
$tauri = Join-Path $web 'src-tauri'
$steps = [System.Collections.Generic.List[object]]::new()
$utf8 = [System.Text.UTF8Encoding]::new($false)

function Read-Json([string]$Path) {
    return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Read-Version([string]$Path, [string]$Pattern) {
    $match = [regex]::Match((Get-Content -LiteralPath $Path -Raw -Encoding UTF8), $Pattern)
    if (-not $match.Success) { throw "Cannot read package version: $Path" }
    return $match.Groups[1].Value
}

function Capture([string]$File, [string[]]$Arguments) {
    $output = & $File @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Preflight command failed: $File ($LASTEXITCODE)" }
    return ($output -join "`n").Trim()
}

function Require-Command([string]$Name) {
    $command = Get-Command $Name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $command) { throw "Required executable is unavailable: $Name" }
    return $command.Source
}

function Get-SmokePort {
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
    $listener.Server.ExclusiveAddressUse = $true
    try {
        $listener.Start()
        return $listener.LocalEndpoint.Port
    }
    finally { $listener.Stop() }
}

$npm = Require-Command 'npm.cmd'
$node = Require-Command 'node.exe'
$uv = Require-Command 'uv.exe'
$cargo = Require-Command 'cargo.exe'
$rustc = Require-Command 'rustc.exe'
$rustup = Require-Command 'rustup.exe'
$python = Capture $uv @('python', 'find', '3.12', '--no-python-downloads')
$pythonVersion = Capture $python @('--version')
$uvVersion = Capture $uv @('--version')
$nodeVersion = Capture $node @('--version')
$rustVersion = Capture $rustc @('--version')
$installedTargets = Capture $rustup @('target', 'list', '--installed')
if ($pythonVersion -notmatch '^Python 3\.12\.') { throw "Python 3.12 required; found $pythonVersion" }
if ($uvVersion -notmatch '^uv 0\.11\.26\b') { throw "uv 0.11.26 required; found $uvVersion" }
if ($rustVersion -notmatch '^rustc 1\.97\.1\b') { throw "Rust 1.97.1 required; found $rustVersion" }
if ([int]($nodeVersion.TrimStart('v').Split('.')[0]) -lt 22) { throw "Node 22 or newer required; found $nodeVersion" }
if ($installedTargets.Split("`n").Trim() -notcontains $Target) { throw "Rust target is not installed: $Target" }
if ($Target.EndsWith('-gnu')) { $null = Require-Command 'gcc.exe' }
if ($Target.EndsWith('-msvc')) {
    $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe'
    if (-not (Test-Path -LiteralPath $vswhere)) { throw 'MSVC build tools are unavailable: vswhere.exe missing.' }
    $visualStudio = Capture $vswhere @('-latest', '-products', '*', '-requires', 'Microsoft.VisualStudio.Component.VC.Tools.x86.x64', '-property', 'installationPath')
    if (-not $visualStudio) { throw 'Visual Studio C++ build tools are not installed.' }
}

$package = Read-Json (Join-Path $web 'package.json')
$config = Read-Json (Join-Path $tauri 'tauri.conf.json')
$versions = [ordered]@{
    python = Read-Version (Join-Path $source 'pyproject.toml') '(?ms)^\[project\]\s*\r?\n.*?^version = "([^"]+)"'
    pythonLock = Read-Version (Join-Path $source 'uv.lock') '(?m)^name = "daedalus"\r?\nversion = "([^"]+)"'
    npm = $package.version
    # Windows PowerShell 5.1 cannot deserialize JSON objects with an empty key.
    npmLock = Read-Version (Join-Path $web 'package-lock.json') '"version"\s*:\s*"([^"]+)"'
    npmLockRoot = Read-Version (Join-Path $web 'package-lock.json') '(?s)"packages"\s*:\s*\{\s*""\s*:\s*\{.*?"version"\s*:\s*"([^"]+)"'
    cargo = Read-Version (Join-Path $tauri 'Cargo.toml') '(?ms)^\[package\]\s*\r?\n.*?^version = "([^"]+)"'
    cargoLock = Read-Version (Join-Path $tauri 'Cargo.lock') '(?m)^name = "daedalus-desktop"\r?\nversion = "([^"]+)"'
    tauri = $config.version
}
foreach ($entry in $versions.GetEnumerator()) {
    if ($entry.Value -ne $ExpectedVersion) { throw "Version mismatch: $($entry.Key) is $($entry.Value), expected $ExpectedVersion" }
}
if ($config.productName -ne 'Daedalus' -or $config.identifier -ne 'dev.daedalus.desktop') { throw 'Unexpected desktop installation identity.' }
if ($config.bundle.createUpdaterArtifacts) { throw 'Local packaging expects updater artifacts disabled.' }
if ($package.devDependencies.'@tauri-apps/cli' -ne '2.11.4') { throw 'Expected locked Tauri CLI 2.11.4.' }
foreach ($relative in @('tools/build_tauri_sidecar.py', 'tools/smoke_tauri_sidecar.py', 'scripts/daedalus_desktop_sidecar.py', 'apps/web/src-tauri/icons/icon.svg')) {
    if (-not (Test-Path -LiteralPath (Join-Path $source $relative) -PathType Leaf)) { throw "Missing canonical packaging input: $relative" }
}

$preflight = [ordered]@{
    schema = 'daedalus-local-package-preflight/1'
    source = $source
    cache = $cache
    version = $ExpectedVersion
    target = $Target
    versions = $versions
    toolchain = [ordered]@{ python = $pythonVersion; pythonExecutable = $python; uv = $uvVersion; node = $nodeVersion; rust = $rustVersion; tauri = '2.11.4' }
    ciDifferences = @($(if ($Target.EndsWith('-gnu')) { 'Local Windows GNU target; CI uses Windows MSVC.' }), $(if ($nodeVersion -notmatch '^v22\.') { 'Local Node differs from the CI Node 22 series.' })) | Where-Object { $_ }
    signing = 'Unsigned local Windows package; updater artifacts disabled.'
    smokePort = 'OS-selected loopback port at smoke time; desktop port remains unchanged.'
}
if ($PreflightOnly) { $preflight | ConvertTo-Json -Depth 8; exit 0 }

$runName = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ') + '-' + [guid]::NewGuid().ToString('N').Substring(0, 8)
$run = Join-Path $output ($ExpectedVersion + '/' + $runName)
$null = New-Item -ItemType Directory -Path $run
$logs = Join-Path $run 'logs'
$null = New-Item -ItemType Directory -Path $logs
$receiptPath = Join-Path $run 'result.json'
$receipt = [ordered]@{
    schema = 'daedalus-local-package-result/1'; status = 'running'; startedUtc = [DateTime]::UtcNow.ToString('o')
    preflight = $preflight; output = $run; stages = $steps; smokePort = $null; artifact = $null; error = $null
}

function Write-Receipt {
    [System.IO.File]::WriteAllText($receiptPath, ($receipt | ConvertTo-Json -Depth 10), $utf8)
}

function Invoke-Stage([string]$Name, [string]$Directory, [string]$Executable, [string[]]$Arguments) {
    $log = Join-Path $logs ($Name + '.log')
    $stage = [ordered]@{ name = $Name; startedUtc = [DateTime]::UtcNow.ToString('o'); exitCode = $null; log = $log }
    $steps.Add($stage)
    [System.IO.File]::WriteAllText($log, "Stage: $Name`r`nStarted UTC: $($stage.startedUtc)`r`n", $utf8)
    Write-Receipt
    Write-Output "[$Name] $Executable $($Arguments -join ' ')"
    Push-Location -LiteralPath $Directory
    $oldPreference = $ErrorActionPreference
    $logWriter = $null
    try {
        $logWriter = [System.IO.StreamWriter]::new($log, $true, $utf8)
        $logWriter.AutoFlush = $true
        # Native tools commonly write progress on stderr. Their exit code,
        # rather than PowerShell's NativeCommandError stream, determines success.
        $ErrorActionPreference = 'Continue'
        & $Executable @Arguments 2>&1 | ForEach-Object {
            $line = "$_"
            $logWriter.WriteLine($line)
            Write-Output $line
        }
        $nativeExit = $LASTEXITCODE
    }
    finally {
        if ($null -ne $logWriter) { $logWriter.Dispose() }
        $ErrorActionPreference = $oldPreference
        Pop-Location
    }
    $stage.exitCode = $nativeExit
    $stage['finishedUtc'] = [DateTime]::UtcNow.ToString('o')
    Write-Receipt
    if ($nativeExit -ne 0) { throw "Stage $Name failed with exit code $nativeExit; see $log" }
}

$environmentNames = @('UV_PROJECT_ENVIRONMENT', 'CARGO_TARGET_DIR', 'PYTHONIOENCODING', 'PYTHONUTF8', 'CI')
$previousEnvironment = @{}
foreach ($name in $environmentNames) { $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }
$cacheLock = $null
try {
    $null = New-Item -ItemType Directory -Path $cache -Force
    $lockPath = Join-Path $cache 'package.lock'
    try {
        $cacheLock = [System.IO.File]::Open($lockPath, [System.IO.FileMode]::OpenOrCreate,
            [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
    }
    catch [System.IO.IOException] {
        throw "Cannot acquire exclusive packaging cache lock at $lockPath. Another build may be using this cache. $($_.Exception.Message)"
    }
    $lockBytes = $utf8.GetBytes("PID=$PID`r`nSource=$source`r`nStartedUtc=$([DateTime]::UtcNow.ToString('o'))`r`n")
    $cacheLock.SetLength(0)
    $cacheLock.Write($lockBytes, 0, $lockBytes.Length)
    $cacheLock.Flush()
    $env:UV_PROJECT_ENVIRONMENT = Join-Path $cache 'python'
    $env:CARGO_TARGET_DIR = Join-Path $cache 'cargo-target'
    $env:PYTHONIOENCODING = 'utf-8'
    $env:PYTHONUTF8 = '1'
    $env:CI = 'true'
    Write-Receipt
    Invoke-Stage '01-npm-ci' $web $npm @('ci', '--no-audit', '--no-fund')
    Invoke-Stage '02-web-app-tests' $web $npm @('run', 'test:app')
    Invoke-Stage '03-web-motion-tests' $web $npm @('run', 'test:motion')
    Invoke-Stage '04-web-build' $web $npm @('run', 'build')
    Invoke-Stage '05-python-sync' $source $uv @('sync', '--locked', '--python', $python, '--extra', 'test', '--extra', 'desktop-build', '--no-extra', 'gpu', '--no-extra', 'computer')
    $buildPython = Join-Path $env:UV_PROJECT_ENVIRONMENT 'Scripts/python.exe'
    Invoke-Stage '06-desktop-contracts' $source $buildPython @('-m', 'pytest', '-q', 'tests/test_desktop_packaging.py', 'tests/test_desktop_runtime.py', 'tests/test_desktop_startup_nonce.py', 'tests/test_project_registration.py')
    Invoke-Stage '07-sidecar-build' $source $buildPython @('tools/build_tauri_sidecar.py', '--target', $Target)
    $receipt.smokePort = Get-SmokePort
    Invoke-Stage '08-sidecar-smoke' $source $buildPython @('tools/smoke_tauri_sidecar.py', '--port', [string]$receipt.smokePort)
    Invoke-Stage '09-desktop-icons' $web $npm @('exec', '--', 'tauri', 'icon', 'src-tauri/icons/icon.svg')
    Invoke-Stage '10-rust-format' $source $cargo @('fmt', '--manifest-path', 'apps/web/src-tauri/Cargo.toml', '--', '--check')
    Invoke-Stage '11-rust-tests' $source $cargo @('test', '--manifest-path', 'apps/web/src-tauri/Cargo.toml', '--lib', '--locked', '--target', $Target)
    $bundleStarted = [DateTime]::UtcNow
    Invoke-Stage '12-windows-installer' $web $npm @('exec', '--', 'tauri', 'build', '--target', $Target, '--bundles', 'nsis', '--ci')
    $installerName = "Daedalus_${ExpectedVersion}_x64-setup.exe"
    $installer = Join-Path $env:CARGO_TARGET_DIR "$Target/release/bundle/nsis/$installerName"
    if (-not (Test-Path -LiteralPath $installer -PathType Leaf)) { throw "Expected installer missing: $installer" }
    $installerInfo = Get-Item -LiteralPath $installer
    if ($installerInfo.Length -lt 1MB -or $installerInfo.LastWriteTimeUtc -lt $bundleStarted.AddSeconds(-2)) { throw 'Installer is empty, implausibly small, or stale.' }
    $destination = Join-Path $run $installerName
    Copy-Item -LiteralPath $installer -Destination $destination
    $receipt.artifact = [ordered]@{
        path = $destination; bytes = (Get-Item -LiteralPath $destination).Length
        sha256 = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant()
        backendBundleId = (Get-Content -LiteralPath (Join-Path $tauri 'backend/BUNDLE_ID') -Raw).Trim()
        signature = (Get-AuthenticodeSignature -LiteralPath $destination).Status.ToString()
    }
    $receipt.status = 'complete'
    Write-Output "Local installer created: $destination"
}
catch {
    $receipt.status = 'failed'
    $receipt.error = $_.Exception.Message
    Write-Error -Message $receipt.error -ErrorAction Continue
}
finally {
    try {
        $receipt['finishedUtc'] = [DateTime]::UtcNow.ToString('o')
        Write-Receipt
    }
    finally {
        if ($null -ne $cacheLock) { $cacheLock.Dispose() }
        foreach ($name in $environmentNames) { [Environment]::SetEnvironmentVariable($name, $previousEnvironment[$name], 'Process') }
    }
}
Write-Output "Package result: $receiptPath"
if ($receipt.status -ne 'complete') { exit 1 }
