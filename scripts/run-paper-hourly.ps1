param(
    [string]$PythonExe = ".\.venv\Scripts\python.exe",
    [string]$Config = "configs/locked.json",
    [string]$Calendar = "configs/release_calendar.usd_q2_2026.json",
    [string]$WebhookEnv = "",
    [string]$TelegramBotTokenEnv = "",
    [string]$TelegramChatIdEnv = ""
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Resolve-Path (Join-Path $scriptRoot "..")

Push-Location $projectRoot
try {
    $arguments = @("-m", "fundamental_bias_alerts.cli", "run", "--config", $Config)
    if ($Calendar) {
        $arguments += @("--calendar", $Calendar)
    }
    if ($WebhookEnv) {
        $arguments += @("--webhook-env", $WebhookEnv)
    }
    if ($TelegramBotTokenEnv -or $TelegramChatIdEnv) {
        if (-not $TelegramBotTokenEnv -or -not $TelegramChatIdEnv) {
            throw "Telegram delivery requires both -TelegramBotTokenEnv and -TelegramChatIdEnv."
        }
        $arguments += @("--telegram-token-env", $TelegramBotTokenEnv)
        $arguments += @("--telegram-chat-id-env", $TelegramChatIdEnv)
    }

    & $PythonExe @arguments
}
finally {
    Pop-Location
}
