"""Job filtering and ranking helpers."""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def _lower_set(xs: Iterable[str]) -> set[str]:
    return {str(x).lower() for x in xs if x}


def matches(
    job: dict[str, Any],
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
    tags = _lower_set(job.get("filterTags", []) + job.get("technologies", []))

    if tech:
        wanted = _lower_set(tech)
        hit = tags & wanted
        if tech_any and not hit:
            return False
        if not tech_any and hit != wanted:
            return False

    if location:
        loc = location.lower()
        if loc not in (job.get("cityCategory", "") + " " + job.get("actualCity", "")).lower():
            return False

    if remote is True and job.get("workplace") not in ("remote", "hybrid"):
        return False
    if remote is False and job.get("workplace") == "remote":
        return False

    if visa is True and job.get("hasVisaSponsorship") != "Yes":
        return False

    if level and job.get("expLevel", "").lower() != level.lower():
        return False

    if language and job.get("language", "").lower() != language.lower():
        return False

    if min_salary is not None and (job.get("annualSalaryTo") or 0) < min_salary:
        return False
    if max_salary is not None and (job.get("annualSalaryFrom") or 10**9) > max_salary:
        return False

    if company and company.lower() not in (job.get("company", "") or "").lower():
        return False

    if query:
        q = query.lower()
        hay = " ".join(
            str(job.get(k, "") or "")
            for k in ("name", "company", "actualCity", "techCategory")
        ) + " " + " ".join(tags)
        if q not in hay.lower():
            return False

    return True


def _posted_at_from_id(job: dict[str, Any]) -> int:
    """Decode the MongoDB ObjectId timestamp (first 8 hex chars = unix epoch seconds).

    `activeFrom` is unreliable as a posting date — SwissDevJobs re-stamps it
    when they bump a listing back to the top. The ObjectId encodes the real
    creation time and never changes.
    """
    oid = job.get("_id") or ""
    try:
        return int(oid[:8], 16)
    except (ValueError, TypeError):
        return 0


def sort_key(job: dict[str, Any], *, by: str):
    if by == "salary":
        return -(job.get("annualSalaryTo") or job.get("annualSalaryFrom") or 0)
    if by == "date":
        # Newest first by `activeFrom` (when SwissDevJobs last bumped it).
        return -_iso_to_epoch(job.get("activeFrom") or "")
    if by == "posted":
        # Newest first by true posting time, decoded from the ObjectId.
        return -_posted_at_from_id(job)
    if by == "company":
        return (job.get("company") or "").lower()
    return 0


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
