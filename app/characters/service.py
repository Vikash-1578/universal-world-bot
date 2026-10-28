"""Asset library (master prompt §11, §12): characters, environments and props with versions, QC and project casting.

* Every change (profile edit, new image, new expression) creates a new version; old files are never overwritten.
* A project pins a specific version (`project_items`), so editing a character never silently changes an old project.
* Files live under data/library/<item>/v<N>/ and are recorded in `assets` (protected, checksummed).
"""
from __future__ import annotations

import re
import time
import unicodedata
from pathlib import Path
from typing import Any

from app.characters import imaging, templates
from app.core.errors import Conflict, InvalidInput, NotFound
from app.storage.db import Database, dumps, loads
from app.storage.files import safe_join, sha256

KINDS = ("character", "environment", "prop")
EXPRESSIONS = ("happy", "sad", "angry", "surprised", "scared", "talk", "blink")
POSES = ("wave", "point", "walk", "sit", "run")
PROFILE_FIELDS = {
    "character": ("description", "look", "style", "proportions", "gender", "age", "size", "outfits", "voice", "personality"),
    "environment": ("description", "look", "style", "setting", "time_of_day", "lighting"),
    "prop": ("description", "look", "style"),
}
BG_SIZE = (1920, 1080)


def slugify(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s[:40]


class LibraryService:
    def __init__(self, db: Database, data_dir: Path) -> None:
        self.db = db
        self.data_dir = data_dir
        self.root = data_dir / "library"
        self.root.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------------- items
    def _new_id(self, base: str, kind: str) -> str:
        base = base or {"character": "char", "environment": "place", "prop": "prop"}[kind]
        cand, n = base, 2
        while self.db.one("SELECT 1 FROM library_items WHERE id = ?", (cand,)):
            cand, n = f"{base}-{n}", n + 1
        return cand

    def create_item(self, kind: str, name: str, profile: dict | None = None, *, category: str = "", template_id: str | None = None,
                    note: str = "Bana") -> dict:
        if kind not in KINDS:
            raise InvalidInput("Kind character / environment / prop ho.")
        name = " ".join((name or "").split())[:60]
        if len(name) < 2:
            raise InvalidInput("Naam kam se kam 2 akshar ka ho.")
        iid = self._new_id(slugify(name) or (template_id or "").replace("_", "-")[:40], kind)
        now = time.time()
        prof = self._clean_profile(kind, profile or {})

        def tx(db: Database) -> None:
            db.insert("library_items", {"id": iid, "kind": kind, "name": name, "category": category[:40], "current_version": 1,
                                        "template_id": template_id, "created_at": now, "updated_at": now})
            db.insert("library_versions", {"item_id": iid, "version": 1, "profile_json": dumps(prof), "files_json": "{}",
                                           "qc_json": "{}", "note": note[:200], "created_at": now})

        self.db.tx(tx)
        return self.get(iid)

    def from_template(self, template_id: str) -> dict:
        t = templates.get(template_id)
        if not t:
            raise NotFound("Template nahi mila.")
        kind = "environment" if t["kind"] == "place" else "character"
        style = templates.catalog()["style"]
        if kind == "character":
            prof = {"description": t.get("look", ""), "look": t.get("look", ""), "style": style, "gender": t.get("gender", ""),
                    "age": t.get("age", ""), "size": t.get("size", "medium"),
                    "voice": {"preset": t.get("voice", ""), "tune": t.get("tune", [0, 0])}}
        else:
            prof = {"description": t.get("look", ""), "look": t.get("look", ""), "style": style,
                    "time_of_day": "night" if "raat" in template_id else "day"}
        return self.create_item(kind, t["name"], prof, category=t.get("category", ""), template_id=template_id, note="Template se bana")

    def _clean_profile(self, kind: str, prof: dict) -> dict:
        out: dict[str, Any] = {}
        for k, v in prof.items():
            if k not in PROFILE_FIELDS[kind]:
                continue
            if isinstance(v, str):
                v = v.strip()[:1000]
            out[k] = v
        return out

    def get(self, item_id: str, version: int | None = None) -> dict:
        it = self.db.one("SELECT * FROM library_items WHERE id = ?", (item_id,))
        if not it:
            raise NotFound("Library item nahi mila.")
        v = self.db.one("SELECT * FROM library_versions WHERE item_id = ? AND version = ?", (item_id, version or it["current_version"]))
        if not v:
            raise NotFound("Ye version nahi mila.")
        it["version"] = v["version"]
        it["profile"] = loads(v["profile_json"], {})
        it["files"] = loads(v["files_json"], {})
        it["qc"] = loads(v["qc_json"], {})
        it["note"] = v["note"]
        return it

    def list_items(self, kind: str, *, query: str = "", offset: int = 0, limit: int = 8) -> tuple[list[dict], int]:
        where, params = "kind = ?", [kind]
        if query:
            where += " AND (name LIKE ? OR id LIKE ? OR category LIKE ?)"
            q = f"%{query.strip()[:40]}%"
            params += [q, q, q]
        total = self.db.one(f"SELECT COUNT(*) AS n FROM library_items WHERE {where}", tuple(params))["n"]
        rows = self.db.all(f"SELECT * FROM library_items WHERE {where} ORDER BY updated_at DESC LIMIT ? OFFSET ?", (*params, limit, offset))
        return rows, int(total)

    def versions(self, item_id: str) -> list[dict]:
        return self.db.all("SELECT version, note, created_at, files_json FROM library_versions WHERE item_id = ? ORDER BY version DESC",
                           (item_id,))

    # ---------------------------------------------------------------- new versions
    def _new_version(self, item_id: str, *, profile: dict | None = None, files: dict | None = None, qc: dict | None = None,
                     note: str = "") -> dict:
        cur = self.get(item_id)
        n = cur["version"] + 1
        now = time.time()

        def tx(db: Database) -> None:
            db.insert("library_versions", {"item_id": item_id, "version": n,
                                           "profile_json": dumps(profile if profile is not None else cur["profile"]),
                                           "files_json": dumps(files if files is not None else cur["files"]),
                                           "qc_json": dumps(qc if qc is not None else cur["qc"]), "note": note[:200], "created_at": now})
            db.update("library_items", item_id, {"current_version": n, "updated_at": now,
                                                 **({"qc_status": "unchecked" if not qc else ("ok" if qc.get("ok") else "needs_fix")}
                                                    if files is not None else {})})

        self.db.tx(tx)
        return self.get(item_id)

    def update_profile(self, item_id: str, changes: dict, note: str = "Profile badla") -> dict:
        cur = self.get(item_id)
        if "name" in changes:
            name = " ".join(str(changes.pop("name")).split())[:60]
            if len(name) < 2:
                raise InvalidInput("Naam chhota hai.")
            self.db.update("library_items", item_id, {"name": name})
        prof = {**cur["profile"], **self._clean_profile(cur["kind"], changes)}
        return self._new_version(item_id, profile=prof, note=note)

    def _store(self, item_id: str, version: int, role: str, data: bytes, ext: str) -> dict:
        folder = safe_join(self.root, item_id, f"v{version}")
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{re.sub(r'[^a-z0-9_]+', '_', role.lower())}.{ext}"
        path.write_bytes(data)
        rel = str(path.relative_to(self.data_dir)).replace("\\", "/")
        digest = sha256(path)
        self.db.execute("INSERT OR REPLACE INTO assets (asset_type, relative_path, checksum, metadata_json, protected, project_id, created_at) "
                        "VALUES (?, ?, ?, ?, 1, NULL, ?)", (f"library:{role}", rel, digest, dumps({"item": item_id, "version": version}),
                                                          time.time()))
        return {"path": rel, "sha256": digest}

    def add_image(self, item_id: str, role: str, data: bytes, *, source: str = "upload") -> tuple[dict, imaging.QC | None]:
        """Add or replace one image (main / expression / pose / background / reference) as a new version."""
        cur = self.get(item_id)
        kind = cur["kind"]
        valid = {"main", "reference"} | {f"expr:{e}" for e in EXPRESSIONS} | {f"pose:{p}" for p in POSES}
        if kind == "environment":
            valid = {"background", "background:night", "reference"}
        if role not in valid:
            raise InvalidInput(f"Ye image type yahan nahi chalega: {role}")
        im = imaging.open_image(data)
        nv = cur["version"] + 1
        files = dict(cur["files"])
        qc: imaging.QC | None = None
        if role == "reference":
            files[f"reference:{int(time.time())}"] = self._store(item_id, nv, f"reference_{int(time.time())}", imaging.png_bytes(im.convert("RGB")), "png")
        elif kind == "environment":
            files[f"{role}:original"] = self._store(item_id, nv, f"{role}_original", imaging.png_bytes(im.convert("RGB")), "png")
            bg = imaging.cover(im, *BG_SIZE)
            files[role] = {**self._store(item_id, nv, role, imaging.png_bytes(bg), "png"), "w": bg.width, "h": bg.height}
            qc = imaging.analyse(im, "environment")
        else:
            cut = im.convert("RGBA") if imaging.has_alpha(im) else imaging.cutout(im)
            files[f"{role}:original"] = self._store(item_id, nv, f"{role}_original", imaging.png_bytes(im.convert("RGBA")), "png")
            if cut is None:
                cut = im.convert("RGBA")  # keep it, QC will say "background nahi hata"
            if cut.getbbox():
                cut = cut.crop(cut.getchannel("A").getbbox() or (0, 0, cut.width, cut.height))
            files[role] = {**self._store(item_id, nv, role, imaging.png_bytes(cut), "png"), "w": cut.width, "h": cut.height}
            qc = imaging.analyse(cut, "character" if kind == "character" else "prop")
        qc_all = dict(cur["qc"])
        if qc is not None:
            qc_all[role] = qc.to_dict()
        main_role = "background" if kind == "environment" else "main"
        overall = {**qc_all, "ok": bool(qc_all.get(main_role, {}).get("ok"))}
        updated = self._new_version(item_id, files=files, qc=overall, note=f"{role} image ({source})")
        return updated, qc

    def approve_qc(self, item_id: str) -> dict:
        it = self.get(item_id)
        main = "background" if it["kind"] == "environment" else "main"
        if main not in it["files"]:
            raise Conflict("Pehle main image do, phir approve karo.")
        self.db.update("library_items", item_id, {"qc_status": "approved", "updated_at": time.time()})
        return self.get(item_id)

    def file_path(self, item: dict, role: str) -> Path | None:
        f = item["files"].get(role)
        if not f:
            return None
        p = safe_join(self.data_dir, *f["path"].split("/"))
        return p if p.exists() else None

    # ---------------------------------------------------------------- projects (casting)
    def cast(self, project_id: int, role: str, item_id: str, version: int | None = None) -> dict:
        it = self.get(item_id, version)
        role = " ".join(role.split())[:60]
        if not role:
            raise InvalidInput("Role ka naam chahiye.")
        self.db.execute("INSERT INTO project_items (project_id, role, item_id, version, created_at) VALUES (?, ?, ?, ?, ?) "
                        "ON CONFLICT(project_id, role) DO UPDATE SET item_id = excluded.item_id, version = excluded.version",
                        (project_id, role, item_id, it["version"], time.time()))
        return self.casting(project_id)[role]

    def uncast(self, project_id: int, role: str) -> None:
        self.db.execute("DELETE FROM project_items WHERE project_id = ? AND role = ?", (project_id, role))

    def casting(self, project_id: int) -> dict[str, dict]:
        rows = self.db.all("SELECT pi.role, pi.item_id, pi.version, li.kind, li.name, li.current_version FROM project_items pi "
                           "JOIN library_items li ON li.id = pi.item_id WHERE pi.project_id = ? ORDER BY pi.created_at", (project_id,))
        return {r["role"]: {**r, "outdated": r["version"] < r["current_version"]} for r in rows}

    def used_by(self, item_id: str) -> list[dict]:
        return self.db.all("SELECT pi.project_id, pi.role, pi.version, p.name FROM project_items pi JOIN projects p ON p.id = pi.project_id "
                           "WHERE pi.item_id = ?", (item_id,))

    def suggest_for(self, name: str, kind: str = "character") -> tuple[list[dict], list[dict]]:
        """Existing library items + catalog templates that match a script name (e.g. 'Khargosh')."""
        own, _ = self.list_items(kind, query=name.split()[0] if name.split() else name, limit=5)
        tmpl = templates.search(name, "place" if kind == "environment" else "actor", limit=5)
        return own, tmpl
