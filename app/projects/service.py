"""Projects: create / open / update / list / archive, versioned JSON manifests (master prompt sections 8, 19).

Folder layout per project (all inside the data folder):
    data/projects/<id>/manifest.json         current manifest
    data/projects/<id>/versions/v<N>.json     saved versions (checksummed in project_versions)
    data/projects/<id>/assets/ renders/ exports/
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from app.core.errors import InvalidInput, NotFound
from app.storage.db import Database, dumps, loads
from app.storage.files import safe_join, sha256

MANIFEST_SCHEMA = 1
TYPES = {"2d": "2D cartoon", "3d": "3D (Blender)", "slideshow": "Images + narration"}
STATUSES = ("draft", "scripting", "storyboard", "production", "rendering", "review", "done", "archived")
DEFAULT_SETTINGS = {"language": "hindi", "aspect": "16:9", "fps": 30, "resolution": "1080p", "audience": "kids",
                    "tone": "fun", "style": "kids cartoon", "target_seconds": 60, "cloud_ok": False}
ASPECTS = ("16:9", "9:16", "1:1")


class ProjectService:
    def __init__(self, db: Database, data_dir: Path) -> None:
        self.db = db
        self.root = data_dir / "projects"
        self.root.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------------- paths
    def folder(self, project_id: int, *sub: str) -> Path:
        p = safe_join(self.root, str(int(project_id)), *sub)
        p.mkdir(parents=True, exist_ok=True)
        return p

    # ---------------------------------------------------------------- CRUD
    def create_project(self, name: str, project_type: str = "2d", settings: dict | None = None) -> dict:
        name = " ".join((name or "").split())[:80]
        if len(name) < 2:
            raise InvalidInput("Project ka naam kam se kam 2 akshar ka ho.")
        if project_type not in TYPES:
            raise InvalidInput("Project type 2d, 3d ya slideshow ho.")
        merged = {**DEFAULT_SETTINGS, **self._clean_settings(settings or {})}
        now = time.time()
        pid = self.db.insert("projects", {"name": name, "project_type": project_type, "status": "draft",
                                          "settings_json": dumps(merged), "created_at": now, "updated_at": now})
        for sub in ("assets", "renders", "exports", "versions"):
            self.folder(pid, sub)
        self.save_version(pid, "Project bana")
        return self.get_project(pid)

    def _clean_settings(self, s: dict) -> dict:
        out: dict[str, Any] = {}
        for k, v in s.items():
            if k not in DEFAULT_SETTINGS:
                continue
            if k == "aspect" and v not in ASPECTS:
                raise InvalidInput("Aspect 16:9, 9:16 ya 1:1 ho.")
            if k == "fps" and int(v) not in (24, 30, 60):
                raise InvalidInput("FPS 24, 30 ya 60 ho.")
            if k == "target_seconds" and not 5 <= int(v) <= 1800:
                raise InvalidInput("Video 5 second se 30 minute ke beech ho.")
            out[k] = v
        return out

    def get_project(self, project_id: int) -> dict:
        row = self.db.one("SELECT * FROM projects WHERE id = ?", (int(project_id),))
        if not row:
            raise NotFound("Project nahi mila.")
        row["settings"] = loads(row.pop("settings_json"), {})
        return row

    def update_project(self, project_id: int, changes: dict) -> dict:
        p = self.get_project(project_id)
        vals: dict[str, Any] = {}
        if "name" in changes:
            name = " ".join(str(changes["name"]).split())[:80]
            if len(name) < 2:
                raise InvalidInput("Naam bahut chhota hai.")
            vals["name"] = name
        if "status" in changes:
            if changes["status"] not in STATUSES:
                raise InvalidInput("Galat status.")
            vals["status"] = changes["status"]
        if "settings" in changes:
            vals["settings_json"] = dumps({**p["settings"], **self._clean_settings(changes["settings"])})
        if vals:
            vals["updated_at"] = time.time()
            self.db.update("projects", p["id"], vals)
            self.write_manifest(p["id"])
        return self.get_project(project_id)

    def list_projects(self, *, archived: bool = False, offset: int = 0, limit: int = 6) -> tuple[list[dict], int]:
        cond = "archived_at IS NOT NULL" if archived else "archived_at IS NULL"
        total = self.db.one(f"SELECT COUNT(*) AS n FROM projects WHERE {cond}")["n"]
        rows = self.db.all(f"SELECT id, name, project_type, status, updated_at FROM projects WHERE {cond} "
                           "ORDER BY updated_at DESC LIMIT ? OFFSET ?", (limit, offset))
        return rows, int(total)

    def archive_project(self, project_id: int) -> dict:
        self.get_project(project_id)
        self.db.update("projects", project_id, {"archived_at": time.time(), "status": "archived", "updated_at": time.time()})
        return self.get_project(project_id)

    def unarchive_project(self, project_id: int) -> dict:
        self.get_project(project_id)
        self.db.update("projects", project_id, {"archived_at": None, "status": "draft", "updated_at": time.time()})
        return self.get_project(project_id)

    # ---------------------------------------------------------------- manifests / versions
    def manifest(self, project_id: int) -> dict:
        p = self.get_project(project_id)
        scripts = self.db.all("SELECT id, version_number, language, approval_status, created_at FROM scripts "
                              "WHERE project_id = ? ORDER BY version_number", (project_id,))
        scenes = self.db.all("SELECT * FROM scenes WHERE project_id = ? ORDER BY scene_number", (project_id,))
        assets = self.db.all("SELECT asset_type, relative_path, checksum, protected FROM assets WHERE project_id = ?", (project_id,))
        exports = self.db.all("SELECT preset, output_path, checksum, approval_status, kind FROM exports WHERE project_id = ?", (project_id,))
        return {
            "schema": MANIFEST_SCHEMA,
            "app": "universal-world-bot",
            "project": {"id": p["id"], "name": p["name"], "type": p["project_type"], "status": p["status"],
                        "settings": p["settings"], "created_at": p["created_at"], "updated_at": p["updated_at"]},
            "scripts": scripts,
            "scenes": [{**s, "dialogue": loads(s.pop("dialogue_json"), []), "characters": loads(s.pop("character_refs_json"), []),
                        "camera": loads(s.pop("camera_json"), {})} for s in scenes],
            "assets": assets,
            "exports": exports,
        }

    def write_manifest(self, project_id: int) -> Path:
        m = self.manifest(project_id)
        path = self.folder(project_id) / "manifest.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)  # atomic: a crash never leaves a half-written manifest
        return path

    def save_version(self, project_id: int, description: str = "") -> dict:
        self.write_manifest(project_id)
        row = self.db.one("SELECT COALESCE(MAX(version_number), 0) AS n FROM project_versions WHERE project_id = ?", (project_id,))
        n = int(row["n"]) + 1
        src = self.folder(project_id) / "manifest.json"
        dst = self.folder(project_id, "versions") / f"v{n}.json"
        dst.write_bytes(src.read_bytes())
        vid = self.db.insert("project_versions", {"project_id": project_id, "version_number": n,
                                                  "manifest_path": str(dst.relative_to(self.root)), "checksum": sha256(dst),
                                                  "created_at": time.time(), "description": description[:200]})
        return self.db.one("SELECT * FROM project_versions WHERE id = ?", (vid,))

    def versions(self, project_id: int) -> list[dict]:
        return self.db.all("SELECT * FROM project_versions WHERE project_id = ? ORDER BY version_number DESC", (project_id,))

    def verify_version(self, version_id: int) -> bool:
        v = self.db.one("SELECT * FROM project_versions WHERE id = ?", (version_id,))
        if not v:
            raise NotFound("Version nahi mila.")
        path = self.root / v["manifest_path"]
        return path.exists() and sha256(path) == v["checksum"]
