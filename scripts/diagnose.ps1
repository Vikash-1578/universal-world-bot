<#
  Check everything the bot needs and say how to fix problems:
    powershell -ExecutionPolicy Bypass -File scripts\diagnose.ps1
  Checks: Python, CPU, RAM, disk, NVIDIA GPU + driver, FFmpeg/ffprobe, Blender, database, .env, keys.txt.
  It only reads - nothing is installed or changed.
#>
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$venvPy = Join-Path $Root "venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    Write-Host "venv nahi mila - pehle scripts\install.ps1 chalao." -ForegroundColor Red
    exit 1
}
Write-Host "Windows: $([Environment]::OSVersion.VersionString)  |  64-bit: $([Environment]::Is64BitOperatingSystem)"
& $venvPy -m app.diagnose
exit $LASTEXITCODE
