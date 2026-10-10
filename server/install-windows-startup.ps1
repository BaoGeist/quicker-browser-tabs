# Installs the tab server under %LOCALAPPDATA%\FastBrowserTabs\server and
# starts it hidden at Windows login. Re-run after changing main.py to update.
#
#   powershell -ExecutionPolicy Bypass -File server\install-windows-startup.ps1

$ErrorActionPreference = "Stop"

$dest = Join-Path $env:LOCALAPPDATA "FastBrowserTabs\server"
New-Item -ItemType Directory -Force $dest | Out-Null
Copy-Item (Join-Path $PSScriptRoot "main.py"), (Join-Path $PSScriptRoot "requirements.txt") $dest -Force

if (-not (Test-Path "$dest\venv")) { py -3 -m venv "$dest\venv" }
& "$dest\venv\Scripts\python.exe" -m pip install -q --disable-pip-version-check -r "$dest\requirements.txt"

# Hidden launcher in the Startup folder; logs go to server.log next to main.py.
$cmd = "cmd /c cd /d ""$dest"" && venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8765 > server.log 2>&1"
$vbs = Join-Path ([Environment]::GetFolderPath("Startup")) "FastBrowserTabsServer.vbs"
$vbsCmd = $cmd -replace '"', '""'  # VBScript escapes quotes by doubling
Set-Content $vbs ('CreateObject("WScript.Shell").Run "' + $vbsCmd + '", 0, False')

Write-Host "Installed to $dest"
Write-Host "Startup launcher: $vbs"
Write-Host "Start it now with: wscript `"$vbs`""
