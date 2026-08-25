"""Application tracking: dedup checks, recording, listing, stats."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from swissdevjobs_cli.domain.model.application import ApplicationRecord
from swissdevjobs_cli.domain.model.job import Job
from swissdevjobs_cli.domain.ports.unit_of_work import UnitOfWork


def existing_application(uow: UnitOfWork, job_id: str) -> ApplicationRecord | None:
    """The tracked application for a job id, or None."""
    return uow.applications.get_by_job_id(job_id)


def is_job_applied(uow: UnitOfWork, job: Job) -> bool:
    """Whether a job was applied to — by id, or by company+role as fallback.

    The fallback catches applications made outside this tool (LinkedIn, a
    company ATS) that were recorded without a board job id.
    """
    if job.id and uow.applications.get_by_job_id(str(job.id)):
        return True

    company = job.company
    role = job.title
    if company and role and uow.applications.get_by_company_role(company, role):
        return True
    return False


def mark_applied(
    uow: UnitOfWork,
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
    return uow.applications.upsert(
        job_id=job_id,
        company=company,
        role=role,
        method=method,
        status=status,
        notes=notes,
        source=source,
    )


def list_applications(uow: UnitOfWork, limit: int = 100) -> list[ApplicationRecord]:
    """All tracked applications, newest first."""
    return uow.applications.list(limit=limit)


def stats(uow: UnitOfWork) -> dict[str, Any]:
    """Database statistics for `sdj stats`."""
    return uow.stats()


def import_markdown_log(uow: UnitOfWork, path: Path) -> int:
    """Import a legacy applications-log.md into the database."""
    return uow.import_markdown_log(path)
