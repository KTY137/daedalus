# Gate-0 Produktions-Attestation -- Owner-run, ein Befehl.
#
#   .\docs\recovery\gate0_production_attest.ps1 -RunDir runs\gate0-closure-20260818
#
# Laedt die drei Produktions-Keys aus der Owner-Custody
# (%USERPROFILE%\.daedalus-keys\gate0-runtime-fault\, gemintet per
# production_key_ceremony_kit.py), attestiert alle drei Spalten des
# angegebenen Laufs mit --key-class production, erzeugt das Gesamt-Verdikt
# in einem Discovery-sichtbaren runs\gate0-matrix-* Verzeichnis und
# schliesst mit dem Gate-Report gegen die frischen Conformance-Receipts ab.
# Die Schluessel verlassen diese Shell nicht: sie werden in Prozess-Env
# geladen, nie gedruckt, nie an Agenten gereicht.
#
# Voraussetzung: der Lauf wurde vorher von der Koordinatorin gesammelt
# (fixture/ + linux-host/ + live/ + conformance/receipts/ mit Observations
# bei EINER Revision; receipt.json im Lauf nennt sie als source_revision).
#
# Validiert am 2026-08-18 gegen die echten CLIs bei bcc0feaf (argparse) und
# per Trockentest mit Wegwerf-Dev-Keys in einer Scratch-Kopie des Laufs.

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$RunDir,

    # Revision, bei der die Observations gesammelt wurden. Default: aus
    # receipt.json des Laufs -- NICHT aus HEAD, denn die Attestation laeuft
    # nach dem Evidence-Commit und HEAD ist dann eine andere Revision.
    [string]$SourceRevision = "",

    [string]$KeyDir = "$env:USERPROFILE\.daedalus-keys\gate0-runtime-fault",

    # Discovery-sichtbares Verdikt-Verzeichnis. Der Gate-Report findet
    # Verdikte nur unter runs\gate0-matrix-* (discover_whole_matrix_verdicts,
    # daedalus/runtimes/whole_fault_matrix.py) -- ein Verdikt im Closure-Lauf
    # selbst bliebe fuer den Report unsichtbar.
    [string]$MatrixDir = "runs\gate0-matrix-20260818-closure",

    # production ist der Ernstfall. development existiert nur, damit die
    # Wrapper-Logik mit Wegwerf-Keys ausserhalb von runs/ trocken getestet
    # werden kann; es erklaert keine Custody, die nicht existiert.
    [ValidateSet("development", "production")]
    [string]$KeyClass = "production"
)

$ErrorActionPreference = "Stop"

# Das Skript ist mit dem Code versioniert, den es ruft: Repo-Root ist zwei
# Ebenen ueber docs\recovery\, unabhaengig davon, wie der Checkout heisst.
Set-Location -Path (Resolve-Path (Join-Path $PSScriptRoot "..\.."))
$repoRoot = (Get-Location).Path

function Resolve-UnderRoot([string]$path) {
    if ([System.IO.Path]::IsPathRooted($path)) { return $path }
    return (Join-Path $repoRoot $path)
}

if (-not (Test-Path -LiteralPath $RunDir -PathType Container)) {
    throw "RunDir nicht gefunden: $RunDir (erst sammeln lassen, dann attestieren)"
}
foreach ($column in @("fixture", "linux-host", "live")) {
    if (-not (Test-Path -LiteralPath (Join-Path $RunDir $column))) {
        throw "Spalte fehlt im Lauf: $RunDir\$column"
    }
}
$conformanceReceipts = Join-Path $RunDir "conformance\receipts"
if (-not (Test-Path -LiteralPath $conformanceReceipts -PathType Container)) {
    throw "Conformance-Receipts fehlen im Lauf: $conformanceReceipts"
}
foreach ($keyFile in @("deterministic-fixture.key", "linux-host.key", "live-runtime.key")) {
    if (-not (Test-Path -LiteralPath (Join-Path $KeyDir $keyFile))) {
        throw "Key fehlt in der Custody: $KeyDir\$keyFile -- Zeremonie-Kit erneut ausfuehren?"
    }
}

