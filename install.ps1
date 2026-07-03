<#
  install.ps1 - Set up mouse2pad for Minecraft Bedrock (GDK mouse workaround).

  What it does (in order):
    1. Finds Python (points you to python.org if missing).
    2. pip-installs vgamepad, which bundles the ViGEmBus driver installer.
       >> The DRIVER install may prompt for ADMIN and REQUIRES A REBOOT on first
          install before the virtual pad can connect. <<
    3. Copies the script + config into %LOCALAPPDATA%\Mouse2PadBedrock.
    4. Registers a hidden "MouseToPad" Scheduled Task that runs at logon.
    5. Starts it and verifies a single instance.

  No admin is required for steps 3-5. Run from a normal PowerShell:
      powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
#>

$ErrorActionPreference = "Stop"
$AppName    = "Mouse2PadBedrock"
$TaskName   = "MouseToPad"
$InstallDir = Join-Path $env:LOCALAPPDATA $AppName

function Say($m){ Write-Host "[install] $m" -ForegroundColor Cyan }
function Ok ($m){ Write-Host "[  ok   ] $m" -ForegroundColor Green }
function Warn($m){ Write-Host "[ warn  ] $m" -ForegroundColor Yellow }

Say "mouse2pad installer starting."

# --- 1. Locate Python -------------------------------------------------------
Say "Looking for Python..."
$python = $null
$cmd = Get-Command python -ErrorAction SilentlyContinue
if ($cmd) { $python = $cmd.Source }
if (-not $python) {
    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) { $python = (& py -c "import sys; print(sys.executable)") 2>$null }
}
if (-not $python -or -not (Test-Path $python)) {
    Warn "Python was not found."
    Write-Host "  Install Python 3 from https://www.python.org/downloads/ and CHECK"
    Write-Host "  'Add python.exe to PATH' during setup, then re-run this installer."
    exit 1
}
Ok "Python: $python"

# pythonw.exe runs with no console window (used by the scheduled task).
$pythonw = Join-Path (Split-Path $python -Parent) "pythonw.exe"
if (-not (Test-Path $pythonw)) { Warn "pythonw.exe not found beside python.exe; a console may flash."; $pythonw = $python }
else { Ok "pythonw: $pythonw" }

# --- 2. Install vgamepad (+ ViGEmBus driver) --------------------------------
Say "Installing the 'vgamepad' package (bundles the ViGEmBus driver installer)..."
Warn "If a 'ViGEmBus Setup' window or a UAC admin prompt appears, ACCEPT it."
& $python -m pip install --upgrade vgamepad
if ($LASTEXITCODE -ne 0) { Warn "pip install vgamepad failed (exit $LASTEXITCODE). Fix the error above and re-run."; exit 1 }
Ok "vgamepad installed."

$vigem = Get-Service -Name "ViGEmBus" -ErrorAction SilentlyContinue
if ($vigem) { Ok "ViGEmBus driver present (status: $($vigem.Status))." }
else { Warn "ViGEmBus driver not detected yet - it may finish on reboot." }

# --- 3. Copy files ----------------------------------------------------------
Say "Installing files to $InstallDir"
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
Copy-Item -Path (Join-Path $PSScriptRoot "src\mouse2pad.py") -Destination $InstallDir -Force
Ok "copied mouse2pad.py"

$cfgDst = Join-Path $InstallDir "mouse2pad_config.txt"
if (Test-Path $cfgDst) {
    Ok "kept existing mouse2pad_config.txt (your settings preserved)"
} else {
    Copy-Item -Path (Join-Path $PSScriptRoot "config\mouse2pad_config.example.txt") -Destination $cfgDst -Force
    Ok "created mouse2pad_config.txt (edit it to tune sensitivity)"
}

# --- 4. Register the hidden logon task --------------------------------------
Say "Registering scheduled task '$TaskName' (runs hidden at logon)..."
$scriptPath = Join-Path $InstallDir "mouse2pad.py"
$act  = New-ScheduledTaskAction -Execute $pythonw -Argument ('"{0}"' -f $scriptPath)
$trg  = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$set  = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
            -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
$prin = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $TaskName -Action $act -Trigger $trg -Settings $set -Principal $prin -Force | Out-Null
Ok "task registered."

# --- 5. Start + verify ------------------------------------------------------
Say "Starting it now..."
Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 2
$live = @(Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" |
          Where-Object { $_.CommandLine -like '*mouse2pad.py*' })
if ($live.Count -eq 1) { Ok "running (1 instance, pid $($live[0].ProcessId))." }
elseif ($live.Count -eq 0) { Warn "not running yet - it will start at next logon (or after reboot if the driver just installed)." }
else { Warn "$($live.Count) instances found; a single instance is expected." }

Write-Host ""
if (-not $vigem) {
    Warn "FIRST-TIME DRIVER INSTALL: please REBOOT before playing. The virtual pad"
    Warn "cannot connect until Windows restarts after the ViGEmBus driver install."
}
Ok "Done. Launch Minecraft, enter a world, and move the mouse to look around."
Write-Host "Sensitivity knob: $cfgDst  (edit 'sensitivity'; applies live)."
Write-Host "Pause/resume hotkey: Ctrl+Alt+M"
