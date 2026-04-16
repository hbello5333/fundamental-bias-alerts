param(
    [Parameter(Mandatory = $true)]
    [string]$Prices,
    [string]$PythonExe = ".\.venv\Scripts\python.exe",
    [string]$Snapshots = "data/bias_snapshots.jsonl",
    [double]$MinConfidence = 0.0,
    [int]$MinCohortSamples = 10,
    [int]$MaxRankedCohorts = 25,
    [string]$Symbol = "",
    [string]$ConfidenceBuckets = "0.00,0.60,0.75,0.90"
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Resolve-Path (Join-Path $scriptRoot "..")

Push-Location $projectRoot
try {
    $arguments = @(
        "-m", "fundamental_bias_alerts.cli", "validate-prices",
        "--snapshots", $Snapshots,
        "--prices", $Prices,
        "--horizon-hours", "1",
        "--horizon-hours", "4",
        "--horizon-hours", "24",
        "--min-confidence", $MinConfidence.ToString([System.Globalization.CultureInfo]::InvariantCulture),
        "--confidence-buckets", $ConfidenceBuckets,
        "--min-cohort-samples", $MinCohortSamples.ToString(),
        "--max-ranked-cohorts", $MaxRankedCohorts.ToString()
    )

    if ($Symbol) {
        $arguments += @("--symbol", $Symbol)
    }

    & $PythonExe @arguments
}
finally {
    Pop-Location
}
