"""The concrete SQLite unit of work: connection, schema, first-run migration."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from swissdevjobs_cli.adapters.persistence import legacy_import
from swissdevjobs_cli.adapters.persistence.repositories import (
    SqliteApplicationRepository,
    SqliteJobRepository,
)
from swissdevjobs_cli.adapters.persistence.tables import SCHEMA


class SqliteUnitOfWork:
    """Owns the connection and hands out repositories sharing it.

    The connection is created lazily on first repository access; the schema is
    applied idempotently, a pre-`active_from` database is migrated in place,
    and — only when the jobs table is empty — legacy JSON cache files and an
    applications-log.md are imported.
    """

    def __init__(self, db_path: Path, cache_dir: Path, config_dir: Path):
        """Remember filesystem locations; connect lazily on first use."""
        self.db_path = db_path
        self._cache_dir = cache_dir
        self._config_dir = config_dir
        self._conn: sqlite3.Connection | None = None
        self._jobs: SqliteJobRepository | None = None
        self._applications: SqliteApplicationRepository | None = None

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._initialize(self._conn)
        return self._conn

    def _initialize(self, conn: sqlite3.Connection) -> None:
        # v1 → v2 migration: the jobs table gained `source`, `light_json`, and
        # per-board slug uniqueness. It is a pure cache, so the cheapest safe
        # migration is to drop and refetch — applications are NOT touched.
        cols = {
            row["name"] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()
        }
        if cols and "source" not in cols:
            conn.execute("DROP TABLE jobs")
        conn.executescript(SCHEMA)
        conn.commit()

        # Auto-migrate only when the database holds no jobs yet.
        job_count = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        if job_count == 0:
            self._jobs = SqliteJobRepository(conn)
            legacy_import.import_json_cache(self._jobs, self._cache_dir)
            log = legacy_import.find_markdown_log(self._config_dir)
            if log is not None:
                legacy_import.import_markdown_log(conn, log)

    @property
    def jobs(self) -> SqliteJobRepository:
        """The jobs cache repository."""
        conn = self._connect()
        if self._jobs is None:
            self._jobs = SqliteJobRepository(conn)
        return self._jobs

    @property
    def applications(self) -> SqliteApplicationRepository:
        """The applications repository."""
        conn = self._connect()
        if self._applications is None:
            self._applications = SqliteApplicationRepository(conn)
        return self._applications

    def commit(self) -> None:
        """Flush pending writes."""
        if self._conn is not None:
            self._conn.commit()

    def close(self) -> None:
        """Close the connection (tests use this; the CLI just exits)."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None
            self._jobs = None
            self._applications = None

    def import_markdown_log(self, path: Path) -> int:
        """Public entry point: import an applications-log.md right now."""
        return legacy_import.import_markdown_log(self._connect(), path)

    def stats(self) -> dict[str, Any]:
        """Database statistics for `sdj stats`."""
        conn = self._connect()
        jobs_count = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        jobs_with_detail = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE detail_json IS NOT NULL"
        ).fetchone()[0]
        app_stats = self.applications.stats()
        return {
            "jobs_cached": jobs_count,
            "jobs_with_detail": jobs_with_detail,
            "applications_total": app_stats["applications_total"],
            "applications_submitted": app_stats["applications_submitted"],
            "db_path": str(self.db_path),
        }
