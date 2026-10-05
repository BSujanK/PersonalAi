<#
.SYNOPSIS
  What the "PersonalAi agent" scheduled task runs: the agent server, tied to this host process.

.DESCRIPTION
  Stop-ScheduledTask (and a killed task) terminates only this PowerShell host. Without help, the
  Python server it started would keep running, keep port 8765 and serve stale code while the next
  start exits with code 3. So this script first puts itself in a Windows job object that kills
  every member when its last handle closes, and the handle dies with this process. Everything
  started below (python.exe and the interpreter behind the venv launcher) is a member, so
  stopping the task stops the server.

  The server runs from the venv's own python.exe, not through `uv run`, so there is no extra
  uv process in between. Run `uv sync` after changing dependencies, or use
  `uv run python -m agent restart`, which syncs first.

  Not meant to be run by hand; install_task.ps1 registers it.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ServerDir
)
$ErrorActionPreference = "Stop"

Add-Type -TypeDefinition @"
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;

public static class PersonalAiJob {
    [StructLayout(LayoutKind.Sequential)]
    struct BasicLimits {
        public long PerProcessUserTimeLimit;
        public long PerJobUserTimeLimit;
        public uint LimitFlags;
        public UIntPtr MinimumWorkingSetSize;
        public UIntPtr MaximumWorkingSetSize;
        public uint ActiveProcessLimit;
        public UIntPtr Affinity;
        public uint PriorityClass;
        public uint SchedulingClass;
    }
    [StructLayout(LayoutKind.Sequential)]
    struct IoCounters { public ulong a, b, c, d, e, f; }
    [StructLayout(LayoutKind.Sequential)]
    struct ExtendedLimits {
        public BasicLimits Basic;
        public IoCounters Io;
        public UIntPtr ProcessMemoryLimit;
        public UIntPtr JobMemoryLimit;
        public UIntPtr PeakProcessMemoryUsed;
        public UIntPtr PeakJobMemoryUsed;
    }
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern IntPtr CreateJobObject(IntPtr attributes, string name);
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool SetInformationJobObject(IntPtr job, int infoClass, ref ExtendedLimits info, int size);
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
    [DllImport("kernel32.dll")]
    static extern IntPtr GetCurrentProcess();

    static IntPtr job; // held for the life of this process; closing it kills the members

    public static void KillMembersWhenThisProcessEnds() {
        job = CreateJobObject(IntPtr.Zero, null);
        if (job == IntPtr.Zero) throw new Win32Exception();
        ExtendedLimits info = new ExtendedLimits();
        info.Basic.LimitFlags = 0x2000; // JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if (!SetInformationJobObject(job, 9, ref info, Marshal.SizeOf(typeof(ExtendedLimits))))
            throw new Win32Exception();
        if (!AssignProcessToJobObject(job, GetCurrentProcess())) throw new Win32Exception();
    }
}
"@

[PersonalAiJob]::KillMembersWhenThisProcessEnds()

$python = Join-Path $ServerDir ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    Write-Error "No virtual environment at $python. Run 'uv sync' in $ServerDir."
    exit 1
}
Set-Location -LiteralPath $ServerDir
& $python -m agent serve
exit $LASTEXITCODE
