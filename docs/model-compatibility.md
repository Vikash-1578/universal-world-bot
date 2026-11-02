# Model compatibility (owner's laptop: RTX 5050 Laptop 8 GB VRAM, 16 GB RAM)

Only models that were actually tested on the laptop are marked ✅. Everything else is a plan.

| Task | Tool / model | Runs where | Status |
|---|---|---|---|
| Script writing, research notes | Ollama `qwen3:8b` | GPU (~6-7 GB) | ✅ tested 2026-10-28 (Hindi: basic quality) |
| Script writing (alt) | Ollama `llama3.1:8b`, `gemma3:4b` | GPU | not tested |
| Speech-to-text | Groq Whisper (cloud, opt-in) | cloud | not tested |
| Speech-to-text (local) | faster-whisper | GPU/CPU | Milestone 9 |
| Text-to-speech | Piper / Kokoro / XTTS | CPU/GPU | Milestone 8 |

Rules: one heavy model at a time (`max_heavy_workers = 1`), models are never downloaded automatically.
