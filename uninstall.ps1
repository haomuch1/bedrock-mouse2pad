<#
  uninstall.ps1 - Remove mouse2pad cleanly.

  What it does (in order):
    1. Stops the running helper (which neutralizes and UNPLUGS the virtual pad -
       ViGEmBus drops the device when the owning process exits).
    2. Removes the "MouseToPad" scheduled task.
    3. Deletes the install folder.
    4. Optionally uninstalls the ViGEmBus driver (ASKS first - other tools such as
       DS4Windows / x360ce also use ViGEmBus, so it is kept by default).

  Run from a normal PowerShell:
      powershell -NoProfile -ExecutionPolicy Bypass -File .\uninstall.ps1
#>

$AppName    = "Mouse2PadBedrock"
$TaskName   = "MouseToPad"
$InstallDir = Join-Path $env:LOCALAPPDATA $AppName

function Say($m){ Write-Host "[uninstall] $m" -ForegroundColor Cyan }
function Ok ($m){ Write-Host "[   ok    ] $m" -ForegroundColor Green }
function Warn($m){ Write-Host "[  warn   ] $m" -ForegroundColor Yellow }

Say "mouse2pad uninstaller starting."

# --- 1. Stop the running helper (unplugs the virtual pad) -------------------
Say "Stopping the helper and unplugging the virtual pad..."
$procs = Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" |
         Where-Object { $_.CommandLine -like '*mouse2pad.py*' }
if ($procs) {
    foreach ($p in $procs) {
        Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
        Ok "stopped pid $($p.ProcessId) (pad disconnected on exit)"
    }
} else { Ok "no running helper found." }

# --- 2. Remove the scheduled task -------------------------------------------
Say "Removing scheduled task '$TaskName'..."
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Ok "task removed."
} else { Ok "task not present." }

# --- 3. Delete files --------------------------------------------------------
Say "Deleting $InstallDir ..."
if (Test-Path $InstallDir) {
    Remove-Item -Path $InstallDir -Recurse -Force
    Ok "files removed."
} else { Ok "install folder not present." }

# --- 4. Optionally remove the driver ----------------------------------------
Write-Host ""
Warn "The ViGEmBus driver is SHARED - DS4Windows, x360ce and other tools use it."
$ans = Read-Host "Uninstall the ViGEmBus driver too? (needs admin + reboot) [y/N]"
if ($ans -match '^(y|yes)$') {
    Say "Uninstalling ViGEmBus via winget (an admin prompt may appear)..."
    winget uninstall "ViGEmBus"
    Warn "Reboot to complete driver removal."
} else {
    Ok "Left ViGEmBus installed."
    Write-Host "  To also remove the Python package later:  python -m pip uninstall vgamepad"
}

Ok "Uninstall complete."
