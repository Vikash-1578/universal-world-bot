# Installation (Windows 11)

You need: Python 3.12 (python.org, tick "Add python.exe to PATH"), Git for Windows (optional), and later
Blender 4.x for 3D. No administrator rights are needed.

## 1. Get the code
```powershell
cd $HOME\Desktop
git clone https://github.com/Vikash-1578/universal-world-bot
cd universal-world-bot
```
(Without Git: download the ZIP from GitHub → Extract → open the folder in PowerShell.)

## 2. Install
```powershell
powershell -ExecutionPolicy Bypass -File scripts\install.ps1
```
It asks for the bot token (hidden while typing) and your Telegram id, creates `.env`, installs packages into
`venv\`, creates the database and runs diagnostics.

Optional cloud AI keys go in `keys.txt` (`provider:key` per line). They are not used until you switch on
**Settings → Cloud AI** in Telegram.

## 3. Start
```powershell
powershell -ExecutionPolicy Bypass -File scripts\start.ps1
```
Send `/start` to your bot. Keep the window open; Ctrl+C stops it safely.

Don't know your Telegram id? Leave `OWNER_ID` empty, start the bot and send it any message — it replies with your id
(and does nothing else). Put it in `.env` and restart.

## 4. Update later
```powershell
git pull
powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -SkipConfig
```
`.env`, `keys.txt` and `data\` are never touched by updates.

## Better FFmpeg (recommended)
The installer brings a basic FFmpeg. For `ffprobe` (stronger video checks):
`winget install Gyan.FFmpeg`, then restart PowerShell.

## Free local AI (optional, recommended)
1. Install Ollama from ollama.com.
2. Download a model that fits 8 GB VRAM, e.g. `ollama pull qwen3:8b` (good with Hindi).
   If PowerShell does not know `ollama`, use `& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" pull qwen3:8b`.
3. The bot finds it automatically (Script Studio shows "AI: chalu"). To pick a specific model, set
   `ollama_model = "qwen3:8b"` under `[llm]` in `config\config.toml`.
