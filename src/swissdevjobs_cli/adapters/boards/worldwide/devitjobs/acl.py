"""Anti-corruption layer: devitjobs wire JSON → domain Job / JobDetail.

The devitjobs family (swissdevjobs.ch, germantechjobs.de, devitjobs.*) shares
one backend, so one translation covers every board on the platform. The wire
mapping itself is kept on the model as ``raw`` — it is a frozen public
contract (JSON output, SQLite round-trip) — and this module is the only place
that reads wire field names.

Stdlib-mapped for now; when the first non-family platform lands, pydantic
wire models are the pre-approved replacement (see CLAUDE.md).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from swissdevjobs_cli.domain.model.board import Board
from swissdevjobs_cli.domain.model.ids import JobId, posted_at_from_object_id
from swissdevjobs_cli.domain.model.job import Job, JobDetail
from swissdevjobs_cli.domain.model.salary import SalaryRange


def _decorate_posted_at(wire: dict[str, Any]) -> dict[str, Any]:
    """Add `postedAt` (ISO) and `postedAtUnix` decoded from the MongoDB ObjectId.

    The first 8 hex chars of an ObjectId are a unix epoch (seconds). Unlike
    `activeFrom`, this never changes when the board re-promotes a listing.
    """
    ts = posted_at_from_object_id(wire.get("_id") or "")
    wire["postedAtUnix"] = ts
    wire["postedAt"] = (
        datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        if ts is not None
        else None
    )
    return wire


def job_from_wire(wire: Mapping[str, Any], board: Board) -> Job:
    """One jobsLight row → domain Job. Decorates raw with postedAt + board tags."""
    raw = _decorate_posted_at(dict(wire))
    raw["country"] = board.country
    raw["source"] = board.source
    return Job(
        id=JobId(raw.get("_id") or ""),
        slug=raw.get("jobUrl") or "",
        title=raw.get("name") or "",
        company=raw.get("company") or "",
        city=raw.get("actualCity") or raw.get("cityCategory"),
        salary=SalaryRange.from_wire(raw, currency=board.currency),
        posted_at_unix=raw["postedAtUnix"],
        board=board,
        raw=raw,
    )


def jobs_from_wire(wire_rows: list[Mapping[str, Any]], board: Board) -> list[Job]:
    """The full jobsLight feed → domain Jobs."""
    return [job_from_wire(row, board) for row in wire_rows]


def detail_from_wire(wire: Mapping[str, Any], board: Board) -> JobDetail:
    """A job-detail payload → domain JobDetail. Raw gains only board tags."""
    raw = dict(wire)
    raw["country"] = board.country
    raw["source"] = board.source
    return JobDetail(
        id=JobId(wire.get("_id") or ""),
        slug=wire.get("jobUrl") or "",
        title=wire.get("name") or "",
        company=wire.get("company") or "",
        city=wire.get("actualCity"),
        salary=SalaryRange.from_wire(wire, currency=board.currency),
        language=wire.get("language"),
        contact_way=wire.get("candidateContactWay"),
        apply_email=wire.get("emailAddressForApplications"),
        redirect_url=wire.get("redirectJobUrl"),
        questions=tuple(wire.get("applyQuestions") or ()),
        has_lang_check=bool(wire.get("hasLangCheck", False)),
        board=board,
        raw=raw,
    )


def posting_url(board: Board, slug_or_id: str) -> str:
    """The public URL of a posting on its board."""
    return f"{board.base_url}/jobs/{slug_or_id}"