if ([string]::IsNullOrWhiteSpace($SourceRevision)) {
    $runReceiptPath = Join-Path $RunDir "receipt.json"
    if (Test-Path -LiteralPath $runReceiptPath) {
        $SourceRevision = (Get-Content -Raw $runReceiptPath | ConvertFrom-Json).source_revision
        Write-Host "SourceRevision aus $runReceiptPath : $SourceRevision"
    } else {
        $SourceRevision = (git rev-parse HEAD).Trim()
        Write-Warning "Kein receipt.json im Lauf; SourceRevision aus HEAD: $SourceRevision"
        Write-Warning "Wenn seit der Sammlung committet wurde, ist HEAD die FALSCHE Revision."
    }
}

# Issuer-Identitaeten sind pro Spalte getrennt; eine Fixture-Signatur ueber
# eine andere Autoritaet wird von Issuer und Verifier verweigert.
$fixtureIssuer = "issuer.gate0-fixture-$KeyClass"
$fixtureKeyId  = "gate0-fixture-$KeyClass-key"
$hostIssuer    = "issuer.gate0-linux-host-$KeyClass"
$hostKeyId     = "gate0-linux-host-$KeyClass-key"
$liveIssuer    = "issuer.gate0-live-runtime-$KeyClass"
$liveKeyId     = "gate0-live-runtime-$KeyClass-key"

# Keys laden -- nur in dieser Shell, niemals echoen.
$env:DAEDALUS_FIXTURE_FAULT_KEY = (Get-Content -Raw (Join-Path $KeyDir "deterministic-fixture.key")).Trim()
$env:DAEDALUS_HOST_FAULT_KEY    = (Get-Content -Raw (Join-Path $KeyDir "linux-host.key")).Trim()
$env:DAEDALUS_LIVE_FAULT_KEY    = (Get-Content -Raw (Join-Path $KeyDir "live-runtime.key")).Trim()

