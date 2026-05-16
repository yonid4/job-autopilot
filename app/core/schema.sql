PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS jobs (
    id            TEXT PRIMARY KEY,
    url           TEXT UNIQUE NOT NULL,
    title         TEXT NOT NULL,
    company       TEXT NOT NULL,
    description   TEXT,
    salary        TEXT,
    job_level     TEXT,
    title_company TEXT,
    embedding     TEXT,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS jobs_title_company_idx ON jobs (title_company);
CREATE INDEX IF NOT EXISTS jobs_created_at_idx ON jobs (created_at DESC);

CREATE TABLE IF NOT EXISTS resumes (
    id           TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL,
    label        TEXT NOT NULL DEFAULT 'default',
    storage_path TEXT NOT NULL,
    parsed_json  TEXT,
    is_active    INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS resumes_user_id_idx ON resumes (user_id);

CREATE TABLE IF NOT EXISTS resume_chunks (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    resume_id   TEXT NOT NULL REFERENCES resumes(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    section     TEXT,
    content     TEXT NOT NULL,
    embedding   TEXT,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS resume_chunks_user_id_idx  ON resume_chunks (user_id);
CREATE INDEX IF NOT EXISTS resume_chunks_resume_id_idx ON resume_chunks (resume_id);

CREATE TABLE IF NOT EXISTS user_projects (
    id           TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL,
    name         TEXT NOT NULL,
    description  TEXT NOT NULL,
    technologies TEXT,
    url          TEXT,
    embedding    TEXT,
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS user_projects_user_id_idx ON user_projects (user_id);

CREATE TABLE IF NOT EXISTS applications (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    job_id          TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    resume_id       TEXT REFERENCES resumes(id) ON DELETE SET NULL,
    status          TEXT NOT NULL DEFAULT 'not_applied',
    fit_score       INTEGER,
    strengths       TEXT,
    gaps            TEXT,
    summary_text    TEXT,
    cover_letter    TEXT,
    pdf_path        TEXT,
    hook_project_id TEXT REFERENCES user_projects(id) ON DELETE SET NULL,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE (user_id, job_id)
);
CREATE INDEX IF NOT EXISTS applications_user_id_idx ON applications (user_id);
CREATE INDEX IF NOT EXISTS applications_status_idx  ON applications (user_id, status);
