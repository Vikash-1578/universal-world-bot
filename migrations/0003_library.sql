-- 0003: reusable asset library (characters, environments, props) with versions, and project casting.
-- (The original `characters` table from 0001 is kept but unused; library_items covers characters, environments and props.)
CREATE TABLE library_items (
    id TEXT PRIMARY KEY,                       -- slug, e.g. "khargosh", "jungle-subah"
    kind TEXT NOT NULL CHECK (kind IN ('character','environment','prop')),
    name TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT '',
    current_version INTEGER NOT NULL DEFAULT 1,
    qc_status TEXT NOT NULL DEFAULT 'unchecked',   -- unchecked | needs_fix | ok | approved
    template_id TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE library_versions (
    item_id TEXT NOT NULL REFERENCES library_items(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    profile_json TEXT NOT NULL DEFAULT '{}',
    files_json TEXT NOT NULL DEFAULT '{}',        -- role -> {"path": relative, "sha256": ..., "w":, "h":}
    qc_json TEXT NOT NULL DEFAULT '{}',
    note TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    PRIMARY KEY (item_id, version)
);
CREATE TABLE project_items (
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    role TEXT NOT NULL,                           -- name used in the script ("Khargosh") or place name
    item_id TEXT NOT NULL REFERENCES library_items(id) ON DELETE RESTRICT,
    version INTEGER NOT NULL,                     -- pinned: library edits never silently change a project
    created_at REAL NOT NULL,
    PRIMARY KEY (project_id, role)
);
CREATE INDEX idx_library_kind ON library_items(kind, category, name);
