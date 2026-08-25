"""First-run migrations: legacy JSON cache files and the markdown application log."""

from __future__ import annotations

import contextlib
import json
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path

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


def import_json_cache(jobs_repo, cache_dir: Path, board) -> int:
    """Import pre-SQLite JSON cache files, via the ACL so rows are normalized."""
    from swissdevjobs_cli.adapters.boards.worldwide.devitjobs import acl

    imported = 0

    jobs_light_path = cache_dir / "jobsLight.json"
    if jobs_light_path.exists():
        try:
            wire = json.loads(jobs_light_path.read_text())
            jobs_repo.store_jobs(acl.jobs_from_wire(wire, board))
            imported += len(wire)
        except Exception:  # noqa: S110 — best-effort migration; a corrupt legacy file must not block startup
            pass

    for path in cache_dir.glob("job_*.json"):
        try:
            detail = json.loads(path.read_text())
            job_id = detail.get("_id")
            if job_id:
                jobs_repo.store_detail(job_id, detail)
        except Exception:  # noqa: S112 — same: skip unreadable legacy files
            continue

    return imported


def find_markdown_log(config_dir: Path) -> Path | None:
    """Locate an applications-log.md: env override, config dir, or cwd."""
    candidates = [
        os.environ.get("SDJ_APPLICATIONS_LOG"),
        config_dir / "applications-log.md",
        Path.cwd() / "applications-log.md",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return Path(candidate)
    return None


def _parse_log_row(line: str) -> tuple | None:
    """One markdown table row → (company, role, job_id, method, applied_at) or None."""
    if not line.startswith("|") or "---" in line or "Company" in line:
        return None
    parts = [p.strip() for p in line.split("|")]
    if len(parts) < 9:
        return None

    # parts[0] is empty (before first |), parts[1] is #
    company = parts[2]
    role = parts[3]
    url = parts[4]
    method_raw = parts[5].lower()
    status = parts[6].lower()
    timestamp = parts[8] if len(parts) > 8 else None

    if "blocked" in status or "pending" in status:
        return None

    # Extract job_id from a swissdevjobs URL like "… (id: abc123)"
    job_id = None
    if "swissdevjobs.ch/jobs/" in url:
        id_match = re.search(r"\(id:\s*([a-f0-9]+)\)", url)
        if id_match:
            job_id = id_match.group(1)

    method = "browser"  # default
    for pattern, mapped in METHOD_MAP.items():
        if pattern in method_raw:
            method = mapped
            break

    applied_at = None
    if timestamp:
        with contextlib.suppress(Exception):
            applied_at = datetime.strptime(timestamp.strip(), "%Y-%m-%d").isoformat()

    return (company, role, job_id, method, applied_at)


def _insert_if_new(conn: sqlite3.Connection, row: tuple) -> bool:
    """Insert one parsed application unless an equivalent record exists."""
    company, role, job_id, method, applied_at = row
    if job_id:
        cursor = conn.execute("SELECT id FROM applications WHERE job_id = ?", (job_id,))
    else:
        cursor = conn.execute(
            "SELECT id FROM applications WHERE company = ? AND role = ?",
            (company, role),
        )
    if cursor.fetchone():
        return False  # Already imported

    conn.execute(
        """INSERT INTO applications
           (job_id, company, role, method, status, applied_at)
           VALUES (?, ?, ?, ?, 'submitted', ?)""",
        (job_id, company, role, method, applied_at),
    )
    return True


def import_markdown_log(conn: sqlite3.Connection, path: Path) -> int:
    """Parse and import applications-log.md into the applications table.

    Format: | # | Company | Role | URL | Method | Status | Escalated | Timestamp |
    Blocked/pending rows are skipped — they were never actually submitted.
    """
    imported = 0

    try:
        content = path.read_text()
    except Exception:
        return 0

    for line in content.split("\n"):
        try:
            row = _parse_log_row(line)
            if row is None:
                continue
            try:
                if _insert_if_new(conn, row):
                    imported += 1
            except sqlite3.IntegrityError:
                pass
        except Exception:  # noqa: S112 — a malformed table row must not abort the import
            continue

    conn.commit()
    return imported
