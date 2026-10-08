<#
.SYNOPSIS
  Registers (or replaces) the "PersonalAi agent" scheduled task for the current user (M7).

.DESCRIPTION
  The task starts the server at logon and, as a watchdog, every 5 minutes (a no-op while it is
  already running), so it comes back after a crash, a sleep or a stop. It runs the base
  interpreter's pythonw.exe with `-I -S scripts\agent_task.py`, which runs `agent supervise` from
  the venv. That pythonw.exe is a GUI-subsystem program, so the task has no console host: nothing
  can send it the console close or Ctrl+C event that used to kill the server at logon and during
  Modern Standby (exit code 0xC000013A, STATUS_CONTROL_C_EXIT). The venv's own pythonw.exe (from
  uv) is a console launcher, so it is not used. The supervisor starts the real server in its own
  hidden console and ties it to itself with a job object, so stopping the task stops the server.
  Its log is agent.log next to the database.

  To keep the agent stopped, disable the task (Disable-ScheduledTask); a plain stop lasts only
  until the next watchdog run.

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
# The base interpreter's pythonw.exe: pyvenv.cfg names its folder ("home = ...").
$venvCfg = Join-Path $serverDir ".venv\pyvenv.cfg"
$homeLine = Select-String -LiteralPath $venvCfg -Pattern '^\s*home\s*=\s*(.+?)\s*$' | Select-Object -First 1
if (-not $homeLine) { throw "No 'home' in $venvCfg. Recreate the venv with 'uv sync'." }
$basePythonw = Join-Path $homeLine.Matches[0].Groups[1].Value "pythonw.exe"
if (-not (Test-Path -LiteralPath $basePythonw)) { throw "No pythonw.exe at $basePythonw." }
$taskScript = Join-Path $serverDir "scripts\agent_task.py"
$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

if (-not [Environment]::GetEnvironmentVariable("PERSONALAI_BIND_HOSTS", "User")) {
    Write-Warning "PERSONALAI_BIND_HOSTS is not set for your user; the server will bind 127.0.0.1 only and the phone cannot reach it."
}

# The base pythonw.exe has no console, so no terminal can close it or send it Ctrl+C. The
# supervisor (agent.golive.supervisor) runs the server and kills it when the task is stopped.
$action = New-ScheduledTaskAction -Execute $basePythonw -Argument "-I -S `"$taskScript`"" `
    -WorkingDirectory $serverDir
# Start a minute after logon so Tailscale has its address before the server binds to it.
$logon = New-ScheduledTaskTrigger -AtLogOn -User $user
$logon.Delay = "PT1M"
# Watchdog: Task Scheduler's restart-on-failure does not fire when the process exits, so try
# every 5 minutes; MultipleInstances IgnoreNew makes it a no-op while the agent is running.
$watchdog = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5)
$trigger = @($logon, $watchdog)
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
