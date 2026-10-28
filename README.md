# Universal World Bot

A private, single-owner **AI video production hub controlled from Telegram**, running on your own Windows laptop.
Projects, scripts, storyboards with approval, reusable characters, a 2D pipeline, a Blender 3D pipeline, audio,
subtitles, persistent jobs, exports and backups — built in tested milestones.

> Status: Milestones 1–5 (foundation, dashboard, persistent scheduler, script + storyboard with approvals, character/environment library) are working and tested.
> See [docs/CHECKLIST.md](docs/CHECKLIST.md) for exactly what works and what does not yet.

* Only your Telegram account can use it.
* Everything is stored locally (`data\`). Cloud AI is **off** until you switch it on.
* When the laptop is off or asleep, the bot is offline.

Start here: [docs/installation.md](docs/installation.md) · Problems: [docs/troubleshooting.md](docs/troubleshooting.md) ·
Design: [docs/architecture.md](docs/architecture.md)

## Development
```
python -m pip install -r requirements-dev.txt
python -m pytest
python -m app.diagnose
```
