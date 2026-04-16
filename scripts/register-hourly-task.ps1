param(
    [string]$TaskName = "FundamentalBiasAlertsHourly",
    [string]$StartTime = "",
    [string]$PowerShellExe = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe",
    [string]$PythonExe = ".\.venv\Scripts\python.exe",
    [string]$Config = "configs/locked.json",
    [string]$WebhookEnv = "",
    [switch]$UseTelegram,
    [string]$TelegramBotTokenEnv = "TELEGRAM_BOT_TOKEN",
    [string]$TelegramChatIdEnv = "TELEGRAM_CHAT_ID"
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Resolve-Path (Join-Path $scriptRoot "..")
$runnerPath = (Resolve-Path (Join-Path $scriptRoot "run-paper-hourly.ps1")).Path

if (-not $StartTime) {
    $StartTime = (Get-Date).AddMinutes(2).ToString("HH:mm")
}

function Resolve-ProjectOrAbsolutePath([string]$PathValue) {
    if ([System.IO.Path]::IsPathRooted($PathValue)) {
        return (Resolve-Path $PathValue).Path
    }
    return (Resolve-Path (Join-Path $projectRoot $PathValue)).Path
}

function Format-CommandArgument([string]$Value) {
    if ($Value -match '[\s"]') {
        return '"' + ($Value -replace '"', '\"') + '"'
    }
    return $Value
}

$resolvedPowerShellExe = Resolve-ProjectOrAbsolutePath $PowerShellExe
$resolvedPythonExe = Resolve-ProjectOrAbsolutePath $PythonExe
$resolvedConfig = Resolve-ProjectOrAbsolutePath $Config

$startTimeSpan = [TimeSpan]::ParseExact($StartTime, "hh\:mm", $null)
$startAt = (Get-Date).Date.Add($startTimeSpan)
if ($startAt -le (Get-Date)) {
    $startAt = $startAt.AddDays(1)
}

$taskArguments = @(
    "-ExecutionPolicy", "Bypass",
    "-File", $runnerPath,
    "-PythonExe", $resolvedPythonExe,
    "-Config", $resolvedConfig
)

if ($WebhookEnv) {
    $taskArguments += @("-WebhookEnv", $WebhookEnv)
}

if ($UseTelegram) {
    $taskArguments += @("-TelegramBotTokenEnv", $TelegramBotTokenEnv, "-TelegramChatIdEnv", $TelegramChatIdEnv)
}

$scheduledArgumentText = ($taskArguments | ForEach-Object { Format-CommandArgument $_ }) -join " "

$action = New-ScheduledTaskAction -Execute $resolvedPowerShellExe -Argument $scheduledArgumentText
$trigger = New-ScheduledTaskTrigger -Once -At $startAt -RepetitionInterval (New-TimeSpan -Hours 1) -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description "Fundamental Bias Alerts hourly runner" -Force | Out-Null

Write-Host "Registered scheduled task '$TaskName' to run hourly starting at $($startAt.ToString("yyyy-MM-dd HH:mm"))."
Write-Host "Task arguments: $scheduledArgumentText"
