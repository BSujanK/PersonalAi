<#
.SYNOPSIS
  Registers (or replaces) the "PersonalAi agent" scheduled task for the current user (M7).

.DESCRIPTION
  The task starts the server folder's virtualenv Python directly (.venv\Scripts\pythonw.exe
  -m agent serve) at logon and restarts it if it exits. There is no PowerShell or uv process in
  between, so Stop-ScheduledTask stops the server itself and frees its port. pythonw has no
  console window; the server writes its log next to the database (agent.log).

  Run `uv sync` first so .venv exists. After updating the code, run `uv sync` and then
  `uv run python -m agent restart`. It runs only while you are logged on, as you, because the secrets
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
$pythonw = Join-Path $serverDir ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $pythonw)) {
    throw "$pythonw not found. Run 'uv sync' in $serverDir first."
}
$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

if (-not [Environment]::GetEnvironmentVariable("PERSONALAI_BIND_HOSTS", "User")) {
    Write-Warning "PERSONALAI_BIND_HOSTS is not set for your user; the server will bind 127.0.0.1 only and the phone cannot reach it."
}

# The server process is the task's own process: stopping the task stops the server. An earlier
# version ran powershell -> uv -> python, and stopping the task left python holding the port.
$action = New-ScheduledTaskAction -Execute $pythonw -Argument "-m agent serve" `
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