try {
    Write-Host "[1/6] Fixture-Spalte attestieren ($KeyClass)..." -ForegroundColor Cyan
    python -m daedalus.runtimes.fixture_fault_attestation_issuer issue `
        --run-dir (Join-Path $RunDir "fixture") --source-revision $SourceRevision `
        --issuer-id $fixtureIssuer --key-id $fixtureKeyId `
        --fixture-key-env DAEDALUS_FIXTURE_FAULT_KEY --key-class $KeyClass `
        --output (Join-Path $RunDir "fixture-attestations.json")
    if ($LASTEXITCODE -ne 0) { throw "Fixture-Attestation refused (exit $LASTEXITCODE)" }

    Write-Host "[2/6] Linux-Host-Spalte attestieren ($KeyClass)..." -ForegroundColor Cyan
    python -m daedalus.runtimes.fault_attestation_issuer issue `
        --run-dir (Join-Path $RunDir "linux-host") --source-revision $SourceRevision `
        --issuer-id $hostIssuer --key-id $hostKeyId `
        --key-env DAEDALUS_HOST_FAULT_KEY --key-class $KeyClass `
        --output (Join-Path $RunDir "linux-host-attestations.json")
    if ($LASTEXITCODE -ne 0) { throw "Host-Attestation refused (exit $LASTEXITCODE)" }

    Write-Host "[3/6] Live-Spalte attestieren ($KeyClass)..." -ForegroundColor Cyan
    python -m daedalus.runtimes.live_fault_attestation_issuer issue `
        --run-dir (Join-Path $RunDir "live") --source-revision $SourceRevision `
        --issuer-id $liveIssuer --key-id $liveKeyId `
        --live-key-env DAEDALUS_LIVE_FAULT_KEY --key-class $KeyClass `
        --output (Join-Path $RunDir "live-attestations.json")
    if ($LASTEXITCODE -ne 0) { throw "Live-Attestation refused (exit $LASTEXITCODE)" }

    Write-Host "[4/6] Gesamt-Verdikt erzeugen und verifizieren..." -ForegroundColor Cyan
    New-Item -ItemType Directory -Force -Path $MatrixDir | Out-Null
    $verdictPath = Join-Path $MatrixDir "whole-matrix-verdict.json"
    python runs/gate0-matrix-2026-08-17/verify_whole_matrix.py `
        --fixture-run-dir (Join-Path $RunDir "fixture") `
        --fixture-bundle (Join-Path $RunDir "fixture-attestations.json") `
        --fixture-key-env DAEDALUS_FIXTURE_FAULT_KEY `
        --host-run-dir (Join-Path $RunDir "linux-host") `
        --host-bundle (Join-Path $RunDir "linux-host-attestations.json") `
        --host-key-env DAEDALUS_HOST_FAULT_KEY `
        --live-run-dir (Join-Path $RunDir "live") `
        --live-bundle (Join-Path $RunDir "live-attestations.json") `
        --live-key-env DAEDALUS_LIVE_FAULT_KEY `
        --source-revision $SourceRevision `
        --output $verdictPath
    $verdictExit = $LASTEXITCODE
    if ($verdictExit -notin 0, 1) { throw "Verdikt-Verifikation abgebrochen (exit $verdictExit)" }
    Write-Host "Verdikt-Exit: $verdictExit (1 = offen mit benannten Blockern ist der ehrliche Normalfall)"

    Write-Host "[5/6] Binding-Receipt neben das Verdikt schreiben..." -ForegroundColor Cyan
    $verdict = Get-Content -Raw $verdictPath | ConvertFrom-Json
    $blockersDoc = [ordered]@{ total = $verdict.blocker_count }
    foreach ($property in $verdict.blockers_by_class.PSObject.Properties) {
        $blockersDoc[$property.Name] = [ordered]@{
            count     = @($property.Value).Count
            rows      = @($property.Value)
            scoped_by = $null
            note      = "offene Zeilen bleiben benannt; keine Sammel-Scoping-Erklaerung ueber gemischte Ursachen"
        }
    }
    $receipt = [ordered]@{
        schema          = "daedalus-gate0-whole-matrix-receipt/1"
        produced_at     = ([DateTime]::UtcNow.ToString("yyyy-MM-dd"))
        produced_by     = "docs/recovery/gate0_production_attest.ps1"
        source_revision = $verdict.source_revision
        matrix          = [ordered]@{
            matrix_id     = "gate0-whole-runtime-fault-matrix"
            matrix_sha256 = $verdict.matrix_sha256
            observations  = $verdict.observations
            closed        = $verdict.closed
            blocker_count = $verdict.blocker_count
        }
        key_material    = [ordered]@{
            class                  = $KeyClass
            fixture_issuer_id      = $fixtureIssuer
            linux_host_issuer_id   = $hostIssuer
            live_runtime_issuer_id = $liveIssuer
            production_key_material = ($KeyClass -eq "production")
        }
        blockers        = $blockersDoc
        reproduction    = [ordered]@{
            collected_run_dir = "$RunDir"
            note              = "Observations, Attestation-Bundles und Reproduktionsschritte liegen im Sammel-Lauf; dieses Verzeichnis existiert, damit der Gate-Report das Verdikt unter runs/gate0-matrix-* findet."
        }
    }
    $receiptJson = ($receipt | ConvertTo-Json -Depth 12) + "`n"
    [System.IO.File]::WriteAllText(
        (Resolve-UnderRoot (Join-Path $MatrixDir "receipt.json")),
        $receiptJson,
        [System.Text.UTF8Encoding]::new($false)
    )

    Write-Host "[6/6] Gate-Report gegen frische Conformance-Receipts erzeugen..." -ForegroundColor Cyan
    $reportLines = python -m daedalus.gates report --gate 0 --repo-root . `
        --source-revision $SourceRevision `
        --conformance-receipts $conformanceReceipts
    if ($LASTEXITCODE -ne 0) { throw "Gate-Report fehlgeschlagen (exit $LASTEXITCODE)" }
    $reportPath = Join-Path $MatrixDir "gate-report-v3.json"
    [System.IO.File]::WriteAllText(
        (Resolve-UnderRoot $reportPath),
        (($reportLines -join "`n") + "`n"),
        [System.Text.UTF8Encoding]::new($false)
    )
    $report = ($reportLines -join "`n") | ConvertFrom-Json
    Write-Host ""
    Write-Host "Verdikt:     $verdictPath (closed=$($verdict.closed), blockers=$($verdict.blocker_count))" -ForegroundColor Green
    Write-Host "Gate-Report: $reportPath (closed=$($report.closed); blocker-zeilen=$(@($report.blockers).Count))" -ForegroundColor Green
}
finally {
    Remove-Item Env:DAEDALUS_FIXTURE_FAULT_KEY -ErrorAction SilentlyContinue
    Remove-Item Env:DAEDALUS_HOST_FAULT_KEY -ErrorAction SilentlyContinue
    Remove-Item Env:DAEDALUS_LIVE_FAULT_KEY -ErrorAction SilentlyContinue
    Write-Host "Keys aus der Shell-Umgebung entfernt." -ForegroundColor Yellow
}
