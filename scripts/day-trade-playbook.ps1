param(
    [string]$PythonExe = ".\.venv\Scripts\python.exe",
    [string]$Config = "configs/locked.json",
    [string]$Calendar = "configs/release_calendar.usd_q2_2026.json",
    [string]$TradeDate = "",
    [switch]$Brief,
    [string[]]$ReferencePrice = @(),
    [double]$AccountSize = 0
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

    foreach ($PriceSpec in $ReferencePrice) {
        $arguments += @("--reference-price", $PriceSpec)
    }

    if ($AccountSize -gt 0) {
        $arguments += @("--account-size", $AccountSize.ToString([System.Globalization.CultureInfo]::InvariantCulture))
    }

    if ($Brief) {
        $arguments += "--brief"
    }

    & $PythonExe @arguments
}
finally {
    Pop-Location
}
