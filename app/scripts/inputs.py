"""Read story text out of files the owner sends: .txt / .md / .srt / .docx / .pdf.
.docx is read with the standard library (zip + XML); .pdf needs the small `pypdf` package (optional)."""
from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from app.core.errors import InvalidInput

MAX_CHARS = 60_000


def _docx(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml")
    except (zipfile.BadZipFile, KeyError) as e:
        raise InvalidInput("Ye .docx file khul nahi rahi.") from e
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    root = ElementTree.fromstring(xml)
    paras = []
    for p in root.iter(f"{ns}p"):
        paras.append("".join(t.text or "" for t in p.iter(f"{ns}t")))
    return "\n".join(paras)


def _pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as e:
        raise InvalidInput("PDF padhne ka module install nahi hai. Text (.txt) ya .docx bhejo.") from e
    try:
        reader = PdfReader(str(path))
        return "\n".join((pg.extract_text() or "") for pg in reader.pages[:60])
    except Exception as e:  # noqa: BLE001
        raise InvalidInput("Ye PDF padh nahi paaye (scan wali PDF me text nahi hota).") from e


def _srt(text: str) -> str:
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.strip().isdigit() and "-->" not in ln]
    return "\n".join(lines)


def read_text_file(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == ".docx":
        text = _docx(path)
    elif ext == ".pdf":
        text = _pdf(path)
    else:
        raw = path.read_bytes()
        for enc in ("utf-8-sig", "utf-16", "cp1252"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise InvalidInput("File ka text padh nahi paaye (encoding).")
        if ext in (".srt", ".vtt"):
            text = _srt(text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        raise InvalidInput("File me koi text nahi mila.")
    if len(text) > MAX_CHARS:
        raise InvalidInput(f"Script bahut lambi hai ({len(text)} akshar). {MAX_CHARS} tak bhejo ya hisso me baanto.")
    return text
