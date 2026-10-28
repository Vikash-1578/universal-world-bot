# Model compatibility (owner's laptop: RTX 5050 Laptop 8 GB VRAM, 16 GB RAM)

Only models that were actually tested on the laptop are marked ✅. Everything else is a plan.

| Task | Tool / model | Runs where | Status |
|---|---|---|---|
| Script writing, AI Director, descriptions | Ollama `qwen3:8b` | GPU (~6-7 GB) | ✅ tested 2026-10-28 (Hindi: basic quality) |
| Script writing (alt) | Ollama `llama3.1:8b`, `gemma3:4b` | GPU | not tested |
| Character / background images | ComfyUI + SDXL checkpoint | GPU (SDXL ~7-8 GB) | ⬜ not installed yet |
| Speech-to-text | Groq Whisper (cloud, opt-in) | cloud | not tested |
| Speech-to-text (local) | faster-whisper | GPU/CPU | Milestone 9 |
| Text-to-speech | Piper / Kokoro / XTTS | CPU/GPU | Milestone 8 |
| 3D | Blender 4.x | GPU | Milestone 7 (not installed yet) |

Rules: one heavy model at a time (`max_heavy_workers = 1`), models are never downloaded automatically.

## ComfyUI (local image AI) — optional
ComfyUI makes character and background pictures on your own GPU. Without it, you upload your own images and
everything else still works.

1. Download **ComfyUI Desktop** for Windows from comfy.org and install it (it handles Python/NVIDIA itself).
2. Put one checkpoint in ComfyUI's `models\checkpoints` folder. For 8 GB VRAM an **SDXL** checkpoint
   (e.g. a cartoon-style SDXL model from a site you trust; check its licence) is a good start.
3. Start ComfyUI and keep it running. It listens on `http://127.0.0.1:8188` (or set `comfyui_url` in
   `config\config.toml` under `[image]`).
4. In Telegram: 🧍 Characters → the screen shows "🎨 AI image (ComfyUI): chalu".
5. Optional: `checkpoint = "file-name.safetensors"` under `[image]` to choose a specific one.

The bot asks ComfyUI for characters on a plain green background, then removes the background itself. If the
cut-out is not clean, upload a corrected PNG with 🖼 Nayi image (a new version is created, nothing is lost).

**Licences:** every checkpoint has its own licence. Check it before using images commercially (YouTube monetisation).
