param(
    [string]$PythonExe = ".\.venv\Scripts\python.exe",
    [string]$Config = "configs/locked.json",
    [string]$Calendar = "configs/release_calendar.usd_q2_2026.json",
    [string]$TradeDate = "",
    [switch]$Brief
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Resolve-Path (Join-Path $scriptRoot "..")

Push-Location $projectRoot
try {
    $arguments = @(
        "-m", "fundamental_bias_alerts.cli", "day-trade-playbook",
        "--config", $Config,
        "--calendar", $Calendar
    )

    if ($TradeDate) {
        $arguments += @("--trade-date", $TradeDate)
    }

    if ($Brief) {
        $arguments += "--brief"
    }

    & $PythonExe @arguments
}
finally {
    Pop-Location
}
