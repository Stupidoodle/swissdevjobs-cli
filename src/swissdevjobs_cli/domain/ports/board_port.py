"""The port every job-board adapter implements."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from swissdevjobs_cli.domain.model.application import Applicant
from swissdevjobs_cli.domain.model.board import Board
from swissdevjobs_cli.domain.model.job import Job, JobDetail


class BoardPort(Protocol):
    """Fetches postings from one board and submits native applications.

    The port owns every wire-shape concern for its board: fetching, cached-
    payload rehydration, and public URLs all go through it so nothing outside
    the adapter ever reads platform-specific field names.
    """

    board: Board

    def fetch_jobs(
        self,
        *,
        query: str | None = None,
        category: str | None = None,
        force: bool = False,
    ) -> list[Job]:
        """Postings, ACL-normalized to domain Jobs.

        Feed boards return their full lightweight feed and may ignore
        ``query`` (the service layer filters client-side); search-driven
        boards pass it to the server and return the matching slice — without
        a query, their newest postings. ``category`` is an alias ("it") each
        board resolves against its own taxonomy; all-inventory boards use it
        to narrow, single-industry boards ignore it.
        """
        ...

    def fetch_detail(self, job_id: str) -> JobDetail:
        """The full posting for one job id."""
        ...

    def hydrate_detail(self, raw: Mapping[str, Any]) -> JobDetail:
        """A cached raw detail payload → domain JobDetail, via this board's ACL."""
        ...

    def posting_url(self, raw: Mapping[str, Any]) -> str:
        """The public URL of a posting, from its raw wire mapping."""
        ...

    def submit_application(
        self, detail: JobDetail, applicant: Applicant, motivation: str
    ) -> dict[str, Any]:
        """POST the board's native apply form. Returns {"status", "response"}."""
        ...
