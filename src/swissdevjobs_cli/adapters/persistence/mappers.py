"""Imperative mapping: sqlite rows ↔ domain objects and wire mappings."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from swissdevjobs_cli.domain.model.application import ApplicationRecord
from swissdevjobs_cli.domain.model.ids import JobId, posted_at_from_object_id
from swissdevjobs_cli.domain.model.job import Job
from swissdevjobs_cli.domain.model.salary import SalaryRange


def row_to_wire(row: sqlite3.Row) -> dict[str, Any]:
    """The cached wire mapping: `light_json` verbatim, or column fallback.

    `light_json` stores the full normalized payload, so a warm cache is no
    longer lossy. The column path remains only as a defensive fallback for a
    row written without it. The decoded `postedAt` comes from the ObjectId —
    the server's `activeFrom` is a re-bump timestamp and changes when the
    board re-promotes a listing.
    """
    stored = row["light_json"]
    if stored:
        return json.loads(stored)
    oid = row["_id"] or ""
    posted_at_unix = posted_at_from_object_id(oid)
    posted_at_iso = (
        datetime.fromtimestamp(posted_at_unix, tz=timezone.utc).isoformat()
        if posted_at_unix is not None
        else None
    )
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
        "activeFrom": (row["active_from"] if "active_from" in row.keys() else None),
        "postedAt": posted_at_iso,
        "postedAtUnix": posted_at_unix,
    }


def row_to_job(row: sqlite3.Row) -> Job:
    """A cached jobs row → domain Job. The row's `source` names its board."""
    from swissdevjobs_cli.adapters.boards.registry import BOARDS, SOURCE_TO_BOARD

    raw = row_to_wire(row)
    board = SOURCE_TO_BOARD.get(row["source"], BOARDS["ch"])
    return Job(
        id=JobId(raw.get("_id") or ""),
        slug=raw.get("jobUrl") or "",
        title=raw.get("name") or "",
        company=raw.get("company") or "",
        city=raw.get("actualCity"),
        salary=SalaryRange.from_wire(raw, currency=board.currency),
        posted_at_unix=raw.get("postedAtUnix"),
        board=board,
        raw=raw,
    )


def job_to_row_params(job: Job, fetched_at: str) -> tuple:
    """A domain Job → the parameter tuple for the jobs upsert."""
    raw = job.raw
    return (
        raw.get("_id"),
        job.board.source,
        raw.get("jobUrl", ""),
        raw.get("company", ""),
        raw.get("name", ""),
        raw.get("actualCity") or raw.get("cityCategory"),
        raw.get("workplace"),
        raw.get("language"),
        raw.get("annualSalaryFrom"),
        raw.get("annualSalaryTo"),
        json.dumps(raw.get("technologies") or []),
        json.dumps(raw.get("filterTags") or []),
        raw.get("candidateContactWay"),
        raw.get("emailAddressForApplications"),
        raw.get("redirectJobUrl"),
        raw.get("activeFrom"),
        json.dumps(raw),
        fetched_at,
    )


def row_to_application(row: sqlite3.Row) -> ApplicationRecord:
    """An applications row → domain ApplicationRecord."""
    return ApplicationRecord(
        id=row["id"],
        job_id=row["job_id"],
        company=row["company"],
        role=row["role"],
        method=row["method"],
        status=row["status"],
        source=row["source"],
        applied_at=row["applied_at"],
        notes=row["notes"],
    )
