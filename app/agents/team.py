"""The team (15 roles). The owner talks ONLY to the Manager; every other agent is reached through it.
`status` is honest: planned = not built yet."""
from __future__ import annotations

TEAM: list[dict] = [
    {"key": "manager", "name": "Manager", "role": "Owner se baat, baaki agents ko control", "status": "building"},
    {"key": "research", "name": "Research", "role": "Web se research + har claim ka proof (link + quote)", "status": "basic"},
    {"key": "accuracy", "name": "Accuracy", "role": "Proof check; kamzor claim wapas research ko, 2+ sites ya gov/edu", "status": "basic"},
    {"key": "script", "name": "Script", "role": "Hook + Problem + Solution + Result + CTA", "status": "basic"},
    {"key": "virality", "name": "Script Virality Checker", "role": "Script ka viral-potential score; kamzor ho to rewrite", "status": "planned"},
    {"key": "voice", "name": "Voice", "role": "Edge-TTS professional voice (pitch/speed settings)", "status": "planned"},
    {"key": "media", "name": "Media", "role": "Stock footage/images (licensed) + licence log", "status": "planned"},
    {"key": "media_check", "name": "Media Checker", "role": "Clip script se match karti hai? Nahi to dobara / AI", "status": "planned"},
    {"key": "editor", "name": "Editor", "role": "Long video ya Shorts, CapCut-style editing", "status": "planned"},
    {"key": "video_check", "name": "Video Checker", "role": "Voice-visual sync check; galti editor ko wapas", "status": "planned"},
    {"key": "thumbnail", "name": "Thumbnail (+checker)", "role": "Professional thumbnail + uska checker", "status": "planned"},
    {"key": "seo", "name": "SEO", "role": "Title, description, tags, hashtags", "status": "planned"},
    {"key": "quality", "name": "Quality Checker", "role": "Final gate: sab rules pass?", "status": "basic"},
    {"key": "analyst", "name": "Channel Analyser", "role": "Views, comments, competitors, kya chal raha", "status": "planned"},
    {"key": "config", "name": "Config", "role": "Settings, keys, voice/video presets", "status": "planned"},
]
ICON = {"building": "🔨", "basic": "🟡", "planned": "⬜", "done": "✅"}
LEGEND = "✅ ready · 🟡 basic version · 🔨 ban raha · ⬜ abhi baaki"


def team_text() -> str:
    lines = ["👥 Meri team (tum sirf mujhse baat karte ho):", ""]
    for i, a in enumerate(TEAM, 1):
        lines.append(f"{ICON[a['status']]} {i}. {a['name']} — {a['role']}")
    lines += ["", LEGEND]
    return "\n".join(lines)
