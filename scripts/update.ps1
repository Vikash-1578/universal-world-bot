<#
  Update Universal World Bot to the latest code from GitHub (or a specific commit).
    powershell -ExecutionPolicy Bypass -File scripts\update.ps1            # latest main
    powershell -ExecutionPolicy Bypass -File scripts\update.ps1 -Ref <sha> # a specific commit

  Keeps your .env, keys.txt, config\config.toml, data\, logs\ and venv\ untouched.
  Stop the bot (Ctrl+C) before updating.
#>
param([string]$Ref = "main")

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Tmp = Join-Path $env:TEMP ("uwb_update_" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $Tmp | Out-Null
try {
    $zip = Join-Path $Tmp "code.zip"
    Write-Host "Download: $Ref ..." -ForegroundColor Cyan
    Invoke-WebRequest "https://codeload.github.com/Vikash-1578/universal-world-bot/zip/$Ref" -OutFile $zip
    Expand-Archive $zip (Join-Path $Tmp "x") -Force
    $src = Get-ChildItem (Join-Path $Tmp "x") -Directory | Select-Object -First 1
    # exclude only OUR top-level folders (full paths), never folders with the same name inside the code
    $xd = @((Join-Path $Root "venv"), (Join-Path $Root "data"), (Join-Path $Root "logs"), (Join-Path $Root ".git"))
    robocopy $src.FullName $Root /E /XD $xd /XF .env keys.txt config.toml /NFL /NDL /NJH /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy failed ($LASTEXITCODE)" }
    Write-Host "Code update ho gaya. Ab packages/database check:" -ForegroundColor Green
    & powershell -ExecutionPolicy Bypass -File (Join-Path $Root "scripts\install.ps1") -SkipConfig
}
finally {
    Remove-Item $Tmp -Recurse -Force -ErrorAction SilentlyContinue
}
