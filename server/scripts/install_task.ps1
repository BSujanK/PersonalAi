<#
.SYNOPSIS
  Registers (or replaces) the "PersonalAi agent" scheduled task for the current user (M7).

.DESCRIPTION
  The task starts the server at logon and restarts it if it exits. It runs the venv's
  pythonw.exe with `-m agent supervise`. pythonw.exe is a GUI-subsystem program, so the task has
  no console host: nothing can send it the console close or Ctrl+C event that used to kill the
  server at logon (exit code 0xC000013A, STATUS_CONTROL_C_EXIT). The supervisor starts the real
  server in its own hidden console and ties it to itself with a job object, so stopping the task
  stops the server. Its log is agent.log next to the database.

  The task runs only while you are logged on, as you, because the secrets live in your Windows
  Credential Manager. It needs no admin rights and stores no secrets: configuration comes from
  your user environment variables (PERSONALAI_*), set beforehand.

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
$venvPython = Join-Path $serverDir ".venv\Scripts\python.exe"
$venvPythonw = Join-Path $serverDir ".venv\Scripts\pythonw.exe"
if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Host "Creating the virtual environment (uv sync)..."
    & $uv sync --directory $serverDir
    if ($LASTEXITCODE -ne 0) { throw "uv sync failed" }
}
if (-not (Test-Path -LiteralPath $venvPythonw)) {
    throw "No pythonw.exe at $venvPythonw. Run 'uv sync' in $serverDir (a Windows Python is required)."
}
$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

if (-not [Environment]::GetEnvironmentVariable("PERSONALAI_BIND_HOSTS", "User")) {
    Write-Warning "PERSONALAI_BIND_HOSTS is not set for your user; the server will bind 127.0.0.1 only and the phone cannot reach it."
}

# pythonw.exe has no console, so no terminal can close it or send it Ctrl+C. The supervisor
# (agent.golive.supervisor) runs the server and kills it when the task is stopped.
$action = New-ScheduledTaskAction -Execute $venvPythonw -Argument "-m agent supervise" `
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
