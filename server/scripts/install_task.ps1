<#
.SYNOPSIS
  Registers (or replaces) the "PersonalAi agent" scheduled task for the current user (M7).

.DESCRIPTION
  The task starts the server at logon (via scripts\run_agent.ps1, which runs the venv's
  python.exe with `-m agent serve`) and restarts it if it exits. Stopping the task stops the
  server: the wrapper ties the Python process to itself with a job object. The task runs only
  while you are logged on, as you, because the secrets
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
$wrapper = Join-Path $PSScriptRoot "run_agent.ps1"
$venvPython = Join-Path $serverDir ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Host "Creating the virtual environment (uv sync)..."
    & $uv sync --directory $serverDir
    if ($LASTEXITCODE -ne 0) { throw "uv sync failed" }
}
$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

if (-not [Environment]::GetEnvironmentVariable("PERSONALAI_BIND_HOSTS", "User")) {
    Write-Warning "PERSONALAI_BIND_HOSTS is not set for your user; the server will bind 127.0.0.1 only and the phone cannot reach it."
}

# Hidden PowerShell host, so no console window sits open where closing it would stop the server.
# The wrapper runs the venv's python.exe directly and kills it when the host dies, so
# Stop-ScheduledTask really stops the server (see run_agent.ps1).
$argument = "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass " +
    "-File `"$wrapper`" -ServerDir `"$serverDir`""
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $argument `
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
Write-Host "Registered '$TaskName' for $user."
Write-Host "Start it now with:   uv run python -m agent restart"
Write-Host "(restart also stops any server still running from an older install of this task.)"
