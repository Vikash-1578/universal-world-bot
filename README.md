# Universal World Bot

A private, single-owner **AI production hub controlled from Telegram**, running on your own Windows laptop,
for faceless **facts / history / geography / science / mystery** YouTube videos (channel: Verinomia).
Projects, script writing with approval, persistent jobs, exports and backups — plus a team of specialist agents
(Manager, Research, Fact-Check, Script, Quality Checker, then Voice, Media, Editor ...) being added step by step.

> Status: foundation, dashboard, persistent scheduler and script studio (with approvals) exist. Cartoon / character / animation / Blender code has been removed.
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
