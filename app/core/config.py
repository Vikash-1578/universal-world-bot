"""Configuration.

Secrets (bot token, owner id) come from `.env`; AI keys from `keys.txt` (one `provider:key` per line);
everything else from `config/config.toml` (optional, defaults below). Nothing secret is stored in code or logs.
"""
from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


def load_dotenv(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        else:
            v = re.split(r"\s+#", v, maxsplit=1)[0].strip()
        out[k.strip()] = v
    return out


def parse_keys(text: str) -> list[tuple[str, str]]:
    """`provider:key` lines (also `NAME=value`). Bad lines are skipped."""
    out: list[tuple[str, str]] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^([A-Za-z][A-Za-z0-9_ .-]*?)\s*[:=]\s*(.+)$", line)
        if not m:
            continue
        name = m.group(1).strip().lower().replace(" ", "_").replace("-", "_")
        val = m.group(2).strip().strip("\"'")
        if val:
            out.append((name, val))
    return out


@dataclass
class Settings:
    bot_token: str = ""
    owner_id: int = 0
    base_dir: Path = field(default_factory=Path.cwd)
    data_dir: Path = Path("data")
    keys: list[tuple[str, str]] = field(default_factory=list)
    timezone: str = "Asia/Kolkata"
    max_heavy_workers: int = 1
    max_light_workers: int = 2
    fps: int = 30
    temp_retention_days: int = 7
    ffmpeg: str = ""
    blender: str = ""
    log_level: str = "INFO"
    raw: dict = field(default_factory=dict)

    def keys_for(self, *names: str) -> list[str]:
        wanted = {n.lower() for n in names}
        return [v for k, v in self.keys if k in wanted]

    def key(self, *names: str) -> str:
        ks = self.keys_for(*names)
        return ks[0] if ks else ""

    @property
    def db_path(self) -> Path:
        return self.data_dir / "hub.db"

    def path(self, *parts: str) -> Path:
        p = self.data_dir.joinpath(*parts)
        p.mkdir(parents=True, exist_ok=True)
        return p


def load_settings(base_dir: Path | None = None, env: dict[str, str] | None = None) -> Settings:
    base = (base_dir or Path.cwd()).resolve()
    envf = load_dotenv(base / ".env")
    if env is None:
        env = {**envf, **{k: v for k, v in os.environ.items() if k in envf or k.isupper()}}
    toml_path = base / "config" / "config.toml"
    raw: dict = {}
    if toml_path.exists():
        raw = tomllib.loads(toml_path.read_text(encoding="utf-8"))
    hub = raw.get("hub", {})
    owner_raw = env.get("OWNER_ID") or str(hub.get("owner_id", "")) or env.get("TELEGRAM_ALLOWED_USER_IDS", "").split(",")[0]
    try:
        owner = int(str(owner_raw).strip() or 0)
    except ValueError:
        owner = 0
    keys_file = base / env.get("AI_KEYS_FILE", "keys.txt")
    keys = parse_keys(keys_file.read_text(encoding="utf-8-sig")) if keys_file.exists() else []
    keys += parse_keys(env.get("AI_KEYS", "").replace(",", "\n"))
    # well-known env names also count as keys
    for name, prov in (("GEMINI_API_KEY", "gemini"), ("GROQ_API_KEY", "groq"), ("ELEVENLABS_API_KEY", "elevenlabs"),
                       ("PEXELS_API_KEY", "pexels"), ("PIXABAY_API_KEY", "pixabay"), ("CF_ACCOUNT_ID", "cf_account_id"),
                       ("CF_API_TOKEN", "cf_api_token"), ("POLLINATIONS_KEY", "pollinations")):
        if env.get(name):
            keys.append((prov, env[name]))
    data_dir = Path(env.get("HUB_DATA_DIR") or hub.get("data_dir") or "data")
    if not data_dir.is_absolute():
        data_dir = base / data_dir
    data_dir.mkdir(parents=True, exist_ok=True)
    render = raw.get("render", {})
    return Settings(
        bot_token=env.get("BOT_TOKEN", "") or env.get("TELEGRAM_BOT_TOKEN", ""),
        owner_id=owner,
        base_dir=base,
        data_dir=data_dir,
        keys=keys,
        timezone=hub.get("timezone", env.get("HUB_TZ", "Asia/Kolkata")),
        max_heavy_workers=int(hub.get("max_heavy_workers", 1)),
        max_light_workers=int(hub.get("max_light_workers", 2)),
        fps=int(render.get("fps", 30)),
        temp_retention_days=int(raw.get("storage", {}).get("temp_retention_days", 7)),
        ffmpeg=env.get("FFMPEG_PATH", raw.get("tools", {}).get("ffmpeg", "")),
        blender=env.get("BLENDER_PATH", raw.get("tools", {}).get("blender", "")),
        log_level=env.get("LOG_LEVEL", hub.get("log_level", "INFO")),
        raw=raw,
    )
