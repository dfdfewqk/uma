# Windows portable smoke tests: every process gets a finite deadline, and a
# failing child tree is terminated. Does not start or interact with the game.
[CmdletBinding()]
param(
    [ValidateSet('built', 'installed', 'install', 'uninstall')]
    [string]$Mode = 'built',
    [string]$InstallPath = '',
    [string]$Executable = '',
    [ValidateRange(10, 240)]
    [int]$TimeoutSeconds = 90
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$dist = Join-Path $root 'dist'
$reports = Join-Path $dist 'smoke-reports'
New-Item -ItemType Directory -Force -Path $reports | Out-Null

function Invoke-BoundedExe {
    param(
        [Parameter(Mandatory=$true)][string]$Path,
        [string[]]$Arguments = @(),
        [Parameter(Mandatory=$true)][string]$Label,
        [int]$Timeout = 90
    )
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Missing executable for ${Label}: $Path"
    }
    $info = [System.Diagnostics.ProcessStartInfo]::new()
    $info.FileName = [System.IO.Path]::GetFullPath($Path)
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    foreach ($argument in $Arguments) { [void]$info.ArgumentList.Add([string]$argument) }
    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $info
    $startedAt = Get-Date
    Write-Host "[UMA smoke] START ${Label} (limit ${Timeout}s)"
    try {
        if (-not $process.Start()) { throw "Could not start $Label" }
        Write-Host "[UMA smoke] PID ${Label}: $($process.Id)"
        if (-not $process.WaitForExit($Timeout * 1000)) {
            try { $process.Kill($true) } catch { Write-Warning "Could not kill $Label process tree: $_" }
            try { [void]$process.WaitForExit(5000) } catch { }
            throw "TIMEOUT ${Label}: process did not exit in ${Timeout}s; process tree terminated"
        }
        if ($process.ExitCode -ne 0) {
            throw "FAILED ${Label}: exit code $($process.ExitCode)"
        }
        $elapsed = [math]::Round(((Get-Date) - $startedAt).TotalSeconds, 1)
        Write-Host "[UMA smoke] PASS ${Label} ($elapsed seconds)"
    } catch {
        $elapsed = [math]::Round(((Get-Date) - $startedAt).TotalSeconds, 1)
        Write-Host "[UMA smoke] ERROR ${Label} after ${elapsed}s: $($_.Exception.Message)"
        throw
    } finally {
        $process.Dispose()
    }
}

if ($Mode -eq 'install') {
    if (-not $InstallPath -or -not $Executable) { throw 'install requires -InstallPath and -Executable' }
    Invoke-BoundedExe -Path $Executable -Label 'Inno Setup silent install' -Timeout $TimeoutSeconds `
        -Arguments @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', ('/DIR=' + $InstallPath))
    return
}
if ($Mode -eq 'uninstall') {
    if (-not $Executable) { throw 'uninstall requires -Executable' }
    Invoke-BoundedExe -Path $Executable -Label 'Inno Setup silent uninstall' -Timeout $TimeoutSeconds `
        -Arguments @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART')
    return
}

$prefix = if ($Mode -eq 'built') { '' } else { 'installed_' }
$base = if ($Mode -eq 'built') { $dist } else { $InstallPath }
if (-not $base) { throw 'installed mode requires -InstallPath' }

