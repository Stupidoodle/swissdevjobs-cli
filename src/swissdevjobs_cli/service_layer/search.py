"""Searching, filtering, sorting, and resolving jobs across the cache and feed."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from typing import Any

from swissdevjobs_cli.adapters.boards.worldwide.devitjobs import acl
from swissdevjobs_cli.domain.model.job import Job, JobDetail
from swissdevjobs_cli.domain.ports.board_port import BoardPort
from swissdevjobs_cli.domain.ports.unit_of_work import UnitOfWork


def list_jobs(
    uow: UnitOfWork,
    board: BoardPort,
    *,
    max_age_seconds: int = 600,
    force: bool = False,
) -> list[Job]:
    """The board's feed, served from the cache when fresh enough."""
    if not force:
        cached = uow.jobs.cached_jobs(max_age_seconds)
        if cached is not None:
            return cached

    jobs = board.fetch_jobs(force=force)
    uow.jobs.store_jobs(jobs)
    return jobs


def get_detail(
    uow: UnitOfWork,
    board: BoardPort,
    job_id: str,
    *,
    max_age_seconds: int = 3600,
    force: bool = False,
) -> JobDetail:
    """The full posting, served from the cache when fresh enough."""
    if not force:
        cached = uow.jobs.cached_detail(job_id, max_age_seconds)
        if cached is not None:
            return acl.detail_from_wire(cached, board.board)

    detail = board.fetch_detail(job_id)
    uow.jobs.store_detail(job_id, dict(detail.raw))
    return detail


def resolve(jobs: list[Job], query: str) -> Job | None:
    """Find one job by id, exact slug, or slug/title substring."""
    q = query.lower()
    for j in jobs:
        if j.id == query or j.slug.lower() == q:
            return j
    for j in jobs:
        if q in j.slug.lower() or q in j.title.lower():
            return j
    return None


def _lower_set(xs: Iterable[str]) -> set:
    return {str(x).lower() for x in xs if x}


def _tech_ok(tags: set, tech: list[str] | None, tech_any: bool) -> bool:
    if not tech:
        return True
    wanted = _lower_set(tech)
    hit = tags & wanted
    if tech_any:
        return bool(hit)
    return hit == wanted


def _location_ok(raw: Mapping[str, Any], location: str | None) -> bool:
    if not location:
        return True
    hay = (
        (raw.get("cityCategory") or "") + " " + (raw.get("actualCity") or "")
    ).lower()
    return location.lower() in hay


def _workplace_ok(raw: Mapping[str, Any], remote: bool | None) -> bool:
    if remote is True and raw.get("workplace") not in ("remote", "hybrid"):
        return False
    return not (remote is False and raw.get("workplace") == "remote")


def _salary_ok(
    raw: Mapping[str, Any], min_salary: int | None, max_salary: int | None
) -> bool:
    if min_salary is not None and (raw.get("annualSalaryTo") or 0) < min_salary:
        return False
    return not (
        max_salary is not None and (raw.get("annualSalaryFrom") or 10**9) > max_salary
    )


def _query_ok(raw: Mapping[str, Any], tags: set, query: str | None) -> bool:
    if not query:
        return True
    hay = (
        " ".join(
            str(raw.get(k, "") or "")
            for k in ("name", "company", "actualCity", "techCategory")
        )
        + " "
        + " ".join(tags)
    )
    return query.lower() in hay.lower()


def matches(
    job: Job,
    *,
    tech: list[str] | None = None,
    tech_any: bool = True,
    location: str | None = None,
    remote: bool | None = None,
    visa: bool | None = None,
    level: str | None = None,
    min_salary: int | None = None,
    max_salary: int | None = None,
    language: str | None = None,
    query: str | None = None,
    company: str | None = None,
) -> bool:
    """Apply every requested filter; filters combine as AND.

    Reads the normalized wire mapping (`job.raw`) — the ACL guarantees these
    keys for every board of the platform, and the wire shape is the frozen
    contract the JSON output and cache round-trip share.
    """
    raw: Mapping[str, Any] = job.raw
    tags = _lower_set(
        list(raw.get("filterTags") or []) + list(raw.get("technologies") or [])
    )

    if not _tech_ok(tags, tech, tech_any):
        return False
    if not _location_ok(raw, location):
        return False
    if not _workplace_ok(raw, remote):
        return False
    if visa is True and raw.get("hasVisaSponsorship") != "Yes":
        return False
    if level and (raw.get("expLevel") or "").lower() != level.lower():
        return False
    if language and (raw.get("language") or "").lower() != language.lower():
        return False
    if not _salary_ok(raw, min_salary, max_salary):
        return False
    if company and company.lower() not in (raw.get("company") or "").lower():
        return False
    return _query_ok(raw, tags, query)


def _iso_to_epoch(iso: str) -> int:
    """Parse an ISO-8601-ish timestamp to unix seconds. Empty / unparseable → 0."""
    if not iso:
        return 0
    from datetime import datetime

    try:
        # Strip trailing 'Z' or timezone offset; MongoDB-style strings vary.
        s = iso.replace("Z", "+00:00")
        return int(datetime.fromisoformat(s).timestamp())
    except Exception:
        return 0


def sort_key(job: Job, *, by: str):
    """Sort key for one job. `posted` uses the immutable ObjectId timestamp."""
    raw = job.raw
    if by == "salary":
        return -(raw.get("annualSalaryTo") or raw.get("annualSalaryFrom") or 0)
    if by == "date":
        # Newest first by `activeFrom` (when the board last bumped it).
        return -_iso_to_epoch(raw.get("activeFrom") or "")
    if by == "posted":
        # Newest first by true posting time, decoded from the ObjectId.
        return -(job.posted_at_unix or 0)
    if by == "company":
        return job.company.lower()
    return 0


def top_technologies(jobs: list[Job], limit: int) -> list[tuple]:
    """The most-tagged technologies across the current feed."""
    counter: Counter = Counter()
    for job in jobs:
        for tag in job.raw.get("filterTags") or []:
            counter[tag] += 1
    return counter.most_common(limit)
