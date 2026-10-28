# Troubleshooting

| Problem | Why | Fix |
|---|---|---|
| Bot does not reply at all | Laptop asleep/off, PowerShell window closed, or no internet | Open `scripts\start.ps1`. Set Windows sleep to "Never" while charging. |
| "⛔ Ye private bot hai" | Message came from an account that is not `OWNER_ID` | Check `OWNER_ID` in `.env` (numeric id, not @username). |
| Start says token problem | `BOT_TOKEN` missing / wrong | Copy again from @BotFather → /mybots → API Token. No spaces. |
| `running scripts is disabled` | PowerShell execution policy | Use `powershell -ExecutionPolicy Bypass -File scripts\...` exactly as written. |
| `python` not found | Python not installed / not on PATH | Install Python 3.12 from python.org with "Add to PATH". |
| FFmpeg ❌ in diagnostics | Packages not installed | Run `scripts\install.ps1` again, or `winget install Gyan.FFmpeg`. |
| Blender ⚠️ | Not installed / different folder | Install Blender 4.x, or set `BLENDER_PATH=` in `.env`. 3D stays off until then. |
| Job stuck "resource ka wait" | Another heavy job is running | Normal; it starts when the first finishes. Change `max_heavy_workers` only if you have spare RAM/VRAM. |
| Job "🔁 dobara try hoga" | Temporary error (network etc.) | It retries automatically a few times with a pause. |
| Button says "purana ho gaya" | The screen is old (bot restarted or data changed) | Send `/menu`. |
| Database ❌ | `data\hub.db` damaged | Restore from a backup (Milestone 10). |

Logs: `logs\hub.log` (secrets are removed automatically). Diagnostics: `scripts\diagnose.ps1` or Telegram → 🩺 Diagnostics.
