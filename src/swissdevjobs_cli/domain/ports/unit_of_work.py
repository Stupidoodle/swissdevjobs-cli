"""The unit-of-work port: one transactional scope over both repositories."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from swissdevjobs_cli.domain.ports.application_repository import ApplicationRepository
from swissdevjobs_cli.domain.ports.job_repository import JobRepository


class UnitOfWork(Protocol):
    """Owns the connection; repositories share its transaction."""

    @property
    def jobs(self) -> JobRepository:
        """The jobs cache repository."""
        ...

    @property
    def applications(self) -> ApplicationRepository:
        """The applications repository."""
        ...

    def commit(self) -> None:
        """Flush pending writes."""
        ...

    def stats(self) -> dict[str, Any]:
        """Database statistics across both repositories."""
        ...

    def import_markdown_log(self, path: Path) -> int:
        """Import a legacy applications-log.md; returns rows imported."""
        ...
