-- 0001: base schema (master prompt section 8)
CREATE TABLE projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    project_type TEXT NOT NULL CHECK (project_type IN ('2d','3d','slideshow')),
    status TEXT NOT NULL DEFAULT 'draft',
    settings_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    archived_at REAL
);
CREATE TABLE project_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL,
    manifest_path TEXT NOT NULL,
    checksum TEXT NOT NULL,
    created_at REAL NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    UNIQUE (project_id, version_number)
);
CREATE TABLE scripts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL,
    language TEXT NOT NULL DEFAULT 'hindi',
    content TEXT NOT NULL,
    approval_status TEXT NOT NULL DEFAULT 'draft',
    created_at REAL NOT NULL,
    UNIQUE (project_id, version_number)
);
CREATE TABLE scenes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    script_id INTEGER REFERENCES scripts(id) ON DELETE SET NULL,
    scene_number INTEGER NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    dialogue_json TEXT NOT NULL DEFAULT '[]',
    character_refs_json TEXT NOT NULL DEFAULT '[]',
    environment_ref TEXT,
    camera_json TEXT NOT NULL DEFAULT '{}',
    duration_seconds REAL NOT NULL DEFAULT 5,
    approval_status TEXT NOT NULL DEFAULT 'draft'
);
CREATE TABLE assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_type TEXT NOT NULL,
    relative_path TEXT NOT NULL UNIQUE,
    checksum TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    license_metadata TEXT NOT NULL DEFAULT '',
    protected INTEGER NOT NULL DEFAULT 0,
    project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
    created_at REAL NOT NULL
);
CREATE TABLE characters (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    profile_json TEXT NOT NULL DEFAULT '{}',
    current_version INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'catalog'
);
CREATE TABLE jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    job_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    priority INTEGER NOT NULL DEFAULT 5,
    progress REAL NOT NULL DEFAULT 0,
    stage TEXT NOT NULL DEFAULT '',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    input_manifest TEXT NOT NULL DEFAULT '{}',
    output_manifest TEXT NOT NULL DEFAULT '{}',
    error_code TEXT,
    error_message TEXT,
    idempotency_key TEXT UNIQUE,
    chat_id INTEGER,
    card_message_id INTEGER,
    heavy INTEGER NOT NULL DEFAULT 0,
    locked_by TEXT,
    not_before REAL NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    started_at REAL,
    finished_at REAL
);
CREATE TABLE job_dependencies (
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    depends_on_job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    PRIMARY KEY (job_id, depends_on_job_id)
);
CREATE TABLE job_stages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    stage_name TEXT NOT NULL,
    status TEXT NOT NULL,
    checkpoint_path TEXT,
    input_checksum TEXT,
    output_checksum TEXT,
    error_details TEXT,
    started_at REAL,
    finished_at REAL,
    UNIQUE (job_id, stage_name)
);
CREATE TABLE models (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    version TEXT NOT NULL DEFAULT '',
    task_type TEXT NOT NULL,
    runtime TEXT NOT NULL,
    license_metadata TEXT NOT NULL DEFAULT '',
    compatibility_json TEXT NOT NULL DEFAULT '{}',
    installation_path TEXT,
    status TEXT NOT NULL DEFAULT 'available'
);
CREATE TABLE exports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    project_version_id INTEGER REFERENCES project_versions(id) ON DELETE SET NULL,
    preset TEXT NOT NULL,
    output_path TEXT NOT NULL,
    resolution TEXT NOT NULL DEFAULT '',
    frame_rate REAL NOT NULL DEFAULT 0,
    duration_seconds REAL NOT NULL DEFAULT 0,
    checksum TEXT NOT NULL DEFAULT '',
    validation_json TEXT NOT NULL DEFAULT '{}',
    approval_status TEXT NOT NULL DEFAULT 'pending',
    kind TEXT NOT NULL DEFAULT 'final',
    created_at REAL NOT NULL
);
CREATE TABLE settings (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL,
    target_type TEXT NOT NULL DEFAULT '',
    target_id TEXT NOT NULL DEFAULT '',
    result TEXT NOT NULL,
    created_at REAL NOT NULL,
    details_redacted_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE approvals (
    token TEXT PRIMARY KEY,
    action TEXT NOT NULL,
    target TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    used_at REAL
);
CREATE INDEX idx_jobs_status ON jobs(status, priority, created_at);
CREATE INDEX idx_jobs_project ON jobs(project_id);
CREATE INDEX idx_scenes_project ON scenes(project_id, scene_number);
CREATE INDEX idx_exports_project ON exports(project_id);
CREATE INDEX idx_audit_time ON audit_events(created_at);