foreach ($name in @('UmaTrainerKR', 'UmaTrainerKR_Companion', 'UmaTrainerKR_GameTest', 'UmaTrainerKR_Preflight')) {
    $exe = Join-Path $base "$name.exe"
    $report = Join-Path $reports "${prefix}${name}.json"
    if (Test-Path -LiteralPath $report) { throw "Refusing stale smoke report $report" }
    Invoke-BoundedExe -Path $exe -Label "${Mode} $name self-check" -Timeout $TimeoutSeconds `
        -Arguments @('--self-check-report', $report)
    if (-not (Test-Path -LiteralPath $report)) { throw "Missing report after $name" }
    $result = Get-Content -LiteralPath $report -Raw -Encoding utf8 | ConvertFrom-Json
    if ($result.schema -ne 'uma_r25_executable_selfcheck_v1' -or
        $result.executable -ne $name -or $result.result -ne 'PASS' -or
        $result.frozen_binary -ne $true -or
        $result.game_client_tested -ne $false -or
        $result.automatic_click_enabled -ne $false) {
        throw "Invalid or unsuccessful self-check report for $name"
    }
    # This second pass reaches the real GUI entrypoint imports without opening Tk.
    # It detects import-time missing data that the early self-check cannot see.
    $startup = Join-Path $reports "${prefix}${name}_startup.json"
    if (Test-Path -LiteralPath $startup) { throw "Refusing stale startup report $startup" }
    Invoke-BoundedExe -Path $exe -Label "${Mode} $name startup-imports" -Timeout $TimeoutSeconds `
        -Arguments @('--startup-check-report', $startup)
    if (-not (Test-Path -LiteralPath $startup)) { throw "Missing startup report after $name" }
    $launch = Get-Content -LiteralPath $startup -Raw -Encoding utf8 | ConvertFrom-Json
    if ($launch.schema -ne 'uma_r25_executable_selfcheck_v1' -or
        $launch.executable -ne $name -or $launch.result -ne 'PASS' -or
        $launch.frozen_binary -ne $true -or
        $launch.game_client_tested -ne $false -or
        $launch.automatic_click_enabled -ne $false) {
        throw "Invalid or unsuccessful startup import report for $name"
    }
}

# R36: execute real Tk GUI and synthetic R6->R34->R35 interaction once per mode.
# Main program starts without the game; bounded timeout prevents CI hangs.
$gui = Join-Path $base 'UmaTrainerKR.exe'
$guiReport = Join-Path $reports "${prefix}UmaTrainerKR_gui.json"
if (Test-Path -LiteralPath $guiReport) { throw "Refusing stale GUI smoke report $guiReport" }
Invoke-BoundedExe -Path $gui -Label "${Mode} R36 real Tk GUI review" -Timeout $TimeoutSeconds `
    -Arguments @('--gui-smoke-report', $guiReport)
if (-not (Test-Path -LiteralPath $guiReport)) { throw 'Missing R36 GUI smoke report' }
$ui = Get-Content -LiteralPath $guiReport -Raw -Encoding utf8 | ConvertFrom-Json
if ($ui.schema -ne 'uma_r36_windows_gui_synthetic_smoke_v1' -or
    $ui.result -ne 'PASS' -or
    $ui.r6_reviewed_actions -ne 2 -or
    $ui.r34_panel_created -ne $true -or
    $ui.r35_actions_rendered -ne 2 -or
    $ui.r35_stale_invalidation_checked -ne $true -or
    $ui.r35_conflict_detected -ne $true -or
    $ui.game_client_tested -ne $false -or
    $ui.automatic_click_enabled -ne $false -or
    $ui.synthetic_only -ne $true) {
    throw 'Invalid or unsuccessful R36 real GUI smoke report'
}

$companion = Join-Path $base 'UmaTrainerKR_Companion.exe'
$diagnostic = Join-Path $reports "${prefix}first_run_no_game.json"
if (Test-Path -LiteralPath $diagnostic) { throw "Refusing stale first-run report $diagnostic" }
Invoke-BoundedExe -Path $companion -Label "${Mode} first-run diagnostic" -Timeout $TimeoutSeconds `
    -Arguments @('--first-run-report', $diagnostic)
if (-not (Test-Path -LiteralPath $diagnostic)) { throw 'Missing first-run diagnostic report' }
$firstRun = Get-Content -LiteralPath $diagnostic -Raw -Encoding utf8 | ConvertFrom-Json
if ($firstRun.schema -ne 'uma_r26_windows_first_run_v1' -or
    $firstRun.automatic_clicks_enabled -ne $false -or
    $firstRun.real_game_ocr_verified -ne $false) {
    throw 'First-run report claims unsafe readiness or has unexpected schema'
}
Write-Host "[UMA smoke] ALL PASS for $Mode - does not validate Korean live game"
