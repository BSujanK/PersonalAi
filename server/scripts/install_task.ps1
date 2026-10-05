<#
.SYNOPSIS
  Registers (or replaces) the "PersonalAi agent" scheduled task for the current user (M7).

.DESCRIPTION
  The task starts `uv run python -m agent serve` from this repo's server folder at logon and
  restarts it if it exits. It runs only while you are logged on, as you, because the secrets
  live in your Windows Credential Manager. It needs no admin rights and stores no secrets:
  configuration comes from your user environment variables (PERSONALAI_*), set beforehand.

  Run from the server folder:  powershell -ExecutionPolicy Bypass -File scripts\install_task.ps1
  Remove with:                 Unregister-ScheduledTask -TaskName "PersonalAi agent"
#>
[CmdletBinding()]
param(
    [string]$TaskName = "PersonalAi agent"
)
$ErrorActionPreference = "Stop"

$serverDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$uv = (Get-Command uv -ErrorAction Stop).Source
$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

if (-not [Environment]::GetEnvironmentVariable("PERSONALAI_BIND_HOSTS", "User")) {
    Write-Warning "PERSONALAI_BIND_HOSTS is not set for your user; the server will bind 127.0.0.1 only and the phone cannot reach it."
}

# Hidden PowerShell host, so no console window sits open where closing it would stop the server.
$command = "& '$uv' run --directory '$serverDir' python -m agent serve; exit `$LASTEXITCODE"
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -NonInteractive -WindowStyle Hidden -Command `"$command`"" `
    -WorkingDirectory $serverDir
# Start a minute after logon so Tailscale has its address before the server binds to it.
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
$trigger.Delay = "PT1M"
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force | Out-Null
Write-Host "Registered '$TaskName' for $user. Start it now with: Start-ScheduledTask -TaskName '$TaskName'"
