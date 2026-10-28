# Implementation checklist

Status legend: ✅ working + tested · 🟡 partly working · ⬜ not started · 🔒 blocked (needs something from the owner)

"Tested" means automated tests in this repo pass. Tests that use a fake Telegram session or fake AI are **test doubles** —
they prove our own logic, not that Telegram/AI/Blender behave the same way on the owner's laptop.

## Milestone 1 — Foundation and Security
| Item | Status | Notes |
|---|---|---|
| Repository + module layout | ✅ | matches master prompt §22 |
| Config (.env, keys.txt, config.toml) + validation | ✅ | tests/unit/test_foundation.py |
| Owner-only gate (messages + callbacks), setup mode | ✅ | tests/security/test_owner_only.py |
| One-time expiring approvals for sensitive actions | ✅ | |
| Logging with secret redaction, audit log | ✅ | |
| SQLite + migrations + foreign keys + integrity check | ✅ | migrations/ |
| Safe paths, upload validation | ✅ | |
| Diagnostics (Python, CPU, RAM, disk, GPU, FFmpeg, Blender, DB, config) | ✅ | verified on owner's laptop 2026-10-28 (8 OK, Blender missing) |
| install.ps1 / start.ps1 / diagnose.ps1 | ✅ | verified on Windows 11 + Python 3.14 (2026-10-28); backup.ps1 comes in M10 |

## Milestone 2 — Telegram Dashboard and Projects
| Item | Status | Notes |
|---|---|---|
| Main menu (17 sections, honest "coming in Milestone N") | ✅ | owner-only gate confirmed live on Telegram |
| Create / list / open / rename / settings / archive projects | ✅ | tests/integration/test_dashboard.py |
| Versioned, checksummed manifests | ✅ | |
| Conversation state survives restart | ✅ | |
| Stale / forged callback handling, rate limit | ✅ | |

## Milestone 3 — Persistent Scheduler
| Item | Status | Notes |
|---|---|---|
| Job states, priorities, dependencies (cycle check) | ✅ | tests/unit/test_scheduler.py |
| Stages + checkpoints (skip finished stages) | ✅ | |
| Pause / resume / cancel (stage boundary for running jobs) | ✅ | |
| Bounded retries for recoverable errors | ✅ | |
| Approval wait state | ✅ | |
| Restart recovery | ✅ | tests/recovery/test_restart.py |
| Live job cards in Telegram | ✅ | |
| Self-test job (real FFmpeg render + probe) | ✅ | passed on owner's laptop (FFmpeg 9.0.2) |

## Milestone 4 — Script and Storyboard ⬜
## Milestone 5 — Character and Environment Studio ⬜
## Milestone 6 — Working 2D Pipeline ⬜
## Milestone 7 — Working 3D Pipeline (Blender) ⬜
## Milestone 8 — Audio and Subtitles ⬜
## Milestone 9 — Model Management ⬜
## Milestone 10 — Delivery, Backup, Hardening ⬜ (backup.ps1 comes here)
