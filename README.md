# Universal World Bot

A private, single-owner **AI video production hub controlled from Telegram**, running on your own Windows laptop.
Projects, scripts, storyboards with approval, reusable characters, a 2D pipeline, a Blender 3D pipeline, audio,
subtitles, persistent jobs, exports and backups — built in tested milestones.

> Status: Milestones 1–5 work and are tested. Milestone 6 (2D) now renders with **real local voices** (Piper TTS, free,
> no API key), lip-sync from the audio, visible body/head motion and an `.srt` subtitle file — tested in the sandbox
> (incl. a real Hindi Piper voice), **not yet re-tested on the owner's laptop**. Not built yet: music/SFX and burned-in
> subtitles, 3D/Blender (M7), model manager (M9), backups/hardening (M10).
> See [docs/CHECKLIST.md](docs/CHECKLIST.md) and [docs/AUDIT.md](docs/AUDIT.md) for exactly what works and what does not.

* Only your Telegram account can use it.
* Everything is stored locally (`data\`). Cloud AI is **off** until you switch it on.
* When the laptop is off or asleep, the bot is offline.
* Telegram is the only interface (buttons + messages). No web app, no team accounts.
* A video is never made with stand-in figures: if a character or background has no picture, the render stops and says which one.

Start here: [docs/installation.md](docs/installation.md) · Problems: [docs/troubleshooting.md](docs/troubleshooting.md) ·
Design: [docs/architecture.md](docs/architecture.md)

## Development
```
python -m pip install -r requirements-dev.txt
python -m pytest
python -m app.diagnose
```
