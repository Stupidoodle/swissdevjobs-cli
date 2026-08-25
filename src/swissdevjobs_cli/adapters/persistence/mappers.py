"""Imperative mapping: sqlite rows ↔ domain objects and wire mappings."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from swissdevjobs_cli.domain.model.application import ApplicationRecord
from swissdevjobs_cli.domain.model.board import Board
from swissdevjobs_cli.domain.model.ids import JobId, posted_at_from_object_id
from swissdevjobs_cli.domain.model.job import Job
from swissdevjobs_cli.domain.model.salary import SalaryRange


def row_to_wire(row: sqlite3.Row) -> dict[str, Any]:
    """Reconstruct the API-compatible wire mapping from cached columns.

    The reconstruction is lossy: columns exist only for the fields the tool
    filters and renders (a warm cache therefore lacks e.g. `expLevel`). The
    decoded `postedAt` comes from the ObjectId — the server's `activeFrom` is
    a re-bump timestamp and changes when the board re-promotes a listing.
    """
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


def row_to_job(row: sqlite3.Row, board: Board) -> Job:
    """A cached jobs row → domain Job."""
    raw = row_to_wire(row)
    return Job(
        id=JobId(raw["_id"] or ""),
        slug=raw["jobUrl"] or "",
        title=raw["name"] or "",
        company=raw["company"] or "",
        city=raw["actualCity"],
        salary=SalaryRange.from_wire(raw, currency=board.currency),
        posted_at_unix=raw["postedAtUnix"],
        raw=raw,
    )


def job_to_row_params(job: Job, fetched_at: str) -> tuple:
    """A domain Job → the parameter tuple for the jobs upsert."""
    raw = job.raw
    return (
        raw.get("_id"),
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
