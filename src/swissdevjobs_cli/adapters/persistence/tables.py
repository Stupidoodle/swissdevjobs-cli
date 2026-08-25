"""The SQLite schema. Idempotent — safe to execute on every startup."""

from __future__ import annotations

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    _id TEXT PRIMARY KEY,
    job_url TEXT UNIQUE NOT NULL,
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
    detail_json TEXT,
    light_fetched_at TEXT,
    detail_fetched_at TEXT
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
"""
