<#
  Universal World Bot - Windows installer (no administrator rights needed)

  What it does, step by step:
    1. Checks Python (3.11 - 3.14)
    2. Creates a private Python environment in .\venv (does not touch system Python)
    3. Installs the pinned packages from requirements.txt
    4. Creates .env (asks for your bot token + Telegram id) if it does not exist
    5. Creates the local database (data\hub.db)
    6. Downloads the free local Hindi voice for Piper TTS once (~63 MB, hi_IN-pratham-medium) into data\models\piper
    7. Runs diagnostics (GPU, FFmpeg, Blender, disk, RAM, voices ...)

  The only model it downloads is that one voice file (no API key, no account). It does not change system
  settings or need admin rights. Skip the voice with -SkipVoice.
  Usage (from the project folder):   powershell -ExecutionPolicy Bypass -File scripts\install.ps1
#>
param([switch]$SkipConfig, [switch]$SkipVoice)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Step($n, $text) { Write-Host "`n[$n/7] $text" -ForegroundColor Cyan }
function Ok($text)   { Write-Host "  OK  $text" -ForegroundColor Green }
function Warn($text) { Write-Host "  !!  $text" -ForegroundColor Yellow }
function Fail($text, $fix) {
    Write-Host "  XX  $text" -ForegroundColor Red
    if ($fix) { Write-Host "      Kya karein: $fix" -ForegroundColor Yellow }
    exit 1
}

# ---------------------------------------------------------------- 1. Python
Step 1 "Python check"
$py = $null
function PyArgs($cand) { $p = $cand.Split(" "); if ($p.Length -gt 1) { return ,@($p[1..($p.Length - 1)]) } else { return ,@() } }
foreach ($cand in @("py -3.12", "py -3.13", "py -3.14", "py -3.11", "python")) {
    $exe = $cand.Split(" ")[0]; $pre = PyArgs $cand
    try {
        $v = & $exe @pre -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -eq 0 -and $v -match '^3\.(11|12|13|14)$') { $py = $cand; break }
    } catch { }
}
if (-not $py) {
    Fail "Python 3.11 - 3.14 nahi mila" "python.org se Python 3.12 install karo (install ke time 'Add python.exe to PATH' tick karna), phir ye script dobara chalao."
}
Ok "Python mila: $py ($v)"

# ---------------------------------------------------------------- 2. venv
Step 2 "Private Python environment (venv)"
$venvPy = Join-Path $Root "venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    $exe = $py.Split(" ")[0]; $pre = PyArgs $py
    & $exe @pre -m venv venv
    if ($LASTEXITCODE -ne 0) { Fail "venv nahi ban paya" "Antivirus/OneDrive folder lock to nahi kar raha? Project ko C:\Users\<naam>\uwb jaise folder me rakho." }
    Ok "venv bana"
} else { Ok "venv pehle se hai" }

# ---------------------------------------------------------------- 3. packages
Step 3 "Packages install (requirements.txt)"
& $venvPy -m pip install --upgrade pip --quiet
& $venvPy -m pip install -r requirements.txt --quiet
if ($LASTEXITCODE -ne 0) { Fail "Packages install nahi hue" "Internet check karo, phir dobara chalao. Error upar likha hai." }
Ok "Packages ready"

# ---------------------------------------------------------------- 4. config
Step 4 "Configuration (.env)"
$envFile = Join-Path $Root ".env"
if ((Test-Path $envFile) -or $SkipConfig) {
    Ok ".env pehle se hai (badalna ho to Notepad se kholo)"
} else {
    Write-Host "  Telegram me @BotFather -> /mybots -> apna bot -> API Token copy karo."
    $sec = Read-Host "  Bot token paste karo (screen par nahi dikhega)" -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
    $token = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    if ($token -notmatch '^\d{5,12}:[A-Za-z0-9_-]{30,}$') { Warn "Token ka format ajeeb hai - baad me .env me theek kar lena." }
    $owner = Read-Host "  Apni Telegram numeric ID (pata nahi to khali chhodo, bot khud batayega)"
    $lines = @("BOT_TOKEN=$token", "OWNER_ID=$owner", "FFMPEG_PATH=", "BLENDER_PATH=", "LOG_LEVEL=INFO")
    Set-Content -Path $envFile -Value $lines -Encoding UTF8
    $token = $null
    # only the current Windows user may read .env
    try { icacls $envFile /inheritance:r /grant:r "$($env:USERNAME):(R,W)" | Out-Null; Ok ".env bana (sirf tumhara user padh sakta hai)" }
    catch { Warn ".env bana, par permission lock nahi lag paya" }
}
if (-not (Test-Path (Join-Path $Root "keys.txt"))) {
    Copy-Item (Join-Path $Root "keys.txt.example") (Join-Path $Root "keys.txt")
    Ok "keys.txt bana (optional cloud AI keys yahan; default me cloud OFF rehta hai)"
}

# ---------------------------------------------------------------- 5. database
Step 5 "Database"
& $venvPy -c "from app.core.config import load_settings; from app.storage.db import Database; s=load_settings(); d=Database(s.db_path); print('schema v%d' % d.version); d.close()"
if ($LASTEXITCODE -ne 0) { Fail "Database nahi ban paya" "data folder ki permission dekho." }
Ok "Database ready"

# ---------------------------------------------------------------- 6. voice (Piper TTS)
Step 6 "Awaaz (Piper TTS, free, laptop par)"
$voiceDir = Join-Path $Root "data\models\piper"
New-Item -ItemType Directory -Force -Path $voiceDir | Out-Null
if (Test-Path (Join-Path $voiceDir "hi_IN-pratham-medium.onnx")) {
    Ok "Hindi awaaz pehle se hai"
} elseif ($SkipVoice) {
    Warn "Awaaz download chhoda (-SkipVoice). Video banane se pehle ye chalana: venv\Scripts\python -m piper.download_voices hi_IN-pratham-medium --download-dir data\models\piper"
} else {
    Write-Host "  Hindi awaaz download ho rahi hai (~63 MB, ek baar)..."
    & $venvPy -m piper.download_voices hi_IN-pratham-medium --download-dir $voiceDir
    if ($LASTEXITCODE -ne 0) { Warn "Awaaz download nahi hui (internet?). Baad me dobara: scripts\install.ps1 -SkipConfig" }
    else { Ok "Hindi awaaz ready (hi_IN-pratham-medium)" }
}
# English projects: venv\Scripts\python -m piper.download_voices en_US-lessac-medium --download-dir data\models\piper

# ---------------------------------------------------------------- 7. diagnostics
Step 7 "Diagnostics"
& $venvPy -m app.diagnose
if ($LASTEXITCODE -ne 0) {
    Warn "Kuch zaroori cheez missing hai (upar 'fail' wali line dekho). Theek karke: scripts\diagnose.ps1"
} else {
    Write-Host "`nSab set! Bot chalane ke liye:  powershell -ExecutionPolicy Bypass -File scripts\start.ps1" -ForegroundColor Green
}
