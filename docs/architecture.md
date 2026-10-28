# Architecture

Universal World Bot is a single-owner, Telegram-controlled, local-first video production hub that runs on the
owner's Windows laptop. Telegram is the only UI. When the laptop is off or asleep, the bot cannot run jobs.

```
Telegram  ──►  app/telegram (handlers, keyboards, callbacks, conversations)
                    │   OwnerGate middleware (every message & button) + RateLimit
                    ▼
               app/container.Hub  (dependency container; handlers only call services)
                    │
   ┌────────────┬───┴──────────┬──────────────┬────────────────┬──────────────┐
 projects    scheduler       scripts /      characters /     animation       exports /
 (manifests, (persistent     storyboards    environments     two_d / three_d  rendering
  versions)   jobs, stages,  (approval      (asset library)  (Pillow+FFmpeg / (FFmpeg, probe,
              checkpoints)    gates)                          Blender)         validation)
                    │
               storage (SQLite + migrations, safe paths, checksums)  ·  observability (logs, audit, diagnostics)
```

## Key rules
* **Owner only.** `core/security.OwnerGate` drops every update not from `OWNER_ID`. Sensitive services require a
  one-time approval token (`core/security.Approvals`), so a Telegram button is never the only check.
* **Local first, cloud opt-in.** Cloud AI stays off until the owner enables it in Settings (with confirmation).
  Keys in `keys.txt` are never used while it is off.
* **Long work is a job.** Handlers submit jobs; `scheduler/service.JobService` runs them outside the Telegram
  handler, with heavy/light worker limits so the laptop is not overloaded (default: 1 heavy job).
* **Stages + checkpoints.** A job is a list of stages; each finished stage stores a small JSON checkpoint and the
  checksum of its inputs. After a crash/restart the job resumes and skips finished stages whose inputs did not change.
  Non-resumable steps (one FFmpeg/Blender render) simply restart that stage.
* **Approvals.** Script and storyboard approval are owner button clicks (Script Studio / Storyboard, or the guided
  flow's "✅ Theek hai" and "🎬 Sab sahi — Final video banao"). A final render refuses an unapproved storyboard. Jobs can also
  stop in `waiting_for_approval`.
* **No stand-ins.** A render refuses any scene whose character or background has no picture and names what is missing.
* **Data stays local.** Everything lives under `data/` (configurable): `hub.db`, `projects/<id>/...`, `work/`.
  Media is on disk; the database stores relative paths + SHA-256 checksums.
* **Honesty.** Menu sections that are not built yet say which milestone they arrive in. Tests that use fakes
  are labelled as test doubles.

## Job states
`queued → running → completed` plus `waiting_for_resources`, `waiting_for_approval`, `paused`, `retry_pending`,
`failed`, `cancel_requested`, `cancelled`. See `app/scheduler/service.py`.

## Database
SQLite with numbered migrations in `migrations/` (applied in a transaction at start-up; the app refuses to run on a
database newer than its code). Tables: projects, project_versions, scripts, scenes, assets, characters, jobs,
job_dependencies, job_stages, models, exports, settings, audit_events, approvals, and (migration 0003) library_items,
library_versions, project_items. `characters` and `models` are created but not used yet (the library uses `library_*`;
the model manager is Milestone 9). Rendered videos are stored as `assets` (type `export:video`) and listed in `exports`.

## Changes from the suggested structure
* `app/core/config.py`, `security.py`, `events.py`, `errors.py` are single modules instead of sub-packages (small enough).
* `app/container.py` (service wiring) and `app/pipelines.py` (job registration) were added.
