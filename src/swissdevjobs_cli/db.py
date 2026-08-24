"""SQLite persistence for jobs cache and application tracking.

Agent-first design:
- Auto-migration on first access (JSON cache + markdown log)
- Deduplication returns data, not errors
- All operations return dicts for JSON serialization
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

# Use same dirs as api.py
CACHE_DIR = Path(os.environ.get("SDJ_CACHE_DIR", Path.home() / ".cache" / "swissdevjobs-cli"))
CONFIG_DIR = Path(os.environ.get("SDJ_CONFIG_DIR", Path.home() / ".config" / "swissdevjobs-cli"))
DB_PATH = CACHE_DIR / "swissdevjobs.db"

_conn: sqlite3.Connection | None = None
_initialized = False

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

# Method mapping for markdown import
METHOD_MAP = {
    "swissdevjobs (direct)": "direct",
    "sdj direct": "direct",
    "direct": "direct",
    "email": "email",
    "linkedin easy apply": "linkedin",
    "linkedin": "linkedin",
    "lever": "browser",
    "lever (direct ats)": "browser",
    "workday": "browser",
    "workday (direct ats)": "browser",
    "personio": "browser",
    "personio (direct ats)": "browser",
    "personio ats": "browser",
    "teamtailor": "browser",
    "teamtailor ats": "browser",
    "bamboohr": "browser",
    "bamboohr (direct ats)": "browser",
    "join.com": "browser",
    "join.com (direct ats)": "browser",
    "successfactors": "browser",
    "career page": "browser",
    "direct ats": "browser",
    "direct (user-applied)": "browser",
    "email (cv resend)": "email",
}


def get_db() -> sqlite3.Connection:
    """Get or create database connection (singleton)."""
    global _conn
    if _conn is None:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
    return _conn


def _ensure_db() -> None:
    """Initialize database and run auto-migration if needed."""
    global _initialized
    if _initialized:
        return

    conn = get_db()
    conn.executescript(SCHEMA)
    # Schema migration: add active_from column to pre-existing DBs.
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
    if "active_from" not in cols:
        conn.execute("ALTER TABLE jobs ADD COLUMN active_from TEXT")
    conn.commit()

    # Auto-migrate if DB was just created (no data yet)
    cursor = conn.execute("SELECT COUNT(*) FROM jobs")
    job_count = cursor.fetchone()[0]

    if job_count == 0:
        _auto_migrate_json_cache()
        _auto_migrate_markdown_log()

    _initialized = True


def _auto_migrate_json_cache() -> int:
    """Import existing JSON cache files into SQLite."""
    imported = 0

    # Import jobsLight.json
    jobs_light_path = CACHE_DIR / "jobsLight.json"
    if jobs_light_path.exists():
        try:
            jobs = json.loads(jobs_light_path.read_text())
            upsert_jobs_light(jobs)
            imported += len(jobs)
        except Exception:
            pass

    # Import individual job detail files
    for path in CACHE_DIR.glob("job_*.json"):
        try:
            detail = json.loads(path.read_text())
            job_id = detail.get("_id")
            if job_id:
                upsert_job_detail(job_id, detail)
        except Exception:
            pass

    return imported


def _auto_migrate_markdown_log() -> int:
    """Auto-detect and import applications-log.md."""
    # Opt-in only: set SDJ_APPLICATIONS_LOG, or drop the file in the config dir.
    candidates = [
        os.environ.get("SDJ_APPLICATIONS_LOG"),
        CONFIG_DIR / "applications-log.md",
        Path.cwd() / "applications-log.md",
    ]

    for path in candidates:
        if path and Path(path).exists():
            return import_markdown_log(Path(path))

    return 0


def import_markdown_log(path: Path) -> int:
    """Parse and import applications-log.md into database."""
    conn = get_db()
    imported = 0

    try:
        content = path.read_text()
    except Exception:
        return 0

    # Parse markdown table rows
    # Format: | # | Company | Role | URL | Method | Status | Escalated | Timestamp |
    for line in content.split("\n"):
        if not line.startswith("|"):
            continue
        if "---" in line or "Company" in line:
            continue

        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 9:
            continue

        try:
            # parts[0] is empty (before first |), parts[1] is #
            company = parts[2]
            role = parts[3]
            url = parts[4]
            method_raw = parts[5].lower()
            status = parts[6].lower()
            timestamp = parts[8] if len(parts) > 8 else None

            # Skip blocked/pending entries
            if "blocked" in status or "pending" in status:
                continue

            # Extract job_id from swissdevjobs URL
            job_id = None
            if "swissdevjobs.ch/jobs/" in url:
                # Try to find job_id in parentheses like (id: abc123)
                id_match = re.search(r"\(id:\s*([a-f0-9]+)\)", url)
                if id_match:
                    job_id = id_match.group(1)

            # Map method
            method = "browser"  # default
            for pattern, mapped in METHOD_MAP.items():
                if pattern in method_raw:
                    method = mapped
                    break

            # Parse timestamp
            applied_at = None
            if timestamp:
                with contextlib.suppress(Exception):
                    applied_at = datetime.strptime(timestamp.strip(), "%Y-%m-%d").isoformat()

            # Insert (skip duplicates - check by company+role if no job_id)
            try:
                # Check if already exists
                if job_id:
                    cursor = conn.execute(
                        "SELECT id FROM applications WHERE job_id = ?", (job_id,)
                    )
                else:
                    cursor = conn.execute(
                        "SELECT id FROM applications WHERE company = ? AND role = ?",
                        (company, role),
                    )
                if cursor.fetchone():
                    continue  # Already imported

                conn.execute(
                    """INSERT INTO applications
                       (job_id, company, role, method, status, applied_at)
                       VALUES (?, ?, ?, ?, 'submitted', ?)""",
                    (job_id, company, role, method, applied_at),
                )
                imported += 1
            except sqlite3.IntegrityError:
                pass

        except Exception:
            continue

    conn.commit()
    return imported


# --- Jobs Cache Operations ---


def upsert_jobs_light(jobs: list[dict[str, Any]]) -> None:
    """Batch insert/update jobs from /api/jobsLight."""
    _ensure_db()
    conn = get_db()
    now = datetime.now().isoformat()

    for j in jobs:
        # Defensive: a re-listed posting can reuse the same job_url under a new _id,
        # which trips the UNIQUE(job_url) constraint. Wipe stale row first.
        if j.get("jobUrl") and j.get("_id"):
            conn.execute("DELETE FROM jobs WHERE job_url = ? AND _id != ?", (j.get("jobUrl"), j.get("_id")))
        conn.execute(
            """INSERT INTO jobs (_id, job_url, company, name, actual_city, workplace,
                                 language, annual_salary_from, annual_salary_to,
                                 technologies, filter_tags, candidate_contact_way,
                                 email_address, redirect_url, active_from, light_fetched_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(_id) DO UPDATE SET
                   job_url = excluded.job_url,
                   company = excluded.company,
                   name = excluded.name,
                   actual_city = excluded.actual_city,
                   workplace = excluded.workplace,
                   language = excluded.language,
                   annual_salary_from = excluded.annual_salary_from,
                   annual_salary_to = excluded.annual_salary_to,
                   technologies = excluded.technologies,
                   filter_tags = excluded.filter_tags,
                   candidate_contact_way = excluded.candidate_contact_way,
                   email_address = excluded.email_address,
                   redirect_url = excluded.redirect_url,
                   active_from = excluded.active_from,
                   light_fetched_at = excluded.light_fetched_at""",
            (
                j.get("_id"),
                j.get("jobUrl", ""),
                j.get("company", ""),
                j.get("name", ""),
                j.get("actualCity") or j.get("cityCategory"),
                j.get("workplace"),
                j.get("language"),
                j.get("annualSalaryFrom"),
                j.get("annualSalaryTo"),
                json.dumps(j.get("technologies") or []),
                json.dumps(j.get("filterTags") or []),
                j.get("candidateContactWay"),
                j.get("emailAddressForApplications"),
                j.get("redirectJobUrl"),
                j.get("activeFrom"),
                now,
            ),
        )
    conn.commit()


def get_cached_jobs(max_age_seconds: int = 600) -> list[dict[str, Any]] | None:
    """Get cached jobs if fresh enough, else None."""
    _ensure_db()
    conn = get_db()

    # Check freshness of any job
    cursor = conn.execute(
        "SELECT light_fetched_at FROM jobs ORDER BY light_fetched_at DESC LIMIT 1"
    )
    row = cursor.fetchone()
    if not row or not row["light_fetched_at"]:
        return None

    fetched_at = datetime.fromisoformat(row["light_fetched_at"])
    age = (datetime.now() - fetched_at).total_seconds()
    if age > max_age_seconds:
        return None

    # Return all jobs
    cursor = conn.execute("SELECT * FROM jobs")
    jobs = []
    for row in cursor.fetchall():
        jobs.append(_row_to_job_dict(row))
    return jobs


def _row_to_job_dict(row: sqlite3.Row) -> dict[str, Any]:
    """Convert SQLite row back to API-compatible dict."""
    # Decode the MongoDB ObjectId for a real (immutable) posted_at — the
    # server's `activeFrom` is a re-bump timestamp and changes when SDJ
    # re-promotes a listing.
    oid = row["_id"] or ""
    posted_at_unix = None
    posted_at_iso = None
    try:
        posted_at_unix = int(oid[:8], 16)
        from datetime import datetime, timezone
        posted_at_iso = datetime.fromtimestamp(posted_at_unix, tz=timezone.utc).isoformat()
    except (ValueError, TypeError):
        pass
    return {
        "_id": row["_id"],
        "jobUrl": row["job_url"],
        "company": row["company"],
        "name": row["name"],
        "actualCity": row["actual_city"],
        "workplace": row["workplace"],
        "language": row["language"],
        "annualSalaryFrom": row["annual_salary_from"],
        "annualSalaryTo": row["annual_salary_to"],
        "technologies": json.loads(row["technologies"] or "[]"),
        "filterTags": json.loads(row["filter_tags"] or "[]"),
        "candidateContactWay": row["candidate_contact_way"],
        "emailAddressForApplications": row["email_address"],
        "redirectJobUrl": row["redirect_url"],
        # `in row` would search sqlite3.Row *values*; .keys() is required here.
        "activeFrom": (row["active_from"] if "active_from" in row.keys() else None),  # noqa: SIM118
        "postedAt": posted_at_iso,
        "postedAtUnix": posted_at_unix,
    }


def upsert_job_detail(job_id: str, detail: dict[str, Any]) -> None:
    """Store full job detail."""
    _ensure_db()
    conn = get_db()
    now = datetime.now().isoformat()

    # Store the full JSON blob for fields we don't normalize
    conn.execute(
        """UPDATE jobs SET detail_json = ?, detail_fetched_at = ? WHERE _id = ?""",
        (json.dumps(detail), now, job_id),
    )
    conn.commit()


def get_cached_detail(job_id: str, max_age_seconds: int = 3600) -> dict[str, Any] | None:
    """Get cached job detail if fresh enough."""
    _ensure_db()
    conn = get_db()

    cursor = conn.execute(
        "SELECT detail_json, detail_fetched_at FROM jobs WHERE _id = ?", (job_id,)
    )
    row = cursor.fetchone()
    if not row or not row["detail_json"] or not row["detail_fetched_at"]:
        return None

    fetched_at = datetime.fromisoformat(row["detail_fetched_at"])
    age = (datetime.now() - fetched_at).total_seconds()
    if age > max_age_seconds:
        return None

    return json.loads(row["detail_json"])


# --- Applications Operations ---


def is_applied(job_id: str) -> dict[str, Any] | None:
    """Check if job has been applied to. Returns application record or None."""
    _ensure_db()
    conn = get_db()

    cursor = conn.execute(
        "SELECT * FROM applications WHERE job_id = ?", (job_id,)
    )
    row = cursor.fetchone()
    if not row:
        return None

    return {
        "id": row["id"],
        "job_id": row["job_id"],
        "company": row["company"],
        "role": row["role"],
        "method": row["method"],
        "status": row["status"],
        "source": row["source"],
        "applied_at": row["applied_at"],
        "notes": row["notes"],
    }


def is_applied_by_company_role(company: str, role: str) -> dict[str, Any] | None:
    """Check by company+role (for external jobs without job_id)."""
    _ensure_db()
    conn = get_db()

    cursor = conn.execute(
        "SELECT * FROM applications WHERE company = ? AND role = ?",
        (company, role),
    )
    row = cursor.fetchone()
    if not row:
        return None

    return {
        "id": row["id"],
        "job_id": row["job_id"],
        "company": row["company"],
        "role": row["role"],
        "method": row["method"],
        "status": row["status"],
        "source": row["source"],
        "applied_at": row["applied_at"],
        "notes": row["notes"],
    }


def mark_applied(
    job_id: str | None,
    company: str,
    role: str,
    method: str,
    status: str = "submitted",
    notes: str | None = None,
    source: str = "swissdevjobs",
) -> dict[str, Any]:
    """Mark a job as applied. Returns the application record."""
    _ensure_db()
    conn = get_db()
    now = datetime.now().isoformat()

    cursor = conn.execute(
        """INSERT INTO applications (job_id, company, role, method, status, source, applied_at, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(job_id) DO UPDATE SET
               method = excluded.method,
               status = excluded.status,
               notes = excluded.notes,
               applied_at = excluded.applied_at""",
        (job_id, company, role, method, status, source, now, notes),
    )
    conn.commit()

    return {
        "id": cursor.lastrowid,
        "job_id": job_id,
        "company": company,
        "role": role,
        "method": method,
        "status": status,
        "source": source,
        "applied_at": now,
        "notes": notes,
    }


def list_applications(limit: int = 100) -> list[dict[str, Any]]:
    """List all applications."""
    _ensure_db()
    conn = get_db()

    cursor = conn.execute(
        "SELECT * FROM applications ORDER BY applied_at DESC LIMIT ?", (limit,)
    )

    apps = []
    for row in cursor.fetchall():
        apps.append({
            "id": row["id"],
            "job_id": row["job_id"],
            "company": row["company"],
            "role": row["role"],
            "method": row["method"],
            "status": row["status"],
            "source": row["source"],
            "applied_at": row["applied_at"],
            "notes": row["notes"],
        })
    return apps


def get_applied_job_ids() -> set[str]:
    """Get set of all applied job IDs (for filtering)."""
    _ensure_db()
    conn = get_db()

    cursor = conn.execute("SELECT job_id FROM applications WHERE job_id IS NOT NULL")
    return {row["job_id"] for row in cursor.fetchall()}


def get_applied_companies_roles() -> set[tuple[str, str]]:
    """Get set of (company, role) tuples for filtering when job_id is missing."""
    _ensure_db()
    conn = get_db()

    cursor = conn.execute("SELECT company, role FROM applications")
    return {(row["company"].lower(), row["role"].lower()) for row in cursor.fetchall()}


def is_job_applied(job: dict) -> bool:
    """Check if a job has been applied to (by ID or company+role)."""
    job_id = job.get("_id")
    if job_id:
        existing = is_applied(job_id)
        if existing:
            return True

    # Fallback: check by company+role
    company = (job.get("company") or "").lower()
    role = (job.get("name") or "").lower()
    if company and role:
        existing = is_applied_by_company_role(job.get("company", ""), job.get("name", ""))
        if existing:
            return True

    return False


def get_stats() -> dict[str, Any]:
    """Get database statistics."""
    _ensure_db()
    conn = get_db()

    jobs_count = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    jobs_with_detail = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE detail_json IS NOT NULL"
    ).fetchone()[0]
    apps_count = conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0]
    apps_submitted = conn.execute(
        "SELECT COUNT(*) FROM applications WHERE status = 'submitted'"
    ).fetchone()[0]

    return {
        "jobs_cached": jobs_count,
        "jobs_with_detail": jobs_with_detail,
        "applications_total": apps_count,
        "applications_submitted": apps_submitted,
        "db_path": str(DB_PATH),
    }
