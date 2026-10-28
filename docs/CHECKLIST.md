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
| Menu sections with honest "coming in Milestone N" screens | ✅ | owner-only gate confirmed live on Telegram |
| Create / list / open / rename / settings / archive projects | ✅ | tests/integration/test_dashboard.py |
| Versioned, checksummed manifests | ✅ | |
| Conversation state survives restart | ✅ | |
| Stale / forged callback handling, rate limit | ✅ | |
| Short main menu (6 buttons) + 🧰 Aur tools | ✅ | owner asked 2026-10-28 |
| Guided 🎬 Nayi video flow: story (paste / file / AI genre+length+idea) → auto casting + photos + AI images → voice (M8) → final check → video | ✅ sandbox / ⬜ laptop | tests/integration/test_wizard.py (fake Telegram, fake AI) |
| No stand-in figure / plain sky in videos: missing picture blocks the render | ✅ | |

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

## Milestone 4 — Script and Storyboard
| Item | Status | Notes |
|---|---|---|
| Script input: text, .txt/.md/.docx/.pdf, reference photos | ✅ | tests/unit/test_script_storyboard.py (file reading); Telegram download path not tested with real Telegram yet |
| Voice → text (Groq Whisper, only with Cloud AI ON) | 🟡 | code done; **not tested with real Groq**; local Whisper = Milestone 9 |
| Script versions, approve / reject, never overwrite approved | ✅ | |
| Deterministic scene breakdown (no AI needed), Hindi + English | ✅ | |
| AI script writing / revision (job) | ✅ / 🟡 | worked with real Ollama qwen3:8b on owner's laptop (2026-10-28); Hindi quality is basic for an 8B model |
| LLM adapter: local Ollama first, cloud only after opt-in | ✅ | real Ollama verified on laptop; real Groq/Gemini not yet tested |
| Storyboard draft (rules) + AI Director suggestions (validated) | ✅ / 🟡 | rules tested; AI part tested with fake AI only |
| Scene edit, reorder, duration, shot/transition, regenerate | ✅ | regenerate needs real AI (🟡) |
| Storyboard approval gate; changes after approval need re-approval | ✅ | |
| Telegram screens (Script Studio, Storyboard Studio) | ✅ | tests/integration/test_studio_flow.py (fake Telegram) |
## Milestone 5 — Character and Environment Studio
| Item | Status | Notes |
|---|---|---|
| Library items (character / environment / prop) with versions | ✅ | tests/unit/test_library.py |
| Image import: auto background removal, 1080p background fit | ✅ | tested with generated images; real photos may need manual fix |
| QC report: transparency, size, rig hints (neck, two legs) + manual approve | ✅ | |
| Expressions + poses per character | ✅ | |
| 1100+ templates (48 hand-made + 1056 generated + 97 places), search | ✅ | text profiles only — no images until made |
| Project casting with version pinning ("naya version hai" warning) | ✅ | tests/integration/test_library_flow.py |
| Portable packages: export / import with checksum + zip-slip protection | ✅ | |
| AI description (Ollama) job | 🟡 | uses the same verified Ollama path; this prompt not yet tried on the laptop |
| AI image job: local ComfyUI or opt-in Cloudflare | ✅ / 🟡 | Cloudflare verified on laptop 2026-10-28 (lion character + auto cut-out); ComfyUI not installed yet |
| Telegram: Character / Environment Studio, Templates, Casting | ✅ | fake Telegram session |
## Milestone 6 — Working 2D Pipeline 🟡 (built + tested in sandbox; laptop test pending)
| Item | Status | Notes |
|---|---|---|
| Plan from storyboard + casting (pinned versions), deterministic | ✅ | tests/integration/test_animation_2d.py |
| Missing casting / picture -> clear error naming the role; render refused (no stand-in figure / plain sky) | ✅ | changed 2026-10-28 on owner's request; tests/integration/test_animation_2d.py |
| Puppet renderer (ported v1): walk-in with leg swing, talk bounce, emotions/poses if images exist, camera moves, mood grading, fades | ✅ | real Pillow + FFmpeg render in tests |
| Lip-sync (mouth) | 🟡 | only when the character has an `expr:talk` image; driven by estimated timing until M8 voices |
| Render job: one checkpoint per scene, resume reuses finished scenes (sha256 checked) | ✅ | retry test proves scene file not re-rendered |
| Join + validation (size, fps, audio stream, duration) + export to project/exports | ✅ | |
| Final needs approved storyboard (gate); preview works on draft | ✅ | |
| Telegram: Animation / Export screens, scene photo, auto-send video (<50 MB) | ✅ | fake Telegram session |
| Audio | ⛔ | silent track only — voices, music, subtitles are Milestone 8 |
| Verified on owner's laptop | ✅ (file) / ❌ (quality) | 2026-10-28: renders + validates 1080p; owner rated the result 0/10 — static figures, no audio, wrong AI pictures for Hindi names (fixed in code, not re-tested on laptop) |
## Milestone 7 — Working 3D Pipeline (Blender) ⬜
## Milestone 8 — Audio and Subtitles ⬜
## Milestone 9 — Model Management ⬜
## Milestone 10 — Delivery, Backup, Hardening ⬜ (backup.ps1 comes here)
