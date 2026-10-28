# Audit — code vs. final plan (2026-10-28, branch `review/audit-2026-10-28`)

Checked against the code, not README/CHECKLIST claims. Final decisions applied: **owner-only, Telegram-only, laptop-only**.
"Tests" = automated tests in this repo (sandbox: Linux, Python 3.13, real SQLite + scheduler + Pillow + FFmpeg;
Telegram / AI / image AI are test doubles). "Laptop" = seen working on the owner's Windows 11 laptop.

Status: ✅ implemented · 🟡 partial · ❌ missing

| # | Requirement | Where (code) | Status | Evidence | Tests |
|---|---|---|---|---|---|
| 1 | Single owner only, no team/invites | `app/core/security.py` OwnerGate (outer middleware on messages + callbacks), setup mode | ✅ | no team/invite code anywhere (grep) | `tests/security/test_owner_only.py`; laptop: stranger id refused |
| 2 | Telegram is the only UI, no Mini App / web frontend | `app/telegram/*` | ✅ | no web_app / Mini App / HTTP server code | integration tests (fake Telegram) |
| 3 | Windows 11 + ROG laptop, guided setup | `scripts/install.ps1` (asks token/owner, venv, DB, diagnostics), `start.ps1`, `update.ps1`, `diagnose.ps1` | ✅ | Python 3.11–3.14 accepted | laptop 2026-10-28 (Py 3.14.8, 9 OK) — no automated Windows CI |
| 4 | Laptop-only; offline when asleep | `start.ps1` foreground process, no service/deploy | ✅ | no deploy configs in repo | docs only |
| 5 | Local-first data | `data/` (SQLite `hub.db`, projects, library, work), relative paths + SHA-256 | ✅ | `app/storage/*` | unit tests |
| 6 | Cloud AI optional, explicit opt-in, no mandatory paid key | `Hub.cloud_enabled` (default False, approval token to enable); LLM / ImageRouter / STT check it | ✅ | only BOT_TOKEN + OWNER_ID required (`core/validation.py`) | `test_library.CloudImageTests` (no cloud call while OFF), owner_only tests |
| 7 | Projects + versions | `app/projects/service.py` | ✅ | checksummed versions, manifests | `test_dashboard.py` |
| 8 | Script / story workspace | `app/scripts/*`, `handlers/studio.py`, guided `handlers/wizard.py` (paste / PDF·DOCX·TXT / AI genre+length+idea, prose→script) | ✅ | | `test_script_storyboard.py`, `test_wizard.py` |
| 9 | Storyboard with owner approval | `app/storyboards/*`; final render refuses unapproved storyboard | ✅ | wizard's "Sab sahi — Final video banao" click is the approval (shown after the checklist) | `test_animation_2d.py`, `test_wizard.py` |
| 10 | Character / environment studio | `app/characters/*`, `handlers/library.py` (versions, QC, casting pinning, packages, AI image) | ✅ | Hindi names → English look before image; grass-disc removal | `test_library*.py`; laptop: Cloudflare images |
| 11 | Persistent job queue + recovery | `app/scheduler/service.py` (states, stages, checkpoints, reconcile) | ✅ | | `test_scheduler.py`, `tests/recovery/test_restart.py`, 2D resume test |
| 12 | Logs / diagnostics | `app/observability/*` (redaction, audit, diagnostics, self-test) | ✅ | | unit + laptop |
| 13 | Safe local storage | `storage/files.py` safe_join, upload checks, zip-slip protection | ✅ | | unit tests |
| 14 | 2D workflow | `app/animation/two_d/*` (planner, puppet, rig, job), `handlers/animation.py` | 🟡 | renders + validates real MP4; motion basic, **silent**, owner rated quality 0/10 | `test_animation_2d.py` (real FFmpeg); laptop renders |
| 15 | Blender 3D workflow | `app/animation/three_d/` (empty) | ❌ | Blender not installed on laptop; 2D renderer now refuses 3D projects | refusal test only |
| 16 | Separate 2D / 3D test projects | tests create separate 2D and 3D projects | 🟡 | 3D project exists only as a refusal case until M7 | `test_animation_2d.py` |
| 17 | Never render with placeholder/stand-in | `two_d/jobs.require_pictures`, `planner.load_scene` raises; stand-in drawing code removed | ✅ (this branch) | before this branch `load_scene` still had a stand-in fallback behind the gate | `test_load_scene_refuses_missing_pictures`, render-blocked tests |
| 18 | Adaptive quality / rendering | preview 360p·12fps vs final (project resolution/fps); 1 heavy job slot | 🟡 | no hardware-based auto choice; owner cannot set 720p from Telegram (settings has no resolution button) | partial |
| 19 | Multilingual | project language hindi/english/hinglish → script prompts; UI is Hinglish only | 🟡 | Devanagari text in rendered video not needed yet (no subtitles) | parser Hindi tests |
| 20 | Audio / voice / music | `app/audio/stt.py` (Groq speech-to-text, opt-in) only | ❌ | videos carry a silent track; no TTS, voices, music, SFX | — |
| 21 | Subtitles | `app/subtitles/` (empty) | ❌ | | — |
| 22 | Model management | Ollama auto-detect, Cloudflare/ComfyUI routing; `models` table unused | ❌ (🟡 detection) | no list/install/remove UI | LLM/ImageRouter tests |
| 23 | Smart export / delivery | `exports/validate.py` probe+check; auto-send video <48 MB else laptop path; `exports` table + manifest (this branch) | 🟡 | no presets (YouTube/Shorts), no export approval | render test |
| 24 | Backups | `app/backups/` empty, no `backup.ps1` | ❌ | | — |
| 25 | Hardening | rate limit, stale-callback handling, redaction, approvals, network-drop handling | 🟡 | temp clean-up (`temp_retention_days`) **not implemented**; no disk-space guard before render | partial |

