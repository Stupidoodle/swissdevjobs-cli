"""First-run migrations: legacy JSON caches and the v1 jobs table."""

from __future__ import annotations

import json
import sqlite3

from conftest import job
from swissdevjobs_cli.adapters.persistence.unit_of_work import SqliteUnitOfWork


def test_a_legacy_json_cache_is_imported_on_first_run(tmp_path):
    (tmp_path / "jobsLight.json").write_text(json.dumps([job()]))
    detail = job(description="from legacy detail")
    (tmp_path / f"job_{job()['_id']}.json").write_text(json.dumps(detail))

    uow = SqliteUnitOfWork(tmp_path / "new.db", tmp_path, tmp_path / "config")
    try:
        cached = uow.jobs.cached_jobs("swissdevjobs", max_age_seconds=10**9)
        assert cached and cached[0].raw["company"] == "Acme AG"
        stored = uow.jobs.cached_detail(job()["_id"], max_age_seconds=10**9)
        assert stored["description"] == "from legacy detail"
    finally:
        uow.close()


def test_a_v1_jobs_table_is_rebuilt_and_applications_survive(tmp_path):
    """The v1→v2 migration drops only the cache; the ledger is sacred."""
    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE jobs (_id TEXT PRIMARY KEY, job_url TEXT UNIQUE NOT NULL,
                           company TEXT NOT NULL, name TEXT NOT NULL);
        CREATE TABLE applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT UNIQUE,
            company TEXT NOT NULL, role TEXT NOT NULL, method TEXT NOT NULL,
            status TEXT DEFAULT 'submitted', source TEXT DEFAULT 'swissdevjobs',
            applied_at TEXT DEFAULT (datetime('now')), notes TEXT);
        INSERT INTO jobs VALUES ('old-id', 'old-slug', 'Old AG', 'Old Role');
        INSERT INTO applications (job_id, company, role, method)
            VALUES ('old-id', 'Old AG', 'Old Role', 'direct');
        """
    )
    conn.commit()
    conn.close()

    uow = SqliteUnitOfWork(db, tmp_path, tmp_path / "config")
    try:
        assert uow.jobs.count_jobs() == 0, "v1 cache rows are dropped"
        record = uow.applications.get_by_job_id("old-id")
        assert record is not None and record.company == "Old AG"
    finally:
        uow.close()
