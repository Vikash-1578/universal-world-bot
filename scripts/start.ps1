<#
  Start Universal World Bot.
    powershell -ExecutionPolicy Bypass -File scripts\start.ps1            # run once
    powershell -ExecutionPolicy Bypass -File scripts\start.ps1 -AutoRestart   # restart automatically if it crashes

  Stop: press Ctrl+C in this window (running jobs pause safely and continue on next start).
  While this window is closed, or the laptop sleeps / is off, the bot cannot answer.
#>
param([switch]$AutoRestart)

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$venvPy = Join-Path $Root "venv\Scripts\python.exe"

if (-not (Test-Path $venvPy)) {
    Write-Host "venv nahi mila. Pehle install chalao: powershell -ExecutionPolicy Bypass -File scripts\install.ps1" -ForegroundColor Red
    exit 1
}
if (-not (Test-Path (Join-Path $Root ".env"))) {
    Write-Host ".env nahi mila. scripts\install.ps1 chalao ya .env.example ko .env naam se copy karke bharo." -ForegroundColor Red
    exit 1
}

Write-Host "Universal World Bot start ho raha hai... (band karne ke liye Ctrl+C)" -ForegroundColor Cyan
Write-Host "Tip: laptop ko sone mat do - Settings > System > Power > Sleep = Never (charging par)." -ForegroundColor DarkGray

do {
    & $venvPy -m app.main
    $code = $LASTEXITCODE
    if ($code -eq 2) {
        Write-Host "Config me problem hai (upar likha hai). Theek karke dobara chalao." -ForegroundColor Red
        break
    }
    if ($AutoRestart -and $code -ne 0) {
        Write-Host "Bot ruk gaya (code $code). 10 second me dobara start..." -ForegroundColor Yellow
        Start-Sleep -Seconds 10
    }
} while ($AutoRestart -and $code -ne 0)

Write-Host "Bot band hai." -ForegroundColor Yellow
