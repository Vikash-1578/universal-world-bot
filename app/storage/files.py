"""Safe file handling: every path the bot touches must stay inside the data folder.

* `safe_join` blocks path traversal (`..`, absolute paths, drive letters).
* `sha256` for checksums recorded in the database.
* `check_upload` validates type / size of files received from Telegram before processing.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path, PurePosixPath, PureWindowsPath

from app.core.errors import InvalidInput

ALLOWED = {
    "text": ({".txt", ".md", ".srt", ".vtt", ".json"}, 2 * 1024 * 1024),
    "document": ({".txt", ".md", ".pdf", ".docx"}, 20 * 1024 * 1024),
    "image": ({".png", ".jpg", ".jpeg", ".webp"}, 20 * 1024 * 1024),
    "audio": ({".mp3", ".wav", ".ogg", ".oga", ".m4a", ".flac"}, 50 * 1024 * 1024),
    "video": ({".mp4", ".mov", ".mkv", ".webm"}, 200 * 1024 * 1024),
    "model3d": ({".blend", ".glb", ".gltf", ".fbx", ".obj"}, 200 * 1024 * 1024),
}
_MAGIC = {
    b"\x89PNG": {".png"}, b"\xff\xd8\xff": {".jpg", ".jpeg"}, b"RIFF": {".wav", ".webp"}, b"OggS": {".ogg", ".oga"},
    b"ID3": {".mp3"}, b"%PDF": {".pdf"}, b"PK\x03\x04": {".docx", ".glb"}, b"fLaC": {".flac"},
}


def safe_name(name: str, default: str = "file") -> str:
    base = PureWindowsPath(PurePosixPath(name or "").name).name
    base = re.sub(r"[^\w.\- ]+", "_", base, flags=re.UNICODE).strip(" .")
    return (base or default)[:120]


def safe_join(root: Path, *parts: str) -> Path:
    root = root.resolve()
    for p in parts:
        if not p or p in (".", "..") or "\x00" in p or re.match(r"^[a-zA-Z]:", p) or p.startswith(("/", "\\")):
            raise InvalidInput("Galat file path.")
    target = root.joinpath(*parts).resolve()
    if target != root and root not in target.parents:
        raise InvalidInput("File path data folder se bahar ja raha hai.")
    return target


def sha256(path: Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def check_upload(kind: str, filename: str, size: int, head: bytes | None = None) -> str:
    """Return the cleaned filename or raise InvalidInput with a plain-language reason."""
    if kind not in ALLOWED:
        raise InvalidInput("Ye file type support nahi hai.")
    exts, limit = ALLOWED[kind]
    name = safe_name(filename)
    ext = Path(name).suffix.lower()
    if ext not in exts:
        raise InvalidInput(f"{ext or 'bina extension'} file nahi chalegi. Chalega: {', '.join(sorted(exts))}")
    if size <= 0:
        raise InvalidInput("File khali hai.")
    if size > limit:
        raise InvalidInput(f"File bahut badi hai (max {limit // (1024 * 1024)} MB).")
    if head:
        for magic, allowed in _MAGIC.items():
            if head.startswith(magic) and ext not in allowed:
                raise InvalidInput("File ka andar ka type uske naam se match nahi karta.")
    return name


def dir_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) if path.exists() else 0