## Stale / contradicting docs found (fixed on this branch)
* CHECKLIST M6 said "missing casting → stand-in figure / plain sky ✅" — contradicts the no-placeholder rule. Corrected.
* CHECKLIST M2 "17 sections" — main menu is now 6 buttons + 🧰 Aur tools. Corrected.
* CHECKLIST "verified on laptop ✅" for M6 hid the owner's 0/10 quality verdict. Corrected to file ✅ / quality ❌.
* README status stopped at M1–5 and did not say videos are silent. Corrected; added no-stand-in + Telegram-only lines.
* installation/troubleshooting said Python 3.12; installer accepts 3.11–3.14 and the laptop runs 3.14. Corrected.
* model-compatibility: missing the (laptop-tested) Cloudflare image row; said "green background" (now white). Corrected.
* architecture: table list missed library tables; `characters`/`models` tables are unused; approvals text described a
  job wait that storyboard does not use. Corrected.
* config.example implied temp clean-up happens; it does not. Marked as planned (M10).
* `exports` table was read by the manifest but never written. Now written on every export.

## Not changed (needs your decision — large or architectural)
1. **Audio (M8):** pick a TTS engine. Local+free: Piper (has Hindi voices, CPU, small) — voice variety by pitch/speed per
   character as you asked. Cloud alternative: Edge/Microsoft neural voices (better Hindi, but cloud). Needs new
   dependency + model download (~60–100 MB per voice).
2. **Better 2D motion:** walk cycles, facing, gestures need per-character pose images (AI can generate) — bigger change.
3. **3D (M7):** requires installing Blender 4.x on the laptop first.
4. **Backups (M10):** `backup.ps1` + Telegram 💾 Backups (zip of `data\` with checksums, keep last N).
5. Unused `characters` table: leave (harmless) or drop in a new migration — dropping is destructive, so not done.

## Test results (this branch, commit after these fixes)
63 passed, 0 failed, 0 skipped — sandbox Linux, Python 3.13, real FFmpeg (imageio-ffmpeg 7.0.2).
Not run: Windows 11 automated tests (no Windows runner here). Laptop checks are manual (steps below).

## Windows 11 local test steps (this branch)
```powershell
cd C:\uwb\universal-world-bot-main
.\scripts\update.ps1 -Ref <latest commit sha of the review branch>
.\scripts\start.ps1
```
1. Telegram `/menu` → 6 buttons.
2. 🎬 Nayi video banao → 2D → paste a short story → ✅ Theek hai.
3. Characters step: if any ⚠️ image nahi → 🎨 AI image (Cloud AI ON). Try 🎞/🎭 Animation preview **before** images exist:
   it must refuse and name the missing roles (no stand-in video).
4. After all images: ▶ Aage → Final check → 🎬 Final video. Video arrives (silent).
5. Make a 3D project (🎬 → 3D) → 🎭 Animation preview → must say "Ye project 2D nahi hai".
6. Optional (dev): `venv\Scripts\python -m pip install -r requirements-dev.txt` then `venv\Scripts\python -m pytest -q`.
