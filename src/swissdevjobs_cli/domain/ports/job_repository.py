"""Port for the local job cache."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from swissdevjobs_cli.domain.model.job import Job


class JobRepository(Protocol):
    """Caches jobsLight rows and full detail payloads in SQLite."""

    def store_jobs(self, jobs: list[Job]) -> None:
        """Upsert feed rows; a re-listed slug under a new id replaces the old row."""
        ...

    def cached_jobs(self, source: str, max_age_seconds: int = 600) -> list[Job] | None:
        """One board's cached rows if fresh enough, else None."""
        ...

    def store_detail(self, job_id: str, detail_raw: Mapping[str, Any]) -> None:
        """Persist the raw detail payload for one job."""
        ...

    def cached_detail(
        self, job_id: str, max_age_seconds: int = 3600
    ) -> Mapping[str, Any] | None:
        """The raw detail payload if fresh enough, else None."""
        ...

    def count_jobs(self) -> int:
        """How many rows the cache holds (drives first-run auto-migration)."""
        ...
