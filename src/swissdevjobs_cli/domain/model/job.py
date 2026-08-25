"""Job and JobDetail: a posting as the domain sees it.

Both carry ``raw`` — the board's wire payload after ACL normalization. The
wire shape is a frozen public contract (``sdj list --json`` prints it, the
SQLite cache round-trips it), so anything that renders output reads ``raw``,
while typed fields exist for the logic that filters, sorts, and identifies.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from swissdevjobs_cli.domain.model.ids import JobId
from swissdevjobs_cli.domain.model.salary import SalaryRange


def strip_html(text: str) -> str:
    """Flatten the HTML the API returns in description/requirement fields."""
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</p>", "\n\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


@dataclass(frozen=True)
class Job:
    """One row of a board's jobsLight feed."""

    id: JobId
    slug: str
    title: str
    company: str
    city: str | None
    salary: SalaryRange
    posted_at_unix: int | None
    raw: Mapping[str, Any]


@dataclass(frozen=True)
class JobDetail:
    """The full posting, as returned by the board's detail endpoint."""

    id: JobId
    slug: str
    title: str
    company: str
    city: str | None
    salary: SalaryRange
    language: str | None
    contact_way: str | None
    apply_email: str | None
    redirect_url: str | None
    questions: tuple[Any, ...]
    has_lang_check: bool
    raw: Mapping[str, Any]
