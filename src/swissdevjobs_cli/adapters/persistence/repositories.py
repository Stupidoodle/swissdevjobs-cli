"""SQLite repositories implementing the domain's persistence ports."""

from __future__ import annotations

import builtins
import sqlite3
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from swissdevjobs_cli.adapters.persistence import mappers
from swissdevjobs_cli.domain.model.application import ApplicationRecord
from swissdevjobs_cli.domain.model.job import Job


class SqliteJobRepository:
    """The jobs cache: lightweight feed rows plus raw detail payloads."""

    def __init__(self, conn: sqlite3.Connection):
        """Share the UoW connection."""
        self._conn = conn

    def store_jobs(self, jobs: list[Job]) -> None:
        """Upsert feed rows; a re-listed slug under a new id replaces the old row."""
        now = datetime.now().isoformat()
        for job in jobs:
            raw = job.raw
            # Defensive: a re-listed posting can reuse the same job_url under a
            # new _id, which trips the UNIQUE(job_url) constraint. Wipe stale
            # row first.
            if raw.get("jobUrl") and raw.get("_id"):
                self._conn.execute(
                    "DELETE FROM jobs WHERE source = ? AND job_url = ? AND _id != ?",
                    (job.board.source, raw.get("jobUrl"), raw.get("_id")),
                )
            self._conn.execute(
                """INSERT INTO jobs (_id, source, job_url, company, name,
                                     actual_city, workplace, language,
                                     annual_salary_from, annual_salary_to,
                                     technologies, filter_tags,
                                     candidate_contact_way, email_address,
                                     redirect_url, active_from, light_json,
                                     light_fetched_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(_id) DO UPDATE SET
                       source = excluded.source,
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
                       light_json = excluded.light_json,
                       light_fetched_at = excluded.light_fetched_at""",
                mappers.job_to_row_params(job, now),
            )
        self._conn.commit()

    def cached_jobs(self, source: str, max_age_seconds: int = 600) -> list[Job] | None:
        """One board's cached rows if fresh enough, else None.

        Freshness is judged per board — a warm CH cache must not make a
        never-fetched DE board look fresh.
        """
        cursor = self._conn.execute(
            "SELECT light_fetched_at FROM jobs WHERE source = ? "
            "ORDER BY light_fetched_at DESC LIMIT 1",
            (source,),
        )
        row = cursor.fetchone()
        if not row or not row["light_fetched_at"]:
            return None

        fetched_at = datetime.fromisoformat(row["light_fetched_at"])
        age = (datetime.now() - fetched_at).total_seconds()
        if age > max_age_seconds:
            return None

        cursor = self._conn.execute("SELECT * FROM jobs WHERE source = ?", (source,))
        return [mappers.row_to_job(r) for r in cursor.fetchall()]

    def store_detail(self, job_id: str, detail_raw: Mapping[str, Any]) -> None:
        """Persist the raw detail payload for one job."""
        import json

        now = datetime.now().isoformat()
        self._conn.execute(
            "UPDATE jobs SET detail_json = ?, detail_fetched_at = ? WHERE _id = ?",
            (json.dumps(detail_raw), now, job_id),
        )
        self._conn.commit()

    def cached_detail(
        self, job_id: str, max_age_seconds: int = 3600
    ) -> dict[str, Any] | None:
        """The raw detail payload if fresh enough, else None."""
        import json

        cursor = self._conn.execute(
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

    def count_jobs(self) -> int:
        """How many rows the cache holds."""
        return self._conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]


class SqliteApplicationRepository:
    """The applications ledger behind every dedup check."""

    def __init__(self, conn: sqlite3.Connection):
        """Share the UoW connection."""
        self._conn = conn

    def get_by_job_id(self, job_id: str) -> ApplicationRecord | None:
        """The application for a job id, or None."""
        cursor = self._conn.execute(
            "SELECT * FROM applications WHERE job_id = ?", (job_id,)
        )
        row = cursor.fetchone()
        return mappers.row_to_application(row) if row else None

    def get_by_company_role(self, company: str, role: str) -> ApplicationRecord | None:
        """Match for jobs applied to outside this tool (no job id known)."""
        cursor = self._conn.execute(
            "SELECT * FROM applications WHERE company = ? AND role = ?",
            (company, role),
        )
        row = cursor.fetchone()
        return mappers.row_to_application(row) if row else None

    def upsert(
        self,
        *,
        job_id: str | None,
        company: str,
        role: str,
        method: str,
        status: str = "submitted",
        notes: str | None = None,
        source: str = "swissdevjobs",
    ) -> ApplicationRecord:
        """Record an application; a duplicate job_id updates in place."""
        now = datetime.now().isoformat()
        cursor = self._conn.execute(
            """INSERT INTO applications
                   (job_id, company, role, method, status, source, applied_at, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(job_id) DO UPDATE SET
                   method = excluded.method,
                   status = excluded.status,
                   notes = excluded.notes,
                   applied_at = excluded.applied_at""",
            (job_id, company, role, method, status, source, now, notes),
        )
        self._conn.commit()
        return ApplicationRecord(
            id=cursor.lastrowid,
            job_id=job_id,
            company=company,
            role=role,
            method=method,
            status=status,
            source=source,
            applied_at=now,
            notes=notes,
        )

    def list(self, limit: int = 100) -> builtins.list[ApplicationRecord]:
        """All applications, newest first."""
        cursor = self._conn.execute(
            "SELECT * FROM applications ORDER BY applied_at DESC LIMIT ?", (limit,)
        )
        return [mappers.row_to_application(r) for r in cursor.fetchall()]

    def applied_company_roles(self) -> set[tuple[str, str]]:
        """Lowercased (company, role) pairs for id-less dedup."""
        cursor = self._conn.execute("SELECT company, role FROM applications")
        return {
            (row["company"].lower(), row["role"].lower()) for row in cursor.fetchall()
        }

    def stats(self) -> dict[str, Any]:
        """Application counters for `sdj stats`."""
        total = self._conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0]
        submitted = self._conn.execute(
            "SELECT COUNT(*) FROM applications WHERE status = 'submitted'"
        ).fetchone()[0]
        return {"applications_total": total, "applications_submitted": submitted}
