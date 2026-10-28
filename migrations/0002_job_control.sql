-- 0002: control flag for running jobs (pause / cancel requested), last heartbeat, human-readable job title
ALTER TABLE jobs ADD COLUMN control TEXT;
ALTER TABLE jobs ADD COLUMN heartbeat_at REAL;
ALTER TABLE jobs ADD COLUMN title TEXT NOT NULL DEFAULT '';
CREATE INDEX idx_jobs_idem ON jobs(idempotency_key);
