"""System diagnostics: Python, disk, RAM, CPU, GPU/driver, FFmpeg, Blender, database, configuration.

Each check returns a plain-language status + a fix. Used by scripts/diagnose.ps1 (via `python -m app.diagnose`)
and by the Telegram "System Diagnostics" screen. Nothing here installs or changes anything.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from app.core.config import Settings
from app.core.validation import validate

OK, WARN, FAIL = "ok", "warn", "fail"
ICON = {OK: "✅", WARN: "⚠️", FAIL: "❌"}


@dataclass
class Check:
    name: str
    status: str
    detail: str = ""
    fix: str = ""
    data: dict = field(default_factory=dict)


def _run(cmd: list[str], timeout: float = 15) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except (OSError, subprocess.SubprocessError) as e:
        return -1, str(e)


def total_ram_gb() -> float | None:
    try:
        import psutil

        return psutil.virtual_memory().total / 1024 ** 3
    except Exception:  # noqa: BLE001
        return None


def free_ram_gb() -> float | None:
    try:
        import psutil

        return psutil.virtual_memory().available / 1024 ** 3
    except Exception:  # noqa: BLE001
        return None


def find_ffmpeg(s: Settings) -> str | None:
    if s.ffmpeg and Path(s.ffmpeg).exists():
        return s.ffmpeg
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg  # bundled fallback

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        return None


def find_ffprobe(ffmpeg: str | None) -> str | None:
    exe = shutil.which("ffprobe")
    if exe:
        return exe
    if ffmpeg:
        cand = Path(ffmpeg).with_name("ffprobe" + (".exe" if ffmpeg.lower().endswith(".exe") else ""))
        if cand.exists():
            return str(cand)
    return None


def find_blender(s: Settings) -> str | None:
    if s.blender and Path(s.blender).exists():
        return s.blender
    exe = shutil.which("blender")
    if exe:
        return exe
    pf = os.environ.get("ProgramFiles")
    if pf:
        root = Path(pf) / "Blender Foundation"
        found = sorted(root.glob("Blender*/blender.exe"), reverse=True) if root.exists() else []
        if found:
            return str(found[0])
    return None


def check_python() -> Check:
    v = sys.version_info
    if v >= (3, 11):
        return Check("Python", OK, platform.python_version())
    return Check("Python", FAIL, platform.python_version(), "Python 3.11 ya 3.12 install karo (python.org).")


def check_disk(s: Settings) -> Check:
    du = shutil.disk_usage(s.data_dir)
    free = du.free / 1024 ** 3
    st = OK if free >= 20 else WARN if free >= 5 else FAIL
    return Check("Disk", st, f"{free:.0f} GB free", "" if st == OK else "Kuch jagah khali karo (kam se kam 20 GB).",
                 {"free_gb": round(free, 1)})


def check_ram() -> Check:
    gb = total_ram_gb()
    if gb is None:
        return Check("RAM", WARN, "pata nahi chala", "pip install psutil")
    st = OK if gb >= 15 else WARN
    free = free_ram_gb()
    return Check("RAM", st, f"{gb:.0f} GB" + (f" ({free:.0f} GB free)" if free else ""),
                 "" if st == OK else "Kam RAM: ek waqt me ek hi heavy job chalegi.", {"ram_gb": round(gb, 1)})


def check_cpu() -> Check:
    return Check("CPU", OK, f"{platform.processor() or platform.machine()} · {os.cpu_count()} threads",
                 data={"threads": os.cpu_count()})


def check_gpu() -> Check:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return Check("GPU", WARN, "NVIDIA GPU / driver nahi mila",
                     "NVIDIA driver install/update karo. Tab tak sab CPU par chalega.")
    code, out = _run([exe, "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader,nounits"])
    if code != 0 or not out.strip():
        return Check("GPU", WARN, "driver tool chala par jawab nahi mila", "NVIDIA driver dobara install karo.")
    parts = [x.strip() for x in out.strip().splitlines()[0].split(",")]
    name, mem, drv = (parts + ["", "0", ""])[:3]
    try:
        vram = int(float(mem)) / 1024
    except ValueError:
        vram = 0.0
    return Check("GPU", OK, f"{name} · {vram:.0f} GB VRAM · driver {drv}", data={"vram_gb": round(vram, 1), "name": name})


def check_ffmpeg(s: Settings) -> Check:
    exe = find_ffmpeg(s)
    if not exe:
        return Check("FFmpeg", FAIL, "nahi mila", "scripts/install.ps1 chalao, ya: winget install Gyan.FFmpeg")
    code, out = _run([exe, "-hide_banner", "-version"])
    if code != 0:
        return Check("FFmpeg", FAIL, "chalaane par error", "FFmpeg dobara install karo.")
    ver = out.split("\n")[0].replace("ffmpeg version", "").strip().split(" ")[0]
    probe = find_ffprobe(exe)
    return Check("FFmpeg", OK if probe else WARN, ver + ("" if probe else " (ffprobe nahi mila)"),
                 "" if probe else "Poora FFmpeg (ffprobe ke saath) chahiye: winget install Gyan.FFmpeg",
                 {"ffmpeg": exe, "ffprobe": probe})


def check_blender(s: Settings) -> Check:
    exe = find_blender(s)
    if not exe:
        return Check("Blender", WARN, "nahi mila (3D pipeline band rahegi)",
                     "blender.org se Blender 4.x install karo, ya .env me BLENDER_PATH=... likho.")
    code, out = _run([exe, "--version"], timeout=60)
    first = out.strip().splitlines()[0] if out.strip() else ""
    if code != 0 or "Blender" not in first:
        return Check("Blender", WARN, "mila par chala nahi", "Blender dobara install karo.", {"blender": exe})
    return Check("Blender", OK, first, data={"blender": exe})


def check_database(s: Settings) -> Check:
    try:
        from app.storage.db import MIGRATIONS, Database

        db = Database(s.db_path)
        ok = db.integrity_ok()
        ver = db.version
        db.close()
        st = OK if ok and ver == len(MIGRATIONS) else FAIL
        return Check("Database", st, f"schema v{ver}" + ("" if ok else " · integrity problem"),
                     "" if st == OK else "Backup se restore karo (Backups menu ya scripts/backup.ps1 -Restore).")
    except Exception as e:  # noqa: BLE001
        return Check("Database", FAIL, type(e).__name__, "data/hub.db kharab ho sakta hai: backup se restore karo.")


def check_config(s: Settings) -> list[Check]:
    out = []
    probs = validate(s)
    if not probs:
        out.append(Check("Config", OK, "token + owner set"))
    for p in probs:
        out.append(Check("Config", FAIL if p.level == "error" else WARN, p.what, p.fix))
    commented = _commented_keys(s.base_dir / "keys.txt")
    if commented:
        out.append(Check("keys.txt", WARN, f"{len(commented)} key '#' ke peeche hai, isliye band hai: {', '.join(commented)}",
                         "keys.txt me us line ke shuru se '#' hatao (jaise: gemini:AIza...)."))
    providers = sorted({k for k, _ in s.keys})
    out.append(Check("API keys", OK if providers else WARN,
                     f"{len(s.keys)} keys ({', '.join(providers[:8])})" if providers else "keys.txt khali / nahi mila",
                     "" if providers else "Cloud AI optional hai. Chahiye to keys.txt me provider:key lines daalo."))
    return out


def _commented_keys(path: Path) -> list[str]:
    """Names of lines like '# gemini:AIza....' that look like a real key the owner forgot to un-comment."""
    import re

    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        return []
    out = []
    for line in text.splitlines():
        m = re.match(r"^\s*#\s*([A-Za-z][A-Za-z0-9_]*)\s*[:=]\s*(\S{16,})\s*$", line)
        if m and "xxx" not in m.group(2).lower():
            out.append(m.group(1))
    return out


def run_all(s: Settings, include_slow: bool = True) -> list[Check]:
    checks = [check_python(), check_cpu(), check_ram(), check_disk(s), check_gpu(), check_ffmpeg(s)]
    if include_slow:
        checks.append(check_blender(s))
    checks.append(check_database(s))
    checks += check_config(s)
    return checks


def summary(checks: list[Check]) -> str:
    lines = []
    for c in checks:
        line = f"{ICON[c.status]} {c.name}: {c.detail}"
        if c.fix and c.status != OK:
            line += f"\n    ➜ {c.fix}"
        lines.append(line)
    bad = sum(c.status == FAIL for c in checks)
    warn = sum(c.status == WARN for c in checks)
    lines.append(f"\n{len(checks) - bad - warn} OK · {warn} warning · {bad} fail")
    return "\n".join(lines)
