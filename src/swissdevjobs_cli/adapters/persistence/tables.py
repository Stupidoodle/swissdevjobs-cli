"""The SQLite schema. Idempotent — safe to execute on every startup.

Schema v2 (multi-board): the jobs cache carries a `source` column naming the
board a row came from, `light_json` holding the full normalized wire payload
(the v1 cache reconstructed rows from columns and silently dropped fields
like expLevel), and slug uniqueness is per board — two boards can list the
same slug. The applications table is untouched: it already had `source`, and
it holds real user data that must never be rebuilt.
"""

from __future__ import annotations

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    _id TEXT PRIMARY KEY,
    source TEXT NOT NULL DEFAULT 'swissdevjobs',
    job_url TEXT NOT NULL,
    company TEXT NOT NULL,
    name TEXT NOT NULL,
    actual_city TEXT,
    workplace TEXT,
    language TEXT,
    annual_salary_from INTEGER,
    annual_salary_to INTEGER,
    technologies TEXT,
    filter_tags TEXT,
    candidate_contact_way TEXT,
    email_address TEXT,
    redirect_url TEXT,
    active_from TEXT,
    light_json TEXT,
    detail_json TEXT,
    light_fetched_at TEXT,
    detail_fetched_at TEXT,
    UNIQUE(source, job_url)
);

CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT UNIQUE,
    company TEXT NOT NULL,
    role TEXT NOT NULL,
    method TEXT NOT NULL,
    status TEXT DEFAULT 'submitted',
    source TEXT DEFAULT 'swissdevjobs',
    applied_at TEXT DEFAULT (datetime('now')),
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_apps_company ON applications(company);
CREATE INDEX IF NOT EXISTS idx_apps_job_id ON applications(job_id);
CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company);
CREATE INDEX IF NOT EXISTS idx_jobs_source ON jobs(source);
"""
