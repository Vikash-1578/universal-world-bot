# Implementation checklist

Status legend: ✅ working + tested · 🟡 partly working · ⬜ not started · 🔒 blocked (needs something from the owner)

"Tested" means automated tests in this repo pass. Tests that use a fake Telegram session or fake AI are **test doubles** —
they prove our own logic, not that Telegram/AI behave the same way on the owner's laptop.

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
| Diagnostics (Python, CPU, RAM, disk, GPU, FFmpeg, DB, config) | ✅ | verified on owner's laptop 2026-10-28 (8 OK, Blender missing) |
| install.ps1 / start.ps1 / diagnose.ps1 | ✅ | verified on Windows 11 + Python 3.14 (2026-10-28); backup.ps1 comes in M10 |

## Milestone 2 — Telegram Dashboard and Projects
| Item | Status | Notes |
|---|---|---|
| Main menu (17 sections, honest "coming in Milestone N") | ✅ | owner-only gate confirmed live on Telegram |
| Create / list / open / rename / settings / archive projects | ✅ | tests/integration/test_dashboard.py |
| Versioned, checksummed manifests | ✅ | |
| Conversation state survives restart | ✅ | |
| Stale / forged callback handling, rate limit | ✅ | |
| Short main menu (6 buttons) + 🧰 Aur tools | ✅ | owner asked 2026-10-28 |

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

## Milestone 4 — Script Studio
| Item | Status | Notes |
|---|---|---|
| Script input: text, .txt/.md/.docx/.pdf, reference photos | ✅ | tests/unit/test_scripts.py (file reading); Telegram download path not tested with real Telegram yet |
| Voice → text (Groq Whisper, only with Cloud AI ON) | 🟡 | code done; **not tested with real Groq**; local Whisper = Milestone 9 |
| Script versions, approve / reject, never overwrite approved | ✅ | |
| Deterministic scene breakdown (no AI needed), Hindi + English | ✅ | |
| AI script writing / revision (job) | ✅ / 🟡 | worked with real Ollama qwen3:8b on owner's laptop (2026-10-28); Hindi quality is basic for an 8B model |
| LLM adapter: local Ollama first, cloud only after opt-in | ✅ | real Ollama verified on laptop; real Groq/Gemini not yet tested |
| Telegram screens (Script Studio) | ✅ | tests/integration/test_studio_flow.py (fake Telegram) |
## Removed (2026-11) — cartoon pipeline
Character/environment library, storyboards, 2D animation, Blender 3D and ComfyUI image AI were removed; the channel is faceless facts/history/mystery.

## Agents (laptop first) — step 1 built, branch `agents`
| Item | Status | Notes |
|---|---|---|
| Manager job `video_pipeline`: research → fact-check → script → quality (max 2 auto revisions), resumable stages | ✅ sandbox / ⬜ laptop | tests/unit/test_agents.py (fake AI) |
| Research agent: Wikipedia + pages it cites (+Brave/DuckDuckGo) → relevance filter → model PICKS sentences; the proof quote is always a real sentence of the page | ✅ sandbox / 🟡 real internet | tests/unit/test_agents.py (fake web + fake AI) |
| Accuracy agent: code finds the closest sentence on every other page, model only judges same-fact/conflict; accepted = ≥2 independent domains incl. ≥1 tier A/B (or 1 gov/edu), no contradiction; unproven → 2 rounds re-research → dropped; proof.md sent | ✅ sandbox / 🟡 real internet | not a guarantee of truth — owner still approves |
| Quality Checker (deterministic, offline) | ✅ | |
| Never approves a script automatically | ✅ | |
| Manager chat: plain Hinglish text → intents (new video, status, show script, approve, revise, team); asks haan/nahi before anything runs | ✅ sandbox / ⬜ laptop | tests/unit/test_manager_chat.py |
| Team registry (15 roles, honest status) | ✅ | app/agents/team.py |
| Telegram button 🚀 Auto video script (agents) | ✅ sandbox / ⬜ laptop | |

## Next — remaining agents
Manager, Research, Fact-Check, Script, Quality Checker → then Voice (own cloned voice), Media (licensed footage + licence log), Editor → later Thumbnail, SEO, Uploader, Community, Analytics, Config.

## Milestone 8 — Audio and Subtitles ⬜
## Milestone 9 — Model Management ⬜
## Milestone 10 — Delivery, Backup, Hardening ⬜ (backup.ps1 comes here)
